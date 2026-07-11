import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { LayoutGrid, List } from 'lucide-react'

import { useRun } from '@/app/stores/run-store'
import { computeUnits, formatUnits } from '@/lib/cost'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'

import { AnalysisTabs } from './AnalysisTabs'
import { ExportMenu } from './ExportMenu'
import { TopVideos } from './TopVideos'
import { WatchList } from './WatchList'

type ResultsView = 'grid' | 'list'

/** Teal section heading + optional sub-line (Figma 31:184 / 31:843). */
function SectionHeading({
  title,
  subtitle,
  action,
}: {
  title: string
  subtitle?: string
  action?: React.ReactNode
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
      <div className="flex flex-col gap-1">
        <h2 className="text-[20px] font-medium leading-tight text-brand-teal">{title}</h2>
        {subtitle && <p className="text-sm text-brand-muted">{subtitle}</p>}
      </div>
      {action}
    </div>
  )
}

/**
 * Results screen (Figma 31:184 grid · 31:843 list) — F5.
 *
 * Mounted by the app-shell RunRoute only once `useRun(id).status === 'done'`,
 * so `result` is normally present; we still guard against null defensively.
 * Reads the finished ResearchResult from the run store and composes:
 *   • Header      — topic title (serif) + one-line thesis + grid/list toggle.
 *   • Section A   — TopVideos (this track, F5), switched by the toggle.
 *   • Section B   — WatchList (F6), under a heading owned here.
 *   • Section C   — AnalysisTabs (F6), under a heading owned here.
 */
export default function Results() {
  const { id } = useParams<{ id: string }>()
  const { result } = useRun(id)
  const [view, setView] = useState<ResultsView>('grid')

  if (!result) {
    return (
      <div className="mx-auto flex min-h-[50vh] w-full max-w-[960px] items-center justify-center px-1 text-center">
        <p className="text-sm text-brand-muted">Preparing your results…</p>
      </div>
    )
  }

  // H2 — exact YouTube units this run consumed (derived from its real keyword +
  // unique-video counts; the pipeline's cost is one search per term at 100 units).
  const unitsUsed = computeUnits(result.meta.keywords.length, result.meta.counts.unique ?? 0)

  return (
    <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-14 pb-6">
      {/* Header block — export action (top-right) + centered topic title + thesis. */}
      <div className="flex flex-col gap-5 pt-2">
        <div className="flex justify-end">
          <ExportMenu result={result} />
        </div>
        <header className="mx-auto -mt-2 flex max-w-[760px] flex-col items-center gap-3 text-center">
          <h1 className="font-display text-[32px] leading-[1.15] text-foreground sm:text-[40px]">
            {result.topic_title}
          </h1>
          {result.summary && (
            <p className="text-base leading-relaxed text-brand-muted">{result.summary}</p>
          )}
          <p className="text-xs text-brand-muted" title="Exact YouTube Data API units this run used">
            ~{formatUnits(unitsUsed)} YouTube units · {result.meta.keywords.length} search terms
          </p>
        </header>
      </div>

      {/* Section A — Top Highest-Performed Videos (grid/list). */}
      <section className="flex flex-col gap-5">
        <SectionHeading
          title={`Top ${result.top_videos.length} Highest-Performed Videos`}
          subtitle={`${result.meta.filter} · ${result.meta.ranking}`}
          action={
            <ToggleGroup
              type="single"
              value={view}
              onValueChange={(next) => {
                if (next) setView(next as ResultsView)
              }}
              aria-label="Top videos layout"
            >
              <ToggleGroupItem value="grid" aria-label="Grid view">
                <LayoutGrid className="size-4" />
              </ToggleGroupItem>
              <ToggleGroupItem value="list" aria-label="List view">
                <List className="size-4" />
              </ToggleGroupItem>
            </ToggleGroup>
          }
        />
        <TopVideos videos={result.top_videos} view={view} />
      </section>

      {/* Section B — Recommended Watch List by Learning Goal (F6 table). */}
      <section className="flex flex-col gap-5">
        <SectionHeading
          title="Recommended Watch List by Learning Goal"
          subtitle="A short, sequenced list — what to watch and exactly what to take from each."
        />
        <WatchList items={result.watch_list} videos={result.top_videos} />
      </section>

      {/* Section C — Title / Script analysis (F6 tabs). */}
      <section className="flex flex-col gap-5">
        <SectionHeading title="Analysis" />
        <AnalysisTabs
          titleAnalysis={result.title_analysis}
          scriptAnalysis={result.script_analysis}
          videos={result.top_videos}
        />
      </section>
    </div>
  )
}
