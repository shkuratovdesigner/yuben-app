"""UI filters -> script params + labels (B3).

Maps a ``ResearchRequest`` (CONTRACTS.md §2) onto the arguments the Gen-2
``run(...)`` functions expect, plus the human labels the results ``meta`` shows.
Pure + stdlib-only so it is trivially unit-testable without the network.

  upload_date -> days + floor
      all -> ~100y window (effectively "all of YouTube"); else the obvious span.
      The scripts compute publishedAfter = max(floor, now - days), so a fixed
      epoch floor lets ``days`` fully drive the window.

  outperformance -> VSR threshold + sort (applied by ``apply_outperformance`` as a
      post-step over the normalized rows — the scripts themselves always rank by
      views, so this is pure wrapping, never an edit to their scoring):
      any -> no floor, rank by views
      2x / 5x / 10x -> keep vsr >= N, rank by views (drops rows whose VSR is
                       unknown — hidden subs — since the threshold can't be met)
      highest -> no floor, rank by VSR desc (unknown VSR sorts last)

  format -> longform_research.py (>=120s) vs shorts_research.py (<=65s)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Effectively-unbounded window for "all time" (~100 years of days).
_ALL_TIME_DAYS = 36_500
_EPOCH_FLOOR = "1970-01-01T00:00:00Z"

# upload_date -> (days, window label)
_UPLOAD_DATE: Dict[str, Tuple[int, str]] = {
    "all": (_ALL_TIME_DAYS, "All time"),
    "24h": (1, "Last 24 hours"),
    "7d": (7, "Last 7 days"),
    "30d": (30, "Last 30 days"),
    "90d": (90, "Last 90 days"),
    "6m": (183, "Last 6 months"),
    "1y": (365, "Last 12 months"),
}

# outperformance -> minimum VSR floor (None = no floor)
_VSR_FLOOR: Dict[str, Optional[float]] = {
    "any": None,
    "2x": 2.0,
    "5x": 5.0,
    "10x": 10.0,
    "highest": None,
}

_FORMAT_FILTER_LABEL = {
    "longform": "long-form ≥120s",
    "shorts": "Shorts ≤65s",
}

# --- Region preference -----------------------------------------------------
# YouTube search has no region *filter*, only relevance hints, and the strongest
# of those (relevanceLanguage="en") does not do what it looks like it does:
# India is one of the largest English-language markets on the platform, so "en"
# happily returns the ₹-denominated AI-automation content it was meant to
# exclude. The only durable signal is the channel's self-declared country, which
# `get_channel_stats` already receives for free in the `snippet` part.
#
# That field is OPTIONAL, though — a large share of legitimate channels leave it
# blank — so it drives a ranking PREFERENCE, never a filter. Off-region videos
# sink; they are not deleted. Undeclared channels sit in the middle so a blank
# field never costs a good channel its place.
#
# Tune the research region by editing these two sets.
CORE_ENGLISH_COUNTRIES = frozenset({"US", "GB", "CA", "AU", "IE", "NZ"})
EUROPE_COUNTRIES = frozenset(
    {
        "DE", "FR", "NL", "SE", "NO", "DK", "FI", "IS", "ES", "IT", "PT",
        "BE", "AT", "CH", "PL", "CZ", "SK", "HU", "RO", "BG", "GR", "HR",
        "SI", "EE", "LV", "LT", "LU", "MT", "CY", "UA", "RS",
    }
)

# Sort tiers — lower sorts first.
REGION_CORE = 0
REGION_EUROPE = 1
REGION_UNKNOWN = 2
REGION_OTHER = 3

# The search hints handed to the YouTube API. Soft signals; the tiering above is
# what actually shapes the table.
DEFAULT_REGION_CODE = "US"
DEFAULT_RELEVANCE_LANGUAGE = "en"


def region_tier(country: str) -> int:
    """Channel country -> sort tier (0 best). "" is treated as unknown, not bad."""
    c = (country or "").strip().upper()
    if not c:
        return REGION_UNKNOWN
    if c in CORE_ENGLISH_COUNTRIES:
        return REGION_CORE
    if c in EUROPE_COUNTRIES:
        return REGION_EUROPE
    return REGION_OTHER


@dataclass
class PipelineParams:
    """Everything the runner needs to drive one deterministic pipeline run."""

    fmt: str  # "longform" | "shorts"
    keywords: List[str]
    days: int
    floor: str
    compute_medians: bool
    outperformance: str
    max_results: int
    analyze_scripts: bool
    analyze_titles: bool
    # labels for results meta
    window_label: str
    filter_label: str
    ranking_label: str
    vsr_floor: Optional[float] = None
    region_code: str = DEFAULT_REGION_CODE
    relevance_language: str = DEFAULT_RELEVANCE_LANGUAGE

    def as_dict(self) -> Dict[str, Any]:
        return {
            "format": self.fmt,
            "keywords": list(self.keywords),
            "days": self.days,
            "floor": self.floor,
            "compute_medians": self.compute_medians,
            "outperformance": self.outperformance,
            "vsr_floor": self.vsr_floor,
            "max_results": self.max_results,
            "analyze_scripts": self.analyze_scripts,
            "analyze_titles": self.analyze_titles,
            "region_code": self.region_code,
            "relevance_language": self.relevance_language,
        }


def _ranking_label(outperformance: str, vsr_floor: Optional[float]) -> str:
    if outperformance == "highest":
        base = "by VSR (views ÷ subscribers), descending"
    elif vsr_floor:
        base = f"VSR ≥ {vsr_floor:g}×, ranked by views"
    else:
        base = "by views; VSR shown"
    return f"{base} — US/Europe channels first, promoted excluded"


def map_request_to_params(
    request: Any,
    *,
    keywords: Optional[List[str]] = None,
    compute_medians: bool = False,
) -> PipelineParams:
    """Translate a ``ResearchRequest`` (pydantic model or plain dict) into
    ``PipelineParams``.

    ``keywords`` lets B4 inject the agent-expanded search terms; when omitted we
    fall back to the raw query as a single keyword so ``run_pipeline(request)``
    works standalone.
    """
    get = request.get if isinstance(request, dict) else (lambda k, d=None: getattr(request, k, d))

    fmt = get("format", "longform")
    upload_date = get("upload_date", "all")
    outperformance = get("outperformance", "highest")
    query = (get("query", "") or "").strip()
    max_results = int(get("max_results", 40) or 40)

    kws = [k for k in (keywords or []) if k and k.strip()]
    if not kws:
        kws = [query] if query else []

    days, window_label = _UPLOAD_DATE.get(upload_date, _UPLOAD_DATE["all"])
    vsr_floor = _VSR_FLOOR.get(outperformance, None)

    return PipelineParams(
        fmt=fmt,
        keywords=kws,
        days=days,
        floor=_EPOCH_FLOOR,
        compute_medians=bool(compute_medians),
        outperformance=outperformance,
        max_results=max_results,
        analyze_scripts=bool(get("analyze_scripts", False)),
        analyze_titles=bool(get("analyze_titles", False)),
        window_label=window_label,
        filter_label=_FORMAT_FILTER_LABEL.get(fmt, fmt),
        ranking_label=_ranking_label(outperformance, vsr_floor),
        vsr_floor=vsr_floor,
        region_code=str(get("region_code", DEFAULT_REGION_CODE) or ""),
        relevance_language=str(
            get("relevance_language", DEFAULT_RELEVANCE_LANGUAGE) or ""
        ),
    )


def drop_promoted(
    videos: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], int]:
    """Split off rows the normalizer flagged as promoted/bought engagement.

    Returns ``(kept, dropped_count)``. A video under 1.5 likes per 1k views is
    almost always ad-driven or bought traffic, which makes its VSR meaningless
    as an outlier signal — the whole premise of the ranking is that views were
    *earned* relative to channel size. The count comes back so the runner can
    report it: filtering that nobody can see is indistinguishable from a bug.
    """
    kept = [v for v in videos if v.get("engagement_flag") != "promoted"]
    return kept, len(videos) - len(kept)


def apply_outperformance(
    videos: List[Dict[str, Any]], params: PipelineParams
) -> List[Dict[str, Any]]:
    """Filter + rank the normalized rows per the outperformance selection.

    Returns a NEW list; ``videos`` are already view-desc sorted by the
    normalizer, which is the tie-stable base order.

    Region tier is the OUTERMOST sort key, so on-region videos occupy the table
    before any off-region one is considered, and the outperformance selection
    orders within each tier. Nothing is dropped for region — a run whose topic
    is genuinely dominated by one other market still returns a full table, just
    with those rows below the ones the user asked for.
    """
    rows = list(videos)

    floor = params.vsr_floor
    if floor is not None:
        rows = [v for v in rows if isinstance(v.get("vsr"), (int, float)) and v["vsr"] >= floor]

    # Mixed sort directions: tier ascends (0 is best), everything else descends,
    # so the descending components are negated instead of using reverse=True.
    if params.outperformance == "highest":
        # VSR desc; unknown VSR (None) sorts last, view_count breaks ties.
        rows.sort(
            key=lambda v: (
                region_tier(v.get("channel_country", "")),
                0 if v.get("vsr") is None else -1,
                -(v.get("vsr") or 0.0),
                -v.get("view_count", 0),
            )
        )
    else:
        rows.sort(
            key=lambda v: (
                region_tier(v.get("channel_country", "")),
                -v.get("view_count", 0),
            )
        )

    return rows
