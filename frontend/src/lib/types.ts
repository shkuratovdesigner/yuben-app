/**
 * YuBen contract types — the TypeScript mirror of contracts/schemas/*.json.
 *
 * Single source of truth: docs/CONTRACTS.md. Keep in lockstep with the JSON
 * Schemas and Pydantic models. The frontend imports everything from here
 * (`@/lib/types`); the mock + live API clients return these shapes.
 */

export type SchemaVersion = '1.0'
export type Format = 'longform' | 'shorts'
export type UploadDate = 'all' | '24h' | '7d' | '30d' | '90d' | '6m' | '1y'
export type Outperformance = 'any' | '2x' | '5x' | '10x' | 'highest'
export type EngagementFlag = 'ok' | 'promoted'
export type LinkStatus = 'verified' | 'embed_disabled' | 'dead'

export type ProgressPhase =
  | 'queued'
  | 'expanding'
  | 'searching'
  | 'enriching'
  | 'scoring'
  | 'analyzing'
  | 'verifying'
  | 'done'
  | 'error'

export type ErrorCode =
  | 'quota_exceeded'
  | 'cli_missing'
  | 'cli_failed'
  | 'no_results'
  | 'invalid_output'
  | 'cancelled'
  | 'unknown'

// --- ResearchRequest (composer -> backend) --------------------------------
export interface ModelSelection {
  adapter: string
  model: string
}

export interface ResearchRequest {
  schema_version: SchemaVersion
  query: string
  format: Format
  upload_date: UploadDate
  outperformance: Outperformance
  analyze_titles: boolean
  analyze_scripts: boolean
  model: ModelSelection
  max_results?: number
}

// --- Video (unified) -------------------------------------------------------
export interface Video {
  video_id: string
  title: string
  url: string
  watch_url: string
  thumbnail_url: string
  channel_id: string
  channel_name: string
  subscriber_count: number
  view_count: number
  like_count: number | null
  comment_count: number | null
  /** views / subscriber_count — primary outlier signal; null when subs hidden/0. */
  vsr: number | null
  /** views / channel_median — only when medians computed, else null. */
  multiplier: number | null
  /** like_count / view_count * 1000. */
  eng_per_1k: number
  engagement_flag: EngagementFlag
  /** Channel's self-declared ISO 3166-1 alpha-2 country; '' when unset. */
  channel_country: string
  published_at: string
  duration_seconds: number
  duration_label: string
  link_status: LinkStatus
}

// --- ProgressEvent (SSE -> loader) ----------------------------------------
export interface ProgressError {
  code: ErrorCode
  message: string
}

export interface ProgressEvent {
  run_id: string
  phase: ProgressPhase
  label: string
  pct?: number | null
  detail?: string | null
  counts?: Record<string, number> | null
  error?: ProgressError | null
  ts: string
}

// --- ResearchResult (backend -> results screens) --------------------------
export interface WatchListItem {
  video_id: string
  learning_goal: string
  why: string
  rank: number
}

export interface CommonFeature {
  n: number
  pattern: string
  note: string
  count: number
}

export interface EmotionalTrigger {
  n: number
  trigger: string
  example: string
}

export interface TitleAnalysis {
  common_features: CommonFeature[]
  emotional_triggers: EmotionalTrigger[]
}

export interface DurationStat {
  label: string
  value: string
}

export interface StructurePattern {
  name: string
  note: string
}

export interface HookBreakdown {
  rank: number
  title: string
  hook: string
  video_id: string
}

export interface ScriptAnalysis {
  duration_sweet_spot: DurationStat[]
  structure_patterns: StructurePattern[]
  hook_breakdown: HookBreakdown[]
  what_to_avoid: string[]
}

export interface TitleFormula {
  shape: string
  proof_video_id: string
  tailored: string
}

export interface GamePlanBeat {
  t: string
  beat: string
}

export interface GamePlan {
  outline: GamePlanBeat[]
  title_options: string[]
  thumbnail_concepts: string[]
  do: string
  dont: string
}

export interface ResultMeta {
  window: string
  filter: string
  keywords: string[]
  ranking: string
  counts: Record<string, number>
  /** True only for the bundled example run seeded on first boot — its counts are
   *  representative, not live API readings. Absent on runs made before the flag. */
  is_example?: boolean
}

export interface ResearchResult {
  schema_version: SchemaVersion
  run_id: string
  created_at: string
  request: ResearchRequest
  topic_title: string
  summary: string
  meta: ResultMeta
  top_videos: Video[]
  watch_list: WatchListItem[]
  /** null when analyze_titles was off — the UI hides/disables the tab. */
  title_analysis: TitleAnalysis | null
  /** null when analyze_scripts was off — the UI hides/disables the tab. */
  script_analysis: ScriptAnalysis | null
  title_formulas?: TitleFormula[] | null
  game_plan?: GamePlan | null
}

// --- Config / Adapter / History -------------------------------------------
export interface Config {
  schema_version: SchemaVersion
  adapter: string | null
  model: string | null
  youtube_key_present: boolean
  /** Whether the user's Anthropic API key is stored (direct adapter, Phase 4). */
  anthropic_key_present: boolean
  /** Whether the user's OpenAI API key is stored (OpenAI-compatible adapter). */
  openai_key_present: boolean
  /** Whether the user's OpenRouter API key is stored (one key, many vendors). */
  openrouter_key_present: boolean
  /** Whether a Gemini API key is stored locally. */
  gemini_key_present: boolean
  onboarding_complete: boolean
}

/** Which local secret a POST /api/config/key writes. */
export type KeyProvider = 'youtube' | 'anthropic' | 'openai' | 'openrouter' | 'gemini'

export interface Adapter {
  id: string
  name: string
  installed: boolean
  version: string | null
  models: string[]
}

export interface HistoryItem {
  run_id: string
  topic_title: string
  query: string
  format: Format
  created_at: string
  counts: Record<string, number>
  outperformance: Outperformance
}

// --- AgentResult (CLI -> backend; narrative + video_id refs only) ---------
export interface AgentTopVideoRef {
  video_id: string
  rank: number
}

export interface AgentResult {
  schema_version: SchemaVersion
  topic_title: string
  summary: string
  keywords: string[]
  top_video_ids: AgentTopVideoRef[]
  watch_list: WatchListItem[]
  title_analysis: TitleAnalysis | null
  script_analysis: ScriptAnalysis | null
  title_formulas?: TitleFormula[] | null
  game_plan?: GamePlan | null
}

// --- API envelopes ---------------------------------------------------------
/**
 * What the user should DO about a failed env-check, decided by the adapter.
 * `sign_in` means the tool is installed but unauthenticated — the far more
 * common failure — and `command` is the exact thing that fixes it.
 */
export interface EnvCheckRemedy {
  kind: 'install' | 'sign_in'
  label: string
  /** Server-defined; the remedy endpoint runs this, never client input. */
  command: string | null
  url: string | null
}

export interface EnvCheckResult {
  ok: boolean
  adapter: string
  version: string | null
  message: string
  remedy?: EnvCheckRemedy | null
}

export interface RemedyResult {
  ok: boolean
  message: string
  command: string | null
}

export interface KeyTestResult {
  ok: boolean
  message: string
}

export interface StartRunResponse {
  run_id: string
}
