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

hydrateRoot(document.getElementById('root')!, <StrictMode><App /></StrictMode>);
