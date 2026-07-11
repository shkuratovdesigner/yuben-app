/**
 * Global app chrome (Figma node 1:12): a top bar over an <Outlet/> canvas.
 *   • top-left  — YuBen play-mark + wordmark (links home).
 *   • top-right — "built by shkuratovdesigner" + GitHub / YouTube / LinkedIn.
 * Neutral white canvas (--background), 24px inset, generous whitespace. Each
 * screen owns its own content column (~664px centered for onboarding/composer;
 * wide + horizontally scrollable for results) — the layout doesn't constrain it.
 */
import { Link, Outlet } from 'react-router-dom'

import logoMark from '@/assets/brand/logo-mark.svg'
import { GithubIcon, LinkedinIcon, YoutubeIcon } from '@/app/social-icons'
import { ThemeToggle } from '@/app/ThemeToggle'

// Attribution + social links. Placeholder profile URLs — swap for the real
// shkuratovdesigner handles when known. They open in a new tab.
const PROFILE_URL = 'https://github.com/'
const SOCIALS = [
  { label: 'GitHub', href: 'https://github.com/', Icon: GithubIcon },
  { label: 'YouTube', href: 'https://youtube.com/', Icon: YoutubeIcon },
  { label: 'LinkedIn', href: 'https://www.linkedin.com/', Icon: LinkedinIcon },
] as const

function TopBar() {
  return (
    <header className="flex items-center justify-between px-6 py-6">
      <Link to="/" className="flex items-center gap-1.5" aria-label="YuBen home">
        <img src={logoMark} alt="" className="size-7" />
        <span className="text-[16px] font-medium tracking-[-0.32px] text-foreground">YuBen</span>
      </Link>

      <div className="flex items-center gap-3 sm:gap-4">
        {/* Attribution is hidden on narrow screens so the top bar never crowds. */}
        <p className="hidden text-[16px] text-brand-grey sm:block">
          built by{' '}
          <a
            href={PROFILE_URL}
            target="_blank"
            rel="noreferrer noopener"
            className="text-brand-link underline underline-offset-2"
          >
            shkuratovdesigner
          </a>
          :
        </p>
        <nav className="flex items-center gap-2">
          {SOCIALS.map(({ label, href, Icon }) => (
            <a
              key={label}
              href={href}
              target="_blank"
              rel="noreferrer noopener"
              aria-label={label}
              className="flex size-8 items-center justify-center rounded-full text-brand-grey transition-colors hover:bg-muted hover:text-foreground"
            >
              <Icon className="size-5" />
            </a>
          ))}
        </nav>
        <span aria-hidden className="h-5 w-px bg-border" />
        <ThemeToggle />
      </div>
    </header>
  )
}

export function AppLayout() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <TopBar />
      <main className="px-6 pb-20">
        <Outlet />
      </main>
    </div>
  )
}
