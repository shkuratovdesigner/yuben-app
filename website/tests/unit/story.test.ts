import { test } from 'node:test';
import assert from 'node:assert/strict';
import { pickStage } from '../../src/lib/story.ts';

const centers = [400, 1200, 2000]; // screenshot centres; the viewport anchor moves as you scroll

test('selects the stage nearest the anchor', () => {
  assert.equal(pickStage(centers, 380, 0), 0);
  assert.equal(pickStage(centers, 1250, 0), 1);
  assert.equal(pickStage(centers, 2100, 1), 2);
});

test('holds the current stage inside the hysteresis band', () => {
  // Midpoint between 0 and 1 is 800; within ±12px the gain is under 24px.
  assert.equal(pickStage(centers, 805, 0), 0);
  assert.equal(pickStage(centers, 795, 1), 1);
  assert.equal(pickStage(centers, 830, 0), 1);
  assert.equal(pickStage(centers, 770, 1), 0);
});

test('jumps directly after a fast scroll in either direction', () => {
  assert.equal(pickStage(centers, 2050, 0), 2);
  assert.equal(pickStage(centers, 350, 2), 0);
});

test('reverses correctly through a scroll sequence', () => {
  let current = 0;
  const path = [400, 700, 820, 1200, 1700, 1610, 1580, 900, 790, 760, 300];
  const seen = path.map((y) => (current = pickStage(centers, y, current)));
  assert.deepEqual(seen, [0, 0, 1, 1, 2, 2, 1, 1, 1, 0, 0]);
});

test('handles empty and out-of-range input', () => {
  assert.equal(pickStage([], 100, 0), 0);
  assert.equal(pickStage(centers, 1990, 7), 2);
});
