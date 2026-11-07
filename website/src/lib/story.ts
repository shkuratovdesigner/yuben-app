/**
 * Picks the feature stage for a scroll offset through the pinned story.
 * The pinned range is split into `count` equal segments, so every stage gets
 * the same scroll distance. Near a boundary the current stage is kept until
 * the offset is `hysteresis` px past it, so tiny reversals do not flicker.
 * Pure function: it always answers from geometry, so fast scrolls jump
 * straight to the right stage instead of stepping through the skipped ones.
 *
 * @param offset scroll distance into the pinned range (negative before it)
 * @param range  total pinned scroll distance
 */
export function stageAt(offset: number, range: number, count: number, current: number, hysteresis = 24): number {
  if (count <= 0 || range <= 0) return 0;
  const seg = range / count;
  const raw = Math.min(count - 1, Math.max(0, Math.floor(offset / seg)));
  if (raw === current || current < 0 || current >= count) return raw;
  // Only hold when the offset is just across the boundary next to the current stage.
  if (raw === current + 1 && offset - raw * seg < hysteresis) return current;
  if (raw === current - 1 && current * seg - offset < hysteresis) return current;
  return raw;
}
