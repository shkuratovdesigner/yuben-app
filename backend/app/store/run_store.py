"""In-memory run registry (B1) — the SHARED interface between B4 (orchestrator,
which WRITES progress) and B5 (result endpoint, which READS). Keeping the run
state here means B4 and B5 never edit the same file.

Single local user, so a process-global dict guarded by a lock is enough. A run's
*progress* does not survive a backend restart, but its *result* does:
``set_result`` writes through to ``result_store`` and ``get_result`` falls back
to it, so a finished run reopens from History even in a fresh process. The
HistoryItem summary alongside it is written by ``history_store``.

Interface (stable — B4/B5 depend on these exact names):
    create_run(request) -> run_id          # register a run, returns "r_<uuid>"
    set_phase(run_id, phase)               # advance the lifecycle phase
    append_event(run_id, event)            # record a ProgressEvent (SSE feed)
    get_events(run_id) -> list             # all events recorded so far
    set_result(run_id, result)             # attach the final ResearchResult
    get_result(run_id) -> Optional[result] # None until the run is done
    get_status(run_id) -> dict             # {"status": ..., "phase": ...}

Helpers: has_run(run_id) -> bool, cancel_run(run_id) -> bool, reset() (tests).

Status is derived from the phase:
    "queued"                 -> "queued"
    "done"                   -> "done"
    "error"                  -> "error"
    (cancel_run)             -> "cancelled"   (sticky; a late phase won't clobber)
    anything else            -> "running"
Unknown run_id             -> {"status": "not_found", "phase": None}
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.store import result_store

_TERMINAL = {"done", "error"}


@dataclass
class _RunState:
    run_id: str
    request: Any
    phase: str = "queued"
    status: str = "queued"
    events: List[Any] = field(default_factory=list)
    result: Optional[Any] = None


_RUNS: Dict[str, _RunState] = {}
_LOCK = threading.RLock()


def _new_run_id() -> str:
    return "r_" + uuid4().hex


def _status_for_phase(phase: str) -> str:
    if phase == "queued":
        return "queued"
    if phase in _TERMINAL:
        return phase  # "done" | "error"
    return "running"


def _phase_of(event: Any) -> Optional[str]:
    if event is None:
        return None
    if isinstance(event, dict):
        return event.get("phase")
    return getattr(event, "phase", None)


def create_run(request: Any) -> str:
    """Register a new run and return its id (``r_<uuid4-hex>``)."""
    run_id = _new_run_id()
    with _LOCK:
        _RUNS[run_id] = _RunState(run_id=run_id, request=request)
    return run_id


def set_phase(run_id: str, phase: str) -> None:
    """Advance the run's phase (source of truth for ``get_status``)."""
    with _LOCK:
        run = _RUNS.get(run_id)
        if run is None:
            return
        run.phase = phase
        if run.status != "cancelled":  # cancelled is sticky
            run.status = _status_for_phase(phase)


def append_event(run_id: str, event: Any) -> None:
    """Record a progress event. Convenience: if the event carries a ``phase``
    (dict key or attribute), the run's phase/status advance too — so B4 can rely
    on either ``append_event`` or ``set_phase``."""
    with _LOCK:
        run = _RUNS.get(run_id)
        if run is None:
            return
        run.events.append(event)
        phase = _phase_of(event)
        if phase is not None and run.status != "cancelled":
            run.phase = phase
            run.status = _status_for_phase(phase)


def get_events(run_id: str) -> List[Any]:
    """A copy of the events recorded so far (empty list for unknown runs)."""
    with _LOCK:
        run = _RUNS.get(run_id)
        return list(run.events) if run else []


def set_result(run_id: str, result: Any) -> None:
    """Attach the final result and mark the run done (unless cancelled).

    Also writes the result through to SQLite so it outlives this process — see
    ``result_store``. Persistence is best-effort: a DB hiccup must not lose a run
    the user is looking at right now.
    """
    with _LOCK:
        run = _RUNS.get(run_id)
        if run is None:
            return
        run.result = result
        run.phase = "done"
        if run.status != "cancelled":
            run.status = "done"
    try:
        result_store.save_result(run_id, result)
    except Exception:  # pragma: no cover - the in-memory copy still serves
        pass


def get_result(run_id: str) -> Optional[Any]:
    """The final result: this process's copy, else the stored one.

    The fallback is what makes History work across restarts — and what lets a
    seeded run (the bundled example) open like any other.
    """
    with _LOCK:
        run = _RUNS.get(run_id)
        if run is not None and run.result is not None:
            return run.result
    try:
        return result_store.load_result(run_id)
    except Exception:  # pragma: no cover - unreadable store reads as "no result"
        return None


def get_status(run_id: str) -> Dict[str, Optional[str]]:
    """``{"status", "phase"}``. Unknown run -> ``{"not_found", None}``."""
    with _LOCK:
        run = _RUNS.get(run_id)
        if run is None:
            return {"status": "not_found", "phase": None}
        return {"status": run.status, "phase": run.phase}


def has_run(run_id: str) -> bool:
    with _LOCK:
        return run_id in _RUNS


def cancel_run(run_id: str) -> bool:
    """Mark a run cancelled (status sticky). True if the run existed."""
    with _LOCK:
        run = _RUNS.get(run_id)
        if run is None:
            return False
        run.status = "cancelled"
        run.phase = "error"
        return True


def reset() -> None:
    """Test helper: clear the registry."""
    with _LOCK:
        _RUNS.clear()
