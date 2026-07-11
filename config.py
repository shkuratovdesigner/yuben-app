"""
YouTube Research Agent — Configuration & Constants

API Setup Instructions:
    1. Go to https://console.cloud.google.com/
    2. Create a project named "YouTube Research Agent"
    3. Enable "YouTube Data API v3" under APIs & Services > Library
    4. Create an API Key under APIs & Services > Credentials
    5. Restrict the key to YouTube Data API v3 only
    6. Add the key to your shell profile:
           export YOUTUBE_API_KEY="your-key-here"
       Append that line to ~/.zshrc, then run `source ~/.zshrc`.
    7. Alternatively, create a .env file in the youtube-research/ directory:
           YOUTUBE_API_KEY=your-key-here
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# Directory that contains *this* file (youtube-research/)
_MODULE_DIR = Path(__file__).resolve().parent

# Try to load a .env file sitting next to this module (youtube-research/.env).
# python-dotenv is a soft dependency — if it is not installed we simply skip.
_dotenv_path = _MODULE_DIR / ".env"
try:
    from dotenv import load_dotenv

    load_dotenv(_dotenv_path)
except ImportError:
    # python-dotenv not installed — rely on env vars set in the shell
    pass

# Project root. Historically hardcoded to a sibling "Business Automation" repo;
# now repo-relative (this file lives at the YuBen repo root) with an optional
# YUBEN_PROJECT_ROOT override, so the pipeline runs from THIS checkout without
# depending on a sibling repo (B3 plumbing fix — paths only, not the algorithms).
PROJECT_ROOT = Path(os.environ.get("YUBEN_PROJECT_ROOT") or _MODULE_DIR)

# Outputs go under outputs/YouTube research results/
OUTPUTS_DIR = PROJECT_ROOT / "outputs" / "YouTube research results"

# Context files live here
CONTEXT_DIR = PROJECT_ROOT / "Context"

# SQLite database path (relative to this module's directory)
DB_PATH = str(_MODULE_DIR / "data" / "channels.db")

# ---------------------------------------------------------------------------
# YouTube API Key
# ---------------------------------------------------------------------------

YOUTUBE_API_KEY: str = os.environ.get("YOUTUBE_API_KEY", "")

if not YOUTUBE_API_KEY:
    _setup_msg = (
        "\n"
        "ERROR: YOUTUBE_API_KEY is not set.\n"
        "\n"
        "To fix this, follow these steps:\n"
        "  1. Go to https://console.cloud.google.com/\n"
        "  2. Create a project named 'YouTube Research Agent'\n"
        "  3. Enable 'YouTube Data API v3' (APIs & Services > Library)\n"
        "  4. Create an API Key (APIs & Services > Credentials)\n"
        "  5. Restrict the key to 'YouTube Data API v3' only\n"
        "  6. Export it in your shell:\n"
        "         export YOUTUBE_API_KEY=\"your-key-here\"\n"
        "     Or add that line to ~/.zshrc and run: source ~/.zshrc\n"
        "  7. Alternatively, create a file at:\n"
        f"         {_dotenv_path}\n"
        "     with the contents:\n"
        "         YOUTUBE_API_KEY=your-key-here\n"
    )
    # Do NOT SystemExit at import time (B3 plumbing fix): the YuBen backend
    # injects the key from its local secret store before invoking the pipeline,
    # and the key-test endpoint validates it explicitly. Emitting guidance to
    # stderr (instead of exiting) keeps `import youtube_research.youtube_api`
    # working for import-plumbing checks and for programmatic callers that set
    # YOUTUBE_API_KEY after import. A run with no key still fails fast, with a
    # clear message, in app.pipeline.run_pipeline.
    print(_setup_msg, file=sys.stderr)

# ---------------------------------------------------------------------------
# Research defaults
# ---------------------------------------------------------------------------

# Channels whose data is older than this are refreshed automatically
MAX_CHANNEL_AGE_DAYS: int = 30

# How many videos to fetch from a channel's uploads playlist
CHANNEL_SAMPLE_SIZE: int = 50

# How many of those videos to use when computing the median view count
CHANNEL_MEDIAN_SAMPLE: int = 30

# Videos shorter than this (in seconds) are treated as Shorts and excluded
MIN_VIDEO_DURATION_SECONDS: int = 60

# Videos younger than this are considered "immature" and excluded from median
MIN_VIDEO_AGE_DAYS: int = 7

# Default multiplier applied to the median to determine "viral" threshold
DEFAULT_MULTIPLIER: float = 5.0

# Default lookback window (days) when scanning for recent videos
DEFAULT_TIME_PERIOD_DAYS: int = 90

# Default cap on the number of videos returned per channel
DEFAULT_MAX_VIDEOS: int = 100
