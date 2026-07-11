import { useState } from 'react'
import type { FormEvent } from 'react'
import { CheckCircle2, Lightbulb, Send } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useHistory } from '@/app/stores/history-store'

type SubmitStatus = 'idle' | 'submitting' | 'done' | 'error'

/**
 * Suggest feature (PRD §4.6 / FR-6) — a lightweight local capture. Consumes the
 * shell's `useHistory().submitSuggestion(text)`; on success it swaps to a
 * thank-you acknowledgement. The `#suggest` id lets the Composer footer's
 * "Suggest feature" entry deep-link straight to this block.
 *
 * There is no Dialog primitive in the frozen design system (and we add no deps),
 * so this is an inline panel rather than a modal — nothing is sent off-machine.
 */
export function SuggestFeature() {
  const { submitSuggestion } = useHistory()
  const [text, setText] = useState('')
  const [status, setStatus] = useState<SubmitStatus>('idle')

  const canSubmit = text.trim().length > 0 && status !== 'submitting'

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!text.trim()) return
    setStatus('submitting')
    try {
      await submitSuggestion(text.trim())
      setStatus('done')
    } catch {
      setStatus('error')
    }
  }

  function reset() {
    setText('')
    setStatus('idle')
  }

  return (
    <section id="suggest" className="border-t border-border pt-8">
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center gap-2">
          <Lightbulb className="size-4 text-brand-teal" aria-hidden />
          <h2 className="text-[17px] font-medium leading-6 text-foreground">Suggest a feature</h2>
        </div>
        <p className="text-sm text-brand-muted">
          Have an idea that would make YuBen more useful? It stays on your machine.
        </p>
      </div>

      {status === 'done' ? (
        <div className="mt-4 flex items-start gap-3 rounded-[16px] border border-brand-selected/40 bg-brand-selected/8 p-4">
          <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-brand-selected" aria-hidden />
          <div className="flex flex-col items-start gap-1.5">
            <p className="text-sm text-foreground">Thanks — your suggestion was saved locally.</p>
            <button
              type="button"
              onClick={reset}
              className="text-sm text-brand-link underline-offset-2 outline-none hover:underline focus-visible:underline"
            >
              Suggest another
            </button>
          </div>
        </div>
      ) : (
        <form onSubmit={(e) => void handleSubmit(e)} className="mt-4 flex flex-col gap-3">
          <label htmlFor="suggestion" className="sr-only">
            Your suggestion
          </label>
          <textarea
            id="suggestion"
            value={text}
            onChange={(e) => {
              setText(e.target.value)
              if (status === 'error') setStatus('idle')
            }}
            placeholder="e.g. Add CSV export of the outlier table, or a dark mode."
            rows={3}
            className="flex min-h-[92px] w-full resize-y rounded-[var(--radius-field)] border border-input bg-background px-3.5 py-3 text-base text-foreground outline-none placeholder:text-brand-muted focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30"
          />
          <div className="flex items-center justify-between gap-3">
            {status === 'error' ? (
              <p className="text-sm text-destructive">Couldn&rsquo;t save that. Try again.</p>
            ) : (
              <span className="text-xs text-brand-muted">Stored locally — nothing is sent to a server.</span>
            )}
            <Button type="submit" size="sm" disabled={!canSubmit}>
              <Send className="size-4" />
              {status === 'submitting' ? 'Sending…' : 'Send suggestion'}
            </Button>
          </div>
        </form>
      )}
    </section>
  )
}
