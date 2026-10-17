/**
 * Onboarding — Step 2: how to get a YouTube key, + the key field (Figma 16:912).
 *
 * Walks the user through obtaining a free YouTube Data API v3 key in Google
 * Cloud Console, then captures it. Built into the F8 app shell:
 *   • useConfig() → storeKey (write-only), runKeyTest, saveConfig.
 *   • useNavigate() → home ("/") once onboarding is marked complete.
 *
 * COPY NOTE: the step rows used to restate how YuBen works (PRD §6 / BUILD_PLAN
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
import { useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { CheckCircle2, Info, Loader2, XCircle } from 'lucide-react'

import type { KeyTestResult } from '@/lib/types'
import { useConfig } from '@/app/stores/config-store'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { KeyInput } from '@/components/ui/key-input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'
import stepNewProject from '@/assets/key-guide/step-1-new-project.webp'
import stepEnableApi from '@/assets/key-guide/step-2-enable-api.webp'
import stepCreateKey from '@/assets/key-guide/step-3-create-key.webp'
import stepRestrictCreate from '@/assets/key-guide/step-4-restrict-create.webp'
import stepCopyKey from '@/assets/key-guide/step-5-copy-key.webp'

import { ImageLightbox } from './ImageLightbox'

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

// The acquisition steps, each with an annotated console screenshot (red outline
// and arrow on the control to click). Captured 2026-10-17 from Google Cloud's
// current flow, where the API restriction is chosen while creating the key, not
// after. Shot at high pixel density and exported at 2400×1500 so the zoom overlay
// stays sharp. Step 1's project names and IDs are blurred, and step 5 shows a
// blurred placeholder, never a real key. Source frames live in the Paper file
// "YuBen – YouTube key guide"; re-export there when the console moves.
// `body` is a node so each row can link straight to the console screen it describes.
const STEPS: { title: string; body: ReactNode; image: string; alt: string }[] = [
  {
    title: 'Create a Google Cloud project',
    body: (
      <>
        In <ConsoleLink href={GCP_NEW_PROJECT_URL}>Google Cloud Console</ConsoleLink>, open the
        project menu and choose <Ui>New project</Ui> — or pick one you already have. No billing
        account needed.
      </>
    ),
    image: stepNewProject,
    alt: 'Google Cloud Console with the project menu and its New project button highlighted. Project names are blurred.',
  },
  {
    title: 'Enable the YouTube Data API',
    body: (
      <>
        Open <ConsoleLink href={GCP_ENABLE_API_URL}>YouTube Data API v3</ConsoleLink> in the API
        Library and press <Ui>Enable</Ui>.
      </>
    ),
    image: stepEnableApi,
    alt: 'YouTube Data API v3 page with the Enable button highlighted.',
  },
  {
    title: 'Create an API key',
    body: (
      <>
        In <ConsoleLink href={GOOGLE_CONSOLE_URL}>APIs &amp; Services → Credentials</ConsoleLink>,
        open <Ui>Create credentials</Ui> and choose <Ui>API key</Ui>.
      </>
    ),
    image: stepCreateKey,
    alt: 'Credentials page with the Create credentials menu open and API key highlighted.',
  },
  {
    title: 'Limit it to YouTube, then create',
    body: (
      <>
        Under <Ui>Select API restrictions</Ui>, tick <Ui>YouTube Data API v3</Ui>, then press{' '}
        <Ui>Create</Ui>. The key then can’t be spent on anything else.
      </>
    ),
    image: stepRestrictCreate,
    alt: 'Create API key panel with the API restrictions field and the Create button highlighted.',
  },
  {
    title: 'Copy the key and paste it below',
    body: (
      <>
        Copy the new key — every Google key starts with{' '}
        <span className="font-mono text-foreground">AIza</span>. You get 10,000 units a day free; a
        YuBen run costs roughly 1.4k.
      </>
    ),
    image: stepCopyKey,
    alt: 'API key created panel with the copy button highlighted. The key itself is blurred.',
  },
]

export default function OnboardingSetup() {
  const navigate = useNavigate()
  const { config, storeKey, runKeyTest, saveConfig } = useConfig()

  const [key, setKey] = useState('')
  // Last value we successfully wrote via storeKey — lets us avoid re-storing an
  // unchanged key before a test / finish. Never the value read back from a server.
  const [storedKey, setStoredKey] = useState<string | null>(null)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<KeyTestResult | null>(null)
  const [finishing, setFinishing] = useState(false)
  const [finishError, setFinishError] = useState<string | null>(null)

  // A key is already stored (presence flag only — the value never comes back).
  // Then the screen is about THAT key: test it, keep it, or replace it. It used
  // to show the four acquisition steps and an empty field regardless, which read
  // as "your key is gone, connect it again".
  const keyPresent = config?.youtube_key_present === true
  const [replacing, setReplacing] = useState(false)
  // Index of the step screenshot open in the zoom overlay, if any.
  const [zoomedStep, setZoomedStep] = useState<number | null>(null)
  const closeZoom = useCallback(() => setZoomedStep(null), [])
  const usingSaved = keyPresent && !replacing

  const trimmedKey = key.trim()
  const isValidFormat = KEY_FORMAT.test(trimmedKey)
  const canTest = trimmedKey.length > 0 && !testing
  // The key must actually PASS, not merely look like a key. Format alone let a
  // rejected key finish onboarding, after which every research run failed with
  // no explanation — and step 1 already gates Continue on its env-check passing,
  // so gating here keeps both steps honest. Editing the key clears testResult
  // (handleKeyChange), which correctly re-arms this gate.
  const canFinish = (usingSaved || isValidFormat) && testResult?.ok === true && !finishing
  const passed = !testing && testResult?.ok === true

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

  /** Test the key already in the store — nothing typed, nothing re-sent. */
  const testSaved = useCallback(async () => {
    setTesting(true)
    setTestResult(null)
    try {
      setTestResult(await runKeyTest())
    } catch {
      setTestResult({
        ok: false,
        message: 'Could not run the key test. Check that the local backend is running.',
      })
    } finally {
      setTesting(false)
    }
  }, [runKeyTest])

  // A saved key is checked on arrival (and on returning to it from "Replace"),
  // so the screen opens on a verdict rather than on a button to press.
  useEffect(() => {
    if (usingSaved) void testSaved()
  }, [usingSaved, testSaved])

  function startReplacing() {
    setReplacing(true)
    setTestResult(null)
    setFinishError(null)
  }

  /** Back to the saved key — only offered while nothing new has been stored. */
  function cancelReplacing() {
    setReplacing(false)
    setKey('')
    setFinishError(null)
  }

  async function handleFinish() {
    if (!canFinish) return
    setFinishing(true)
    setFinishError(null)
    try {
      if (!usingSaved) await ensureStored()
      await saveConfig({ onboarding_complete: true })
      navigate('/')
    } catch {
      setFinishError('Could not save your setup. Please try again.')
      setFinishing(false)
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-[664px] flex-1 flex-col items-center justify-center gap-14 py-10">
      {/* Heading + sub (§6 copy) */}
      <header className="flex w-full max-w-[521px] flex-col items-center gap-4 text-center">
        <h1 className="font-display text-[40px] leading-[1.1] text-foreground">
          {usingSaved ? 'Your YouTube key' : 'Set up your YouTube key'}
        </h1>
        <p className="text-base leading-[1.3] text-brand-muted">
          {usingSaved
            ? 'A key is already saved on this machine, so there’s nothing to set up. Replace it only if you want to use a different one.'
            : 'YuBen reads video and channel stats straight from YouTube, so it needs your own free API key. Here’s where to get one.'}
        </p>
      </header>

      {usingSaved ? (
        <Card
          className={cn(
            'w-full px-6 py-[18px] transition-colors',
            passed && 'border-success/40 bg-success/10',
          )}
        >
          <div className="flex items-center justify-between gap-4">
            <div className="flex flex-1 flex-col gap-1.5">
              <p className="text-base font-medium leading-6 text-foreground">Saved YouTube key</p>
              <p className="text-sm leading-5 text-brand-muted">
                Stored only on this machine. One quick call checks that YouTube still accepts it.
              </p>
              <KeyTestStatus testing={testing} result={testResult} />
            </div>
            {/* A pass is final — only a failure offers another try. */}
            {!passed ? (
              <Button variant="secondary" size="sm" onClick={testSaved} disabled={testing}>
                {testing ? 'Testing…' : 'Test again'}
              </Button>
            ) : null}
          </div>
          <Button
            variant="link"
            onClick={startReplacing}
            className="mt-2 h-auto p-0 text-sm font-normal"
          >
            Replace with a new key
          </Button>
        </Card>
      ) : null}

      {!usingSaved ? (
        <>
          {/* Numbered step cards (Figma 16:918), each with its annotated screenshot.
              Clicking a screenshot zooms it in an overlay; clicking outside closes it. */}
          <div className="flex w-full flex-col gap-3">
            {STEPS.map((step, i) => (
              <Card key={step.title} className="w-full px-6 pt-4 pb-5">
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
                <button
                  type="button"
                  onClick={() => setZoomedStep(i)}
                  aria-label={`Zoom screenshot for step ${i + 1}`}
                  className="mt-4 block w-full cursor-zoom-in overflow-hidden rounded-[10px] border border-border outline-none transition-opacity hover:opacity-90 focus-visible:ring-2 focus-visible:ring-ring/40"
                >
                  <img
                    src={step.image}
                    alt={step.alt}
                    width={2400}
                    height={1500}
                    loading="lazy"
                    className="block h-auto w-full"
                  />
                </button>
              </Card>
            ))}
          </div>
          {zoomedStep !== null ? (
            <ImageLightbox
              src={STEPS[zoomedStep].image}
              alt={STEPS[zoomedStep].alt}
              onClose={closeZoom}
            />
          ) : null}

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
          <Card
            className={cn(
              'w-full px-6 py-[18px] transition-colors',
              passed && 'border-success/40 bg-success/10',
            )}
          >
            <div className="flex items-center justify-between gap-4">
              <div className="flex flex-1 flex-col gap-1.5">
                <p className="text-base font-medium leading-6 text-foreground">Test your key</p>
                <p className="text-sm leading-5 text-brand-muted">
                  Runs one quick call to confirm YouTube accepts it.
                </p>
                <KeyTestStatus testing={testing} result={testResult} />
              </div>
              {/* Hidden once the key passes; editing the key clears the result and brings it back. */}
              {!passed ? (
                <Button variant="secondary" size="sm" onClick={handleTest} disabled={!canTest}>
                  {testing ? 'Testing…' : testResult ? 'Test again' : 'Test now'}
                </Button>
              ) : null}
            </div>
            {keyPresent && storedKey === null ? (
              <Button
                variant="link"
                onClick={cancelReplacing}
                className="mt-2 h-auto p-0 text-sm font-normal"
              >
                Keep the saved key instead
              </Button>
            ) : null}
          </Card>
        </>
      ) : null}

      {/* Finish (Figma 27:459) — enabled once a key (saved or new) passes its test */}
      <div className="flex flex-col items-center gap-3">
        <Button onClick={handleFinish} disabled={!canFinish}>
          {finishing ? 'Finishing…' : 'Finish Setup'}
        </Button>
        {!canFinish && !finishing && !testing && !(usingSaved && !testResult) ? (
          <p className="flex items-center gap-1.5 text-center text-sm leading-5 text-warning">
            <Info className="size-4 shrink-0" aria-hidden />
            {usingSaved
              ? 'YouTube rejected the saved key — test again or replace it to continue.'
              : !isValidFormat
                ? 'Enter your YouTube key to continue.'
                : testResult && !testResult.ok
                  ? 'That key was rejected — fix it and test again.'
                  : 'Test your key before you continue.'}
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

/** The key test's live verdict line — shared by the saved-key and new-key cards. */
function KeyTestStatus({ testing, result }: { testing: boolean; result: KeyTestResult | null }) {
  if (!testing && !result) return null
  return (
    <p
      role="status"
      aria-live="polite"
      className={cn(
        'mt-0.5 flex items-center gap-1.5 text-sm leading-5',
        testing ? 'text-brand-muted' : result?.ok ? 'font-medium text-success' : 'text-destructive',
      )}
    >
      {testing ? (
        <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden />
      ) : result?.ok ? (
        <CheckCircle2 className="size-4 shrink-0" aria-hidden />
      ) : (
        <XCircle className="size-4 shrink-0" aria-hidden />
      )}
      <span>{testing ? 'Testing your key…' : result?.message}</span>
    </p>
  )
}
