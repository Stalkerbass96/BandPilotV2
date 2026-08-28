export interface PlaybackRangeValue {
  startTick: number;
  endTick: number;
}

interface PlaybackBeatValue {
  absolutePlaybackStart: number;
  playbackDuration: number;
}

export const PLAYBACK_SPEEDS = [0.5, 0.6, 0.7, 0.8, 0.9, 1, 1.1, 1.25, 1.5] as const;

/** Convert one or more stable beat projections into one exact MIDI-tick range. */
export function playbackRangeForBeatGroups(
  groups: ReadonlyArray<ReadonlyArray<PlaybackBeatValue>>,
): PlaybackRangeValue | null {
  const beats = groups.flatMap((group) => [...group]);
  if (beats.length === 0) return null;
  const startTick = Math.min(...beats.map((beat) => beat.absolutePlaybackStart));
  const endTick = Math.max(...beats.map(
    (beat) => beat.absolutePlaybackStart + beat.playbackDuration,
  ));
  if (!Number.isFinite(startTick) || !Number.isFinite(endTick) || endTick <= startTick) {
    return null;
  }
  return { startTick, endTick };
}

export function stepPlaybackSpeed(current: number, direction: -1 | 1): number {
  const nearestIndex = PLAYBACK_SPEEDS.reduce((best, value, index) => (
    Math.abs(value - current) < Math.abs(PLAYBACK_SPEEDS[best]! - current)
      ? index
      : best
  ), 0);
  return PLAYBACK_SPEEDS[
    Math.min(Math.max(nearestIndex + direction, 0), PLAYBACK_SPEEDS.length - 1)
  ]!;
}
