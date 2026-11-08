import { StrictMode } from 'react';
import { hydrateRoot } from 'react-dom/client';
import './styles/fonts.css';
import '@fontsource/ibm-plex-mono/400.css';
import './styles/tokens.css';
import './styles/site.css';
import './styles/motion.css';
import { App } from './app';
import { initAnalytics } from './lib/analytics';

hydrateRoot(document.getElementById('root')!, <StrictMode><App /></StrictMode>);

// Load the analytics tag once the page has loaded and the main thread is idle,
// so it never competes with the first paint or the demo video.
const startAnalytics = () => {
  const run = () => initAnalytics(import.meta.env.PROD);
  if ('requestIdleCallback' in window) window.requestIdleCallback(run, { timeout: 3000 });
  else setTimeout(run, 500);
};
if (document.readyState === 'complete') startAnalytics();
else window.addEventListener('load', startAnalytics, { once: true });
