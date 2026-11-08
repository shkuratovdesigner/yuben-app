/** Google Analytics 4: property "YuBen" (account Shkuratov.designer), stream "YuBen website". */
export const GA_MEASUREMENT_ID = 'G-T6YE8VXL6B';

declare global {
  interface Window {
    dataLayer?: unknown[];
    gtag?: (...args: unknown[]) => void;
  }
}

/** Only the production domain reports; local, preview and *.vercel.app hosts never load the tag. */
export function analyticsAllowed(production: boolean, hostname: string): boolean {
  return production && (hostname === 'yubenapp.org' || hostname === 'www.yubenapp.org');
}

let initialized = false;

export function initAnalytics(production: boolean) {
  if (initialized || typeof window === 'undefined' || !analyticsAllowed(production, window.location.hostname)) return;
  initialized = true;
  window.dataLayer = window.dataLayer || [];
  window.gtag = function () {
    // gtag.js expects the Arguments object itself, not an array.
    // eslint-disable-next-line prefer-rest-params
    window.dataLayer!.push(arguments);
  };
  window.gtag('js', new Date());
  window.gtag('config', GA_MEASUREMENT_ID, {
    page_location: `${window.location.origin}${window.location.pathname}`,
    allow_google_signals: false,
    allow_ad_personalization_signals: false,
  });
  const script = document.createElement('script');
  script.async = true;
  script.src = `https://www.googletagmanager.com/gtag/js?id=${GA_MEASUREMENT_ID}`;
  document.head.appendChild(script);
}

export type CommandPlacement = 'hero' | 'closing';

/** Someone copied the `npx yuben-app@latest` command: the site's main conversion. */
export function trackCommandCopy(placement: CommandPlacement, copied: boolean) {
  if (!initialized) return;
  try {
    window.gtag?.('event', 'copy_install_command', { placement, copied });
  } catch {
    // Analytics must never break the page.
  }
}
