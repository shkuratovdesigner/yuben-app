import * as React from 'react'
import { Eye, EyeOff } from 'lucide-react'

import { cn } from '@/lib/utils'

/**
 * KeyInput — masked, monospace field for the YouTube key (Onboarding Setup).
 * Defaults to hidden (password) with a show/hide toggle. The value stays local
 * and is write-only through the API; never rendered back from the server.
 */
const KeyInput = React.forwardRef<
  HTMLInputElement,
  Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'>
>(({ className, ...props }, ref) => {
  const [visible, setVisible] = React.useState(false)
  return (
    <div className="relative w-full">
      <input
        ref={ref}
        type={visible ? 'text' : 'password'}
        autoComplete="off"
        spellCheck={false}
        className={cn(
          'flex h-[52px] w-full rounded-[var(--radius-field)] border border-input bg-background pl-3.5 pr-12',
          'font-mono text-base tracking-tight text-foreground placeholder:text-brand-muted outline-none',
          'focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30',
          'disabled:cursor-not-allowed disabled:opacity-50',
          className,
        )}
        {...props}
      />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        aria-label={visible ? 'Hide key' : 'Show key'}
        className="absolute right-3 top-1/2 -translate-y-1/2 grid size-7 place-items-center rounded-md text-brand-grey hover:text-foreground"
      >
        {visible ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </button>
    </div>
  )
})
KeyInput.displayName = 'KeyInput'

export { KeyInput }
