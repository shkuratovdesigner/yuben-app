"""
YouTube Data API v3 wrapper.

Provides functions for searching videos, fetching details, filtering
long-form content, and calculating channel median views.
"""

from __future__ import annotations

import re
import time
import statistics
from typing import Optional
from datetime import datetime, timedelta

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from youtube_research.config import (
    YOUTUBE_API_KEY,
    MIN_VIDEO_DURATION_SECONDS,
    MIN_VIDEO_AGE_DAYS,
    CHANNEL_SAMPLE_SIZE,
    CHANNEL_MEDIAN_SAMPLE,
)

# ---------------------------------------------------------------------------
# Error formatting
# ---------------------------------------------------------------------------

def http_error_note(exc: HttpError) -> str:
    """A short, key-free description of an ``HttpError``.

    NEVER log or print the exception itself. ``googleapiclient`` puts the API
    key in the request URI and ``HttpError.__str__`` interpolates that URI
    verbatim, so ``f"failed: {e}"`` prints a live credential to stdout.

    Defined locally rather than imported from ``app.redact`` because this module
    also runs standalone (``python longform_research.py``), where the backend
    package is not importable.
    """
    status = getattr(getattr(exc, "resp", None), "status", None)
    reason = getattr(exc, "reason", None)
    if isinstance(reason, str) and reason.strip():
        return f"HTTP {status} ({reason.strip()})" if status else reason.strip()
    return f"HTTP {status}" if status else type(exc).__name__


# ---------------------------------------------------------------------------
# Service builder
# ---------------------------------------------------------------------------

def build_service():
    """Creates and returns a YouTube API v3 service object."""
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


# ---------------------------------------------------------------------------
# Duration parser
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(
    r"^PT"
    r"(?:(\d+)H)?"
    r"(?:(\d+)M)?"
    r"(?:(\d+)S)?$"
)


def parse_duration(duration_str: str) -> int:
    """Parse an ISO 8601 duration string (e.g. PT1H2M3S) to total seconds.

    Handles all common formats: PT1H2M3S, PT5M30S, PT45S, PT1H, etc.
    Returns 0 if the string cannot be parsed.
    """
    if not duration_str:
        return 0
    match = _DURATION_RE.match(duration_str)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_videos(
    query: str,
    published_after: str,
    max_results: int = 50,
    region_code: str = "",
    relevance_language: str = "",
) -> list:
    """Search YouTube for videos sorted by view count.

    Parameters
    ----------
    query : str
        The search query string.
    published_after : str
        ISO 8601 datetime string (e.g. '2025-12-01T00:00:00Z').
    max_results : int
        Maximum number of results (up to 50 per API call).
    region_code : str
        ISO 3166-1 alpha-2 country (e.g. 'US'). Biases the result set toward
        what that region ranks. Omitted from the request when empty.
    relevance_language : str
        ISO 639-1 language (e.g. 'en'). Biases toward that language.

    Both hints are *soft*: YouTube treats them as relevance signals, not
    filters, so neither one excludes anything on its own. In particular
    ``relevance_language='en'`` will not narrow results to the US/EU — India is
    one of the largest English-language markets on the platform. The hard-ish
    signal is the channel's declared country, applied downstream as a ranking
    preference in ``app/pipeline/params.py``.

    API cost: 100 units per call.
    """
    service = build_service()
    time.sleep(0.1)

    optional = {}
    if region_code:
        optional["regionCode"] = region_code
    if relevance_language:
        optional["relevanceLanguage"] = relevance_language

    try:
        response = (
            service.search()
            .list(
                q=query,
                type="video",
                order="viewCount",
                publishedAfter=published_after,
                part="snippet",
                maxResults=max_results,
                **optional,
            )
            .execute()
        )
    except HttpError as e:
        if e.resp.status == 403:
            print(f"WARNING: YouTube API quota exceeded during search: {http_error_note(e)}")
            return []
        raise

    results = []
    for item in response.get("items", []):
        snippet = item.get("snippet", {})
        results.append(
            {
                "video_id": item["id"]["videoId"],
                "title": snippet.get("title", ""),
                "channel_id": snippet.get("channelId", ""),
                "channel_title": snippet.get("channelTitle", ""),
                "published_at": snippet.get("publishedAt", ""),
            }
        )
    return results


# ---------------------------------------------------------------------------
# Video details
# ---------------------------------------------------------------------------

def get_video_details(video_ids: list) -> list:
    """Fetch full details for a list of video IDs.

    Requests are batched in groups of 50 (the API maximum).

    Parameters
    ----------
    video_ids : list[str]
        YouTube video IDs.

    Returns
    -------
    list[dict]
        Each dict contains: video_id, title, channel_id, channel_title,
        view_count (int), like_count (int), comment_count (int),
        published_at, description, duration_seconds (int).

    API cost: 1 unit per batch of up to 50 IDs.
    """
    service = build_service()
    all_details = []

    # Process in batches of 50
    for i in range(0, len(video_ids), 50):
        batch_ids = video_ids[i : i + 50]
        time.sleep(0.1)

        try:
            response = (
                service.videos()
                .list(
                    part="statistics,snippet,contentDetails",
                    id=",".join(batch_ids),
                )
                .execute()
            )
        except HttpError as e:
            if e.resp.status == 403:
                print(f"WARNING: YouTube API quota exceeded during video details: {http_error_note(e)}")
                return all_details  # return partial results
            raise

        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            content = item.get("contentDetails", {})

            all_details.append(
                {
                    "video_id": item["id"],
                    "title": snippet.get("title", ""),
                    "channel_id": snippet.get("channelId", ""),
                    "channel_title": snippet.get("channelTitle", ""),
                    "view_count": int(stats.get("viewCount", 0)),
                    "like_count": int(stats.get("likeCount", 0)),
                    "comment_count": int(stats.get("commentCount", 0)),
                    "published_at": snippet.get("publishedAt", ""),
                    "description": snippet.get("description", ""),
                    "duration_seconds": parse_duration(
                        content.get("duration", "")
                    ),
                }
            )

    return all_details


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def filter_long_form(videos: list) -> list:
    """Filter out short-form videos (Shorts).

    Returns only videos whose duration_seconds >= MIN_VIDEO_DURATION_SECONDS.
    """
    return [
        v
        for v in videos
        if v.get("duration_seconds", 0) >= MIN_VIDEO_DURATION_SECONDS
    ]


# ---------------------------------------------------------------------------
# Channel helpers
# ---------------------------------------------------------------------------

def get_channel_uploads_playlist(channel_id: str) -> Optional[str]:
    """Get the uploads playlist ID for a channel.

    Parameters
    ----------
    channel_id : str
        YouTube channel ID.

    Returns
    -------
    str or None
        The uploads playlist ID, or None if not found.

    API cost: 1 unit.
    """
    service = build_service()
    time.sleep(0.1)

    try:
        response = (
            service.channels()
            .list(
                part="contentDetails",
                id=channel_id,
            )
            .execute()
        )
    except HttpError as e:
        if e.resp.status == 403:
            print(f"WARNING: YouTube API quota exceeded fetching channel: {http_error_note(e)}")
            return None
        raise

    items = response.get("items", [])
    if not items:
        return None

    return (
        items[0]
        .get("contentDetails", {})
        .get("relatedPlaylists", {})
        .get("uploads")
    )


def get_playlist_video_ids(
    playlist_id: str,
    max_results: int = 50,
) -> list:
    """Fetch video IDs from a playlist.

    Parameters
    ----------
    playlist_id : str
        YouTube playlist ID.
    max_results : int
        Maximum number of video IDs to return (up to 50).

    Returns
    -------
    list[str]
        Video IDs from the playlist.

    API cost: 1 unit.
    """
    service = build_service()
    time.sleep(0.1)

    try:
        response = (
            service.playlistItems()
            .list(
                part="contentDetails",
                playlistId=playlist_id,
                maxResults=max_results,
            )
            .execute()
        )
    except HttpError as e:
        if e.resp.status == 403:
            print(f"WARNING: YouTube API quota exceeded fetching playlist: {http_error_note(e)}")
            return []
        raise

    return [
        item["contentDetails"]["videoId"]
        for item in response.get("items", [])
        if "contentDetails" in item and "videoId" in item["contentDetails"]
    ]


# ---------------------------------------------------------------------------
# Channel median views
# ---------------------------------------------------------------------------

def get_channel_median_views(
    channel_id: str,
    channel_name: str,
) -> tuple:
    """Calculate median views for a channel's long-form content.

    Steps:
    1. Get uploads playlist via get_channel_uploads_playlist().
    2. Fetch last CHANNEL_SAMPLE_SIZE video IDs via get_playlist_video_ids().
    3. Get full details via get_video_details().
    4. Filter out Shorts (< MIN_VIDEO_DURATION_SECONDS) and videos younger
       than MIN_VIDEO_AGE_DAYS.
    5. Take up to CHANNEL_MEDIAN_SAMPLE most recent remaining videos.
    6. Calculate median views using statistics.median().
    7. Calculate sample_window_days (days between oldest and newest in
       sample).

    Parameters
    ----------
    channel_id : str
        YouTube channel ID.
    channel_name : str
        Human-readable channel name (used for logging).

    Returns
    -------
    tuple[float, int, int]
        (median_views, video_count_sampled, sample_window_days).
        Returns (0.0, 0, 0) if no qualifying videos are found.

    API cost: ~3 units per channel.
    """
    # Step 1: Get uploads playlist
    playlist_id = get_channel_uploads_playlist(channel_id)
    if not playlist_id:
        print(f"  Could not find uploads playlist for {channel_name}")
        return (0.0, 0, 0)

    # Step 2: Fetch recent video IDs
    video_ids = get_playlist_video_ids(playlist_id, max_results=CHANNEL_SAMPLE_SIZE)
    if not video_ids:
        print(f"  No videos found for {channel_name}")
        return (0.0, 0, 0)

    # Step 3: Get full details
    details = get_video_details(video_ids)
    if not details:
        print(f"  Could not fetch video details for {channel_name}")
        return (0.0, 0, 0)

    # Step 4: Filter out Shorts and immature videos
    age_cutoff = datetime.now() - timedelta(days=MIN_VIDEO_AGE_DAYS)
    qualifying = []
    for v in details:
        # Skip Shorts
        if v.get("duration_seconds", 0) < MIN_VIDEO_DURATION_SECONDS:
            continue
        # Skip videos that are too new
        published_str = v.get("published_at", "")
        if published_str:
            try:
                published_dt = datetime.fromisoformat(
                    published_str.replace("Z", "+00:00")
                ).replace(tzinfo=None)
                if published_dt > age_cutoff:
                    continue
            except (ValueError, TypeError):
                pass  # if we can't parse the date, keep the video
        qualifying.append(v)

    if not qualifying:
        print(f"  No qualifying long-form videos for {channel_name}")
        return (0.0, 0, 0)

    # Step 5: Take up to CHANNEL_MEDIAN_SAMPLE most recent
    # Sort by published_at descending to get most recent first
    qualifying.sort(key=lambda v: v.get("published_at", ""), reverse=True)
    sample = qualifying[:CHANNEL_MEDIAN_SAMPLE]

    # Step 6: Calculate median views
    view_counts = [v["view_count"] for v in sample]
    median_views = statistics.median(view_counts)

    # Step 7: Calculate sample window days
    dates = []
    for v in sample:
        published_str = v.get("published_at", "")
        if published_str:
            try:
                dt = datetime.fromisoformat(
                    published_str.replace("Z", "+00:00")
                ).replace(tzinfo=None)
                dates.append(dt)
            except (ValueError, TypeError):
                pass

    if len(dates) >= 2:
        sample_window_days = (max(dates) - min(dates)).days
    else:
        sample_window_days = 0

    video_count_sampled = len(sample)

    print(
        f"  {channel_name}: median={median_views:.0f} views, "
        f"sampled={video_count_sampled}, window={sample_window_days} days"
    )

    return (median_views, video_count_sampled, sample_window_days)
