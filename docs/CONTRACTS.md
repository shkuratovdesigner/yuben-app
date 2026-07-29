# YuBen — Interface Contracts (the linchpin for parallel builds)

These contracts are the frozen boundary between **frontend**, **backend**, and the **agent**. Fix them first; then all three can be built in parallel against fixtures. Version everything (`schema_version`). Breaking changes bump the major version.

Related: [PRD.md](PRD.md) · [BUILD_PLAN.md](BUILD_PLAN.md)

Deliverable shape: `contracts/` package containing JSON Schemas, generated TypeScript types (`zod` or `json-schema-to-typescript`), Pydantic models (backend), and realistic fixtures derived from the repo's existing `data/*.json`.

---

## 1. HTTP + SSE API

Base URL `http://localhost:8000`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness. |
| GET | `/api/config` | Current config (adapter, model, key-present flag — never the key value). |
| PUT | `/api/config` | Save adapter/model/settings. |
| POST | `/api/config/key` | Store a key locally (write-only; returns `{ok}`). Body `{key, provider?}` where `provider ∈ {youtube (default), anthropic}` — the Anthropic key backs the direct API adapter. |
| POST | `/api/config/env-check` | Run the adapter "respond hello" probe → `{ok, adapter, version, message}`. |
| POST | `/api/config/key-test` | One cheap YouTube call → `{ok, message}`. |
| GET | `/api/adapters` | Installed adapters + versions + models. |
| POST | `/api/research` | Start a run → `{run_id}`. Body = **ResearchRequest**. |
| GET | `/api/research/{run_id}/events` | **SSE** stream of **ProgressEvent**. |
| GET | `/api/research/{run_id}` | Final **ResearchResult** (or `{status}` if not done). |
| POST | `/api/research/{run_id}/cancel` | Cancel a running job. |
| GET | `/api/history` | List **HistoryItem**. |
| DELETE | `/api/history/{run_id}` | Delete a saved run. |

Secrets rule: keys are write-only through the API; no endpoint ever returns a key. Nothing sensitive in query strings.

---

## 2. ResearchRequest (composer → backend)

```jsonc
{
  "schema_version": "1.0",
  "query": "autonomous AI agents and orchestration",   // required, non-empty
  "format": "longform",                                  // "longform" | "shorts"
  "upload_date": "all",                                  // all|24h|7d|30d|90d|6m|1y
  "outperformance": "highest",                           // any|2x|5x|10x|highest
  "analyze_titles": true,
  "analyze_scripts": true,
  "model": { "adapter": "claude-code", "model": "default" },
  "max_results": 40
}
```

**Backend mapping (UI → script params):**
- `upload_date` → `days` + `floor` (ISO). `all`→ no floor; `24h`→1; `7d`→7; `30d`→30; `90d`→90; `6m`→183; `1y`→365.
- `outperformance` → VSR/multiplier threshold + sort. `any`→ no floor, sort by views; `2x|5x|10x`→ min VSR (or `--multiplier` when medians on); `highest`→ sort by VSR desc.
- `format` → `longform_research.py` (≥120s) vs `shorts_research.py` (≤65s).
- `analyze_scripts=true` → fetch transcripts (Gen-1 `transcript.py`).
- `analyze_titles` → include Title Analysis section in the agent prompt + result.

---

## 3. ProgressEvent (SSE → loader)

```jsonc
{
  "run_id": "r_2026...",
  "phase": "searching",        // queued|expanding|searching|enriching|scoring|analyzing|verifying|done|error
  "label": "Searching YouTube",
  "pct": 42,                    // 0..100, null if indeterminate
  "detail": "keyword 7 / 20",
  "counts": { "found": 412, "longform": 180, "curated": 0 },
  "ts": "2026-07-11T10:00:07Z"
}
```
Terminal events: `phase:"done"` (result ready at `/api/research/{id}`) or `phase:"error"` with `error:{code,message}` where `code ∈ {quota_exceeded, cli_missing, cli_failed, no_results, invalid_output, cancelled, unknown}`.

---

## 4. Video (unified schema — normalizes Gen-2 shapes)

```jsonc
{
  "video_id": "116cwKs2XQs",
  "title": "The Money-Making Secrets Behind Hotel Design",
  "url": "https://www.youtube.com/watch?v=116cwKs2XQs",
  "watch_url": "https://www.youtube.com/watch?v=116cwKs2XQs",
  "thumbnail_url": "https://i.ytimg.com/vi/116cwKs2XQs/hqdefault.jpg",  // derived
  "channel_id": "UCK7tptUDHh-RYDsdxO1-5QQ",
  "channel_name": "The Wall Street Journal",
  "subscriber_count": 6630000,
  "view_count": 2819786,
  "like_count": 41494,
  "comment_count": 2175,
  "vsr": 0.43,                    // views ÷ subs (primary outlier signal)
  "multiplier": null,            // views ÷ channel_median (when medians on)
  "eng_per_1k": 14.7,            // computed: likes/views*1000
  "engagement_flag": "ok",       // "ok" | "promoted" (<1.5) — promoted rows are
                                 // dropped from the ranking; counts.promoted_excluded
                                 // reports how many
  "channel_country": "US",       // channel's declared ISO 3166-1 alpha-2, or ""
                                 // when unset. Sorts US/EU first (a preference,
                                 // never a filter — the field is optional)
  "published_at": "2025-07-29T14:00:01Z",
  "duration_seconds": 399,
  "duration_label": "6:39",       // derived
  "link_status": "verified"       // verified | embed_disabled | dead
}
```
Rendering rule: `video_id`, `url`, `thumbnail_url`, and all numeric fields are authoritative from the **script JSON + backend derivation** — never from agent free-text. Agent output references videos by `video_id` that must exist in the collected set, or the backend drops the reference.

---

## 5. ResearchResult (backend → results screens)

```jsonc
{
  "schema_version": "1.0",
  "run_id": "r_2026...",
  "created_at": "2026-07-11T10:03:00Z",
  "request": { /* echo of ResearchRequest */ },
  "topic_title": "Autonomous AI Agents, Orchestration & Multi-Agent Systems",
  "summary": "Setup walkthroughs and 'every concept explained' formats dominate.",
  "meta": {
    "window": "All time", "filter": "long-form ≥120s",
    "keywords": ["ai agents", "agent orchestration", "..."],
    "ranking": "by views; VSR shown — US/Europe channels first, promoted excluded",
    "counts": { "unique": 412, "longform": 180, "curated": 40,
                "promoted_excluded": 7, "off_region": 3, "country_undeclared": 11 }
  },

  "top_videos": [ /* Video[], ranked — Section A (grid/list) */ ],

  "watch_list": [                                   // Section B
    { "video_id": "…", "learning_goal": "Build your first multi-agent team",
      "why": "Shows an actual multi-agent setup with real terminal output.",
      "rank": 1 }
  ],

  "title_analysis": {                               // Section C, tab 1 (if requested)
    "common_features": [
      { "n": 1, "pattern": "How-to / explainer", "note": "Clear payoff in the title", "count": 27 }
    ],
    "emotional_triggers": [
      { "n": 1, "trigger": "Fear of missing out (FOMO)", "example": "\"…before it's too late\"" }
    ]
  },

  "script_analysis": {                              // Section C, tab 2 (if requested)
    "duration_sweet_spot": [
      { "label": "Median duration of qualifying videos", "value": "18.5 minutes" }
    ],
    "structure_patterns": [
      { "name": "\"Show My Setup\" (highest engagement)", "note": "Screen recordings of real workflows." }
    ],
    "hook_breakdown": [
      { "rank": 1, "title": "Claude COWORK Clearly Explained (466×)",
        "hook": "Opens by acknowledging the confusion and promising to make it simple",
        "video_id": "…" }
    ],
    "what_to_avoid": [ "Generic 'what are AI agents' explainers — the market is saturated." ]
  },

  "title_formulas": [                               // optional (game-plan input)
    { "shape": "[Tool] Clearly Explained", "proof_video_id": "…", "tailored": "Claude Agents Clearly Explained" }
  ],
  "game_plan": {                                    // optional
    "outline": [ { "t": "0:00", "beat": "Hook: acknowledge the confusion" } ],
    "title_options": ["…"],
    "thumbnail_concepts": ["…"],
    "do": "Show a real terminal setup.", "dont": "Ship another generic explainer."
  }
}
```

Sections `title_analysis` / `script_analysis` are `null` when the matching toggle was off — the UI hides/disables that tab.

---

## 6. Config, Adapter, History

```jsonc
// GET /api/config  (key values are NEVER returned — only presence flags)
{ "schema_version":"1.0", "adapter":"claude-code", "model":"default",
  "youtube_key_present": true, "anthropic_key_present": false, "onboarding_complete": true }

// GET /api/adapters  (anthropic-api = the terminal-free direct Messages path;
//   `installed` there means the `anthropic` SDK is importable, `version` is its SDK version)
[ { "id":"anthropic-api", "name":"Anthropic API", "installed":true, "version":"0.x.y",
    "models":["default","claude-opus-5","..."] },
  { "id":"claude-code", "name":"Claude Code", "installed":true, "version":"x.y.z",
    "models":["default","claude-opus-5","..."] },
  { "id":"gemini-cli", "name":"Gemini CLI", "installed":false, "version":null, "models":[] } ]

// HistoryItem (GET /api/history)
{ "run_id":"r_…", "topic_title":"…", "query":"…", "format":"longform",
  "created_at":"…", "counts":{"curated":40}, "outperformance":"highest" }
```

---

## 7. Agent output contract (model → backend)

The orchestrator drives **two LLM calls with the deterministic pipeline in between**, identically for every adapter: (1) a keyword-expansion call whose JSON array feeds `run_pipeline(keywords=…)`, then (2) a narrative call given the videos `run_pipeline` collected, which must **emit a single JSON object** matching a strict "AgentResult" schema — a subset of ResearchResult carrying **narrative + video_id references only** (no numbers it invented, no fabricated IDs). The backend then:
1. Validates against the AgentResult schema (retry/repair prompt on failure).
2. Joins every referenced `video_id` to the collected pipeline videos; drops unknown IDs.
3. Attaches authoritative numbers, derives thumbnails/labels, computes Eng/1k, verifies links.
4. Produces the final validated `ResearchResult`.

This is the concrete mechanism of the §8 trust split in the PRD: **narrative from the LLM, facts from the pipeline, verification by the backend.**

**No adapter does its own research** — not even a CLI that could. Agentic CLIs were once prompted to run the research scripts themselves while `run_pipeline` searched in parallel, and step 2 above then joined two independent searches: the intersection was frequently empty, so a run that had really collected videos rendered a result page with none. The pipeline is the single source of ids for every adapter, and the narrative prompt tells the model not to research. `AgentAdapter.agentic` still records whether an adapter *has* a tool loop, but it no longer changes the run flow.

---

## 8. Fixtures (build against these before the backend is live)

Built from real, link-verified videos so screens look real on day one:
- `fixtures/research-result.longform.json` — generated from `contracts/mock_videos/` (real titles, channels and video ids; representative counts).
- `fixtures/research-result.shorts.json` — same source, Shorts set.
- `fixtures/history.json` — generated alongside the two above.
- `fixtures/progress-events.jsonl` — a realistic phase timeline for the loader; hand-maintained.
- `fixtures/adapters.json`, `fixtures/config.json` — hand-maintained.

`contracts/build_mock_fixtures.py` builds the generated ones; `contracts/validate_fixtures.py` contract-checks all of them, generated or hand-edited. `make fixtures` runs the pair.

Separately, `contracts/normalize_reference.py` holds a second, independent implementation of raw-row → Video normalization that the backend's normalizer is diffed against in tests. It writes no fixtures.
