import * as React from 'react'
import * as TooltipPrimitive from '@radix-ui/react-tooltip'
import { Info } from 'lucide-react'

import { cn } from '@/lib/utils'

/**
 * Tooltip primitives. Content is portalled to <body>, which matters here: the
 * results tables live inside `TableScroll` (overflow-x: auto), and anything
 * positioned inside that container gets clipped at its edge.
 */
const TooltipProvider = TooltipPrimitive.Provider
const Tooltip = TooltipPrimitive.Root
const TooltipTrigger = TooltipPrimitive.Trigger

const TooltipContent = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 6, ...props }, ref) => (
  <TooltipPrimitive.Portal>
    <TooltipPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      className={cn(
        'z-50 max-w-[260px] rounded-[10px] border border-border bg-popover px-3 py-2',
        'text-xs font-normal normal-case leading-relaxed tracking-normal text-popover-foreground shadow-md',
        'data-[state=delayed-open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=delayed-open]:fade-in-0',
        className,
      )}
      {...props}
    />
  </TooltipPrimitive.Portal>
))
TooltipContent.displayName = TooltipPrimitive.Content.displayName

/**
 * The small ⓘ affordance used in table headers. It's a real button so it is
 * keyboard-reachable — headers that also sort keep the two as siblings rather
 * than nesting one interactive element inside another.
 */
function InfoHint({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger
        type="button"
        aria-label={`What is ${label}?`}
        // The tooltip carries the explanation; clicking must not sort.
        onClick={(e) => e.preventDefault()}
        className="inline-flex shrink-0 rounded-full text-brand-grey outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/40"
      >
        <Info className="size-3.5" aria-hidden />
      </TooltipTrigger>
      <TooltipContent>{children}</TooltipContent>
    </Tooltip>
  )
}

export { TooltipProvider, Tooltip, TooltipTrigger, TooltipContent, InfoHint }
