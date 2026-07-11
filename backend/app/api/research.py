"""Research run-lifecycle router (B4) — start / SSE events / cancel.

B4 owns the run lifecycle here; B5 owns the result-read in research_result.py —
so B4 and B5 never edit the same file. Both share app/store/run_store.py.

Endpoints (CONTRACTS §1):
  POST /api/research                     -> {"run_id"}      (StartRunResponse)
  GET  /api/research/{run_id}/events     -> text/event-stream of ProgressEvent
  POST /api/research/{run_id}/cancel     -> {"run_id","cancelled"}

SSE is implemented manually (sse-starlette is not installed): a StreamingResponse
async-generator replays every event already recorded (so a page refresh / late
connect survives — PRD §9) then live-tails ``run_store`` until a terminal event
(phase done|error). The heavy run itself is a background thread (see
``app.orchestrator.launch``); this async generator only polls the thread-safe
store, so it never blocks the event loop.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from contracts.python.models import ProgressEvent, ResearchRequest

from app.orchestrator import launch, request_cancel
from app.orchestrator.events import make_error_event
from app.store import run_store

router = APIRouter(prefix="/api", tags=["research"])

_TERMINAL_PHASES = {"done", "error"}
_TERMINAL_STATUSES = {"done", "error", "cancelled"}
_SSE_POLL_SECONDS = 0.1  # live-tail cadence
_SSE_ORPHAN_GRACE_SECONDS = 2.0  # stop a stream whose run ended without an event


class StartRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str


class CancelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    cancelled: bool


@router.post("/research", response_model=StartRunResponse)
def start_research(request: ResearchRequest) -> StartRunResponse:
    """Register a run and kick off the background worker; return the id at once."""
    run_id = run_store.create_run(request)
    launch(run_id, request)
    return StartRunResponse(run_id=run_id)


def _phase_of(event: Any) -> Optional[str]:
    if isinstance(event, dict):
        return event.get("phase")
    return getattr(event, "phase", None)


def _event_payload(event: Any) -> dict:
    if isinstance(event, ProgressEvent):
        return event.model_dump()
    if hasattr(event, "model_dump"):
        try:
            return event.model_dump()
        except Exception:
            pass
    if isinstance(event, dict):
        return event
    return {"raw": str(event)}


def _sse_data(event: Any) -> str:
    payload = json.dumps(_event_payload(event), ensure_ascii=False, separators=(",", ":"))
    return "data: %s\n\n" % payload


@router.get("/research/{run_id}/events")
async def research_events(run_id: str, request: Request) -> StreamingResponse:
    """SSE stream of ProgressEvents: replay recorded, then live-tail to terminal."""
    if not run_store.has_run(run_id):
        raise HTTPException(status_code=404, detail="unknown run")

    async def event_stream() -> AsyncIterator[str]:
        yield ": connected\n\n"  # prelude comment: opens the stream promptly
        sent = 0
        orphan_idle = 0.0
        while True:
            if await request.is_disconnected():
                break

            events = run_store.get_events(run_id)
            terminal = False
            while sent < len(events):
                event = events[sent]
                sent += 1
                yield _sse_data(event)
                if _phase_of(event) in _TERMINAL_PHASES:
                    terminal = True
            if terminal:
                break

            status = run_store.get_status(run_id).get("status")
            if status in _TERMINAL_STATUSES:
                # Run ended; if all recorded events are flushed but none was a
                # terminal-phase event (should not happen), close after a grace.
                if sent >= len(run_store.get_events(run_id)):
                    orphan_idle += _SSE_POLL_SECONDS
                    if orphan_idle >= _SSE_ORPHAN_GRACE_SECONDS:
                        yield _sse_data(
                            make_error_event(
                                run_id, "unknown", "Run ended without a terminal event."
                            )
                        )
                        break
            else:
                orphan_idle = 0.0

            await asyncio.sleep(_SSE_POLL_SECONDS)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # disable proxy buffering (e.g. nginx)
    }
    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers=headers
    )


@router.post("/research/{run_id}/cancel", response_model=CancelResponse)
def cancel_research(run_id: str) -> CancelResponse:
    """Cancel a running job; emits a terminal error{code:'cancelled'}."""
    if not run_store.has_run(run_id):
        raise HTTPException(status_code=404, detail="unknown run")
    cancelled = request_cancel(run_id)
    return CancelResponse(run_id=run_id, cancelled=bool(cancelled))
