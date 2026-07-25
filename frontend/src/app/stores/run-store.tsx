/**
 * Run store — owns the lifecycle of every research run: start → SSE progress →
 * final result, plus reopening a finished run from History without re-running.
 *
 * WAVE-2 SCREENS CONSUME THIS — two hooks:
 *
 *   useStartRun(): (req: ResearchRequest) => Promise<string>
 *     Starts a run, subscribes to its progress stream, returns the new run_id.
 *     • F3 Composer: `const id = await startRun(req); navigate('/run/' + id)`.
 *
 *   useRun(runId: string | undefined): RunView
 *     RunView = {
 *       runId, status, phase, latestEvent, events, result, error, cancel()
 *     }
 *     Reactive per-run state. Mounting it also ENSURES the run is tracked: if the
 *     store has never seen `runId` (page refresh, or a History click), it fetches
 *     the cached result (getResult) — falling back to live progress if not done.
 *     • F4 Loader:  reads status/phase/latestEvent/events; Cancel → `cancel()`.
 *     • F5/F6 Results: read `result` once `status === 'done'`.
 *
 * STATUS values:
 *   'idle'    — unknown / no runId yet.
 *   'loading' — fetching a previously-finished run's result (History reopen / refresh).
 *   'running' — live: progress events are streaming.
 *   'done'    — finished; `result` is populated. (Only now may Results mount.)
 *   'error'   — failed or cancelled; `error` holds {code, message}.
 *   'missing' — the server has no such run (404). Terminal, and distinct from
 *               'error': nothing went wrong with a run, there is no run.
 *
 * The App-shell RunRoute switches screens on this: `status === 'done' && result`
 * ⇒ <Results/>, otherwise ⇒ <Loader/>. Results is never mounted without a result.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import type {
  ProgressError,
  ProgressEvent,
  ProgressPhase,
  ResearchRequest,
  ResearchResult,
} from '@/lib/types'
import { ApiError, api } from '@/lib/api'

export type RunStatus = 'idle' | 'loading' | 'running' | 'done' | 'error' | 'missing'

export interface RunState {
  runId: string
  status: RunStatus
  phase: ProgressPhase | null
  latestEvent: ProgressEvent | null
  events: ProgressEvent[]
  result: ResearchResult | null
  error: ProgressError | null
}

export interface RunView extends RunState {
  /** Cancel a running job (no-op once done/errored). */
  cancel: () => void
}

interface RunContextValue {
  runs: Record<string, RunState>
  startRun: (req: ResearchRequest) => Promise<string>
  ensureRun: (runId: string) => void
  cancelRun: (runId: string) => void
}

const RunContext = createContext<RunContextValue | null>(null)

function initialState(runId: string, status: RunStatus): RunState {
  return { runId, status, phase: null, latestEvent: null, events: [], result: null, error: null }
}

function idleState(runId: string): RunView {
  return { ...initialState(runId, 'idle'), cancel: () => {} }
}

export function RunProvider({ children }: { children: ReactNode }) {
  const [runs, setRuns] = useState<Record<string, RunState>>({})
  // Guards + handles that must not trigger re-renders.
  const tracked = useRef<Set<string>>(new Set())
  const unsubs = useRef<Map<string, () => void>>(new Map())

  const patchRun = useCallback((runId: string, patch: Partial<RunState>) => {
    setRuns((prev) => {
      const base = prev[runId] ?? initialState(runId, 'running')
      return { ...prev, [runId]: { ...base, ...patch } }
    })
  }, [])

  const applyEvent = useCallback(
    (runId: string, event: ProgressEvent) => {
      setRuns((prev) => {
        const base = prev[runId] ?? initialState(runId, 'running')
        // 'done' stays 'running' here — status flips to 'done' only once the
        // result is fetched, so Results never mounts against a null result.
        const status: RunStatus = event.phase === 'error' ? 'error' : base.status === 'done' ? 'done' : 'running'
        return {
          ...prev,
          [runId]: {
            ...base,
            status,
            phase: event.phase,
            latestEvent: event,
            events: [...base.events, event],
          },
        }
      })
    },
    [],
  )

  const subscribe = useCallback(
    (runId: string) => {
      // Never double-subscribe a run.
      if (unsubs.current.has(runId)) return
      const unsub = api.subscribeEvents(
        runId,
        (event) => applyEvent(runId, event),
        async () => {
          try {
            const result = await api.getResult(runId)
            patchRun(runId, { status: 'done', phase: 'done', result })
          } catch (err) {
            patchRun(runId, {
              status: 'error',
              error: { code: 'unknown', message: err instanceof Error ? err.message : 'Failed to load result.' },
            })
          }
        },
        (error) => patchRun(runId, { status: 'error', error }),
      )
      unsubs.current.set(runId, unsub)
    },
    [applyEvent, patchRun],
  )

  const startRun = useCallback(
    async (req: ResearchRequest) => {
      const { run_id } = await api.startResearch(req)
      tracked.current.add(run_id)
      patchRun(run_id, { status: 'running' })
      subscribe(run_id)
      return run_id
    },
    [patchRun, subscribe],
  )

  const ensureRun = useCallback(
    (runId: string) => {
      // Idempotent: a run we started (or already ensured) is skipped.
      if (tracked.current.has(runId)) return
      tracked.current.add(runId)
      patchRun(runId, { status: 'loading' })
      api
        .getResult(runId)
        .then((result) => patchRun(runId, { status: 'done', phase: 'done', result }))
        .catch((err: unknown) => {
          // A 404 means the server has no such run — it was never started, or
          // the backend restarted (runs live in memory). That is terminal:
          // treating it as "not finished yet" subscribes to a stream that also
          // 404s, leaving the loader spinning on "Queued" forever.
          if (err instanceof ApiError && err.status === 404) {
            patchRun(runId, { status: 'missing' })
            return
          }
          // Any other failure — still running, or a transient blip. Fall back to
          // the live progress stream.
          patchRun(runId, { status: 'running' })
          subscribe(runId)
        })
    },
    [patchRun, subscribe],
  )

  const cancelRun = useCallback(
    (runId: string) => {
      void api.cancelRun(runId)
      unsubs.current.get(runId)?.()
      unsubs.current.delete(runId)
      patchRun(runId, { status: 'error', error: { code: 'cancelled', message: 'Run cancelled.' } })
    },
    [patchRun],
  )

  // Tear down every open stream when the provider unmounts.
  useEffect(() => {
    const handles = unsubs.current
    return () => {
      handles.forEach((unsub) => unsub())
      handles.clear()
    }
  }, [])

  const value = useMemo<RunContextValue>(
    () => ({ runs, startRun, ensureRun, cancelRun }),
    [runs, startRun, ensureRun, cancelRun],
  )

  return <RunContext.Provider value={value}>{children}</RunContext.Provider>
}

function useRunContext(): RunContextValue {
  const ctx = useContext(RunContext)
  if (!ctx) throw new Error('Run hooks must be used within <RunProvider> (see AppProviders).')
  return ctx
}

/** Composer entry point: start a run, get its run_id back to navigate to. */
export function useStartRun(): (req: ResearchRequest) => Promise<string> {
  return useRunContext().startRun
}

/** Reactive view of one run; mounting it ensures the run is tracked/fetched. */
export function useRun(runId: string | undefined): RunView {
  const { runs, ensureRun, cancelRun } = useRunContext()

  useEffect(() => {
    if (runId) ensureRun(runId)
  }, [runId, ensureRun])

  const cancel = useCallback(() => {
    if (runId) cancelRun(runId)
  }, [runId, cancelRun])

  if (!runId) return idleState('')
  const state = runs[runId] ?? initialState(runId, 'loading')
  return { ...state, cancel }
}
