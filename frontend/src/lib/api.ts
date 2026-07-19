/**
 * YuBen typed API client — the single boundary between the frontend and the
 * backend (CONTRACTS §1). Every function returns a shape from `@/lib/types`.
 *
 * Two modes, switched on `USE_MOCKS` from `@/lib/env`:
 *   • MOCK  (default ON)  — serves the bundled `frontend/fixtures/*`; never
 *                            touches the network. Lets the whole UI run with no
 *                            backend. Light in-memory state makes writes
 *                            (`putConfig`/`postKey`/`deleteHistory`/…) stick for
 *                            subsequent reads within the session.
 *   • LIVE  (USE_MOCKS=0)  — real `fetch` to `${API_BASE}/api/...` (empty base
 *                            ⇒ relative, uses the Vite dev proxy). SSE via
 *                            EventSource. Not exercised until Phase 2, but it
 *                            typechecks and is correct.
 *
 * TRUST RULE: this client only plumbs data. It never synthesizes or transforms
 * video IDs, view counts, or any fact — those originate solely in the fixtures
 * now (and the deterministic backend later). The only identifiers it mints are
 * session-scoped `run_id`s for mock runs.
 *
 * SECRETS: the YouTube key is write-only (`postKey` POST body). No function ever
 * returns a key or places any secret in a URL / query string.
 */
import type {
  Adapter,
  Config,
  EnvCheckResult,
  HistoryItem,
  KeyProvider,
  KeyTestResult,
  ProgressError,
  ProgressEvent,
  RemedyResult,
  ResearchRequest,
  ResearchResult,
  StartRunResponse,
} from '@/lib/types'
import { API_BASE, USE_MOCKS } from '@/lib/env'

// Bundled fixtures (mock data source). JSON imports need `resolveJsonModule`;
// the JSONL stream is imported as raw text (`vite/client` types `?raw` = string).
import adaptersJson from '@fixtures/adapters.json'
import configJson from '@fixtures/config.json'
import historyJson from '@fixtures/history.json'
import longformJson from '@fixtures/research-result.longform.json'
import shortsJson from '@fixtures/research-result.shorts.json'
import eventsRaw from '@fixtures/progress-events.jsonl?raw'

/**
 * The client every screen imports. One method per CONTRACTS §1 endpoint plus
 * the SSE subscription helper. `subscribeEvents` returns an unsubscribe fn;
 * everything else is a Promise of the resolved contract shape.
 */
export interface ApiClient {
  getConfig(): Promise<Config>
  putConfig(config: Config): Promise<Config>
  /**
   * Write-only: stores a key locally, returns `{ ok }`. Never echoes it.
   * `provider` selects the secret — `'youtube'` (default) or `'anthropic'`.
   */
  postKey(key: string, provider?: KeyProvider): Promise<{ ok: boolean }>
  envCheck(): Promise<EnvCheckResult>
  /**
   * Run the selected adapter's remedy (today: open a terminal on its sign-in
   * command). Sends only an adapter id — the command lives on the backend.
   */
  runRemedy(adapter?: string): Promise<RemedyResult>
  keyTest(): Promise<KeyTestResult>
  getAdapters(): Promise<Adapter[]>
  startResearch(req: ResearchRequest): Promise<StartRunResponse>
  /**
   * Subscribe to a run's ProgressEvent stream.
   * @returns an unsubscribe fn — call it to stop the stream (EventSource close
   *          in live mode, timer clear in mock mode).
   */
  subscribeEvents(
    runId: string,
    onEvent: (event: ProgressEvent) => void,
    onDone: () => void,
    onError: (error: ProgressError) => void,
  ): () => void
  getResult(runId: string): Promise<ResearchResult>
  cancelRun(runId: string): Promise<void>
  getHistory(): Promise<HistoryItem[]>
  deleteHistory(runId: string): Promise<void>
}

// Cast fixtures through `unknown`: JSON imports widen literal unions (e.g.
// `schema_version` infers `string`, not `'1.0'`), so a direct cast won't hold.
const FIXTURE_CONFIG = configJson as unknown as Config
const FIXTURE_ADAPTERS = adaptersJson as unknown as Adapter[]
const FIXTURE_HISTORY = historyJson as unknown as HistoryItem[]
const FIXTURE_LONGFORM = longformJson as unknown as ResearchResult
const FIXTURE_SHORTS = shortsJson as unknown as ResearchResult

/** Which Config presence flag each stored key flips (mirrors the config store). */
const MOCK_PRESENCE_FLAG: Record<KeyProvider, keyof Config> = {
  youtube: 'youtube_key_present',
  anthropic: 'anthropic_key_present',
  openai: 'openai_key_present',
  openrouter: 'openrouter_key_present',
}

/**
 * Adapters whose mock env-check hinges on a stored key rather than an installed
 * CLI. Ollama is absent on purpose: it needs no key, so it follows the CLI path
 * and its verdict comes from the adapter fixture's `installed` flag.
 */
const MOCK_KEY_ADAPTERS: Record<
  string,
  { flag: keyof Config; label: string; version: string; model: string }
> = {
  'anthropic-api': {
    flag: 'anthropic_key_present',
    label: 'Anthropic',
    version: '0.117.0',
    model: 'claude-opus-4-8',
  },
  'openai-api': {
    flag: 'openai_key_present',
    label: 'OpenAI',
    version: '2.46.0',
    model: 'gpt-4o-mini',
  },
  openrouter: {
    flag: 'openrouter_key_present',
    label: 'OpenRouter',
    version: '2.46.0',
    model: 'openai/gpt-4o-mini',
  },
}

/** Parse the JSONL fixture once into an ordered ProgressEvent list. */
const FIXTURE_EVENTS: ProgressEvent[] = eventsRaw
  .split('\n')
  .map((line) => line.trim())
  .filter((line) => line.length > 0)
  .map((line) => JSON.parse(line) as ProgressEvent)

// ---------------------------------------------------------------------------
// Mock client
// ---------------------------------------------------------------------------

function createMockClient(): ApiClient {
  // In-memory session state so writes reflect on later reads.
  let config: Config = { ...FIXTURE_CONFIG }
  let history: HistoryItem[] = FIXTURE_HISTORY.map((item) => ({ ...item }))
  // Remember each started run's format so getResult can serve the right fixture.
  const runFormat = new Map<string, ResearchRequest['format']>()
  let runCounter = 0

  const delay = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

  /** Pick the result fixture: by the started run's format, else infer from the id. */
  function resultFor(runId: string): ResearchResult {
    const format = runFormat.get(runId) ?? (runId.includes('shorts') ? 'shorts' : 'longform')
    const base = format === 'shorts' ? FIXTURE_SHORTS : FIXTURE_LONGFORM
    // Keep the run coherent with the URL without touching any fact fields.
    return { ...base, run_id: runId }
  }

  return {
    async getConfig() {
      await delay(60)
      return { ...config }
    },

    async putConfig(next) {
      await delay(60)
      config = { ...next }
      return { ...config }
    },

    async postKey(key, provider = 'youtube') {
      await delay(80)
      // Never store or echo the value in the mock; just flip the presence flag.
      const ok = key.trim().length > 0
      if (ok) config = { ...config, [MOCK_PRESENCE_FLAG[provider]]: true }
      return { ok }
    },

    async envCheck() {
      await delay(400)
      const adapterId = config.adapter ?? 'claude-code'
      // Key-paste API paths: the "probe" needs a stored key, not a CLI.
      const keyPath = MOCK_KEY_ADAPTERS[adapterId]
      if (keyPath) {
        return config[keyPath.flag]
          ? {
              ok: true,
              adapter: adapterId,
              version: keyPath.version,
              message: `${keyPath.label} responded (${keyPath.model}).`,
            }
          : {
              ok: false,
              adapter: adapterId,
              version: keyPath.version,
              message: `Paste your ${keyPath.label} API key above, then run the check again.`,
            }
      }
      const adapter = FIXTURE_ADAPTERS.find((a) => a.id === adapterId)
      if (adapter?.installed) {
        return {
          ok: true,
          adapter: adapterId,
          version: adapter.version,
          message: `${adapter.name} responded: hello`,
        }
      }
      return {
        ok: false,
        adapter: adapterId,
        version: null,
        message: `Couldn't find the ${adapter?.name ?? adapterId} CLI. Install it, then run the check again.`,
        remedy: {
          kind: 'install' as const,
          label: `Install ${adapter?.name ?? adapterId}`,
          command: null,
          url: 'https://claude.com/claude-code',
        },
      }
    },

    async runRemedy() {
      await delay(200)
      // No terminal to open in mock mode — say so plainly rather than pretending.
      return {
        ok: false,
        message: 'Mock mode: connect a real backend to run the sign-in for you.',
        command: null,
      }
    },

    async keyTest() {
      await delay(400)
      return config.youtube_key_present
        ? { ok: true, message: 'YouTube accepted the key.' }
        : { ok: false, message: 'No key stored yet. Paste your YouTube key first.' }
    },

    async getAdapters() {
      await delay(60)
      return FIXTURE_ADAPTERS.map((a) => ({ ...a }))
    },

    async startResearch(req) {
      await delay(120)
      const runId = `r_mock_${req.format}_${++runCounter}`
      runFormat.set(runId, req.format)
      return { run_id: runId }
    },

    subscribeEvents(runId, onEvent, onDone, onError) {
      let cancelled = false
      let timer: ReturnType<typeof setTimeout> | undefined
      let i = 0

      const step = () => {
        if (cancelled) return
        if (i >= FIXTURE_EVENTS.length) return
        // Re-stamp run_id so the stream is coherent with the subscribed run.
        const event: ProgressEvent = { ...FIXTURE_EVENTS[i], run_id: runId }
        i += 1
        onEvent(event)
        if (event.phase === 'done') {
          onDone()
          return
        }
        if (event.phase === 'error') {
          onError(event.error ?? { code: 'unknown', message: 'Run failed.' })
          return
        }
        timer = setTimeout(step, 350)
      }

      // Kick off on the next tick so callers can finish wiring state first.
      timer = setTimeout(step, 250)

      return () => {
        cancelled = true
        if (timer) clearTimeout(timer)
      }
    },

    async getResult(runId) {
      await delay(120)
      return resultFor(runId)
    },

    async cancelRun(runId) {
      await delay(40)
      runFormat.delete(runId)
    },

    async getHistory() {
      await delay(60)
      return history.map((item) => ({ ...item }))
    },

    async deleteHistory(runId) {
      await delay(60)
      history = history.filter((item) => item.run_id !== runId)
    },
  }
}

// ---------------------------------------------------------------------------
// Live client
// ---------------------------------------------------------------------------

/** Thin JSON fetch helper. `API_BASE` empty ⇒ relative path (Vite dev proxy). */
async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    throw new Error(`${init?.method ?? 'GET'} ${path} failed: ${res.status} ${res.statusText}`)
  }
  // 204/empty bodies are valid for void endpoints.
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}

/** Heuristic: a full ResearchResult carries `top_videos`; a not-done poll doesn't. */
function isResult(payload: unknown): payload is ResearchResult {
  return typeof payload === 'object' && payload !== null && 'top_videos' in payload
}

function createLiveClient(): ApiClient {
  return {
    getConfig() {
      return http<Config>('/api/config')
    },

    putConfig(config) {
      return http<Config>('/api/config', { method: 'PUT', body: JSON.stringify(config) })
    },

    postKey(key, provider = 'youtube') {
      // Secret travels in the POST body only — never a URL/query string.
      return http<{ ok: boolean }>('/api/config/key', {
        method: 'POST',
        body: JSON.stringify({ key, provider }),
      })
    },

    envCheck() {
      return http<EnvCheckResult>('/api/config/env-check', { method: 'POST' })
    },

    runRemedy(adapter?: string) {
      return http<RemedyResult>('/api/config/remedy', {
        method: 'POST',
        body: JSON.stringify({ adapter: adapter ?? null }),
      })
    },

    keyTest() {
      return http<KeyTestResult>('/api/config/key-test', { method: 'POST' })
    },

    getAdapters() {
      return http<Adapter[]>('/api/adapters')
    },

    startResearch(req) {
      return http<StartRunResponse>('/api/research', {
        method: 'POST',
        body: JSON.stringify(req),
      })
    },

    subscribeEvents(runId, onEvent, onDone, onError) {
      const source = new EventSource(`${API_BASE}/api/research/${runId}/events`)

      source.onmessage = (msg: MessageEvent<string>) => {
        let event: ProgressEvent
        try {
          event = JSON.parse(msg.data) as ProgressEvent
        } catch {
          return
        }
        onEvent(event)
        if (event.phase === 'done') {
          source.close()
          onDone()
        } else if (event.phase === 'error') {
          source.close()
          onError(event.error ?? { code: 'unknown', message: 'Run failed.' })
        }
      }

      source.onerror = () => {
        // Transient network blips: EventSource auto-reconnects. A hard failure
        // surfaces as a stream that stops; the run store can still poll getResult.
      }

      return () => source.close()
    },

    async getResult(runId) {
      const payload = await http<unknown>(`/api/research/${runId}`)
      if (!isResult(payload)) {
        throw new Error(`Run ${runId} is not done yet`)
      }
      return payload
    },

    async cancelRun(runId) {
      await http<void>(`/api/research/${runId}/cancel`, { method: 'POST' })
    },

    getHistory() {
      return http<HistoryItem[]>('/api/history')
    },

    async deleteHistory(runId) {
      await http<void>(`/api/history/${runId}`, { method: 'DELETE' })
    },
  }
}

/**
 * The singleton API client. Screens and stores import this — they never branch
 * on mock/live themselves; the switch lives here.
 */
export const api: ApiClient = USE_MOCKS ? createMockClient() : createLiveClient()
