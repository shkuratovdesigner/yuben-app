import { useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react'

import { Badge, vsrTier } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  TableScroll,
} from '@/components/ui/table'
import { InfoHint, TooltipProvider } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import type { Video } from '@/lib/types'

/**
 * Compact outperformance label, e.g. 0.43 -> "0.4×", 41.62 -> "41×".
 * Truncates (never rounds up) so the number never crosses a `vsrTier()`
 * boundary the colour doesn't — a 1.98 stays "1.9×" (neutral), not "2.0×".
 *
 * Kept identical to WatchList's helper so the Mult badge reads the same across
 * Section A (here) and Section B (F6's WatchList).
 */
function formatMult(n: number): string {
  const truncated = Math.floor(n * 10) / 10
  return truncated >= 10 ? `${Math.floor(n)}×` : `${truncated.toFixed(1)}×`
}

/** Eng/1k as a one-decimal string (likes ÷ views × 1000, already computed). */
function formatEng(n: number): string {
  return n.toFixed(1)
}

// --- Grid (Figma 31:184) ---------------------------------------------------

/**
 * One video card: thumbnail (with duration overlay) + title, channel, the
 * outperformance badge, view count and a Watch link. Every value is read
 * straight off the `Video` — no ids/links/numbers are ever fabricated here.
 */
function VideoCard({ video }: { video: Video }) {
  return (
    <Card className="flex flex-col overflow-hidden border-border transition-shadow hover:shadow-sm">
      <a
        href={video.watch_url}
        target="_blank"
        rel="noopener noreferrer"
        className="relative block aspect-video bg-muted"
        aria-label={`Watch “${video.title}” on YouTube`}
      >
        <img
          src={video.thumbnail_url}
          alt=""
          loading="lazy"
          className="size-full object-cover"
        />
        <span className="absolute bottom-2 right-2 rounded bg-black/75 px-1.5 py-0.5 text-[11px] font-medium tabular-nums text-white">
          {video.duration_label}
        </span>
      </a>

      <div className="flex flex-1 flex-col gap-1.5 p-4">
        <h3
          className="line-clamp-2 text-sm font-medium leading-snug text-foreground"
          title={video.title}
        >
          {video.title}
        </h3>
        <p className="truncate text-xs text-brand-grey" title={video.channel_name}>
          {video.channel_name}
          {video.channel_country && (
            <span
              className="ml-1.5 text-[10px] font-medium uppercase tracking-wide text-brand-grey/70"
              title={`Channel country: ${video.channel_country}`}
            >
              {video.channel_country}
            </span>
          )}
        </p>

        <div className="mt-auto flex flex-wrap items-center gap-x-2 gap-y-1 pt-2 text-xs text-brand-grey">
          <span className="tabular-nums">{video.view_count.toLocaleString()} views</span>
          {video.vsr != null && (
            <Badge variant={vsrTier(video.vsr)} size="sm">
              {formatMult(video.vsr)}
            </Badge>
          )}
          {video.engagement_flag === 'promoted' && (
            <Badge variant="promoted" size="sm">
              promoted
            </Badge>
          )}
          <a
            href={video.watch_url}
            target="_blank"
            rel="noopener noreferrer"
            className="ml-auto font-medium text-brand-link hover:underline"
          >
            Watch
          </a>
        </div>
      </div>
    </Card>
  )
}

function TopVideosGrid({ videos }: { videos: Video[] }) {
  return (
    <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
      {videos.map((video) => (
        <VideoCard key={video.video_id} video={video} />
      ))}
    </div>
  )
}

// --- List (Figma 31:843) ---------------------------------------------------

type SortKey = 'views' | 'mult' | 'eng' | 'duration'
type SortDir = 'desc' | 'asc'

/** The sortable numeric columns. `mult` is nullable — subs can be 0/hidden. */
const SORT_VALUE: Record<SortKey, (v: Video) => number | null> = {
  views: (v) => v.view_count,
  mult: (v) => v.vsr,
  eng: (v) => v.eng_per_1k,
  duration: (v) => v.duration_seconds,
}

/**
 * A header that sorts its column, plus an optional ⓘ explaining the metric.
 * The two are siblings, never nested — a tooltip trigger inside the sort button
 * would be a button inside a button, which breaks both semantics and keyboard
 * order. `aria-sort` lives on the <th> so screen readers announce the state.
 */
function SortableHead({
  label,
  sortKey,
  active,
  dir,
  onSort,
  hint,
  className,
}: {
  label: string
  sortKey: SortKey
  active: boolean
  dir: SortDir
  onSort: (key: SortKey) => void
  hint?: React.ReactNode
  className?: string
}) {
  const Arrow = !active ? ArrowUpDown : dir === 'desc' ? ArrowDown : ArrowUp
  return (
    <TableHead
      className={className}
      aria-sort={active ? (dir === 'desc' ? 'descending' : 'ascending') : 'none'}
    >
      <div className="flex items-center justify-end gap-1">
        <button
          type="button"
          onClick={() => onSort(sortKey)}
          title={`Sort by ${label}`}
          className={cn(
            'inline-flex items-center gap-1 rounded outline-none transition-colors',
            'hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/40',
            active && 'text-foreground',
          )}
        >
          {label}
          <Arrow className={cn('size-3', !active && 'opacity-40')} aria-hidden />
        </button>
        {hint ? <InfoHint label={label}>{hint}</InfoHint> : null}
      </div>
    </TableHead>
  )
}

/**
 * Ranked table: № · Title & thumbnail · Channel · Views · Mult · Eng/1k ·
 * Duration · Link. The Mult cell is colour-coded by `vsrTier(video.vsr)`; the
 * whole table lives inside TableScroll so wide content scrolls horizontally
 * without ever breaking the page layout (PRD §7).
 *
 * The four numeric columns sort on click — first click high→low, clicking the
 * active column again flips it. № keeps each video's original outlier rank
 * rather than renumbering, so re-sorting by duration doesn't silently restate
 * the ranking.
 */
function TopVideosList({ videos }: { videos: Video[] }) {
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir } | null>(null)

  function handleSort(key: SortKey) {
    setSort((prev) =>
      prev?.key === key ? { key, dir: prev.dir === 'desc' ? 'asc' : 'desc' } : { key, dir: 'desc' },
    )
  }

  const rows = useMemo(() => {
    const ranked = videos.map((video, i) => ({ video, rank: i + 1 }))
    if (!sort) return ranked
    const get = SORT_VALUE[sort.key]
    return [...ranked].sort((a, b) => {
      const av = get(a.video)
      const bv = get(b.video)
      // Missing values sort last in both directions — they're absent, not small.
      if (av == null && bv == null) return a.rank - b.rank
      if (av == null) return 1
      if (bv == null) return -1
      return sort.dir === 'desc' ? bv - av : av - bv
    })
  }, [videos, sort])

  const headProps = (key: SortKey) => ({
    sortKey: key,
    active: sort?.key === key,
    dir: sort?.key === key ? sort.dir : ('desc' as SortDir),
    onSort: handleSort,
    className: 'text-right',
  })

  return (
    <TooltipProvider delayDuration={150}>
      <TableScroll className="rounded-[12px] border border-border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10">№</TableHead>
              <TableHead className="min-w-[260px]">Title &amp; thumbnail</TableHead>
              <TableHead className="min-w-[140px]">Channel</TableHead>
              <SortableHead label="Views" {...headProps('views')} />
              <SortableHead
                label="Mult"
                {...headProps('mult')}
                hint={
                  <>
                    <strong className="font-medium">Views ÷ subscribers (VSR).</strong> How far the
                    video outran its channel&rsquo;s size — 5× means five times as many views as the
                    channel has subscribers. High multiples point to the idea carrying the video
                    rather than an existing audience.
                  </>
                }
              />
              <SortableHead
                label="Eng/1k"
                {...headProps('eng')}
                hint={
                  <>
                    <strong className="font-medium">Likes per 1,000 views.</strong> A sanity check on
                    the view count: below 1.5 the video is flagged{' '}
                    <em className="not-italic text-brand-grey">promoted</em>, since unusually low
                    engagement can indicate bought or dead views.
                  </>
                }
              />
              <SortableHead label="Duration" {...headProps('duration')} />
              <TableHead className="text-right">Link</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map(({ video, rank }) => (
              <TableRow key={video.video_id}>
                <TableCell className="align-top tabular-nums text-brand-grey">{rank}</TableCell>
                <TableCell className="align-top">
                  <div className="flex items-start gap-3">
                    <img
                      src={video.thumbnail_url}
                      alt=""
                      loading="lazy"
                      className="hidden aspect-video w-16 shrink-0 rounded-md border border-border bg-muted object-cover sm:block"
                    />
                    <span className="min-w-[180px] font-medium leading-snug">{video.title}</span>
                  </div>
                </TableCell>
                <TableCell className="align-top text-brand-grey">
                  {video.channel_name}
                  {video.channel_country && (
                    <span
                      className="ml-1.5 align-middle text-[10px] font-medium uppercase tracking-wide text-brand-grey/70"
                      title={`Channel country: ${video.channel_country}`}
                    >
                      {video.channel_country}
                    </span>
                  )}
                </TableCell>
                <TableCell className="align-top whitespace-nowrap text-right tabular-nums">
                  {video.view_count.toLocaleString()}
                </TableCell>
                <TableCell className="align-top text-right">
                  {video.vsr != null ? (
                    <Badge variant={vsrTier(video.vsr)}>{formatMult(video.vsr)}</Badge>
                  ) : (
                    <span className="text-brand-grey">—</span>
                  )}
                </TableCell>
                <TableCell className="align-top whitespace-nowrap text-right tabular-nums text-brand-grey">
                  {formatEng(video.eng_per_1k)}
                  {video.engagement_flag === 'promoted' && (
                    <Badge variant="promoted" size="sm" className="ml-2 align-middle">
                      promoted
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="align-top whitespace-nowrap text-right tabular-nums text-brand-grey">
                  {video.duration_label}
                </TableCell>
                <TableCell className="align-top text-right">
                  <a
                    href={video.watch_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-medium text-brand-link hover:underline"
                  >
                    Watch
                  </a>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableScroll>
    </TooltipProvider>
  )
}

// --- public component ------------------------------------------------------

/**
 * Section A — Top Highest-Performed Videos (Figma 31:184 grid / 31:843 list).
 *
 * The `view` toggle is owned by the Results container (index.tsx); this
 * component just renders the matching layout. TRUST RULE: thumbnails, links,
 * view counts, VSR and Eng/1k all come straight from the `Video` objects.
 */
export function TopVideos({ videos, view }: { videos: Video[]; view: 'grid' | 'list' }) {
  if (videos.length === 0) {
    return <p className="text-sm text-brand-muted">No videos were curated for this run.</p>
  }
  return view === 'grid' ? <TopVideosGrid videos={videos} /> : <TopVideosList videos={videos} />
}
