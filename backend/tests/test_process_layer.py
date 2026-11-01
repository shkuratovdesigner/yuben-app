"""Reliability Phase 3: one process layer that works on every OS.

Real cheap subprocesses (``sys.executable -c``) cover stdin delivery, UTF-8
decoding and process-tree kills on this machine. Windows can't run here, so
its branches (``taskkill /T /F``, new process group, the 32,767-character
command line) are also tested by forcing ``base._IS_WINDOWS`` and mocking the
calls. Phase 5 runs this file on Windows, macOS and Linux in CI: the fake-CLI
round trip, the ``.cmd`` shim and the tree kills then exercise the real thing.
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import subprocess
import sys
import threading
import time

import pytest

from app.adapters import base, get_adapter
from app.adapters.base import AdapterError, KIND_CONTEXT_TOO_LONG

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")

#: Measured size of the narrative prompt (reliability plan W1).
NARRATIVE_PROMPT = "Видео 🎬 & 100% \"quoted\" ^caret\n" * 1400  # ~43k chars


def _py(code: str) -> list:
    return [sys.executable, "-c", code]


def _alive(pid: int) -> bool:
    if os.name == "nt":
        return _alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover - exists, owned by someone else
        return True
    # A zombie still answers signal 0; ask ps whether it has really gone.
    out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return bool(out.stdout.strip()) and not out.stdout.strip().startswith("Z")


def _alive_windows(pid: int) -> bool:
    # os.kill(pid, 0) on Windows is TerminateProcess, not a probe; ask the
    # kernel for the exit code instead.
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _wait_dead(pid: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return False


# --- prompts on stdin (W1, W2) ----------------------------------------------
def test_large_prompt_reaches_stdin_without_deadlock():
    """The child fills its stdout pipe before reading stdin. Writing stdin on
    the consuming thread would deadlock; the feeder thread must not."""
    code = (
        "import sys\n"
        "for _ in range(4000): print('x' * 60)\n"
        "data = sys.stdin.read()\n"
        "print('LEN', len(data))\n"
    )
    prompt = "p" * 300_000  # far beyond a 64 KiB pipe buffer
    lines = list(base.stream_process(_py(code), stdin_text=prompt, total_timeout=60))
    assert lines[-1] == "LEN 300000"
    assert len(lines) == 4001


def test_stdin_prompt_round_trips_unicode_and_shell_characters():
    code = "import sys; sys.stdout.write(sys.stdin.read())"
    lines = list(base.stream_process(_py(code), stdin_text=NARRATIVE_PROMPT))
    assert "\n".join(lines) + "\n" == NARRATIVE_PROMPT


def test_child_that_ignores_stdin_is_not_an_error():
    lines = list(base.stream_process(_py("print('done')"), stdin_text="z" * 500_000))
    assert lines == ["done"]


def test_without_a_prompt_stdin_is_closed():
    """No prompt means DEVNULL, so a CLI waiting on stdin sees EOF at once."""
    lines = list(base.stream_process(_py("import sys; print(repr(sys.stdin.read()))")))
    assert lines == ["''"]


def test_run_probe_sends_input_on_stdin():
    proc = base.run_probe(
        _py("import sys; print(sys.stdin.read().upper())"), timeout=30, input="привет hello"
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == "ПРИВЕТ HELLO"


def test_claude_code_narrative_command_line_holds_only_flags(monkeypatch):
    from app.adapters import claude_code as claude_mod

    seen = {}

    def fake_stream(cmd, cwd=None, stdin_text=None):
        seen.update(cmd=cmd, stdin=stdin_text)
        yield "{}"

    monkeypatch.setattr(claude_mod, "which", lambda _b: "C:\\npm\\claude.cmd")
    monkeypatch.setattr(claude_mod, "stream_process", fake_stream)
    list(claude_mod.ClaudeCodeAdapter().stream(NARRATIVE_PROMPT, model="claude-opus-5-5"))
    assert seen["stdin"] == NARRATIVE_PROMPT
    assert all("\n" not in arg for arg in seen["cmd"]), "no multi-line arg reaches cmd.exe"
    assert len(subprocess.list2cmdline(seen["cmd"])) < 200


def test_claude_code_probe_sends_hello_on_stdin(monkeypatch):
    from app.adapters import claude_code as claude_mod

    seen = {}

    def fake_probe(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        return subprocess.CompletedProcess(cmd, 0, "hello", "")

    monkeypatch.setattr(claude_mod, "which", lambda _b: "/bin/claude")
    monkeypatch.setattr(claude_mod, "run_version", lambda _p, **kw: "2.0.0")
    monkeypatch.setattr(claude_mod, "run_probe", fake_probe)
    assert claude_mod.ClaudeCodeAdapter().check_env()["ok"] is True
    assert seen["cmd"] == ["/bin/claude", "-p"]
    assert seen["input"] == "Reply with exactly: hello"


@pytest.mark.parametrize(
    "adapter_id", ["codex-cli", "opencode-cli", "qwen-cli", "copilot-cli", "amp-cli"]
)
def test_stdin_clis_stream_prompt_on_stdin(monkeypatch, adapter_id):
    import app.adapters.cli_agents as cli_mod

    seen = {}

    def fake_stream(cmd, cwd=None, stdin_text=None):
        seen.update(cmd=cmd, stdin=stdin_text)
        yield "ok"

    monkeypatch.setattr(cli_mod, "which", lambda _b: "/bin/tool")
    monkeypatch.setattr(cli_mod, "stream_process", fake_stream)
    assert list(get_adapter(adapter_id).stream(NARRATIVE_PROMPT)) == ["ok"]
    assert seen["stdin"] == NARRATIVE_PROMPT
    assert NARRATIVE_PROMPT not in seen["cmd"]


def test_generic_probe_uses_the_same_stdin_path(monkeypatch):
    import app.adapters.cli_agents as cli_mod

    seen = {}

    def fake_probe(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        return subprocess.CompletedProcess(cmd, 0, "hello", "")

    monkeypatch.setattr(cli_mod, "which", lambda _b: "/bin/amp")
    monkeypatch.setattr(cli_mod, "run_version", lambda _p, **kw: "1.0")
    monkeypatch.setattr(cli_mod, "run_probe", fake_probe)
    assert get_adapter("amp-cli").check_env()["ok"] is True
    assert seen["cmd"] == ["/bin/amp", "-x"]
    assert seen["input"] == "Reply with exactly: hello"


# A stand-in agent CLI: reads the prompt from stdin as UTF-8 bytes, echoes it,
# then reports a hash of what arrived. Newlines are normalised first because a
# text-mode pipe on Windows writes "\n" as "\r\n"; every other byte must match.
_FAKE_CLI = (
    "import hashlib, sys\n"
    "data = sys.stdin.buffer.read().decode('utf-8')\n"
    "out = sys.stdout.buffer\n"
    "out.write(data.encode('utf-8'))\n"
    "digest = hashlib.sha256(data.replace('\\r\\n', '\\n').encode('utf-8')).hexdigest()\n"
    "out.write(('\\nSHA ' + digest + '\\n').encode('ascii'))\n"
)

#: Phase 5: 100,000 characters of Cyrillic, emoji and cmd.exe metacharacters.
LONG_PROMPT = ("Как набрать 1M подписчиков 🚀🎬 & 100% \"quoted\" ^caret <pipe|> %PATH%\n" * 2000)[:100_000]


def _fake_cli(tmp_path) -> str:
    script = tmp_path / "fake_cli.py"
    script.write_text(_FAKE_CLI, encoding="utf-8")
    return str(script)


def _assert_round_trip(lines):
    assert lines[-1] == "SHA " + hashlib.sha256(LONG_PROMPT.encode("utf-8")).hexdigest()
    assert "\n".join(lines[:-1]) == LONG_PROMPT


def test_fake_cli_round_trips_a_100k_unicode_prompt(tmp_path):
    assert len(LONG_PROMPT) == 100_000
    cmd = [sys.executable, _fake_cli(tmp_path)]
    _assert_round_trip(list(base.stream_process(cmd, stdin_text=LONG_PROMPT, total_timeout=60)))


@pytest.mark.skipif(os.name != "nt", reason="npm-style .cmd shims exist only on Windows")
def test_fake_cli_behind_a_cmd_shim_round_trips_a_100k_prompt(tmp_path):
    """W2: npm installs CLIs as .cmd shims run by cmd.exe. With the prompt on
    stdin the command line holds no text for cmd.exe to mangle."""
    shim = tmp_path / "fake-cli.cmd"
    shim.write_text(
        '@echo off\r\n"%s" "%s" %%*\r\n' % (sys.executable, _fake_cli(tmp_path)),
        encoding="utf-8",
    )
    lines = list(base.stream_process([str(shim)], stdin_text=LONG_PROMPT, total_timeout=60))
    _assert_round_trip(lines)


# --- command-line limits for argv-prompt CLIs ---------------------------------
def test_windows_rejects_an_argv_prompt_past_the_limit_before_spawning(monkeypatch):
    """Cursor still takes the prompt on argv. On Windows the narrative prompt
    can't fit, so the run stops with a clear message and nothing is spawned."""
    monkeypatch.setattr(base, "_IS_WINDOWS", True)

    def no_spawn(*_a, **_kw):  # pragma: no cover - must not be reached
        raise AssertionError("spawned a command Windows would reject")

    monkeypatch.setattr(base.subprocess, "Popen", no_spawn)
    cmd, stdin_text = get_adapter("cursor-cli")._build_cmd(
        "C:\\npm\\cursor-agent.cmd", NARRATIVE_PROMPT, None
    )
    assert stdin_text is None
    with pytest.raises(AdapterError) as exc:
        list(base.stream_process(cmd))
    assert exc.value.kind == KIND_CONTEXT_TOO_LONG
    assert "32,767" in str(exc.value)
    with pytest.raises(OSError):
        base.run_probe(cmd, timeout=5)


def test_windows_allows_short_command_lines(monkeypatch):
    monkeypatch.setattr(base, "_IS_WINDOWS", True)
    assert base.command_line_problem(["C:\\npm\\claude.cmd", "-p", "--verbose"]) is None


def test_posix_rejects_one_argument_over_128_kib(monkeypatch):
    monkeypatch.setattr(base, "_IS_WINDOWS", False)
    assert base.command_line_problem(["tool", "a" * 200_000]) is not None
    # Non-Latin text counts in bytes: 50k Cyrillic chars are ~100 KiB, still fine.
    assert base.command_line_problem(["tool", "ж" * 50_000]) is None
    assert base.command_line_problem(["tool", "ж" * 70_000]) is not None


# --- UTF-8 everywhere (W3) ----------------------------------------------------
def test_stdout_is_decoded_as_utf8_whatever_the_locale():
    code = (
        "import sys\n"
        "sys.stdout.buffer.write('Как я набрал 1M 🚀\\n'.encode('utf-8'))\n"
        "sys.stdout.buffer.write(b'bad \\xff byte\\n')\n"
    )
    lines = list(base.stream_process(_py(code)))
    assert lines[0] == "Как я набрал 1M 🚀"
    assert lines[1] == "bad \ufffd byte"  # replaced, not a crash


def test_children_are_told_to_write_utf8(monkeypatch):
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    proc = base.run_probe(
        _py("import os; print(os.environ.get('PYTHONIOENCODING'))"), timeout=30
    )
    assert proc.stdout.strip() == "utf-8"


def test_research_log_survives_a_console_that_cannot_encode(monkeypatch):
    """W4: a Cyrillic keyword on a cp1252 console used to raise and kill the run."""
    from app.pipeline._paths import install_youtube_research_alias

    install_youtube_research_alias()
    import youtube_research.longform_research as longform  # type: ignore

    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("yuben.research")
    monkeypatch.setattr(logging, "raiseExceptions", False)
    logger.addHandler(handler)
    try:
        longform.log("[1/3] search: как набрать подписчиков 🚀")  # must not raise
    finally:
        logger.removeHandler(handler)


# --- kill the whole process tree (W5) -----------------------------------------
_TREE = (
    "import subprocess, sys, time\n"
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
    "print(child.pid, flush=True)\n"
    "time.sleep(120)\n"
)


def test_cancel_kills_grandchildren_too():
    box: dict = {}
    started = threading.Event()

    def worker():
        box["ident"] = threading.get_ident()
        try:
            for line in base.stream_process(_py(_TREE)):
                box["grandchild"] = int(line)
                started.set()
        except Exception as exc:
            box["exc"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    assert started.wait(20), "tree never started"
    assert _alive(box["grandchild"])

    assert base.terminate_for_thread(box["ident"]) == 1
    thread.join(15)
    assert not thread.is_alive()
    assert _wait_dead(box["grandchild"]), "the grandchild outlived cancel"


def test_idle_timeout_kills_grandchildren_too():
    lines: list = []
    with pytest.raises(AdapterError, match="no output"):
        for line in base.stream_process(_py(_TREE), idle_timeout=2.0, total_timeout=None):
            lines.append(int(line))
    assert lines and _wait_dead(lines[0])


def test_probe_timeout_kills_grandchildren_too(tmp_path):
    pid_file = tmp_path / "pid"
    code = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        "open(sys.argv[1], 'w', encoding='utf-8').write(str(child.pid))\n"
        "time.sleep(120)\n"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        base.run_probe([sys.executable, "-c", code, str(pid_file)], timeout=3)
    assert _wait_dead(int(pid_file.read_text(encoding="utf-8")))


@posix_only
def test_children_start_in_their_own_session():
    proc = base.run_probe(_py("import os; print(os.getsid(0) == os.getpid())"), timeout=30)
    assert proc.stdout.strip() == "True"


class _FakeProc:
    pid = 4242

    def __init__(self):
        self.terminated = self.killed = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def test_windows_kill_uses_taskkill_on_the_tree(monkeypatch):
    calls = []
    monkeypatch.setattr(base, "_IS_WINDOWS", True)
    monkeypatch.setattr(base.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    proc = _FakeProc()
    base.kill_tree(proc)
    assert calls == [["taskkill", "/PID", "4242", "/T", "/F"]]
    assert not proc.terminated, "the tree call worked; no fallback needed"


def test_windows_kill_falls_back_to_the_child_when_taskkill_fails(monkeypatch):
    monkeypatch.setattr(base, "_IS_WINDOWS", True)

    def broken(*_a, **_kw):
        raise FileNotFoundError("taskkill")

    monkeypatch.setattr(base.subprocess, "run", broken)
    proc = _FakeProc()
    base.kill_tree(proc, force=True)
    assert proc.killed


def test_windows_spawns_a_new_process_group(monkeypatch):
    monkeypatch.setattr(base, "_IS_WINDOWS", True)
    monkeypatch.setattr(base.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
    assert base._spawn_flags() == {"creationflags": 0x200}


def test_kill_tree_ignores_a_finished_process():
    proc = subprocess.Popen(_py("pass"))
    proc.wait()
    base.kill_tree(proc)  # no error, nothing to do


# --- parallel link checks (R1) ------------------------------------------------
class _SlowVerifier:
    def __init__(self, delay: float, fail=()):
        self.delay = delay
        self.fail = set(fail)
        self.calls = 0
        self.lock = threading.Lock()

    def verify(self, video_id):
        with self.lock:
            self.calls += 1
        time.sleep(self.delay)
        if video_id in self.fail:
            raise RuntimeError("boom")
        return "dead" if video_id.endswith("d") else "verified"


def test_link_checks_run_in_parallel():
    from app.verify.assemble import _verify_links

    ids = ["v{:02d}".format(i) for i in range(16)] + ["xxd"]
    started = time.monotonic()
    out = _verify_links(_SlowVerifier(0.3, fail={"v03"}), ids)
    assert time.monotonic() - started < 2.0  # 17 × 0.3 s would be 5 s in series
    assert out["v00"] == "verified" and out["xxd"] == "dead"
    assert out["v03"] is None  # a raising verifier is inconclusive


def test_link_checks_stop_at_the_budget():
    from app.verify.assemble import _verify_links

    started = time.monotonic()
    out = _verify_links(_SlowVerifier(3.0), ["a", "b"], budget=0.5)
    assert time.monotonic() - started < 1.5
    assert out == {}


def test_link_checks_stop_on_cancel():
    from app.verify.assemble import _verify_links

    started = time.monotonic()
    out = _verify_links(_SlowVerifier(3.0), ["a", "b"], should_stop=lambda: True)
    assert time.monotonic() - started < 1.0
    assert out == {}


def test_runner_passes_the_cancel_check_to_link_verification(monkeypatch):
    from app.orchestrator import runner
    import app.verify as verify_pkg

    seen = {}

    def fake_assemble(request, agent_result, videos, meta, *, should_stop=None):
        seen["should_stop"] = should_stop
        return "result"

    monkeypatch.setattr(verify_pkg, "assemble_and_verify", fake_assemble)
    monkeypatch.setattr(runner, "is_cancelled", lambda run_id: run_id == "r_1")
    assert runner._default_verifier(None, None, [], {"run_id": "r_1"}) == "result"
    assert seen["should_stop"]() is True


# --- cached, parallel adapter detection (R2) ----------------------------------
class _FakeAdapter:
    selectable = True

    def __init__(self, ident: str, delay: float):
        self.id = self.name = ident
        self.delay = delay
        self.detects = 0

    def detect(self):
        self.detects += 1
        time.sleep(self.delay)
        return {"installed": True, "version": "1.0"}

    def models(self):
        return ["default"]


def test_adapter_detection_is_parallel_cached_and_resettable(monkeypatch):
    import app.adapters as registry

    fakes = [_FakeAdapter("fake-{}".format(i), 0.3) for i in range(5)]
    monkeypatch.setattr(registry, "_ADAPTERS", {f.id: f for f in fakes})

    started = time.monotonic()
    first = registry.list_adapters()
    assert time.monotonic() - started < 1.2  # 5 × 0.3 s would be 1.5 s in series
    assert [a.id for a in first] == [f.id for f in fakes]  # display order kept

    registry.list_adapters()
    assert all(f.detects == 1 for f in fakes), "second call within the TTL re-detected"

    registry.forget_detection()
    registry.list_adapters()
    assert all(f.detects == 2 for f in fakes)


def test_saving_a_key_clears_cached_detection(monkeypatch):
    from fastapi.testclient import TestClient

    import app.adapters as registry
    from app.main import app

    fake = _FakeAdapter("fake", 0.0)
    monkeypatch.setattr(registry, "_ADAPTERS", {"fake": fake})
    registry.list_adapters()
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    resp = client.post(
        "/api/config/key",
        json={"provider": "openai", "key": "sk-test-1234567890"},
        headers={"Origin": "http://127.0.0.1:8000"},
    )
    assert resp.status_code == 200, resp.text
    registry.list_adapters()
    assert fake.detects == 2
