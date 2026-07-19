"""AgentAdapter — the uniform surface over a local agent CLI.

Two consumers, one interface:

* **Onboarding / env-check** (F1 screen → B1's `app/api/config.py:env_check`
  → the registry's `check_env`) calls :meth:`detect`, :meth:`models`, and
  :meth:`check_env` — cheap detection plus a live "respond hello" probe.
* **The orchestrator** (B4) calls :meth:`stream` to run a headless prompt and
  consume the CLI's streamed stdout events line by line.

Concrete adapters (``ClaudeCodeAdapter``, ``GeminiCliAdapter``) wrap exactly one
CLI. Detection uses :func:`shutil.which` + ``--version``; the run surfaces use
stdlib :mod:`subprocess` only (no new deps — B3 owns requirements.txt).

TRUST RULE (project-wide): an adapter carries the LLM's *narrative* output only.
Nothing it emits is ever a source of video IDs or numbers — those come from the
deterministic pipeline (B3) and are re-verified by B5. Keep that discipline in
anything built on top of ``stream()``.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterator, List, Optional

__all__ = [
    "AgentAdapter",
    "AdapterError",
    "extract_version",
    "terminate_for_thread",
]


# ---------------------------------------------------------------------------
# Live child processes, keyed by the thread consuming them
# ---------------------------------------------------------------------------
#
# Cancel used to be routed through ``generator.close()`` from the API thread.
# That cannot work: the worker thread is blocked in ``for raw in proc.stdout``,
# so closing its generator from elsewhere raises ``ValueError: generator already
# executing``, which the caller swallowed — the CLI kept running and the UI
# reported a successful cancel either way.
#
# A ``Popen`` handle, unlike a generator, is safe to signal from any thread.
# ``stream_process`` runs its body on the consuming thread (the generator body
# only advances on ``next()``), so registering under ``get_ident()`` at spawn
# time gives the orchestrator a thread-addressable handle on the child.
# Terminating it lands EOF on stdout, the worker's loop ends, and the existing
# ``finally`` reaps the child on its own thread exactly as before.

_LIVE_LOCK = threading.Lock()
_LIVE: Dict[int, List["subprocess.Popen"]] = {}


def _register_child(proc: "subprocess.Popen") -> None:
    with _LIVE_LOCK:
        _LIVE.setdefault(threading.get_ident(), []).append(proc)


def _unregister_child(proc: "subprocess.Popen") -> None:
    ident = threading.get_ident()
    with _LIVE_LOCK:
        procs = _LIVE.get(ident)
        if not procs:
            return
        try:
            procs.remove(proc)
        except ValueError:  # pragma: no cover - already dropped
            pass
        if not procs:
            _LIVE.pop(ident, None)


def terminate_for_thread(ident: Optional[int]) -> int:
    """Terminate every live child spawned by thread ``ident``. Returns the count.

    Safe to call from any thread, and safe to call when nothing is running.
    """
    if ident is None:
        return 0
    with _LIVE_LOCK:
        procs = list(_LIVE.get(ident, ()))
    killed = 0
    for proc in procs:
        try:
            if proc.poll() is None:
                proc.terminate()
                killed += 1
        except Exception:  # pragma: no cover - process already reaped
            pass
    return killed


#: Names scrubbed from the environment of *probe* spawns. A YouTube Data API
#: key has no business reaching ``claude --version``; the agentic ``stream``
#: path keeps it, because the CLI shells out to the research scripts, which
#: read it at import (``config.py:60``). Provider keys are deliberately left
#: alone — a vendor's own CLI legitimately reads its own credential.
_PROBE_SCRUBBED_ENV = ("YOUTUBE_API_KEY",)


def _probe_env() -> Dict[str, str]:
    env = dict(os.environ)
    for name in _PROBE_SCRUBBED_ENV:
        env.pop(name, None)
    return env


class AdapterError(RuntimeError):
    """An unrecoverable adapter/CLI failure.

    ``check_env`` never raises this (it always returns an ``ok:false`` dict), but
    ``stream`` does — B4 maps it to a ``cli_missing`` / ``cli_failed``
    ProgressEvent.
    """


def extract_version(text: str) -> Optional[str]:
    """Pull a semver-ish token out of ``--version`` output.

    ``"2.1.198 (Claude Code)"`` -> ``"2.1.198"``. Falls back to the trimmed
    line when no numeric version is present, and ``None`` for empty input.
    """
    import re

    if not text:
        return None
    stripped = text.strip()
    match = re.search(r"\d+\.\d+(?:\.\d+)?(?:[.\-+][0-9A-Za-z.\-]+)?", stripped)
    if match:
        return match.group(0)
    return stripped or None


class AgentAdapter(ABC):
    """Abstract base every concrete adapter implements.

    Class attributes (set by subclasses):
      * ``id``      — stable adapter id used in the API + persisted config
                      (e.g. ``"claude-code"``). Matches ``Adapter.id``.
      * ``name``    — human-readable label (e.g. ``"Claude Code"``).
      * ``binary``  — the executable looked up on ``PATH`` (e.g. ``"claude"``).
      * ``agentic`` — whether the adapter runs the research scripts ITSELF as an
                      agent (``True``, the CLI adapters) or is a plain
                      text-completion surface the orchestrator must feed the
                      already-collected videos to (``False``, the direct API
                      adapter). B4 branches on this. Defaults to ``True``.
    """

    id: str = ""
    name: str = ""
    binary: str = ""
    agentic: bool = True

    # -- detection (cheap, read-only, never raises) --------------------------
    @abstractmethod
    def detect(self) -> Dict[str, Any]:
        """Return ``{"installed": bool, "version": str | None}``.

        Looks the CLI up on ``PATH`` and reads ``<binary> --version``. A missing
        CLI is ``{"installed": False, "version": None}`` — this must never raise.
        """

    @abstractmethod
    def models(self) -> List[str]:
        """Selectable model ids for this adapter (``[]`` when none/unknown)."""

    # -- live probe (never raises; returns the EnvCheckResult shape) ---------
    @abstractmethod
    def check_env(self, model: Optional[str] = None) -> Dict[str, Any]:
        """Run a live "respond hello" probe against the CLI.

        Returns the EnvCheckResult dict
        ``{"ok": bool, "adapter": <id>, "version": str | None, "message": str}``.
        Never raises: a missing CLI, a non-zero exit, a timeout, or unexpected
        output are all reported as ``ok=False`` with a plain-language ``message``
        (and an install hint when the CLI is absent). ``model`` is optional;
        ``None`` or ``"default"`` uses the CLI's own default model.
        """

    # -- headless run surface (consumed by B4's orchestrator) ----------------
    @abstractmethod
    def stream(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        cwd: Optional[str] = None,
    ) -> Iterator[str]:
        """Spawn the CLI **headless** for ``prompt`` and stream its stdout.

        **Contract for B4** (this is the surface the orchestrator depends on):

        * Returns a **live generator** that yields **one decoded stdout line at a
          time** (trailing newline stripped, blank lines skipped), in order, as
          the CLI emits them — not a buffered list. For ``ClaudeCodeAdapter``
          each line is a JSON object from ``--output-format stream-json`` (a
          stream of events ending in a ``{"type":"result", ...}`` line); parse
          each line as JSON and ignore any that fail to decode.
        * The child runs to completion as the generator is consumed. Exhausting
          or closing the generator early terminates the child (``terminate`` then
          ``kill``), so it is safe to ``break`` out of the loop.
        * If the CLI cannot be launched (binary missing) or exits non-zero having
          produced **no** stdout, it raises :class:`AdapterError`. Output already
          yielded before a late failure is left for B4 to handle.
        * stderr (the CLI's own logs) is drained but **not** yielded — only the
          stdout event stream is surfaced.
        * ``model=None`` / ``"default"`` uses the CLI default; any other value is
          passed through to the CLI's ``--model`` flag. ``cwd`` sets the child's
          working directory (defaults to the current process cwd).

        Not implemented adapters (the Gemini stub) raise
        :class:`NotImplementedError`.
        """
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Shared subprocess helpers (stdlib only) — used by the concrete adapters.
# --------------------------------------------------------------------------- #

def which(binary: str) -> Optional[str]:
    """Absolute path to ``binary`` on ``PATH``, or ``None``."""
    return shutil.which(binary)


# --------------------------------------------------------------------------- #
# Remedies — what the user should DO about a failed env-check.
# --------------------------------------------------------------------------- #
#
# A failing check used to surface one generic "Install guide" link, which is
# actively misleading when the CLI is installed and the real problem is a stale
# login. An adapter now says which of these applies, and the UI renders the
# matching action instead of guessing.

#: The tool isn't on PATH — link to its install page.
REMEDY_INSTALL = "install"
#: The tool is installed but not usable until the user authenticates. ``command``
#: is run for them (in a terminal) by POST /api/config/remedy.
REMEDY_SIGN_IN = "sign_in"


def remedy(
    kind: str,
    label: str,
    *,
    command: Optional[str] = None,
    url: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the remedy payload carried on an EnvCheckResult.

    ``command`` is always defined HERE, by the adapter — never accepted from the
    client — so the run-remedy endpoint can only ever execute a command this
    codebase chose.
    """
    return {"kind": kind, "label": label, "command": command, "url": url}


def run_version(path: str, *, flag: str = "--version", timeout: float = 10.0) -> Optional[str]:
    """Run ``<path> <flag>`` and return a parsed version string, or ``None``.

    Reads stdout then stderr (some CLIs print the version to stderr). Never
    raises — any failure yields ``None``.
    """
    try:
        proc = subprocess.run(
            [path, flag],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_probe_env(),
        )
    except Exception:
        return None
    out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    return extract_version(out)


def run_probe(
    cmd: List[str],
    *,
    timeout: float,
    cwd: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """Run ``cmd`` to completion, capturing text stdout/stderr.

    Thin wrapper over :func:`subprocess.run`; the caller interprets the result.
    May raise :class:`subprocess.TimeoutExpired` / ``OSError`` — callers in
    ``check_env`` catch these and convert them to ``ok:false``.

    ``stdin`` is closed explicitly: under uvicorn the child would otherwise
    inherit a pipe that never delivers data, and agent CLIs stall waiting on it
    (Claude Code burns 3s, then warns on stderr) — noise that used to mask the
    real error. Every probe here is non-interactive, so DEVNULL is always right.
    """
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        env=_probe_env(),
    )


def stream_process(cmd: List[str], *, cwd: Optional[str] = None) -> Iterator[str]:
    """Popen ``cmd`` and yield decoded, newline-stripped stdout lines.

    Drains stderr on a daemon thread (so a chatty CLI cannot deadlock on a full
    pipe), terminates the child if the consumer stops early, and raises
    :class:`AdapterError` if the process could not start or exited non-zero
    without producing any stdout. This is the engine behind every adapter's
    :meth:`AgentAdapter.stream`.
    """
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=cwd,
            stdin=subprocess.DEVNULL,  # see run_probe: never let the CLI wait on stdin
        )
    except FileNotFoundError as exc:
        raise AdapterError("CLI not found: {}".format(cmd[0])) from exc
    except OSError as exc:
        raise AdapterError("Could not launch CLI {}: {}".format(cmd[0], exc)) from exc

    # Make the child reachable from other threads so cancel can stop it.
    _register_child(proc)

    err_chunks: List[str] = []

    def _drain_stderr() -> None:
        try:
            if proc.stderr is not None:
                for line in proc.stderr:
                    err_chunks.append(line)
        except Exception:
            pass

    drainer = threading.Thread(target=_drain_stderr, daemon=True)
    drainer.start()

    saw_output = False
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            if line:
                saw_output = True
                yield line
    finally:
        # Reap the child. If the consumer stopped early — or cancel terminated
        # it from another thread — this is where it gets waited on.
        _unregister_child(proc)
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    pass
        else:
            proc.wait()
        drainer.join(timeout=1)

    if proc.returncode not in (0, None) and not saw_output:
        raise AdapterError(
            "".join(err_chunks).strip()
            or "CLI exited with code {}".format(proc.returncode)
        )
