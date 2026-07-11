"""Liveness probe — GET /api/health (CONTRACTS.md §1)."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "yuben-backend"}
