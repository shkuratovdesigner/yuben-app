/**
 * Client-side export of a finished `ResearchResult` → Markdown or a
 * self-contained styled HTML document (H3, PRD §7 hardening).
 *
 * Local-first: everything is generated in the browser from the already
 * trust-verified `ResearchResult` and downloaded via a Blob — nothing is sent
 * anywhere. TRUST RULE is preserved for free: every id, number and link here
 * comes straight from the result the backend assembled + verified; this module
 * only formats it. No value is synthesized.
 */
import type { ResearchResult, Video, WatchListItem } from '@/lib/types'

// --- shared formatting (mirrors the on-screen renderers) -------------------

/** 0.43 → "0.4×", 41.62 → "41×" — truncates so it never crosses a tier edge. */
export function formatMult(n: number | null | undefined): string {
  if (n == null) return '—'
  const truncated = Math.floor(n * 10) / 10
  return truncated >= 10 ? `${Math.floor(n)}×` : `${truncated.toFixed(1)}×`
}

/** VSR → tier (matches `vsrTier()` in components/ui/badge.tsx). */
function tier(vsr: number | null | undefined): 'hot' | 'warm' | 'cool' | 'default' {
  if (vsr == null) return 'default'
  if (vsr >= 5) return 'hot'
  if (vsr >= 2) return 'warm'
  if (vsr < 1) return 'cool'
  return 'default'
}

const TIER_COLOR: Record<string, string> = {
  hot: '#b45309',
  warm: '#3f6212',
  cool: '#9a9aa2',
  default: '#777274',
}

function num(n: number | null | undefined): string {
  return n == null ? '—' : n.toLocaleString('en-US')
}

/** A filesystem-safe slug from the topic title, e.g. "yuben-claude-code-tips". */
export function exportBasename(result: ResearchResult): string {
  const slug = (result.topic_title || 'research')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60)
  return `yuben-${slug || 'research'}`
}

// ---------------------------------------------------------------------------
// Markdown
// ---------------------------------------------------------------------------

/** Escape a `|` so it can't break a Markdown table cell. */
function mdCell(s: string): string {
  return String(s ?? '').replace(/\|/g, '\\|').replace(/\n+/g, ' ').trim()
}

export function toMarkdown(result: ResearchResult): string {
  const L: string[] = []
  L.push(`# ${result.topic_title}`, '')
  if (result.summary) L.push(result.summary, '')

  const m = result.meta
  L.push(
    `**Window:** ${m.window} · **Filter:** ${m.filter} · **Ranking:** ${m.ranking}`,
    '',
  )
  if (m.keywords?.length) L.push(`**Keywords searched:** ${m.keywords.join(', ')}`, '')
  const counts = Object.entries(m.counts || {})
    .map(([k, v]) => `${v.toLocaleString('en-US')} ${k}`)
    .join(' · ')
  if (counts) L.push(`**Counts:** ${counts}`, '')

  // Top videos
  L.push(`## Top ${result.top_videos.length} Highest-Performed Videos`, '')
  L.push('| # | Title | Channel | Mult (VSR) | Eng/1k | Views | Duration | Link |')
  L.push('|--:|---|---|--:|--:|--:|--:|---|')
  result.top_videos.forEach((v: Video, i) => {
    L.push(
      `| ${i + 1} | ${mdCell(v.title)} | ${mdCell(v.channel_name)} | ${formatMult(v.vsr)}` +
        ` | ${v.eng_per_1k ?? '—'} | ${num(v.view_count)} | ${v.duration_label}` +
        ` | [Watch](${v.watch_url}) |`,
    )
  })
  L.push('')

  // Watch list
  if (result.watch_list.length) {
    const byId: Record<string, Video> = {}
    for (const v of result.top_videos) byId[v.video_id] = v
    L.push('## Recommended Watch List by Learning Goal', '')
    L.push('| # | Title | Learning goal | Why to watch | Link |')
    L.push('|--:|---|---|---|---|')
    ;[...result.watch_list]
      .sort((a: WatchListItem, b) => a.rank - b.rank)
      .forEach((w) => {
        const v = byId[w.video_id]
        if (!v) return
        L.push(
          `| ${w.rank} | ${mdCell(v.title)} | ${mdCell(w.learning_goal)}` +
            ` | ${mdCell(w.why)} | [Watch](${v.watch_url}) |`,
        )
      })
    L.push('')
  }

  // Title analysis
  if (result.title_analysis) {
    const ta = result.title_analysis
    L.push('## Title Analysis', '')
    if (ta.common_features.length) {
      L.push('### Common Features', '', '| # | Pattern | Note | Videos |', '|--:|---|---|--:|')
      ta.common_features.forEach((f) =>
        L.push(`| ${f.n} | ${mdCell(f.pattern)} | ${mdCell(f.note)} | ${num(f.count)} |`),
      )
      L.push('')
    }
    if (ta.emotional_triggers.length) {
      L.push('### Emotional Triggers', '', '| # | Trigger | Example |', '|--:|---|---|')
      ta.emotional_triggers.forEach((t) =>
        L.push(`| ${t.n} | ${mdCell(t.trigger)} | ${mdCell(t.example)} |`),
      )
      L.push('')
    }
  }

  // Script analysis
  if (result.script_analysis) {
    const sa = result.script_analysis
    const byId: Record<string, Video> = {}
    for (const v of result.top_videos) byId[v.video_id] = v
    L.push('## Script Analysis', '')
    if (sa.duration_sweet_spot.length) {
      L.push('### Duration Sweet Spot', '')
      sa.duration_sweet_spot.forEach((s) => L.push(`- **${mdCell(s.label)}:** ${mdCell(s.value)}`))
      L.push('')
    }
    if (sa.structure_patterns.length) {
      L.push('### Content Structure Patterns', '')
      sa.structure_patterns.forEach((p) => L.push(`- **${mdCell(p.name)}** — ${mdCell(p.note)}`))
      L.push('')
    }
    const hooks = sa.hook_breakdown.filter((h) => byId[h.video_id])
    if (hooks.length) {
      L.push('### Hook Breakdown (First 30 Seconds)', '', '| # | Title | Hook | Link |', '|--:|---|---|---|')
      ;[...hooks]
        .sort((a, b) => a.rank - b.rank)
        .forEach((h) =>
          L.push(
            `| ${h.rank} | ${mdCell(byId[h.video_id].title)} | ${mdCell(h.hook)}` +
              ` | [Video](${byId[h.video_id].watch_url}) |`,
          ),
        )
      L.push('')
    }
    if (sa.what_to_avoid.length) {
      L.push('### What to Avoid', '')
      sa.what_to_avoid.forEach((s) => L.push(`- ${mdCell(s)}`))
      L.push('')
    }
  }

  L.push('---', `_Generated by YuBen · ${new Date().toISOString().slice(0, 10)}_`, '')
  return L.join('\n')
}

// ---------------------------------------------------------------------------
// HTML (self-contained, styled with the brand tokens)
// ---------------------------------------------------------------------------

function esc(s: unknown): string {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function multCell(vsr: number | null | undefined): string {
  return `<span style="color:${TIER_COLOR[tier(vsr)]};font-weight:600">${esc(formatMult(vsr))}</span>`
}

function link(href: string, label: string): string {
  return `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`
}

export function toHtml(result: ResearchResult): string {
  const m = result.meta
  const byId: Record<string, Video> = {}
  for (const v of result.top_videos) byId[v.video_id] = v

  const rows = result.top_videos
    .map(
      (v, i) => `<tr>
      <td class="num">${i + 1}</td>
      <td><div class="t">${esc(v.title)}</div><div class="sub">${esc(v.channel_name)}</div></td>
      <td class="r">${multCell(v.vsr)}</td>
      <td class="r num">${v.eng_per_1k ?? '—'}</td>
      <td class="r num">${num(v.view_count)}</td>
      <td class="r num">${esc(v.duration_label)}</td>
      <td class="r">${link(v.watch_url, 'Watch')}</td>
    </tr>`,
    )
    .join('')

  const watch = result.watch_list.length
    ? `<h2>Recommended Watch List by Learning Goal</h2>
    <table><thead><tr><th class="num">#</th><th>Title</th><th>Learning goal</th><th>Why to watch</th><th>Link</th></tr></thead><tbody>${[
      ...result.watch_list,
    ]
      .sort((a, b) => a.rank - b.rank)
      .map((w) => {
        const v = byId[w.video_id]
        if (!v) return ''
        return `<tr><td class="num">${w.rank}</td><td class="t">${esc(v.title)}</td><td>${esc(
          w.learning_goal,
        )}</td><td class="sub">${esc(w.why)}</td><td>${link(v.watch_url, 'Watch')}</td></tr>`
      })
      .join('')}</tbody></table>`
    : ''

  const ta = result.title_analysis
  const titleSec = ta
    ? `<h2>Title Analysis</h2>
    ${
      ta.common_features.length
        ? `<h3>Common Features</h3><table><thead><tr><th class="num">#</th><th>Pattern</th><th>Note</th><th class="r">Videos</th></tr></thead><tbody>${ta.common_features
            .map(
              (f) =>
                `<tr><td class="num">${f.n}</td><td class="t">${esc(f.pattern)}</td><td class="sub">${esc(
                  f.note,
                )}</td><td class="r num">${num(f.count)}</td></tr>`,
            )
            .join('')}</tbody></table>`
        : ''
    }
    ${
      ta.emotional_triggers.length
        ? `<h3>Emotional Triggers</h3><table><thead><tr><th class="num">#</th><th>Trigger</th><th>Example</th></tr></thead><tbody>${ta.emotional_triggers
            .map(
              (t) =>
                `<tr><td class="num">${t.n}</td><td class="t">${esc(t.trigger)}</td><td class="sub">${esc(
                  t.example,
                )}</td></tr>`,
            )
            .join('')}</tbody></table>`
        : ''
    }`
    : ''

  const sa = result.script_analysis
  const hooks = sa ? sa.hook_breakdown.filter((h) => byId[h.video_id]) : []
  const scriptSec = sa
    ? `<h2>Script Analysis</h2>
    ${
      sa.duration_sweet_spot.length
        ? `<h3>Duration Sweet Spot</h3><ul>${sa.duration_sweet_spot
            .map((s) => `<li><strong>${esc(s.label)}:</strong> ${esc(s.value)}</li>`)
            .join('')}</ul>`
        : ''
    }
    ${
      sa.structure_patterns.length
        ? `<h3>Content Structure Patterns</h3><ul>${sa.structure_patterns
            .map((p) => `<li><strong>${esc(p.name)}</strong> — ${esc(p.note)}</li>`)
            .join('')}</ul>`
        : ''
    }
    ${
      hooks.length
        ? `<h3>Hook Breakdown (First 30 Seconds)</h3><table><thead><tr><th class="num">#</th><th>Title</th><th>Hook</th><th>Link</th></tr></thead><tbody>${[
            ...hooks,
          ]
            .sort((a, b) => a.rank - b.rank)
            .map(
              (h) =>
                `<tr><td class="num">${h.rank}</td><td class="t">${esc(
                  byId[h.video_id].title,
                )}</td><td class="sub">${esc(h.hook)}</td><td>${link(
                  byId[h.video_id].watch_url,
                  'Video',
                )}</td></tr>`,
            )
            .join('')}</tbody></table>`
        : ''
    }
    ${
      sa.what_to_avoid.length
        ? `<h3>What to Avoid</h3><ul>${sa.what_to_avoid
            .map((s) => `<li>${esc(s)}</li>`)
            .join('')}</ul>`
        : ''
    }`
    : ''

  const countsLine = Object.entries(m.counts || {})
    .map(([k, v]) => `${v.toLocaleString('en-US')} ${esc(k)}`)
    .join(' · ')

  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>${esc(result.topic_title)} — YuBen</title>
<style>
  :root{--teal:#04607d;--link:#00809c;--ink:#2b2d33;--grey:#777274;--border:#d5d5d6;--muted:#808185}
  *{box-sizing:border-box}
  body{margin:0;background:#fff;color:var(--ink);font:15px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased}
  .wrap{max-width:960px;margin:0 auto;padding:48px 24px 72px}
  h1{font-family:Georgia,'Times New Roman',serif;font-weight:500;font-size:34px;line-height:1.15;margin:0 0 12px}
  h2{color:var(--teal);font-size:20px;font-weight:600;margin:44px 0 14px}
  h3{color:var(--teal);font-size:15px;font-weight:600;margin:24px 0 8px}
  .summary{font-size:16px;color:var(--grey);margin:0 0 20px}
  .meta{font-size:13px;color:var(--muted);border-top:1px solid var(--border);border-bottom:1px solid var(--border);padding:12px 0;margin:0 0 8px}
  .meta b{color:var(--ink);font-weight:600}
  table{width:100%;border-collapse:collapse;border:1px solid var(--border);border-radius:12px;overflow:hidden;font-size:13.5px;margin:0 0 8px}
  th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--border);vertical-align:top}
  th{background:#fafafa;color:var(--grey);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.03em}
  tr:last-child td{border-bottom:0}
  td.r,th.r{text-align:right}
  td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;color:var(--grey);white-space:nowrap}
  td.t .t,td.t{font-weight:500}
  .t{font-weight:500}
  .sub{color:var(--grey);font-weight:400}
  td .sub{margin-top:2px;font-size:12.5px}
  a{color:var(--link);text-decoration:none}
  a:hover{text-decoration:underline}
  ul{margin:0 0 8px;padding-left:18px}
  li{margin:0 0 6px}
  .foot{margin-top:48px;padding-top:16px;border-top:1px solid var(--border);color:var(--muted);font-size:12.5px}
  @media (prefers-color-scheme: dark){
    body{background:#151517;color:#e7e7ea}
    h1{color:#f2f2f4}.summary,.sub,td.num,th{color:#9a9aa2}
    th{background:#1e1e21}table,th,td,.meta,.foot{border-color:#2c2c30}
    .meta,.meta b{color:#c9c9cd}.meta b{color:#e7e7ea}
  }
</style></head>
<body><div class="wrap">
  <h1>${esc(result.topic_title)}</h1>
  ${result.summary ? `<p class="summary">${esc(result.summary)}</p>` : ''}
  <p class="meta"><b>Window:</b> ${esc(m.window)} · <b>Filter:</b> ${esc(m.filter)} · <b>Ranking:</b> ${esc(
    m.ranking,
  )}${countsLine ? ` · <b>Counts:</b> ${countsLine}` : ''}${
    m.keywords?.length ? `<br/><b>Keywords:</b> ${esc(m.keywords.join(', '))}` : ''
  }</p>

  <h2>Top ${result.top_videos.length} Highest-Performed Videos</h2>
  <table><thead><tr>
    <th class="num">#</th><th>Title</th><th class="r">Mult</th><th class="r">Eng/1k</th>
    <th class="r">Views</th><th class="r">Duration</th><th class="r">Link</th>
  </tr></thead><tbody>${rows}</tbody></table>

  ${watch}
  ${titleSec}
  ${scriptSec}

  <p class="foot">Generated by YuBen · ${esc(new Date().toISOString().slice(0, 10))} · Every link and number
  is re-verified from the YouTube Data API — narrative is AI-authored, facts are not.</p>
</div></body></html>`
}

// ---------------------------------------------------------------------------
// Download / clipboard helpers
// ---------------------------------------------------------------------------

/** Trigger a browser download of `content` as `filename` with the given MIME. */
export function downloadFile(filename: string, content: string, mime: string): void {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  // Revoke on the next tick so the download has started.
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

export function downloadMarkdown(result: ResearchResult): void {
  downloadFile(`${exportBasename(result)}.md`, toMarkdown(result), 'text/markdown')
}

export function downloadHtml(result: ResearchResult): void {
  downloadFile(`${exportBasename(result)}.html`, toHtml(result), 'text/html')
}
