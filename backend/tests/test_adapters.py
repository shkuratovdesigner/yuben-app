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
    AdapterError,
    ClaudeCodeAdapter,
    DirectAnthropicAdapter,
    GeminiCliAdapter,
    check_env,
    get_adapter,
    list_adapters,
)
from app.adapters import base as adapters_base  # noqa: E402
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
    assert "claude-fable-5" in models


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
    def __init__(self, text):
        self.content = [_FakeBlock(text)] if text is not None else []


class _FakeStreamCtx:
    """Mimics client.messages.stream(...) — a context manager exposing text_stream."""

    def __init__(self, chunks, enter_exc=None):
        self._chunks = chunks
        self._enter_exc = enter_exc

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
    def __init__(self, *, text=None, chunks=None, exc=None):
        self._text = text
        self._chunks = chunks or []
        self._exc = exc

    def create(self, **kw):
        if self._exc:
            raise self._exc
        return _FakeResponse(self._text)

    def stream(self, **kw):
        return _FakeStreamCtx(self._chunks, enter_exc=self._exc)


class _FakeClient:
    """with_options() returns self so .messages.create / .stream still resolve."""

    def __init__(self, *, text=None, chunks=None, exc=None):
        self._messages = _FakeMessages(text=text, chunks=chunks, exc=exc)

    @property
    def messages(self):
        return self._messages

    def with_options(self, **kw):
        return self


def _fake_client(**kw):
    return lambda self, key: _FakeClient(**kw)


class _AuthenticationError(Exception):
    """Stand-in whose class name triggers the auth-error branch."""


def test_direct_is_not_agentic():
    # The orchestrator branches on this: direct API adapter can't run tools.
    assert DirectAnthropicAdapter().agentic is False
    assert ClaudeCodeAdapter().agentic is True


def test_direct_models_lists_current_ids():
    models = DirectAnthropicAdapter().models()
    assert models[0] == "default"
    assert "claude-opus-4-8" in models and "claude-fable-5" in models


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
    # Terminal-free Anthropic API path first (Phase 4), then the local CLIs.
    assert ids == ["anthropic-api", "claude-code", "gemini-cli"]
    for a in adapters:
        assert isinstance(a.installed, bool)
        assert isinstance(a.models, list)
    gem = next(a for a in adapters if a.id == "gemini-cli")
    assert gem.models == []


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
    assert isinstance(body, list) and len(body) == 3
    by_id = {a["id"]: a for a in body}
    assert set(by_id) == {"anthropic-api", "claude-code", "gemini-cli"}
    claude = by_id["claude-code"]
    assert set(claude) == {"id", "name", "installed", "version", "models"}
    assert claude["name"] == "Claude Code"
    assert "default" in claude["models"]
    assert by_id["gemini-cli"]["installed"] is False
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
