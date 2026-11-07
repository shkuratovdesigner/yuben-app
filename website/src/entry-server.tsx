import { StrictMode } from 'react';
import { renderToString } from 'react-dom/server';
import { App } from './app';

export function render() {
  return renderToString(<StrictMode><App /></StrictMode>);
}
