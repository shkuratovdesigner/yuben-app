import { StrictMode } from 'react';
import { hydrateRoot } from 'react-dom/client';
import '@fontsource-variable/inter/index.css';
import '@fontsource-variable/newsreader/opsz.css';
import '@fontsource-variable/newsreader/opsz-italic.css';
import '@fontsource/ibm-plex-mono/400.css';
import './styles/tokens.css';
import './styles/site.css';
import './styles/motion.css';
import { App } from './app';
import { initAnalytics } from './lib/analytics';

hydrateRoot(document.getElementById('root')!, <StrictMode><App /></StrictMode>);

// Load the analytics tag after the page has loaded so it never competes with the demo video.
const startAnalytics = () => initAnalytics(import.meta.env.PROD);
if (document.readyState === 'complete') startAnalytics();
else window.addEventListener('load', startAnalytics, { once: true });
