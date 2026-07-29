"""``run_pipeline`` — the deterministic SOURCE OF TRUTH for a research run (B3).

B4 calls this. It maps the UI filters to script params, imports+runs the correct
Gen-2 script (``longform_research`` / ``shorts_research``), and normalizes the raw
rows into contract-valid ``Video`` dicts. Every id + number here comes straight
from the YouTube Data API via the scripts — never from agent/LLM text. B5 later
re-verifies links and joins the agent's ``video_id`` references against THIS set,
dropping anything not present, so the whole job's trust rests on this output being
correct, complete and deterministic (PRD §8 / CONTRACTS §7).

Signature
---------
    run_pipeline(
        request: ResearchRequest,        # pydantic model or plain dict
        *,
        keywords: list[str] | None = None,   # agent-expanded terms; else [query]
        compute_medians: bool = False,       # longform outlier_multiplier (extra API)
    ) -> tuple[list[Video-dict], meta-dict]

``meta`` (dict) — top level is exactly the CONTRACTS §5 ``ResultMeta`` shape so
B5 can lift it straight in; pipeline internals live under ``meta["pipeline"]``::

    {
      "window":  "All time",
      "filter":  "long-form ≥120s",
      "keywords": [...searched...],
      "ranking": "by views; VSR shown",
      "counts":  {"unique": N, "longform"|"shorts": M, "curated": K},
      "pipeline": {                        # B3/B4 internals, not part of ResultMeta
        "format": "longform"|"shorts", "script": "longform_research",
        "params": {...}, "published_after": iso, "snapshot_utc": iso,
        "kept": M, "after_outperformance": K2,
        "transcripts": {video_id: text|None} | None,   # when analyze_scripts
      }
    }

Note: ``videos`` is the FULL collected+ranked authoritative set (all rows that
passed the duration + outperformance filters). B5 truncates to ``max_results``
for ``top_videos``; ``counts.curated`` already reflects that cap.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

# Importing _paths ensures the repo root is on sys.path (for `contracts`) and is
# where the youtube_research alias lives.
from ._paths import REPO_ROOT, install_youtube_research_alias
from .normalize import normalize_videos
from .params import (
    REGION_OTHER,
    REGION_UNKNOWN,
    PipelineParams,
    apply_outperformance,
    drop_promoted,
    map_request_to_params,
    region_tier,
)

# Cap transcript fetches so a live run never balloons; transcripts feed the
# agent's script analysis, which only looks at the curated head anyway.
_MAX_TRANSCRIPTS = 15


class PipelineError(RuntimeError):
    """Raised when a live run cannot proceed (missing key, missing script, …).

    Carries a ``code`` matching the CONTRACTS §3 ProgressEvent error codes so the
    orchestrator can map it onto a terminal error event.
    """

    def __init__(self, message: str, *, code: str = "unknown") -> None:
        super().__init__(message)
        self.code = code


def _require_live_key() -> str:
    """Return the stored YouTube key or raise a clear PipelineError.

    Reads the local secret store directly (never the API / env / a URL).
    """
    try:
        from app.store.secrets import get_youtube_key
    except Exception as exc:  # pragma: no cover - store always present in-app
        raise PipelineError(f"secret store unavailable: {exc}", code="unknown")
    key = get_youtube_key()
    if not key:
        raise PipelineError(
            "No YouTube API key is stored. Add your key in Setup before running.",
            code="quota_exceeded",
        )
    return key


def _prime_key(key: str) -> None:
    """Make the Gen-2 modules use ``key``.

    ``config.py`` binds ``YOUTUBE_API_KEY`` once at import and ``youtube_api.py``
    copies the name — so if either was already imported (e.g. keyless, during the
    import-plumbing check) a fresh ``os.environ`` write would be ignored. Set the
    env AND patch the already-bound module globals so ``build_service()`` uses the
    real key deterministically.
    """
    os.environ["YOUTUBE_API_KEY"] = key
    import sys

    for name in ("youtube_research.config", "youtube_research.youtube_api"):
        mod = sys.modules.get(name)
        if mod is not None and getattr(mod, "YOUTUBE_API_KEY", None) != key:
            try:
                setattr(mod, "YOUTUBE_API_KEY", key)
            except Exception:  # pragma: no cover - defensive
                pass


def _run_script(params: PipelineParams) -> Tuple[Dict[str, Any], str, bool]:
    """Import + invoke the correct Gen-2 script's ``run(...)``.

    Returns (raw_result, script_name, keep_multiplier).
    """
    install_youtube_research_alias()

    if params.fmt == "shorts":
        try:
            import shorts_research  # type: ignore
        except ModuleNotFoundError as exc:
            raise PipelineError(
                f"shorts_research.py not importable from {REPO_ROOT}: {exc}",
                code="cli_missing",
            )
        raw = shorts_research.run(
            params.keywords,
            params.days,
            params.floor,
            params.region_code,
            params.relevance_language,
        )
        return raw, "shorts_research", False

    try:
        import longform_research  # type: ignore
    except ModuleNotFoundError as exc:
        raise PipelineError(
            f"longform_research.py not importable from {REPO_ROOT}: {exc}",
            code="cli_missing",
        )
    raw = longform_research.run(
        params.keywords,
        params.days,
        params.floor,
        params.compute_medians,
        params.region_code,
        params.relevance_language,
    )
    return raw, "longform_research", True


def _fetch_transcripts(video_ids: List[str]) -> Dict[str, Optional[str]]:
    """Best-effort transcript fetch (no YouTube Data API quota). Never raises."""
    if not video_ids:
        return {}
    try:
        install_youtube_research_alias()
        from youtube_research.transcript import get_transcripts_batch  # type: ignore
    except Exception as exc:  # pragma: no cover - dep/network guarded
        import sys

        print(f"[pipeline] transcript fetch unavailable: {exc}", file=sys.stderr)
        return {vid: None for vid in video_ids}
    try:
        return get_transcripts_batch(video_ids)
    except Exception as exc:  # pragma: no cover - network guarded
        import sys

        print(f"[pipeline] transcript batch failed: {exc}", file=sys.stderr)
        return {vid: None for vid in video_ids}


def _validate_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep only rows that satisfy the ``Video`` contract; warn+drop the rest.

    The normalizer mirrors the validated fixtures, so this should never drop
    anything in practice — it's a belt-and-suspenders guard so one odd API row
    can't ship an invalid ``Video`` downstream.
    """
    from contracts.python.models import Video  # repo root already on sys.path

    ok: List[Dict[str, Any]] = []
    for row in rows:
        try:
            Video(**row)
            ok.append(row)
        except Exception as exc:  # pragma: no cover - guard only
            import sys

            print(
                f"[pipeline] dropping invalid Video row {row.get('video_id')!r}: {exc}",
                file=sys.stderr,
            )
    return ok


def run_pipeline(
    request: Any,
    *,
    keywords: Optional[List[str]] = None,
    compute_medians: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Run the deterministic research pipeline for ``request``.

    See the module docstring for the return contract. Raises ``PipelineError``
    (with a ProgressEvent ``code``) on unrecoverable setup failures.
    """
    params = map_request_to_params(
        request, keywords=keywords, compute_medians=compute_medians
    )
    if not params.keywords:
        raise PipelineError("query is empty; nothing to search.", code="no_results")

    key = _require_live_key()
    _prime_key(key)

    raw, script_name, keep_multiplier = _run_script(params)
    raw_rows = raw.get("videos", []) or []

    videos = normalize_videos(raw_rows, keep_multiplier=keep_multiplier)
    videos, promoted_dropped = drop_promoted(videos)
    videos = apply_outperformance(videos, params)
    videos = _validate_rows(videos)

    # Region is a preference, not a filter, so these rows are still present —
    # they just sort below the on-region ones. Counting them inside the curated
    # head is what tells the user whether the topic actually has US/EU coverage
    # or whether the table only looks on-region because it was reordered.
    head = videos[: params.max_results]
    off_region_in_head = sum(
        1 for v in head if region_tier(v.get("channel_country", "")) == REGION_OTHER
    )
    undeclared_in_head = sum(
        1 for v in head if region_tier(v.get("channel_country", "")) == REGION_UNKNOWN
    )

    curated = min(len(videos), params.max_results)
    transcripts: Optional[Dict[str, Optional[str]]] = None
    if params.analyze_scripts:
        head_ids = [v["video_id"] for v in videos[: min(curated, _MAX_TRANSCRIPTS)]]
        transcripts = _fetch_transcripts(head_ids)

    count_key = "shorts" if params.fmt == "shorts" else "longform"
    kept_by_duration = int(
        raw.get("total_shorts" if params.fmt == "shorts" else "total_longform")
        or len(videos)
    )

    meta: Dict[str, Any] = {
        # --- CONTRACTS §5 ResultMeta (B5 lifts this subset verbatim) ---
        "window": params.window_label,
        "filter": params.filter_label,
        "keywords": list(params.keywords),
        "ranking": params.ranking_label,
        # ResultMeta.counts is an open map of integers by contract, so the
        # region/engagement tallies belong here rather than buried in the
        # pipeline internals — they are the user's evidence that the filtering
        # ran, and how much of the table it moved.
        "counts": {
            "unique": int(raw.get("total_search_unique", len(videos))),
            count_key: kept_by_duration,
            "curated": curated,
            "promoted_excluded": promoted_dropped,
            "off_region": off_region_in_head,
            "country_undeclared": undeclared_in_head,
        },
        # --- pipeline internals (not part of ResultMeta) ---
        "pipeline": {
            "format": params.fmt,
            "script": script_name,
            "params": params.as_dict(),
            "published_after": raw.get("published_after", ""),
            "snapshot_utc": raw.get("snapshot_utc", ""),
            "kept": kept_by_duration,
            "after_outperformance": len(videos),
            "transcripts": transcripts,
        },
    }
    return videos, meta
