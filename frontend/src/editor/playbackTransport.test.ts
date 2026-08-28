import { describe, expect, it } from "vitest";
import {
  playbackRangeForBeatGroups,
  stepPlaybackSpeed,
} from "./playbackTransport";

describe("playback transport", () => {
  it("covers every rendered continuation in a stable beat selection", () => {
    expect(playbackRangeForBeatGroups([
      [
        { absolutePlaybackStart: 960, playbackDuration: 240 },
        { absolutePlaybackStart: 1200, playbackDuration: 120 },
      ],
      [{ absolutePlaybackStart: 1440, playbackDuration: 480 }],
    ])).toEqual({ startTick: 960, endTick: 1920 });
  });

  it("rejects empty or zero-length playback selections", () => {
    expect(playbackRangeForBeatGroups([])).toBeNull();
    expect(playbackRangeForBeatGroups([[
      { absolutePlaybackStart: 100, playbackDuration: 0 },
    ]])).toBeNull();
  });

  it("steps through bounded musician-facing speed presets", () => {
    expect(stepPlaybackSpeed(1, -1)).toBe(0.9);
    expect(stepPlaybackSpeed(1, 1)).toBe(1.1);
    expect(stepPlaybackSpeed(0.5, -1)).toBe(0.5);
    expect(stepPlaybackSpeed(1.5, 1)).toBe(1.5);
  });
});
