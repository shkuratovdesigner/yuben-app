// Icon paths copied from the approved Paper artboards.
type P = { className?: string; size?: number };

export const LogoMark = ({ size = 27 }: P) => (
  <svg width={size} height={size} viewBox="0 0 28 28" aria-hidden="true" className="logo-mark">
    <path d="M7 4Q7 1 10 3L25 12Q28 14 25 16L10 25Q7 27 7 24Z" fill="#00809C" />
  </svg>
);

export const GitHubIcon = ({ size = 18 }: P) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
    <path
      d="M12 2a10 10 0 0 0-3.16 19.49c.5.09.68-.22.68-.48v-1.86c-2.78.6-3.37-1.18-3.37-1.18-.45-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.61.07-.61 1 .07 1.53 1.03 1.53 1.03.89 1.53 2.34 1.09 2.91.83.09-.65.35-1.09.64-1.34-2.22-.25-4.56-1.11-4.56-4.94 0-1.09.39-1.99 1.03-2.69-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.03a9.58 9.58 0 0 1 5 0c1.91-1.3 2.75-1.03 2.75-1.03.55 1.38.2 2.4.1 2.65.64.7 1.03 1.6 1.03 2.69 0 3.84-2.34 4.69-4.57 4.94.36.31.68.92.68 1.85v2.75c0 .27.18.58.69.48A10 10 0 0 0 12 2Z"
      fill="#000"
    />
  </svg>
);

export const StarIcon = ({ size = 18 }: P) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
    <path
      d="m12 3 2.78 5.63 6.22.9-4.5 4.39 1.06 6.19L12 17.19l-5.56 2.92 1.06-6.19L3 9.53l6.22-.9Z"
      fill="#E8AD20"
      stroke="#C78E11"
      strokeWidth="1.2"
      strokeLinejoin="round"
    />
  </svg>
);

export const CopyIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <rect x="8" y="8" width="12" height="12" rx="3" fill="none" stroke="currentColor" strokeWidth="1.6" />
    <path d="M16 8V4H4v12h4" fill="none" stroke="currentColor" strokeWidth="1.6" />
  </svg>
);

export const CheckIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="m5 12.5 4.5 4.5L19 7.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const PauseIcon = () => (
  <svg viewBox="0 0 20 20" aria-hidden="true">
    <rect x="5" y="3.5" width="3.5" height="13" rx="1" fill="currentColor" />
    <rect x="11.5" y="3.5" width="3.5" height="13" rx="1" fill="currentColor" />
  </svg>
);

export const PlayIcon = () => (
  <svg viewBox="0 0 20 20" aria-hidden="true">
    <path d="M6.5 4.2v11.6c0 .6.66.97 1.17.65l9.06-5.8a.77.77 0 0 0 0-1.3L7.67 3.55a.77.77 0 0 0-1.17.65Z" fill="currentColor" />
  </svg>
);

const speaker = 'M3.25 7.25H6L10 4V16L6 12.75H3.25C2.84 12.75 2.5 12.41 2.5 12V8C2.5 7.59 2.84 7.25 3.25 7.25Z';

export const SoundOffIcon = () => (
  <svg viewBox="0 0 20 20" aria-hidden="true">
    <path d={speaker} fill="currentColor" />
    <path d="m13 7 5 6m0-6-5 6" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

export const SoundOnIcon = () => (
  <svg viewBox="0 0 20 20" aria-hidden="true">
    <path d={speaker} fill="currentColor" />
    <path d="M12.75 7.25c1.52 1.52 1.52 3.98 0 5.5M15 5c2.76 2.76 2.76 7.24 0 10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

export const MenuIcon = () => (
  <svg width="26" height="26" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M4 8h16M4 16h16" fill="none" stroke="#2B2D33" strokeWidth="1.6" strokeLinecap="round" />
  </svg>
);

export const CloseIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
    <path d="m6 6 12 12M18 6 6 18" fill="none" stroke="#2B2D33" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

export const ShortPlayIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M8 4L21 12L8 20Z" fill="#fff" stroke="#fff" strokeWidth="2.5" strokeLinejoin="round" />
  </svg>
);

/** Plus that becomes a minus: the vertical stroke collapses when open. */
export const PlusMinusIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true" className="faq-icon">
    <path d="M5.5 12h13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    <path className="faq-icon-v" d="M12 5.5v13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);
