"""Assemble the final ``ResearchResult`` (B5) — the HARD TRUST RULE lives here.

CONTRACTS §7 steps 2-4 / PRD §8. ``assemble_and_verify`` is the single seam B4's
orchestrator calls right before it emits the terminal ``done`` event:

    result = assemble_and_verify(request, agent_result, pipeline_videos, meta)
    run_store.set_result(run_id, result)   # B4 does this

The agent (``AgentResult``) contributes **narrative only** — topic title,
summary, keywords, learning-goal / why prose, title/script analysis text, and
the *ordering* of videos. Every number, id, link and thumbnail is re-derived
from the deterministic ``pipeline_videos`` the research scripts collected. The
agent is KNOWN to fabricate 11-char ids; the join-and-drop below is the guardrail
that keeps a hand-typed id from ever reaching a rendered ``ResearchResult``.

Trust boundary applied to every agent reference:
  * ``top_video_ids``            -> join to ``pipeline_videos``; drop unknowns.
    The surviving ids, in the agent's rank order (capped to ``max_results``),
    become ``top_videos`` — the only videos rendered as full ``Video`` objects.
  * ``watch_list[].video_id``    -> must resolve to a ``top_videos`` id. The UI
    has no ``Video`` object for anything outside ``top_videos`` (WatchListItem
    carries no title/duration), so a ref outside it is unrenderable and dropped.
    (Stricter than "in pipeline set" but strictly inside the trust boundary, and
    it upholds the frozen invariant watch_list ⊆ top_videos — test_contracts.)
  * ``hook_breakdown[].video_id`` and ``title_formulas[].proof_video_id``
    -> must exist in ``pipeline_videos`` (existence/fabrication guard). These
    carry their own renderable text and link straight to a real id, so they may
    reference a collected video that isn't in the curated ``top_videos`` set.

``meta`` is the deterministic run metadata B4 supplies (dict or attr-object).
Keys read (all optional; sensible fallbacks derived from ``request``):
    run_id, created_at, window, filter, ranking, counts, keywords.

History is written here (``history_store.add_history``) so a HistoryItem is
persisted exactly when a result is assembled — see the B5 handoff note.
"""
from __future__ import annotations

import logging
from typing import Any, List, Mapping, Optional
from uuid import uuid4

from contracts.python.models import (
    AgentResult,
    GamePlan,
    HistoryItem,
    LinkStatus,
    ResearchRequest,
    ResearchResult,
    ResultMeta,
    ScriptAnalysis,
    TitleAnalysis,
    TitleFormula,
    Video,
    WatchListItem,
)

from app.store import history_store
from app.store.db import utcnow_iso
from app.verify.links import LinkVerifier, OEmbedVerifier, watch_url

logger = logging.getLogger("yuben.verify")

# UI → label fallbacks (used only when B4 doesn't pass an explicit meta value).
_WINDOW = {
    "all": "All time",
    "24h": "Last 24 hours",
    "7d": "Last 7 days",
    "30d": "Last 30 days",
    "90d": "Last 90 days",
    "6m": "Last 6 months",
    "1y": "Last year",
}
_FILTER = {"longform": "long-form ≥120s", "shorts": "Shorts ≤65s"}
_PROMOTED_THRESHOLD = 1.5  # PRD §8 engagement guard: Eng/1k < 1.5 → promoted/dead.


# --- derived-field helpers (pure functions of authoritative raw fields) -------
def derive_thumbnail(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def duration_label(seconds: int) -> str:
    """``H:MM:SS`` when there are hours, else ``M:SS`` (mirrors the reports)."""
    seconds = max(int(seconds), 0)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def eng_per_1k(like_count: Optional[int], view_count: int) -> float:
    """Likes per 1,000 views, 2dp (PRD §8). 0.0 when data is missing."""
    if not like_count or not view_count:
        return 0.0
    return round(like_count / view_count * 1000, 2)


def engagement_flag(eng: float) -> str:
    return "promoted" if eng < _PROMOTED_THRESHOLD else "ok"


def _finalize_video(src: Video, link_status: LinkStatus) -> Video:
    """A fresh ``Video`` with authoritative numbers + re-derived fields.

    Numbers (view/like/comment/subscriber counts, vsr, multiplier, published_at,
    duration_seconds, channel, title) are copied verbatim from the pipeline
    video. ``url``/``watch_url``/``thumbnail_url``/``duration_label`` are re-built
    from the id + duration; ``eng_per_1k``/``engagement_flag`` are recomputed per
    PRD §8 (idempotent when the pipeline already applied the same rule).
    """
    eng = eng_per_1k(src.like_count, src.view_count)
    url = watch_url(src.video_id)
    return Video(
        video_id=src.video_id,
        title=src.title,
        url=url,
        watch_url=url,
        thumbnail_url=derive_thumbnail(src.video_id),
        channel_id=src.channel_id,
        channel_name=src.channel_name,
        subscriber_count=src.subscriber_count,
        view_count=src.view_count,
        like_count=src.like_count,
        comment_count=src.comment_count,
        vsr=src.vsr,
        multiplier=src.multiplier,
        eng_per_1k=eng,
        engagement_flag=engagement_flag(eng),
        published_at=src.published_at,
        duration_seconds=src.duration_seconds,
        duration_label=duration_label(src.duration_seconds),
        link_status=link_status,
    )


def _meta_get(meta: Any, key: str, default: Any = None) -> Any:
    if meta is None:
        return default
    if isinstance(meta, Mapping):
        return meta.get(key, default)
    return getattr(meta, key, default)


def _write_history(result: ResearchResult, request: ResearchRequest) -> None:
    """Persist a HistoryItem (best-effort: never fail assembly on a DB hiccup)."""
    try:
        history_store.add_history(
            HistoryItem(
                run_id=result.run_id,
                topic_title=result.topic_title,
                query=request.query,
                format=request.format,
                created_at=result.created_at,
                counts=dict(result.meta.counts),
                outperformance=request.outperformance,
            )
        )
    except Exception:  # pragma: no cover - defensive
        logger.warning("history write failed for run %s", result.run_id, exc_info=True)


def assemble_and_verify(
    request: ResearchRequest,
    agent_result: AgentResult,
    pipeline_videos: List[Video],
    meta: Any,
    *,
    verifier: Optional[LinkVerifier] = None,
    verify_links: bool = True,
    write_history: bool = True,
) -> ResearchResult:
    """Join agent narrative to authoritative videos, verify links, validate.

    Positional signature is the B4 contract:
    ``assemble_and_verify(request, agent_result, pipeline_videos, meta)``.
    Keyword-only extras let tests inject a stub verifier / skip network / skip
    the history write.
    """
    index = {v.video_id: v for v in pipeline_videos}

    # --- top_videos: agent order, drop fabricated + dupes, cap to max_results --
    top_ids: List[str] = []
    seen = set()
    for ref in sorted(agent_result.top_video_ids, key=lambda r: r.rank):
        if ref.video_id in index and ref.video_id not in seen:
            top_ids.append(ref.video_id)
            seen.add(ref.video_id)
    top_ids = top_ids[: request.max_results]
    top_set = set(top_ids)

    # --- link verification for the rendered videos ----------------------------
    own_verifier = False
    if verify_links and verifier is None:
        verifier = OEmbedVerifier()
        own_verifier = True
    try:
        top_videos: List[Video] = []
        for vid in top_ids:
            src = index[vid]
            status: Optional[LinkStatus] = None
            if verify_links and verifier is not None:
                status = verifier.verify(vid)
            # inconclusive → keep the pipeline status; last resort "verified"
            # (the id is already proven real via the pipeline join above).
            final_status: LinkStatus = status or src.link_status or "verified"
            top_videos.append(_finalize_video(src, final_status))
    finally:
        if own_verifier and hasattr(verifier, "close"):
            verifier.close()  # type: ignore[union-attr]

    # --- watch_list: only ids that resolve to a rendered top_video ------------
    watch_list: List[WatchListItem] = [
        w for w in agent_result.watch_list if w.video_id in top_set
    ]

    # --- analysis tabs: null when the matching request toggle was off ---------
    title_analysis: Optional[TitleAnalysis] = (
        agent_result.title_analysis if request.analyze_titles else None
    )
    script_analysis: Optional[ScriptAnalysis] = None
    if request.analyze_scripts and agent_result.script_analysis is not None:
        sa = agent_result.script_analysis
        script_analysis = ScriptAnalysis(
            duration_sweet_spot=sa.duration_sweet_spot,
            structure_patterns=sa.structure_patterns,
            # existence guard: drop hooks whose proof id was fabricated.
            hook_breakdown=[h for h in sa.hook_breakdown if h.video_id in index],
            what_to_avoid=sa.what_to_avoid,
        )

    # --- optional sections ----------------------------------------------------
    title_formulas: Optional[List[TitleFormula]] = None
    if agent_result.title_formulas is not None:
        title_formulas = [
            t for t in agent_result.title_formulas if t.proof_video_id in index
        ]
    game_plan: Optional[GamePlan] = agent_result.game_plan  # no video refs

    # --- meta (deterministic run facts + agent-expanded keywords) -------------
    counts = dict(_meta_get(meta, "counts", {}) or {})
    counts["curated"] = len(top_videos)  # curated always reflects rendered count
    result_meta = ResultMeta(
        window=_meta_get(meta, "window") or _WINDOW.get(request.upload_date, "All time"),
        filter=_meta_get(meta, "filter") or _FILTER.get(request.format, request.format),
        keywords=list(_meta_get(meta, "keywords") or agent_result.keywords),
        ranking=_meta_get(meta, "ranking") or "by views; VSR shown",
        counts=counts,
    )

    run_id = _meta_get(meta, "run_id") or ("r_" + uuid4().hex)
    created_at = _meta_get(meta, "created_at") or utcnow_iso()

    # Construction validates against the ResearchResult Pydantic model
    # (extra="forbid" + field constraints) — raises on any drift.
    result = ResearchResult(
        schema_version="1.0",
        run_id=run_id,
        created_at=created_at,
        request=request,
        topic_title=agent_result.topic_title,
        summary=agent_result.summary,
        meta=result_meta,
        top_videos=top_videos,
        watch_list=watch_list,
        title_analysis=title_analysis,
        script_analysis=script_analysis,
        title_formulas=title_formulas,
        game_plan=game_plan,
    )

    if write_history:
        _write_history(result, request)

    return result
