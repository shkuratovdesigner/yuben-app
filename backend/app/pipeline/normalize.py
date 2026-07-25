"""Gen-2 -> unified ``Video`` normalizer (B3).

This MIRRORS ``contracts/normalize_reference.py``'s ``normalize_video`` /
``duration_label`` / ``_num`` byte-for-byte in behavior so that **live pipeline
output and the checked-in fixtures are identical in shape**. The mirroring is
enforced by ``backend/tests/test_pipeline.py`` (it re-normalizes the same
``data/*.json`` through both this module and ``normalize_reference`` and asserts the
rows are equal), so any future drift fails loudly in CI.

Derived fields (CONTRACTS.md §4 / PRD §8):
  * ``thumbnail_url``   = https://i.ytimg.com/vi/<id>/hqdefault.jpg
  * ``duration_label``  from ``duration_seconds``
  * ``eng_per_1k``      = like_count / view_count * 1000  (0.0 when unknown)
  * ``engagement_flag`` = "promoted" when Eng/1k < 1.5 else "ok"   (guards bought views)
  * ``vsr``             = views ÷ subscriber_count (from the script's ``views_to_subs``)
  * ``multiplier``      = views ÷ channel_median (only when medians were computed)

Pure + dependency-free (stdlib only): safe to import without the pipeline deps
or a YouTube key.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

# Engagement guard: below this likes-per-1k-views the views read as promoted /
# bought (PRD §8 / MEMORY: "VSR can be gamed — add engagement filter").
PROMOTED_ENG_PER_1K_THRESHOLD = 1.5


def duration_label(seconds: int) -> str:
    """Seconds -> "H:MM:SS" (or "M:SS" under an hour). Mirrors normalize_reference."""
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _num(x: Any) -> Optional[float]:
    """Coerce to int (when integral) / float / None. Mirrors normalize_reference."""
    if x is None:
        return None
    try:
        f = float(x)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return None


def normalize_video(raw: Dict[str, Any], *, keep_multiplier: bool) -> Optional[Dict[str, Any]]:
    """Raw Gen-2 row -> unified ``Video`` dict. Returns ``None`` if the id is
    unusable (mirrors ``contracts/normalize_reference.py``)."""
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
        "engagement_flag": "promoted" if eng_per_1k < PROMOTED_ENG_PER_1K_THRESHOLD else "ok",
        "published_at": raw.get("published_at", "") or "1970-01-01T00:00:00Z",
        "duration_seconds": int(_num(raw.get("duration_seconds")) or 0),
        "duration_label": duration_label(int(_num(raw.get("duration_seconds")) or 0)),
        "link_status": "verified",
    }


def normalize_videos(
    raw_rows: List[Dict[str, Any]], *, keep_multiplier: bool
) -> List[Dict[str, Any]]:
    """Normalize a list of raw Gen-2 rows, dropping any with unusable ids.

    Sorted by ``view_count`` desc to match ``normalize_reference.load_videos``; the
    outperformance sort/filter is applied afterwards by ``params``.
    """
    out: List[Dict[str, Any]] = []
    for raw in raw_rows:
        v = normalize_video(raw, keep_multiplier=keep_multiplier)
        if v is not None:
            out.append(v)
    out.sort(key=lambda v: v["view_count"], reverse=True)
    return out
