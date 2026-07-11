import { useState } from 'react'
import { AlertCircle, CheckCircle2, Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { EnvCheckResult } from '@/lib/types'

interface EnvCheckRowProps {
  /** No adapter picked yet → nothing to probe. */
  disabled: boolean
  /** Optional install page for the selected adapter (shown on a failed check). */
  installUrl?: string
  /** Live probe: `useConfig().runEnvCheck` — asks the CLI to respond "hello". */
  onRun: () => Promise<EnvCheckResult>
  /** Bubble the outcome up so the screen can gate Continue on a passing check. */
  onResult: (result: EnvCheckResult) => void
}

/**
 * Adapter environment-check row (Figma 13:474). Resting #fbfbfb card with a
 * "Test now" tonal button that runs the real probe and renders its pass/fail
 * result verbatim (CLI found + responded + version, or a missing-CLI hint).
 */
export function EnvCheckRow({ disabled, installUrl, onRun, onResult }: EnvCheckRowProps) {
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<EnvCheckResult | null>(null)

  async function run() {
    setRunning(true)
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
        <div className="mt-3 flex items-start gap-2 text-sm">
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
            {!result.ok && installUrl ? (
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
      ) : null}
    </Card>
  )
}
