import { describe, expect, it } from "vitest";
import { stepScoreScale } from "./scoreView";

describe("score view", () => {
  it("steps through bounded notation zoom presets", () => {
    expect(stepScoreScale(1, -1)).toBe(0.9);
    expect(stepScoreScale(1, 1)).toBe(1.1);
    expect(stepScoreScale(0.75, -1)).toBe(0.75);
    expect(stepScoreScale(1.5, 1)).toBe(1.5);
  });
});
