import { test } from 'node:test';
import assert from 'node:assert/strict';
import { analyticsAllowed, initAnalytics, trackCommandCopy, GA_MEASUREMENT_ID } from '../../src/lib/analytics.ts';

test('analytics is restricted to the production YuBen domain', () => {
  for (const host of ['localhost', '127.0.0.1', 'yuben.vercel.app', 'preview.yubenapp.org', 'yubenapp.org.evil.test']) {
    assert.equal(analyticsAllowed(true, host), false);
  }
  assert.equal(analyticsAllowed(false, 'yubenapp.org'), false);
  assert.equal(analyticsAllowed(true, 'yubenapp.org'), true);
  assert.equal(analyticsAllowed(true, 'www.yubenapp.org'), true);
});

test('loads the tag once, strips query strings and tracks command copies', () => {
  const scripts: { src?: string }[] = [];
  const win = {
    location: { hostname: 'yubenapp.org', origin: 'https://yubenapp.org', pathname: '/', search: '?email=private@example.com' },
    dataLayer: [] as unknown[],
    gtag: undefined as undefined | ((...args: unknown[]) => void),
  };
  Object.assign(globalThis, { window: win, document: { createElement: () => ({}), head: { appendChild: (s: { src?: string }) => scripts.push(s) } } });
  try {
    initAnalytics(false);
    trackCommandCopy('hero', true);
    assert.equal(scripts.length, 0);
    initAnalytics(true);
    initAnalytics(true);
    assert.equal(scripts.length, 1);
    assert.ok(scripts[0].src?.endsWith(GA_MEASUREMENT_ID));
    trackCommandCopy('hero', true);
    trackCommandCopy('closing', false);
    const events = win.dataLayer.map((args) => Array.from(args as ArrayLike<unknown>));
    assert.equal(events[1][1], GA_MEASUREMENT_ID);
    assert.equal((events[1][2] as { page_location: string }).page_location, 'https://yubenapp.org/');
    assert.deepEqual(events.slice(2), [
      ['event', 'copy_install_command', { placement: 'hero', copied: true }],
      ['event', 'copy_install_command', { placement: 'closing', copied: false }],
    ]);
    assert.ok(!JSON.stringify(events).includes('private@example.com'));
    win.gtag = () => { throw new Error('blocked'); };
    assert.doesNotThrow(() => trackCommandCopy('hero', true));
  } finally {
    Reflect.deleteProperty(globalThis, 'window');
    Reflect.deleteProperty(globalThis, 'document');
  }
});
