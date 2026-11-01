"""The cross-OS launcher (yuben.py) and the port it threads end to end.

Reliability plan Phase 4, findings W6 (Makefile-only setup with `.venv/bin`
paths) and W7 (port 8000 hardcoded in the Makefile and the origin allowlist).
Windows paths are exercised through injected `which` / runner fakes; nothing
here needs a Windows machine, a real `py` launcher or a free port 8000.
"""
from __future__ import annotations

import importlib.util
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.security import SameOriginGuardMiddleware, allowed_origins, backend_port

_ROOT = Path(__file__).resolve().parents[2]


def _load_launcher():
    spec = importlib.util.spec_from_file_location("yuben_launcher", _ROOT / "yuben.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


yl = _load_launcher()


# --- venv layout -----------------------------------------------------------


def test_venv_python_uses_scripts_on_windows() -> None:
    assert yl.venv_python(Path("v"), windows=True) == Path("v") / "Scripts" / "python.exe"


def test_venv_python_uses_bin_elsewhere() -> None:
    assert yl.venv_python(Path("v"), windows=False) == Path("v") / "bin" / "python"


# --- finding Python --------------------------------------------------------


def _versions(table):
    """A fake runner answering the version probe from {first-arg-tuple: 'x.y'}."""

    def run(cmd):
        key = tuple(cmd[: -2])  # strip `-c <probe>`
        return table.get(key)

    return run


def test_windows_candidates_try_the_py_launcher_newest_first() -> None:
    which = {"py": r"C:\Windows\py.exe", "python": r"C:\Users\u\AppData\Local\Microsoft\WindowsApps\python.exe"}.get
    cands = yl.python_candidates(windows=True, which=which, current=None)
    assert cands[0] == ["py", "-3.14"]
    assert ["py", "-3.10"] in cands and ["py", "-3"] in cands
    assert cands.index(["py", "-3"]) > cands.index(["py", "-3.10"])
    assert cands[-1] == [which("python")]


def test_find_python_skips_old_and_broken_interpreters() -> None:
    cands = [["py", "-3.14"], ["py", "-3"], ["stub-python"], ["good"]]
    run = _versions({("py", "-3"): "3.9\n", ("stub-python",): None, ("good",): "3.12\n"})
    # py -3.14 is not installed (probe fails), py -3 is 3.9, the Store stub
    # does not run: only the real 3.12 qualifies.
    assert yl.find_python(cands, run) == ["good"]


def test_find_python_returns_none_without_a_310() -> None:
    assert yl.find_python([["python3"]], _versions({("python3",): "3.9"})) is None


def test_macos_candidates_include_homebrew_off_path() -> None:
    # A Finder double-click has no Homebrew on PATH; the folder is still found.
    present = {"/opt/homebrew/bin/python3.13"}
    cands = yl.python_candidates(
        windows=False, which=lambda _n: None, exists=present.__contains__, current=None
    )
    if sys.platform == "darwin":
        assert ["/opt/homebrew/bin/python3.13"] in cands
    else:
        assert cands == []


def test_the_launcher_itself_parses_under_python_39() -> None:
    # It must run on macOS's stock 3.9 to find a newer Python. Compile it with
    # 3.9 grammar (feature_version) so 3.10-only syntax cannot slip in.
    import ast

    ast.parse((_ROOT / "yuben.py").read_text(encoding="utf-8"), feature_version=(3, 9))


# --- Node ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("v20.18.1", False),
        ("v20.19.0", True),
        ("v21.7.3", False),
        ("v22.11.0", False),
        ("v22.12.0", True),
        ("v24.1.0", True),
        ("v18.20.0", False),
    ],
)
def test_node_range_matches_package_engines(text: str, ok: bool) -> None:
    assert yl.node_supported(yl.parse_node_version(text)) is ok


def test_unreadable_node_version() -> None:
    assert yl.parse_node_version("not node") is None


# --- port selection --------------------------------------------------------


def test_default_port_when_free() -> None:
    assert yl.pick_port(env={}, is_free=lambda _p: True) == 8000


def test_busy_default_falls_through_to_next_free_port() -> None:
    busy = {8000, 8001}
    assert yl.pick_port(env={}, is_free=lambda p: p not in busy) == 8002


def test_explicit_port_is_used_exactly() -> None:
    assert yl.pick_port(env={"YUBEN_PORT": "8123"}, is_free=lambda _p: True) == 8123


def test_explicit_busy_port_is_an_error_not_a_silent_switch() -> None:
    with pytest.raises(yl.LauncherError, match="8123"):
        yl.pick_port(env={"YUBEN_PORT": "8123"}, is_free=lambda _p: False)


@pytest.mark.parametrize("bad", ["abc", "0", "70000", "-1"])
def test_malformed_explicit_port_is_an_error(bad: str) -> None:
    with pytest.raises(yl.LauncherError, match="YUBEN_PORT"):
        yl.pick_port(env={"YUBEN_PORT": bad}, is_free=lambda _p: True)


def test_all_ports_busy() -> None:
    with pytest.raises(yl.LauncherError, match="in use"):
        yl.pick_port(env={}, is_free=lambda _p: False)


def test_port_free_sees_a_real_listener() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    try:
        assert yl.port_free(port) is False
    finally:
        sock.close()


def test_port_free_sees_an_ipv6_only_listener() -> None:
    # A Vite on [::1] only is invisible to an IPv4 probe, yet `localhost` in a
    # browser reaches it first. Found on a real machine with two dev servers.
    if not socket.has_ipv6:
        pytest.skip("no IPv6")
    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        sock.bind(("::1", 0))
    except OSError:
        pytest.skip("no IPv6 loopback")
    sock.listen(1)
    port = sock.getsockname()[1]
    try:
        assert yl.port_free(port) is False
    finally:
        sock.close()


# --- what the server is started with ---------------------------------------


def test_start_env_sets_the_port_and_spa() -> None:
    env = yl.child_env(8123, serve_spa=True, base={"YUBEN_SERVE_SPA": "0", "KEEP": "1"})
    assert env["YUBEN_PORT"] == "8123"
    assert env["YUBEN_SERVE_SPA"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["KEEP"] == "1"


def test_dev_env_never_serves_the_spa() -> None:
    env = yl.child_env(8000, base={"YUBEN_SERVE_SPA": "1"})
    assert "YUBEN_SERVE_SPA" not in env


def test_server_command_binds_loopback_on_the_chosen_port() -> None:
    cmd = yl.server_command(Path("py"), 8123, reload=True)
    assert cmd[:4] == ["py", "-m", "uvicorn", "app.main:app"]
    assert cmd[cmd.index("--host") + 1] == "127.0.0.1"
    assert cmd[cmd.index("--port") + 1] == "8123"
    assert "--reload" in cmd


def test_stop_uses_taskkill_tree_on_windows(monkeypatch) -> None:
    calls = []

    class Proc:
        pid = 42

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(yl, "is_windows", lambda: True)
    monkeypatch.setattr(yl.subprocess, "call", lambda cmd, **_k: calls.append(cmd) or 0)
    yl.stop(Proc())
    assert calls == [["taskkill", "/T", "/F", "/PID", "42"]]


def test_cli_rejects_unknown_command() -> None:
    out = subprocess.run(
        [sys.executable, str(_ROOT / "yuben.py"), "nope"], capture_output=True, text=True
    )
    assert out.returncode == 2


# --- smoke (Phase 5) ---------------------------------------------------------


def _smoke_args(*argv):
    return yl.build_parser().parse_args(["smoke", *argv])


def test_smoke_runs_the_backend_module_in_the_venv() -> None:
    args = _smoke_args("--adapter", "openai-api", "--model", "gpt-4o")
    assert yl.smoke_command(Path("py"), args) == [
        "py", "-m", "app.smoke", "--adapter", "openai-api", "--format", "longform",
        "--model", "gpt-4o",
    ]


def test_smoke_passes_format_and_query_and_omits_unset_options() -> None:
    args = _smoke_args("--adapter", "ollama", "--format", "shorts", "--query", "как расти")
    cmd = yl.smoke_command(Path("py"), args)
    assert "--model" not in cmd
    assert cmd[cmd.index("--format") + 1] == "shorts"
    assert cmd[cmd.index("--query") + 1] == "как расти"


def test_smoke_requires_an_adapter() -> None:
    with pytest.raises(SystemExit):
        _smoke_args("--model", "gpt-4o")


def test_smoke_reports_failure_and_runs_from_the_backend_folder(monkeypatch) -> None:
    seen = {}

    def fake_call(cmd, cwd=None, env=None):
        seen.update(cmd=cmd, cwd=cwd, env=env)
        return 1

    monkeypatch.setattr(yl, "venv_ok", lambda *a, **k: True)
    monkeypatch.setattr(yl.subprocess, "call", fake_call)
    with pytest.raises(yl.LauncherError, match="smoke test failed"):
        yl.cmd_smoke(_smoke_args("--adapter", "openai-api"))
    assert seen["cwd"] == str(yl.BACKEND)
    assert seen["env"]["PYTHONIOENCODING"] == "utf-8"


def test_smoke_without_a_venv_says_to_install(monkeypatch) -> None:
    monkeypatch.setattr(yl, "venv_ok", lambda *a, **k: False)
    with pytest.raises(yl.LauncherError, match="yuben.py install"):
        yl.cmd_smoke(_smoke_args("--adapter", "openai-api"))


# --- wrappers --------------------------------------------------------------


def test_makefile_and_double_click_scripts_delegate_to_the_launcher() -> None:
    makefile = (_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "yuben.py" in makefile and ".venv/bin/uvicorn" not in makefile
    assert "yuben.py start" in (_ROOT / "start.command").read_text(encoding="utf-8")
    cmd = (_ROOT / "start.cmd").read_bytes()
    assert b"yuben.py start" in cmd and b"\r\n" in cmd


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits")
def test_start_command_is_executable() -> None:
    import os

    assert os.access(_ROOT / "start.command", os.X_OK)


# --- the origin guard follows YUBEN_PORT -----------------------------------


def test_backend_port_defaults_and_reads_env() -> None:
    assert backend_port({}) == 8000
    assert backend_port({"YUBEN_PORT": " 8123 "}) == 8123


def test_backend_port_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="YUBEN_PORT"):
        backend_port({"YUBEN_PORT": "eighty"})


def test_allowed_origins_name_the_configured_port() -> None:
    origins = allowed_origins(8123)
    assert "http://localhost:8123" in origins and "http://127.0.0.1:8123" in origins
    assert "http://localhost:5173" in origins
    assert "http://localhost:8000" not in origins


def _guarded_app() -> TestClient:
    app = FastAPI()

    @app.post("/api/thing")
    def thing():
        return {"ok": True}

    app.add_middleware(SameOriginGuardMiddleware)
    return TestClient(app)


def test_guard_honours_a_non_default_port(monkeypatch) -> None:
    monkeypatch.setenv("YUBEN_PORT", "8123")
    client = _guarded_app()
    ok = client.post("/api/thing", headers={"Origin": "http://localhost:8123"})
    assert ok.status_code == 200
    stale = client.post("/api/thing", headers={"Origin": "http://localhost:8000"})
    assert stale.status_code == 403


def test_guard_defaults_to_8000(monkeypatch) -> None:
    monkeypatch.delenv("YUBEN_PORT", raising=False)
    client = _guarded_app()
    assert client.post("/api/thing", headers={"Origin": "http://localhost:8000"}).status_code == 200
