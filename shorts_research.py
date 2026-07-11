"""
Shorts Research — one-off adaptation of the YouTube research pipeline for
SHORT-FORM videos (Shorts, <= ~60s) instead of long-form.

Reuses youtube_api primitives (search_videos, get_video_details) but:
  - KEEPS only Shorts (duration <= MAX_SHORT_SECONDS) instead of filtering them out
  - Ranks by raw views and views-to-subscriber ratio (cross-channel virality)
  - Fetches subscriber counts to compute an outlier signal

Outputs JSON to stdout; logs to stderr.
"""
from __future__ import annotations

import sys
import json
import time
import statistics
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

MAX_SHORT_SECONDS = 65  # tolerance above 60 for rounding / true Shorts


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def get_channel_stats(channel_ids: list) -> dict:
    """Return {channel_id: {subscriber_count, video_count, title}}."""
    service = build_service()
    out: dict = {}
    ids = list({c for c in channel_ids if c})
    for i in range(0, len(ids), 50):
        batch = ids[i : i + 50]
        time.sleep(0.1)
        try:
            resp = (
                service.channels()
                .list(part="statistics,snippet", id=",".join(batch))
                .execute()
            )
        except HttpError as e:
            log(f"channel stats error: {e}")
            continue
        for item in resp.get("items", []):
            stats = item.get("statistics", {})
            out[item["id"]] = {
                "subscriber_count": int(stats.get("subscriberCount", 0)),
                "hidden_subs": stats.get("hiddenSubscriberCount", False),
                "channel_total_videos": int(stats.get("videoCount", 0)),
                "title": item.get("snippet", {}).get("title", ""),
            }
    return out


def run(keywords: list, days: int, published_after_floor: str) -> dict:
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

    # KEEP only Shorts
    shorts = [v for v in details if 0 < v.get("duration_seconds", 0) <= MAX_SHORT_SECONDS]
    log(f"shorts (<= {MAX_SHORT_SECONDS}s): {len(shorts)}")

    # Channel stats for virality signal
    chan_stats = get_channel_stats([v["channel_id"] for v in shorts])

    rows = []
    for v in shorts:
        cs = chan_stats.get(v["channel_id"], {})
        subs = cs.get("subscriber_count", 0)
        views = v["view_count"]
        vsr = round(views / subs, 2) if subs > 0 else None
        rows.append({
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
            "published_at": v.get("published_at", ""),
            "duration_seconds": v.get("duration_seconds", 0),
            "description": (v.get("description", "") or "")[:300],
            "url": f"https://www.youtube.com/shorts/{v['video_id']}",
            "watch_url": f"https://www.youtube.com/watch?v={v['video_id']}",
        })

    rows.sort(key=lambda x: x["view_count"], reverse=True)
    return {
        "published_after": published_after,
        "keywords": keywords,
        "total_search_unique": len(search_rows),
        "total_details": len(details),
        "total_shorts": len(shorts),
        "videos": rows,
    }


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--keywords", nargs="+", required=True)
    p.add_argument("--days", type=int, default=180)
    p.add_argument("--floor", default="2025-12-01T00:00:00Z")
    a = p.parse_args()
    print(json.dumps(run(a.keywords, a.days, a.floor), indent=2, default=str))
