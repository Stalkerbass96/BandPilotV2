import { describe, expect, it } from "vitest";
import { model, Settings } from "@coderline/alphatab";
import type { ScoreBeat, ScoreDocument } from "../api/types";
import {
  AlphaTabAdapterError,
  buildAlphaTabScore,
  decomposeScoreDuration,
} from "./alphaTabAdapter";

function beat(id: string, startNumerator: number, durationNumerator: number, durationDenominator = 1): ScoreBeat {
  return {
    id,
    start: { numerator: startNumerator, denominator: 1 },
    duration: { numerator: durationNumerator, denominator: durationDenominator },
    voice: 1,
    staff_id: "staff:guitar",
    kind: "notes",
    tie_in: false,
    tie_out: false,
    properties: {},
    notes: [{
      id: `note:${id}`,
      pitch: 64,
      source: null,
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
      technique_ids: [],
      properties: {},
    }],
  };
}

function documentWith(beats: ScoreBeat[]): ScoreDocument {
  return {
    id: "document:test",
    schema_version: "3.0",
    title: "Adapter test",
    source: {},
    analysis: {},
    tracks: [{
      id: "track:guitar",
      order: 0,
      name: "Guitar",
      family: "guitar",
      role: "rhythm",
      source_track_indices: [],
      instrument: { tuning: [40, 45, 50, 55, 59, 64], fret_count: 24 },
      notation_mode: "standard_tab",
      mixer: { volume: 0.8, pan: 0, mute: false, solo: false },
      staves: [{ id: "staff:guitar", order: 0, kind: "standard_tab", line_count: 5 }],
      measures: [{
        id: "measure:1",
        number: 1,
        start: { numerator: 0, denominator: 1 },
        duration: { numerator: 4, denominator: 1 },
        numerator: 4,
        denominator: 4,
        beats,
        annotations: {},
      }],
    }],
    tempo_map: [{ id: "tempo:1", position: { numerator: 0, denominator: 1 }, bpm: 120 }],
    time_signatures: [{ id: "time:1", position: { numerator: 0, denominator: 1 }, numerator: 4, denominator: 4 }],
    techniques: [],
    performance: { profile_id: "test", events: [] },
    unresolved_events: [],
    validation: { status: "valid", issues: [] },
    pins: {},
    arrangement_mode: "faithful",
    knowledge: null,
    transformations: [],
    warnings: [],
  };
}

describe("ScoreDocument alphaTab adapter", () => {
  it("splits an exact non-atomic value and preserves stable note identity", () => {
    expect(decomposeScoreDuration({ numerator: 5, denominator: 4 })).toHaveLength(2);
    const result = buildAlphaTabScore(documentWith([beat("long", 0, 5, 4)]), new Settings());
    const rendered = result.stableNoteModels.get("note:long") ?? [];

    expect(rendered).toHaveLength(2);
    expect(rendered.every((note) => note.string === 6 && note.fret === 0)).toBe(true);
    expect(rendered[1]?.isTieDestination).toBe(true);
    expect([...result.alphaNoteIds.values()]).toEqual(["note:long", "note:long"]);
  });

  it("keeps dotted, triplet and dynamic notation explicit", () => {
    const dotted = decomposeScoreDuration({ numerator: 3, denominator: 2 });
    const triplet = decomposeScoreDuration({ numerator: 2, denominator: 3 });
    expect(dotted).toHaveLength(1);
    expect(dotted[0]?.dots).toBe(1);
    expect(triplet).toHaveLength(1);
    expect(triplet[0]?.tupletNumerator).toBe(3);
    expect(triplet[0]?.tupletDenominator).toBe(2);

    const dynamicBeat = beat("dynamic", 0, 1);
    dynamicBeat.properties.dynamic = "f";
    const result = buildAlphaTabScore(documentWith([dynamicBeat]), new Settings());
    expect(result.stableBeatModels.get("dynamic")?.[0]?.dynamics).toBe(
      model.DynamicValue.F,
    );
  });

  it("projects score tempo changes onto the exact master-bar positions", () => {
    const document = documentWith([beat("first", 0, 1)]);
    const firstMeasure = document.tracks[0]!.measures[0]!;
    firstMeasure.beats = [
      beat("first", 0, 1),
      beat("second", 2, 1),
    ];
    document.tracks[0]!.measures.push({
      ...firstMeasure,
      id: "measure:2",
      number: 2,
      start: { numerator: 4, denominator: 1 },
      beats: [beat("third", 4, 1)],
    });
    document.tempo_map = [
      { id: "tempo:initial", position: { numerator: 0, denominator: 1 }, bpm: 120 },
      { id: "tempo:middle", position: { numerator: 2, denominator: 1 }, bpm: 180 },
      { id: "tempo:second-bar", position: { numerator: 4, denominator: 1 }, bpm: 90 },
    ];

    const result = buildAlphaTabScore(document, new Settings());

    expect(result.score.masterBars[0]!.tempoAutomations.map((value) => ({
      bpm: value.value,
      position: value.ratioPosition,
    }))).toEqual([
      { bpm: 120, position: 0 },
      { bpm: 180, position: 0.5 },
    ]);
    expect(result.score.masterBars[1]!.tempoAutomations.map((value) => ({
      bpm: value.value,
      position: value.ratioPosition,
    }))).toEqual([{ bpm: 90, position: 0 }]);
  });

  it("projects an explicit adjacent tie without creating renderer-owned identity", () => {
    const source = beat("tie-source", 0, 1);
    const target = beat("tie-target", 1, 1);
    source.tie_out = true;
    target.tie_in = true;
    const result = buildAlphaTabScore(documentWith([source, target]), new Settings());
    const renderedSource = result.stableNoteModels.get("note:tie-source")?.[0];
    const renderedTarget = result.stableNoteModels.get("note:tie-target")?.[0];
    expect(renderedTarget?.isTieDestination).toBe(true);
    expect(renderedTarget?.tieOrigin).toBe(renderedSource);
  });

  it("rejects overlapping beats instead of shifting them", () => {
    const overlapping = documentWith([
      beat("first", 0, 1),
      { ...beat("second", 0, 1), start: { numerator: 1, denominator: 2 } },
    ]);

    expect(() => buildAlphaTabScore(overlapping, new Settings())).toThrow(AlphaTabAdapterError);
    expect(() => buildAlphaTabScore(overlapping, new Settings())).toThrow(/not silently shifted/);
  });

  it("projects manual note techniques without making renderer state authoritative", () => {
    const document = documentWith([beat("technique", 0, 1)]);
    const note = document.tracks[0]!.measures[0]!.beats[0]!.notes[0]!;
    note.technique_ids = ["technique:palm", "technique:staccato"];
    document.techniques = [
      {
        id: "technique:palm",
        type: "palm_mute",
        note_ids: [note.id],
        confidence: 1,
        reason: "manual",
        parameters: {},
      },
      {
        id: "technique:staccato",
        type: "staccato",
        note_ids: [note.id],
        confidence: 1,
        reason: "manual",
        parameters: {},
      },
    ];

    const result = buildAlphaTabScore(document, new Settings());
    const rendered = result.stableNoteModels.get(note.id)?.[0];
    expect(rendered?.isPalmMute).toBe(true);
    expect(rendered?.isStaccato).toBe(true);
  });

  it("renders direct guitar effects and explicit two-note links", () => {
    const sourceBeat = beat("source", 0, 1);
    const targetBeat = beat("target", 1, 1);
    const sourceNote = sourceBeat.notes[0]!;
    const targetNote = targetBeat.notes[0]!;
    targetNote.pitch = 67;
    targetNote.realization.fret = 3;
    sourceNote.technique_ids = [
      "technique:bend",
      "technique:harmonic",
      "technique:vibrato",
      "technique:hammer",
      "technique:slide",
    ];
    targetNote.technique_ids = ["technique:hammer", "technique:slide"];
    const document = documentWith([sourceBeat, targetBeat]);
    document.techniques = [
      {
        id: "technique:bend",
        type: "bend",
        note_ids: [sourceNote.id],
        confidence: 1,
        reason: "manual",
        parameters: { semitones: 1 },
      },
      {
        id: "technique:harmonic",
        type: "harmonic",
        note_ids: [sourceNote.id],
        confidence: 1,
        reason: "manual",
        parameters: {},
      },
      {
        id: "technique:vibrato",
        type: "vibrato",
        note_ids: [sourceNote.id],
        confidence: 1,
        reason: "manual",
        parameters: { width: 2 },
      },
      {
        id: "technique:hammer",
        type: "hammer_on",
        note_ids: [sourceNote.id, targetNote.id],
        confidence: 1,
        reason: "manual",
        parameters: {},
      },
      {
        id: "technique:slide",
        type: "slide",
        note_ids: [sourceNote.id, targetNote.id],
        confidence: 1,
        reason: "manual",
        parameters: {},
      },
    ];

    const result = buildAlphaTabScore(document, new Settings());
    const renderedSource = result.stableNoteModels.get(sourceNote.id)?.[0];
    const renderedTarget = result.stableNoteModels.get(targetNote.id)?.[0];

    expect(renderedSource?.bendType).toBe(model.BendType.Bend);
    expect(renderedSource?.bendPoints?.at(-1)?.value).toBe(2);
    expect(renderedSource?.harmonicType).toBe(model.HarmonicType.Natural);
    expect(renderedSource?.vibrato).toBe(model.VibratoType.Wide);
    expect(renderedSource?.isHammerPullOrigin).toBe(true);
    expect(renderedSource?.hammerPullDestination).toBe(renderedTarget);
    expect(renderedSource?.slideOutType).toBe(model.SlideOutType.Shift);
    expect(renderedSource?.slideTarget).toBe(renderedTarget);
  });

  it.each(["drums", "keys"])("preserves beat and note identity for %s notation", (family) => {
    const document = documentWith([beat(`${family}-beat`, 0, 1)]);
    const track = document.tracks[0]!;
    const scoreBeat = track.measures[0]!.beats[0]!;
    const note = scoreBeat.notes[0]!;
    track.family = family;
    track.instrument = family === "drums" ? { kit: "standard_5pc" } : {};
    track.staves[0]!.kind = family === "drums" ? "percussion" : "treble";
    note.pitch = family === "drums" ? 38 : 60;
    note.realization = {
      ...note.realization,
      kind: family,
      string: null,
      fret: null,
      piece: family === "drums" ? "snare" : null,
      hand: family === "keys" ? "right" : null,
    };

    const result = buildAlphaTabScore(document, new Settings());

    expect([...result.alphaBeatIds.values()]).toContain(scoreBeat.id);
    expect([...result.alphaNoteIds.values()]).toContain(note.id);
    expect(result.stableBeatModels.get(scoreBeat.id)).toHaveLength(1);
    expect(result.stableNoteModels.get(note.id)).toHaveLength(1);
  });
});
