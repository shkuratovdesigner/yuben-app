import { useRef } from 'react';
import { features } from '../data/site-content';
import { useFeatureScroll } from '../hooks/use-feature-scroll';
import { featurePanels } from './feature-panels';

/**
 * Desktop: one stationary copy slot, vertically centred in a sticky rail.
 * Each real UI panel scrolls in, holds level with the copy, then scrolls on.
 * Every stage gets an equal share of the scroll; the swap is a short cross-blur.
 * Narrow or short screens: three stacked text + panel blocks.
 */
export function FeatureStory() {
  const ref = useRef<HTMLElement>(null);
  const { active, enabled } = useFeatureScroll(ref, '.story-steps');

  return (
    <section ref={ref} id="how-it-works" className="story" aria-label="How it works" data-story={enabled ? 'on' : 'off'}>
      <div className="story-rail" aria-hidden="true">
        <div className="story-sticky">
          <div className="story-slot">
            {features.map((f, i) => (
              <div key={f.id} className="story-copy" data-active={i === active}>
                <p className="feature-title">{f.title}</p>
                <p className="feature-body" style={{ maxWidth: f.bodyWidth }}>{f.body}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
      <ol className="story-steps">
        {features.map((f, i) => {
          const Panel = featurePanels[i];
          return (
            <li key={f.id} className="story-step" data-step={i}>
              <div className="step-copy">
                <h2 className="feature-title">{f.title}</h2>
                <p className="feature-body" style={{ maxWidth: f.bodyWidth }}>{f.body}</p>
              </div>
              <div className="story-stage">
                <Panel />
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
