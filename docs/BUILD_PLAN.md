# YuBen — Subagent Build Plan

How we build the app efficiently with parallel subagents. The strategy is **contract-first**: freeze the interface ([CONTRACTS.md](CONTRACTS.md)) + design tokens first, then fan out ~13 build agents that never block each other because each builds against fixtures, not against another agent's half-finished code.

Related: [PRD.md](PRD.md) · [CONTRACTS.md](CONTRACTS.md)

---

## 1. Strategy

1. **Freeze contracts + fixtures + design system (Phase 0).** Small, fast, sequential-ish. Everything downstream depends on it.
2. **Fan out (Phase 1).** Every screen is one frontend agent (builds against fixtures). Every backend capability is one agent (builds against the same contracts). Two tracks, fully parallel.
3. **Integrate (Phase 2).** Swap fixtures for the live API; run one real end-to-end research with a real key + CLI; fix contract drift.
4. **Harden (Phase 3).** Error/empty states, cost meter, export, a11y, dark mode.

**Why this parallelizes cleanly:** the only shared surface is `contracts/`. Frontend agents import generated TS types + JSON fixtures; backend agents implement the same schemas in Pydantic. Neither waits on the other. Integration is mostly deleting the mock layer.

**Isolation:** Phase-1 agents edit disjoint directories, so they can run concurrently in the same tree. If any two must touch a shared file (e.g., the router or Tailwind config), give those agents **git worktrees** (`isolation: "worktree"`) or serialize just those two. Prefer disjoint files by design (see repo layout).

---

## 2. Architecture & repo layout

Monorepo, three top-level packages + the existing Python pipeline reused as a library.

```
YuBen/
├── frontend/                 # Vite + React + TS + Tailwind + shadcn/ui
│   ├── src/
│   │   ├── screens/          # one folder per screen (disjoint → parallel agents)
│   │   │   ├── OnboardingModel/
│   │   │   ├── OnboardingSetup/
│   │   │   ├── Composer/
│   │   │   ├── Loader/
│   │   │   ├── Results/
│   │   │   └── History/
│   │   ├── components/ui/     # shared design-system primitives (Phase 0)
│   │   ├── lib/api.ts         # typed API client (+ mock switch)
│   │   ├── lib/types.ts       # generated from contracts
│   │   ├── app/               # shell, router, providers (App shell agent)
│   │   └── styles/            # tailwind theme, fonts
│   └── fixtures/ -> ../contracts/fixtures
├── backend/                  # FastAPI
│   ├── app/
│   │   ├── api/               # routers: config, research, history
│   │   ├── adapters/          # AgentAdapter, ClaudeCodeAdapter, GeminiCliAdapter
│   │   ├── orchestrator/      # prompt build, run loop, SSE, validation/repair
│   │   ├── pipeline/          # wrapper over existing scripts → unified Video
│   │   ├── verify/            # oEmbed + id-existence link verification
│   │   ├── store/             # SQLite config + history; secret storage
│   │   └── models/            # Pydantic (mirror contracts)
│   └── tests/
├── contracts/                # JSON Schemas, TS types, Pydantic, fixtures, build_mock_fixtures.py
├── docs/                     # this PRD/CONTRACTS/BUILD_PLAN
├── longform_research.py …    # EXISTING scripts — reused as-is (wrapped, not rewritten)
└── data/                     # existing raw JSON (source for fixtures)
```

Dev ergonomics (Phase 0): `make dev` runs frontend (5173) + backend (8000); `VITE_USE_MOCKS=1` serves fixtures without a backend.

---

## 3. The subagent DAG

```
                 ┌─────────────────────── PHASE 0 (foundations) ───────────────────────┐
                 │  W0.1 Scaffold ──▶ W0.2 Contracts+Fixtures ──▶ W0.3 Design System   │
                 └───────┬───────────────────┬────────────────────────┬────────────────┘
                         │                    │                        │
        ┌────────────────┘        ┌───────────┴───────────┐            └────────────┐
        ▼  (contracts)            ▼   FRONTEND (fixtures)  ▼                         ▼  BACKEND (contracts)
   ┌──────────────┐   F1 Onboarding-Model     F5 Results-Top       ┌───────────────────────────────────┐
   │ App shell F8 │   F2 Onboarding-Setup     F6 Results-Analysis  │ B1 API skeleton + config store     │
   │ (router/     │   F3 Composer             F7 History           │ B2 Adapter layer (env-check)       │
   │  layout)     │   F4 Loader                                    │ B3 Pipeline wrapper + normalizer   │
   └──────┬───────┘                                                │ B4 Orchestrator + prompt + SSE     │
          │                                                        │ B5 Research API + history + verify │
          │                                                        └──────────────────┬────────────────┘
          └───────────────────────────┬───────────────────────────────────────────────┘
                                       ▼
                          ┌──────────── PHASE 2 (integration) ────────────┐
                          │  I1 Wire FE→API+SSE   I2 Real E2E run/fixes    │
                          └───────────────────────┬───────────────────────┘
                                                   ▼
                          ┌──────────── PHASE 3 (harden) ─────────────────┐
                          │  H1 Errors/empty  H2 Cost meter  H3 Export     │
                          │  H4 a11y/dark                                  │
                          └───────────────────────────────────────────────┘
```

**Concurrency:** Phase 0 = 1 agent at a time (fast). Phase 1 = up to ~13 agents at once (7 frontend incl. shell + 5 backend + review). Phase 2 = 1–2 agents. Phase 3 = 5 parallel.

---

## 4. Phase 0 — Foundations (do first, roughly sequential)

| ID | Agent scope | Deliverable | Depends | Verify |
|---|---|---|---|---|
| **W0.1** | **Scaffold** monorepo: Vite+React+TS+Tailwind+shadcn init, FastAPI skeleton, `contracts/` package, lint/format/test tooling, `make dev`, mock switch. | Repo builds; empty app renders; backend `/api/health` 200. | — | `npm run build`, `pytest -q`, both dev servers boot. |
| **W0.2** | **Contracts & fixtures** (linchpin): JSON Schemas + generated TS types + Pydantic models for every object in CONTRACTS.md; `build_fixtures.py` normalizes `data/*.json` → `research-result.*.json`; progress/adapters/history/config fixtures. *(Since superseded: fixtures are now built by `build_mock_fixtures.py` from `contracts/mock_videos/`, and `build_fixtures.py` was stripped to its normalizer and renamed `normalize_reference.py`.)* | `contracts/` complete; fixtures validate against schemas. | W0.1 | Schema-validate fixtures in CI; TS types compile; Pydantic loads fixtures. |
| **W0.3** | **Design system**: Tailwind theme (tokens from Figma: `#2B2D33`, `#777274`, `#D5D5D6`, teal accent, serif+sans fonts, Label-Large scale), shadcn base, shared primitives (Button pill, Card, Select, Checkbox, Tabs, Table, Badge, KeyInput, Progress, Toggle). Pull exact values via `get_design_context` on `1:12`. | `components/ui/*` + Storybook/preview page. | W0.1 | Visual preview page matches Figma primitives; tokens applied. |

---

## 5. Phase 1 — Parallel build

### Frontend track (each = one agent, builds against `contracts/fixtures`)

| ID | Screen / scope | Figma | Key components | Depends |
|---|---|---|---|---|
| **F8** | **App shell**: router (`/onboarding/*`, `/`, `/run/:id`, `/history`), top-bar chrome (logo + attribution + socials), global config/run store, onboarding gating, mock/live API client. | all | Layout, Router, Providers | W0.1–3 |
| **F1** | **Onboarding — Choose the model**: adapter cards (selectable), model select, env-check row + Test now, Continue. | `1:12` | Card, Select, Button | W0.2–3 |
| **F2** | **Onboarding — Setup**: 4 key-acquisition step rows (copy from PRD §6), Private YouTube Key field, key-test row, Finish Setup. | `16:912` | Steps, KeyInput, Button | W0.2–3 |
| **F3** | **Composer**: prompt panel, Upload-date + Outperformance dropdowns, Titles/Script checkboxes, send button (disabled/enabled states), model footer. | `27:529`,`29:135` | Textarea, Select, Checkbox, Button | W0.2–3 |
| **F4** | **Loader**: phase checklist + progress bar + live counters + cancel + error state; consumes `progress-events` fixture. | new | Progress, list | W0.2–3 |
| **F5** | **Results — Top videos**: header + grid/list toggle; grid cards; list table with VSR color tiers, Eng/1k, Watch links. | `31:184`,`31:843` | Toggle, Card, Table, Badge | W0.2–3 |
| **F6** | **Results — Watch list + Analysis tabs**: Recommended Watch List table; Title/Script analysis tabs (features, triggers, duration sweet spot, hooks, what-to-avoid). | `31:843`,`35:2181` | Tabs, Table | W0.2–3 |
| **F7** | **History**: history list (topic/date/counts), open-from-cache, delete. | `36:2939` | List, Badge, Dialog | W0.2–3 |

> F5+F6 both live under `screens/Results/` — split by distinct files (TopVideos vs AnalysisTabs) so the two agents don't collide; the Results container is owned by F5, imports F6's tab block.

### Backend track (each = one agent, implements `contracts/`)

| ID | Scope | Deliverable | Depends |
|---|---|---|---|
| **B1** | **API skeleton + config store**: FastAPI app, CORS, routers stubbed, SQLite store, local secret storage (keychain/`.env`), `/api/config*`, `/api/health`. | Config CRUD + key storage works. | W0.1–2 |
| **B2** | **Adapter layer**: `AgentAdapter` iface; `ClaudeCodeAdapter` (headless `claude -p --output-format stream-json`) + `GeminiCliAdapter`; detect install/version; `check_env()` "respond hello"; `/api/adapters`, `/api/config/env-check`. | Env-check returns real pass/fail. | W0.1–2 |
| **B3** | **Pipeline wrapper + normalizer**: import/shell existing `longform_research.py`/`shorts_research.py`; fix path/symlink quirk; map filters→params; normalize Gen-2 output → unified **Video**; compute Eng/1k, thumbnail, duration_label, VSR tiers; optional transcripts. | `run_pipeline(request) → Video[]` + meta. | W0.2 |
| **B4** | **Orchestrator + prompt + SSE**: build agent prompt from ResearchRequest; spawn adapter; translate CLI stream → ProgressEvents; collect AgentResult; schema-validate + repair. | `/api/research` starts; `/events` streams. | B1,B2,B3 |
| **B5** | **Research API + history + link verify**: assemble final ResearchResult (join agent refs → script videos, **drop fabricated IDs**, oEmbed + existence verify); persist; `/api/research/{id}`, `/cancel`, `/api/history*`. | End-to-end result JSON validates. | B4 |

**Review gate:** after Phase 1, one `code-reviewer` agent per track checks against PRD/CONTRACTS before integration.

---

## 6. Phase 2 — Integration

| ID | Scope | Depends |
|---|---|---|
| **I1** | Flip `VITE_USE_MOCKS=0`; wire the typed API client + SSE to real endpoints; loading/error wiring; keep a mock fallback flag. | All Phase 1 |
| **I2** | Real end-to-end run with a real `YOUTUBE_API_KEY` + installed Claude Code CLI; reconcile any contract drift; **verify numbers and every link resolve** (apply the fabrication guard); confirm loader phases match real timing. | I1 |

Verification here is behavioral, not just tests: drive onboarding → compose → run → results in the browser preview, watch the SSE loader advance, open a Watch link, confirm the ID exists in the run's JSON.

---

## 7. Phase 3 — Hardening (parallel)

| ID | Scope |
|---|---|
| **H1** | Error/empty/partial states everywhere (quota, CLI-missing, no-results, malformed output, cancel). |
| **H2** | Cost meter: estimate YouTube API units from keyword count; warn before run; surface quota use. |
| **H3** | Export results (reuse `build_html_report.py` / `promote_report_to_html.py`, add `.md`). |
| **H4** | Accessibility pass + responsive + optional dark mode (VSR tiers already themed). |

---

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| **Agent fabricates video IDs/links** (documented). | Backend never renders agent IDs; re-derive from script JSON, join by view_count/title, oEmbed + existence verify (B5). Facts from scripts, narrative from LLM. |
| **CLI headless mode differs / Gemini gaps.** | Adapter abstraction (B2); ship Claude Code first, stub Gemini behind the same interface; feature-detect. |
| **YouTube quota (403).** | Surface cost pre-run (H2); graceful quota error; later fallback to WebSearch/Apify enrichment. |
| **Hardcoded "Business Automation" paths + symlink import.** | B3 makes paths repo-relative / sets `PYTHONPATH`; no dependency on the sibling repo. |
| **Two pipeline generations diverge (Gen-1 agent vs Gen-2 reports).** | Standardize on Gen-2 scripts; add missing knobs (VSR threshold, title/script toggles) in orchestrator/agent, not by rewriting scripts. |
| **Long multi-minute runs feel broken.** | SSE progress (B4/F4); run survives refresh via `/{id}` polling; cancel supported. |
| **Parallel agents editing shared files (router, tailwind config).** | Disjoint-file layout; give the App-shell agent ownership of shared files; use git worktrees for any unavoidable overlap. |
| **Contract drift between tracks.** | Single source of truth in `contracts/`; CI validates fixtures + both type systems; review gate before integration. |

---

## 9. How to dispatch the agents

- **Phase 0:** run W0.1 → W0.2 → W0.3 sequentially (each fast; each unblocks the fan-out). Do not start Phase 1 until fixtures validate.
- **Phase 1:** launch F1–F8 and B1–B5 concurrently. Frontend agents get: the screen's Figma node id, the relevant fixture path, and the target `screens/<Name>/` folder. Backend agents get: their router/module path and the contract objects they own. Instruct each to pull its own `get_design_context`/`get_screenshot` for pixel accuracy.
- **Review:** one code-reviewer per track.
- **Phase 2–3:** smaller, more sequential; driver (you) stays in the loop between steps.

**Suggested first move:** approve this plan, then I run **Phase 0** myself (scaffold + contracts + fixtures + design system) so the fan-out has a solid, validated base — that's the highest-leverage, least-parallelizable part. Then we launch the Phase 1 fleet.

---

## 10. Definition of done (v1)

Onboarding connects a real local CLI + stores a working YouTube key; a typed topic with filters runs end-to-end; the loader reflects real progress; results render Top-15 (grid+list), Recommended Watch List, and Title/Script analysis with **every link verified real**; history saves and reopens runs; all keys stay local. Screens are pixel-close to Figma.
