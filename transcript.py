"""Transcript fetching for YouTube videos.

Uses youtube-transcript-api (v1.2.4+) to fetch transcripts without
consuming any YouTube Data API quota. Handles errors gracefully so
one failed video never kills a batch run.
"""

import sys
import time
from typing import Optional

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    CouldNotRetrieveTranscript,
)


def _log(msg: str) -> None:
    """Print to stderr so stdout JSON stays clean."""
    print(msg, file=sys.stderr)


def get_transcript(video_id: str, languages: list = None) -> Optional[str]:
    """Fetch transcript for a single video.

    Uses youtube_transcript_api to retrieve the transcript, joining all
    segments into a single string separated by spaces.

    Args:
        video_id: YouTube video ID (not the full URL).
        languages: Language codes in descending priority, e.g. ['en', 'en-US'].
            Defaults to ['en']. The library automatically falls back through
            manually-created then auto-generated transcripts for each code.

    Returns:
        Full transcript text as a single string, or None if no transcript
        could be retrieved (disabled, unavailable, blocked, etc.).
    """
    if languages is None:
        languages = ["en"]

    try:
        ytt_api = YouTubeTranscriptApi()
        fetched = ytt_api.fetch(video_id, languages=languages)
        # Join all snippet texts with spaces into one continuous string
        text = " ".join(snippet.text for snippet in fetched)
        return text
    except CouldNotRetrieveTranscript as exc:
        _log(f"[transcript] Could not retrieve transcript for {video_id}: {type(exc).__name__}")
        return None
    except Exception as exc:
        _log(f"[transcript] Unexpected error for {video_id}: {type(exc).__name__}: {exc}")
        return None


def get_transcripts_batch(video_ids: list) -> dict:
    """Fetch transcripts for multiple videos.

    Processes videos sequentially with a small delay between requests
    to avoid rate-limiting. Each video is handled independently so one
    failure does not affect the rest.

    Args:
        video_ids: List of YouTube video IDs.

    Returns:
        Dict mapping each video_id to its transcript text (str) or None
        if the transcript could not be retrieved.
    """
    results = {}
    for i, video_id in enumerate(video_ids):
        results[video_id] = get_transcript(video_id)
        # Small delay between requests to be polite to YouTube
        if i < len(video_ids) - 1:
            time.sleep(0.2)
    return results


if __name__ == "__main__":
    # Quick smoke test with Rick Astley - Never Gonna Give You Up
    test_id = "dQw4w9WgXcQ"
    print(f"Fetching transcript for video: {test_id}")
    transcript = get_transcript(test_id)
    if transcript:
        print(f"Success! Transcript length: {len(transcript)} chars")
        print(f"First 300 chars:\n{transcript[:300]}")
    else:
        print("Failed to retrieve transcript.")
