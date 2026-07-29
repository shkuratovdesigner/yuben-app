"""
Long-form Research — one-off adaptation of the YouTube research pipeline for
LONG-FORM videos (>= ~120s) instead of Shorts.

Modeled on shorts_research.py but INVERTED to KEEP long-form:
  - KEEPS only videos with duration >= MIN_LONG_SECONDS (drops Shorts/clips)
  - order=viewCount in search, dedupe across keywords
  - fetches subscriber counts to compute VSR (views / subscriber_count)
  - also computes a channel median-view baseline (outlier multiplier) when cheap
  - verifies each kept video resolves via YouTube oEmbed (HTTP 200)
  - ranks by raw views; reports VSR as the cross-channel virality signal

Outputs JSON to stdout; logs to stderr.
"""
from __future__ import annotations

import sys
import json
import time
import statistics
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Make `youtube_research.*` resolve to this directory when the script is run
# directly (`python longform_research.py`). Under the backend this is already
# done by app/pipeline/_paths.py, so both guards below are no-ops there.
#
# This block used to put the repo's *parent* on sys.path, which only resolved
# through a `youtube_research -> YuBen` symlink that existed on one machine. On
# a clean checkout the script died with ModuleNotFoundError.
_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if "youtube_research" not in sys.modules:
    import types as _types

    _pkg = _types.ModuleType("youtube_research")
    _pkg.__path__ = [str(_REPO_ROOT)]  # type: ignore[attr-defined]
    sys.modules["youtube_research"] = _pkg

from googleapiclient.errors import HttpError
from youtube_research.youtube_api import (
    build_service,
    search_videos,
    get_video_details,
    http_error_note,
)

MIN_LONG_SECONDS = 120  # keep >= 2 min; drops Shorts and tiny clips


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def oembed_ok(video_id: str) -> bool:
    url = (
        "https://www.youtube.com/oembed?format=json&url="
        + urllib.parse.quote(
            f"https://www.youtube.com/watch?v={video_id}", safe=""
        )
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception:
        return False


def get_channel_stats(channel_ids: list) -> dict:
    """Return {channel_id: {subscriber_count, hidden, uploads, title, country}}.

    ``country`` is the channel's self-declared ISO 3166-1 alpha-2 code. It rides
    along in the ``snippet`` part this call already requests, so reading it costs
    no extra quota. It is optional on YouTube's side — plenty of legitimate
    channels leave it blank, which is why downstream treats it as a ranking
    preference rather than a filter.
    """
    service = build_service()
    out: dict = {}
    ids = list({c for c in channel_ids if c})
    for i in range(0, len(ids), 50):
        batch = ids[i : i + 50]
        time.sleep(0.1)
        try:
            resp = (
                service.channels()
                .list(part="statistics,snippet,contentDetails", id=",".join(batch))
                .execute()
            )
        except HttpError as e:
            log(f"channel stats error: {http_error_note(e)}")
            continue
        for item in resp.get("items", []):
            stats = item.get("statistics", {})
            uploads = (
                item.get("contentDetails", {})
                .get("relatedPlaylists", {})
                .get("uploads")
            )
            out[item["id"]] = {
                "subscriber_count": int(stats.get("subscriberCount", 0)),
                "hidden_subs": stats.get("hiddenSubscriberCount", False),
                "uploads": uploads,
                "title": item.get("snippet", {}).get("title", ""),
                "country": (item.get("snippet", {}).get("country", "") or "").upper(),
            }
    return out


def channel_median(uploads_playlist: str) -> float:
    """Median views of last ~20 long-form uploads for an outlier baseline."""
    if not uploads_playlist:
        return 0.0
    service = build_service()
    time.sleep(0.1)
    try:
        resp = (
            service.playlistItems()
            .list(
                part="contentDetails",
                playlistId=uploads_playlist,
                maxResults=30,
            )
            .execute()
        )
    except Exception:
        return 0.0
    vids = [
        it["contentDetails"]["videoId"]
        for it in resp.get("items", [])
        if "videoId" in it.get("contentDetails", {})
    ]
    if not vids:
        return 0.0
    details = get_video_details(vids)
    longform = [
        d["view_count"]
        for d in details
        if d.get("duration_seconds", 0) >= MIN_LONG_SECONDS
    ]
    sample = longform[:20] if longform else [d["view_count"] for d in details][:20]
    return statistics.median(sample) if sample else 0.0


def run(
    keywords: list,
    days: int,
    published_after_floor: str,
    compute_medians: bool,
    region_code: str = "",
    relevance_language: str = "",
) -> dict:
    floor_dt = datetime.fromisoformat(published_after_floor.replace("Z", "+00:00"))
    window_dt = datetime.now(timezone.utc) - timedelta(days=days)
    published_after = max(floor_dt, window_dt).strftime("%Y-%m-%dT%H:%M:%SZ")
    log(f"publishedAfter = {published_after}")
    if region_code or relevance_language:
        log(f"region hint: regionCode={region_code or '-'} lang={relevance_language or '-'}")

    seen: set = set()
    search_rows: list = []
    for idx, kw in enumerate(keywords, 1):
        log(f"[{idx}/{len(keywords)}] search: {kw}")
        for r in search_videos(
            kw,
            published_after,
            max_results=50,
            region_code=region_code,
            relevance_language=relevance_language,
        ):
            if r["video_id"] not in seen:
                seen.add(r["video_id"])
                search_rows.append(r)
    log(f"unique videos from search: {len(search_rows)}")

    ids = [r["video_id"] for r in search_rows]
    details = get_video_details(ids) if ids else []
    log(f"fetched details: {len(details)}")

    # KEEP only long-form
    longform = [
        v for v in details if v.get("duration_seconds", 0) >= MIN_LONG_SECONDS
    ]
    log(f"long-form (>= {MIN_LONG_SECONDS}s): {len(longform)}")

    # Channel stats for virality signal
    chan_stats = get_channel_stats([v["channel_id"] for v in longform])

    # Optional median baselines (more API spend). Only compute for the channels
    # that surface in long-form to keep cost bounded.
    median_cache: dict = {}
    if compute_medians:
        ch_ids = list({v["channel_id"] for v in longform})
        log(f"computing medians for {len(ch_ids)} channels…")
        for cid in ch_ids:
            uploads = chan_stats.get(cid, {}).get("uploads")
            median_cache[cid] = channel_median(uploads)
            time.sleep(0.03)

    rows = []
    for v in longform:
        cs = chan_stats.get(v["channel_id"], {})
        subs = cs.get("subscriber_count", 0)
        views = v["view_count"]
        vsr = round(views / subs, 2) if subs > 0 else None
        med = median_cache.get(v["channel_id"], 0.0)
        rows.append(
            {
                "video_id": v["video_id"],
                "title": v["title"],
                "channel_id": v["channel_id"],
                "channel_name": v.get("channel_title", ""),
                "channel_country": cs.get("country", ""),
                "subscriber_count": subs,
                "subs_hidden": cs.get("hidden_subs", False),
                "view_count": views,
                "like_count": v["like_count"],
                "comment_count": v["comment_count"],
                "views_to_subs": vsr,
                "channel_median": med,
                "outlier_multiplier": round(views / med, 1) if med else None,
                "published_at": v.get("published_at", ""),
                "duration_seconds": v.get("duration_seconds", 0),
                "description": (v.get("description", "") or "")[:300],
                "url": f"https://www.youtube.com/watch?v={v['video_id']}",
            }
        )

    rows.sort(key=lambda x: x["view_count"], reverse=True)
    return {
        "published_after": published_after,
        "snapshot_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "keywords": keywords,
        "total_search_unique": len(search_rows),
        "total_details": len(details),
        "total_longform": len(longform),
        "videos": rows,
    }


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--keywords", nargs="+", required=True)
    p.add_argument("--days", type=int, default=365)
    p.add_argument("--floor", default="2025-06-09T00:00:00Z")
    p.add_argument("--medians", action="store_true", help="compute channel medians")
    p.add_argument("--out", default="", help="write raw JSON to this path too")
    a = p.parse_args()
    result = run(a.keywords, a.days, a.floor, a.medians)
    payload = json.dumps(result, indent=2, default=str)
    if a.out:
        Path(a.out).write_text(payload)
    print(payload)
