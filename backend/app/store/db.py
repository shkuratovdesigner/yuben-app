"""SQLite persistence for YuBen (B1).

Local, private store under ``backend/.yuben/`` (already gitignored). Uses the
stdlib ``sqlite3`` — no extra deps. A fresh connection is opened per operation
so the store is safe to call from FastAPI's threadpool (SQLite forbids sharing a
single connection across threads).

Data-dir resolution (shared with ``secrets.py`` so the DB and the key file live
together):
  * ``$YUBEN_DATA_DIR`` when set — used by tests for isolation; else
  * ``backend/.yuben`` (repo-relative), created lazily on first use.

Schema — two tables:
  * ``config``      — single row (id = 1): adapter, model, onboarding_complete,
                      settings_json.
  * ``history``     — one row per saved run (mirrors contracts HistoryItem).
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Set

# backend/app/store/db.py -> parents[2] == backend/
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DIR = _BACKEND_ROOT / ".yuben"

# db paths whose schema has already been ensured in this process (fast-path).
_schema_ready: Set[str] = set()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS config (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    adapter             TEXT,
    model               TEXT,
    onboarding_complete INTEGER NOT NULL DEFAULT 0,
    settings_json       TEXT
);
CREATE TABLE IF NOT EXISTS history (
    run_id          TEXT PRIMARY KEY,
    topic_title     TEXT NOT NULL,
    query           TEXT NOT NULL,
    format          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    counts_json     TEXT NOT NULL,
    outperformance  TEXT NOT NULL
);
"""


def data_dir() -> Path:
    """Directory for the local store (DB + secret file). Created if missing."""
    override = os.environ.get("YUBEN_DATA_DIR")
    d = Path(override).expanduser() if override else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return data_dir() / "yuben.db"


def utcnow_iso() -> str:
    """UTC timestamp, ISO-8601 with a trailing ``Z`` (matches the fixtures)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_schema(conn: sqlite3.Connection, path: str) -> None:
    if path in _schema_ready:
        return
    conn.executescript(_SCHEMA)
    conn.commit()
    _schema_ready.add(path)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open a connection (schema ensured), commit on clean exit, always close."""
    path = str(db_path())
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        _ensure_schema(conn, path)
        yield conn
        conn.commit()
    finally:
        conn.close()
