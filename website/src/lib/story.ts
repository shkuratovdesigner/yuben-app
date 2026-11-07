/**
 * Picks the feature stage whose screenshot centre is nearest the viewport
 * centre. The current stage keeps priority until another is closer by more
 * than `hysteresis` px, so tiny reversals at a boundary do not flicker.
 * Pure function: it always answers from geometry, so fast scrolls jump
 * straight to the right stage instead of stepping through skipped ones.
 */
export function pickStage(centers: readonly number[], anchor: number, current: number, hysteresis = 24): number {
  if (centers.length === 0) return 0;
  let nearest = 0;
  for (let i = 1; i < centers.length; i++) {
    if (Math.abs(centers[i] - anchor) < Math.abs(centers[nearest] - anchor)) nearest = i;
  }
  if (nearest === current || current < 0 || current >= centers.length) return nearest;
  const gain = Math.abs(centers[current] - anchor) - Math.abs(centers[nearest] - anchor);
  return gain > hysteresis ? nearest : current;
}
