import * as React from 'react'

import { cn } from '@/lib/utils'

/** Base input — 52px tall, rounded-[12px], border #d5d5d6 (Figma Select field). */
const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type, ...props }, ref) => (
    <input
      ref={ref}
      type={type}
      className={cn(
        'flex h-[52px] w-full rounded-[var(--radius-field)] border border-input bg-background px-3.5 text-base text-foreground',
        'placeholder:text-brand-muted outline-none',
        'focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30',
        'disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    />
  ),
)
Input.displayName = 'Input'

export { Input }
