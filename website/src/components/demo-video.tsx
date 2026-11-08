import { useEffect, useRef, useState } from 'react';
import { demo } from '../data/site-content';
import { prefersReducedMotion } from '../hooks/use-reduced-motion';
import { initialIntent, mayPlay, nextIntent, type IntentEvent } from '../lib/playback';
import { PauseIcon, PlayIcon, SoundOffIcon, SoundOnIcon } from './icons';

export const OTHER_MEDIA_EVENT = 'yuben:other-media';
type Status = 'idle' | 'loading' | 'blocked' | 'failed';

/**
 * Hero demo, adapted from the portfolio's playback-intent player.
 * Visibility suspends playback; only explicit actions change intent.
 * The supplied MP4 (music and effects included) is used as is.
 */
export function DemoVideo() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const intent = useRef(true);
  const pending = useRef(false);
  const request = useRef(0);
  const api = useRef({ sync: () => {}, load: () => {} });
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(true);
  const [status, setStatus] = useState<Status>('idle');

  useEffect(() => {
    const video = videoRef.current!;
    let active = true;
    let visible = false;
    let loaded = false;
    intent.current = initialIntent(prefersReducedMotion());
    video.muted = true;

    const canPlay = () => active && mayPlay(intent.current, { visible, documentHidden: document.hidden, loaded });
    const pause = () => { request.current++; pending.current = false; video.pause(); };
    const sync = () => {
      if (!canPlay()) { pause(); return; }
      if (pending.current || !video.paused) return;
      const id = ++request.current;
      pending.current = true;
      setStatus('loading');
      // play() is called synchronously so a button press keeps its user activation.
      video.play().then(() => {
        if (!active || id !== request.current) return;
        pending.current = false;
        setStatus('idle');
        if (!canPlay()) video.pause();
      }).catch((error: DOMException) => {
        if (!active || id !== request.current) return;
        pending.current = false;
        if (error.name === 'AbortError') { setStatus('idle'); return; }
        if (error.name === 'NotSupportedError') return; // onError reports it
        intent.current = nextIntent(intent.current, error.name === 'NotAllowedError' ? 'blocked' : 'failed');
        setStatus(error.name === 'NotAllowedError' ? 'blocked' : 'failed');
      });
    };
    const load = () => {
      if (loaded) return;
      loaded = true;
      video.src = demo.src;
      video.load();
    };
    const change = (event: IntentEvent) => { intent.current = nextIntent(intent.current, event); sync(); };
    api.current = { sync, load };

    const onPlaying = () => { if (active) { setStatus('idle'); setPlaying(true); } };
    const onPause = () => { if (active) { setPlaying(false); setStatus((s) => (s === 'loading' ? 'idle' : s)); } };
    const onVolume = () => { if (active) setMuted(video.muted || video.volume === 0); };
    const onWaiting = () => { if (active && intent.current && !video.paused) setStatus('loading'); };
    const onError = () => {
      if (!active) return;
      pause();
      intent.current = nextIntent(intent.current, 'failed');
      setPlaying(false);
      setStatus('failed');
    };
    const events = { playing: onPlaying, pause: onPause, volumechange: onVolume, waiting: onWaiting, error: onError };
    Object.entries(events).forEach(([name, fn]) => video.addEventListener(name, fn));

    // The 4.5 MB source waits until the page has loaded and gone idle, so it never
    // competes with the first paint; the poster shows until then. A press on Play
    // loads it at once.
    let near = false;
    let pageReady = false;
    const hasIdle = 'requestIdleCallback' in window;
    let graceTimer = 0;
    let idleHandle = 0;
    const markReady = () => {
      const run = () => { pageReady = true; if (near) { load(); sync(); } };
      // A short grace period after load keeps the video's bandwidth away from the
      // first paint on slow connections.
      graceTimer = window.setTimeout(() => {
        if (hasIdle) idleHandle = window.requestIdleCallback(run, { timeout: 2000 });
        else run();
      }, 1200);
    };
    if (document.readyState === 'complete') markReady();
    else window.addEventListener('load', markReady, { once: true });

    const viewport = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting && entry.intersectionRatio >= 0.1;
      near = entry.isIntersecting;
      if (near && pageReady) load();
      sync();
    }, { threshold: [0, 0.1], rootMargin: '200px 0px' });
    viewport.observe(video);

    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const onMotion = () => { if (motion.matches) change('reduced-motion'); };
    const onOther = () => change('other-media');
    document.addEventListener('visibilitychange', sync);
    motion.addEventListener('change', onMotion);
    window.addEventListener(OTHER_MEDIA_EVENT, onOther);
    return () => {
      active = false;
      pause();
      viewport.disconnect();
      window.removeEventListener('load', markReady);
      window.clearTimeout(graceTimer);
      if (hasIdle && idleHandle) window.cancelIdleCallback(idleHandle);
      document.removeEventListener('visibilitychange', sync);
      motion.removeEventListener('change', onMotion);
      window.removeEventListener(OTHER_MEDIA_EVENT, onOther);
      Object.entries(events).forEach(([name, fn]) => video.removeEventListener(name, fn));
    };
  }, []);

  const play = () => {
    intent.current = nextIntent(intent.current, 'user-play');
    setStatus('idle');
    api.current.load();
    if (videoRef.current?.error) videoRef.current.load();
    api.current.sync();
  };
  const toggle = () => {
    if (!videoRef.current!.paused || pending.current) {
      intent.current = nextIntent(intent.current, 'user-pause');
      api.current.sync();
    } else play();
  };
  const toggleSound = () => {
    const video = videoRef.current!;
    const silent = video.muted || video.volume === 0;
    video.muted = !silent;
    if (silent && video.volume === 0) video.volume = 1;
    // Turning sound on is an explicit wish to hear it, so start playback too.
    if (silent && video.paused) play();
  };

  return (
    <figure className="demo" aria-label={demo.description}>
      <div className="demo-frame">
        <video
          ref={videoRef}
          className="demo-video"
          poster={demo.poster}
          width={demo.width}
          height={demo.height}
          loop
          muted
          playsInline
          preload="none"
          aria-label={demo.description}
        />
        {status === 'blocked' && (
          <button type="button" className="demo-fallback btn-gray" onClick={play}>Play demo</button>
        )}
      </div>
      <div className="demo-controls">
        <button type="button" className="btn-gray demo-btn" onClick={toggle} aria-label={playing ? 'Pause demo' : 'Play demo'}>
          <span className="t-icon-swap" data-state={playing ? 'a' : 'b'} aria-hidden="true">
            <span className="t-icon" data-icon="a"><PauseIcon /></span>
            <span className="t-icon" data-icon="b"><PlayIcon /></span>
          </span>
        </button>
        <button
          type="button"
          className="btn-gray demo-btn"
          onClick={toggleSound}
          aria-label={muted ? 'Turn demo sound on' : 'Turn demo sound off'}
          aria-pressed={!muted}
        >
          <span className="t-icon-swap" data-state={muted ? 'a' : 'b'} aria-hidden="true">
            <span className="t-icon" data-icon="a"><SoundOffIcon /></span>
            <span className="t-icon" data-icon="b"><SoundOnIcon /></span>
          </span>
        </button>
      </div>
      <p className="demo-status" role="status">
        {status === 'failed' && <>Video unavailable. <a href={demo.src}>Open the video</a> or press play to retry.</>}
      </p>
      <noscript>
        <p className="demo-status"><a href={demo.src}>Watch the YuBen demo</a></p>
      </noscript>
    </figure>
  );
}
