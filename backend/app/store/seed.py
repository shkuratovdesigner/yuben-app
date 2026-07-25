"""Bundled example research (B1).

A brand-new install has an empty History, which makes the app hard to read: you
cannot see what a finished run looks like until you have spent YouTube quota on
one. So the demo run shipped in ``contracts/fixtures`` — the same one pictured in
the README — is seeded into the real store on first boot and behaves like any
other saved run: it lists in History and opens from cache.

Two rules keep it honest:
  * It is seeded ONCE. ``seeded_example`` in the config settings records that, so
    deleting the example makes it stay deleted instead of returning next boot.
  * Its numbers are representative, not live API readings, so the result carries
    ``meta.is_example = true``. Nothing forces the UI to show that, but the flag
    travels with the data, so a run of the user's own can always be told apart
    from the bundled one.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from app.store import config_store, history_store, result_store
from contracts.python.models import HistoryItem

# backend/app/store/seed.py -> parents[3] == repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE = _REPO_ROOT / "contracts" / "fixtures" / "research-result.longform.json"

_SEEDED_FLAG = "seeded_example"


def _load_fixture() -> Optional[Dict[str, Any]]:
    try:
        return json.loads(_FIXTURE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def seed_example_research() -> bool:
    """Install the bundled example run if it has never been seeded.

    Returns True when it wrote something. Never raises: a broken or missing
    fixture is a missing example, not a backend that won't boot.
    """
    try:
        settings = config_store.get_settings()
        if settings.get(_SEEDED_FLAG):
            return False

        result = _load_fixture()
        if not result:
            return False

        run_id = result.get("run_id")
        request = result.get("request") or {}
        meta = result.get("meta") or {}
        if not run_id:
            return False

        # Mark it in the payload the UI reads, so the label can't drift from the
        # data: whatever renders this result knows it is the example.
        meta["is_example"] = True
        result["meta"] = meta

        result_store.save_result(run_id, result)
        history_store.add_history(
            HistoryItem(
                run_id=run_id,
                topic_title=result.get("topic_title", "Example research"),
                query=request.get("query", ""),
                format=request.get("format", "longform"),
                created_at=result.get("created_at", ""),
                counts=dict(meta.get("counts") or {}),
                outperformance=request.get("outperformance", "highest"),
            )
        )
        settings[_SEEDED_FLAG] = True
        config_store.save_config(settings=settings)
        return True
    except Exception:  # pragma: no cover - the app boots without an example
        return False
