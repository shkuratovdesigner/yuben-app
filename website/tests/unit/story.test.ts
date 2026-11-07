import { test } from 'node:test';
import assert from 'node:assert/strict';
import { stageAt } from '../../src/lib/story.ts';

const range = 3000; // three equal 1000px segments

test('splits the pinned range into equal segments', () => {
  assert.equal(stageAt(0, range, 3, 0), 0);
  assert.equal(stageAt(999, range, 3, 0), 0);
  assert.equal(stageAt(1500, range, 3, 1), 1);
  assert.equal(stageAt(2500, range, 3, 2), 2);
});

test('clamps before and after the pinned range', () => {
  assert.equal(stageAt(-400, range, 3, 0), 0);
  assert.equal(stageAt(5000, range, 3, 2), 2);
});

test('holds the current stage just past a boundary', () => {
  assert.equal(stageAt(1010, range, 3, 0), 0);
  assert.equal(stageAt(1030, range, 3, 0), 1);
  assert.equal(stageAt(990, range, 3, 1), 1);
  assert.equal(stageAt(970, range, 3, 1), 0);
});

test('jumps directly after a fast scroll in either direction', () => {
  assert.equal(stageAt(2600, range, 3, 0), 2);
  assert.equal(stageAt(100, range, 3, 2), 0);
  assert.equal(stageAt(2010, range, 3, 0), 2); // hysteresis only guards a neighbour
});

test('reverses correctly through a scroll sequence', () => {
  let current = 0;
  const path = [0, 900, 1010, 1100, 2100, 1990, 1970, 1000, 985, 960, 0];
  const seen = path.map((y) => (current = stageAt(y, range, 3, current)));
  assert.deepEqual(seen, [0, 0, 0, 1, 2, 2, 1, 1, 1, 0, 0]);
});

test('handles empty and out-of-range input', () => {
  assert.equal(stageAt(100, 0, 3, 0), 0);
  assert.equal(stageAt(100, range, 0, 0), 0);
  assert.equal(stageAt(2500, range, 3, 7), 2);
});
