import { useEffect, useRef, useState } from 'react';
import { shorts } from '../data/site-content';
import { OTHER_MEDIA_EVENT } from './demo-video';
import { ShortPlayIcon } from './icons';

/**
 * Shorts play in place: activating a card swaps its thumbnail for a
 * privacy-enhanced YouTube embed inside the same card. Only one plays at a
 * time; starting one pauses the demo. Without JavaScript the card is a plain
 * link to the Short on YouTube.
 */
export function ShortsGallery() {
  const [playing, setPlaying] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const trackRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<HTMLIFrameElement>(null);

  // Mobile swipe gallery: dots follow the card nearest the track's start.
  useEffect(() => {
    const track = trackRef.current;
    if (!track) return;
    let frame = 0;
    const onScroll = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const cards = Array.from(track.children) as HTMLElement[];
        const left = track.getBoundingClientRect().left;
        let best = 0;
        cards.forEach((card, i) => {
          if (Math.abs(card.getBoundingClientRect().left - left) < Math.abs(cards[best].getBoundingClientRect().left - left)) best = i;
        });
        setPage(best);
      });
    };
    track.addEventListener('scroll', onScroll, { passive: true });
    return () => { cancelAnimationFrame(frame); track.removeEventListener('scroll', onScroll); };
  }, []);

  // Keep keyboard focus on the card that just started playing.
  useEffect(() => { if (playing) frameRef.current?.focus(); }, [playing]);

  const play = (id: string) => {
    window.dispatchEvent(new Event(OTHER_MEDIA_EVENT));
    setPlaying(id);
  };

  const goTo = (i: number) => {
    const card = trackRef.current?.children[i] as HTMLElement | undefined;
    card?.scrollIntoView({ block: 'nearest', inline: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  };

  return (
    <>
      <div className="shorts-track" ref={trackRef}>
        {shorts.map((short) => (
          <div key={short.id} className="short-card" data-playing={playing === short.id}>
            {playing === short.id ? (
              <iframe
                ref={frameRef}
                className="short-embed"
                src={`https://www.youtube-nocookie.com/embed/${short.id}?autoplay=1&playsinline=1&rel=0`}
                title={`${short.label.replace('Play ', '')} on YouTube`}
                allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
                allowFullScreen
              />
            ) : (
              <a
                className="short-link"
                href={`https://www.youtube.com/shorts/${short.id}`}
                onClick={(e) => { e.preventDefault(); play(short.id); }}
                aria-label={short.label}
              >
                <img src={short.thumb} alt="" width="304" height="540" loading="lazy" decoding="async" />
                <span className="btn-teal short-play" aria-hidden="true"><ShortPlayIcon /></span>
              </a>
            )}
          </div>
        ))}
      </div>
      <div className="shorts-dots" aria-hidden="true">
        {shorts.map((short, i) => (
          <button key={short.id} type="button" tabIndex={-1} data-on={i === page} onClick={() => goTo(i)} />
        ))}
      </div>
    </>
  );
}
