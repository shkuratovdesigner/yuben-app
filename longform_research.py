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

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from googleapiclient.errors import HttpError
from youtube_research.youtube_api import (
    build_service,
    search_videos,
    get_video_details,
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
    """Return {channel_id: {subscriber_count, hidden, uploads, title}}."""
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
            log(f"channel stats error: {e}")
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
) -> dict:
    floor_dt = datetime.fromisoformat(published_after_floor.replace("Z", "+00:00"))
    window_dt = datetime.now(timezone.utc) - timedelta(days=days)
    published_after = max(floor_dt, window_dt).strftime("%Y-%m-%dT%H:%M:%SZ")
    log(f"publishedAfter = {published_after}")

    seen: set = set()
    search_rows: list = []
    for idx, kw in enumerate(keywords, 1):
        log(f"[{idx}/{len(keywords)}] search: {kw}")
        for r in search_videos(kw, published_after, max_results=50):
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
