"""B2 verification: AgentAdapter interface, ClaudeCode + Gemini adapters,
registry, and the /api/adapters route.

All CLI interaction is mocked (no live ``claude`` turn, no network), so the suite
is deterministic and fast. The store is isolated to a temp dir the same way
test_config.py does it, since importing ``app.main`` pulls in the config router.
"""
import os
import subprocess
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="yuben-test-adapters-")
os.environ.setdefault("YUBEN_DATA_DIR", _TMP)
os.environ.setdefault("YUBEN_FORCE_FILE_SECRET", "1")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.adapters as registry  # noqa: E402
from app.adapters import (  # noqa: E402
    CLI_SPECS,
    AdapterError,
    ClaudeCodeAdapter,
    DirectAnthropicAdapter,
    GeminiCliAdapter,
    GenericCliAdapter,
    OllamaAdapter,
    OpenAIAdapter,
    OpenRouterAdapter,
    check_env,
    get_adapter,
    list_adapters,
)
from app.adapters import base as adapters_base  # noqa: E402
from app.adapters.base import OutputTruncated  # noqa: E402
from app.adapters import claude_code as claude_mod  # noqa: E402
from app.adapters import direct_anthropic as direct_mod  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=["claude"], returncode=returncode, stdout=stdout, stderr=stderr)


# --- version parsing --------------------------------------------------------
def test_extract_version_parses_semver():
    assert adapters_base.extract_version("2.1.198 (Claude Code)") == "2.1.198"
    assert adapters_base.extract_version("gemini 0.4.0") == "0.4.0"
    assert adapters_base.extract_version("v1.2") == "1.2"
    assert adapters_base.extract_version("") is None
    # No numeric token -> falls back to the trimmed line.
    assert adapters_base.extract_version("weird-build") == "weird-build"


# --- ClaudeCodeAdapter detection -------------------------------------------
def test_claude_detect_missing(monkeypatch):
    monkeypatch.setattr(claude_mod, "which", lambda _b: None)
    assert ClaudeCodeAdapter().detect() == {"installed": False, "version": None}


def test_claude_detect_present(monkeypatch):
    monkeypatch.setattr(claude_mod, "which", lambda _b: "/usr/local/bin/claude")
    monkeypatch.setattr(claude_mod, "run_version", lambda _p, **kw: "2.1.198")
    assert ClaudeCodeAdapter().detect() == {"installed": True, "version": "2.1.198"}


def test_claude_models_lists_current_ids():
    models = ClaudeCodeAdapter().models()
    assert models[0] == "default"
    assert "claude-opus-4-8" in models
    assert "claude-fable-5-1" in models and "claude-opus-5-5" in models


# --- ClaudeCodeAdapter check_env (mocked probe) ----------------------------
def test_claude_check_env_missing_cli(monkeypatch):
    monkeypatch.setattr(claude_mod, "which", lambda _b: None)
    res = ClaudeCodeAdapter().check_env()
    assert res["ok"] is False
    assert res["adapter"] == "claude-code"
    assert res["version"] is None
    assert "couldn't find" in res["message"].lower()


def test_claude_check_env_probe_ok(monkeypatch):
    monkeypatch.setattr(claude_mod, "which", lambda _b: "/bin/claude")
    monkeypatch.setattr(claude_mod, "run_version", lambda _p, **kw: "2.1.198")
    monkeypatch.setattr(claude_mod, "run_probe", lambda cmd, **kw: _completed(0, "hello"))
    res = ClaudeCodeAdapter().check_env()
    assert res["ok"] is True
    assert res["adapter"] == "claude-code"
    assert res["version"] == "2.1.198"
    assert "responded" in res["message"].lower()


def test_claude_check_env_passes_model_flag(monkeypatch):
    seen = {}

    def fake_probe(cmd, **kw):
        seen["cmd"] = cmd
        return _completed(0, "hello")

    monkeypatch.setattr(claude_mod, "which", lambda _b: "/bin/claude")
    monkeypatch.setattr(claude_mod, "run_version", lambda _p, **kw: "2.1.198")
    monkeypatch.setattr(claude_mod, "run_probe", fake_probe)

    ClaudeCodeAdapter().check_env(model="claude-opus-4-8")
    assert "--model" in seen["cmd"]
    assert "claude-opus-4-8" in seen["cmd"]

    # "default" must NOT add a --model flag.
    ClaudeCodeAdapter().check_env(model="default")
    assert "--model" not in seen["cmd"]


def test_claude_check_env_unexpected_output(monkeypatch):
    monkeypatch.setattr(claude_mod, "which", lambda _b: "/bin/claude")
    monkeypatch.setattr(claude_mod, "run_version", lambda _p, **kw: "2.1.198")
    monkeypatch.setattr(claude_mod, "run_probe", lambda cmd, **kw: _completed(0, "I cannot do that"))
    res = ClaudeCodeAdapter().check_env()
    assert res["ok"] is False
    assert "unexpectedly" in res["message"].lower()


def test_claude_check_env_nonzero_exit(monkeypatch):
    monkeypatch.setattr(claude_mod, "which", lambda _b: "/bin/claude")
    monkeypatch.setattr(claude_mod, "run_version", lambda _p, **kw: "2.1.198")
    monkeypatch.setattr(claude_mod, "run_probe", lambda cmd, **kw: _completed(1, "", "auth error: not logged in"))
    res = ClaudeCodeAdapter().check_env()
    assert res["ok"] is False
    assert "auth error" in res["message"]


def test_claude_check_env_timeout(monkeypatch):
    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 90)

    monkeypatch.setattr(claude_mod, "which", lambda _b: "/bin/claude")
    monkeypatch.setattr(claude_mod, "run_version", lambda _p, **kw: "2.1.198")
    monkeypatch.setattr(claude_mod, "run_probe", boom)
    res = ClaudeCodeAdapter().check_env()
    assert res["ok"] is False
    assert "did not respond" in res["message"].lower()


# --- ClaudeCodeAdapter.stream (the surface B4 consumes) --------------------
def test_claude_stream_missing_raises(monkeypatch):
    monkeypatch.setattr(claude_mod, "which", lambda _b: None)
    with pytest.raises(AdapterError):
        list(ClaudeCodeAdapter().stream("hi"))


def test_claude_stream_builds_headless_cmd(monkeypatch):
    seen = {}

    def fake_stream_process(cmd, cwd=None):
        seen["cmd"] = cmd
        seen["cwd"] = cwd
        yield '{"type":"system"}'
        yield '{"type":"result","result":"ok"}'

    monkeypatch.setattr(claude_mod, "which", lambda _b: "/bin/claude")
    monkeypatch.setattr(claude_mod, "stream_process", fake_stream_process)

    lines = list(ClaudeCodeAdapter().stream("do research", model="claude-sonnet-5", cwd="/tmp"))
    assert lines[-1] == '{"type":"result","result":"ok"}'
    cmd = seen["cmd"]
    assert cmd[0] == "/bin/claude"
    assert cmd[1] == "-p"
    assert cmd[2] == "do research"
    assert "--output-format" in cmd and "stream-json" in cmd
    assert "--verbose" in cmd
    assert "--model" in cmd and "claude-sonnet-5" in cmd
    assert seen["cwd"] == "/tmp"


# --- the shared stream engine (real cheap subprocess, no LLM) --------------
def test_stream_process_yields_lines_and_reaps():
    cmd = [sys.executable, "-c", "print('alpha'); print('beta')"]
    assert list(adapters_base.stream_process(cmd)) == ["alpha", "beta"]


def test_stream_process_raises_on_error_with_no_output():
    cmd = [sys.executable, "-c", "import sys; sys.stderr.write('kaboom'); sys.exit(3)"]
    with pytest.raises(AdapterError) as exc:
        list(adapters_base.stream_process(cmd))
    assert "kaboom" in str(exc.value)


def test_stream_process_missing_binary_raises():
    with pytest.raises(AdapterError):
        list(adapters_base.stream_process(["definitely-not-a-real-binary-xyz"]))


# --- GeminiCliAdapter (stub) -----------------------------------------------
def test_gemini_detect_missing(monkeypatch):
    from app.adapters import gemini_cli as gem_mod

    monkeypatch.setattr(gem_mod, "which", lambda _b: None)
    assert GeminiCliAdapter().detect() == {"installed": False, "version": None}


def test_gemini_check_env_graceful():
    res = GeminiCliAdapter().check_env()
    assert res["ok"] is False  # never a hard pass while stubbed
    assert res["adapter"] == "gemini-cli"
    assert isinstance(res["message"], str) and res["message"]


def test_gemini_stream_not_implemented():
    with pytest.raises(NotImplementedError):
        list(GeminiCliAdapter().stream("hi"))


# --- DirectAnthropicAdapter (Phase 4 — no CLI, Messages API) ---------------
class _FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text, stop_reason="end_turn"):
        self.content = [_FakeBlock(text)] if text is not None else []
        self.stop_reason = stop_reason


class _FakeStreamCtx:
    """Mimics client.messages.stream(...) — a context manager exposing text_stream."""

    def __init__(self, chunks, enter_exc=None, stop_reason="end_turn"):
        self._chunks = chunks
        self._enter_exc = enter_exc
        self._stop_reason = stop_reason

    def get_final_message(self):
        return _FakeResponse("".join(self._chunks), self._stop_reason)

    def __enter__(self):
        if self._enter_exc:
            raise self._enter_exc
        return self

    def __exit__(self, *a):
        return False

    @property
    def text_stream(self):
        for chunk in self._chunks:
            yield chunk


class _FakeMessages:
    def __init__(self, *, text=None, chunks=None, exc=None, stop_reason="end_turn"):
        self._text = text
        self._chunks = chunks or []
        self._exc = exc
        self._stop_reason = stop_reason
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        if self._exc:
            raise self._exc
        return _FakeResponse(self._text)

    def stream(self, **kw):
        self.calls.append(kw)
        chunks = self._chunks or ([self._text] if self._text is not None else [])
        return _FakeStreamCtx(chunks, enter_exc=self._exc, stop_reason=self._stop_reason)


class _FakeModelInfo:
    def __init__(self, max_tokens, adaptive):
        self.max_tokens = max_tokens
        self.capabilities = {"thinking": {"types": {"adaptive": {"supported": adaptive}}}}


class _FakeModels:
    def __init__(self, info):
        self._info = info

    def retrieve(self, model):
        if self._info is None:
            raise RuntimeError("models api unavailable")
        return self._info


class _FakeClient:
    """with_options() returns self so .messages.create / .stream still resolve."""

    def __init__(self, *, text=None, chunks=None, exc=None, stop_reason="end_turn", info=None):
        self._messages = _FakeMessages(
            text=text, chunks=chunks, exc=exc, stop_reason=stop_reason
        )
        self.models = _FakeModels(info)

    @property
    def messages(self):
        return self._messages

    def with_options(self, **kw):
        return self


def _fake_client(**kw):
    return lambda self, key: _FakeClient(**kw)


def _AuthenticationError(message):
    """A real ``anthropic.AuthenticationError``: adapters classify by SDK type."""
    import anthropic
    import httpx2

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.AuthenticationError(
        message, response=httpx2.Response(401, request=request), body=None
    )


def test_direct_is_not_agentic():
    # The orchestrator branches on this: direct API adapter can't run tools.
    assert DirectAnthropicAdapter().agentic is False
    assert ClaudeCodeAdapter().agentic is True


def test_direct_models_lists_current_ids():
    models = DirectAnthropicAdapter().models()
    assert models[0] == "default"
    assert "claude-opus-4-8" in models and "claude-fable-5-1" in models


def test_direct_detect_reflects_sdk(monkeypatch):
    monkeypatch.setattr(direct_mod, "_sdk_version", lambda: "0.116.0")
    assert DirectAnthropicAdapter().detect() == {"installed": True, "version": "0.116.0"}
    monkeypatch.setattr(direct_mod, "_sdk_version", lambda: None)
    assert DirectAnthropicAdapter().detect() == {"installed": False, "version": None}


def test_direct_check_env_missing_sdk(monkeypatch):
    monkeypatch.setattr(direct_mod, "_sdk_version", lambda: None)
    res = DirectAnthropicAdapter().check_env()
    assert res["ok"] is False
    assert res["adapter"] == "anthropic-api"
    assert "anthropic" in res["message"].lower()


def test_direct_check_env_missing_key(monkeypatch):
    monkeypatch.setattr(direct_mod, "_sdk_version", lambda: "0.116.0")
    monkeypatch.setattr(direct_mod, "_stored_key", lambda: None)
    res = DirectAnthropicAdapter().check_env()
    assert res["ok"] is False
    assert "key" in res["message"].lower()


def test_direct_check_env_ping_ok(monkeypatch):
    monkeypatch.setattr(direct_mod, "_sdk_version", lambda: "0.116.0")
    monkeypatch.setattr(direct_mod, "_stored_key", lambda: "sk-ant-xxx")
    monkeypatch.setattr(direct_mod.DirectAnthropicAdapter, "_client", _fake_client(text="hello"))
    res = DirectAnthropicAdapter().check_env(model="claude-opus-4-8")
    assert res["ok"] is True
    assert res["adapter"] == "anthropic-api"
    assert res["version"] == "0.116.0"
    assert "claude-opus-4-8" in res["message"]


def test_direct_check_env_auth_error(monkeypatch):
    monkeypatch.setattr(direct_mod, "_sdk_version", lambda: "0.116.0")
    monkeypatch.setattr(direct_mod, "_stored_key", lambda: "sk-ant-bad")
    monkeypatch.setattr(
        direct_mod.DirectAnthropicAdapter, "_client",
        _fake_client(exc=_AuthenticationError("401")),
    )
    res = DirectAnthropicAdapter().check_env(model="claude-opus-4-8")
    assert res["ok"] is False
    assert "rejected" in res["message"].lower()


def test_direct_check_env_unexpected_output(monkeypatch):
    monkeypatch.setattr(direct_mod, "_sdk_version", lambda: "0.116.0")
    monkeypatch.setattr(direct_mod, "_stored_key", lambda: "sk-ant-xxx")
    monkeypatch.setattr(
        direct_mod.DirectAnthropicAdapter, "_client", _fake_client(text="I cannot do that"),
    )
    res = DirectAnthropicAdapter().check_env(model="claude-opus-4-8")
    assert res["ok"] is False
    assert "unexpectedly" in res["message"].lower()


def test_direct_stream_yields_lines(monkeypatch):
    # Deltas arrive at arbitrary boundaries; the adapter re-emits complete lines
    # so the collector reassembles losslessly (no raw newline injected into JSON).
    monkeypatch.setattr(direct_mod, "_sdk_version", lambda: "0.116.0")
    monkeypatch.setattr(direct_mod, "_stored_key", lambda: "sk-ant-xxx")
    monkeypatch.setattr(
        direct_mod.DirectAnthropicAdapter, "_client",
        _fake_client(chunks=['{"topic', '_title":\n', ' "x"}']),
    )
    out = list(DirectAnthropicAdapter().stream("do research", model="claude-opus-4-8"))
    # Split on the single newline; the two lines rejoin to the original text.
    assert out == ['{"topic_title":', ' "x"}']
    assert "\n".join(out) == '{"topic_title":\n "x"}'


def test_direct_stream_missing_key_raises(monkeypatch):
    monkeypatch.setattr(direct_mod, "_sdk_version", lambda: "0.116.0")
    monkeypatch.setattr(direct_mod, "_stored_key", lambda: None)
    with pytest.raises(AdapterError):
        list(DirectAnthropicAdapter().stream("hi"))


def test_direct_stream_api_error_becomes_adapter_error(monkeypatch):
    monkeypatch.setattr(direct_mod, "_sdk_version", lambda: "0.116.0")
    monkeypatch.setattr(direct_mod, "_stored_key", lambda: "sk-ant-xxx")
    monkeypatch.setattr(
        direct_mod.DirectAnthropicAdapter, "_client",
        _fake_client(exc=_AuthenticationError("401")),
    )
    with pytest.raises(AdapterError):
        list(DirectAnthropicAdapter().stream("hi", model="claude-opus-4-8"))


@pytest.fixture
def _anthropic_ready(monkeypatch):
    monkeypatch.setattr(direct_mod, "_sdk_version", lambda: "0.116.0")
    monkeypatch.setattr(direct_mod, "_stored_key", lambda: "sk-ant-xxx")
    monkeypatch.delenv("YUBEN_MAX_OUTPUT_TOKENS", raising=False)
    direct_mod._model_info_cache.clear()
    yield
    direct_mod._model_info_cache.clear()


def _install_client(monkeypatch, client):
    monkeypatch.setattr(direct_mod.DirectAnthropicAdapter, "_client", lambda self, key: client)
    return client


def test_direct_haiku_45_gets_no_adaptive_thinking(monkeypatch, _anthropic_ready):
    # Models API unreachable: the static rule still keeps adaptive off Haiku 4.5,
    # and the check sends the same parameters as the run.
    client = _install_client(monkeypatch, _FakeClient(text="hello"))
    adapter = DirectAnthropicAdapter()
    assert adapter.check_env(model="claude-haiku-4-5")["ok"] is True
    list(adapter.stream("x", model="claude-haiku-4-5"))
    check_kw, run_kw = client.messages.calls
    assert "thinking" not in check_kw and "thinking" not in run_kw
    assert check_kw["max_tokens"] == run_kw["max_tokens"] == direct_mod._FALLBACK_MAX_TOKENS


def test_direct_adaptive_thinking_and_cap_from_models_api(monkeypatch, _anthropic_ready):
    client = _install_client(
        monkeypatch, _FakeClient(text="hello", info=_FakeModelInfo(128000, True))
    )
    adapter = DirectAnthropicAdapter()
    assert adapter.check_env(model="claude-opus-5-5")["ok"] is True
    list(adapter.stream("x", model="claude-opus-5-5"))
    for kw in client.messages.calls:
        assert kw["thinking"] == {"type": "adaptive"}
        assert kw["max_tokens"] == 128000


def test_direct_models_api_capability_overrides_static_rule(monkeypatch, _anthropic_ready):
    client = _install_client(
        monkeypatch, _FakeClient(text="hello", info=_FakeModelInfo(64000, False))
    )
    list(DirectAnthropicAdapter().stream("x", model="claude-some-new-model"))
    assert "thinking" not in client.messages.calls[0]
    assert client.messages.calls[0]["max_tokens"] == 64000


def test_direct_reads_typed_sdk_model_info(monkeypatch, _anthropic_ready):
    # The installed SDK returns ModelInfo with typed capabilities, not a dict.
    from anthropic.types import ModelInfo

    sup = {"supported": True}
    no = {"supported": False}
    info = ModelInfo.model_validate({
        "id": "claude-haiku-4-5", "type": "model", "display_name": "Claude Haiku 4.5",
        "created_at": "2025-10-01T00:00:00Z", "max_input_tokens": 200000, "max_tokens": 64000,
        "capabilities": {
            "batch": sup, "citations": sup, "code_execution": no, "image_input": sup,
            "pdf_input": sup, "structured_outputs": sup,
            "context_management": {"supported": False, "clear_thinking_20251015": no,
                                   "clear_tool_uses_20250919": no, "compact_20260112": no},
            "effort": {"supported": False, "low": no, "medium": no, "high": no, "max": no},
            "thinking": {"supported": True, "types": {"enabled": sup, "adaptive": no}},
        },
    })
    client = _install_client(monkeypatch, _FakeClient(text="hello", info=info))
    list(DirectAnthropicAdapter().stream("x", model="claude-haiku-4-5"))
    assert "thinking" not in client.messages.calls[0]
    assert client.messages.calls[0]["max_tokens"] == 64000


def test_direct_output_cap_override(monkeypatch, _anthropic_ready):
    monkeypatch.setenv("YUBEN_MAX_OUTPUT_TOKENS", "9000")
    client = _install_client(
        monkeypatch, _FakeClient(text="hello", info=_FakeModelInfo(128000, True))
    )
    list(DirectAnthropicAdapter().stream("x", model="claude-opus-5-5"))
    assert client.messages.calls[0]["max_tokens"] == 9000


def test_direct_stream_max_tokens_stop_raises_truncated(monkeypatch, _anthropic_ready):
    _install_client(
        monkeypatch, _FakeClient(chunks=['{"topic_title": "x",\n', '"summ'], stop_reason="max_tokens")
    )
    with pytest.raises(OutputTruncated):
        list(DirectAnthropicAdapter().stream("x", model="claude-opus-5-5"))


# --- OpenAI-compatible request shape ----------------------------------------
class _Chunk:
    def __init__(self, text, finish_reason=None):
        delta = type("Delta", (), {"content": text})()
        choice = type("Choice", (), {"delta": delta, "finish_reason": finish_reason})()
        self.choices = [choice]


class _FakeCompletions:
    def __init__(self, chunks, text="hello"):
        self._chunks = chunks
        self._text = text
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        if kw.get("stream"):
            return iter(self._chunks)
        message = type("Msg", (), {"content": self._text})()
        return type("Resp", (), {"choices": [type("C", (), {"message": message})()]})()


class _FakeOpenAIClient:
    def __init__(self, chunks=(), text="hello"):
        self.completions = _FakeCompletions(list(chunks), text)
        self.chat = type("Chat", (), {"completions": self.completions})()

    def with_options(self, **kw):
        return self


def _openai_ready(monkeypatch, adapter_id, client):
    import app.adapters.openai_compatible as oa

    adapter = get_adapter(adapter_id)
    monkeypatch.setattr(oa, "_sdk_version", lambda: "1.0")
    monkeypatch.setattr(type(adapter), "_stored_key", lambda self: "sk-test")
    monkeypatch.setattr(type(adapter), "_client", lambda self, key: client)
    return adapter


@pytest.mark.parametrize("adapter_id", ["openai-api", "gemini-api", "openrouter"])
def test_openai_compatible_sends_no_output_cap_by_default(monkeypatch, adapter_id):
    monkeypatch.delenv("YUBEN_MAX_OUTPUT_TOKENS", raising=False)
    client = _FakeOpenAIClient([_Chunk("ok", "stop")])
    adapter = _openai_ready(monkeypatch, adapter_id, client)
    assert adapter.check_env(model="m")["ok"] is True
    assert list(adapter.stream("x", model="m")) == ["ok"]
    for kw in client.completions.calls:
        assert "max_tokens" not in kw and "max_completion_tokens" not in kw


@pytest.mark.parametrize(
    "adapter_id,param",
    [("openai-api", "max_completion_tokens"), ("gemini-api", "max_tokens"),
     ("openrouter", "max_tokens")],
)
def test_openai_compatible_cap_override_uses_provider_param(monkeypatch, adapter_id, param):
    monkeypatch.setenv("YUBEN_MAX_OUTPUT_TOKENS", "4000")
    client = _FakeOpenAIClient([_Chunk("ok", "stop")])
    adapter = _openai_ready(monkeypatch, adapter_id, client)
    adapter.check_env(model="m")
    list(adapter.stream("x", model="m"))
    check_kw, run_kw = client.completions.calls
    assert check_kw[param] == run_kw[param] == 4000
    other = {"max_tokens", "max_completion_tokens"} - {param}
    assert not other & set(check_kw) and not other & set(run_kw)


def test_openai_compatible_length_finish_raises_truncated(monkeypatch):
    monkeypatch.delenv("YUBEN_MAX_OUTPUT_TOKENS", raising=False)
    client = _FakeOpenAIClient([_Chunk('{"topic_title": "x",\n'), _Chunk('"summ', "length")])
    adapter = _openai_ready(monkeypatch, "openai-api", client)
    with pytest.raises(OutputTruncated):
        list(adapter.stream("x", model="gpt-4o"))


# --- registry ---------------------------------------------------------------
def test_get_adapter_and_aliases():
    assert isinstance(get_adapter("claude-code"), ClaudeCodeAdapter)
    assert isinstance(get_adapter("claude"), ClaudeCodeAdapter)  # alias
    assert isinstance(get_adapter("gemini-cli"), GeminiCliAdapter)
    assert isinstance(get_adapter("anthropic-api"), DirectAnthropicAdapter)
    assert isinstance(get_adapter("anthropic"), DirectAnthropicAdapter)  # alias
    with pytest.raises(KeyError):
        get_adapter("nope")


def test_list_adapters_shape_and_order():
    adapters = list_adapters()
    ids = [a.id for a in adapters]
    # Key-paste API providers first (nothing to install), then the hand-written
    # CLIs, then the spec-driven fleet in CLI_SPECS order. Gemini CLI is a stub,
    # so it is hidden from the list (A6) but still resolvable by id.
    assert ids[:6] == [
        "anthropic-api",
        "openai-api",
        "gemini-api",
        "openrouter",
        "ollama",
        "claude-code",
    ]
    assert ids[6:] == [spec.id for spec in CLI_SPECS]
    assert "gemini-cli" not in ids
    assert isinstance(get_adapter("gemini-cli"), GeminiCliAdapter)
    assert len(ids) == len(set(ids)), "adapter ids must be unique"
    for a in adapters:
        assert isinstance(a.installed, bool)
        assert isinstance(a.models, list)


def test_cli_specs_are_well_formed():
    """Every spec must be dispatchable and reachable — the table is the API."""
    for spec in CLI_SPECS:
        assert spec.id and spec.name and spec.binary
        assert spec.prompt_args, "a spec with no prompt args can't be invoked"
        assert spec.install_url.startswith("https://")
        assert isinstance(get_adapter(spec.id), GenericCliAdapter)


def test_generic_cli_builds_expected_argv():
    """The prompt lands in argv and the model flag is only added when asked for."""
    codex = get_adapter("codex-cli")
    assert codex._build_cmd("/bin/codex", "hi", None) == ["/bin/codex", "exec", "hi"]
    assert codex._build_cmd("/bin/codex", "hi", "default") == ["/bin/codex", "exec", "hi"]
    assert codex._build_cmd("/bin/codex", "hi", "o3") == ["/bin/codex", "exec", "hi", "-m", "o3"]
    # extra_args ride after the prompt (Cursor forces plain-text output).
    cursor = get_adapter("cursor-cli")
    assert cursor._build_cmd("/bin/cursor-agent", "hi", None) == [
        "/bin/cursor-agent", "-p", "hi", "--output-format", "text",
    ]
    # A spec with no model flag ignores the model rather than emitting a bare id.
    amp = get_adapter("amp-cli")
    assert amp._build_cmd("/bin/amp", "hi", "some-model") == ["/bin/amp", "-x", "hi"]


def test_codex_models_use_visible_catalog_entries(monkeypatch, tmp_path):
    import json

    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    (tmp_path / "models_cache.json").write_text(json.dumps({"models": [
        {"slug": "test-astra", "visibility": "list"},
        {"slug": "internal", "visibility": "hide"},
        {"slug": "test-astra", "visibility": "list"},
        {"slug": None, "visibility": "list"},
    ]}))
    assert get_adapter("codex-cli").models() == ["default", "test-astra"]
    (tmp_path / "models_cache.json").write_text("broken")
    assert get_adapter("codex-cli").models() == ["default"]


def test_codex_narrative_enforces_schema_and_cleans_up(monkeypatch):
    import json
    from pathlib import Path
    import app.adapters.cli_agents as cli_mod

    paths = []

    def fake_stream(cmd, cwd=None):
        assert cmd[cmd.index("-m") + 1] == "test-astra"
        path = Path(cmd[cmd.index("--output-schema") + 1])
        paths.append(path)
        schema = json.loads(path.read_text())
        assert schema["properties"]["topic_title"]["type"] == "string"
        assert schema["properties"]["summary"]["type"] == "string"
        assert set(schema["required"]) == set(schema["properties"])
        assert schema["additionalProperties"] is False
        yield "result"

    monkeypatch.setattr(cli_mod, "which", lambda _: "/bin/codex")
    monkeypatch.setattr(cli_mod, "stream_process", fake_stream)
    assert list(get_adapter("codex-cli").stream("OUTPUT CONTRACT", model="test-astra")) == ["result"]
    assert not paths[0].exists()


def test_generic_cli_missing_binary_is_graceful(monkeypatch):
    import app.adapters.cli_agents as cli_mod

    monkeypatch.setattr(cli_mod, "which", lambda _b: None)
    res = get_adapter("codex-cli").check_env()
    assert res["ok"] is False
    assert "codex" in res["message"].lower()


def test_generic_cli_prefers_stdout_for_errors(monkeypatch):
    """Same precedence fix as Claude Code: the actionable error is on stdout."""
    import app.adapters.cli_agents as cli_mod

    monkeypatch.setattr(cli_mod, "which", lambda _b: "/bin/codex")
    monkeypatch.setattr(cli_mod, "run_version", lambda _p, **kw: "1.0.0")
    monkeypatch.setattr(
        cli_mod, "run_probe",
        lambda cmd, **kw: _completed(1, "Not logged in. Run 'codex login'.", "warning: noise"),
    )
    res = get_adapter("codex-cli").check_env()
    assert res["ok"] is False
    assert "codex login" in res["message"]
    assert "noise" not in res["message"]


# --- env-check remedies -----------------------------------------------------
def _claude_probe_fails(monkeypatch, stdout, auth_status):
    """Claude Code present, probe fails with `stdout`, auth status as given."""
    monkeypatch.setattr(claude_mod, "which", lambda _b: "/bin/claude")
    monkeypatch.setattr(claude_mod, "run_version", lambda _p, **kw: "2.1.198")
    monkeypatch.setattr(claude_mod, "run_probe", lambda cmd, **kw: _completed(1, stdout, ""))
    adapter = ClaudeCodeAdapter()
    monkeypatch.setattr(adapter, "auth_status", lambda: auth_status)
    return adapter.check_env()


def test_claude_stale_login_names_the_account(monkeypatch):
    """The confusing case: signed in on paper, 401 in practice.

    Reporting "install it" here (the old behaviour) is actively wrong — the CLI
    is right there and the account is known. Say so, and offer a re-auth.
    """
    res = _claude_probe_fails(
        monkeypatch,
        "Failed to authenticate. API Error: 401 Invalid authentication credentials",
        {"loggedIn": True, "email": "someone@example.com", "subscriptionType": "max"},
    )
    assert res["ok"] is False
    assert "someone@example.com" in res["message"]
    assert "stale" in res["message"].lower()
    assert res["remedy"]["kind"] == "sign_in"
    assert res["remedy"]["command"] == "claude auth login"


def test_claude_signed_out_says_so(monkeypatch):
    res = _claude_probe_fails(
        monkeypatch, "API Error: 401 Unauthorized", {"loggedIn": False}
    )
    assert res["ok"] is False
    assert "isn't signed in" in res["message"]
    assert res["remedy"]["kind"] == "sign_in"


def test_claude_non_auth_error_gets_no_remedy(monkeypatch):
    """A crash isn't an auth problem — don't offer a sign-in that can't help."""
    res = _claude_probe_fails(monkeypatch, "Segmentation fault", {"loggedIn": True})
    assert res["ok"] is False
    assert "Segmentation fault" in res["message"]
    assert res["remedy"] is None


def test_claude_missing_binary_offers_install(monkeypatch):
    monkeypatch.setattr(claude_mod, "which", lambda _b: None)
    res = ClaudeCodeAdapter().check_env()
    assert res["ok"] is False
    assert res["remedy"]["kind"] == "install"
    assert res["remedy"]["command"] is None  # nothing to run — just a link


def test_claude_auth_status_survives_garbage(monkeypatch):
    """A CLI that prints non-JSON must not break the check."""
    monkeypatch.setattr(claude_mod, "which", lambda _b: "/bin/claude")
    monkeypatch.setattr(claude_mod, "run_probe", lambda cmd, **kw: _completed(0, "not json"))
    assert ClaudeCodeAdapter().auth_status() is None


def test_remedy_endpoint_ignores_client_supplied_command(monkeypatch):
    """The endpoint takes an adapter id; the command comes from the adapter.

    Guards the one genuinely dangerous shape here — a local endpoint that runs
    shell commands must never take one from the request body.
    """
    captured = {}

    def fake_launch(command):
        captured["command"] = command
        return True, "opened"

    import app.api.config as config_api

    monkeypatch.setattr(
        config_api, "_coerce_env_check",
        lambda raw, requested: config_api.EnvCheckResult(
            ok=False, adapter="claude-code", version=None, message="nope",
            remedy=config_api.EnvCheckRemedy(
                kind="sign_in", label="Sign in", command="claude auth login", url=None
            ),
        ),
    )
    import app.adapters.terminal as term

    monkeypatch.setattr(term, "launch_in_terminal", fake_launch)

    resp = client.post(
        "/api/config/remedy",
        json={"adapter": "claude-code", "command": "rm -rf /", "kind": "sign_in"},
    )
    assert resp.status_code == 200
    # The injected command is ignored entirely; the adapter's own one runs.
    assert captured["command"] == "claude auth login"


# --- OpenAI-compatible adapters ---------------------------------------------
def test_openai_compatible_ids_and_key_requirements():
    assert isinstance(get_adapter("openai-api"), OpenAIAdapter)
    assert isinstance(get_adapter("openai"), OpenAIAdapter)  # alias
    assert isinstance(get_adapter("openrouter"), OpenRouterAdapter)
    assert isinstance(get_adapter("ollama"), OllamaAdapter)
    # Ollama is the only one that needs no credential.
    assert get_adapter("openai-api").requires_key is True
    assert get_adapter("openrouter").requires_key is True
    assert get_adapter("ollama").requires_key is False


def test_gemini_api_preset_wiring():
    from app.adapters.openai_compatible import GeminiAdapter

    adapter = get_adapter("gemini-api")
    assert isinstance(adapter, GeminiAdapter)
    assert isinstance(get_adapter("google"), GeminiAdapter)  # alias
    assert adapter.requires_key is True
    assert adapter.agentic is False
    assert adapter._base_url().startswith("https://generativelanguage.googleapis.com")
    assert "default" in adapter.fallback_models


def test_gemini_api_check_env_without_key_is_graceful(monkeypatch):
    import app.adapters.openai_compatible as oai
    from app.adapters.openai_compatible import GeminiAdapter

    monkeypatch.setattr(oai, "_sdk_version", lambda: "2.46.0")
    adapter = GeminiAdapter()
    monkeypatch.setattr(adapter, "_stored_key", lambda: None)
    res = adapter.check_env()
    assert res["ok"] is False
    assert "gemini api key" in res["message"].lower()


def test_openai_check_env_without_key_is_graceful(monkeypatch):
    import app.adapters.openai_compatible as oai

    monkeypatch.setattr(oai, "_sdk_version", lambda: "2.46.0")
    adapter = OpenAIAdapter()
    monkeypatch.setattr(adapter, "_stored_key", lambda: None)
    res = adapter.check_env()
    assert res["ok"] is False
    assert "openai api key" in res["message"].lower()


def test_openai_compatible_models_fall_back_without_live_fetch(monkeypatch):
    """No key / no network ⇒ the static list, never an exception."""
    import app.adapters.openai_compatible as oai

    monkeypatch.setattr(oai, "_model_cache", {})
    adapter = OpenAIAdapter()
    monkeypatch.setattr(adapter, "_models_live", lambda: (_ for _ in ()).throw(RuntimeError("no net")))
    assert adapter.models() == adapter.fallback_models
    assert "default" in adapter.models()


def test_ollama_resolves_to_an_installed_model(monkeypatch):
    """A static default 404s on most machines — prefer what's actually pulled."""
    adapter = OllamaAdapter()
    monkeypatch.setattr(adapter, "models", lambda: ["default", "qwen2.5:14b"])
    assert adapter._resolve_model(None) == "qwen2.5:14b"
    # An explicit choice always wins over the local-library guess.
    assert adapter._resolve_model("llama3.3") == "llama3.3"


def test_ollama_check_env_without_binary_is_graceful(monkeypatch):
    import app.adapters.openai_compatible as oai

    monkeypatch.setattr(oai, "which", lambda _b: None)
    res = OllamaAdapter().check_env()
    assert res["ok"] is False
    assert "ollama" in res["message"].lower()


def test_check_env_dispatch(monkeypatch):
    impl = get_adapter("claude-code")
    monkeypatch.setattr(
        impl, "check_env",
        lambda model=None: {"ok": True, "adapter": "claude-code", "version": "9.9.9", "message": "probe ok"},
    )
    res = check_env("claude-code")
    assert res == {"ok": True, "adapter": "claude-code", "version": "9.9.9", "message": "probe ok"}


def test_check_env_empty_defaults_to_primary(monkeypatch):
    impl = get_adapter("claude-code")
    monkeypatch.setattr(impl, "check_env", lambda model=None: {"ok": True, "adapter": "claude-code", "version": None, "message": "x"})
    # Empty adapter id falls back to the primary (claude-code).
    assert check_env("")["adapter"] == "claude-code"


def test_check_env_unknown_adapter_graceful():
    res = check_env("banana")
    assert res["ok"] is False
    assert "unknown adapter" in res["message"].lower()


# --- /api/adapters route ----------------------------------------------------
def test_get_adapters_route():
    resp = client.get("/api/adapters")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list) and len(body) == len(list_adapters())
    by_id = {a["id"]: a for a in body}
    assert set(by_id) == {a.id for a in list_adapters()}
    # Every registered adapter is routable and shaped the same way.
    for entry in body:
        assert set(entry) == {"id", "name", "installed", "version", "models"}
    claude = by_id["claude-code"]
    assert claude["name"] == "Claude Code"
    assert "default" in claude["models"]
    assert "gemini-cli" not in by_id
    # The direct Anthropic API adapter is present with its Claude model list.
    api = by_id["anthropic-api"]
    assert api["name"] == "Anthropic API"
    assert "claude-opus-4-8" in api["models"]


def test_env_check_route_wired(monkeypatch):
    # POST /api/config/env-check now delegates to app.adapters.check_env (B2).
    monkeypatch.setattr(
        registry, "check_env",
        lambda adapter, model=None: {"ok": True, "adapter": adapter, "version": "1.2.3", "message": "ok"},
    )
    resp = client.post("/api/config/env-check", json={"adapter": "claude-code"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["adapter"] == "claude-code"
    assert body["version"] == "1.2.3"
