/**
 * Global app chrome (Figma node 1:12): a top bar over an <Outlet/> canvas.
 *   • top-left  — YuBen play-mark + wordmark (links home).
 *   • top-right — "built by shkuratovdesigner" + GitHub / LinkedIn / Instagram / YouTube
 *     as the design's brand-colour badges.
 * Neutral white canvas (--background), 24px inset, generous whitespace. Each
 * screen owns its own content column (~664px centered for onboarding/composer;
 * wide + horizontally scrollable for results) — the layout doesn't constrain it.
 */
import { Link, Outlet } from 'react-router-dom'

import logoMark from '@/assets/brand/logo-mark.svg'
import { GithubIcon, InstagramIcon, LinkedinIcon, YoutubeIcon } from '@/app/social-icons'
import { ThemeToggle } from '@/app/ThemeToggle'

// Attribution + social links, opened in a new tab. GitHub / LinkedIn / YouTube
// below are still placeholder homepages — swap for the real handles when known.
const PROFILE_URL = 'https://www.shkuratovdesigner.com/'
// Order mirrors the design (Figma node 141:221).
const SOCIALS = [
  { label: 'GitHub', href: 'https://github.com/', Icon: GithubIcon },
  { label: 'LinkedIn', href: 'https://www.linkedin.com/', Icon: LinkedinIcon },
  { label: 'Instagram', href: 'https://www.instagram.com/evgeny.shkuratov', Icon: InstagramIcon },
  { label: 'YouTube', href: 'https://youtube.com/', Icon: YoutubeIcon },
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
              // The badge fills the target, so hover lifts opacity rather than
              // painting a background behind an already-opaque circle.
              className="flex size-8 rounded-full transition-opacity hover:opacity-80"
            >
              <Icon className="size-8" />
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
