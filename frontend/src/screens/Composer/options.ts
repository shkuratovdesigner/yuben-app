/**
 * Composer control options — the single place the dropdown/segment LABELS (what
 * the user sees) map to the ResearchRequest ENUM values (what the backend gets).
 *
 * Source of truth: PRD §6 (microcopy) + CONTRACTS §2 (ResearchRequest enums).
 * Because each option stores its enum `value` directly, the composer keeps enum
 * values in state and `buildRequest` needs no separate label→enum lookup table —
 * the mapping IS these arrays.
 */
import type { Format, Outperformance, UploadDate } from '@/lib/types'

/** Upload date (default "All time"). PRD §6 labels → CONTRACTS §2 enums. */
export const UPLOAD_DATE_OPTIONS: { value: UploadDate; label: string }[] = [
  { value: 'all', label: 'All time' },
  { value: '24h', label: 'Last 24 hours' },
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
  { value: '90d', label: 'Last 90 days' },
  { value: '6m', label: 'Last 6 months' },
  { value: '1y', label: 'Last year' },
]

/**
 * Outperformance (default "highest"). PRD §6 lists this option as "Highest first";
 * Figma 27:529's resting trigger reads "Highest Outperformance". Both map to
 * 'highest' (per the F3 brief) — we use the Figma wording so the resting state is
 * pixel-accurate.
 */
export const OUTPERFORMANCE_OPTIONS: { value: Outperformance; label: string }[] = [
  { value: 'any', label: 'Any' },
  { value: '2x', label: '2× and up' },
  { value: '5x', label: '5× and up' },
  { value: '10x', label: '10× and up' },
  { value: 'highest', label: 'Highest Outperformance' },
]

/**
 * Long-form / Shorts. Figma 27:529 / 29:135 have NO format control, so the brief
 * says default 'longform'. We add this subtle segmented toggle anyway because
 * capturing format is required (PRD FR-2 / Goal-5, CONTRACTS §2) — a composer
 * that can only ever request long-form is a functional dead-end.
 */
export const FORMAT_OPTIONS: { value: Format; label: string }[] = [
  { value: 'longform', label: 'Long-form' },
  { value: 'shorts', label: 'Shorts' },
]

export const UPLOAD_DATE_DEFAULT: UploadDate = 'all'
export const OUTPERFORMANCE_DEFAULT: Outperformance = 'highest'
export const FORMAT_DEFAULT: Format = 'longform'

/**
 * How many curated videos a report holds (CONTRACTS §2 `max_results`, capped at
 * 100 by the schema). The pipeline collects far more than this and B5 truncates
 * the agent's ranked list to it, so this is purely how deep the report goes —
 * raising it costs no extra YouTube quota, only more oEmbed link checks.
 */
export const MAX_RESULTS_DEFAULT = 40

/**
 * Borderless inline trigger for the control-bar + footer <Select>s. The design
 * system's SelectTrigger is a 52px bordered field; Figma's control-bar dropdowns
 * are plain 14px muted text + a small chevron, so we flatten it here (twMerge
 * wins over the base). Shared so both selects read identically.
 */
export const INLINE_SELECT_TRIGGER =
  'flex h-auto w-auto items-center justify-start gap-1.5 rounded-none border-0 bg-transparent px-0 py-0 ' +
  'text-[14px] leading-[22px] text-brand-muted outline-none transition-colors hover:text-foreground ' +
  'focus:border-0 focus:ring-0 data-[placeholder]:text-brand-muted [&>svg]:size-4 [&>svg]:text-brand-grey'

/**
 * Composer control-bar variant of the above. The bar must never wrap to a second
 * row, and its widest state ("Last 6 months" + "Highest Outperformance") lands
 * within ~5px of the 800px card, so the two selects run a tighter gap and a 14px
 * chevron — which also matches the 14px label better than the 16px one. The
 * footer's model select keeps the roomier INLINE_SELECT_TRIGGER.
 */
export const COMPOSER_SELECT_TRIGGER =
  `${INLINE_SELECT_TRIGGER} shrink-0 gap-1 whitespace-nowrap [&>svg]:size-3.5`
