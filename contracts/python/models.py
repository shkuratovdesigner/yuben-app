"""
Pydantic v2 models mirroring contracts/schemas/*.json (and docs/CONTRACTS.md).

`extra="forbid"` everywhere so the models catch contract drift the same way the
JSON Schemas' `additionalProperties:false` does. The backend (B1–B5) imports
these to validate agent output and to serialize the final ResearchResult.
"""
from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Format = Literal["longform", "shorts"]
UploadDate = Literal["all", "24h", "7d", "30d", "90d", "6m", "1y"]
Outperformance = Literal["any", "2x", "5x", "10x", "highest"]
EngagementFlag = Literal["ok", "promoted"]
LinkStatus = Literal["verified", "embed_disabled", "dead"]
ProgressPhase = Literal[
    "queued", "expanding", "searching", "enriching",
    "scoring", "analyzing", "verifying", "done", "error",
]
ErrorCode = Literal[
    "quota_exceeded", "cli_missing", "cli_failed", "no_results",
    "invalid_output", "cancelled", "unknown",
]


class Strict(BaseModel):
    """Base: reject unknown keys (mirrors additionalProperties:false)."""

    model_config = ConfigDict(extra="forbid")


# --- ResearchRequest -------------------------------------------------------
class ModelSelection(Strict):
    adapter: str
    model: str


class ResearchRequest(Strict):
    schema_version: Literal["1.0"]
    query: str = Field(min_length=1)
    format: Format
    upload_date: UploadDate
    outperformance: Outperformance
    analyze_titles: bool
    analyze_scripts: bool
    model: ModelSelection
    max_results: int = Field(default=15, ge=1, le=100)


# --- Video -----------------------------------------------------------------
class Video(Strict):
    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")
    title: str = Field(min_length=1)
    url: str
    watch_url: str
    thumbnail_url: str
    channel_id: str
    channel_name: str
    subscriber_count: int = Field(ge=0)
    view_count: int = Field(ge=0)
    like_count: Optional[int] = Field(default=None, ge=0)
    comment_count: Optional[int] = Field(default=None, ge=0)
    vsr: Optional[float] = Field(default=None, ge=0)
    multiplier: Optional[float] = Field(default=None, ge=0)
    eng_per_1k: float = Field(ge=0)
    engagement_flag: EngagementFlag
    published_at: str
    duration_seconds: int = Field(ge=0)
    duration_label: str
    link_status: LinkStatus


# --- ProgressEvent ---------------------------------------------------------
class ProgressErrorDetail(Strict):
    code: ErrorCode
    message: str


class ProgressEvent(Strict):
    run_id: str
    phase: ProgressPhase
    label: str
    pct: Optional[int] = Field(default=None, ge=0, le=100)
    detail: Optional[str] = None
    counts: Optional[Dict[str, int]] = None
    error: Optional[ProgressErrorDetail] = None
    ts: str


# --- ResearchResult --------------------------------------------------------
class WatchListItem(Strict):
    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")
    learning_goal: str
    why: str
    rank: int = Field(ge=1)


class CommonFeature(Strict):
    n: int = Field(ge=1)
    pattern: str
    note: str
    count: int = Field(ge=0)


class EmotionalTrigger(Strict):
    n: int = Field(ge=1)
    trigger: str
    example: str


class TitleAnalysis(Strict):
    common_features: List[CommonFeature]
    emotional_triggers: List[EmotionalTrigger]


class DurationStat(Strict):
    label: str
    value: str


class StructurePattern(Strict):
    name: str
    note: str


class HookBreakdown(Strict):
    rank: int = Field(ge=1)
    title: str
    hook: str
    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")


class ScriptAnalysis(Strict):
    duration_sweet_spot: List[DurationStat]
    structure_patterns: List[StructurePattern]
    hook_breakdown: List[HookBreakdown]
    what_to_avoid: List[str]


class TitleFormula(Strict):
    shape: str
    proof_video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")
    tailored: str


class GamePlanBeat(Strict):
    t: str
    beat: str


class GamePlan(Strict):
    outline: List[GamePlanBeat]
    title_options: List[str]
    thumbnail_concepts: List[str]
    do: str
    dont: str


class ResultMeta(Strict):
    window: str
    filter: str
    keywords: List[str]
    ranking: str
    counts: Dict[str, int]


class ResearchResult(Strict):
    schema_version: Literal["1.0"]
    run_id: str
    created_at: str
    request: ResearchRequest
    topic_title: str
    summary: str
    meta: ResultMeta
    top_videos: List[Video]
    watch_list: List[WatchListItem]
    title_analysis: Optional[TitleAnalysis]
    script_analysis: Optional[ScriptAnalysis]
    title_formulas: Optional[List[TitleFormula]] = None
    game_plan: Optional[GamePlan] = None


# --- Config / Adapter / History -------------------------------------------
class Config(Strict):
    schema_version: Literal["1.0"]
    adapter: Optional[str]
    model: Optional[str]
    youtube_key_present: bool
    # Whether the user's Anthropic API key is stored (direct adapter, Phase 4).
    # Defaulted for backward-compatible loads of pre-Phase-4 configs.
    anthropic_key_present: bool = False
    onboarding_complete: bool


class Adapter(Strict):
    id: str
    name: str
    installed: bool
    version: Optional[str]
    models: List[str]


class HistoryItem(Strict):
    run_id: str
    topic_title: str
    query: str
    format: Format
    created_at: str
    counts: Dict[str, int]
    outperformance: Outperformance


# --- AgentResult (CLI -> backend; narrative + video_id refs only) ---------
class AgentTopVideoRef(Strict):
    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")
    rank: int = Field(ge=1)


class AgentResult(Strict):
    schema_version: Literal["1.0"]
    topic_title: str
    summary: str
    keywords: List[str]
    top_video_ids: List[AgentTopVideoRef]
    watch_list: List[WatchListItem]
    title_analysis: Optional[TitleAnalysis]
    script_analysis: Optional[ScriptAnalysis]
    title_formulas: Optional[List[TitleFormula]] = None
    game_plan: Optional[GamePlan] = None
