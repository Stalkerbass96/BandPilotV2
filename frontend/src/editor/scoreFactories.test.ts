import { describe, expect, it } from "vitest";
import type { ScoreTrack } from "../api/types";
import { createFirstNoteBeat, createFirstRestBeat } from "./scoreFactories";

function blankTrack(family: string): ScoreTrack {
  const instrument = family === "guitar"
    ? { tuning: [40, 45, 50, 55, 59, 64], fret_count: 24 }
    : family === "bass"
      ? { tuning: [28, 33, 38, 43], fret_count: 24 }
      : {};
  return {
    id: `track:${family}`,
    order: 0,
    name: family,
    family,
    role: "unknown",
    source_track_indices: [],
    instrument,
    notation_mode: family === "guitar" || family === "bass" ? "standard_tab" : "standard",
    mixer: { volume: 0.8, pan: 0, mute: false, solo: false },
    staves: [{
      id: `staff:${family}`,
      order: 0,
      kind: family === "drums" ? "percussion" : "standard",
      line_count: 5,
    }],
    measures: [{
      id: `measure:${family}:1`,
      number: 1,
      start: { numerator: 0, denominator: 1 },
      duration: { numerator: 4, denominator: 1 },
      numerator: 4,
      denominator: 4,
      beats: [],
      annotations: {},
    }],
  };
}

describe("blank score first-note factory", () => {
  it.each([
    ["guitar", 64, 1, 0, null, null],
    ["bass", 43, 1, 0, null, null],
    ["drums", 38, null, null, "snare", null],
    ["keys", 60, null, null, null, "right"],
    ["generic", 60, null, null, null, null],
  ])("creates a valid %s default", (family, pitch, stringNumber, fret, piece, hand) => {
    let index = 0;
    const created = createFirstNoteBeat(blankTrack(family), () => String(++index));
    const note = created.beat.notes[0];

    expect(created.beat.voice).toBe(1);
    expect(created.beat.duration).toEqual({ numerator: 1, denominator: 1 });
    expect(note?.pitch).toBe(pitch);
    expect(note?.realization).toMatchObject({
      kind: family,
      string: stringNumber,
      fret,
      piece,
      hand,
    });
    expect(note?.realization.finger).toBe(family === "keys" ? 1 : null);
    expect(created.performanceEvents).toEqual([expect.objectContaining({
      note_id: note?.id,
      start: created.beat.start,
      duration: created.beat.duration,
      velocity: 80,
    })]);
  });

  it("creates an explicit first rest without a performance event", () => {
    const created = createFirstRestBeat(blankTrack("guitar"), () => "rest");

    expect(created.beat).toMatchObject({ kind: "rest", notes: [], voice: 1 });
  });
});
