import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/utils'

/**
 * Badge — outperformance tiers (hot/warm/cool mirror build_html_report.py),
 * plus a `count` pill for the "Research history [n]" chip.
 */
const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-full border font-medium whitespace-nowrap',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-primary/10 text-primary',
        outline: 'border-border text-brand-grey',
        count: 'border-transparent bg-secondary text-secondary-foreground',
        hot: 'border-transparent bg-tier-hot/12 text-tier-hot',
        warm: 'border-transparent bg-tier-warm/12 text-tier-warm',
        cool: 'border-transparent bg-tier-cool/15 text-tier-cool',
        promoted: 'border-tier-hot/40 text-tier-hot',
      },
      size: {
        default: 'px-2.5 py-0.5 text-xs',
        sm: 'px-2 py-0.5 text-[11px]',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, size, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant, size }), className)} {...props} />
}

/** Map a VSR value to its tier variant (hot ≥5×, warm 2–5×, cool <1×, else default). */
export function vsrTier(vsr: number | null | undefined): 'hot' | 'warm' | 'cool' | 'default' {
  if (vsr == null) return 'default'
  if (vsr >= 5) return 'hot'
  if (vsr >= 2) return 'warm'
  if (vsr < 1) return 'cool'
  return 'default'
}

export { Badge, badgeVariants }
