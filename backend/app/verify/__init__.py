"""Trust-critical assembly + link verification (B5).

``assemble_and_verify`` (CONTRACTS §7 / PRD §8) joins agent narrative to the
deterministic ``pipeline_videos``, drops fabricated ids, verifies links via
oEmbed, and returns a validated ``ResearchResult``. See ``assemble.py`` for the
HARD TRUST RULE and ``links.py`` for the oEmbed ``link_status`` mapping.
"""
from __future__ import annotations

from app.verify.assemble import assemble_and_verify
from app.verify.links import (
    LinkVerifier,
    OEmbedVerifier,
    classify_status,
    watch_url,
)

__all__ = [
    "assemble_and_verify",
    "LinkVerifier",
    "OEmbedVerifier",
    "classify_status",
    "watch_url",
]
