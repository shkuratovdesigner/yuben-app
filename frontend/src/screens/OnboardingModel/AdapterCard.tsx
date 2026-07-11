import { Card, CardDescription, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { Adapter } from '@/lib/types'

interface AdapterCardProps {
  adapter: Adapter
  /** Static brand icon (adapter-claude.png / adapter-gemini.png). */
  icon: string
  /** Static one-line description ("Local Claude agent"). */
  description: string
  selected: boolean
  onSelect: () => void
}

/**
 * Selectable adapter card (Figma 7:5210 / 7:5227). Resting = #fbfbfb, transparent
 * border; selected = #f8f8f8 + teal-green ring — driven by the shared `Card active`.
 * TRUST RULE: `name`, `installed`, and `version` render straight from the
 * `Adapter` record in useConfig() — never fabricated here.
 */
export function AdapterCard({ adapter, icon, description, selected, onSelect }: AdapterCardProps) {
  const installedLabel = adapter.installed
    ? adapter.version
      ? `Installed · v${adapter.version}`
      : 'Installed'
    : 'Not installed'

  return (
    <Card
      active={selected}
      role="radio"
      aria-checked={selected}
      aria-label={adapter.name}
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onSelect()
        }
      }}
      className={cn(
        'flex cursor-pointer flex-col gap-5 px-6 pt-4 pb-3 outline-none transition-colors',
        'focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
        !selected && 'hover:border-border',
      )}
    >
      <img src={icon} alt="" className="size-14" />
      <div className="flex w-full flex-col gap-1.5">
        {/* Resting title is greyed (per Figma); selected goes full ink. */}
        <CardTitle className={cn(!selected && 'text-brand-grey')}>{adapter.name}</CardTitle>
        <CardDescription>{description}</CardDescription>
        <span
          className={cn(
            'mt-1 inline-flex items-center gap-1.5 text-[13px]',
            adapter.installed ? 'text-brand-selected' : 'text-brand-grey',
          )}
        >
          <span
            className={cn(
              'size-1.5 rounded-full',
              adapter.installed ? 'bg-brand-selected' : 'bg-brand-grey',
            )}
          />
          {installedLabel}
        </span>
      </div>
    </Card>
  )
}
