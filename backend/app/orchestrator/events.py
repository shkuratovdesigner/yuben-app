"""ProgressEvent construction + loader-phase vocabulary (B4).

The single place that knows the lifecycle phase order, the human labels
(PRD §6 / §4.4), and the rough progress marks that make the loader bar advance.
Everything the orchestrator emits goes through :func:`make_event` /
:func:`make_error_event` so every event is a schema-valid ``ProgressEvent``
(``contracts.python.models``) — self-checking our own output.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

from contracts.python.models import (
    ErrorCode,
    ProgressErrorDetail,
    ProgressEvent,
)

# Ordered non-terminal lifecycle (CONTRACTS §3 phase enum minus done/error).
PHASE_SEQUENCE = [
    "queued",
    "expanding",
    "searching",
    "enriching",
    "scoring",
    "analyzing",
    "verifying",
]

# Human copy — PRD §6 "Loader phase labels" + §4.4.
_PHASE_LABELS: Dict[str, str] = {
    "queued": "Queued",
    "expanding": "Expanding your topic into search terms",
    "searching": "Searching YouTube",
    "enriching": "Pulling channel sizes & stats",
    "scoring": "Scoring outliers (views vs. channel size)",
    "analyzing": "Analyzing titles & scripts",
    "verifying": "Verifying every link",
    "done": "Done",
    "error": "Something went wrong",
}

# Rough progress marks so the bar moves predictably across phases.
_PHASE_PCT: Dict[str, Optional[int]] = {
    "queued": 0,
    "expanding": 8,
    "searching": 25,
    "enriching": 45,
    "scoring": 62,
    "analyzing": 80,
    "verifying": 92,
    "done": 100,
    "error": None,
}

# Sentinel distinguishing "caller passed pct=None (indeterminate)" from
# "caller omitted pct (use the phase default)".
_UNSET = object()


def phase_label(phase: str) -> str:
    return _PHASE_LABELS.get(phase, phase.replace("_", " ").title())


def phase_pct(phase: str) -> Optional[int]:
    return _PHASE_PCT.get(phase)


def now_iso() -> str:
    """UTC timestamp in the fixtures' shape, e.g. ``2026-07-11T10:00:07Z``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_event(
    run_id: str,
    phase: str,
    *,
    label: Optional[str] = None,
    pct=_UNSET,
    detail: Optional[str] = None,
    counts: Optional[Dict[str, int]] = None,
) -> ProgressEvent:
    """Build a schema-valid non-terminal ``ProgressEvent``.

    ``pct`` omitted -> the phase's default mark; pass ``pct=None`` for an
    explicitly indeterminate bar, or an int to override.
    """
    resolved_pct = phase_pct(phase) if pct is _UNSET else pct
    return ProgressEvent(
        run_id=run_id,
        phase=phase,  # type: ignore[arg-type]
        label=label or phase_label(phase),
        pct=resolved_pct,
        detail=detail,
        counts=counts,
        error=None,
        ts=now_iso(),
    )


def make_error_event(run_id: str, code: ErrorCode, message: str) -> ProgressEvent:
    """Build the terminal ``phase:"error"`` event carrying ``error:{code,message}``."""
    return ProgressEvent(
        run_id=run_id,
        phase="error",
        label=phase_label("error"),
        pct=None,
        detail=message,
        counts=None,
        error=ProgressErrorDetail(code=code, message=message),
        ts=now_iso(),
    )
