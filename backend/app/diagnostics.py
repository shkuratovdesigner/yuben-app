"""Per-run diagnostics log (reliability plan, Phase 6).

A failed run used to leave nothing behind but its one-line error, so diagnosing
it took rounds of guessing ("which model? what came back?"). Each run now writes
one redacted JSON file to ``<data_dir>/diagnostics/<run_id>.json`` with what is
needed to diagnose it in one message: adapter, model, the request parameters
sent, token usage, stop reason, the first and last few KB of each raw answer,
the parse error, progress details, and the terminal error.

How it is fed: the run's worker thread owns one :class:`RunDiagnostics`, held in
a thread-local while the run executes. The runner opens a step per model call
(expand, narrative, repair) and the adapters, whose generators run on that same
thread, call :func:`note` with what only they see (request params, usage, stop
reason). A call with no active recorder is a no-op, so adapters stay usable
from model checks, smoke runs and tests.

Never logged: the prompt text (only its size) and anything credential-shaped.
The whole file goes through :func:`app.redact.redact` before it is written, the
same scrubber that guards every error message.

Diagnostics must never break a run: every public function swallows its own
failures.
"""
from __future__ import annotations

import json
import os
import platform
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.redact import redact

#: Bytes of raw answer kept from each end. Enough for the opening of a reply
#: and its cut-off tail, small enough to paste into a chat message.
RAW_KEEP = 4096
#: Diagnostics files kept on disk; the oldest are deleted past this.
KEEP_FILES = 50

_LOCAL = threading.local()
_DIRNAME = "diagnostics"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _jsonable(value: Any) -> Any:
    """``value`` reduced to JSON types; unknown objects become their repr."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        pass
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "model_dump"):
        try:
            return _jsonable(value.model_dump())
        except Exception:
            pass
    return repr(value)


def summarize_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Request parameters with any JSON Schema replaced by a short marker.

    The AgentResult schema is several KB and identical on every run; what
    matters for diagnosis is that one was sent and where.
    """

    def walk(value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            if key in ("schema", "format") and ("properties" in value or "$schema" in value):
                return "<json schema>"
            return {k: walk(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value

    return walk(params) if isinstance(params, dict) else {}


def head_tail(text: str, keep: int = RAW_KEEP) -> Dict[str, Any]:
    """The first and last ``keep`` characters of ``text`` and its full length."""
    text = text or ""
    if len(text) <= 2 * keep:
        return {"chars": len(text), "head": text, "tail": ""}
    return {"chars": len(text), "head": text[:keep], "tail": text[-keep:]}


class RunDiagnostics:
    """Everything recorded about one run. Built and mutated on its worker thread."""

    def __init__(self, run_id: str, request: Any = None) -> None:
        model = getattr(request, "model", None)
        self.data: Dict[str, Any] = {
            "run_id": run_id,
            "started_at": _now(),
            "finished_at": None,
            "app": {
                "python": platform.python_version(),
                "platform": sys.platform,
                "os": platform.platform(terse=True),
            },
            "adapter": getattr(model, "adapter", None),
            "model": getattr(model, "model", None),
            "request": _request_summary(request),
            "steps": [],
            "progress": [],
            "outcome": None,
        }
        self._step: Optional[Dict[str, Any]] = None

    # -- steps (one per model call) ---------------------------------------
    def begin_step(self, name: str, prompt: str) -> None:
        self._step = {
            "name": name,
            "prompt_chars": len(prompt or ""),
            "request": {},
            "usage": None,
            "stop_reason": None,
            "raw": None,
            "parse_error": None,
            "error": None,
        }
        self.data["steps"].append(self._step)

    def note(self, **fields: Any) -> None:
        step = self._step
        if step is None:
            return
        for key, value in fields.items():
            if key == "request" and isinstance(value, dict):
                step["request"].update(_jsonable(value))
            else:
                step[key] = _jsonable(value)

    def progress(self, phase: str, detail: Optional[str]) -> None:
        if detail:
            self.data["progress"].append({"ts": _now(), "phase": phase, "detail": detail})

    def finish(self, event: Any) -> None:
        error = getattr(event, "error", None)
        self.data["finished_at"] = _now()
        self.data["outcome"] = {
            "phase": getattr(event, "phase", None),
            "code": getattr(error, "code", None),
            "message": getattr(error, "message", None),
        }


def _request_summary(request: Any) -> Dict[str, Any]:
    """The run's settings, minus the model block (recorded at the top level)."""
    if request is None or not hasattr(request, "model_dump"):
        return {}
    try:
        dumped = request.model_dump(mode="json")
    except Exception:
        return {}
    dumped.pop("model", None)
    return dumped


# --- thread-local plumbing (called by the runner and the adapters) ----------
def start(run_id: str, request: Any = None) -> Optional[RunDiagnostics]:
    try:
        diag = RunDiagnostics(run_id, request)
    except Exception:
        return None
    _LOCAL.current = diag
    return diag


def current() -> Optional[RunDiagnostics]:
    return getattr(_LOCAL, "current", None)


def stop() -> None:
    _LOCAL.current = None


def begin_step(name: str, prompt: str) -> None:
    diag = current()
    if diag is not None:
        try:
            diag.begin_step(name, prompt)
        except Exception:
            pass


def note(**fields: Any) -> None:
    """Record fields on the current step. No-op outside a run."""
    diag = current()
    if diag is not None:
        try:
            diag.note(**fields)
        except Exception:
            pass


def progress(phase: str, detail: Optional[str]) -> None:
    diag = current()
    if diag is not None:
        try:
            diag.progress(phase, detail)
        except Exception:
            pass


# --- storage ------------------------------------------------------------------
def diagnostics_dir() -> Path:
    from app.store.db import data_dir

    return data_dir() / _DIRNAME


def _path_for(run_id: str) -> Optional[Path]:
    # Run ids are server-generated hex; refuse anything that could be a path.
    if not run_id or not all(c.isalnum() or c in "_-" for c in run_id):
        return None
    return diagnostics_dir() / ("%s.json" % run_id)


def save(diag: Optional[RunDiagnostics]) -> Optional[Path]:
    """Write ``diag`` redacted to disk, then prune old files. Never raises."""
    if diag is None:
        return None
    try:
        path = _path_for(str(diag.data.get("run_id")))
        if path is None:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        text = redact(json.dumps(_jsonable(diag.data), ensure_ascii=False, indent=2))
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
        _prune(path.parent)
        return path
    except Exception:
        return None


def _prune(folder: Path) -> None:
    try:
        files = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    for old in files[KEEP_FILES:]:
        try:
            old.unlink()
        except OSError:
            pass


def load(run_id: str) -> Optional[Dict[str, Any]]:
    path = _path_for(run_id)
    if path is None or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def render_text(data: Dict[str, Any]) -> str:
    """The saved log as plain text for the "Copy diagnostics" button.

    A short header a person can read, then the full JSON, so the paste works
    both for a human and for whoever debugs it.
    """
    outcome = data.get("outcome") or {}
    lines: List[str] = [
        "YuBen diagnostics",
        "Run: %s" % data.get("run_id"),
        "Adapter: %s  Model: %s" % (data.get("adapter"), data.get("model")),
        "Platform: %s, Python %s"
        % ((data.get("app") or {}).get("os"), (data.get("app") or {}).get("python")),
        "Outcome: %s%s"
        % (
            outcome.get("code") or outcome.get("phase"),
            " - %s" % outcome["message"] if outcome.get("message") else "",
        ),
        "",
        json.dumps(data, ensure_ascii=False, indent=2),
    ]
    return redact("\n".join(lines))
