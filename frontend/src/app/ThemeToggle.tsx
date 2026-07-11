import { useState } from 'react'
import { Moon, Sun } from 'lucide-react'

import { applyTheme, getInitialTheme, storeTheme, type Theme } from '@/lib/theme'

/**
 * Top-bar light/dark switch (H4). A single button that flips the theme, persists
 * the choice and re-applies it. Initial value mirrors what main.tsx already put
 * on <html> (stored choice or OS preference), so the icon is correct on load.
 */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(getInitialTheme)
  const next: Theme = theme === 'dark' ? 'light' : 'dark'

  const toggle = () => {
    setTheme(next)
    storeTheme(next)
    applyTheme(next)
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={`Switch to ${next} mode`}
      title={`Switch to ${next} mode`}
      className="flex size-8 items-center justify-center rounded-full text-brand-grey outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/40"
    >
      {theme === 'dark' ? <Sun className="size-5" aria-hidden /> : <Moon className="size-5" aria-hidden />}
    </button>
  )
}
