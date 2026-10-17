import { useEffect, useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, Copy, ExternalLink, Loader2, LogIn } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { api } from '@/lib/api'
import type { EnvCheckResult } from '@/lib/types'

/**
 * How long the user must have been away from the tab before coming back re-runs
 * the check. Long enough that a stray click outside the window doesn't spawn a
 * probe; far shorter than any real sign-in round-trip.
 */
const AWAY_THRESHOLD_MS = 1500

interface EnvCheckRowProps {
  /** No adapter picked yet → nothing to probe. */
  disabled: boolean
  /** Fallback install page, used only when the backend sends no remedy. */
  installUrl?: string
  /**
   * A verdict the app already has for this adapter (the composer's load-time
   * probe). Adopted while the row has none of its own, so arriving via
   * "Reconnect" opens on the failure and its fix instead of a blank row.
   */
  knownResult?: EnvCheckResult | null
  /** That app-level probe is in flight — render it as testing. */
  checking?: boolean
  /** Live probe: `useConfig().runEnvCheck` — asks the CLI to respond "hello". */
  onRun: () => Promise<EnvCheckResult>
  /** Bubble the outcome up so the screen can gate Continue on a passing check. */
  onResult: (result: EnvCheckResult) => void
}

/**
 * Adapter environment-check row (Figma 13:474). Runs the real probe and renders
 * its verdict verbatim.
 *
 * FAILURES CARRY AN ACTION, NOT A LINK DUMP. This row used to answer every
 * failure with the same "Install guide ↗" — nonsense when the CLI is plainly
 * installed and the real problem is a stale login, which is the single most
 * common way connecting a model goes wrong. The backend now says which remedy
 * applies (`result.remedy`) and this renders the matching control: a one-click
 * **Sign in** that opens a terminal on the auth flow, or an install link when
 * the tool genuinely isn't there.
 *
 * Sign-in itself is an interactive OAuth round-trip, so the button gets the user
 * to a ready prompt rather than pretending to authenticate for them — and if no
 * terminal can be opened, it degrades to copying the exact command.
 *
 * THE FIX ENDS WITH A RE-TEST, SO THE ROW RUNS IT. Every remedy happens outside
 * this tab (a terminal, a browser sign-in, an installer). Until the check passes,
 * coming back to the tab re-runs it, so returning from sign-in lands on the
 * green check instead of a second "Test now" the user has to know to press.
 */
export function EnvCheckRow({
  disabled,
  installUrl,
  knownResult = null,
  checking = false,
  onRun,
  onResult,
}: EnvCheckRowProps) {
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<EnvCheckResult | null>(null)
  const [fixing, setFixing] = useState(false)
  const [fixNote, setFixNote] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  // The app-level probe counts as "testing" only until this row has a verdict.
  const busy = running || (checking && !result)
  const busyRef = useRef(busy)
  const runRef = useRef(run)
  useEffect(() => {
    busyRef.current = busy
    runRef.current = run
  })

  async function run() {
    if (busyRef.current) return
    busyRef.current = true
    setRunning(true)
    setFixNote(null)
    try {
      const next = await onRun()
      setResult(next)
      onResult(next)
    } catch {
      const failed: EnvCheckResult = {
        ok: false,
        adapter: '',
        version: null,
        message: 'The environment check could not run. Try again.',
      }
      setResult(failed)
      onResult(failed)
    } finally {
      setRunning(false)
    }
  }

  // Adopt the app's verdict while this row has none of its own. Never replaces
  // a result the row produced itself.
  useEffect(() => {
    if (!knownResult || result || running) return
    setResult(knownResult)
    onResult(knownResult)
  }, [knownResult, result, running, onResult])

  // Re-test on return to the tab until the check passes. `blur`/`hidden` mark
  // when the user left; `focus`/`visible` (both fire on return — the first one
  // consumes the mark) re-run the probe if they were gone long enough.
  const passed = result?.ok === true
  useEffect(() => {
    if (disabled || passed) return
    let leftAt: number | null = document.visibilityState === 'hidden' ? Date.now() : null

    function onLeave() {
      if (leftAt === null) leftAt = Date.now()
    }
    function onReturn() {
      if (document.visibilityState !== 'visible' || leftAt === null) return
      const away = Date.now() - leftAt
      leftAt = null
      if (away >= AWAY_THRESHOLD_MS) void runRef.current()
    }
    function onVisibility() {
      if (document.visibilityState === 'hidden') onLeave()
      else onReturn()
    }

    window.addEventListener('blur', onLeave)
    window.addEventListener('focus', onReturn)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.removeEventListener('blur', onLeave)
      window.removeEventListener('focus', onReturn)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [disabled, passed])

  /** Ask the backend to open a terminal on the adapter's own sign-in command. */
  async function signIn() {
    setFixing(true)
    setFixNote(null)
    try {
      const res = await api.runRemedy(result?.adapter)
      setFixNote(res.message)
    } catch {
      setFixNote('Could not start the sign-in. Is the local backend running?')
    } finally {
      setFixing(false)
    }
  }

  async function copyCommand(command: string) {
    try {
      await navigator.clipboard.writeText(command)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setFixNote(`Copy failed — run this yourself: ${command}`)
    }
  }

  const showResult = Boolean(result && !busy)
  const succeeded = showResult && passed
  const remedy = result && !result.ok ? result.remedy : undefined
  const showInstallFallback = Boolean(result && !result.ok && !remedy && installUrl)
  // The backend's success line usually names the version already; don't repeat it.
  const versionSuffix =
    result?.ok && result.version && !result.message.includes(result.version)
      ? ` · v${result.version}`
      : ''

  return (
    <Card
      className={cn(
        'w-full px-6 py-[18px] transition-colors',
        succeeded && 'border-success/40 bg-success/10',
      )}
    >
      <div className="flex items-center justify-between gap-4">
        <div className="flex flex-1 flex-col gap-1.5">
          <p className="text-[16px] font-medium leading-6 text-foreground">
            Adapter environment check
          </p>
          <p className="text-sm leading-5 text-brand-muted">
            Runs a live probe that asks the adapter CLI to respond with hello
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={run} disabled={disabled || busy}>
          {busy ? (
            <>
              <Loader2 className="size-4 animate-spin" />
              Testing…
            </>
          ) : result ? (
            'Test again'
          ) : (
            'Test now'
          )}
        </Button>
      </div>

      {showResult && result ? (
        <div className="mt-3 flex flex-col gap-3">
          <div
            role="status"
            aria-live="polite"
            className={cn(
              'flex items-start gap-2 text-sm',
              result.ok ? 'font-medium text-success' : 'text-destructive',
            )}
          >
            {result.ok ? (
              <CheckCircle2 className="mt-0.5 size-4 shrink-0" aria-hidden />
            ) : (
              <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
            )}
            <p className="leading-5">
              {result.message}
              {versionSuffix}
              {showInstallFallback ? (
                <>
                  {' '}
                  <a
                    href={installUrl}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="text-brand-link underline underline-offset-2"
                  >
                    Install guide ↗
                  </a>
                </>
              ) : null}
            </p>
          </div>

          {remedy ? (
            <div className="flex flex-wrap items-center gap-2 pl-6">
              {remedy.kind === 'sign_in' && remedy.command ? (
                <>
                  <Button size="sm" onClick={signIn} disabled={fixing}>
                    {fixing ? (
                      <>
                        <Loader2 className="size-4 animate-spin" />
                        Opening…
                      </>
                    ) : (
                      <>
                        <LogIn className="size-4" />
                        {remedy.label}
                      </>
                    )}
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => copyCommand(remedy.command as string)}
                  >
                    <Copy className="size-4" />
                    {copied ? 'Copied' : remedy.command}
                  </Button>
                </>
              ) : remedy.url ? (
                <Button variant="secondary" size="sm" asChild>
                  <a href={remedy.url} target="_blank" rel="noreferrer noopener">
                    <ExternalLink className="size-4" />
                    {remedy.label}
                  </a>
                </Button>
              ) : null}
            </div>
          ) : null}

          {!result.ok ? (
            <p aria-live="polite" className="pl-6 text-sm leading-5 text-brand-muted">
              {fixNote ? `${fixNote} ` : null}
              When you come back to this tab, YuBen tests the connection again automatically.
            </p>
          ) : null}
        </div>
      ) : null}
    </Card>
  )
}
