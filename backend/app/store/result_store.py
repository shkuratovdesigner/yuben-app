"""Finished-result persistence (B1).

``run_store`` holds live runs in memory, which is right for an in-flight job but
wrong for a finished one: History promises "reopen any past run instantly —
results load from cache, never re-run", and an in-memory cache is empty after
every restart. So the assembled ``ResearchResult`` is written here, next to its
``history`` row, and ``run_store.get_result`` falls back to this table.

Stored as the JSON the API already serves, so a read is a parse, not a re-fetch.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from app.store.db import connect


def save_result(run_id: str, result: Any) -> None:
    """Persist a run's final result. Accepts a pydantic model or a plain dict."""
    payload = result
    if hasattr(result, "model_dump"):
        payload = result.model_dump(mode="json")
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO results (run_id, result_json) VALUES (?, ?)",
            (run_id, json.dumps(payload)),
        )


def load_result(run_id: str) -> Optional[Dict[str, Any]]:
    """The stored result as a dict, or None when this run has none."""
    with connect() as conn:
        row = conn.execute(
            "SELECT result_json FROM results WHERE run_id = ?", (run_id,)
        ).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row["result_json"])
    except (ValueError, TypeError):  # corrupt row — treat as absent, never raise
        return None


def has_result(run_id: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM results WHERE run_id = ?", (run_id,)
        ).fetchone()
    return row is not None
