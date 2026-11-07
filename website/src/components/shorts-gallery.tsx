import { useEffect, useRef, useState } from 'react';
import { shorts } from '../data/site-content';
import { OTHER_MEDIA_EVENT } from './demo-video';
import { CloseIcon, ShortPlayIcon } from './icons';

type Short = (typeof shorts)[number];

export function ShortsGallery() {
  const [openShort, setOpenShort] = useState<Short | null>(null);
  const [page, setPage] = useState(0);
  const trackRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

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

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (openShort && !dialog.open) {
      dialog.showModal();
      // showModal would focus the iframe, which then swallows Escape.
      closeRef.current?.focus();
    }
  }, [openShort]);

  const play = (short: Short, event: React.MouseEvent<HTMLElement>) => {
    opener.current = event.currentTarget;
    window.dispatchEvent(new Event(OTHER_MEDIA_EVENT));
    setOpenShort(short);
  };

  const close = () => dialogRef.current?.close();
  // Fires for the close button, Escape and backdrop clicks alike.
  const onClosed = () => {
    setOpenShort(null); // unmounts the iframe, which stops playback
    opener.current?.focus({ preventScroll: true });
  };

  const goTo = (i: number) => {
    const card = trackRef.current?.children[i] as HTMLElement | undefined;
    card?.scrollIntoView({ block: 'nearest', inline: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  };

  return (
    <>
      <div className="shorts-track" ref={trackRef}>
        {shorts.map((short) => (
          <a
            key={short.id}
            className="short-card"
            href={`https://www.youtube.com/shorts/${short.id}`}
            onClick={(e) => { e.preventDefault(); play(short, e); }}
            aria-label={short.label}
          >
            <img src={short.thumb} alt="" width="304" height="540" loading="lazy" decoding="async" />
            <span className="btn-teal short-play" aria-hidden="true"><ShortPlayIcon /></span>
          </a>
        ))}
      </div>
      <div className="shorts-dots" aria-hidden="true">
        {shorts.map((short, i) => (
          <button key={short.id} type="button" tabIndex={-1} data-on={i === page} onClick={() => goTo(i)} />
        ))}
      </div>
      <dialog
        ref={dialogRef}
        className="short-dialog"
        aria-label="YuBen Short"
        onClose={onClosed}
        onClick={(e) => { if (e.target === e.currentTarget) close(); }}
      >
        {openShort && (
          <div className="short-dialog-body">
            <div className="short-frame">
              <iframe
                src={`https://www.youtube-nocookie.com/embed/${openShort.id}?autoplay=1&playsinline=1&rel=0`}
                title="YuBen Short on YouTube"
                allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
                allowFullScreen
              />
            </div>
            <div className="short-dialog-bar">
              <a href={`https://www.youtube.com/shorts/${openShort.id}`} target="_blank" rel="noreferrer">
                Not loading? Watch on YouTube ↗
              </a>
              <button ref={closeRef} type="button" className="btn-gray short-close" aria-label="Close video" onClick={close}>
                <CloseIcon />
              </button>
            </div>
          </div>
        )}
      </dialog>
    </>
  );
}
