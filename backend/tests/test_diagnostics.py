"""Phase 6: the per-run diagnostics log and its endpoint.

Runs go through ``run_research_job`` with injected fakes (no network, no keys);
the adapter hooks are exercised with fake SDK clients.
"""
import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("YUBEN_DATA_DIR", tempfile.mkdtemp(prefix="yuben-diag-test-"))
os.environ.setdefault("YUBEN_FORCE_FILE_SECRET", "1")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from contracts.python.models import ResearchRequest  # noqa: E402

from app import diagnostics  # noqa: E402
from app.adapters import direct_anthropic as direct_mod  # noqa: E402
from app.adapters import get_adapter  # noqa: E402
from app.adapters import openai_compatible as oai  # noqa: E402
from app.main import app  # noqa: E402
from app.orchestrator import runner as _runner  # noqa: E402
from app.store import run_store  # noqa: E402

client = TestClient(app)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = json.loads(
    (_REPO_ROOT / "contracts" / "fixtures" / "research-result.longform.json").read_text(encoding="utf-8")
)
_NARRATIVE = "... OUTPUT CONTRACT — emit EXACTLY ONE JSON object ..."
_FAKE_KEY = "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ"


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("YUBEN_DATA_DIR", str(tmp_path))
    run_store.reset()
    _runner.reset()
    diagnostics.stop()
    yield
    diagnostics.stop()
    run_store.reset()
    _runner.reset()


def _request() -> ResearchRequest:
    return ResearchRequest.model_validate(
        dict(
            schema_version="1.0",
            query="how to promote your airbnb",
            format="longform",
            upload_date="all",
            outperformance="highest",
            analyze_titles=True,
            analyze_scripts=False,
            model={"adapter": "openai-api", "model": "gpt-test"},
            max_results=5,
        )
    )


class _ApiAdapter:
    """Non-agentic: expansion gets a keyword array, every narrative call ``answer``."""

    agentic = False

    def __init__(self, answer):
        self._answer = answer
        self.calls = 0

    def stream(self, prompt, *, model=None, cwd=None):
        self.calls += 1
        if self.calls == 1:
            return iter(['["airbnb tips", "airbnb marketing"]'])
        return iter(self._answer.split("\n"))

    def context_window(self, model=None):
        return None


def _run(adapter):
    req = _request()
    run_id = run_store.create_run(req)
    _runner.run_research_job(
        run_id,
        req,
        adapter_factory=lambda _id: adapter,
        pipeline_runner=lambda _r, keywords=None: (list(_FIXTURE["top_videos"]), {"counts": {}}),
        preflight=lambda _a, _m: None,
        verifier=lambda *a: _FIXTURE,
    )
    return run_id


def test_failed_run_writes_a_redacted_log():
    answer = "I could not do that. My key is %s and the answer is cut" % _FAKE_KEY
    run_id = _run(_ApiAdapter(answer))

    path = diagnostics.diagnostics_dir() / ("%s.json" % run_id)
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert _FAKE_KEY not in text and "[redacted]" in text

    data = json.loads(text)
    assert data["adapter"] == "openai-api" and data["model"] == "gpt-test"
    assert data["request"]["query"] == "how to promote your airbnb"
    assert data["outcome"]["code"] == "invalid_output"
    assert [s["name"] for s in data["steps"]] == ["expand", "narrative", "repair"]
    narrative = data["steps"][1]
    assert narrative["prompt_chars"] > 0
    assert narrative["raw"]["head"].startswith("I could not do that.")
    assert narrative["parse_error"] == "No JSON object was found in the agent output."
    assert data["steps"][0]["parse_error"] is None
    assert any("repairing" in p["detail"] for p in data["progress"])


def test_successful_run_is_logged_too():
    good = json.dumps(
        {
            "schema_version": "1.0",
            "topic_title": _FIXTURE["topic_title"],
            "summary": _FIXTURE["summary"],
            "keywords": _FIXTURE["meta"]["keywords"],
            "top_video_ids": [
                {"video_id": v["video_id"], "rank": i + 1}
                for i, v in enumerate(_FIXTURE["top_videos"])
            ],
            "watch_list": _FIXTURE["watch_list"],
            "title_analysis": _FIXTURE["title_analysis"],
            "script_analysis": None,
        }
    )
    run_id = _run(_ApiAdapter(good))
    data = diagnostics.load(run_id)
    assert data["outcome"]["phase"] == "done" and data["outcome"]["code"] is None
    assert [s["name"] for s in data["steps"]] == ["expand", "narrative"]


def test_raw_answer_keeps_only_head_and_tail():
    text = "A" * 10_000 + "MIDDLE" + "Z" * 10_000
    kept = diagnostics.head_tail(text)
    assert kept["chars"] == len(text)
    assert kept["head"] == "A" * diagnostics.RAW_KEEP
    assert kept["tail"] == "Z" * diagnostics.RAW_KEEP
    short = diagnostics.head_tail("short")
    assert short == {"chars": 5, "head": "short", "tail": ""}


def test_note_outside_a_run_is_a_no_op():
    diagnostics.note(usage={"x": 1})
    diagnostics.begin_step("expand", "prompt")
    assert diagnostics.current() is None


def test_schema_is_summarized_not_logged():
    params = {
        "model": "m",
        "output_config": {"format": {"type": "json_schema", "schema": {"properties": {}}}},
        "format": {"$schema": "x", "properties": {}},
    }
    out = diagnostics.summarize_params(params)
    assert out["output_config"]["format"]["schema"] == "<json schema>"
    assert out["format"] == "<json schema>"
    assert out["model"] == "m"


def test_old_logs_are_pruned(monkeypatch):
    monkeypatch.setattr(diagnostics, "KEEP_FILES", 3)
    for i in range(5):
        diag = diagnostics.RunDiagnostics("r_%d" % i)
        diagnostics.save(diag)
        path = diagnostics.diagnostics_dir() / ("r_%d.json" % i)
        os.utime(path, (1_000_000 + i, 1_000_000 + i))
    names = sorted(p.name for p in diagnostics.diagnostics_dir().glob("*.json"))
    assert names == ["r_2.json", "r_3.json", "r_4.json"]


def test_endpoint_returns_the_log_as_text():
    run_id = _run(_ApiAdapter("not json"))
    res = client.get("/api/research/%s/diagnostics" % run_id)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/plain")
    assert res.text.startswith("YuBen diagnostics\nRun: %s" % run_id)
    assert "Adapter: openai-api  Model: gpt-test" in res.text
    assert "Outcome: invalid_output - " in res.text


@pytest.mark.parametrize("run_id", ["r_missing", "..%2F..%2Fyuben", "a.b"])
def test_endpoint_404s_without_a_log(run_id):
    assert client.get("/api/research/%s/diagnostics" % run_id).status_code == 404


# --------------------------------------------------------------------------- #
# Adapter hooks                                                               #
# --------------------------------------------------------------------------- #
class _AStream:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def text_stream(self):
        yield '{"reply": "hello"}'

    def get_final_message(self):
        usage = {"input_tokens": 1200, "output_tokens": 34}
        return type("M", (), {"stop_reason": "end_turn", "usage": usage})()


class _AInfo:
    max_tokens = 128000
    max_input_tokens = 1_000_000
    capabilities = {
        "thinking": {"types": {"adaptive": {"supported": True}}},
        "structured_outputs": {"supported": True},
    }


class _AClient:
    def __init__(self):
        class Messages:
            def stream(self, **kw):
                return _AStream()

        class Models:
            def retrieve(self, model):
                return _AInfo()

        self.messages = Messages()
        self.models = Models()

    def with_options(self, **kw):
        return self


def test_anthropic_records_params_usage_and_stop_reason(monkeypatch):
    monkeypatch.setattr(direct_mod, "_sdk_version", lambda: "1.5.0")
    monkeypatch.setattr(direct_mod, "_stored_key", lambda: _FAKE_KEY)
    monkeypatch.setattr(direct_mod.DirectAnthropicAdapter, "_client", lambda self, key: _AClient())
    monkeypatch.delenv("YUBEN_MAX_OUTPUT_TOKENS", raising=False)
    direct_mod._model_info_cache.clear()

    diag = diagnostics.start("r_anthropic")
    diagnostics.begin_step("narrative", _NARRATIVE)
    list(get_adapter("anthropic-api").stream(_NARRATIVE, model="claude-opus-5-5"))
    step = diag.data["steps"][0]
    direct_mod._model_info_cache.clear()

    assert step["request"]["model"] == "claude-opus-5-5"
    assert step["request"]["max_tokens"] == 128000
    assert step["request"]["output_config"]["format"]["schema"] == "<json schema>"
    assert step["stop_reason"] == "end_turn"
    assert step["usage"] == {"input_tokens": 1200, "output_tokens": 34}
    assert _FAKE_KEY not in json.dumps(step)


def test_openai_records_format_finish_reason_and_usage(monkeypatch):
    usage = {"prompt_tokens": 900, "completion_tokens": 12}

    class Completions:
        def create(self, **kw):
            delta = type("D", (), {"content": '{"reply": "hello"}'})()
            choice = type("C", (), {"delta": delta, "finish_reason": "stop"})()
            return iter(
                [
                    type("K", (), {"choices": [choice], "usage": None})(),
                    type("K", (), {"choices": [], "usage": usage})(),
                ]
            )

    fake = type("Client", (), {"chat": type("Chat", (), {"completions": Completions()})()})()
    monkeypatch.delenv("YUBEN_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.setattr(oai, "_sdk_version", lambda: "3.13.0")
    monkeypatch.setattr(oai, "_model_meta", {})
    adapter = get_adapter("openai-api")
    monkeypatch.setattr(type(adapter), "_stored_key", lambda self: "sk-test")
    monkeypatch.setattr(type(adapter), "_client", lambda self, key: fake)

    diag = diagnostics.start("r_openai")
    diagnostics.begin_step("narrative", _NARRATIVE)
    list(adapter.stream(_NARRATIVE, model="gpt-5"))
    step = diag.data["steps"][0]

    assert step["request"]["model"] == "gpt-5"
    assert step["request"]["stream"] is True
    assert step["request"]["response_format"] == "json_schema"
    assert "messages" not in step["request"]
    assert step["stop_reason"] == "stop"
    assert step["usage"] == usage


def test_cli_records_argv_exit_code_and_stderr(tmp_path):
    from app.adapters import base
    import sys

    script = "import sys; sys.stderr.write('warming up\\n'); print('{\"ok\": true}')"
    diag = diagnostics.start("r_cli")
    diagnostics.begin_step("expand", "prompt")
    lines = list(base.stream_process([sys.executable, "-c", script], stdin_text="x" * 50))
    step = diag.data["steps"][0]

    assert lines == ['{"ok": true}']
    assert step["request"]["argv"][0] == sys.executable
    assert step["request"]["stdin_chars"] == 50
    assert step["exit_code"] == 0 and step["timed_out"] is None
    assert step["stderr"]["head"] == "warming up\n"
