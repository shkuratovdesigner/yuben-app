#!/usr/bin/env python3
"""YuBen launcher: install and start the app the same way on every OS.

    python yuben.py install    backend venv + frontend node deps
    python yuben.py start      build, then serve the whole app on one port
    python yuben.py dev        backend + Vite with hot reload
    python yuben.py test       backend pytest + frontend typecheck
    python yuben.py build      production frontend build
    python yuben.py smoke --adapter openai-api --model gpt-4o
                               test one model on bundled videos, no YouTube quota

Standard library only, and written to run on Python 3.9: that is what macOS
still ships as ``python3``, and this script is what finds a newer one. The
backend itself needs 3.10+ (fastapi 0.139 dropped 3.9), so ``install`` locates
a suitable interpreter (``py -3.x`` on Windows) and builds the venv from it.

The Makefile, ``start.command`` (macOS) and ``start.cmd`` (Windows) are thin
wrappers around this file, so there is one implementation of every step.
Reliability plan findings W6 (Makefile-only, ``.venv/bin`` paths) and W7
(port 8000 hardcoded).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
VENV = BACKEND / ".venv"

MIN_PYTHON = (3, 10)
#: Python versions to try, newest first.
PYTHON_MINORS = (14, 13, 12, 11, 10)

DEFAULT_PORT = 8000
#: How many ports past the default to try when it is busy.
PORT_SCAN = 20
PORT_ENV = "YUBEN_PORT"
#: The Vite dev server's port. Fixed (strictPort in vite.config.ts) because
#: the backend's origin allowlist names it.
DEV_FRONTEND_PORT = 5173

#: Install folders that are often missing from PATH: a Finder double-click
#: gets a minimal PATH without Homebrew, and python.org installs live in the
#: framework folder.
_MAC_PYTHON_DIRS = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    *("/Library/Frameworks/Python.framework/Versions/3.%d/bin" % m for m in PYTHON_MINORS),
)

Runner = Callable[[Sequence[str]], Optional[str]]


class LauncherError(Exception):
    """A problem the user can fix; printed without a traceback."""


def is_windows() -> bool:
    return os.name == "nt"


# --- Python ----------------------------------------------------------------


def venv_python(venv: Path = VENV, windows: Optional[bool] = None) -> Path:
    """The venv's interpreter: ``Scripts\\python.exe`` on Windows, ``bin/python`` elsewhere."""
    windows = is_windows() if windows is None else windows
    if windows:
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _run_capture(cmd: Sequence[str]) -> Optional[str]:
    """Run a probe command; return its stdout, or None if it failed to run or exited non-zero."""
    try:
        out = subprocess.run(
            list(cmd),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout


_VERSION_PROBE = "import sys; print('%d.%d' % sys.version_info[:2])"


def python_version(cmd: Sequence[str], run: Runner = _run_capture) -> Optional[Tuple[int, int]]:
    """Ask an interpreter its version. None when it does not run.

    Running it, rather than trusting the name, also skips the Windows Store
    ``python.exe`` stub, which exists on PATH but only opens the Store.
    """
    out = run([*cmd, "-c", _VERSION_PROBE])
    if not out:
        return None
    m = re.search(r"(\d+)\.(\d+)", out)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def python_candidates(
    windows: Optional[bool] = None,
    which: Callable[[str], Optional[str]] = shutil.which,
    exists: Callable[[str], bool] = os.path.exists,
    current: Optional[str] = sys.executable,
) -> List[List[str]]:
    """Commands that might start a Python 3.10+, in the order to try them."""
    windows = is_windows() if windows is None else windows
    found: List[List[str]] = []

    def add(cmd: List[str]) -> None:
        if cmd not in found:
            found.append(cmd)

    if current:
        add([current])
    if windows and which("py"):
        # The py launcher picks among installed versions by flag.
        for minor in PYTHON_MINORS:
            add(["py", "-3.%d" % minor])
        add(["py", "-3"])
    names = ["python3.%d" % m for m in PYTHON_MINORS] + ["python3", "python"]
    for name in names:
        path = which(name)
        if path:
            add([path])
    if not windows and sys.platform == "darwin":
        for folder in _MAC_PYTHON_DIRS:
            for name in names[:-1]:
                path = os.path.join(folder, name)
                if exists(path):
                    add([path])
    return found


def find_python(
    candidates: Optional[List[List[str]]] = None, run: Runner = _run_capture
) -> Optional[List[str]]:
    """The first candidate that runs and is at least 3.10."""
    for cmd in python_candidates() if candidates is None else candidates:
        version = python_version(cmd, run)
        if version and version >= MIN_PYTHON:
            return cmd
    return None


def venv_ok(venv: Path = VENV, run: Runner = _run_capture) -> bool:
    py = venv_python(venv)
    if not py.exists():
        return False
    version = python_version([str(py)], run)
    return bool(version and version >= MIN_PYTHON)


# --- Node ------------------------------------------------------------------


def parse_node_version(text: str) -> Optional[Tuple[int, int, int]]:
    m = re.search(r"v?(\d+)\.(\d+)\.(\d+)", text or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def node_supported(version: Tuple[int, int, int]) -> bool:
    """``^20.19.0 || >=22.12.0``, the range Vite and oxlint need (package.json engines)."""
    major, minor, _ = version
    if major == 20:
        return minor >= 19
    if major == 22:
        return minor >= 12
    return major > 22


def tool(name: str) -> str:
    """Resolve a Node tool. On Windows ``npm`` is ``npm.cmd``, which only a PATH lookup finds."""
    path = shutil.which(name)
    if not path:
        raise LauncherError(
            "%s not found on PATH. Install Node 20.19+ or 22.12+ from https://nodejs.org "
            "and open a new terminal." % name
        )
    return path


def check_node(run: Runner = _run_capture) -> Tuple[int, int, int]:
    out = run([tool("node"), "--version"])
    version = parse_node_version(out or "")
    if not version:
        raise LauncherError("Could not read the Node version (`node --version`).")
    if not node_supported(version):
        raise LauncherError(
            "Node %d.%d.%d is too old or unsupported. YuBen needs Node 20.19+ or 22.12+ "
            "(21.x does not work). Get it from https://nodejs.org." % version
        )
    return version


# --- Port ------------------------------------------------------------------


def parse_port(value: str) -> int:
    try:
        port = int(str(value).strip())
    except ValueError:
        port = 0
    if not 1 <= port <= 65535:
        raise LauncherError("%s must be a port number from 1 to 65535, got %r." % (PORT_ENV, value))
    return port


def _answers(family: int, host: str, port: int) -> bool:
    probe = socket.socket(family, socket.SOCK_STREAM)
    probe.settimeout(0.3)
    try:
        return probe.connect_ex((host, port)) == 0
    except OSError:  # no IPv6 on this machine
        return False
    finally:
        probe.close()


def port_free(port: int, host: str = "127.0.0.1") -> bool:
    """True when nothing answers on the port, over IPv4 or IPv6, and it can be bound.

    Both loopbacks matter: a browser resolves ``localhost`` to ``::1`` first,
    so a server listening only on ``[::1]:8000`` would answer instead of
    YuBen's IPv4 one. The connect checks come before the bind because on
    Windows a bind can succeed next to a server on 0.0.0.0.
    """
    if _answers(socket.AF_INET, "127.0.0.1", port):
        return False
    if socket.has_ipv6 and _answers(socket.AF_INET6, "::1", port):
        return False
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
    except OSError:
        return False
    finally:
        sock.close()
    return True


def pick_port(
    env: Optional[Dict[str, str]] = None,
    is_free: Callable[[int], bool] = port_free,
) -> int:
    """The backend port.

    An explicit ``YUBEN_PORT`` is used exactly, and a busy one is an error: the
    user asked for that port. Without it, the first free port from 8000 up.
    """
    env = os.environ if env is None else env
    explicit = env.get(PORT_ENV)
    if explicit:
        port = parse_port(explicit)
        if not is_free(port):
            raise LauncherError(
                "Port %d (%s) is in use. Stop whatever is using it, or pick another port."
                % (port, PORT_ENV)
            )
        return port
    for port in range(DEFAULT_PORT, DEFAULT_PORT + PORT_SCAN):
        if port == DEV_FRONTEND_PORT:
            continue
        if is_free(port):
            return port
    raise LauncherError(
        "Ports %d-%d are all in use. Set %s to a free port."
        % (DEFAULT_PORT, DEFAULT_PORT + PORT_SCAN - 1, PORT_ENV)
    )


# --- Processes -------------------------------------------------------------


def child_env(port: int, serve_spa: bool = False, base: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Environment for the backend and Vite: one port, UTF-8 output.

    ``YUBEN_PORT`` reaches the backend's origin allowlist and the Vite proxy,
    so the port changes end to end. ``YUBEN_SERVE_SPA`` is set only for
    ``start``; under ``dev`` the backend stays a JSON API (see backend/app/spa.py).
    """
    env = dict(os.environ if base is None else base)
    env[PORT_ENV] = str(port)
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("YUBEN_SERVE_SPA", None)
    if serve_spa:
        env["YUBEN_SERVE_SPA"] = "1"
    return env


def server_command(python: Path, port: int, reload: bool = False) -> List[str]:
    cmd = [str(python), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)]
    if reload:
        cmd.append("--reload")
    return cmd


def run(cmd: Sequence[str], cwd: Path, env: Optional[Dict[str, str]] = None) -> None:
    print("> " + " ".join(str(c) for c in cmd), flush=True)
    code = subprocess.call(list(cmd), cwd=str(cwd), env=env)
    if code != 0:
        raise LauncherError("Command failed (exit %d): %s" % (code, " ".join(str(c) for c in cmd)))


def stop(proc: "subprocess.Popen[bytes]") -> None:
    """Stop a child and everything it started.

    On Windows ``npm`` is a ``.cmd`` shim, so terminating the direct child would
    leave Vite running; ``taskkill /T`` takes the whole tree.
    """
    if proc.poll() is not None:
        return
    if is_windows():
        subprocess.call(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def open_when_ready(url: str, health: str, timeout: float = 60.0) -> threading.Thread:
    """Open the browser once the backend answers, without blocking the server."""

    def wait_and_open() -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(health, timeout=2) as resp:
                    if resp.status == 200:
                        webbrowser.open(url)
                        return
            except Exception:
                pass
            time.sleep(0.5)

    thread = threading.Thread(target=wait_and_open, daemon=True)
    thread.start()
    return thread


# --- Commands --------------------------------------------------------------


def cmd_install(args: argparse.Namespace) -> None:
    check_node()
    if venv_ok():
        print("Backend venv: %s" % venv_python())
    else:
        python = [args.python] if args.python else find_python()
        if not python:
            raise LauncherError(
                "No Python 3.10+ found. The backend needs it (fastapi 0.139+).\n"
                "  macOS: `brew install python@3.13`, or the installer from https://python.org\n"
                "  Windows: the installer from https://python.org (it adds the `py` launcher)\n"
                "  Linux: your package manager's python3.12 (or newer) plus python3-venv\n"
                "Already have one elsewhere? Point at it:\n"
                "  python yuben.py install --python /path/to/python3.12"
            )
        version = python_version(python)
        if not version or version < MIN_PYTHON:
            raise LauncherError("%s is not Python 3.10+." % " ".join(python))
        if VENV.exists():
            print("Replacing the backend venv: it is missing or older than Python 3.10.")
            shutil.rmtree(VENV)
        print("Backend venv using %s (Python %d.%d)" % ((" ".join(python),) + version))
        run([*python, "-m", "venv", str(VENV)], ROOT)
    py = str(venv_python())
    run([py, "-m", "pip", "install", "--upgrade", "pip"], ROOT)
    run([py, "-m", "pip", "install", "-r", str(BACKEND / "requirements.txt")], ROOT)
    run([tool("npm"), "install"], FRONTEND)
    print("\nInstalled. Start YuBen with: python yuben.py start")


def installed() -> bool:
    return venv_ok() and (FRONTEND / "node_modules").is_dir()


def ensure_installed(args: argparse.Namespace) -> None:
    if not installed():
        print("First run: installing dependencies.\n")
        cmd_install(argparse.Namespace(python=getattr(args, "python", None)))


def cmd_build(_args: argparse.Namespace) -> None:
    run([tool("npm"), "run", "build"], FRONTEND)


def cmd_start(args: argparse.Namespace) -> None:
    ensure_installed(args)
    if not args.no_build:
        cmd_build(args)
    port = pick_port()
    url = "http://localhost:%d" % port
    if port != DEFAULT_PORT and not os.environ.get(PORT_ENV):
        print("Port %d is busy, using %d." % (DEFAULT_PORT, port))
    print("\nYuBen on %s (Ctrl-C to stop)" % url, flush=True)
    if not args.no_browser:
        open_when_ready(url, "http://127.0.0.1:%d/api/health" % port)
    proc = subprocess.Popen(server_command(venv_python(), port), cwd=str(BACKEND), env=child_env(port, serve_spa=True))
    try:
        code = proc.wait()
    except KeyboardInterrupt:
        stop(proc)
        return
    if code != 0:
        raise LauncherError("The server stopped (exit %d)." % code)


def cmd_dev(args: argparse.Namespace) -> None:
    ensure_installed(args)
    port = pick_port()
    if not port_free(DEV_FRONTEND_PORT):
        raise LauncherError(
            "Port %d (the Vite dev server) is in use. Stop the other dev server first." % DEV_FRONTEND_PORT
        )
    env = child_env(port)
    print("Backend :%d + frontend :%d (Ctrl-C to stop). Open http://localhost:%d" % (port, DEV_FRONTEND_PORT, DEV_FRONTEND_PORT), flush=True)
    procs = [
        subprocess.Popen(server_command(venv_python(), port, reload=True), cwd=str(BACKEND), env=env),
        subprocess.Popen([tool("npm"), "run", "dev"], cwd=str(FRONTEND), env=env),
    ]
    interrupted = False
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
    except KeyboardInterrupt:
        interrupted = True
    finally:
        for p in procs:
            stop(p)
    if not interrupted:
        # One side died on its own (a busy port, a syntax error); the other was
        # stopped with it, so say which.
        names = ("backend", "frontend")
        dead = [n for n, p in zip(names, procs) if p.returncode not in (0, None)]
        raise LauncherError("The %s stopped; dev is shut down." % " and ".join(dead or names))


def cmd_test(args: argparse.Namespace) -> None:
    if not venv_ok():
        raise LauncherError("The backend venv is missing. Run: python yuben.py install")
    extra = [a for a in args.pytest_args if a != "--"]
    run([str(venv_python()), "-m", "pytest", *extra], BACKEND, env=child_env(DEFAULT_PORT))
    if not args.backend_only:
        run([tool("npx"), "tsc", "-b"], FRONTEND)


def smoke_command(python: Path, args: argparse.Namespace) -> List[str]:
    """The backend's smoke module (backend/app/smoke.py), run in the venv."""
    cmd = [str(python), "-m", "app.smoke", "--adapter", args.adapter, "--format", args.format]
    if args.model:
        cmd += ["--model", args.model]
    if args.query:
        cmd += ["--query", args.query]
    return cmd


def cmd_smoke(args: argparse.Namespace) -> None:
    if not venv_ok():
        raise LauncherError("The backend venv is missing. Run: python yuben.py install")
    code = subprocess.call(smoke_command(venv_python(), args), cwd=str(BACKEND), env=child_env(DEFAULT_PORT))
    if code != 0:
        raise LauncherError("The smoke test failed (see above).")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yuben.py", description="Install and run YuBen.")
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True

    p = sub.add_parser("install", help="backend venv + frontend node deps")
    p.add_argument("--python", help="a specific Python 3.10+ to build the venv from")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("start", help="build, then serve the whole app on one port")
    p.add_argument("--no-build", action="store_true", help="serve the existing frontend build")
    p.add_argument("--no-browser", action="store_true", help="do not open the browser")
    p.add_argument("--python", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_start)

    p = sub.add_parser("dev", help="backend + Vite with hot reload")
    p.add_argument("--python", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_dev)

    p = sub.add_parser("test", help="backend pytest + frontend typecheck")
    p.add_argument("--backend-only", action="store_true", help="skip the frontend typecheck")
    p.add_argument("pytest_args", nargs=argparse.REMAINDER, help="extra pytest arguments after --")
    p.set_defaults(func=cmd_test)

    p = sub.add_parser("build", help="production frontend build")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("smoke", help="test one model on bundled videos; no YouTube quota")
    p.add_argument("--adapter", required=True, help="adapter id, e.g. openai-api or claude-code")
    p.add_argument("--model", help="model id; the adapter's default when omitted")
    p.add_argument("--format", choices=("longform", "shorts"), default="longform")
    p.add_argument("--query", help="topic to expand; the bundled run's topic when omitted")
    p.set_defaults(func=cmd_smoke)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except LauncherError as exc:
        print("\nyuben: %s" % exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
