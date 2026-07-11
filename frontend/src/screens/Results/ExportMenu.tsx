import { useRef, useState } from 'react'
import { Check, ChevronDown, Copy, Download, FileCode2, FileText } from 'lucide-react'

import type { ResearchResult } from '@/lib/types'
import { downloadHtml, downloadMarkdown, toMarkdown } from '@/lib/export'
import { cn } from '@/lib/utils'

/**
 * Export control for a finished run (H3). A native <details> disclosure — fully
 * keyboard-accessible, no extra dep, no click-outside plumbing — offering:
 *   • Download Markdown (.md)   • Download HTML (.html)   • Copy Markdown
 *
 * Everything is generated in the browser from the already trust-verified
 * `ResearchResult` (see lib/export.ts); nothing leaves the machine.
 */
export function ExportMenu({ result }: { result: ResearchResult }) {
  const ref = useRef<HTMLDetailsElement>(null)
  const [copied, setCopied] = useState(false)

  const close = () => {
    if (ref.current) ref.current.open = false
  }

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(toMarkdown(result))
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      // Clipboard blocked (e.g. insecure context) — fall back to a download.
      downloadMarkdown(result)
    }
    close()
  }

  const itemClass =
    'flex w-full items-center gap-2.5 rounded-[8px] px-3 py-2 text-left text-sm text-foreground outline-none transition-colors hover:bg-muted focus-visible:bg-muted'

  return (
    <details ref={ref} className="group relative [&_summary::-webkit-details-marker]:hidden">
      <summary
        className={cn(
          'flex cursor-pointer list-none items-center gap-1.5 rounded-full border border-border px-3.5 py-1.5',
          'text-sm font-medium text-foreground outline-none transition-colors',
          'hover:border-brand-selected/50 hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/40',
        )}
      >
        <Download className="size-4" aria-hidden />
        Export
        <ChevronDown className="size-3.5 text-brand-grey transition-transform group-open:rotate-180" aria-hidden />
      </summary>

      <div
        className="absolute right-0 z-20 mt-2 flex w-56 flex-col gap-0.5 rounded-[12px] border border-border bg-background p-1.5 shadow-lg"
        role="menu"
      >
        <button type="button" role="menuitem" className={itemClass} onClick={() => { downloadMarkdown(result); close() }}>
          <FileText className="size-4 shrink-0 text-brand-grey" aria-hidden />
          Download Markdown
          <span className="ml-auto text-xs text-brand-grey">.md</span>
        </button>
        <button type="button" role="menuitem" className={itemClass} onClick={() => { downloadHtml(result); close() }}>
          <FileCode2 className="size-4 shrink-0 text-brand-grey" aria-hidden />
          Download HTML
          <span className="ml-auto text-xs text-brand-grey">.html</span>
        </button>
        <button type="button" role="menuitem" className={itemClass} onClick={() => void onCopy()}>
          {copied ? (
            <Check className="size-4 shrink-0 text-brand-selected" aria-hidden />
          ) : (
            <Copy className="size-4 shrink-0 text-brand-grey" aria-hidden />
          )}
          {copied ? 'Copied to clipboard' : 'Copy Markdown'}
        </button>
      </div>
    </details>
  )
}
