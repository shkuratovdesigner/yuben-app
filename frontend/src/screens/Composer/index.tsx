/**
 * F3 — Composer (home screen). Figma 27:529 (resting) + 29:135 (enabled send),
 * file OG4eN9FgW3gnu88CRQRMGt. PRD §4.3 / §4.6 / §6, CONTRACTS §2.
 *
 * Builds a ResearchRequest from the topic + filters and hands it to the run
 * store: `const runId = await startRun(req); navigate('/run/' + runId)`. It
 * renders NO video data — it only constructs the request (TRUST RULE). Model +
 * adapter come from useConfig(); the footer's history entries key off
 * useHistory().items.length.
 */
import { Fragment, useCallback, useState, type KeyboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowUp } from 'lucide-react'

import { useConfig } from '@/app/stores/config-store'
import { useHistory } from '@/app/stores/history-store'
import { useStartRun } from '@/app/stores/run-store'
import { Card } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { Format, Outperformance, ResearchRequest, UploadDate } from '@/lib/types'
import { cn } from '@/lib/utils'

import { ComposerFooter } from './ComposerFooter'
import { CostHint } from './CostHint'
import {
  COMPOSER_SELECT_TRIGGER,
  FORMAT_DEFAULT,
  FORMAT_OPTIONS,
  MAX_RESULTS_DEFAULT,
  OUTPERFORMANCE_DEFAULT,
  OUTPERFORMANCE_OPTIONS,
  UPLOAD_DATE_DEFAULT,
  UPLOAD_DATE_OPTIONS,
} from './options'

export default function Composer() {
  const startRun = useStartRun()
  const { config, adapters, saveConfig } = useConfig()
  const { items } = useHistory()
  const navigate = useNavigate()

  // Composer state — filters hold their ENUM values directly (see options.ts).
  const [query, setQuery] = useState('')
  const [format, setFormat] = useState<Format>(FORMAT_DEFAULT)
  const [uploadDate, setUploadDate] = useState<UploadDate>(UPLOAD_DATE_DEFAULT)
  const [outperformance, setOutperformance] = useState<Outperformance>(OUTPERFORMANCE_DEFAULT)
  const [analyzeTitles, setAnalyzeTitles] = useState(false)
  const [analyzeScripts, setAnalyzeScripts] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const trimmed = query.trim()
  const canSend = trimmed.length > 0 && !submitting

  /** Assemble the ResearchRequest (CONTRACTS §2). Model/adapter from config. */
  const buildRequest = useCallback(
    (): ResearchRequest => ({
      schema_version: '1.0',
      query: trimmed,
      format,
      upload_date: uploadDate,
      outperformance,
      analyze_titles: analyzeTitles,
      analyze_scripts: analyzeScripts,
      model: {
        adapter: config?.adapter ?? 'claude-code',
        model: config?.model ?? 'default',
      },
      max_results: MAX_RESULTS_DEFAULT,
    }),
    [trimmed, format, uploadDate, outperformance, analyzeTitles, analyzeScripts, config],
  )

  const handleSubmit = useCallback(
    async (e: { preventDefault: () => void }) => {
      e.preventDefault()
      if (!canSend) return
      setSubmitting(true)
      setError(null)
      try {
        const runId = await startRun(buildRequest())
        navigate(`/run/${runId}`)
      } catch (err) {
        setSubmitting(false)
        setError(err instanceof Error ? err.message : 'Could not start the run. Try again.')
      }
    },
    [canSend, startRun, buildRequest, navigate],
  )

  const onTextareaKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter inserts a newline (the input is multiline); ⌘/Ctrl+Enter sends.
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault()
      e.currentTarget.form?.requestSubmit()
    }
  }

  const handleModelChange = useCallback(
    (model: string) => {
      void saveConfig({ model }).catch(() => {})
    },
    [saveConfig],
  )

  return (
    <div className="mx-auto flex min-h-[calc(100vh-8rem)] w-full max-w-[800px] flex-col">
      <div className="flex flex-1 items-center justify-center">
        <div className="flex w-full flex-col items-center gap-12">
          {/* Header — serif H1 + sub (Figma 27:550/27:551/27:552). */}
          <header className="flex w-full flex-col items-center gap-2 text-center">
            <h1 className="font-display text-[40px] leading-[1.1] text-foreground">
              What content are you searching for?
            </h1>
            <p className="text-[14px] leading-[1.4] text-brand-muted">
              Type a topic to find the videos already outperforming their channels — and why.
            </p>
          </header>

          {/* Composer panel (Figma 27:643 "Inputs Outline"). */}
          <form onSubmit={handleSubmit} className="w-full">
            <Card className="flex w-full flex-col gap-3 overflow-hidden border-border bg-muted px-4 pb-3 pt-4 transition-colors focus-within:border-brand-selected/50">
              <textarea
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={onTextareaKeyDown}
                rows={4}
                aria-label="Research topic"
                placeholder="Describe what to research — e.g. autonomous AI agents and orchestration"
                className="w-full resize-none bg-transparent px-1 text-[16px] leading-[1.4] text-foreground outline-none placeholder:text-brand-muted"
              />

              {/* Inline control bar. The filters stay on ONE row whatever the
                  selected labels are ("Highest Outperformance" + "Last 6 months"
                  is the widest pair and only just fits at the 800px max width):
                  every group is shrink-0/nowrap, and the strip scrolls sideways
                  rather than wrapping under the send button on narrow viewports.
                  py-1/-my-1 keeps focus rings from being clipped by the scroller
                  without adding height. */}
              <div className="flex w-full items-center justify-between gap-3">
                <div className="flex min-w-0 flex-1 flex-nowrap items-center gap-x-3 overflow-x-auto py-1 -my-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                  {/* Format toggle — subtle segmented control (not in Figma; see options.ts). */}
                  <div
                    role="group"
                    aria-label="Format"
                    className="flex shrink-0 items-center gap-1 whitespace-nowrap text-[14px] leading-[22px]"
                  >
                    {FORMAT_OPTIONS.map((opt, i) => (
                      <Fragment key={opt.value}>
                        {i > 0 && <span className="text-border">·</span>}
                        <button
                          type="button"
                          onClick={() => setFormat(opt.value)}
                          aria-pressed={format === opt.value}
                          className={cn(
                            'rounded-md outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring/40',
                            format === opt.value
                              ? 'font-medium text-brand-teal'
                              : 'text-brand-muted hover:text-foreground',
                          )}
                        >
                          {opt.label}
                        </button>
                      </Fragment>
                    ))}
                  </div>

                  {/* Upload date. */}
                  <Select value={uploadDate} onValueChange={(v) => setUploadDate(v as UploadDate)}>
                    <SelectTrigger aria-label="Upload date" className={COMPOSER_SELECT_TRIGGER}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {UPLOAD_DATE_OPTIONS.map((o) => (
                        <SelectItem key={o.value} value={o.value}>
                          {o.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  {/* Outperformance. */}
                  <Select
                    value={outperformance}
                    onValueChange={(v) => setOutperformance(v as Outperformance)}
                  >
                    <SelectTrigger aria-label="Outperformance" className={COMPOSER_SELECT_TRIGGER}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {OUTPERFORMANCE_OPTIONS.map((o) => (
                        <SelectItem key={o.value} value={o.value}>
                          {o.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  {/* Analysis toggles. Label is a SIBLING (not a wrapper) of the
                      control: wrapping a labelable control in a <label htmlFor>
                      pointing back at it double-fires the click and cancels the toggle. */}
                  <div className="flex shrink-0 items-center gap-1.5">
                    <Checkbox
                      id="analyze-titles"
                      checked={analyzeTitles}
                      onCheckedChange={(v) => setAnalyzeTitles(v === true)}
                    />
                    <label
                      htmlFor="analyze-titles"
                      className="cursor-pointer whitespace-nowrap text-[14px] leading-[22px] text-brand-muted"
                    >
                      Titles Analytic
                    </label>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <Checkbox
                      id="analyze-scripts"
                      checked={analyzeScripts}
                      onCheckedChange={(v) => setAnalyzeScripts(v === true)}
                    />
                    <label
                      htmlFor="analyze-scripts"
                      className="cursor-pointer whitespace-nowrap text-[14px] leading-[22px] text-brand-muted"
                    >
                      Script analytics
                    </label>
                  </div>
                </div>

                {/* Send (Figma 27:927 disabled @30% → 29:135 solid teal enabled). */}
                <span
                  className="shrink-0"
                  title={trimmed.length === 0 ? 'Type a topic to start.' : undefined}
                >
                  <button
                    type="submit"
                    disabled={!canSend}
                    aria-label="Send"
                    className={cn(
                      'flex items-center justify-center rounded-[8px] bg-primary p-2 text-primary-foreground outline-none transition-opacity',
                      'focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
                      canSend ? 'cursor-pointer hover:bg-primary/90' : 'cursor-not-allowed opacity-30',
                    )}
                  >
                    <ArrowUp className="size-5" />
                  </button>
                </span>
              </div>
            </Card>

            {error && (
              <p role="alert" className="mt-2 text-center text-[13px] text-destructive">
                {error}
              </p>
            )}

            {/* H2 — pre-run YouTube quota expectation (estimate; see lib/cost.ts). */}
            <div className="mt-3">
              <CostHint />
            </div>
          </form>
        </div>
      </div>

      <ComposerFooter
        config={config}
        adapters={adapters}
        historyCount={items.length}
        onModelChange={handleModelChange}
      />
    </div>
  )
}
