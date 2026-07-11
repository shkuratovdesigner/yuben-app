import { Badge, vsrTier } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  TableScroll,
} from '@/components/ui/table'
import type { Video, WatchListItem } from '@/lib/types'

/**
 * Compact outperformance label, e.g. 0.43 -> "0.4×", 41.62 -> "41×".
 * Truncates (never rounds up) so the number never crosses a `vsrTier()`
 * boundary the colour doesn't — a 1.98 stays "1.9×" (neutral), not "2.0×".
 */
function formatMult(n: number): string {
  const truncated = Math.floor(n * 10) / 10
  return truncated >= 10 ? `${Math.floor(n)}×` : `${truncated.toFixed(1)}×`
}

/**
 * Section B — Recommended Watch List by Learning Goal (Figma 31:843 / 32:1518).
 *
 * Renders WatchListItem[] as a horizontally-scrollable table, joined to the
 * authoritative Video[] by `video_id`. Rows are ordered by `item.rank`; any
 * item whose `video_id` is absent from `videos` is skipped (never fabricated).
 *
 * TRUST RULE: the title, thumbnail, outperformance tier, duration and link all
 * come from the joined Video — only the narrative (`why` / `learning_goal`)
 * comes from the item free-text. F5's Results container owns the section
 * heading; this component renders the table only.
 */
export function WatchList({ items, videos }: { items: WatchListItem[]; videos: Video[] }) {
  const byId: Record<string, Video> = {}
  for (const v of videos) byId[v.video_id] = v

  const rows = [...items]
    .sort((a, b) => a.rank - b.rank)
    .map((item) => ({ item, video: byId[item.video_id] }))
    .filter((row): row is { item: WatchListItem; video: Video } => Boolean(row.video))

  if (rows.length === 0) {
    return (
      <p className="text-sm text-brand-muted">No watch-list recommendations for this run.</p>
    )
  }

  return (
    <TableScroll className="rounded-[12px] border border-border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-10">№</TableHead>
            <TableHead className="min-w-[220px]">Title</TableHead>
            <TableHead className="min-w-[280px]">Why to watch</TableHead>
            <TableHead className="text-right">Mult</TableHead>
            <TableHead className="text-right">Duration</TableHead>
            <TableHead className="text-right">Link</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map(({ item, video }) => (
            <TableRow key={item.video_id}>
              <TableCell className="align-top tabular-nums text-brand-grey">{item.rank}</TableCell>
              <TableCell className="align-top">
                <div className="flex items-start gap-3">
                  <img
                    src={video.thumbnail_url}
                    alt=""
                    loading="lazy"
                    className="hidden aspect-video w-16 shrink-0 rounded-md border border-border bg-muted object-cover sm:block"
                  />
                  <div className="min-w-0">
                    <div className="font-medium leading-snug">{video.title}</div>
                    <div className="text-xs text-brand-grey">{video.channel_name}</div>
                  </div>
                </div>
              </TableCell>
              <TableCell className="max-w-[440px] align-top">
                {item.learning_goal && (
                  <div className="font-medium text-foreground">{item.learning_goal}</div>
                )}
                {item.why && <div className="text-brand-grey">{item.why}</div>}
              </TableCell>
              <TableCell className="align-top text-right">
                {video.vsr != null ? (
                  <Badge variant={vsrTier(video.vsr)}>{formatMult(video.vsr)}</Badge>
                ) : (
                  <span className="text-brand-grey">—</span>
                )}
              </TableCell>
              <TableCell className="align-top text-right tabular-nums text-brand-grey">
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
  )
}
