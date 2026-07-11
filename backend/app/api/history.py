"""History router (B5) — wires the durable run history (``app.store.history_store``).

Owns ``GET /api/history`` (list saved runs, most-recent-first) and
``DELETE /api/history/{run_id}`` (remove one; 404 when absent). History rows are
written by ``app.verify.assemble_and_verify`` when a run's result is assembled,
so this router is a thin read/delete surface over the store.
"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException

from contracts.python.models import HistoryItem

from app.store import history_store

router = APIRouter(prefix="/api", tags=["history"])


@router.get("/history", response_model=List[HistoryItem])
def get_history() -> List[HistoryItem]:
    return history_store.list_history()


@router.delete("/history/{run_id}")
def remove_history(run_id: str) -> dict:
    if not history_store.delete_history(run_id):
        raise HTTPException(
            status_code=404, detail={"status": "not_found", "run_id": run_id}
        )
    return {"ok": True, "run_id": run_id}
