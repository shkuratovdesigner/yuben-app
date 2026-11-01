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
import time
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


#: Names scrubbed from the environment of every CLI spawn. A YouTube Data API
#: key has no business reaching ``claude --version`` — and, since B4 stopped
#: sending agents off to run the research scripts themselves, no business
#: reaching the ``stream`` path either: the backend calls the scripts in-process
#: and reads the key from the secret store. Provider keys are deliberately left
#: alone — a vendor's own CLI legitimately reads its own credential.
_SCRUBBED_ENV = ("YOUTUBE_API_KEY",)


def _child_env() -> Dict[str, str]:
    env = dict(os.environ)
    for name in _SCRUBBED_ENV:
        env.pop(name, None)
    return env


#: ``AdapterError.kind`` values. B4 picks the terminal ErrorCode from the kind,
#: never from the message text.
KIND_AUTH = "auth"  # key missing, rejected or lacking permission
KIND_RATE_LIMIT = "rate_limit"
KIND_OUTPUT_LIMIT = "output_limit"
KIND_CONTEXT_TOO_LONG = "context_too_long"
KIND_NETWORK = "network"
KIND_SERVER = "server"  # provider-side 5xx / overloaded
KIND_MODEL_NOT_FOUND = "model_not_found"
KIND_BAD_REQUEST = "bad_request"
KIND_NOT_INSTALLED = "not_installed"  # CLI or SDK absent
KIND_UNKNOWN = "unknown"


class AdapterError(RuntimeError):
    """An unrecoverable adapter/CLI failure.

    ``check_env`` never raises this (it always returns an ``ok:false`` dict), but
    ``stream`` does — B4 maps its ``kind`` to a ``cli_missing`` / ``cli_failed``
    / ``invalid_output`` ProgressEvent. The message is already plain language.
    """

    def __init__(self, message: str = "", *, kind: str = KIND_UNKNOWN) -> None:
        super().__init__(message)
        self.kind = kind


class OutputTruncated(AdapterError):
    """The model stopped at its output-token cap, so the answer is cut off.

    Raised by API adapters that can read the provider's stop reason. B4 reports
    it as invalid output with this message instead of "no JSON was found".
    """

    def __init__(self, provider: str) -> None:
        super().__init__(
            "{}'s answer was cut off at the model's output limit. Pick a model "
            "with a larger output limit, or turn off an optional analysis.".format(provider),
            kind=KIND_OUTPUT_LIMIT,
        )


def _clip(text: str, limit: int = 300) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _is_context_error(exc: Exception) -> bool:
    """A 400 that means the prompt exceeds the model's context window.

    OpenAI-compatible APIs set ``code="context_length_exceeded"``; Anthropic and
    others only say so in the message, so that is checked as a second signal.
    """
    if getattr(exc, "code", None) == "context_length_exceeded":
        return True
    text = str(getattr(exc, "message", None) or exc).lower()
    return any(
        tok in text
        for tok in ("prompt is too long", "context length", "context window", "maximum context")
    )


def api_error(exc: Exception, sdk: Any, provider: str) -> AdapterError:
    """Typed :class:`AdapterError` for an ``anthropic`` / ``openai`` SDK exception.

    ``sdk`` is the imported SDK module. Both SDKs export the same typed
    exception hierarchy, so classification is by ``isinstance`` on those
    classes, most specific first. Never includes the request URL or key.
    """
    detail = _clip(getattr(exc, "message", None) or str(exc) or type(exc).__name__)

    def cls(name: str) -> Any:
        found = getattr(sdk, name, None)
        return found if isinstance(found, type) else ()

    if isinstance(exc, cls("AuthenticationError")):
        return AdapterError(
            "{} rejected the API key. Check that it's correct and active.".format(provider),
            kind=KIND_AUTH,
        )
    if isinstance(exc, cls("PermissionDeniedError")):
        return AdapterError(
            "{} refused this key permission for the request. Check the key's "
            "project, region and model access.".format(provider),
            kind=KIND_AUTH,
        )
    if isinstance(exc, cls("NotFoundError")):
        return AdapterError(
            "That model isn't available on {} for this key. Pick another model.".format(provider),
            kind=KIND_MODEL_NOT_FOUND,
        )
    if isinstance(exc, cls("RateLimitError")):
        if getattr(exc, "code", None) == "insufficient_quota":
            return AdapterError(
                "{} says this account is out of credit or over its spending "
                "limit. Check billing, then try again.".format(provider),
                kind=KIND_RATE_LIMIT,
            )
        return AdapterError(
            "{}'s rate limit was hit. Wait a moment and try again.".format(provider),
            kind=KIND_RATE_LIMIT,
        )
    if isinstance(exc, cls("RequestTooLargeError")) or (
        isinstance(exc, cls("BadRequestError")) and _is_context_error(exc)
    ):
        return AdapterError(
            "The research prompt is longer than this model's context window. "
            "Pick a model with a larger context window.",
            kind=KIND_CONTEXT_TOO_LONG,
        )
    if isinstance(exc, cls("BadRequestError")) or isinstance(
        exc, cls("UnprocessableEntityError")
    ):
        return AdapterError(
            "{} rejected the request: {}".format(provider, detail), kind=KIND_BAD_REQUEST
        )
    if isinstance(exc, cls("APIConnectionError")):  # includes APITimeoutError
        return AdapterError(
            "Couldn't reach {}. Check your connection and try again.".format(provider),
            kind=KIND_NETWORK,
        )
    if isinstance(exc, cls("APIStatusError")) and (getattr(exc, "status_code", 0) or 0) >= 500:
        return AdapterError(
            "{} had a server error or is overloaded. Try again in a moment.".format(provider),
            kind=KIND_SERVER,
        )
    return AdapterError("{} API error: {}".format(provider, detail), kind=KIND_UNKNOWN)


def output_cap_override() -> Optional[int]:
    """``YUBEN_MAX_OUTPUT_TOKENS`` as a positive int, else ``None``.

    API adapters send no output cap by default, so each model uses its own
    maximum; this is the escape hatch for a provider that needs one.
    """
    raw = os.environ.get("YUBEN_MAX_OUTPUT_TOKENS", "").strip()
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def key_digest(key: Optional[str]) -> str:
    """Short one-way digest of a credential, for fingerprints only."""
    import hashlib

    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16] if key else "none"


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
      * ``agentic`` — whether the adapter has a tool loop at all (``True``, the
                      CLI adapters) or is a plain text-completion surface
                      (``False``, the direct API adapter). Descriptive only:
                      B4 feeds every adapter the already-collected videos and
                      lets none of them research on their own, because only
                      pipeline ids survive B5's join. Defaults to ``True``.
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

    def settings_fingerprint(self, model: str) -> str:
        """What a passing check depends on besides the adapter id and model.

        The orchestrator's preflight reuses a passing check only while this is
        unchanged. API adapters add their key and base URL; never return a
        secret itself, only a digest of it.
        """
        return "cap={}".format(output_cap_override())

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
            env=_child_env(),
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
        env=_child_env(),
    )


#: A research run is minutes, not hours. These bound the two ways an agent CLI
#: wedges: producing nothing at all, and producing a trickle forever. Both are
#: generous — they exist to stop a hung process holding a run open indefinitely,
#: not to cut short a slow-but-working one.
STREAM_IDLE_TIMEOUT = 300.0   # no stdout line for 5 minutes
STREAM_TOTAL_TIMEOUT = 3600.0  # 1 hour wall clock, whatever it is doing


def stream_process(
    cmd: List[str],
    *,
    cwd: Optional[str] = None,
    idle_timeout: Optional[float] = STREAM_IDLE_TIMEOUT,
    total_timeout: Optional[float] = STREAM_TOTAL_TIMEOUT,
) -> Iterator[str]:
    """Popen ``cmd`` and yield decoded, newline-stripped stdout lines.

    Drains stderr on a daemon thread (so a chatty CLI cannot deadlock on a full
    pipe), terminates the child if the consumer stops early, and raises
    :class:`AdapterError` if the process could not start or exited non-zero
    without producing any stdout. This is the engine behind every adapter's
    :meth:`AgentAdapter.stream`.

    Unlike :func:`run_probe`, this cannot pass ``timeout=`` to subprocess — it
    yields lines as they arrive rather than running to completion — so a
    watchdog thread enforces the bounds instead. Killing the child lands EOF on
    stdout and the loop below ends normally; ``AdapterError`` is then raised
    from the timeout branch so the caller can tell a hang from a clean exit.
    Pass ``None`` for either bound to disable it.
    """
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=cwd,
            env=_child_env(),
            stdin=subprocess.DEVNULL,  # see run_probe: never let the CLI wait on stdin
        )
    except FileNotFoundError as exc:
        raise AdapterError(
            "CLI not found: {}".format(cmd[0]), kind=KIND_NOT_INSTALLED
        ) from exc
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

    # Watchdog: the reader below blocks in the kernel, so the only way to bound
    # it is from another thread. `timed_out` is set before the kill so the
    # timeout branch can distinguish this from an ordinary exit.
    started_at = time.monotonic()
    last_output_at = [started_at]
    timed_out: List[str] = []
    watchdog_stop = threading.Event()

    def _watchdog() -> None:
        while not watchdog_stop.wait(1.0):
            if proc.poll() is not None:
                return
            now = time.monotonic()
            if total_timeout is not None and now - started_at > total_timeout:
                timed_out.append(
                    "CLI exceeded the {:.0f}s time limit".format(total_timeout)
                )
            elif idle_timeout is not None and now - last_output_at[0] > idle_timeout:
                timed_out.append(
                    "CLI produced no output for {:.0f}s".format(idle_timeout)
                )
            else:
                continue
            try:
                proc.terminate()
            except Exception:  # pragma: no cover - already gone
                pass
            return

    watchdog = threading.Thread(target=_watchdog, daemon=True)
    watchdog.start()

    saw_output = False
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            last_output_at[0] = time.monotonic()
            line = raw.rstrip("\n")
            if line:
                saw_output = True
                yield line
    finally:
        watchdog_stop.set()
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
        watchdog.join(timeout=2)

    if timed_out:
        raise AdapterError(timed_out[0])

    if proc.returncode not in (0, None) and not saw_output:
        raise AdapterError(
            "".join(err_chunks).strip()
            or "CLI exited with code {}".format(proc.returncode)
        )
