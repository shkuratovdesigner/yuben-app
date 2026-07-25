/**
 * Composer footer (Figma 27:529 resting = model switcher only · 36:2939
 * "home with history" = model switcher · Research history [n]).
 *
 * The model switcher reflects the ACTIVE model from config (never a hardcoded
 * label) and, when the active adapter exposes models, lets the user switch it
 * (saveConfig). Beside it sits the YouTube key status — a run needs BOTH halves
 * (a model to narrate, a YouTube key to fetch the facts), and the footer used to
 * show only the first. The history entry appears only after the first run
 * (historyCount > 0) and deep-links to /history, which owns the actual list.
 */
import { Link } from 'react-router-dom'

import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { Adapter, Config } from '@/lib/types'
import { cn } from '@/lib/utils'

import { INLINE_SELECT_TRIGGER } from './options'

/**
 * YouTube Data API key status, beside the model switcher.
 *
 * Reads `config.youtube_key_present` — a PRESENCE FLAG, not the key. The key is
 * write-only and never reaches the frontend (SECRET RULE, lib/api.ts), so this
 * reports "a key is stored", never "a key that works": a stored-but-rejected key
 * still reads as connected until the user re-tests it in onboarding step 2.
 *
 * Both states link to /onboarding/setup, which owns the key field and its test —
 * so "not connected" is one click from fixed, and a stale key is one click from
 * replaced. That route is gated by <RequireAdapter/>, which the composer has
 * already satisfied (it only renders once onboarding is complete).
 */
function YouTubeKeyStatus({ connected }: { connected: boolean }) {
  const label = connected ? 'YouTube API' : 'Connect YouTube API'
  const hint = connected
    ? 'YouTube Data API key connected — click to test or replace it.'
    : 'No YouTube Data API key stored — research runs need one. Click to connect.'

  return (
    <Link
      to="/onboarding/setup"
      title={hint}
      aria-label={hint}
      className={cn(
        'flex items-center gap-2 rounded-md outline-none transition-colors',
        'hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/40',
        connected ? 'text-brand-muted' : 'text-destructive',
      )}
    >
      <span
        aria-hidden
        className={cn(
          'size-2 shrink-0 rounded-full',
          connected ? 'bg-brand-selected' : 'bg-destructive',
        )}
      />
      <span>{label}</span>
    </Link>
  )
}

interface ComposerFooterProps {
  config: Config | null
  adapters: Adapter[]
  historyCount: number
  onModelChange: (model: string) => void
}

export function ComposerFooter({
  config,
  adapters,
  historyCount,
  onModelChange,
}: ComposerFooterProps) {
  const model = config?.model ?? 'default'
  const activeAdapter = adapters.find((a) => a.id === config?.adapter)
  const models = activeAdapter?.models ?? []
  // Guarantee the current value is selectable so the trigger never renders blank.
  const modelOptions = models.includes(model) ? models : [model, ...models]
  const canSwitchModel = models.length > 0
  const hasHistory = historyCount > 0

  return (
    <footer className="flex flex-wrap items-center justify-center gap-x-14 gap-y-3 pt-8 text-[14px] leading-[22px] text-brand-muted">
      {canSwitchModel ? (
        <Select value={model} onValueChange={onModelChange}>
          <SelectTrigger aria-label="Active model" className={INLINE_SELECT_TRIGGER}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {modelOptions.map((m) => (
              <SelectItem key={m} value={m}>
                {m}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : (
        <span className="tabular-nums text-brand-muted">{model}</span>
      )}

      {/* Only once config has loaded — an absent flag is "unknown", not "missing". */}
      {config && <YouTubeKeyStatus connected={config.youtube_key_present} />}

      {hasHistory && (
        <Link
          to="/history"
          className="flex items-center gap-2 text-brand-muted transition-colors hover:text-foreground"
        >
          <span>Research history</span>
          <Badge
            variant="count"
            className="h-[22px] min-w-[22px] justify-center rounded-full px-1.5 text-[13px]"
          >
            {historyCount}
          </Badge>
        </Link>
      )}
    </footer>
  )
}
