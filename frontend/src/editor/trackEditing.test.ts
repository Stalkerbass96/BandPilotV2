import { describe, expect, it } from "vitest";
import type { ScoreDocument, ScoreTrack } from "../api/types";
import { applyOperationsLocally } from "./scoreEditing";
import { createEmptyTrack, formatTuning, parseTuning, prepareTrackSetup } from "./trackEditing";

function guitarTrack(): ScoreTrack {
  return {
    id: "track:guitar",
    order: 0,
    name: "Guitar",
    family: "guitar",
    role: "rhythm",
    source_track_indices: [],
    instrument: { tuning: [40, 45, 50, 55, 59, 64], fret_count: 24, capo: 0, program: 25 },
    staves: [{ id: "staff:guitar", order: 0, kind: "standard_tab", line_count: 5 }],
    notation_mode: "standard_tab",
    mixer: { volume: 0.8, pan: 0, mute: false, solo: false },
    measures: [{
      id: "measure:1",
      number: 1,
      start: { numerator: 0, denominator: 1 },
      duration: { numerator: 4, denominator: 1 },
      numerator: 4,
      denominator: 4,
      annotations: {},
      beats: [{
        id: "beat:1",
        start: { numerator: 0, denominator: 1 },
        duration: { numerator: 1, denominator: 1 },
        voice: 1,
        staff_id: "staff:guitar",
        kind: "notes",
        tie_in: false,
        tie_out: false,
        properties: {},
        notes: [{
          id: "note:1",
          pitch: 64,
          source: null,
          technique_ids: [],
          properties: {},
          realization: {
            kind: "guitar",
            string: 1,
            fret: 0,
            fretting_digit: null,
            hand_position: null,
            piece: null,
            sticking: null,
            hit_technique: null,
            hand: null,
            finger: null,
            pedal: null,
          },
        }],
      }],
    }],
  };
}

function document(): ScoreDocument {
  return {
    id: "document:tracks",
    schema_version: "3.0",
    title: "Tracks",
    source: {},
    analysis: {},
    tracks: [guitarTrack()],
    tempo_map: [],
    time_signatures: [],
    techniques: [],
    performance: {
      profile_id: "source-preserved",
      events: [{
        id: "performance:1",
        note_id: "note:1",
        start: { numerator: 0, denominator: 1 },
        duration: { numerator: 1, denominator: 1 },
        velocity: 80,
        controls: [],
      }],
    },
    unresolved_events: [],
    validation: { status: "passed", issues: [] },
    pins: {},
    arrangement_mode: "band",
    knowledge: null,
    transformations: [],
    warnings: [],
  };
}

describe("track editing", () => {
  it("creates an empty family track aligned to the current score", () => {
    let counter = 0;
    const track = createEmptyTrack(document(), "drums", () => String(++counter));
    expect(track.family).toBe("drums");
    expect(track.notation_mode).toBe("percussion");
    expect(track.measures.map((measure) => measure.start)).toEqual([{ numerator: 0, denominator: 1 }]);
    expect(track.measures[0]?.beats).toEqual([]);
  });

  it("retunes without changing pitch by recalculating playable frets", () => {
    const source = document();
    const operations = prepareTrackSetup(source.tracks[0]!, {
      name: "Drop Guitar",
      notationMode: "tablature",
      program: 29,
      capo: 1,
      tuning: [38, 45, 50, 55, 59, 62],
    });
    const changed = applyOperationsLocally(source, operations);
    expect(changed.tracks[0]?.name).toBe("Drop Guitar");
    expect(changed.tracks[0]?.notation_mode).toBe("tablature");
    expect(changed.tracks[0]?.instrument.capo).toBe(1);
    expect(changed.tracks[0]?.measures[0]?.beats[0]?.notes[0]?.pitch).toBe(64);
    expect(changed.tracks[0]?.measures[0]?.beats[0]?.notes[0]?.realization.fret).toBe(1);
  });

  it("rejects an unplayable tuning and parses concise tuning input", () => {
    expect(parseTuning("40, 45 50,55,59,64")).toEqual([40, 45, 50, 55, 59, 64]);
    expect(parseTuning("E2 A2 D3 G3 B3 E4")).toEqual([40, 45, 50, 55, 59, 64]);
    expect(formatTuning([40, 45, 50, 55, 59, 64])).toBe("E2 A2 D3 G3 B3 E4");
    expect(() => prepareTrackSetup(guitarTrack(), {
      name: "Impossible",
      notationMode: "standard_tab",
      program: 25,
      capo: 24,
      tuning: [80, 81, 82, 83],
    })).toThrow(/cannot preserve note/);
  });
});
