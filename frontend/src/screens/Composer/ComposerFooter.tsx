/**
 * Composer footer (Figma 27:529 resting = model switcher only · 36:2939
 * "home with history" = model switcher · Research history [n]).
 *
 * The model switcher reflects the ACTIVE model from config (never a hardcoded
 * label) and, when the active adapter exposes models, lets the user switch it
 * (saveConfig). The history entry appears only after the first run
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

import { INLINE_SELECT_TRIGGER } from './options'

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
