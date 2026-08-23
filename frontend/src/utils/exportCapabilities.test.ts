import { describe, expect, it } from "vitest";
import type { TrackSummaryItem } from "../api/types";
import { canExportFormat, exportUnavailableReason } from "./exportCapabilities";

const track = (family: string): TrackSummaryItem => ({
  index: 0,
  name: family,
  family,
  is_guitar: family === "guitar",
  role: "unknown",
  confidence: 1,
  note_count: 1,
});

describe("export capabilities", () => {
  it("keeps score and band MIDI exports available for non-guitar projects", () => {
    expect(canExportFormat("gp5", [track("keys")])).toBe(true);
    expect(canExportFormat("musicxml", [track("drums")])).toBe(true);
    expect(canExportFormat("humanized_midi", [track("bass")])).toBe(true);
  });

  it("requires a guitar track for Ample Eclipse exports", () => {
    expect(canExportFormat("ample_midi", [track("keys")])).toBe(false);
    expect(canExportFormat("humanized_ample_eclipse_midi", [track("guitar")])).toBe(true);
    expect(exportUnavailableReason("ample_midi", [track("drums")])).toContain("guitar");
  });
});
