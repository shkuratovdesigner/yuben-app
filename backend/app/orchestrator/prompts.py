"""Prompt builder + UI->script filter mapping (B4).

:func:`map_filters` turns a ``ResearchRequest`` into concrete script parameters
(CONTRACTS §2 "Backend mapping"). :func:`build_prompt` bakes those filters, the
CONTRACTS §7 agent output contract, and the HARD TRUST RULE (PRD §8) into a
single instruction. The agent supplies **narrative + video_id references only**;
the backend (B3 pipeline + B5 verify) owns every number and link.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from contracts.python.models import ResearchRequest

# upload_date -> lookback window in days (CONTRACTS §2). ``all`` = no floor.
_UPLOAD_DAYS: Dict[str, Optional[int]] = {
    "all": None,
    "24h": 1,
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "6m": 183,
    "1y": 365,
}

# upload_date -> human window label (PRD §6 composer copy).
_WINDOW_LABEL: Dict[str, str] = {
    "all": "All time",
    "24h": "Last 24 hours",
    "7d": "Last 7 days",
    "30d": "Last 30 days",
    "90d": "Last 90 days",
    "6m": "Last 6 months",
    "1y": "Last year",
}

# outperformance -> (mode, threshold, sort, label). CONTRACTS §2.
_OUTPERF: Dict[str, Dict[str, Any]] = {
    "any": {"mode": "any", "threshold": None, "sort": "views_desc", "label": "Any"},
    "2x": {"mode": "min_vsr", "threshold": 2.0, "sort": "vsr_desc", "label": "2× and up"},
    "5x": {"mode": "min_vsr", "threshold": 5.0, "sort": "vsr_desc", "label": "5× and up"},
    "10x": {"mode": "min_vsr", "threshold": 10.0, "sort": "vsr_desc", "label": "10× and up"},
    "highest": {"mode": "sort", "threshold": None, "sort": "vsr_desc", "label": "Highest first"},
}

_FORMAT_SCRIPT: Dict[str, str] = {
    "longform": "longform_research.py",
    "shorts": "shorts_research.py",
}
_FORMAT_DURATION: Dict[str, str] = {
    "longform": "long-form ≥120s",
    "shorts": "Shorts ≤65s",
}


def map_filters(request: ResearchRequest) -> Dict[str, Any]:
    """UI selections -> concrete script parameters (deterministic, no I/O)."""
    days = _UPLOAD_DAYS.get(request.upload_date)
    floor_iso: Optional[str] = None
    if days is not None:
        floor_iso = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
    outperf = _OUTPERF.get(request.outperformance, _OUTPERF["highest"])
    return {
        "query": request.query,
        "format": request.format,
        "script": _FORMAT_SCRIPT[request.format],
        "duration_filter": _FORMAT_DURATION[request.format],
        "days": days,
        "floor_iso": floor_iso,
        "window_label": _WINDOW_LABEL.get(request.upload_date, request.upload_date),
        "outperformance": outperf,
        "outperformance_label": outperf["label"],
        "max_results": request.max_results,
        "analyze_titles": request.analyze_titles,
        "analyze_scripts": request.analyze_scripts,
        "adapter": request.model.adapter,
        "model": request.model.model,
    }


# --- HARD TRUST RULE (PRD §8 / CONTRACTS §7) -- baked verbatim into the prompt.
TRUST_INSTRUCTION = (
    "HARD RULE — TRUST: You MUST NOT invent, guess, or fabricate video IDs, "
    "view counts, subscriber counts, durations, or ANY numbers. Reference each "
    "video ONLY by its real 11-character YouTube video_id exactly as printed in "
    "the research script's JSON output. Provide narrative only — the backend "
    "attaches all authoritative numbers, derives thumbnails and links, and DROPS "
    "any video_id that is not present in the deterministic results. A fabricated "
    "ID is worse than an omitted one."
)

# The exact JSON envelope the CLI must emit (CONTRACTS §7 / AgentResult schema).
_OUTPUT_CONTRACT = """\
OUTPUT CONTRACT — emit EXACTLY ONE JSON object and NOTHING else (no prose, no
code fences) as your final message. It must match this shape:

{
  "schema_version": "1.0",
  "topic_title": "<a polished title for this research topic>",
  "summary": "<one- or two-sentence thesis of what wins in this space>",
  "keywords": ["<expanded search term>", "..."],
  "top_video_ids": [ { "video_id": "<11-char id>", "rank": 1 }, ... ],
  "watch_list": [
    { "video_id": "<11-char id>",
      "learning_goal": "<what the viewer learns>",
      "why": "<why this one is worth watching>",
      "rank": 1 }
  ],
  "title_analysis": <object|null>,
  "script_analysis": <object|null>,
  "title_formulas": <array|null>,
  "game_plan": <object|null>
}

Rules:
- Every video_id in top_video_ids / watch_list / hook_breakdown / proof_video_id
  MUST be a real id from the script output. Do not carry numbers into the JSON.
- title_analysis: { "common_features": [ {"n","pattern","note","count"} ],
  "emotional_triggers": [ {"n","trigger","example"} ] }.
- script_analysis: { "duration_sweet_spot": [ {"label","value"} ],
  "structure_patterns": [ {"name","note"} ],
  "hook_breakdown": [ {"rank","title","hook","video_id"} ],
  "what_to_avoid": [ "..." ] }.
"""


def _toggles_block(filters: Dict[str, Any]) -> str:
    titles = "ON" if filters["analyze_titles"] else "OFF"
    scripts = "ON" if filters["analyze_scripts"] else "OFF"
    lines = [
        "- Titles Analytic: %s" % titles,
        "  %s"
        % (
            "Include a title_analysis object (common features + emotional triggers)."
            if filters["analyze_titles"]
            else "Set title_analysis to null (the user did not request it)."
        ),
        "- Script analytics: %s" % scripts,
        "  %s"
        % (
            "Fetch transcripts and include a script_analysis object "
            "(duration sweet spot, structure patterns, hook breakdown, what to avoid)."
            if filters["analyze_scripts"]
            else "Set script_analysis to null (do not fetch transcripts)."
        ),
    ]
    return "\n".join(lines)


def _outperf_line(outperf: Dict[str, Any]) -> str:
    if outperf["mode"] == "any":
        return "Any outlier level; rank by view count (no VSR floor)."
    if outperf["mode"] == "sort":
        return "Highest outperformance first; rank by VSR (views ÷ subscribers) descending."
    return (
        "Keep videos with VSR ≥ %.1f (or channel-median multiplier when medians "
        "are on); rank by VSR descending." % outperf["threshold"]
    )


def _filters_block(f: Dict[str, Any], *, name_the_script: bool = True) -> str:
    """The MAPPED FILTERS block shared by the agentic + direct prompts.

    ``name_the_script`` is on for the agentic CLI (it runs the script itself) and
    off for the direct path (the backend already ran the pipeline — the model has
    no script to run).
    """
    window = f["window_label"]
    if f["floor_iso"]:
        window = "%s (published on or after %s)" % (window, f["floor_iso"])
    if name_the_script:
        format_line = "- Format: %s — run %s (%s)." % (
            f["format"], f["script"], f["duration_filter"],
        )
    else:
        format_line = "- Format: %s (%s)." % (f["format"], f["duration_filter"])
    return "\n".join(
        [
            "- Topic / query: %s" % f["query"],
            format_line,
            "- Upload window: %s" % window,
            "- Outperformance: %s — %s"
            % (f["outperformance_label"], _outperf_line(f["outperformance"])),
            "- Return at most %d curated videos (max_results = %d)."
            % (f["max_results"], f["max_results"]),
        ]
    )


def build_prompt(
    request: ResearchRequest, *, filters: Optional[Dict[str, Any]] = None
) -> str:
    """Build the full agent instruction from a ``ResearchRequest`` (agentic CLI)."""
    f = filters if filters is not None else map_filters(request)
    filters_block = _filters_block(f)

    return "\n\n".join(
        [
            "You are YuBen's YouTube research agent. Turn one topic into a proven "
            "video plan by finding outlier videos (videos that vastly outperform "
            "their channel size) and explaining why they win.",
            TRUST_INSTRUCTION,
            "TASK\n"
            "1. Expand the topic into a focused set of YouTube search keywords.\n"
            "2. Run the correct research script with the mapped filters below; it "
            "prints the qualifying videos as JSON to stdout (views, subscriber "
            "counts, VSR, durations — all authoritative).\n"
            "3. If Script analytics is ON, fetch transcripts (no API quota) for the "
            "top videos.\n"
            "4. Analyze the winners: title patterns, hooks, ideal length, what to "
            "avoid — and draft a game plan.\n"
            "5. Emit the single AgentResult JSON object described below.",
            "MAPPED FILTERS\n" + filters_block,
            "ANALYSIS TOGGLES\n" + _toggles_block(f),
            _OUTPUT_CONTRACT,
            "Reminder: the ONLY things you author are narrative and real video_id "
            "references. Numbers and links come from the scripts, not from you.",
        ]
    )


def build_repair_prompt(
    original_prompt: str, bad_output: Any, error: str
) -> str:
    """One-shot error-correcting retry prompt (validate/repair path)."""
    if bad_output is None:
        prior = "(no JSON object was found in your previous output)"
    else:
        try:
            import json

            prior = json.dumps(bad_output)[:2000]
        except Exception:
            prior = str(bad_output)[:2000]
    return "\n\n".join(
        [
            "REPAIR REQUEST — your previous response was not a valid AgentResult.",
            "Validation error:\n%s" % error,
            "What you returned (truncated):\n%s" % prior,
            "Re-emit EXACTLY ONE valid JSON object matching the AgentResult schema "
            "and NOTHING else — no prose, no code fences, no explanation. Keep "
            "the same real video_id references; only fix the JSON so it validates. "
            "Do not invent IDs or numbers.",
            TRUST_INSTRUCTION,
        ]
    )


# ---------------------------------------------------------------------------
# Direct (non-agentic) adapter prompts — the LLM's two steps, fed by run_pipeline
# ---------------------------------------------------------------------------
# The direct adapter (DirectAnthropicAdapter) has NO tools: it can't run the
# research scripts. So B4 drives the two LLM steps itself — (1) expand keywords to
# broaden the deterministic search, (2) write the AgentResult narrative over the
# videos the pipeline already collected. Facts still come only from run_pipeline;
# the trust guard is unchanged.

# Bound the video list baked into the narrative prompt (the pipeline head is
# already ranked; the model curates the top max_results from these).
_DIRECT_MAX_VIDEOS = 60
# How many top videos to attach transcript snippets for (script analysis only).
_DIRECT_MAX_TRANSCRIPTS = 8
_TRANSCRIPT_SNIPPET_CHARS = 600


def build_expand_prompt(
    request: ResearchRequest, *, filters: Optional[Dict[str, Any]] = None
) -> str:
    """Direct-path LLM step 1: expand one topic into YouTube search phrases.

    The model returns a JSON array of short search queries; B4 feeds them to
    ``run_pipeline`` to broaden the deterministic search (this is the concrete
    "keyword expansion" the cost meter budgets for). Best-effort — B4 falls back
    to the raw query if the array can't be parsed.
    """
    f = filters if filters is not None else map_filters(request)
    return "\n\n".join(
        [
            "You are YuBen's YouTube research assistant. Expand ONE research topic "
            "into a focused set of YouTube SEARCH QUERIES that will surface outlier "
            "videos (videos that beat their channel size).",
            "TOPIC: %s" % request.query,
            "FORMAT: %s (%s)." % (f["format"], f["duration_filter"]),
            "Return BETWEEN 6 AND 12 short search phrases (2–5 words each): specific, "
            "varied angles a creator would actually type into YouTube — include the "
            "core topic plus adjacent framings. No full sentences, no hashtags, no "
            "duplicates.",
            'OUTPUT: a single JSON array of strings and NOTHING else. Example:\n'
            '["how to promote your airbnb", "airbnb direct booking tips", '
            '"short term rental marketing", "airbnb listing optimization"]',
        ]
    )


def _video_brief(video: Any) -> Dict[str, Any]:
    """A compact, authoritative record of one collected video for the prompt.

    Only the fields the model needs to CURATE + reference are included (no derived
    URLs/thumbnails — the backend owns those). Numbers are the pipeline's, so the
    model can rank by real outperformance without inventing anything.
    """
    return {
        "video_id": video.video_id,
        "title": video.title,
        "channel": video.channel_name,
        "subscribers": video.subscriber_count,
        "views": video.view_count,
        "vsr": video.vsr,
        "duration": video.duration_label,
        "published_at": video.published_at,
    }


def _transcripts_block(videos: List[Any], meta: Any, f: Dict[str, Any]) -> str:
    """Optional transcript snippets for the top videos (script analysis only)."""
    if not f["analyze_scripts"] or not isinstance(meta, dict):
        return ""
    transcripts = (meta.get("pipeline") or {}).get("transcripts")
    if not isinstance(transcripts, dict):
        return ""
    lines: List[str] = []
    for video in videos[:_DIRECT_MAX_TRANSCRIPTS]:
        text = transcripts.get(video.video_id)
        if not text:
            continue
        snippet = " ".join(str(text).split())[:_TRANSCRIPT_SNIPPET_CHARS]
        lines.append('- %s ("%s"): %s…' % (video.video_id, video.title[:60], snippet))
    if not lines:
        return ""
    return (
        "TRANSCRIPT SNIPPETS (opening lines — for hook/structure analysis only; "
        "still reference each by its real video_id):\n" + "\n".join(lines)
    )


def build_direct_prompt(
    request: ResearchRequest,
    videos: List[Any],
    meta: Any = None,
    *,
    filters: Optional[Dict[str, Any]] = None,
) -> str:
    """Direct-path LLM step 2: the AgentResult narrative over collected videos.

    ``videos`` is the deterministic, authoritative set from ``run_pipeline`` (Video
    models). The model curates + ranks them by ``video_id``, writes the analysis,
    and emits the same ``AgentResult`` envelope the CLI does — so B5's
    ``assemble_and_verify`` join is byte-for-byte identical. It has no tools and
    invents nothing; every id it may use is printed below.
    """
    f = filters if filters is not None else map_filters(request)
    briefs = [_video_brief(v) for v in list(videos)[:_DIRECT_MAX_VIDEOS]]
    videos_json = json.dumps(briefs, ensure_ascii=False)
    transcripts_block = _transcripts_block(list(videos), meta, f)

    parts = [
        "You are YuBen's YouTube research analyst. You have NO tools and you do NOT "
        "run any scripts — every fact you need is already provided below, collected "
        "deterministically from the YouTube Data API.",
        TRUST_INSTRUCTION,
        "TASK\n"
        "1. Expand the topic into search keywords and echo them in the JSON "
        "'keywords' (narrative only).\n"
        "2. From the COLLECTED VIDEOS below, curate and RANK the strongest outliers "
        "(highest views relative to channel size / VSR). Reference each ONLY by its "
        "real video_id exactly as printed — never invent or alter one.\n"
        "3. Analyze why the winners work: title patterns, hooks, ideal length, and "
        "what to avoid — and draft a game plan.\n"
        "4. Emit the single AgentResult JSON object described below.",
        "MAPPED FILTERS\n" + _filters_block(f, name_the_script=False),
        "ANALYSIS TOGGLES\n" + _toggles_block(f),
        "COLLECTED VIDEOS (authoritative — the ONLY valid video_id values, already "
        "ranked; curate the top %d):\n%s" % (f["max_results"], videos_json),
        transcripts_block,
        _OUTPUT_CONTRACT,
        "Reminder: reference ONLY video_id values that appear in COLLECTED VIDEOS. "
        "Numbers and links come from YuBen, not from you — provide narrative only.",
    ]
    return "\n\n".join(part for part in parts if part)
