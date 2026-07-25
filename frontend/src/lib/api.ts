/**
 * YuBen typed API client — the single boundary between the frontend and the
 * backend (CONTRACTS §1). Every function returns a shape from `@/lib/types`.
 *
 * One mode: real `fetch` to `${API_BASE}/api/...` (an empty base ⇒ relative, via
 * the Vite dev proxy), with SSE over EventSource. There used to be a fixture-
 * serving mock client here too, on by default — which meant the app's own
 * History and results could be demo data without the user being told. The
 * example run now lives in the backend's store like any other run, so the
 * frontend has no second source of truth.
 *
 * TRUST RULE: this client only plumbs data. It never synthesizes or transforms
 * video IDs, view counts, or any fact — every one of those comes from the
 * deterministic backend.
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
import { API_BASE } from '@/lib/env'

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

// ---------------------------------------------------------------------------
// Live client
// ---------------------------------------------------------------------------

/**
 * An HTTP error that kept its status code.
 *
 * Callers have to tell "this run is not on the server" (404) apart from "the
 * request failed" — a run store that can't see the difference reads a 404 as
 * "still working" and waits on a run that will never report. Mock-client errors
 * stay plain `Error`s, so `status` is simply undefined there.
 */
export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** Thin JSON fetch helper. `API_BASE` empty ⇒ relative path (Vite dev proxy). */
async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    throw new ApiError(
      `${init?.method ?? 'GET'} ${path} failed: ${res.status} ${res.statusText}`,
      res.status,
    )
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
export const api: ApiClient = createLiveClient()
