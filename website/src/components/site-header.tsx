import { useCallback, useEffect, useRef, useState } from 'react';
import { nav, repoUrl, starCount } from '../data/site-content';
import { CloseIcon, GitHubIcon, LogoMark, MenuIcon, StarIcon } from './icons';

const EXIT_MS = 180;

function GitHubButton({ className = '', size = 18 }: { className?: string; size?: number }) {
  return (
    // The accessible name is the visible text ("GitHub 19") plus a hidden " stars".
    <a className={`btn-gray github-btn ${className}`} href={repoUrl}>
      <GitHubIcon size={size} />
      <span className="github-label">GitHub</span>{' '}
      <span className="github-stars">
        <StarIcon size={size} />
        <span className="tabular">{starCount}</span>
        <span className="sr-only"> stars</span>
      </span>
    </a>
  );
}

/** Locks page scroll while keeping the current position, and returns a restore function. */
function lockScroll() {
  const y = window.scrollY;
  const body = document.body.style;
  const prev = { position: body.position, top: body.top, width: body.width, overflow: body.overflow };
  Object.assign(body, { position: 'fixed', top: `-${y}px`, width: '100%', overflow: 'hidden' });
  return () => {
    Object.assign(body, prev);
    const html = document.documentElement;
    const behavior = html.style.scrollBehavior;
    html.style.scrollBehavior = 'auto';
    window.scrollTo(0, y);
    html.style.scrollBehavior = behavior;
  };
}

export function SiteHeader() {
  const [state, setState] = useState<'closed' | 'open' | 'closing'>('closed');
  const toggleRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const unlock = useRef<(() => void) | null>(null);
  const exitTimer = useRef<number | undefined>(undefined);

  const close = useCallback((after?: () => void, restoreFocus = true) => {
    window.clearTimeout(exitTimer.current);
    setState((s) => (s === 'closed' ? s : 'closing'));
    unlock.current?.();
    unlock.current = null;
    after?.();
    if (restoreFocus) toggleRef.current?.focus({ preventScroll: true });
    exitTimer.current = window.setTimeout(() => setState('closed'), EXIT_MS);
  }, []);

  const open = () => {
    window.clearTimeout(exitTimer.current);
    unlock.current ??= lockScroll();
    setState('open');
  };

  useEffect(() => {
    if (state !== 'open') return;
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close();
      if (event.key !== 'Tab' || !dialogRef.current) return;
      // Move focus ourselves: Safari skips links on Tab by default, which would escape the menu.
      event.preventDefault();
      const items = Array.from(dialogRef.current.querySelectorAll<HTMLElement>('a[href], button'));
      const at = items.indexOf(document.activeElement as HTMLElement);
      const next = (at + (event.shiftKey ? -1 : 1) + items.length) % items.length;
      items[at === -1 ? 0 : next].focus();
    };
    // Rotating to a wide layout hides the menu button; close instead of leaving a locked page.
    const wide = window.matchMedia('(min-width: 768px)');
    const onWide = () => { if (wide.matches) close(undefined, false); };
    document.addEventListener('keydown', onKey);
    wide.addEventListener('change', onWide);
    return () => {
      document.removeEventListener('keydown', onKey);
      wide.removeEventListener('change', onWide);
    };
  }, [state, close]);

  useEffect(() => () => { unlock.current?.(); window.clearTimeout(exitTimer.current); }, []);

  const onNav = (event: React.MouseEvent<HTMLAnchorElement>, href: string) => {
    if (!href.startsWith('#')) return;
    event.preventDefault();
    close(() => {
      document.querySelector(href)?.scrollIntoView();
      history.pushState(null, '', href);
    }, false);
  };

  return (
    <header className="site-header">
      <div className="header-row">
        <a className="brand" href="#top" aria-label="YuBen home">
          <LogoMark />
          <span>YuBen</span>
        </a>
        <nav className="header-nav" aria-label="Main">
          {nav.map((item) => (
            <a key={item.label} href={item.href} className="nav-link">{item.label}</a>
          ))}
        </nav>
        <GitHubButton className="github-header" />
        <button
          ref={toggleRef}
          type="button"
          className="menu-toggle"
          aria-label="Open menu"
          aria-expanded={state === 'open'}
          aria-controls="mobile-menu"
          onClick={open}
        >
          <MenuIcon />
        </button>
      </div>
      {state !== 'closed' && (
        <div
          ref={dialogRef}
          id="mobile-menu"
          className="mobile-menu"
          data-state={state}
          role="dialog"
          aria-modal="true"
          aria-label="Menu"
        >
          <div className="menu-top">
            <a className="brand" href="#top" onClick={(e) => onNav(e, '#top')}>
              <LogoMark size={24} />
              <span>YuBen</span>
            </a>
            <button ref={closeRef} type="button" className="btn-gray menu-close" aria-label="Close menu" onClick={() => close()}>
              <CloseIcon />
            </button>
          </div>
          <nav className="menu-links" aria-label="Mobile">
            {nav.map((item, i) => (
              <a key={item.label} href={item.href} style={{ '--i': i } as React.CSSProperties} onClick={(e) => onNav(e, item.href)}>
                {item.label}
              </a>
            ))}
          </nav>
          <div className="menu-bottom">
            <GitHubButton className="github-menu" />
          </div>
        </div>
      )}
    </header>
  );
}
