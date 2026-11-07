import { useEffect, useState, type RefObject } from 'react';
import { pickStage } from '../lib/story';

export const STORY_QUERY = '(min-width: 1024px) and (min-height: 700px)';

/**
 * Tracks which feature stage is showing on desktop: the one whose
 * screenshot is nearest the viewport centre.
 * One passive scroll listener, rAF-throttled, runs only while the story is
 * near the viewport. Selection uses measured geometry, never callback order,
 * so fast or reverse scrolling lands on the right stage without replaying
 * the ones it skipped.
 */
export function useFeatureScroll(section: RefObject<HTMLElement | null>, shotSelector: string) {
  const [active, setActive] = useState(0);
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    const root = section.current;
    if (!root) return;
    const mode = window.matchMedia(STORY_QUERY);
    let current = 0;
    let frame = 0;
    let near = false;

    const measure = () => {
      frame = 0;
      if (!mode.matches) return;
      // The copy follows whichever screenshot is nearest the viewport centre.
      const shots = root.querySelectorAll<HTMLElement>(shotSelector);
      const centers = Array.from(shots, (el) => {
        const r = el.getBoundingClientRect();
        return r.top + r.height / 2;
      });
      const next = pickStage(centers, window.innerHeight / 2, current);
      if (next !== current) { current = next; setActive(next); }
    };
    const schedule = () => { if (near && !frame) frame = requestAnimationFrame(measure); };
    const now = () => { cancelAnimationFrame(frame); measure(); };

    const gate = new IntersectionObserver(([entry]) => {
      near = entry.isIntersecting;
      if (near) now();
    }, { rootMargin: '50% 0px' });
    gate.observe(root);

    const onMode = () => { setEnabled(mode.matches); now(); };
    onMode();
    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', now);
    window.addEventListener('pageshow', now); // back/forward cache restores
    mode.addEventListener('change', onMode);
    return () => {
      cancelAnimationFrame(frame);
      gate.disconnect();
      window.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', now);
      window.removeEventListener('pageshow', now);
      mode.removeEventListener('change', onMode);
    };
  }, [section, shotSelector]);

  return { active, enabled };
}
