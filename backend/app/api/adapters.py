"""Adapters router (B2) — CONTRACTS.md §1 / §6.

Owns ``GET /api/adapters``: the installed agent adapters with detected versions
and their selectable models. The ``env-check`` probe lives on the config router
(B1) and delegates to ``app.adapters.check_env``.
"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter

from contracts.python.models import Adapter

from app.adapters import list_adapters

# main.py imports this exact symbol — keep the name and the /api prefix.
router = APIRouter(prefix="/api", tags=["adapters"])


@router.get("/adapters", response_model=List[Adapter])
def get_adapters() -> List[Adapter]:
    """Detect installed adapters (+ version + models). Never 500s on a missing
    CLI — an absent adapter is simply ``installed:false``."""
    return list_adapters()
