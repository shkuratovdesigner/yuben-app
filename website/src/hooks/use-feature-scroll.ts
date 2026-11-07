import { useEffect, useState, type RefObject } from 'react';
import { stageAt } from '../lib/story';

export const STORY_QUERY = '(min-width: 1024px) and (min-height: 700px)';

/**
 * Tracks which feature stage is showing on desktop: the pinned scroll
 * distance through the story is divided equally between the stages.
 * One passive scroll listener, rAF-throttled, runs only while the story is
 * near the viewport. Selection uses measured geometry, never callback order,
 * so fast or reverse scrolling lands on the right stage without replaying
 * the ones it skipped.
 */
export function useFeatureScroll(section: RefObject<HTMLElement | null>, stepsSelector: string) {
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
      // The copy is pinned while the steps list scrolls past; split that
      // pinned distance into equal parts, one per stage.
      const steps = root.querySelector<HTMLElement>(stepsSelector);
      if (!steps) return;
      const r = steps.getBoundingClientRect();
      const count = steps.children.length;
      const next = stageAt(-r.top, r.height - window.innerHeight, count, current);
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
  }, [section, stepsSelector]);

  return { active, enabled };
}
