"""Suggestions router (B5) — wires ``app.store.suggestions_store``.

Owns ``POST /api/suggestions``: body ``{text}`` → stored ``Suggestion``. The
request body is bound to ``SuggestionInput`` so contract bounds (1..2000 chars)
are enforced as a clean 422 before anything is persisted; the store re-validates
via the ``Suggestion`` model as a second guard.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from contracts.python.models import Suggestion

from app.store import suggestions_store

router = APIRouter(prefix="/api", tags=["suggestions"])


class SuggestionInput(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.post("/suggestions", response_model=Suggestion)
def create_suggestion(body: SuggestionInput) -> Suggestion:
    return suggestions_store.add_suggestion(body.text)
