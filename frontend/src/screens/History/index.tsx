/**
 * History screen (route `/history`, Figma `36:2939` home-with-history family).
 *
 * Consumes the F8 shell store only — `useHistory()` → { items, loading, remove }.
 * Every row is a "stretched link" to `/run/:run_id`; the shell's run store
 * reopens the SAVED result from cache (never re-runs). Delete uses the store's
 * optimistic `remove(run_id)`.
 *
 * TRUST RULE: run ids and counts are rendered straight from `useHistory().items`
 * — nothing here fabricates a run id, count, or metric, and opening a run always
 * routes through the shell rather than reconstructing a result locally.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight, FileText, Film, Inbox, Trash2 } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useHistory } from '@/app/stores/history-store'
import type { Format, HistoryItem, Outperformance } from '@/lib/types'

import { SuggestFeature } from './SuggestFeature'

const FORMAT_META: Record<Format, { label: string; Icon: LucideIcon }> = {
  longform: { label: 'Long-form', Icon: FileText },
  shorts: { label: 'Shorts', Icon: Film },
}

const OUTPERFORMANCE_LABEL: Record<Outperformance, string> = {
  any: 'Any',
  '2x': '2×+',
  '5x': '5×+',
  '10x': '10×+',
  highest: 'Highest',
}

/** Absolute, locale-formatted run date. Absolute (not relative) so it stays correct regardless of the client clock. */
function formatDate(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }).format(date)
}

function HistoryRow({ item, onDelete }: { item: HistoryItem; onDelete: (runId: string) => void }) {
  const [confirming, setConfirming] = useState(false)
  const { label: formatLabel, Icon } = FORMAT_META[item.format] ?? FORMAT_META.longform
  const title = item.topic_title || item.query
  const curated = typeof item.counts?.curated === 'number' ? item.counts.curated : null

  return (
    <Card className="group relative flex items-start gap-4 border-border p-4 transition-colors hover:bg-brand-card-active sm:p-5">
      <div className="flex size-10 shrink-0 items-center justify-center rounded-[10px] border border-border bg-background text-brand-grey">
        <Icon className="size-5" aria-hidden />
      </div>

      <div className="min-w-0 flex-1">
        <p className="line-clamp-2 pr-2 text-[15px] font-medium leading-snug text-foreground">
          {title}
        </p>
        <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[13px] text-brand-grey">
          <span>{formatLabel}</span>
          <span aria-hidden>·</span>
          <span>{formatDate(item.created_at)}</span>
          {curated !== null && (
            <>
              <span aria-hidden>·</span>
              <span>
                {curated} video{curated === 1 ? '' : 's'}
              </span>
            </>
          )}
        </p>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        {confirming ? (
          // z-10 keeps the confirm controls above the stretched link (which is
          // suppressed for this row while confirming, so the row isn't clickable).
          <div className="relative z-10 flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              className="h-8 px-3"
              onClick={() => setConfirming(false)}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              size="sm"
              className="h-8 px-3"
              onClick={() => onDelete(item.run_id)}
            >
              Delete
            </Button>
          </div>
        ) : (
          <>
            <Badge variant="outline">{OUTPERFORMANCE_LABEL[item.outperformance] ?? item.outperformance}</Badge>
            <div className="relative z-10">
              <button
                type="button"
                aria-label={`Delete research: ${title}`}
                onClick={() => setConfirming(true)}
                className="flex size-8 items-center justify-center rounded-full text-brand-grey opacity-0 outline-none transition-opacity hover:bg-muted hover:text-destructive focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring group-hover:opacity-100 group-focus-within:opacity-100"
              >
                <Trash2 className="size-4" aria-hidden />
              </button>
            </div>
            <ChevronRight
              className="size-4 text-brand-grey/50 opacity-0 transition-opacity group-hover:opacity-100"
              aria-hidden
            />
          </>
        )}
      </div>

      {/* Stretched link: the whole card opens the cached run. Hidden while
          confirming a delete so the destructive step isn't one stray click away. */}
      {!confirming && (
        <Link
          to={`/run/${item.run_id}`}
          aria-label={`Open research: ${title}`}
          className="absolute inset-0 rounded-[16px] outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
      )}
    </Card>
  )
}

function LoadingState() {
  return (
    <div className="flex flex-col gap-3" aria-hidden>
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-[86px] animate-pulse rounded-[16px] border border-border bg-brand-card" />
      ))}
    </div>
  )
}

function EmptyState() {
  return (
    <div className="mx-auto flex max-w-[440px] flex-col items-center gap-4 rounded-[16px] border border-dashed border-border bg-brand-card px-6 py-16 text-center">
      <div className="flex size-12 items-center justify-center rounded-full bg-muted text-brand-grey">
        <Inbox className="size-6" aria-hidden />
      </div>
      <div className="flex flex-col gap-1.5">
        <p className="font-display text-[24px] leading-tight text-foreground">No research yet</p>
        <p className="text-sm text-brand-muted">
          Run your first topic and it&rsquo;ll show up here — ready to reopen any time.
        </p>
      </div>
      <Button asChild size="sm">
        <Link to="/">Run your first topic</Link>
      </Button>
    </div>
  )
}

export default function History() {
  const { items, loading, remove } = useHistory()

  return (
    <div className="mx-auto flex w-full max-w-[760px] flex-col gap-10 py-10 sm:py-14">
      <section className="flex flex-col gap-6">
        <header className="flex flex-col gap-2">
          <div className="flex items-center gap-3">
            <h1 className="font-display text-[32px] leading-tight text-foreground sm:text-[40px]">
              Research history
            </h1>
            {!loading && items.length > 0 && <Badge variant="count">{items.length}</Badge>}
          </div>
          <p className="text-sm text-brand-muted">
            Reopen any past run instantly — results load from cache, never re-run.
          </p>
        </header>

        {loading ? (
          <LoadingState />
        ) : items.length === 0 ? (
          <EmptyState />
        ) : (
          <ul className="flex flex-col gap-3">
            {items.map((item) => (
              <li key={item.run_id}>
                <HistoryRow item={item} onDelete={remove} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <SuggestFeature />
    </div>
  )
}
