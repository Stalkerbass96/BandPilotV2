export const SCORE_SCALES = [0.75, 0.9, 1, 1.1, 1.25, 1.5] as const;

export function stepScoreScale(current: number, direction: -1 | 1): number {
  const nearestIndex = SCORE_SCALES.reduce((best, value, index) => (
    Math.abs(value - current) < Math.abs(SCORE_SCALES[best]! - current)
      ? index
      : best
  ), 0);
  return SCORE_SCALES[
    Math.min(Math.max(nearestIndex + direction, 0), SCORE_SCALES.length - 1)
  ]!;
}
