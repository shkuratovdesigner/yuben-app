"""Research result-read router (B5).

Split from research.py so B4 (lifecycle: start/events/cancel) and B5 (result
read) never edit one file. Owns ``GET /api/research/{run_id}``.

Contract (CONTRACTS §1): return the cached ``ResearchResult`` once a run is done;
otherwise the run's ``{status}``. This endpoint is a pure READ over the shared
``run_store`` — it NEVER re-runs a job (assembly happens in B4's orchestrator via
``app.verify.assemble_and_verify`` before the result is stored).

not-done / not-found responses:
  * result present            -> 200  ResearchResult
  * run exists, not done       -> 200  {"status": <queued|running|error|cancelled>,
                                        "phase": <str>}   (frontend keeps polling)
  * unknown run_id             -> 404  {"status": "not_found", "run_id": <id>}
    (runs live in-memory, so an unknown id — e.g. after a backend restart — is a
    genuine "gone"; 404 lets the client stop polling and reopen from history.)
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.store import run_store

router = APIRouter(prefix="/api", tags=["research"])


@router.get("/research/{run_id}")
def get_research_result(run_id: str):
    result = run_store.get_result(run_id)
    if result is not None:
        # B4 typically stores a validated ResearchResult; serialize via
        # model_dump so datetimes/enums render as JSON. A plain dict (already
        # JSON-able) passes through unchanged.
        if isinstance(result, BaseModel):
            return JSONResponse(content=result.model_dump(mode="json"))
        return result

    status = run_store.get_status(run_id)
    if status.get("status") == "not_found":
        raise HTTPException(
            status_code=404, detail={"status": "not_found", "run_id": run_id}
        )
    # Run exists but has no result yet: report its live status (200) so the
    # loader/poller can keep waiting.
    return status
