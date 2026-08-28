import { describe, expect, it } from "vitest";
import type { ScoreBeat, ScoreDocument, ScoreTrack } from "../api/types";
import {
  applyOperationsLocally,
  availableAfter,
  contiguousBeatIds,
  findBeat,
  makeBeatClipboard,
  orderedBeatContexts,
  prepareBeatAfter,
  prepareClipboardAfter,
  prepareDrumInput,
  prepareFretInput,
  prepareMeasureAfter,
  prepareMeasureDelete,
  preparePitchedInput,
  prepareTie,
  toggleWrittenDurationModifier,
  writtenDurationState,
} from "./scoreEditing";

function noteBeat(id: string, start: number, duration = 1): ScoreBeat {
  return {
    id,
    start: { numerator: start, denominator: 1 },
    duration: { numerator: duration, denominator: 1 },
    voice: 1,
    staff_id: "staff:guitar",
    kind: "notes",
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
    tie_in: false,
    tie_out: false,
    properties: {},
  };
}

function documentWith(beats: ScoreBeat[]): ScoreDocument {
  const track: ScoreTrack = {
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
  };
  return {
    id: "document:test",
    schema_version: "3.0",
    title: "Editing test",
    source: {},
    analysis: {},
    tracks: [track],
    tempo_map: [],
    time_signatures: [],
    techniques: [],
    performance: {
      profile_id: "source-preserved",
      events: beats.flatMap((beat) => beat.notes.map((note) => ({
        id: `performance:${note.id}`,
        note_id: note.id,
        start: beat.start,
        duration: beat.duration,
        velocity: 91,
        controls: [],
      }))),
    },
    unresolved_events: [],
    validation: { status: "passed", issues: [] },
    pins: {},
    arrangement_mode: "faithful",
    knowledge: null,
    transformations: [],
    warnings: [],
  };
}

function ids(): () => string {
  let index = 0;
  return () => String(++index);
}

function drumDocument(): ScoreDocument {
  const beat = noteBeat("snare", 0);
  beat.staff_id = "staff:drums";
  beat.notes[0]!.pitch = 38;
  beat.notes[0]!.realization = {
    kind: "drums",
    string: null,
    fret: null,
    fretting_digit: null,
    hand_position: null,
    piece: "snare",
    sticking: null,
    hit_technique: "center",
    hand: null,
    finger: null,
    pedal: null,
  };
  const document = documentWith([beat]);
  const track = document.tracks[0]!;
  track.id = "track:drums";
  track.name = "Drums";
  track.family = "drums";
  track.instrument = { kit: "standard_5pc" };
  track.staves = [{ id: "staff:drums", order: 0, kind: "percussion", line_count: 5 }];
  return document;
}

describe("score editing helpers", () => {
  it("finds exact free time and prepares a complete inserted note", () => {
    const document = documentWith([noteBeat("first", 0), noteBeat("last", 2)]);
    const context = findBeat(document, "first");
    expect(context).not.toBeNull();
    expect(availableAfter(context!)).toEqual({ numerator: 1, denominator: 1 });

    const prepared = prepareBeatAfter(
      context!,
      "notes",
      { numerator: 1, denominator: 2 },
      ids(),
    );
    expect(prepared.operation.beat.start).toEqual({ numerator: 1, denominator: 1 });
    expect(prepared.operation.performance_events).toEqual([
      expect.objectContaining({
        note_id: prepared.noteId,
        start: { numerator: 1, denominator: 1 },
        duration: { numerator: 1, denominator: 2 },
      }),
    ]);
  });

  it("rejects insertion that would overlap the next beat", () => {
    const document = documentWith([noteBeat("first", 0), noteBeat("last", 2)]);
    const context = findBeat(document, "first");

    expect(() => prepareBeatAfter(
      context!,
      "rest",
      { numerator: 2, denominator: 1 },
      ids(),
    )).toThrow(/not enough room/);
  });

  it("pastes with new stable IDs and matching performance references", () => {
    const document = documentWith([noteBeat("source", 0), noteBeat("anchor", 2)]);
    const source = findBeat(document, "source")!;
    const anchor = findBeat(document, "anchor")!;
    const clipboard = makeBeatClipboard(document, source);
    const prepared = prepareClipboardAfter(anchor, clipboard, ids());

    expect(prepared.operation.beat.id).not.toBe(source.beat.id);
    expect(prepared.operation.beat.notes[0]?.id).not.toBe(source.beat.notes[0]?.id);
    expect(prepared.operation.performance_events[0]).toMatchObject({
      note_id: prepared.operation.beat.notes[0]?.id,
      velocity: 91,
      start: { numerator: 3, denominator: 1 },
    });
  });

  it("applies supported operations optimistically without mutating the source", () => {
    const document = documentWith([noteBeat("first", 0)]);
    const context = findBeat(document, "first")!;
    const rest = prepareBeatAfter(
      context,
      "rest",
      { numerator: 1, denominator: 1 },
      ids(),
    );
    const changed = applyOperationsLocally(document, [
      {
        kind: "set_note_pitch",
        note_id: "note:first",
        pitch: 65,
        expected_pitch: 64,
      },
      {
        kind: "set_beat_voice",
        beat_id: "first",
        voice: 2,
        expected_voice: 1,
      },
      rest.operation,
    ]);

    expect(document.tracks[0]?.measures[0]?.beats).toHaveLength(1);
    expect(changed.tracks[0]?.measures[0]?.beats).toHaveLength(2);
    expect(changed.tracks[0]?.measures[0]?.beats[0]?.notes[0]?.pitch).toBe(65);
    expect(changed.tracks[0]?.measures[0]?.beats[0]?.voice).toBe(2);
  });

  it("navigates beats deterministically and adds a chord tone by fret", () => {
    const document = documentWith([noteBeat("second", 2), noteBeat("first", 0)]);
    const ordered = orderedBeatContexts(document, "track:guitar");
    expect(ordered.map((context) => context.beat.id)).toEqual(["first", "second"]);
    expect(contiguousBeatIds(ordered, "first", "second")).toEqual(["first", "second"]);

    const prepared = prepareFretInput(ordered[0]!, 2, 3, ids());
    expect(prepared).toMatchObject({ stringNumber: 2, fret: 3, pitch: 62 });
    expect(prepared.operations[0]).toMatchObject({
      kind: "add_note",
      beat_id: "first",
      expected_beat_kind: "notes",
    });
    const changed = applyOperationsLocally(document, prepared.operations);
    const changedBeat = findBeat(changed, "first")!.beat;
    expect(changedBeat.notes).toHaveLength(2);
    expect(changedBeat.notes.find((note) => note.id === prepared.noteId)).toMatchObject({
      pitch: 62,
      realization: { string: 2, fret: 3 },
    });
    expect(changed.performance.events.some((event) => event.note_id === prepared.noteId)).toBe(true);
  });

  it("deleting the last note locally turns the beat into an explicit rest", () => {
    const document = documentWith([noteBeat("first", 0)]);
    const changed = applyOperationsLocally(document, [{
      kind: "delete_note",
      beat_id: "first",
      note_id: "note:first",
      expected_note_hash: null,
    }]);

    expect(findBeat(changed, "first")!.beat).toMatchObject({ kind: "rest", notes: [] });
    expect(changed.performance.events).toEqual([]);
  });

  it("keeps technique forward and reverse references in sync locally", () => {
    const document = documentWith([noteBeat("first", 0)]);
    const added = applyOperationsLocally(document, [{
      kind: "add_technique",
      technique: {
        id: "technique:palm",
        type: "palm_mute",
        note_ids: ["note:first"],
        confidence: 1,
        reason: "manual",
        parameters: {},
      },
    }]);
    expect(added.techniques).toHaveLength(1);
    expect(findBeat(added, "first")!.beat.notes[0]!.technique_ids).toEqual(["technique:palm"]);

    const removed = applyOperationsLocally(added, [{
      kind: "delete_technique",
      technique_id: "technique:palm",
      expected_technique_hash: null,
    }]);
    expect(removed.techniques).toEqual([]);
    expect(findBeat(removed, "first")!.beat.notes[0]!.technique_ids).toEqual([]);
  });

  it("inserts an aligned score-wide empty bar with a selectable explicit rest", () => {
    const document = documentWith([noteBeat("first", 0)]);
    const prepared = prepareMeasureAfter(
      document,
      1,
      "track:guitar",
      "empty",
      ids(),
    );
    const changed = applyOperationsLocally(document, [prepared.operation]);

    expect(document.tracks[0]?.measures).toHaveLength(1);
    expect(changed.tracks[0]?.measures).toHaveLength(2);
    expect(changed.tracks[0]?.measures[1]).toMatchObject({
      number: 2,
      start: { numerator: 4, denominator: 1 },
      beats: [{
        id: prepared.selectedBeatId,
        kind: "rest",
        duration: { numerator: 4, denominator: 1 },
      }],
    });
  });

  it("duplicates and deletes a complete bar with new note/performance/technique IDs", () => {
    const document = documentWith([noteBeat("first", 0)]);
    document.techniques.push({
      id: "technique:palm",
      type: "palm_mute",
      note_ids: ["note:first"],
      confidence: 1,
      reason: "manual",
      parameters: {},
    });
    document.tracks[0]!.measures[0]!.beats[0]!.notes[0]!.technique_ids = [
      "technique:palm",
    ];
    const duplicated = prepareMeasureAfter(
      document,
      1,
      "track:guitar",
      "duplicate",
      ids(),
    );
    const changed = applyOperationsLocally(document, [duplicated.operation]);
    const copiedNoteId = changed.tracks[0]!.measures[1]!.beats[0]!.notes[0]!.id;
    expect(copiedNoteId).not.toBe("note:first");
    expect(changed.performance.events.some((event) => event.note_id === copiedNoteId)).toBe(true);
    expect(changed.techniques).toHaveLength(2);
    expect(changed.tracks[0]!.measures[1]!.beats[0]!.notes[0]!.technique_ids).toHaveLength(1);

    const deletion = prepareMeasureDelete(changed, 2, "track:guitar");
    const restored = applyOperationsLocally(changed, [deletion.operation]);
    expect(restored).toEqual(document);
  });

  it("routes drum kit entry to conventional hands and feet voices", () => {
    const document = drumDocument();
    const context = findBeat(document, "snare")!;
    const kick = prepareDrumInput(
      context.track,
      context,
      "kick",
      { numerator: 1, denominator: 1 },
      ids(),
    );
    expect(kick.operations[0]).toMatchObject({
      kind: "insert_beat",
      beat: { voice: 2, notes: [{ pitch: 36, realization: { piece: "kick" } }] },
    });
    const withKick = applyOperationsLocally(document, kick.operations);
    const hihat = prepareDrumInput(
      findBeat(withKick, "snare")!.track,
      findBeat(withKick, "snare")!,
      "hihat_closed",
      { numerator: 1, denominator: 1 },
      ids(),
    );
    expect(hihat.operations[0]).toMatchObject({
      kind: "add_note",
      beat_id: "snare",
      note: { pitch: 42, realization: { piece: "hihat_closed" } },
    });
    const changed = applyOperationsLocally(withKick, hihat.operations);
    expect(findBeat(changed, "snare")!.beat.notes).toHaveLength(2);
    expect(changed.tracks[0]!.measures[0]!.beats.map((beat) => beat.voice).sort()).toEqual([1, 2]);
  });

  it("edits a selected pitched note or adds a chord tone on a standard staff", () => {
    const document = documentWith([noteBeat("first", 0)]);
    const track = document.tracks[0]!;
    track.family = "generic";
    track.instrument = {};
    track.staves = [{ id: "staff:guitar", order: 0, kind: "standard", line_count: 5 }];
    track.measures[0]!.beats[0]!.notes[0]!.realization.kind = "generic";
    track.measures[0]!.beats[0]!.notes[0]!.realization.string = null;
    track.measures[0]!.beats[0]!.notes[0]!.realization.fret = null;
    const context = findBeat(document, "first")!;
    const replaced = preparePitchedInput(
      track,
      context,
      "note:first",
      62,
      { numerator: 1, denominator: 1 },
      ids(),
    );
    expect(replaced.operations[0]).toMatchObject({
      kind: "set_note_pitch",
      note_id: "note:first",
      pitch: 62,
    });
    const chord = preparePitchedInput(
      track,
      context,
      null,
      67,
      { numerator: 1, denominator: 1 },
      ids(),
    );
    const changed = applyOperationsLocally(document, chord.operations);
    expect(findBeat(changed, "first")!.beat.notes.map((note) => note.pitch).sort()).toEqual([64, 67]);
  });

  it("assigns unique playable fingers when adding keyboard chord tones", () => {
    const document = documentWith([noteBeat("first", 0)]);
    const track = document.tracks[0]!;
    track.family = "keys";
    track.instrument = {};
    track.staves = [{ id: "staff:guitar", order: 0, kind: "treble", line_count: 5 }];
    const first = track.measures[0]!.beats[0]!.notes[0]!;
    first.realization = {
      ...first.realization,
      kind: "keys",
      string: null,
      fret: null,
      hand: "right",
      finger: 1,
    };
    const context = findBeat(document, "first")!;

    const chord = preparePitchedInput(
      track,
      context,
      null,
      67,
      { numerator: 1, denominator: 1 },
      ids(),
    );

    expect(chord.operations[0]).toMatchObject({
      kind: "add_note",
      note: { realization: { hand: "right", finger: 2 } },
    });
  });

  it("toggles dotted and triplet written durations without losing the base value", () => {
    const quarter = { numerator: 1, denominator: 1 };
    const dotted = toggleWrittenDurationModifier(quarter, "dot");
    expect(dotted).toEqual({ numerator: 3, denominator: 2 });
    expect(writtenDurationState(dotted)).toMatchObject({ modifier: "dot" });
    expect(toggleWrittenDurationModifier(dotted, "dot")).toEqual(quarter);

    const triplet = toggleWrittenDurationModifier(quarter, "triplet");
    expect(triplet).toEqual({ numerator: 2, denominator: 3 });
    expect(writtenDurationState(triplet)).toMatchObject({ modifier: "triplet" });
  });

  it("creates and removes a validated adjacent tie with local dynamic projection", () => {
    const document = documentWith([
      noteBeat("tie-source", 0),
      noteBeat("tie-target", 1),
    ]);
    const beats = orderedBeatContexts(document, "track:guitar");
    const prepared = prepareTie(beats, ["tie-source"], "tie-source");
    expect(prepared.active).toBe(false);
    let changed = applyOperationsLocally(document, prepared.operations);
    expect(findBeat(changed, "tie-source")!.beat.tie_out).toBe(true);
    expect(findBeat(changed, "tie-target")!.beat.tie_in).toBe(true);

    const removal = prepareTie(
      orderedBeatContexts(changed, "track:guitar"),
      ["tie-source", "tie-target"],
      "tie-source",
    );
    expect(removal.active).toBe(true);
    changed = applyOperationsLocally(changed, [
      ...removal.operations,
      {
        kind: "set_beat_dynamic",
        beat_id: "tie-source",
        dynamic: "f",
        expected_dynamic: null,
      },
      {
        kind: "set_performance_velocity",
        note_id: "note:tie-source",
        velocity: 96,
        expected_velocity: 91,
      },
    ]);
    expect(findBeat(changed, "tie-source")!.beat.tie_out).toBe(false);
    expect(findBeat(changed, "tie-target")!.beat.tie_in).toBe(false);
    expect(findBeat(changed, "tie-source")!.beat.properties.dynamic).toBe("f");
    expect(changed.performance.events.find(
      (event) => event.note_id === "note:tie-source",
    )?.velocity).toBe(96);
  });
});
