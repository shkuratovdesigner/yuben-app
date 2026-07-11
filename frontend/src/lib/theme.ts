/**
 * Light/dark theme (H4). The design system was built dark-ready — index.css
 * declares `@custom-variant dark (&:is(.dark *))` and every primitive reads
 * semantic CSS variables — so a theme is just toggling `.dark` on <html>, which
 * cascades the `.dark { … }` variable overrides to everything.
 *
 * Default follows the OS (`prefers-color-scheme`); an explicit choice is
 * remembered in localStorage. Applied in main.tsx BEFORE first render to avoid
 * a flash of the wrong theme.
 */
export type Theme = 'light' | 'dark'

export const THEME_KEY = 'yuben-theme'

/** Stored choice if any, else the OS preference, else light. */
export function getInitialTheme(): Theme {
  try {
    const stored = localStorage.getItem(THEME_KEY)
    if (stored === 'light' || stored === 'dark') return stored
  } catch {
    /* localStorage unavailable (private mode) — fall through to OS/default. */
  }
  if (typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches) {
    return 'dark'
  }
  return 'light'
}

/** Toggle the `.dark` class + native `color-scheme` (scrollbars, form controls). */
export function applyTheme(theme: Theme): void {
  const root = document.documentElement
  root.classList.toggle('dark', theme === 'dark')
  root.style.colorScheme = theme
}

export function storeTheme(theme: Theme): void {
  try {
    localStorage.setItem(THEME_KEY, theme)
  } catch {
    /* best-effort persistence */
  }
}
