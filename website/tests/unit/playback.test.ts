import { test } from 'node:test';
import assert from 'node:assert/strict';
import { initialIntent, mayPlay, nextIntent, type Environment } from '../../src/lib/playback.ts';

const onScreen: Environment = { visible: true, documentHidden: false, loaded: true };

test('autoplays only without reduced motion', () => {
  assert.equal(initialIntent(false), true);
  assert.equal(initialIntent(true), false);
});

test('visibility suspends playback without changing intent', () => {
  const intent = initialIntent(false);
  assert.equal(mayPlay(intent, { ...onScreen, visible: false }), false);
  assert.equal(mayPlay(intent, { ...onScreen, documentHidden: true }), false);
  assert.equal(mayPlay(intent, onScreen), true, 'resumes when visible again');
});

test('a user pause persists across scrolling away and back', () => {
  const paused = nextIntent(true, 'user-pause');
  assert.equal(mayPlay(paused, { ...onScreen, visible: false }), false);
  assert.equal(mayPlay(paused, onScreen), false);
});

test('only an explicit play restores intent', () => {
  for (const event of ['user-pause', 'reduced-motion', 'other-media', 'blocked', 'failed'] as const) {
    assert.equal(nextIntent(true, event), false, event);
  }
  assert.equal(nextIntent(false, 'user-play'), true);
});

test('never plays before the source is loaded', () => {
  assert.equal(mayPlay(true, { ...onScreen, loaded: false }), false);
});
