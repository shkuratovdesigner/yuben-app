import { useSyncExternalStore } from 'react';

const query = '(prefers-reduced-motion: reduce)';

const subscribe = (notify: () => void) => {
  const list = window.matchMedia(query);
  list.addEventListener('change', notify);
  return () => list.removeEventListener('change', notify);
};

/** False during server rendering; follows the OS setting after hydration. */
export function useReducedMotion() {
  return useSyncExternalStore(subscribe, () => window.matchMedia(query).matches, () => false);
}

export const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia(query).matches;
