import { features } from '../data/site-content';

/**
 * Real light-theme screenshots of the local YuBen app (captured 2026-11-08 at
 * 2x from saved reports; see readme). Three widths, picked by the browser.
 */
export function FeatureShot({ index }: { index: number }) {
  const shot = features[index].shot;
  const src = (w: number) => `/media/app-${shot.name}-${w}.webp`;
  return (
    <figure className="panel shot">
      <img
        src={src(1264)}
        srcSet={`${src(760)} 760w, ${src(1264)} 1264w, ${src(1800)} 1800w`}
        // Matches the rendered width (measured 2026-11-08): capped at 905px by the 1600px container.
        sizes="(min-width: 1960px) 905px, (min-width: 1024px) 46vw, (min-width: 768px) 83vw, calc(100vw - 42px)"
        width={1264}
        height={843}
        alt={shot.alt}
        loading="lazy"
        decoding="async"
      />
    </figure>
  );
}
