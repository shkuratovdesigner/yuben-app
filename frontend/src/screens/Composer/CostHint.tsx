import { ChevronDown, Gauge } from 'lucide-react'

import { YT_DAILY_QUOTA, estimateRun, formatUnits, runsPerDay } from '@/lib/cost'

/**
 * Composer cost hint (H2) — a subtle, expandable line that sets expectations
 * about YouTube Data API quota BEFORE a run, so a search-heavy run never
 * surprises the user (the free tier is 10,000 units/day; each run is a
 * meaningful slice). A native <details> disclosure — accessible, no dep.
 *
 * Figures are estimates: the agent expands one topic into several search terms
 * (100 units each) and the exact count isn't known until the run. See lib/cost.ts.
 * The exact per-run figure is shown afterwards on the results screen.
 */
export function CostHint() {
  const est = estimateRun()

  return (
    <details className="group mx-auto max-w-[560px] text-center [&_summary::-webkit-details-marker]:hidden">
      <summary
        className="inline-flex cursor-pointer list-none items-center gap-1.5 rounded-full px-2 py-1 text-xs text-brand-muted outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/40"
        title="Estimated YouTube Data API usage"
      >
        <Gauge className="size-3.5" aria-hidden />
        <span>
          Est. <span className="font-medium text-foreground">~{formatUnits(est.typical)}</span> YouTube
          units per run · {formatUnits(YT_DAILY_QUOTA)} free daily
        </span>
        <ChevronDown className="size-3 transition-transform group-open:rotate-180" aria-hidden />
      </summary>

      <div className="mx-auto mt-2 max-w-[520px] rounded-[12px] border border-border bg-muted/40 p-3.5 text-left text-xs leading-relaxed text-brand-grey">
        <p>
          Each run expands your topic into several search terms, and YouTube charges{' '}
          <span className="font-medium text-foreground">100 units per search</span> (plus a little for
          video &amp; channel details). A typical run costs{' '}
          <span className="font-medium text-foreground">
            {formatUnits(est.low)}–{formatUnits(est.high)} units
          </span>{' '}
          — so the free{' '}
          <span className="font-medium text-foreground">{formatUnits(YT_DAILY_QUOTA)}/day</span> quota
          is about <span className="font-medium text-foreground">{runsPerDay()} runs</span>.
        </p>
        <p className="mt-1.5">
          YouTube doesn&rsquo;t report live usage, so this is an estimate — the exact cost of a run is
          shown on its results.
        </p>
      </div>
    </details>
  )
}
