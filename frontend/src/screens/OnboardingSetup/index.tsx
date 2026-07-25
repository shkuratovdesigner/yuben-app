/**
 * Onboarding — Step 2: how to get a YouTube key, + the key field (Figma 16:912).
 *
 * Walks the user through obtaining a free YouTube Data API v3 key in Google
 * Cloud Console, then captures it. Built into the F8 app shell:
 *   • useConfig() → storeKey (write-only), runKeyTest, saveConfig.
 *   • useNavigate() → home ("/") once onboarding is marked complete.
 *
 * COPY NOTE: the four rows used to restate how YuBen works (PRD §6 / BUILD_PLAN
 * F2). That belonged in the README, not in the one screen standing between the
 * user and a working key — so they're now the actual acquisition steps. PRD §4.2
 * and §6 were updated to match; the "Detailed guide" link (PRD §10 Q1) is gone
 * because these steps ARE the guide.
 *
 * SECRET RULE (non-negotiable): the key lives only in local component state and
 * travels solely through storeKey()/runKeyTest() POST bodies (handled by the
 * shell). It is masked in the UI (KeyInput), never logged, and never placed in a
 * URL or query string. No fact/number here is invented — the key test verdict is
 * whatever the backend returns.
 */
import { useState } from 'react'
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { CheckCircle2, Loader2, XCircle } from 'lucide-react'

import type { KeyTestResult } from '@/lib/types'
import { useConfig } from '@/app/stores/config-store'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { KeyInput } from '@/components/ui/key-input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

// Deep links into Google Cloud Console, one per step, so each row lands the user
// exactly where the action happens instead of on a console home page.
const GCP_NEW_PROJECT_URL = 'https://console.cloud.google.com/projectcreate'
const GCP_ENABLE_API_URL = 'https://console.cloud.google.com/apis/library/youtube.googleapis.com'
// Where a free key comes from — also referenced by the key-field helper text.
const GOOGLE_CONSOLE_URL = 'https://console.cloud.google.com/apis/credentials'

// Google API keys are "AIza" + 35 chars of [A-Za-z0-9_-] (39 total). Used only
// as a basic format gate for enabling Finish Setup; the real check is the test.
const KEY_FORMAT = /^AIza[0-9A-Za-z_-]{35}$/

/** External link into the console — same treatment as the key-field helper link. */
function ConsoleLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      className="text-brand-link underline underline-offset-2"
    >
      {children}
    </a>
  )
}

/** A console menu path / button name, lifted out of the muted body text. */
function Ui({ children }: { children: ReactNode }) {
  return <span className="font-medium text-foreground">{children}</span>
}

// The four acquisition steps. `body` is a node so each row can link straight to
// the console screen it describes.
const STEPS: { title: string; body: ReactNode }[] = [
  {
    title: 'Create a Google Cloud project',
    body: (
      <>
        Open <ConsoleLink href={GCP_NEW_PROJECT_URL}>Google Cloud Console</ConsoleLink> and create a
        project — or pick one you already have. The YouTube Data API needs no billing account.
      </>
    ),
  },
  {
    title: 'Enable the YouTube Data API',
    body: (
      <>
        Go to <Ui>APIs &amp; Services → Library</Ui>, open{' '}
        <ConsoleLink href={GCP_ENABLE_API_URL}>YouTube Data API v3</ConsoleLink>, and press{' '}
        <Ui>Enable</Ui>.
      </>
    ),
  },
  {
    title: 'Create an API key',
    body: (
      <>
        In <ConsoleLink href={GOOGLE_CONSOLE_URL}>APIs &amp; Services → Credentials</ConsoleLink>,
        choose <Ui>Create credentials → API key</Ui>, then copy it. Every Google key starts with{' '}
        <span className="font-mono text-foreground">AIza</span>.
      </>
    ),
  },
  {
    title: 'Restrict it, then paste it below',
    body: (
      <>
        Optional but worth it: edit the key and, under <Ui>API restrictions</Ui>, limit it to{' '}
        <Ui>YouTube Data API v3</Ui> so it can’t be spent on anything else. You get 10,000 units a
        day free — a YuBen run costs roughly 1.4k.
      </>
    ),
  },
]

export default function OnboardingSetup() {
  const navigate = useNavigate()
  const { storeKey, runKeyTest, saveConfig } = useConfig()

  const [key, setKey] = useState('')
  // Last value we successfully wrote via storeKey — lets us avoid re-storing an
  // unchanged key before a test / finish. Never the value read back from a server.
  const [storedKey, setStoredKey] = useState<string | null>(null)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<KeyTestResult | null>(null)
  const [finishing, setFinishing] = useState(false)
  const [finishError, setFinishError] = useState<string | null>(null)

  const trimmedKey = key.trim()
  const isValidFormat = KEY_FORMAT.test(trimmedKey)
  const canTest = trimmedKey.length > 0 && !testing
  // The key must actually PASS, not merely look like a key. Format alone let a
  // rejected key finish onboarding, after which every research run failed with
  // no explanation — and step 1 already gates Continue on its env-check passing,
  // so gating here keeps both steps honest. Editing the key clears testResult
  // (handleKeyChange), which correctly re-arms this gate.
  const canFinish = isValidFormat && testResult?.ok === true && !finishing

  /** Write the current key locally (write-only) if it changed. Returns ok. */
  async function ensureStored(): Promise<boolean> {
    if (!trimmedKey) return false
    if (trimmedKey === storedKey) return true
    const res = await storeKey(trimmedKey)
    if (res.ok) setStoredKey(trimmedKey)
    return res.ok
  }

  function handleKeyChange(e: React.ChangeEvent<HTMLInputElement>) {
    setKey(e.target.value)
    // Any prior verdict is stale once the key text changes.
    setTestResult(null)
    setFinishError(null)
  }

  // Persist on blur once it looks like a key — "on entering a key, store it".
  function handleKeyBlur() {
    if (isValidFormat && trimmedKey !== storedKey) void ensureStored()
  }

  async function handleTest() {
    if (!canTest) return
    setTesting(true)
    setTestResult(null)
    try {
      await ensureStored()
      setTestResult(await runKeyTest())
    } catch {
      setTestResult({
        ok: false,
        message: 'Could not run the key test. Check that the local backend is running.',
      })
    } finally {
      setTesting(false)
    }
  }

  async function handleFinish() {
    if (!canFinish) return
    setFinishing(true)
    setFinishError(null)
    try {
      await ensureStored()
      await saveConfig({ onboarding_complete: true })
      navigate('/')
    } catch {
      setFinishError('Could not save your setup. Please try again.')
      setFinishing(false)
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-[664px] flex-col items-center gap-14 py-10">
      {/* Heading + sub (§6 copy) */}
      <header className="flex w-full max-w-[521px] flex-col items-center gap-4 text-center">
        <h1 className="font-display text-[40px] leading-[1.1] text-foreground">
          Set up your YouTube key
        </h1>
        <p className="text-base leading-[1.3] text-brand-muted">
          {'YuBen reads video and channel stats straight from YouTube, so it needs your own free API key. Here’s where to get one.'}
        </p>
      </header>

      {/* Four numbered step cards (Figma 16:918) */}
      <div className="flex w-full flex-col gap-3">
        {STEPS.map((step, i) => (
          <Card key={step.title} className="w-full px-6 pt-4 pb-3">
            <div className="flex flex-col gap-1.5">
              <div className="flex items-baseline gap-4">
                <span className="text-[17px] font-medium leading-6 tabular-nums text-foreground">
                  {i + 1}
                </span>
                <span className="text-[17px] font-medium leading-6 text-foreground">
                  {step.title}
                </span>
              </div>
              <p className="text-sm leading-5 text-brand-muted">{step.body}</p>
            </div>
          </Card>
        ))}
      </div>

      {/* Private YouTube Key field (masked, local-only) */}
      <div className="flex w-full flex-col gap-3">
        <Label htmlFor="youtube-key">Private YouTube Key</Label>
        <KeyInput
          id="youtube-key"
          placeholder="AIza…"
          value={key}
          onChange={handleKeyChange}
          onBlur={handleKeyBlur}
          aria-describedby="youtube-key-helper"
        />
        <p id="youtube-key-helper" className="text-sm leading-5 text-brand-muted">
          Stored only on your machine and used to fetch video data. Get one free in{' '}
          <a
            href={GOOGLE_CONSOLE_URL}
            target="_blank"
            rel="noreferrer noopener"
            className="text-brand-link underline underline-offset-2"
          >
            Google Cloud Console
          </a>
          .
        </p>
      </div>

      {/* Key test row (Figma 16:935) */}
      <Card className="w-full px-6 py-[18px]">
        <div className="flex items-center justify-between gap-4">
          <div className="flex flex-1 flex-col gap-1.5">
            <p className="text-base font-medium leading-6 text-foreground">Test your key</p>
            <p className="text-sm leading-5 text-brand-muted">
              Runs one quick call to confirm YouTube accepts it.
            </p>
            {(testing || testResult) && (
              <p
                role="status"
                aria-live="polite"
                className={cn(
                  'mt-0.5 flex items-center gap-1.5 text-sm leading-5',
                  testing
                    ? 'text-brand-muted'
                    : testResult?.ok
                      ? 'text-brand-selected'
                      : 'text-destructive',
                )}
              >
                {testing ? (
                  <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden />
                ) : testResult?.ok ? (
                  <CheckCircle2 className="size-4 shrink-0" aria-hidden />
                ) : (
                  <XCircle className="size-4 shrink-0" aria-hidden />
                )}
                <span>{testing ? 'Testing your key…' : testResult?.message}</span>
              </p>
            )}
          </div>
          <Button variant="secondary" size="sm" onClick={handleTest} disabled={!canTest}>
            {testing ? 'Testing…' : 'Test now'}
          </Button>
        </div>
      </Card>

      {/* Finish (Figma 27:459) — enabled once the key is a valid format */}
      <div className="flex flex-col items-center gap-3">
        <Button onClick={handleFinish} disabled={!canFinish}>
          {finishing ? 'Finishing…' : 'Finish Setup'}
        </Button>
        {!canFinish && !finishing ? (
          <p className="text-center text-[13px] text-brand-muted">
            {!isValidFormat
              ? 'Enter your YouTube key to continue.'
              : testResult && !testResult.ok
                ? 'That key was rejected — fix it and test again.'
                : 'Test your key to continue.'}
          </p>
        ) : null}
        {finishError && (
          <p role="alert" className="text-sm text-destructive">
            {finishError}
          </p>
        )}
      </div>
    </div>
  )
}
