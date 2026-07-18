"""App config persistence (B1): a single-row config table + derived flags.

``youtube_key_present`` is derived at read time from the secret store, so the
key value never has to live in the config row.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from contracts.python.models import Config

from app.store import secrets
from app.store.db import connect

_SCHEMA_VERSION = "1.0"


def _row_to_config(row: Optional[Any]) -> Config:
    if row is None:
        adapter: Optional[str] = None
        model: Optional[str] = None
        onboarding = False
    else:
        adapter = row["adapter"]
        model = row["model"]
        onboarding = bool(row["onboarding_complete"])
    return Config(
        schema_version=_SCHEMA_VERSION,
        adapter=adapter,
        model=model,
        youtube_key_present=secrets.has_youtube_key(),
        anthropic_key_present=secrets.has_anthropic_key(),
        openai_key_present=secrets.has_openai_key(),
        openrouter_key_present=secrets.has_openrouter_key(),
        onboarding_complete=onboarding,
    )


def get_config() -> Config:
    """Current config. Defaults (no row): adapter/model null, onboarding false."""
    with connect() as conn:
        row = conn.execute(
            "SELECT adapter, model, onboarding_complete FROM config WHERE id = 1"
        ).fetchone()
    return _row_to_config(row)


def get_settings() -> Dict[str, Any]:
    """Free-form settings blob persisted alongside the config (may be empty)."""
    with connect() as conn:
        row = conn.execute("SELECT settings_json FROM config WHERE id = 1").fetchone()
    if row and row["settings_json"]:
        try:
            return json.loads(row["settings_json"])
        except (ValueError, TypeError):
            return {}
    return {}


def save_config(
    adapter: Optional[str] = None,
    model: Optional[str] = None,
    onboarding_complete: Optional[bool] = None,
    settings: Optional[Dict[str, Any]] = None,
) -> Config:
    """Partial upsert: only provided (non-None) fields change; the rest persist.

    Passing ``None`` for a field leaves the stored value unchanged (so an
    onboarding step can set the adapter without wiping a later model choice).
    """
    with connect() as conn:
        row = conn.execute(
            "SELECT adapter, model, onboarding_complete, settings_json "
            "FROM config WHERE id = 1"
        ).fetchone()
        cur_adapter = row["adapter"] if row else None
        cur_model = row["model"] if row else None
        cur_onboarding = bool(row["onboarding_complete"]) if row else False
        cur_settings = row["settings_json"] if row else None

        new_adapter = adapter if adapter is not None else cur_adapter
        new_model = model if model is not None else cur_model
        new_onboarding = (
            onboarding_complete if onboarding_complete is not None else cur_onboarding
        )
        new_settings = json.dumps(settings) if settings is not None else cur_settings

        if row is None:
            conn.execute(
                "INSERT INTO config (id, adapter, model, onboarding_complete, settings_json) "
                "VALUES (1, ?, ?, ?, ?)",
                (new_adapter, new_model, 1 if new_onboarding else 0, new_settings),
            )
        else:
            conn.execute(
                "UPDATE config SET adapter = ?, model = ?, onboarding_complete = ?, "
                "settings_json = ? WHERE id = 1",
                (new_adapter, new_model, 1 if new_onboarding else 0, new_settings),
            )
    return get_config()
