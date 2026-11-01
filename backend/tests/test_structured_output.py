"""Reliability Phase 2: schema-valid output from every provider.

Covers the shared strict schema, the request each provider is sent (Anthropic
``output_config.format``, OpenAI-style ``response_format``, Ollama's native
``format`` + ``num_ctx``), the one-pass parser for API adapters, dropping
unknown keys before validation, prompt sizing to the context window, and the
model-picker filters. No network: every client is a fake.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("YUBEN_DATA_DIR", tempfile.mkdtemp(prefix="yuben-structured-"))

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import jsonschema  # noqa: E402
import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app.adapters import direct_anthropic as direct_mod  # noqa: E402
from app.adapters import get_adapter  # noqa: E402
from app.adapters import openai_compatible as oai  # noqa: E402
from app.adapters.base import KIND_MODEL_NOT_FOUND, AdapterError, OutputTruncated  # noqa: E402
from app.adapters.structured import (  # noqa: E402
    AGENT_RESULT_SCHEMA_NAME,
    PROBE_SCHEMA,
    agent_result_schema,
    prune_unknown_keys,
    strict_schema,
)
from app.orchestrator import runner as _runner  # noqa: E402
from app.orchestrator.parse import parse_json_text, validate_agent_result  # noqa: E402
from app.orchestrator.prompts import build_narrative_prompt  # noqa: E402
from app.store import run_store  # noqa: E402
from contracts.python.models import (  # noqa: E402
    AgentResult,
    ResearchRequest,
    ResearchResult,
    Video,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = json.loads(
    (_REPO_ROOT / "contracts" / "fixtures" / "research-result.longform.json").read_text()
)
_NARRATIVE = "... OUTPUT CONTRACT — emit EXACTLY ONE JSON object ..."
_EXPANSION = "OUTPUT: a single JSON array of strings and NOTHING else."


def _agent_result() -> dict:
    return copy.deepcopy({
        "schema_version": "1.0",
        "topic_title": _FIXTURE["topic_title"],
        "summary": _FIXTURE["summary"],
        "keywords": _FIXTURE["meta"]["keywords"],
        "top_video_ids": [
            {"video_id": v["video_id"], "rank": i + 1} for i, v in enumerate(_FIXTURE["top_videos"])
        ],
        "watch_list": _FIXTURE["watch_list"],
        "title_analysis": _FIXTURE["title_analysis"],
        "script_analysis": _FIXTURE["script_analysis"],
        "title_formulas": _FIXTURE["title_formulas"],
        "game_plan": _FIXTURE["game_plan"],
    })


def _request(**over) -> ResearchRequest:
    base = dict(
        schema_version="1.0",
        query="how to promote your airbnb",
        format="longform",
        upload_date="all",
        outperformance="highest",
        analyze_titles=True,
        analyze_scripts=True,
        model={"adapter": "anthropic-api", "model": "claude-opus-5-5"},
        max_results=5,
    )
    base.update(over)
    return ResearchRequest.model_validate(base)


def _keywords(node):
    """Every schema keyword in ``node``, skipping property names."""
    found = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "properties":
                for sub in value.values():
                    found |= _keywords(sub)
            else:
                found.add(key)
                found |= _keywords(value)
    elif isinstance(node, list):
        for item in node:
            found |= _keywords(item)
    return found


def _objects(node):
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            yield node
        for key, value in node.items():
            if key == "properties":
                for sub in value.values():
                    yield from _objects(sub)
            else:
                yield from _objects(value)
    elif isinstance(node, list):
        for item in node:
            yield from _objects(item)


# --------------------------------------------------------------------------- #
# Step 1: one strict schema, shared                                           #
# --------------------------------------------------------------------------- #
def test_agent_result_schema_is_provider_safe():
    schema = agent_result_schema()
    keywords = _keywords(schema)
    # Inlined, and no keyword any provider rejects in strict mode.
    assert not keywords & {"$ref", "$defs", "default", "title", "pattern", "minimum", "const"}
    for obj in _objects(schema):
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])
    assert schema["properties"]["schema_version"] == {"enum": ["1.0"], "type": "string"}
    # A property literally named "title" survives (only the keyword is dropped).
    hook = schema["properties"]["script_analysis"]["anyOf"][0]
    assert "title" in hook["properties"]["hook_breakdown"]["items"]["properties"]


def test_agent_result_schema_accepts_a_real_answer():
    jsonschema.validate(_agent_result(), agent_result_schema())
    # Toggled-off sections are explicit nulls under "required everything".
    jsonschema.validate(
        dict(_agent_result(), title_analysis=None, script_analysis=None,
             title_formulas=None, game_plan=None),
        agent_result_schema(),
    )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(dict(_agent_result(), extra=1), agent_result_schema())


def test_agent_result_schema_copies_are_independent():
    first = agent_result_schema()
    first["properties"].clear()
    assert agent_result_schema()["properties"]


def test_strict_schema_inlines_refs():
    schema = {
        "$defs": {"Item": {"type": "object", "properties": {"a": {"type": "integer", "minimum": 1}}}},
        "type": "object",
        "properties": {"items": {"type": "array", "items": {"$ref": "#/$defs/Item"}}},
    }
    assert strict_schema(schema) == {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"a": {"type": "integer"}},
                    "additionalProperties": False,
                    "required": ["a"],
                },
            }
        },
        "additionalProperties": False,
        "required": ["items"],
    }


# --------------------------------------------------------------------------- #
# Steps 2–3: parse once, drop unknown keys, stay strict otherwise             #
# --------------------------------------------------------------------------- #
def _with_extras() -> dict:
    obj = _agent_result()
    obj["confidence"] = "high"  # top level
    obj["watch_list"][0]["thumbnail_hint"] = "red arrow"  # inside an array item
    obj["title_analysis"]["notes"] = "extra"  # inside an anyOf object
    obj["title_analysis"]["common_features"][0]["weight"] = 0.4  # nested array item
    obj["game_plan"]["outline"][0]["duration"] = "0:30"
    return obj


_PRETTY = json.dumps(_with_extras(), indent=2)

_CORPUS = {
    "compact": json.dumps(_with_extras()),
    "pretty": _PRETTY,
    "fenced": "```json\n" + _PRETTY + "\n```",
    "bare fence": "```\n" + _PRETTY + "\n```",
    "prose around": "Here is the report you asked for:\n\n" + _PRETTY + "\n\nLet me know!",
    "prose and fence": "Sure.\n```json\n" + _PRETTY + "\n```\nDone.",
    "leading whitespace": "\n\n   " + _PRETTY + "\n",
    # A CLI on Windows can write CRLF line endings.
    "crlf fenced": ("Sure.\n```json\n" + _PRETTY + "\n```\n").replace("\n", "\r\n"),
}


@pytest.mark.parametrize("cut", [0.5, 0.9, 0.999])
def test_parser_rejects_a_truncated_answer(cut):
    # A cut-off answer must not be half-read into a "valid" partial report;
    # the run loop reports truncation from the stop reason instead.
    # A complete inner object (a watch-list item) may still be found, but it
    # must not validate as a report.
    text = "```json\n" + _PRETTY[: int(len(_PRETTY) * cut)]
    parsed = parse_json_text(text)
    if parsed is not None:
        with pytest.raises(ValidationError):
            validate_agent_result(parsed)


@pytest.mark.parametrize("name", sorted(_CORPUS))
def test_parser_corpus_with_extra_keys_validates(name):
    parsed = parse_json_text(_CORPUS[name])
    assert parsed is not None, name
    result = validate_agent_result(parsed)
    assert isinstance(result, AgentResult)
    dumped = result.model_dump()
    assert "confidence" not in dumped
    assert "thumbnail_hint" not in dumped["watch_list"][0]
    assert "notes" not in dumped["title_analysis"]
    assert "weight" not in dumped["title_analysis"]["common_features"][0]
    assert "duration" not in dumped["game_plan"]["outline"][0]
    assert dumped["topic_title"] == _FIXTURE["topic_title"]


def test_parser_returns_none_without_an_object():
    assert parse_json_text("") is None
    assert parse_json_text("I could not find any videos.") is None
    assert parse_json_text('["just", "an", "array"]') is None


def test_prune_does_not_mutate_input():
    obj = _with_extras()
    prune_unknown_keys(obj, agent_result_schema())
    assert obj["confidence"] == "high"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda o: o.pop("summary"),  # required field missing
        lambda o: o.__setitem__("top_video_ids", "nope"),  # wrong type
        lambda o: o["watch_list"][0].__setitem__("video_id", "bad id"),  # id pattern
        lambda o: o["top_video_ids"][0].__setitem__("rank", 0),  # ge=1
        lambda o: o.__setitem__("schema_version", "2.0"),
    ],
)
def test_validation_stays_strict_apart_from_unknown_keys(mutate):
    obj = _with_extras()
    mutate(obj)
    with pytest.raises(ValidationError):
        validate_agent_result(obj)


def test_research_result_still_forbids_extras():
    data = dict(_FIXTURE, unexpected=True)
    with pytest.raises(ValidationError):
        ResearchResult.model_validate(data)


class _ApiAdapter:
    """A non-agentic adapter: yields the model's answer verbatim, line by line."""

    agentic = False

    def __init__(self, text, window=None):
        self._text = text
        self._window = window
        self.prompts = []

    def stream(self, prompt, *, model=None, cwd=None):
        self.prompts.append(prompt)
        return iter(self._text.split("\n"))

    def context_window(self, model=None):
        return self._window


@pytest.fixture
def _run():
    run_store.reset()
    _runner.reset()
    req = _request()
    run_id = run_store.create_run(req)
    yield run_id, req
    run_store.reset()
    _runner.reset()


def test_api_adapter_output_is_parsed_as_one_text(_run):
    run_id, req = _run
    adapter = _ApiAdapter("Here you go:\n```json\n" + _PRETTY + "\n```")
    obj = _runner._stream_and_extract(run_id, adapter, _NARRATIVE, {}, req)
    assert validate_agent_result(obj).topic_title == _FIXTURE["topic_title"]


def test_extra_keys_do_not_trigger_a_repair(_run):
    run_id, req = _run
    adapter = _ApiAdapter(_PRETTY)
    result = _runner._run_agent(run_id, req, _NARRATIVE, adapter, {})
    assert isinstance(result, AgentResult)
    assert len(adapter.prompts) == 1


# --------------------------------------------------------------------------- #
# Step 4: size the prompt to the model                                        #
# --------------------------------------------------------------------------- #
def _videos(n):
    base = _FIXTURE["top_videos"][0]
    out = []
    for i in range(n):
        row = dict(base, video_id="v%010d" % i, title="Video number %d about airbnb" % i)
        out.append(Video.model_validate(row))
    return out


def test_large_context_sends_every_video(_run):
    run_id, req = _run
    videos = _videos(40)
    adapter = _ApiAdapter("", window=1_000_000)
    prompt = _runner._fit_narrative_prompt(run_id, req, videos, {}, _runner.map_filters(req), adapter, {})
    assert all(v.video_id in prompt for v in videos)


def test_small_context_sends_fewer_videos_and_says_so(_run):
    run_id, req = _run
    videos = _videos(120)
    filters = _runner.map_filters(req)
    full = build_narrative_prompt(req, videos, {}, filters=filters)
    window = len(full) // 3 // 2 + 8192  # room for about half the full prompt
    adapter = _ApiAdapter("", window=window)
    prompt = _runner._fit_narrative_prompt(run_id, req, videos, {}, filters, adapter, {})
    assert len(prompt) < len(full)
    assert videos[0].video_id in prompt  # the top-ranked videos stay
    assert videos[-1].video_id not in prompt
    details = [getattr(e, "detail", None) for e in run_store.get_events(run_id)]
    assert any(d and "context window" in d for d in details)


def test_context_sizing_never_drops_below_requested_results(_run):
    run_id, req = _run
    videos = _videos(30)
    adapter = _ApiAdapter("", window=9000)  # far too small for anything
    prompt = _runner._fit_narrative_prompt(run_id, req, videos, {}, _runner.map_filters(req), adapter, {})
    assert all(v.video_id in prompt for v in videos[: req.max_results])


def test_unknown_context_window_sends_the_full_prompt(_run):
    run_id, req = _run
    videos = _videos(20)

    class NoWindow:
        def stream(self, prompt, **kw):  # pragma: no cover - not called
            return iter(())

    prompt = _runner._fit_narrative_prompt(run_id, req, videos, {}, _runner.map_filters(req), NoWindow(), {})
    assert all(v.video_id in prompt for v in videos)


# --------------------------------------------------------------------------- #
# Request shape: Anthropic                                                    #
# --------------------------------------------------------------------------- #
class _AStream:
    def __init__(self, text):
        self._text = text

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def text_stream(self):
        yield self._text

    def get_final_message(self):
        block = type("B", (), {"type": "text", "text": self._text})()
        return type("M", (), {"content": [block], "stop_reason": "end_turn"})()


class _AInfo:
    def __init__(self, structured=True, max_input_tokens=1_000_000):
        self.max_tokens = 128000
        self.max_input_tokens = max_input_tokens
        self.capabilities = {
            "thinking": {"types": {"adaptive": {"supported": True}}},
            "structured_outputs": {"supported": structured},
        }


class _AClient:
    def __init__(self, info=None, text='{"reply": "hello"}', listed=()):
        self.calls = []
        self._info = info
        self._text = text
        self._listed = list(listed)
        outer = self

        class Messages:
            def stream(self, **kw):
                outer.calls.append(kw)
                return _AStream(outer._text)

        class Models:
            def retrieve(self, model):
                if outer._info is None:
                    raise RuntimeError("models api unavailable")
                return outer._info

            def list(self):
                return [type("M", (), {"id": i})() for i in outer._listed]

        self.messages = Messages()
        self.models = Models()

    def with_options(self, **kw):
        return self


@pytest.fixture
def _anthropic(monkeypatch):
    monkeypatch.setattr(direct_mod, "_sdk_version", lambda: "1.5.0")
    monkeypatch.setattr(direct_mod, "_stored_key", lambda: "sk-ant-test")
    monkeypatch.delenv("YUBEN_MAX_OUTPUT_TOKENS", raising=False)
    direct_mod._model_info_cache.clear()
    direct_mod._model_list_cache.clear()

    def install(client):
        monkeypatch.setattr(direct_mod.DirectAnthropicAdapter, "_client", lambda self, key: client)
        return client

    yield install
    direct_mod._model_info_cache.clear()
    direct_mod._model_list_cache.clear()


def test_anthropic_narrative_sends_output_config_format(_anthropic):
    client = _anthropic(_AClient(info=_AInfo()))
    list(get_adapter("anthropic-api").stream(_NARRATIVE, model="claude-opus-5-5"))
    fmt = client.calls[0]["output_config"]["format"]
    assert fmt == {"type": "json_schema", "schema": agent_result_schema()}
    assert client.calls[0]["thinking"] == {"type": "adaptive"}


def test_anthropic_expansion_sends_no_format(_anthropic):
    client = _anthropic(_AClient(info=_AInfo()))
    list(get_adapter("anthropic-api").stream(_EXPANSION, model="claude-opus-5-5"))
    assert "output_config" not in client.calls[0]


def test_anthropic_check_uses_the_probe_schema(_anthropic):
    client = _anthropic(_AClient(info=_AInfo()))
    res = get_adapter("anthropic-api").check_env(model="claude-opus-5-5")
    assert res["ok"] is True
    kw = client.calls[0]
    assert kw["output_config"]["format"]["schema"] == PROBE_SCHEMA
    assert "JSON" in kw["messages"][0]["content"]


def test_anthropic_models_api_can_turn_format_off(_anthropic):
    client = _anthropic(_AClient(info=_AInfo(structured=False), text="hello"))
    adapter = get_adapter("anthropic-api")
    assert adapter.check_env(model="claude-new")["ok"] is True
    list(adapter.stream(_NARRATIVE, model="claude-new"))
    assert all("output_config" not in kw for kw in client.calls)
    assert client.calls[0]["messages"][0]["content"] == "Reply with exactly: hello"


@pytest.mark.parametrize(
    "model,expected",
    [("claude-haiku-4-5", True), ("claude-opus-5-5", True), ("claude-opus-4-6", False)],
)
def test_anthropic_static_structured_rule_without_models_api(_anthropic, model, expected):
    client = _anthropic(_AClient(info=None))
    list(get_adapter("anthropic-api").stream(_NARRATIVE, model=model))
    assert ("output_config" in client.calls[0]) is expected


def test_anthropic_context_window_from_models_api(_anthropic):
    _anthropic(_AClient(info=_AInfo(max_input_tokens=200_000)))
    assert get_adapter("anthropic-api").context_window("claude-haiku-4-5") == 200_000


def test_anthropic_model_list_comes_from_models_api(_anthropic):
    _anthropic(_AClient(listed=["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]))
    assert get_adapter("anthropic-api").models() == [
        "default", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5",
    ]


def test_anthropic_model_list_falls_back_without_key(monkeypatch):
    monkeypatch.setattr(direct_mod, "_stored_key", lambda: None)
    models = get_adapter("anthropic-api").models()
    assert models[0] == "default" and "claude-opus-5-5" in models


# --------------------------------------------------------------------------- #
# Request shape: OpenAI-compatible                                            #
# --------------------------------------------------------------------------- #
def _bad_request(message):
    import httpx2
    import openai

    request = httpx2.Request("POST", "https://api.example.test/v1/chat/completions")
    return openai.BadRequestError(message, response=httpx2.Response(400, request=request), body=None)


class _OClient:
    def __init__(self, text='{"reply": "hello"}', reject=()):
        self.calls = []
        self._text = text
        self._reject = list(reject)  # response_format types to 400 on
        outer = self

        class Completions:
            def create(self, **kw):
                outer.calls.append(kw)
                fmt = (kw.get("response_format") or {}).get("type")
                if fmt in outer._reject:
                    raise _bad_request("Invalid parameter: 'response_format' of type '%s'" % fmt)
                if kw.get("stream"):
                    delta = type("D", (), {"content": outer._text})()
                    choice = type("C", (), {"delta": delta, "finish_reason": "stop"})()
                    return iter([type("K", (), {"choices": [choice]})()])
                message = type("Msg", (), {"content": outer._text})()
                return type("R", (), {"choices": [type("C", (), {"message": message})()]})()

        self.chat = type("Chat", (), {"completions": Completions()})()

    def with_options(self, **kw):
        return self


@pytest.fixture
def _openai(monkeypatch):
    monkeypatch.delenv("YUBEN_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.setattr(oai, "_sdk_version", lambda: "3.13.0")
    monkeypatch.setattr(oai, "_model_meta", {})
    monkeypatch.setattr(oai, "_model_cache", {})

    def install(adapter_id, client):
        adapter = get_adapter(adapter_id)
        monkeypatch.setattr(type(adapter), "_stored_key", lambda self: "sk-test")
        monkeypatch.setattr(type(adapter), "_client", lambda self, key: client)
        return adapter

    return install


def _format(kw):
    return kw.get("response_format")


def test_openai_narrative_sends_strict_json_schema(_openai):
    client = _OClient()
    adapter = _openai("openai-api", client)
    list(adapter.stream(_NARRATIVE, model="gpt-4o"))
    assert _format(client.calls[0]) == {
        "type": "json_schema",
        "json_schema": {"name": AGENT_RESULT_SCHEMA_NAME, "strict": True, "schema": agent_result_schema()},
    }


def test_openai_expansion_sends_no_format(_openai):
    client = _OClient()
    list(_openai("openai-api", client).stream(_EXPANSION, model="gpt-4o"))
    assert "response_format" not in client.calls[0]


@pytest.mark.parametrize("model", ["gpt-4-turbo", "gpt-4", "gpt-3.5-turbo"])
def test_openai_older_models_get_json_object(_openai, model):
    client = _OClient()
    list(_openai("openai-api", client).stream(_NARRATIVE, model=model))
    assert _format(client.calls[0]) == {"type": "json_object"}


def test_openai_rejected_schema_steps_down_to_json_object(_openai):
    client = _OClient(reject=["json_schema"])
    adapter = _openai("openai-api", client)
    out = list(adapter.stream(_NARRATIVE, model="gpt-5-mini"))
    assert [(_format(kw) or {}).get("type") for kw in client.calls] == ["json_schema", "json_object"]
    assert out == ['{"reply": "hello"}']


def test_openai_rejected_formats_step_down_to_none(_openai):
    client = _OClient(text="hello", reject=["json_schema", "json_object"])
    adapter = _openai("openai-api", client)
    assert adapter.check_env(model="gpt-5-mini")["ok"] is True
    assert [(_format(kw) or {}).get("type") for kw in client.calls] == ["json_schema", "json_object", None]


def test_openai_check_sends_the_probe_schema(_openai):
    client = _OClient()
    assert _openai("openai-api", client).check_env(model="gpt-4o-mini")["ok"] is True
    fmt = _format(client.calls[0])
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["schema"] == PROBE_SCHEMA


def test_other_400s_are_not_retried(_openai):
    client = _OClient()

    def boom(**kw):
        client.calls.append(kw)
        raise _bad_request("temperature is not supported")

    client.chat.completions.create = boom
    with pytest.raises(AdapterError):
        list(_openai("openai-api", client).stream(_NARRATIVE, model="gpt-4o"))
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    "model,expected",
    [("gemini-2.5-flash", "json_schema"), ("models/gemini-3-pro", "json_schema"),
     ("gemini-1.5-pro", None), ("gemma-3-27b-it", None)],
)
def test_gemini_format_by_model(_openai, model, expected):
    client = _OClient()
    list(_openai("gemini-api", client).stream(_NARRATIVE, model=model))
    assert (_format(client.calls[0]) or {}).get("type") == expected


@pytest.mark.parametrize(
    "params,expected",
    [(["structured_outputs", "response_format"], "json_schema"),
     (["response_format", "tools"], "json_object"),
     (["tools"], None)],
)
def test_openrouter_format_follows_listed_support(_openai, params, expected):
    client = _OClient()
    adapter = _openai("openrouter", client)
    oai._model_meta["openrouter"] = {"vendor/model": {"supported_parameters": params}}
    list(adapter.stream(_NARRATIVE, model="vendor/model"))
    assert (_format(client.calls[0]) or {}).get("type") == expected


def test_openrouter_unknown_model_gets_no_format(_openai):
    client = _OClient()
    adapter = _openai("openrouter", client)
    oai._model_meta["openrouter"] = {}
    list(adapter.stream(_NARRATIVE, model="vendor/unlisted"))
    assert "response_format" not in client.calls[0]


def test_openrouter_context_window_from_models_list(_openai):
    adapter = _openai("openrouter", _OClient())
    oai._model_meta["openrouter"] = {"vendor/small": {"context_length": 8192}}
    assert adapter.context_window("vendor/small") == 8192
    assert adapter.context_window("vendor/unknown") is None


# --------------------------------------------------------------------------- #
# Request shape: Ollama native /api/chat                                      #
# --------------------------------------------------------------------------- #
class _HResponse:
    def __init__(self, status=200, lines=(), body=b"", payload=None):
        self.status_code = status
        self._lines = list(lines)
        self._body = body
        self._payload = payload or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_lines(self):
        yield from self._lines

    def read(self):
        return self._body

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def _ndjson(*texts, done_reason="stop"):
    lines = [json.dumps({"message": {"content": t}, "done": False}) for t in texts]
    lines.append(json.dumps({"message": {"content": ""}, "done": True, "done_reason": done_reason}))
    return lines


@pytest.fixture
def _ollama(monkeypatch):
    import httpx

    monkeypatch.delenv("YUBEN_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.delenv("YUBEN_OLLAMA_BASE_URL", raising=False)
    monkeypatch.setattr(oai, "_ollama_context", {})
    sent = {"chat": [], "show": []}
    state = {"chat": _HResponse(lines=_ndjson('{"reply": ', '"hello"}')), "window": 32768}

    def fake_stream(method, url, json=None, timeout=None):
        sent["chat"].append((url, json))
        return state["chat"]

    def fake_post(url, json=None, timeout=None):
        sent["show"].append((url, json))
        if state["window"] is None:
            return _HResponse(status=404)
        return _HResponse(payload={"model_info": {"qwen2.context_length": state["window"]}})

    monkeypatch.setattr(httpx, "stream", fake_stream)
    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(oai, "which", lambda b: "/usr/local/bin/ollama")
    monkeypatch.setattr(oai, "run_version", lambda p, **kw: "0.12.0")
    return sent, state


def test_ollama_narrative_uses_native_chat_with_format_and_num_ctx(_ollama):
    sent, state = _ollama
    prompt = _NARRATIVE + " " + "x" * 30000  # ~10K tokens, like a real run
    list(get_adapter("ollama").stream(prompt, model="qwen2.5:14b"))
    url, body = sent["chat"][0]
    assert url == "http://localhost:11434/api/chat"
    assert body["format"] == agent_result_schema()
    num_ctx = body["options"]["num_ctx"]
    assert num_ctx >= len(prompt) // 3 + 8192 and num_ctx % 2048 == 0
    assert num_ctx <= state["window"]


def test_ollama_num_ctx_is_capped_by_the_model_maximum(_ollama):
    sent, state = _ollama
    state["window"] = 16384
    list(get_adapter("ollama").stream(_NARRATIVE + "x" * 90000, model="qwen2.5:14b"))
    assert sent["chat"][0][1]["options"]["num_ctx"] == 16384
    assert get_adapter("ollama").context_window("qwen2.5:14b") == 16384


def test_ollama_expansion_sends_no_format_but_a_minimum_context(_ollama):
    sent, _ = _ollama
    list(get_adapter("ollama").stream(_EXPANSION, model="qwen2.5:14b"))
    body = sent["chat"][0][1]
    assert "format" not in body
    assert body["options"]["num_ctx"] >= oai._OLLAMA_MIN_CTX


def test_ollama_check_uses_native_chat_and_probe_schema(_ollama):
    sent, _ = _ollama
    res = get_adapter("ollama").check_env(model="qwen2.5:14b")
    assert res["ok"] is True and res["version"] == "0.12.0"
    assert sent["chat"][0][1]["format"] == PROBE_SCHEMA


def test_ollama_length_stop_raises_truncated(_ollama):
    _, state = _ollama
    state["chat"] = _HResponse(lines=_ndjson('{"topic_title": "x",\n', '"summ', done_reason="length"))
    with pytest.raises(OutputTruncated):
        list(get_adapter("ollama").stream(_NARRATIVE, model="qwen2.5:14b"))


def test_ollama_missing_model_is_typed(_ollama):
    _, state = _ollama
    state["chat"] = _HResponse(status=404, body=b'{"error": "model \\"nope\\" not found"}')
    with pytest.raises(AdapterError) as info:
        list(get_adapter("ollama").stream(_NARRATIVE, model="nope"))
    assert info.value.kind == KIND_MODEL_NOT_FOUND


def test_ollama_custom_base_url_maps_to_native_root(_ollama, monkeypatch):
    sent, _ = _ollama
    monkeypatch.setenv("YUBEN_OLLAMA_BASE_URL", "http://gpu-box:11434/v1/")
    list(get_adapter("ollama").stream(_EXPANSION, model="qwen2.5:14b"))
    assert sent["chat"][0][0] == "http://gpu-box:11434/api/chat"


# --------------------------------------------------------------------------- #
# Step 5: pickers list only models that can write a report                    #
# --------------------------------------------------------------------------- #
def _listed(monkeypatch, adapter_id, ids):
    adapter = get_adapter(adapter_id)
    monkeypatch.setattr(oai, "_model_cache", {})
    monkeypatch.setattr(adapter, "_models_live", lambda: sorted(ids))
    return adapter.models()


def test_openai_picker_keeps_chat_models_only(monkeypatch):
    ids = [
        "gpt-4o", "gpt-4o-mini", "gpt-5", "gpt-5-mini", "o3", "o4-mini", "chatgpt-4o-latest",
        "ft:gpt-4o-mini:acme::abc", "text-embedding-3-large", "tts-1", "whisper-1",
        "dall-e-3", "gpt-image-1", "omni-moderation-latest", "gpt-4o-realtime-preview",
        "gpt-4o-transcribe", "gpt-4o-search-preview", "babbage-002", "davinci-002",
        "gpt-3.5-turbo-instruct", "codex-mini-latest", "o3-pro", "sora-2",
        "computer-use-preview", "o3-deep-research", "gpt-audio",
    ]
    assert _listed(monkeypatch, "openai-api", ids) == [
        "default", "chatgpt-4o-latest", "ft:gpt-4o-mini:acme::abc", "gpt-4o", "gpt-4o-mini",
        "gpt-5", "gpt-5-mini", "o3", "o4-mini",
    ]


def test_gemini_picker_drops_non_text_models(monkeypatch):
    ids = [
        "models/gemini-2.5-flash", "models/gemini-2.5-pro", "models/gemma-3-27b-it",
        "models/text-embedding-004", "models/gemini-embedding-001", "models/imagen-4.0-generate-001",
        "models/veo-3.0-generate-001", "models/aqa", "models/gemini-2.5-flash-preview-tts",
        "models/gemini-2.5-flash-image", "models/gemini-live-2.5-flash",
    ]
    assert _listed(monkeypatch, "gemini-api", ids) == [
        "default", "models/gemini-2.5-flash", "models/gemini-2.5-pro", "models/gemma-3-27b-it",
    ]


def test_openrouter_picker_drops_models_without_text_output(monkeypatch):
    adapter = get_adapter("openrouter")
    monkeypatch.setattr(oai, "_model_cache", {})
    meta = {
        "openai/gpt-4o": {"architecture": {"output_modalities": ["text"]}},
        "google/gemini-2.5-flash-image": {"architecture": {"output_modalities": ["image", "text"]}},
        "vendor/image-only": {"architecture": {"output_modalities": ["image"]}},
        "vendor/no-metadata": {},
    }

    def live():
        oai._model_meta["openrouter"] = meta
        return sorted(meta)

    monkeypatch.setattr(adapter, "_models_live", live)
    assert adapter.models() == [
        "default", "google/gemini-2.5-flash-image", "openai/gpt-4o", "vendor/no-metadata",
    ]


def test_ollama_picker_drops_embedding_models(monkeypatch):
    ids = ["llama3.2:latest", "qwen2.5:14b", "nomic-embed-text:latest", "mxbai-embed-large:latest",
           "bge-m3:latest", "all-minilm:latest"]
    assert _listed(monkeypatch, "ollama", ids) == ["default", "llama3.2:latest", "qwen2.5:14b"]
