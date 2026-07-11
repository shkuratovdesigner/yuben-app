"""Research history persistence (B1). B5 wires the /api/history endpoints.

Rows mirror the contracts ``HistoryItem``; ``counts`` is stored as JSON.
"""
from __future__ import annotations

import json
from typing import List

from contracts.python.models import HistoryItem

from app.store.db import connect


def list_history() -> List[HistoryItem]:
    """Saved runs, most-recent-first."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT run_id, topic_title, query, format, created_at, counts_json, "
            "outperformance FROM history ORDER BY created_at DESC, rowid DESC"
        ).fetchall()
    items: List[HistoryItem] = []
    for row in rows:
        items.append(
            HistoryItem(
                run_id=row["run_id"],
                topic_title=row["topic_title"],
                query=row["query"],
                format=row["format"],
                created_at=row["created_at"],
                counts=json.loads(row["counts_json"]),
                outperformance=row["outperformance"],
            )
        )
    return items


def add_history(item: HistoryItem) -> HistoryItem:
    """Insert (or replace) a saved run. Accepts a validated ``HistoryItem``."""
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO history "
            "(run_id, topic_title, query, format, created_at, counts_json, outperformance) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                item.run_id,
                item.topic_title,
                item.query,
                item.format,
                item.created_at,
                json.dumps(item.counts),
                item.outperformance,
            ),
        )
    return item


def delete_history(run_id: str) -> bool:
    """Delete a saved run. True when a row was removed, False when absent."""
    with connect() as conn:
        cur = conn.execute("DELETE FROM history WHERE run_id = ?", (run_id,))
        deleted = cur.rowcount > 0
    return deleted
