import { useState } from 'react'
import { AlertCircle, CheckCircle2, Loader2 } from 'lucide-react'

import type { EnvCheckResult, KeyProvider } from '@/lib/types'
import { useConfig } from '@/app/stores/config-store'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { KeyInput } from '@/components/ui/key-input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

interface ApiKeyConnectProps {
  /** Adapter this key belongs to — only used to shape the local reset verdict. */
  adapterId: string
  /** Which secret the backend should write (write-only POST body). */
  provider: KeyProvider
  /** Field label, e.g. "OpenAI API key". */
  label: string
  /** Masked-input placeholder hinting the key's shape, e.g. "sk-…". */
  placeholder: string
  /** Where to create a key, and what to call that place in the helper text. */
  consoleUrl: string
  consoleName: string
  /** Bubble the outcome up so the screen can gate Continue on a passing test. */
  onResult: (result: EnvCheckResult) => void
}

/**
 * F1 — the key-paste connect block, for every API-based adapter.
 *
 * Replaces the CLI env-check on the key paths (Anthropic, OpenAI, OpenRouter):
 * paste a key, click Test, and a cheap real "reply hello" call turns it green —
 * no terminal, no `claude login`. Originally Anthropic-only; the provider is now
 * a prop because all these adapters connect identically and only the label,
 * placeholder and console link differ.
 *
 * SECRET RULE: the key lives only in local component state and travels solely
 * through storeKey()'s POST body (write-only). It's masked (KeyInput), never
 * logged, and never placed in a URL. The verdict is whatever the backend's live
 * probe returns — no fact is invented here.
 */
export function ApiKeyConnect({
  adapterId,
  provider,
  label,
  placeholder,
  consoleUrl,
  consoleName,
  onResult,
}: ApiKeyConnectProps) {
  const { storeKey, runEnvCheck } = useConfig()
  const fieldId = `${provider}-key`

  const [key, setKey] = useState('')
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<EnvCheckResult | null>(null)

  const trimmed = key.trim()
  const canTest = trimmed.length > 0 && !testing

  /** A local "reset the gate" verdict when the key text changes after a test. */
  function reset(): EnvCheckResult {
    return { ok: false, adapter: adapterId, version: null, message: '' }
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
      const stored = await storeKey(trimmed, provider)
      if (!stored.ok) {
        const failed: EnvCheckResult = {
          ok: false,
          adapter: adapterId,
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
      {/* Provider key field (masked, local-only) */}
      <div className="flex w-full flex-col gap-3">
        <Label htmlFor={fieldId}>{label}</Label>
        <KeyInput
          id={fieldId}
          placeholder={placeholder}
          value={key}
          onChange={handleChange}
          aria-describedby={`${fieldId}-helper`}
        />
        <p id={`${fieldId}-helper`} className="text-sm leading-5 text-brand-muted">
          Stored only on your machine and used to run the model — no terminal needed. Create one in{' '}
          <a
            href={consoleUrl}
            target="_blank"
            rel="noreferrer noopener"
            className="text-brand-link underline underline-offset-2"
          >
            {consoleName}
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
