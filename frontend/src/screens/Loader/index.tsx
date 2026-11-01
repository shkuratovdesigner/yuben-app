/**
 * F4 — Loader (research in progress). Designed here (no Figma node) to match the
 * app aesthetic: Newsreader display + Inter body + teal, on a centered brand Card.
 *
 * Mounted by the /run/:id route (router.tsx `RunRoute`) for every non-finished
 * status. It reads the live run purely from the store — `useRun(id)` — and never
 * invents a number: phases, pct, detail and counts all come off the stream
 * (CONTRACTS §3 ProgressEvent). See run-store.tsx for the RunView shape.
 *
 * What it renders:
 *   • a phase checklist (PRD §6 labels) driven by `phase`, with completed / active
 *     / pending states and a stepper connector;
 *   • a teal Progress bar — `latestEvent.pct` when present, else indeterminate;
 *   • a live counter strip merged from the stream's `counts`, plus the active
 *     phase's `detail`;
 *   • reassurance copy + a Cancel affordance (`cancel()`); and
 *   • a plain-language error screen mapped from the terminal ErrorCode (PRD §6),
 *     including the no-results empty state, each with a route-back affordance.
 */
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { AlertTriangle, Check, Copy, Info, Loader2, SearchX } from 'lucide-react'

import { useRun } from '@/app/stores/run-store'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { api } from '@/lib/api'
import type { ErrorCode, ProgressPhase } from '@/lib/types'
import { cn } from '@/lib/utils'

// ---------------------------------------------------------------------------
// Phase model — ProgressEvent.phase enum → the exact PRD §6 labels.
// ---------------------------------------------------------------------------

/** The ordered working phases shown as checklist rows (§6, minus done/error). */
const PHASE_SEQUENCE: ProgressPhase[] = [
  'queued',
  'expanding',
  'searching',
  'enriching',
  'scoring',
  'analyzing',
  'verifying',
]

/** ProgressEvent.phase → its PRD §6 label. Rendered for every row (including
 *  phases not yet reached), so it can't come from `event.label` alone. */
const PHASE_LABELS: Record<ProgressPhase, string> = {
  queued: 'Queued',
  expanding: 'Expanding your topic into search terms',
  searching: 'Searching YouTube',
  enriching: 'Pulling channel sizes & stats',
  scoring: 'Scoring outliers (views vs. channel size)',
  analyzing: 'Analyzing titles & scripts',
  verifying: 'Verifying every link',
  done: 'Done',
  error: 'Run stopped',
}

// ---------------------------------------------------------------------------
// Live counters — render only keys the stream actually sends (TRUST RULE).
// ---------------------------------------------------------------------------

const COUNT_ORDER = ['found', 'longform', 'shorts', 'curated'] as const
const COUNT_LABELS: Record<string, (n: number) => string> = {
  found: (n) => `${n.toLocaleString()} videos found`,
  longform: (n) => `${n.toLocaleString()} long-form`,
  shorts: (n) => `${n.toLocaleString()} shorts`,
  curated: (n) => `${n.toLocaleString()} curated`,
}

/** Human phrases from a counts snapshot, known keys first, then any extras. */
function countChips(counts: Record<string, number>): string[] {
  const known = COUNT_ORDER.filter((k) => k in counts).map((k) => COUNT_LABELS[k](counts[k]))
  const extra = Object.keys(counts)
    .filter((k) => !(COUNT_ORDER as readonly string[]).includes(k))
    .map((k) => `${counts[k].toLocaleString()} ${k}`)
  return [...known, ...extra]
}

// ---------------------------------------------------------------------------
// Error copy — terminal ErrorCode → plain-language reason + a route-back action.
// ---------------------------------------------------------------------------

type ErrorTone = 'error' | 'empty' | 'neutral'

interface ErrorCopy {
  tone: ErrorTone
  title: string
  body: string
  actionLabel: string
  actionTo: string
}

/** PRD §6 empty/error copy. The backend detail (`message`) is the body for every
 *  code: it names the actual cause and fix (a disabled YouTube API, a rejected
 *  model key), which one fixed string per code cannot. The canonical §6 string
 *  is the fallback. Titles stay generic enough to fit every cause behind a code;
 *  `cancelled` keeps its own copy, since its detail adds nothing. */
function errorCopy(code: ErrorCode, message?: string | null): ErrorCopy {
  const detail = message?.trim()
  switch (code) {
    case 'no_results':
      return {
        tone: 'empty',
        title: 'No standout videos found',
        body:
          detail ||
          'No standout videos matched those filters. Try a broader date range or lower the outperformance bar.',
        actionLabel: 'Adjust filters',
        actionTo: '/',
      }
    case 'quota_exceeded':
      return {
        tone: 'error',
        title: "YouTube couldn't run the search",
        body: detail || "YouTube's daily quota is used up. Try again after it resets, or use a different key.",
        actionLabel: 'Check YouTube key',
        actionTo: '/onboarding/setup',
      }
    case 'cli_missing':
      return {
        tone: 'error',
        title: 'Finish the model setup',
        body:
          detail ||
          "We couldn't find the agent CLI. Install it, then run the environment check again.",
        actionLabel: 'Go to setup',
        actionTo: '/onboarding/model',
      }
    case 'cancelled':
      return {
        tone: 'neutral',
        title: 'Run cancelled',
        body: 'You stopped this research run. Nothing was saved — start a new search whenever you’re ready.',
        actionLabel: 'New search',
        actionTo: '/',
      }
    case 'cli_failed':
      return {
        tone: 'error',
        title: 'The model hit an error',
        body: detail || 'The model failed partway through the run. Trying again often clears it.',
        actionLabel: 'Back to search',
        actionTo: '/',
      }
    case 'invalid_output':
      return {
        tone: 'error',
        title: 'Couldn’t read the results',
        body:
          detail ||
          'The agent returned something we couldn’t parse. Running it again usually fixes this.',
        actionLabel: 'Back to search',
        actionTo: '/',
      }
    default:
      return {
        tone: 'error',
        title: 'Something went wrong',
        body: detail || 'The run stopped unexpectedly. Please try again.',
        actionLabel: 'Back to search',
        actionTo: '/',
      }
  }
}

// ---------------------------------------------------------------------------
// Small presentational pieces.
// ---------------------------------------------------------------------------

/** Vertically-centered stage under the app chrome. */
function Stage({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto flex min-h-[70vh] w-full max-w-[560px] flex-col items-center justify-center">
      {children}
    </div>
  )
}

type StepState = 'complete' | 'active' | 'pending'

/**
 * Stepper node. All three sit centred on the 20px icon column so the rail behind
 * them (see the checklist below) stays on one axis.
 *
 * complete/active are opaque 20px discs — the rail runs *behind* them and is
 * masked, so they read as beads threaded on the line. `bg-brand-card` on the
 * spinner is load-bearing: Loader2 is an open ring, so without it the rail shows
 * through the middle of the active node.
 *
 * pending is a small dot drawn straight *on top of* the rail (no mask), which is
 * what keeps the untravelled stretch reading as one unbroken line. It's a
 * flex-centred wrapper rather than a bare sized span because a `size-5` <span>
 * is still `display: inline` — width/height don't apply, and it collapses into a
 * 2px tick offset from the rail, i.e. the doubled-line artefact.
 */
function StepIcon({ state }: { state: StepState }) {
  if (state === 'complete') {
    return (
      <span className="flex size-5 items-center justify-center rounded-full bg-brand-selected text-white">
        <Check className="size-3" strokeWidth={3} />
      </span>
    )
  }
  if (state === 'active') {
    return (
      <span className="flex size-5 items-center justify-center rounded-full bg-brand-card">
        <Loader2 className="size-5 animate-spin text-brand-teal" />
      </span>
    )
  }
  return (
    <span className="flex size-5 items-center justify-center">
      <span className="size-2.5 rounded-full bg-brand-muted" />
    </span>
  )
}

type CopyState = 'idle' | 'copying' | 'copied' | 'failed'

/** Copies the run's redacted diagnostics log (backend `diagnostics.py`) so a
 *  failed run can be reported in one message. The log is fetched when the card
 *  mounts, so the click writes to the clipboard at once: Safari refuses a write
 *  that waits on a fetch after the click. If the clipboard is blocked, the text
 *  is shown to copy by hand, with where it is saved. */
function CopyDiagnosticsButton({ runId }: { runId: string }) {
  const [state, setState] = useState<CopyState>('idle')
  const [text, setText] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    api
      .getDiagnostics(runId)
      .then((t) => live && setText(t))
      .catch(() => {})
    return () => {
      live = false
    }
  }, [runId])

  async function onCopy() {
    setState('copying')
    try {
      const value = text ?? (await api.getDiagnostics(runId))
      setText(value)
      await navigator.clipboard.writeText(value)
      setState('copied')
      window.setTimeout(() => setState('idle'), 2000)
    } catch {
      setState('failed')
    }
  }

  return (
    <div className="flex w-full flex-col items-center gap-2">
      <Button variant="outline" size="sm" onClick={() => void onCopy()} disabled={state === 'copying'}>
        {state === 'copied' ? <Check className="size-4" aria-hidden /> : <Copy className="size-4" aria-hidden />}
        {state === 'copied' ? 'Copied' : 'Copy diagnostics'}
      </Button>
      {state === 'failed' && (
        <div className="flex w-full flex-col gap-2" role="status">
          <p className="text-[13px] leading-relaxed text-brand-muted">
            Couldn’t copy automatically. {text ? 'Select the text below and copy it. ' : ''}It’s also
            saved as backend/.yuben/diagnostics/{runId}.json.
          </p>
          {text && (
            <textarea
              readOnly
              value={text}
              onFocus={(e) => e.currentTarget.select()}
              aria-label="Diagnostics"
              className="h-40 w-full resize-none rounded-md border border-input bg-background p-3 text-left font-mono text-[12px] text-foreground"
            />
          )}
        </div>
      )}
    </div>
  )
}

/** Terminal error / empty screen — a plain-language reason (PRD §6) plus a
 *  route-back action. Rendered for every non-'done' terminal, cancel included.
 *  Errors also offer "Copy diagnostics" when the run id is known. */
export function LoaderErrorCard({
  code,
  message,
  runId,
}: {
  code: ErrorCode
  message?: string | null
  runId?: string
}) {
  const navigate = useNavigate()
  const copy = errorCopy(code, message)
  const Icon = copy.tone === 'empty' ? SearchX : copy.tone === 'neutral' ? Info : AlertTriangle
  const iconTone =
    copy.tone === 'error' ? 'bg-destructive/10 text-destructive' : 'bg-muted text-brand-grey'

  return (
    <Stage>
      <Card className="flex w-full flex-col items-center gap-6 p-8 text-center sm:p-10">
        <span className={cn('flex size-12 items-center justify-center rounded-full', iconTone)}>
          <Icon className="size-6" />
        </span>
        <div className="flex flex-col gap-2">
          <h1 className="font-display text-[26px] leading-tight text-foreground">{copy.title}</h1>
          <p className="text-[15px] leading-relaxed text-brand-muted">{copy.body}</p>
        </div>
        <div className="flex flex-col items-center gap-3">
          <Button onClick={() => navigate(copy.actionTo)}>{copy.actionLabel}</Button>
          {copy.tone === 'error' && runId && <CopyDiagnosticsButton runId={runId} />}
        </div>
      </Card>
    </Stage>
  )
}

/** The run id isn't on the server. Its own card, because every ErrorCode would
 *  claim a run failed — nothing failed here, there's just nothing to show. */
export function LoaderMissingCard() {
  const navigate = useNavigate()
  return (
    <Stage>
      <Card className="flex w-full flex-col items-center gap-6 p-8 text-center sm:p-10">
        <span className="flex size-12 items-center justify-center rounded-full bg-muted text-brand-grey">
          <SearchX className="size-6" />
        </span>
        <div className="flex flex-col gap-2">
          <h1 className="font-display text-[26px] leading-tight text-foreground">
            This run isn’t here anymore
          </h1>
          <p className="text-[15px] leading-relaxed text-brand-muted">
            Runs are kept in memory while the app is open, so restarting the backend clears them.
            Nothing is running behind this page — start a new search to pick it up again.
          </p>
        </div>
        <Button onClick={() => navigate('/')}>New search</Button>
      </Card>
    </Stage>
  )
}

// ---------------------------------------------------------------------------
// Screen.
// ---------------------------------------------------------------------------

export default function Loader() {
  const { id } = useParams<{ id: string }>()
  const run = useRun(id)

  const { status, phase, latestEvent, events, error } = run

  // Merge every counts snapshot seen so far so the strip never flickers back to
  // empty — each value is the last real figure the stream reported for that key.
  const counts = useMemo(
    () =>
      events.reduce<Record<string, number>>((acc, e) => {
        if (e.counts) for (const [k, v] of Object.entries(e.counts)) acc[k] = v
        return acc
      }, {}),
    [events],
  )

  // --- Terminal error / empty state (covers cancel too) --------------------
  if (status === 'error') {
    const code: ErrorCode = error?.code ?? latestEvent?.error?.code ?? 'unknown'
    return (
      <LoaderErrorCard
        code={code}
        message={error?.message ?? latestEvent?.error?.message}
        runId={id}
      />
    )
  }

  // --- The server has no such run ------------------------------------------
  // Not an ErrorCode: no run failed, so don't dress it as a failure. Runs are
  // held in memory, so a restarted backend forgets them and any old /run/ link
  // lands here.
  if (status === 'missing') {
    return <LoaderMissingCard />
  }

  // --- In-progress state ---------------------------------------------------
  // Index of the active phase; `done` marks every row complete; null/loading
  // (fresh start, history reopen) reads as "just queued".
  const currentIndex =
    phase === 'done'
      ? PHASE_SEQUENCE.length
      : phase && PHASE_SEQUENCE.includes(phase)
        ? PHASE_SEQUENCE.indexOf(phase)
        : 0

  const pct = latestEvent?.pct
  const hasPct = typeof pct === 'number'
  const detail = latestEvent?.detail
  const chips = countChips(counts)
  const isDone = phase === 'done'
  const showCancel = status === 'running' && !isDone

  const srSummary = `${PHASE_LABELS[phase ?? 'queued']}${hasPct ? `, ${pct}%` : ''}`

  return (
    <Stage>
      <Card className="w-full p-8 sm:p-10">
        {/* Eyebrow + headline */}
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2 text-[13px] font-medium text-brand-teal">
            {isDone ? (
              <Check className="size-3.5" strokeWidth={3} />
            ) : (
              <span className="relative flex size-2" aria-hidden>
                <span className="absolute inline-flex size-full animate-ping rounded-full bg-brand-teal opacity-60" />
                <span className="relative inline-flex size-2 rounded-full bg-brand-teal" />
              </span>
            )}
            {isDone ? 'Done' : 'Researching'}
          </div>
          <h1 className="font-display text-[28px] leading-tight text-foreground">
            Finding your outliers
          </h1>
          <p className="text-[15px] leading-relaxed text-brand-muted">
            Scanning YouTube and scoring videos against their channel size. This can take a couple of
            minutes — you can keep this tab open.
          </p>
        </div>

        {/* Progress bar + live meta */}
        <div className="mt-7 flex flex-col gap-2">
          <Progress value={hasPct ? pct : undefined} indeterminate={!hasPct} />
          <div className="flex items-center justify-between gap-3 text-[13px] text-brand-grey">
            <span className="truncate">{chips.length > 0 ? chips.join(' · ') : detail ?? ' '}</span>
            {hasPct && <span className="shrink-0 tabular-nums">{pct}%</span>}
          </div>
        </div>

        {/* Phase checklist */}
        <ol className="mt-7 flex flex-col">
          {PHASE_SEQUENCE.map((p, i) => {
            const state: StepState =
              i < currentIndex ? 'complete' : i === currentIndex ? 'active' : 'pending'
            const isLast = i === PHASE_SEQUENCE.length - 1
            return (
              <li
                key={p}
                aria-current={state === 'active' ? 'step' : undefined}
                className="relative flex gap-3 pb-5 last:pb-0"
              >
                {/* The rail, in two halves per row: node centre is 11px down
                    (1px mt-px + half of the 20px node). Each row's lower half
                    runs to its own bottom edge and the next row's upper half
                    starts at 0, so the halves butt together into ONE unbroken
                    line down the column — no rounded caps, or the joins notch.
                    Splitting at the node is what lets the active row show a
                    travelled (green) stretch above and an untravelled (grey)
                    one below. */}
                {i > 0 && (
                  <span
                    aria-hidden
                    className={cn(
                      'absolute left-[9px] top-0 h-[11px] w-0.5',
                      i <= currentIndex ? 'bg-brand-selected' : 'bg-border',
                    )}
                  />
                )}
                {!isLast && (
                  <span
                    aria-hidden
                    className={cn(
                      'absolute bottom-0 left-[9px] top-[11px] w-0.5',
                      i < currentIndex ? 'bg-brand-selected' : 'bg-border',
                    )}
                  />
                )}
                <span className="relative z-10 mt-px shrink-0">
                  <StepIcon state={state} />
                </span>
                <div className="flex min-w-0 flex-col">
                  <span
                    className={cn(
                      'text-[15px] leading-5',
                      state === 'active' && 'font-medium text-foreground',
                      state === 'complete' && 'text-foreground',
                      state === 'pending' && 'text-brand-muted',
                    )}
                  >
                    {PHASE_LABELS[p]}
                  </span>
                  {state === 'active' && detail && (
                    <span className="mt-0.5 text-[13px] text-brand-muted">{detail}</span>
                  )}
                </div>
              </li>
            )
          })}
        </ol>

        {/* Cancel */}
        {showCancel && (
          <div className="mt-8 flex justify-center border-t border-border pt-6">
            <Button variant="ghost" size="sm" onClick={run.cancel}>
              Cancel research
            </Button>
          </div>
        )}

        {/* Screen-reader live status (concise; avoids announcing every row). */}
        <p className="sr-only" role="status" aria-live="polite">
          {srSummary}
        </p>
      </Card>
    </Stage>
  )
}
