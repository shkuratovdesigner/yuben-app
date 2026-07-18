import { useState } from 'react'
import { AlertCircle, CheckCircle2, Copy, ExternalLink, Loader2, LogIn } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { api } from '@/lib/api'
import type { EnvCheckResult } from '@/lib/types'

interface EnvCheckRowProps {
  /** No adapter picked yet → nothing to probe. */
  disabled: boolean
  /** Fallback install page, used only when the backend sends no remedy. */
  installUrl?: string
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
 */
export function EnvCheckRow({ disabled, installUrl, onRun, onResult }: EnvCheckRowProps) {
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<EnvCheckResult | null>(null)
  const [fixing, setFixing] = useState(false)
  const [fixNote, setFixNote] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  async function run() {
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

  const remedy = result && !result.ok ? result.remedy : undefined
  const showInstallFallback = Boolean(result && !result.ok && !remedy && installUrl)

  return (
    <Card className="w-full px-6 py-[18px]">
      <div className="flex items-center justify-between gap-4">
        <div className="flex flex-1 flex-col gap-1.5">
          <p className="text-[16px] font-medium leading-6 text-foreground">
            Adapter environment check
          </p>
          <p className="text-sm leading-5 text-brand-muted">
            Runs a live probe that asks the adapter CLI to respond with hello
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={run} disabled={disabled || running}>
          {running ? (
            <>
              <Loader2 className="size-4 animate-spin" />
              Testing…
            </>
          ) : (
            'Test now'
          )}
        </Button>
      </div>

      {result && !running ? (
        <div className="mt-3 flex flex-col gap-3">
          <div className="flex items-start gap-2 text-sm">
            {result.ok ? (
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-brand-selected" />
            ) : (
              <AlertCircle className="mt-0.5 size-4 shrink-0 text-destructive" />
            )}
            <p className={cn('leading-5', result.ok ? 'text-foreground' : 'text-destructive')}>
              {result.message}
              {result.ok && result.version ? (
                <span className="text-brand-muted"> · v{result.version}</span>
              ) : null}
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

          {fixNote ? (
            <p role="status" aria-live="polite" className="pl-6 text-sm leading-5 text-brand-muted">
              {fixNote}
            </p>
          ) : null}
        </div>
      ) : null}
    </Card>
  )
}
