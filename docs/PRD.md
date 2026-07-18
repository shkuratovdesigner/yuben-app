# YuBen — Product Requirements Document

**Product:** YuBen — a local-first desktop-style web app that turns a topic into a proven YouTube video plan by finding outlier videos and explaining why they win.
**Status:** Draft v1 (for build)
**Owner:** shkuratovdesigner
**Last updated:** 2026-07-11

Related docs: [CONTRACTS.md](CONTRACTS.md) (the shared API/JSON interface) · [BUILD_PLAN.md](BUILD_PLAN.md) (subagent execution plan)

---

## 1. Overview

YuBen wraps an existing Python YouTube-research pipeline in a friendly interface. A user connects their own local AI agent CLI (Claude Code or Gemini CLI) as the "brain," pastes a private YouTube Data API key, then types a topic and gets back a ranked list of **outlier videos** (videos that vastly outperform their channel's size) plus a breakdown of the title/hook/length patterns that make them work — ending in a ready-to-use plan for their own video.

The engine already exists as Python scripts (`longform_research.py`, `shorts_research.py`, etc.) that search YouTube, compute **VSR** (views ÷ subscribers), and rank outliers. This project adds: (1) an onboarding flow, (2) a chat-style composer with filters, (3) a live progress loader, (4) rich results screens, and (5) research history — all running locally.

### Architecture at a glance (decided)

- **Runtime:** Local web app. A **FastAPI** backend serves a **React** frontend on `localhost` and shells out to the user's installed agent CLI. All keys stay on the machine.
- **Brain:** The selected local CLI (**Claude Code** or **Gemini CLI**) **orchestrates everything** — it runs the existing research scripts as tools, then writes the title/script analysis and video plan.
- **Frontend:** Vite + React + TypeScript + Tailwind + shadcn/ui.

```
Browser (React SPA, localhost:5173)
   │  HTTP + SSE
FastAPI backend (localhost:8000)
   │  • config / secrets / env-checks
   │  • adapter layer (ClaudeCode | Gemini)
   │  • orchestrator: prompt → CLI → progress events → validated result
   │  • deterministic pipeline wrapper (existing scripts) + link verification
   │  subprocess (headless)
Local agent CLI  →  runs YuBen scripts (YouTube Data API) → emits ResearchResult JSON
```

**Trust split (non-negotiable):** all *numbers and video IDs/links* come from the deterministic scripts and are re-verified by the backend; the CLI supplies *narrative* (keyword expansion, title/script analysis, game plan). The backend never renders a video ID the agent typed — it re-derives every ID from the saved script JSON and re-verifies links (oEmbed + existence check). See §8.

---

## 2. Goals & non-goals

### Goals
1. Take a non-technical user from install → first research report in under ~3 minutes.
2. Faithfully reproduce today's report quality (outlier tables, title formulas, game plan) in an interactive UI.
3. Keep the user's keys and CLI auth fully local; zero server dependency.
4. Make the six designed screens real, pixel-close to Figma, and responsive.
5. Support both **long-form** and **Shorts** research and the designed filters (upload date, outperformance, title analysis, script analysis).

### Non-goals (v1)
- Multi-user accounts, cloud sync, or hosting.
- Editing/publishing to YouTube.
- Replacing the Python pipeline with a rewrite (we wrap it).
- Billing/quotas beyond surfacing YouTube API cost warnings.
- Mobile-native apps (responsive web only; primary target is desktop).

---

## 3. Users & primary use case

**Primary user:** a solo YouTube creator / content strategist (the repo owner's persona) planning their next video. Technical enough to install a CLI and get a YouTube API key, but wants the research automated and visual.

**Primary job-to-be-done:** *"Before I script a video on topic X, show me which videos already crushed it relative to their channel size, tell me exactly what made them win, and hand me a title + hook + outline I can use."*

---

## 4. Screen requirements

Six screens (five in Figma + one loader we design). Node IDs reference the Figma file `OG4eN9FgW3gnu88CRQRMGt`.

### Global chrome (all screens)
- Top-left: YuBen play-mark logo + wordmark.
- Top-right: "built by shkuratovdesigner" + GitHub / YouTube / LinkedIn icons.
- Neutral off-white canvas; generous whitespace; centered content column (~664px for onboarding/composer).

### 4.1 Onboarding — Step 1: "Choose the model" (`1:12`)
**Purpose:** connect the local agent CLI that will act as the brain.
- **H1 (serif):** "Choose the model" · sub: "This will be an engine and brain behind the agent."
- **Adapter cards** (selectable, teal border when active): **Anthropic API** ("paste a key, no terminal" — the direct Messages path, Phase 4), **Claude Code** ("Local Claude agent"), **Gemini CLI** ("Local Gemini agent"). Expandable link: **"More agent adapter types ▾"** (future adapters).
- **Model** select → "Default" (options depend on chosen adapter).
- **Connect step (adapter-dependent):**
  - *Anthropic API (key):* a masked **Anthropic API key** field + **[Test now]** that stores the key write-only and runs a cheap **real Messages ping** ("reply hello") — turns green on success, no terminal.
  - *Local CLI:* **Adapter environment check** row: "Runs a live probe that asks the adapter CLI to respond with hello" + **[Test now]**. Shows pass/fail (CLI found + responded, version detected) or an install hint if missing.
- **[Continue]** primary pill (disabled until an adapter is selected; ideally until env-check passes).

### 4.2 Onboarding — Step 2: "How it works" + key (`16:912`)
**Purpose:** explain the flow in 4 steps and capture the YouTube key.
- **H1 + sub** (see copy in §6).
- **4 numbered step rows** (see copy in §6).
- **"Detailed guide ↗"** link (opens a longer guide — external or in-app; v1 can link to README).
- **Private YouTube Key** field (masked, monospace; helper text; local-only).
- **Key test row:** "Test your key" + **[Test now]** — runs one cheap API call and shows accept/reject.
- **[Finish Setup]** primary pill (enabled once a valid-format key is entered; ideally after a passing test).

### 4.3 Main composer — "What content are you searching for?" (`27:529` / `29:135`)
**Purpose:** compose a research request. This is the home screen.
- **H1 (serif):** "What content are you searching for?" + sub.
- **Composer panel** (chat-style card): multiline input with placeholder.
- **Inline control bar** (inside the panel, bottom):
  - **Upload date** dropdown — default "All time" (options in §6).
  - **Outperformance** dropdown — default "Highest Outperformance" (options in §6).
  - **☐ Titles Analytic** checkbox.
  - **☐ Script analytics** checkbox.
  - **Send** button (arrow-up) — disabled until the input is non-empty (`29:135` shows the enabled/teal state).
- **Footer:** model switcher **"Claude Opus 4.6 ▾"** (reflects/changes the active model). After the first run, the footer also shows **Research history [n]** (see 4.6).

### 4.4 Loader — research in progress (design new)
**Purpose:** show live scraping + analysis progress so a multi-minute run feels alive.
- Centered progress card driven by the SSE **ProgressEvent** stream (see [CONTRACTS.md](CONTRACTS.md)).
- **Phase checklist** with a moving indeterminate/percentage bar. Phases + copy in §6: expanding keywords → searching YouTube → enriching (subs, stats) → scoring outliers (VSR) → analyzing titles/scripts → verifying links → done.
- Live counters (e.g., "412 videos found · 180 long-form · verifying 15 links").
- Secondary text reassures it may take a couple of minutes; **[Cancel]** ends the run.
- Graceful **error** state (quota exceeded, CLI failed, no results) with a retry and a plain-language reason.

### 4.5 Results (`31:184` grid · `31:843` list · `35:2181` script tab)
**Purpose:** render the finished research. One route, several sections.
- **Header:** topic title (e.g., "Autonomous AI Agents, Orchestration & Multi-Agent Systems") + one-line thesis + a **grid/list toggle**.
- **Section A — Top 15 Highest-Performed Videos:**
  - **Grid view** (`31:184`): video cards (thumbnail, title, channel, views, outperformance badge, duration, Watch link).
  - **List view** (`31:843`): table — `№ · Title & thumbnail · Channel · Views · Mult (outperformance) · Eng/1k · Duration · Link → Watch`. Color-code the outperformance cell by tier (hot / warm / cool).
- **Section B — Recommended Watch List by Learning Goal:** table — `№ · Title · Why to watch · Mult · Duration · Link`.
- **Section C — Analysis tabs:** **Title Analysis** / **Script Analysis**.
  - *Title Analysis:* "Common Features" table (pattern → note → # videos) + "Emotional Triggers Used in the Titles" table (trigger → example).
  - *Script Analysis* (`35:2181`): Duration Sweet Spot (stat list), Content Structure Patterns, Hook Breakdown (First 30 Seconds) with per-item Video links, What to Avoid.
- **Empty/partial states:** if a toggle was off (e.g., Script analytics unchecked), hide/disable that tab with an inline hint.
- **Actions (v1+):** export report (reuse existing `.md`/`.html` builders), re-run, save.

### 4.6 Home with history (`36:2939`)
Same composer as 4.3, but the footer now exposes:
- **Research history [n]** — opens a list of past runs (topic, date, format, result counts); clicking reopens the saved result (no re-run).

---

## 5. Functional requirements

**FR-1 Onboarding & config.** Detect installed adapters; select adapter + model; run env-check probe; store YouTube key locally (OS keychain preferred, `.env` fallback); test key; persist config; gate the app until setup is complete.

**FR-2 Compose a run.** Capture query + format (long/short) + upload-date + outperformance + title/script toggles + model. Validate non-empty query. Show an estimated YouTube API cost/keyword warning before running.

**FR-3 Execute a run.** Backend maps UI filters → script parameters, builds the agent prompt, spawns the chosen CLI headless, streams progress as SSE ProgressEvents, collects the CLI's ResearchResult, **re-derives and re-verifies all video IDs/links from the deterministic script JSON**, schema-validates, persists, and returns the result.

**FR-4 Render results.** Grid/list toggle, outperformance color tiers, Title/Script analysis tabs, watch links that open YouTube. Respect which analyses were requested.

**FR-5 History.** List, open (from cache), and delete past runs. Never silently re-run.

**FR-7 Resilience.** Handle: CLI not installed, CLI/auth failure, YouTube 403 quota, zero results, malformed agent output (repair/fallback), and run cancellation — each with a clear message.

---

## 6. Content & microcopy

### Onboarding Step 2 — "How it works" (short & plain — generated per request)
**H1:** "How YuBen finds your next video"
**Sub:** "Paste your YouTube key below. Here's what happens each time you research a topic."

1. **Tell it a topic** — Type what to research and set your filters: date range, how hard a video must beat its channel, and whether to analyze titles and scripts.
2. **It scans YouTube** — YuBen pulls the top-viewed videos and measures each one against its channel size to surface true outliers.
3. **It finds the pattern** — The agent breaks down *why* the winners work: title formulas, hooks, ideal length, and what to avoid.
4. **You get a plan** — A ranked outlier list plus a ready-to-use title, hook, and structure for your own video.

- **Key field label:** "Private YouTube Key" · helper: "Stored only on your machine and used to fetch video data. Get one free in Google Cloud Console."
- **Key test row:** title "Test your key" · sub "Runs one quick call to confirm YouTube accepts it." · button "Test now."
- **CTA:** "Finish Setup."

### Composer dropdowns
- **Upload date** (default "All time"): All time · Last 24 hours · Last 7 days · Last 30 days · Last 90 days · Last 6 months · Last year. → backend maps to `days` + `floor`.
- **Outperformance** (default "Highest Outperformance"): Any · 2× and up · 5× and up · 10× and up · Highest first. → backend maps to VSR/multiplier threshold + sort.
- **Checkboxes:** "Titles Analytic" · "Script analytics."
- **Send** tooltip when disabled: "Type a topic to start."

### Loader phase labels
Queued → "Expanding your topic into search terms" → "Searching YouTube" → "Pulling channel sizes & stats" → "Scoring outliers (views vs. channel size)" → "Analyzing titles & scripts" → "Verifying every link" → "Done."

### Empty / error states
- No results: "No standout videos matched those filters. Try a broader date range or lower the outperformance bar."
- Quota: "YouTube's daily quota is used up. Try again after it resets, or use a different key."
- CLI missing: "We couldn't find the {Claude Code|Gemini} CLI. Install it, then run the environment check again." + install link.

---

## 7. Design system (from Figma tokens + observed styles)

- **Colors:** Brand/Primary (text) `#2B2D33`; secondary grey `#777274`; borders `#D5D5D6`; white `#FFFFFF`; **teal accent** (buttons/send/links/selected border) ≈ `#0E6E7E` (extract exact per-component via `get_design_context`). Link blue-teal slightly brighter.
- **Outperformance tiers (results):** hot (≥5×) warm-amber · warm (2–5×) green · cool (<1×) grey — mirror `build_html_report.py`.
- **Type:** serif display for H1s (e.g., a transitional serif — Newsreader/Tiempos feel); neutral sans for UI/body (Inter/system). Label Large = 14 / line-height 20 / tracking 0.1.
- **Components (shadcn/ui mapped):** pill Button (primary teal / secondary grey), Card (adapter card, composer panel, result cards), Select/Dropdown, Checkbox, Tabs, Table (sticky header, scrollable), Badge (outperformance, history count), masked KeyInput, Progress, Toggle (grid/list).
- **Layout:** centered ~664px column for onboarding/composer; wide scrollable container for results tables (must `overflow-x: auto`, never break page layout).

Exact spacing, fonts, and hex values are pulled per-screen by each build agent via `get_design_context` (see [BUILD_PLAN.md](BUILD_PLAN.md)).

---

## 8. Data & trust requirements

- **Outlier metric:** primary signal is **VSR = view_count ÷ subscriber_count** (Gen-2 scripts). Optional channel-median **multiplier = views ÷ channel_median** when enabled. The UI's "outperformance"/"Mult" column shows the chosen signal.
- **Engagement guard:** compute **Eng/1k = likes ÷ views × 1000**; flag `< 1.5` as possible promoted/dead engagement (mirrors `build_property_report.py`).
- **Link integrity (critical):** the agent is known to fabricate 11-char video IDs. The backend MUST (a) take IDs only from the deterministic script JSON, (b) join agent narrative to real videos by a stable key (exact view_count / title substring), (c) oEmbed-verify + existence-check every link, marking `embed_disabled` (public but not embeddable) vs `dead`. No hand-typed IDs are ever rendered.
- **Derived fields:** thumbnails from `https://i.ytimg.com/vi/<id>/hqdefault.jpg`; `duration_label` from `duration_seconds`.
- **Transcripts:** only fetched when **Script analytics** is on (Gen-1 `transcript.py`, no API quota).
- **Secrets:** YouTube key stored locally only; never sent to any external server, never placed in URLs/query strings; masked in UI. CLI adapters use the user's own local auth.
- **Path hygiene:** the existing scripts hardcode a sibling "Business Automation" path and rely on a `youtube_research → YuBen` symlink; the backend wrapper must make these repo-relative / set `PYTHONPATH` so runs work from this repo.

---

## 9. Non-functional requirements

- **Local-only & private:** no outbound calls except YouTube APIs and the user's own CLI/LLM.
- **Performance:** first paint < 1s; UI stays responsive during multi-minute runs (all heavy work backgrounded; progress via SSE).
- **Resilience:** SSE reconnection; run survivable across a page refresh (poll `/{id}`); validate + repair agent output.
- **Accessibility:** keyboard-navigable, labeled inputs, sufficient contrast, focus states.
- **Cross-platform:** macOS first (dev target), Windows-friendly paths.
- **Observability:** per-run logs retained locally for debugging.

---

## 10. Assumptions & open questions

**Assumptions (proceeding unless told otherwise):**
- Headless invocation is available for both CLIs (Claude Code print/stream mode; Gemini CLI non-interactive). If Gemini lacks a needed mode, ship Claude Code first, stub Gemini.
- We standardize on the **Gen-2** scripts and *add* the missing knobs (VSR threshold, title/script toggles) in the orchestrator/agent rather than rewriting scripts.
- YouTube Data API key (as designed) is the data source; Apify/WebSearch is a later fallback for quota exhaustion.

**Open questions:**
1. Should "Detailed guide" be an in-app page or an external link for v1? (Assumed: link to README.)
2. Export formats for results in v1 — reuse `.md` + `.html` builders, or skip to v1.1? (Assumed: v1.1.)
3. Dark mode — in scope for v1? (Assumed: light-first, dark is nice-to-have.)
4. Persist raw run JSON in `data/` (reuse existing convention) or a new app DB? (Assumed: app SQLite for history + keep raw JSON artifacts.)

---

## 11. Out of scope (v1)
Accounts/auth, cloud hosting, collaboration, scheduled/recurring research, YouTube publishing, payment, native mobile apps.
