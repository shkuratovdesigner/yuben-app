import { useState } from 'react'
import { AlertCircle, CheckCircle2, Loader2 } from 'lucide-react'

import type { EnvCheckResult } from '@/lib/types'
import { useConfig } from '@/app/stores/config-store'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { KeyInput } from '@/components/ui/key-input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

// Where a key comes from — referenced by the key-field helper text.
const CONSOLE_KEYS_URL = 'https://console.anthropic.com/settings/keys'

interface ApiKeyConnectProps {
  /** Bubble the outcome up so the screen can gate Continue on a passing test. */
  onResult: (result: EnvCheckResult) => void
}

/**
 * F1 — the Anthropic API connect block (Phase 4). Replaces the CLI env-check for
 * the "Anthropic API (key)" path: paste a key, click Test, and a cheap real
 * Messages "reply hello" ping turns it green — no terminal, no `claude login`.
 *
 * SECRET RULE: the key lives only in local component state and travels solely
 * through storeKey()'s POST body (write-only, provider="anthropic"). It's masked
 * (KeyInput), never logged, and never placed in a URL. The verdict is whatever
 * the backend's live probe returns — no fact is invented here.
 */
export function ApiKeyConnect({ onResult }: ApiKeyConnectProps) {
  const { storeKey, runEnvCheck } = useConfig()

  const [key, setKey] = useState('')
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<EnvCheckResult | null>(null)

  const trimmed = key.trim()
  const canTest = trimmed.length > 0 && !testing

  /** A local "reset the gate" verdict when the key text changes after a test. */
  function reset(): EnvCheckResult {
    return { ok: false, adapter: 'anthropic-api', version: null, message: '' }
  }

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    setKey(e.target.value)
    if (result) {
      setResult(null)
      onResult(reset()) // any prior pass is stale once the key changes
    }
  }

  async function handleTest() {
    if (!canTest) return
    setTesting(true)
    setResult(null)
    try {
      // Store write-only first (the backend probe reads the stored key), then ping.
      const stored = await storeKey(trimmed, 'anthropic')
      if (!stored.ok) {
        const failed: EnvCheckResult = {
          ok: false,
          adapter: 'anthropic-api',
          version: null,
          message: 'Could not store the key locally. Is the backend running?',
        }
        setResult(failed)
        onResult(failed)
        return
      }
      const next = await runEnvCheck()
      setResult(next)
      onResult(next)
    } catch {
      const failed: EnvCheckResult = {
        ok: false,
        adapter: 'anthropic-api',
        version: null,
        message: 'The connection test could not run. Is the local backend running?',
      }
      setResult(failed)
      onResult(failed)
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="flex w-full flex-col gap-4">
      {/* Anthropic key field (masked, local-only) */}
      <div className="flex w-full flex-col gap-3">
        <Label htmlFor="anthropic-key">Anthropic API key</Label>
        <KeyInput
          id="anthropic-key"
          placeholder="sk-ant-…"
          value={key}
          onChange={handleChange}
          aria-describedby="anthropic-key-helper"
        />
        <p id="anthropic-key-helper" className="text-sm leading-5 text-brand-muted">
          Stored only on your machine and used to run the model — no terminal needed. Create one in
          the{' '}
          <a
            href={CONSOLE_KEYS_URL}
            target="_blank"
            rel="noreferrer noopener"
            className="text-brand-link underline underline-offset-2"
          >
            Anthropic Console
          </a>
          .
        </p>
      </div>

      {/* Connect / live-ping row */}
      <Card className="w-full px-6 py-[18px]">
        <div className="flex items-center justify-between gap-4">
          <div className="flex flex-1 flex-col gap-1.5">
            <p className="text-[16px] font-medium leading-6 text-foreground">Connect the model</p>
            <p className="text-sm leading-5 text-brand-muted">
              Runs one quick message to confirm your key works.
            </p>
            {(testing || result) && (
              <p
                role="status"
                aria-live="polite"
                className={cn(
                  'mt-0.5 flex items-center gap-1.5 text-sm leading-5',
                  testing
                    ? 'text-brand-muted'
                    : result?.ok
                      ? 'text-brand-selected'
                      : 'text-destructive',
                )}
              >
                {testing ? (
                  <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden />
                ) : result?.ok ? (
                  <CheckCircle2 className="size-4 shrink-0" aria-hidden />
                ) : (
                  <AlertCircle className="size-4 shrink-0" aria-hidden />
                )}
                <span>
                  {testing ? 'Testing your key…' : result?.message}
                  {result?.ok && result.version ? (
                    <span className="text-brand-muted"> · SDK v{result.version}</span>
                  ) : null}
                </span>
              </p>
            )}
          </div>
          <Button variant="secondary" size="sm" onClick={handleTest} disabled={!canTest}>
            {testing ? 'Testing…' : 'Test now'}
          </Button>
        </div>
      </Card>
    </div>
  )
}
