/**
 * Playback intent for the demo video. Intent changes only through explicit
 * events (user controls, reduced motion, another video taking over, or a
 * browser refusal). Scrolling away or hiding the tab never changes intent;
 * it only suspends playback, so a user pause survives scrolling back.
 */
export type IntentEvent = 'user-play' | 'user-pause' | 'reduced-motion' | 'other-media' | 'blocked' | 'failed';

export const initialIntent = (reducedMotion: boolean): boolean => !reducedMotion;

export function nextIntent(_current: boolean, event: IntentEvent): boolean {
  return event === 'user-play';
}

export type Environment = { visible: boolean; documentHidden: boolean; loaded: boolean };

export const mayPlay = (intent: boolean, env: Environment): boolean =>
  intent && env.visible && !env.documentHidden && env.loaded;
