#!/usr/bin/env python3
"""
normalize_reference.py — the reference implementation of raw-row → unified
``Video`` normalization, kept as the independent second opinion that
``backend/app/pipeline/normalize.py`` is tested against.

This module does **NOT** build fixtures, despite what its old name
(``build_fixtures.py``) implied. The committed fixtures are built by
``build_mock_fixtures.py`` from the curated, oEmbed-verified video set in
``contracts/mock_videos/`` and checked by ``validate_fixtures.py`` — that pair
is what ``make fixtures`` runs. This file writes nothing and has no entry point.

Why keep a second copy of the normalizer? ``test_pipeline.py`` runs raw
``data/*.json`` rows through both this module and the backend's normalizer and
asserts the results are identical. Two independent implementations that agree is
a much stronger signal than one implementation compared against itself, so the
duplication is deliberate — resolve any drift by fixing whichever side is wrong,
never by copying one into the other.

The parity tests skip unless ``data/`` is present; it is gitignored and absent
from a fresh clone.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"

YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


# ---------------------------------------------------------------------------
# Derivations (mirror the pipeline + report builders)
# ---------------------------------------------------------------------------
def duration_label(seconds: int) -> str:
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _num(x):
    if x is None:
        return None
    try:
        f = float(x)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return None


def normalize_video(raw: dict, *, keep_multiplier: bool) -> dict | None:
    """Raw Gen-2 row -> unified Video. Returns None if the id is unusable."""
    vid = str(raw.get("video_id", ""))
    if not YT_ID_RE.match(vid):
        return None

    view = int(_num(raw.get("view_count")) or 0)
    like = _num(raw.get("like_count"))
    comment = _num(raw.get("comment_count"))
    eng_per_1k = round((like / view) * 1000, 2) if (like and view) else 0.0

    vsr = _num(raw.get("views_to_subs"))
    multiplier = _num(raw.get("outlier_multiplier")) if keep_multiplier else None

    watch = f"https://www.youtube.com/watch?v={vid}"
    return {
        "video_id": vid,
        "title": raw.get("title", "") or "(untitled)",
        "url": watch,
        "watch_url": watch,
        "thumbnail_url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
        "channel_id": raw.get("channel_id", "") or "",
        "channel_name": raw.get("channel_name", "") or "",
        "subscriber_count": int(_num(raw.get("subscriber_count")) or 0),
        "view_count": view,
        "like_count": int(like) if like is not None else None,
        "comment_count": int(comment) if comment is not None else None,
        "vsr": vsr,
        "multiplier": multiplier,
        "eng_per_1k": eng_per_1k,
        "engagement_flag": "promoted" if eng_per_1k < 1.5 else "ok",
        "published_at": raw.get("published_at", "") or "1970-01-01T00:00:00Z",
        "duration_seconds": int(_num(raw.get("duration_seconds")) or 0),
        "duration_label": duration_label(int(_num(raw.get("duration_seconds")) or 0)),
        "link_status": "verified",
    }


def load_videos(filename: str, *, keep_multiplier: bool) -> tuple[list[dict], dict]:
    src = json.loads((DATA / filename).read_text())
    videos = []
    for raw in src.get("videos", []):
        v = normalize_video(raw, keep_multiplier=keep_multiplier)
        if v is not None:
            videos.append(v)
    videos.sort(key=lambda v: v["view_count"], reverse=True)
    return videos, src
