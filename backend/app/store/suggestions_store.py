"""Feature-suggestion persistence (B1). B5 wires POST /api/suggestions.

Constructing the ``Suggestion`` first enforces the contract bounds
(1..2000 chars) before anything is written — an empty/oversized suggestion
raises ``pydantic.ValidationError`` and nothing is persisted.
"""
from __future__ import annotations

from contracts.python.models import Suggestion

from app.store.db import connect, utcnow_iso


def add_suggestion(text: str) -> Suggestion:
    suggestion = Suggestion(text=text, created_at=utcnow_iso())
    with connect() as conn:
        conn.execute(
            "INSERT INTO suggestions (text, created_at) VALUES (?, ?)",
            (suggestion.text, suggestion.created_at),
        )
    return suggestion
