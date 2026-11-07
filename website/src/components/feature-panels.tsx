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
        sizes="(min-width: 1024px) 60vw, 100vw"
        width={1264}
        height={843}
        alt={shot.alt}
        loading="lazy"
        decoding="async"
      />
    </figure>
  );
}
