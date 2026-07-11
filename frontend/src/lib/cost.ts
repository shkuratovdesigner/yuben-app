/**
 * YouTube Data API cost model (H2 cost meter, PRD §7 hardening).
 *
 * The pipeline's cost is dominated by `search.list` — 100 units per search term
 * — and the agent expands one topic into several terms. `videos.list` (details)
 * and `channels.list` (subscriber counts) are 1 unit per batch of 50. The free
 * daily quota is 10,000 units, so a typical run is a meaningful slice of it and
 * worth surfacing before/after a run.
 *
 * NOTE: the YouTube Data API exposes no "quota used so far today" endpoint, so a
 * true live meter isn't possible. Pre-run figures are ESTIMATES (keywords are
 * agent-expanded, unknown until the run); the per-run figure on the results
 * screen is EXACT — derived from the run's real keyword + unique-video counts.
 */

/** Free daily quota for a default YouTube Data API v3 project. */
export const YT_DAILY_QUOTA = 10_000

const SEARCH_COST = 100 // search.list, per keyword (one page of ≤50)
const LIST_COST = 1 // videos.list / channels.list, per batch of ≤50 ids
const BATCH_SIZE = 50

/**
 * Exact units a run consumed: one search per keyword, plus a details pass and a
 * channels pass over the unique videos (two ≤50-id batched list calls).
 */
export function computeUnits(keywordCount: number, uniqueVideos: number): number {
  const searches = Math.max(keywordCount, 0) * SEARCH_COST
  const batches = Math.ceil(Math.max(uniqueVideos, 0) / BATCH_SIZE)
  return searches + batches * LIST_COST * 2
}

// Pre-run: the agent decides how many terms to expand a topic into, so estimate
// a typical spread (units are search-dominated, so keyword count is the driver).
const LOW_KEYWORDS = 6
const TYPICAL_KEYWORDS = 14
const HIGH_KEYWORDS = 22
const UNIQUES_PER_KEYWORD = 45 // ~ deduped videos each term contributes

export interface RunEstimate {
  low: number
  typical: number
  high: number
}

/** Estimated units for a single run (keyword count unknown until it runs). */
export function estimateRun(): RunEstimate {
  return {
    low: computeUnits(LOW_KEYWORDS, LOW_KEYWORDS * UNIQUES_PER_KEYWORD),
    typical: computeUnits(TYPICAL_KEYWORDS, TYPICAL_KEYWORDS * UNIQUES_PER_KEYWORD),
    high: computeUnits(HIGH_KEYWORDS, HIGH_KEYWORDS * UNIQUES_PER_KEYWORD),
  }
}

/** Roughly how many typical runs fit in the daily free quota. */
export function runsPerDay(): number {
  return Math.max(1, Math.floor(YT_DAILY_QUOTA / estimateRun().typical))
}

/** Compact unit label: 1426 → "1.4k", 610 → "610", 10000 → "10k". */
export function formatUnits(n: number): string {
  if (n < 1000) return String(Math.round(n))
  const k = n / 1000
  return `${k >= 10 ? Math.round(k) : k.toFixed(1)}k`
}
