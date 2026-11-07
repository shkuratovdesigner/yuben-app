import { useEffect } from 'react';

/**
 * Restrained section entrance. Content is hidden only once JS has run
 * (html.js) and only until the section nears the viewport, so nothing stays
 * hidden if scripts fail. Reduced motion skips it in CSS.
 */
export function useReveal() {
  useEffect(() => {
    const items = document.querySelectorAll<HTMLElement>('.reveal');
    if (!('IntersectionObserver' in window)) {
      items.forEach((el) => el.classList.add('is-in'));
      return;
    }
    const io = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) { entry.target.classList.add('is-in'); io.unobserve(entry.target); }
      }
    }, { rootMargin: '0px 0px -8% 0px' });
    items.forEach((el) => {
      // Already on screen (reload mid-page, anchor jump): show without animating.
      const r = el.getBoundingClientRect();
      if (r.top < window.innerHeight && r.bottom > 0) el.classList.add('is-in', 'no-anim');
      else io.observe(el);
    });
    document.documentElement.classList.add('reveal-ready');
    return () => io.disconnect();
  }, []);
}
