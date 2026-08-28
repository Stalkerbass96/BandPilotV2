import type {
  ScoreBeat,
  ScoreDocument,
  ScoreMeasure,
  ScoreNote,
  ScoreOperation,
  ScorePerformanceEvent,
  ScoreRational,
  ScoreTechnique,
  ScoreTrack,
} from "../api/types";

export interface BeatContext {
  track: ScoreTrack;
  measure: ScoreMeasure;
  beat: ScoreBeat;
}

export interface NoteContext extends BeatContext {
  note: ScoreNote;
}

export interface BeatClipboard {
  sourceTrackId: string;
  beat: ScoreBeat;
  performanceEvents: ScorePerformanceEvent[];
}

export interface PreparedBeatInsert {
  operation: Extract<ScoreOperation, { kind: "insert_beat" }>;
  beatId: string;
  noteId: string | null;
}

export interface PreparedFretInput {
  operations: ScoreOperation[];
  noteId: string;
  pitch: number;
  stringNumber: number;
  fret: number;
}

export interface PreparedMeasureInsert {
  operation: Extract<ScoreOperation, { kind: "insert_measure_group" }>;
  measureIds: string[];
  selectedBeatId: string | null;
  selectedNoteId: string | null;
}

export interface PreparedMeasureDelete {
  operation: Extract<ScoreOperation, { kind: "delete_measure_group" }>;
  measureIds: string[];
  fallbackBeatId: string | null;
  fallbackNoteId: string | null;
}

export interface PreparedDrumInput {
  operations: ScoreOperation[];
  beatId: string;
  noteId: string;
  piece: string;
  voice: number;
}

export interface PreparedPitchedInput {
  operations: ScoreOperation[];
  beatId: string;
  noteId: string;
  pitch: number;
}

export interface PreparedTie {
  operations: ScoreOperation[];
  sourceBeatId: string;
  targetBeatId: string;
  active: boolean;
}

export const PITCH_CLASS_INPUTS = [
  { pitchClass: 0, label: "C" },
  { pitchClass: 1, label: "C♯" },
  { pitchClass: 2, label: "D" },
  { pitchClass: 3, label: "E♭" },
  { pitchClass: 4, label: "E" },
  { pitchClass: 5, label: "F" },
  { pitchClass: 6, label: "F♯" },
  { pitchClass: 7, label: "G" },
  { pitchClass: 8, label: "A♭" },
  { pitchClass: 9, label: "A" },
  { pitchClass: 10, label: "B♭" },
  { pitchClass: 11, label: "B" },
] as const;

export const DRUM_INPUT_PIECES = [
  { piece: "kick", label: "Kick", pitch: 36, voice: 2, hitTechnique: "center" },
  { piece: "snare", label: "Snare", pitch: 38, voice: 1, hitTechnique: "center" },
  { piece: "hihat_closed", label: "HH", pitch: 42, voice: 1, hitTechnique: "closed" },
  { piece: "hihat_open", label: "Open HH", pitch: 46, voice: 1, hitTechnique: "open" },
  { piece: "hihat_pedal", label: "Pedal HH", pitch: 44, voice: 2, hitTechnique: "pedal" },
  { piece: "tom_high", label: "High tom", pitch: 50, voice: 1, hitTechnique: "center" },
  { piece: "tom_floor", label: "Floor tom", pitch: 41, voice: 1, hitTechnique: "center" },
  { piece: "crash", label: "Crash", pitch: 49, voice: 1, hitTechnique: "edge" },
  { piece: "ride", label: "Ride", pitch: 51, voice: 1, hitTechnique: "bow" },
] as const;

export const WRITTEN_DURATIONS = [
  { label: "Whole", shortLabel: "1/1", value: { numerator: 4, denominator: 1 } },
  { label: "Half", shortLabel: "1/2", value: { numerator: 2, denominator: 1 } },
  { label: "Quarter", shortLabel: "1/4", value: { numerator: 1, denominator: 1 } },
  { label: "Eighth", shortLabel: "1/8", value: { numerator: 1, denominator: 2 } },
  { label: "Sixteenth", shortLabel: "1/16", value: { numerator: 1, denominator: 4 } },
  { label: "Thirty-second", shortLabel: "1/32", value: { numerator: 1, denominator: 8 } },
  { label: "Sixty-fourth", shortLabel: "1/64", value: { numerator: 1, denominator: 16 } },
] as const;

export const DYNAMIC_INPUTS = [
  { label: "ppp", velocity: 24 },
  { label: "pp", velocity: 36 },
  { label: "p", velocity: 48 },
  { label: "mp", velocity: 64 },
  { label: "mf", velocity: 80 },
  { label: "f", velocity: 96 },
  { label: "ff", velocity: 112 },
  { label: "fff", velocity: 124 },
] as const;

function gcd(left: number, right: number): number {
  let a = Math.abs(left);
  let b = Math.abs(right);
  while (b !== 0) {
    const remainder = a % b;
    a = b;
    b = remainder;
  }
  return a || 1;
}

export function rational(numerator: number, denominator = 1): ScoreRational {
  if (!Number.isInteger(numerator) || !Number.isInteger(denominator) || denominator === 0) {
    throw new Error("Score time requires finite integer fractions.");
  }
  const sign = denominator < 0 ? -1 : 1;
  const divisor = gcd(numerator, denominator);
  return {
    numerator: (numerator / divisor) * sign,
    denominator: Math.abs(denominator / divisor),
  };
}

export function addRational(left: ScoreRational, right: ScoreRational): ScoreRational {
  return rational(
    left.numerator * right.denominator + right.numerator * left.denominator,
    left.denominator * right.denominator,
  );
}

export function multiplyRational(
  value: ScoreRational,
  numerator: number,
  denominator = 1,
): ScoreRational {
  return rational(value.numerator * numerator, value.denominator * denominator);
}

export function subtractRational(left: ScoreRational, right: ScoreRational): ScoreRational {
  return rational(
    left.numerator * right.denominator - right.numerator * left.denominator,
    left.denominator * right.denominator,
  );
}

export function compareRational(left: ScoreRational, right: ScoreRational): number {
  return left.numerator * right.denominator - right.numerator * left.denominator;
}

export function equalRational(left: ScoreRational, right: ScoreRational): boolean {
  return compareRational(left, right) === 0;
}

export type DurationModifier = "dot" | "triplet";

export function writtenDurationState(value: ScoreRational): {
  base: ScoreRational;
  modifier: DurationModifier | null;
} | null {
  for (const duration of WRITTEN_DURATIONS) {
    if (equalRational(value, duration.value)) {
      return { base: duration.value, modifier: null };
    }
    if (equalRational(value, multiplyRational(duration.value, 3, 2))) {
      return { base: duration.value, modifier: "dot" };
    }
    if (equalRational(value, multiplyRational(duration.value, 2, 3))) {
      return { base: duration.value, modifier: "triplet" };
    }
  }
  return null;
}

export function toggleWrittenDurationModifier(
  value: ScoreRational,
  modifier: DurationModifier,
): ScoreRational {
  const state = writtenDurationState(value);
  if (!state) throw new Error("Choose a standard written duration before adding a modifier.");
  if (state.modifier === modifier) return state.base;
  return modifier === "dot"
    ? multiplyRational(state.base, 3, 2)
    : multiplyRational(state.base, 2, 3);
}

export function findBeat(
  document: ScoreDocument | null,
  beatId: string | null,
): BeatContext | null {
  if (!document || !beatId) return null;
  for (const track of document.tracks) {
    for (const measure of track.measures) {
      const beat = measure.beats.find((candidate) => candidate.id === beatId);
      if (beat) return { track, measure, beat };
    }
  }
  return null;
}

export function findNote(
  document: ScoreDocument | null,
  noteId: string | null,
): NoteContext | null {
  if (!document || !noteId) return null;
  for (const track of document.tracks) {
    for (const measure of track.measures) {
      for (const beat of measure.beats) {
        const note = beat.notes.find((candidate) => candidate.id === noteId);
        if (note) return { track, measure, beat, note };
      }
    }
  }
  return null;
}

/** Stable keyboard-navigation order within one track. */
export function orderedBeatContexts(
  document: ScoreDocument | null,
  trackId: string | null,
): BeatContext[] {
  if (!document || !trackId) return [];
  const track = document.tracks.find((candidate) => candidate.id === trackId);
  if (!track) return [];
  const staffOrder = new Map(track.staves.map((staff) => [staff.id, staff.order]));
  return track.measures
    .flatMap((measure) => measure.beats.map((beat) => ({ track, measure, beat })))
    .sort((left, right) => (
      left.measure.number - right.measure.number ||
      compareRational(left.beat.start, right.beat.start) ||
      (staffOrder.get(left.beat.staff_id) ?? 0) - (staffOrder.get(right.beat.staff_id) ?? 0) ||
      left.beat.voice - right.beat.voice ||
      left.beat.id.localeCompare(right.beat.id)
    ));
}

export function contiguousBeatIds(
  beats: BeatContext[],
  anchorId: string,
  extentId: string,
): string[] {
  const anchorIndex = beats.findIndex((context) => context.beat.id === anchorId);
  const extentIndex = beats.findIndex((context) => context.beat.id === extentId);
  if (anchorIndex < 0 || extentIndex < 0) return extentIndex >= 0 ? [extentId] : [];
  const start = Math.min(anchorIndex, extentIndex);
  const end = Math.max(anchorIndex, extentIndex);
  return beats.slice(start, end + 1).map((context) => context.beat.id);
}

function tieKeys(context: BeatContext): Set<string> {
  return new Set(context.beat.notes.map((note) => (
    context.track.family === "guitar" || context.track.family === "bass"
      ? `${note.pitch}:${note.realization.string ?? "none"}`
      : String(note.pitch)
  )));
}

export function prepareTie(
  beats: BeatContext[],
  selectedBeatIds: string[],
  selectedBeatId: string | null,
): PreparedTie {
  const selected = new Set(selectedBeatIds.length > 0
    ? selectedBeatIds
    : selectedBeatId ? [selectedBeatId] : []);
  const contexts = beats.filter((context) => selected.has(context.beat.id));
  if (contexts.length === 0 || contexts.length > 2) {
    throw new Error("Select one source beat or exactly two adjacent beats to create a tie.");
  }
  const source = contexts[0]!;
  const sourceIndex = beats.findIndex((context) => context.beat.id === source.beat.id);
  const target = contexts.length === 2
    ? contexts[1]!
    : beats.slice(sourceIndex + 1).find((context) => (
        context.beat.staff_id === source.beat.staff_id &&
        context.beat.voice === source.beat.voice
      ));
  if (!target) throw new Error("There is no following beat in this staff and voice.");
  if (source.track.id !== target.track.id || source.track.family === "drums") {
    throw new Error("Sustain ties are available only between pitched notes on one track.");
  }
  if (
    source.beat.kind !== "notes" || target.beat.kind !== "notes" ||
    source.beat.notes.length === 0 || target.beat.notes.length === 0
  ) {
    throw new Error("A tie cannot start or stop on a rest.");
  }
  if (
    source.beat.staff_id !== target.beat.staff_id ||
    source.beat.voice !== target.beat.voice ||
    compareRational(
      addRational(source.beat.start, source.beat.duration),
      target.beat.start,
    ) !== 0
  ) {
    throw new Error("A tie requires adjacent beats in the same staff and voice.");
  }
  const targetKeys = tieKeys(target);
  const sourceKeys = tieKeys(source);
  if (
    sourceKeys.size !== targetKeys.size ||
    ![...sourceKeys].every((key) => targetKeys.has(key))
  ) {
    throw new Error("Beat-level ties require matching chord pitches and strings.");
  }
  if (source.beat.tie_out !== target.beat.tie_in) {
    throw new Error("The existing tie endpoints are inconsistent and must be repaired first.");
  }
  const active = source.beat.tie_out && target.beat.tie_in;
  return {
    sourceBeatId: source.beat.id,
    targetBeatId: target.beat.id,
    active,
    operations: [
      {
        kind: "set_beat_tie",
        beat_id: source.beat.id,
        tie_in: source.beat.tie_in,
        tie_out: !active,
        expected_tie_in: source.beat.tie_in,
        expected_tie_out: source.beat.tie_out,
      },
      {
        kind: "set_beat_tie",
        beat_id: target.beat.id,
        tie_in: !active,
        tie_out: target.beat.tie_out,
        expected_tie_in: target.beat.tie_in,
        expected_tie_out: target.beat.tie_out,
      },
    ],
  };
}

export function isFretted(context: NoteContext): boolean {
  return (
    (context.track.family === "guitar" || context.track.family === "bass") &&
    context.note.realization.string !== null &&
    context.note.realization.fret !== null
  );
}

export function availableAfter(context: BeatContext): ScoreRational {
  const start = addRational(context.beat.start, context.beat.duration);
  const measureEnd = addRational(context.measure.start, context.measure.duration);
  const nextStart = context.measure.beats
    .filter((candidate) => (
      candidate.id !== context.beat.id &&
      candidate.staff_id === context.beat.staff_id &&
      candidate.voice === context.beat.voice &&
      compareRational(candidate.start, start) >= 0
    ))
    .map((candidate) => candidate.start)
    .sort(compareRational)[0] ?? measureEnd;
  return subtractRational(nextStart, start);
}

function deepClone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function newStableId(prefix: string, createId: () => string): string {
  return `${prefix}:${createId()}`;
}

export function defaultNote(
  track: ScoreTrack,
  voice: number,
  staffId: string,
  createId: () => string,
): ScoreNote {
  const realization: ScoreNote["realization"] = {
    kind: track.family,
    string: null,
    fret: null,
    fretting_digit: null,
    hand_position: null,
    piece: null,
    sticking: null,
    hit_technique: null,
    hand: null,
    finger: null,
    pedal: null,
  };
  let pitch = 60;
  if (track.family === "guitar" || track.family === "bass") {
    const tuning = Array.isArray(track.instrument.tuning) ? track.instrument.tuning : [];
    const capo = Number(track.instrument.capo ?? 0);
    pitch = Number(tuning[tuning.length - 1] ?? (track.family === "guitar" ? 64 : 43)) + capo;
    realization.string = 1;
    realization.fret = 0;
  } else if (track.family === "drums") {
    const footVoice = voice === 2;
    pitch = footVoice ? 36 : 38;
    realization.piece = footVoice ? "kick" : "snare";
    realization.hit_technique = "center";
  } else if (track.family === "keys") {
    const isBassStaff = track.staves.find((staff) => staff.id === staffId)?.kind === "bass";
    pitch = isBassStaff ? 48 : 60;
    realization.hand = isBassStaff ? "left" : "right";
    realization.finger = isBassStaff ? 5 : 1;
  }
  return {
    id: newStableId("note", createId),
    pitch,
    source: null,
    realization,
    technique_ids: [],
    properties: {},
  };
}

/** Prepare Guitar Pro-style direct fret entry on the caret string. */
export function prepareFretInput(
  context: BeatContext,
  stringNumber: number,
  fret: number,
  createId: () => string = () => crypto.randomUUID(),
): PreparedFretInput {
  if (context.track.family !== "guitar" && context.track.family !== "bass") {
    throw new Error("Direct fret entry is available only for guitar and bass tracks.");
  }
  const tuning = Array.isArray(context.track.instrument.tuning)
    ? context.track.instrument.tuning.filter(
        (value): value is number => typeof value === "number" && Number.isInteger(value),
      )
    : [];
  const fretCount = Number(context.track.instrument.fret_count ?? 24);
  if (stringNumber < 1 || stringNumber > tuning.length) {
    throw new Error(`String must be between 1 and ${tuning.length}.`);
  }
  if (!Number.isInteger(fret) || fret < 0 || fret > fretCount) {
    throw new Error(`Fret must be between 0 and ${fretCount}.`);
  }
  const openPitch = tuning[tuning.length - stringNumber];
  if (openPitch === undefined) throw new Error("The active track has no usable tuning.");
  const capo = Number(context.track.instrument.capo ?? 0);
  const pitch = openPitch + capo + fret;
  const existing = context.beat.notes.find(
    (note) => note.realization.string === stringNumber,
  );
  if (existing) {
    const operations: ScoreOperation[] = [];
    if (existing.pitch !== pitch) {
      operations.push({
        kind: "set_note_pitch",
        note_id: existing.id,
        pitch,
        expected_pitch: existing.pitch,
      });
    }
    if (existing.realization.fret !== fret) {
      operations.push({
        kind: "set_note_fretting",
        note_id: existing.id,
        string: stringNumber,
        fret,
        expected_string: existing.realization.string,
        expected_fret: existing.realization.fret,
      });
    }
    return { operations, noteId: existing.id, pitch, stringNumber, fret };
  }

  const note = defaultNote(
    context.track,
    context.beat.voice,
    context.beat.staff_id,
    createId,
  );
  note.pitch = pitch;
  note.realization.string = stringNumber;
  note.realization.fret = fret;
  const performanceEvent = performanceForBeat(
    { ...context.beat, kind: "notes", notes: [note] },
    [],
    createId,
  )[0];
  if (!performanceEvent) throw new Error("The fret entry has no performance event.");
  return {
    operations: [{
      kind: "add_note",
      beat_id: context.beat.id,
      note,
      performance_event: performanceEvent,
      expected_beat_kind: context.beat.kind,
    }],
    noteId: note.id,
    pitch,
    stringNumber,
    fret,
  };
}

/** Prepare a conventional five-line drum entry at the selected onset. */
export function prepareDrumInput(
  track: ScoreTrack,
  context: BeatContext | null,
  piece: string,
  duration: ScoreRational,
  createId: () => string = () => crypto.randomUUID(),
): PreparedDrumInput {
  if (track.family !== "drums") {
    throw new Error("The drum kit palette is available only on drum tracks.");
  }
  const definition = DRUM_INPUT_PIECES.find((candidate) => candidate.piece === piece);
  if (!definition) throw new Error(`Drum piece ${piece} is not in the editor kit.`);
  const measure = context?.measure ?? track.measures[0];
  const staff = track.staves[0];
  if (!measure || !staff) throw new Error("The drum track needs a measure and percussion staff.");
  const start = context?.beat.start ?? measure.start;
  const target = measure.beats.find((beat) => (
    beat.staff_id === staff.id &&
    beat.voice === definition.voice &&
    equalRational(beat.start, start)
  ));
  const existing = target?.notes.find(
    (note) => note.realization.piece === definition.piece,
  );
  if (existing && target) {
    return {
      operations: [],
      beatId: target.id,
      noteId: existing.id,
      piece: definition.piece,
      voice: definition.voice,
    };
  }
  const note = defaultNote(track, definition.voice, staff.id, createId);
  note.pitch = definition.pitch;
  note.realization.piece = definition.piece;
  note.realization.hit_technique = definition.hitTechnique;
  const beat: ScoreBeat = target ?? {
    id: newStableId("beat", createId),
    start,
    duration,
    voice: definition.voice,
    staff_id: staff.id,
    kind: "notes",
    notes: [],
    tie_in: false,
    tie_out: false,
    properties: {},
  };
  const event = performanceForBeat(
    { ...beat, kind: "notes", notes: [note] },
    [],
    createId,
  )[0];
  if (!event) throw new Error("The drum hit has no performance event.");
  return {
    operations: target
      ? [{
          kind: "add_note",
          beat_id: target.id,
          note,
          performance_event: event,
          expected_beat_kind: target.kind,
        }]
      : [{
          kind: "insert_beat",
          track_id: track.id,
          measure_id: measure.id,
          beat: { ...beat, notes: [note] },
          performance_events: [event],
        }],
    beatId: beat.id,
    noteId: note.id,
    piece: definition.piece,
    voice: definition.voice,
  };
}

/** Prepare standard-notation entry for keyboard and generic pitched staves. */
export function preparePitchedInput(
  track: ScoreTrack,
  context: BeatContext | null,
  selectedNoteId: string | null,
  pitch: number,
  duration: ScoreRational,
  createId: () => string = () => crypto.randomUUID(),
): PreparedPitchedInput {
  if (track.family !== "keys" && track.family !== "generic") {
    throw new Error("Pitched staff entry is available only for keys and standard notation.");
  }
  if (!Number.isInteger(pitch) || pitch < 0 || pitch > 127) {
    throw new Error("Pitch must stay within MIDI 0–127.");
  }
  if (context && selectedNoteId) {
    const selected = context.beat.notes.find((note) => note.id === selectedNoteId);
    if (selected) {
      return {
        operations: selected.pitch === pitch ? [] : [{
          kind: "set_note_pitch",
          note_id: selected.id,
          pitch,
          expected_pitch: selected.pitch,
        }],
        beatId: context.beat.id,
        noteId: selected.id,
        pitch,
      };
    }
  }
  const measure = context?.measure ?? track.measures[0];
  const staff = context
    ? track.staves.find((candidate) => candidate.id === context.beat.staff_id)
    : track.staves[0];
  if (!measure || !staff) throw new Error("The pitched track needs a measure and staff.");
  const existing = context?.beat.notes.find((note) => note.pitch === pitch);
  if (context && existing) {
    return { operations: [], beatId: context.beat.id, noteId: existing.id, pitch };
  }
  const note = defaultNote(track, context?.beat.voice ?? 1, staff.id, createId);
  note.pitch = pitch;
  if (track.family === "keys" && context) {
    const hand = note.realization.hand;
    const usedFingers = new Set(
      context.beat.notes
        .filter((candidate) => candidate.realization.hand === hand)
        .map((candidate) => candidate.realization.finger)
        .filter((finger): finger is number => finger !== null),
    );
    const preferred = hand === "left" ? [5, 4, 3, 2, 1] : [1, 2, 3, 4, 5];
    const available = preferred.find((finger) => !usedFingers.has(finger));
    if (available === undefined) {
      throw new Error("A keyboard hand cannot contain more than five simultaneous notes.");
    }
    note.realization.finger = available;
  }
  const beat: ScoreBeat = context?.beat ?? {
    id: newStableId("beat", createId),
    start: measure.start,
    duration,
    voice: 1,
    staff_id: staff.id,
    kind: "notes",
    notes: [],
    tie_in: false,
    tie_out: false,
    properties: {},
  };
  const event = performanceForBeat(
    { ...beat, kind: "notes", notes: [note] },
    [],
    createId,
  )[0];
  if (!event) throw new Error("The pitched note has no performance event.");
  return {
    operations: context
      ? [{
          kind: "add_note",
          beat_id: context.beat.id,
          note,
          performance_event: event,
          expected_beat_kind: context.beat.kind,
        }]
      : [{
          kind: "insert_beat",
          track_id: track.id,
          measure_id: measure.id,
          beat: { ...beat, notes: [note] },
          performance_events: [event],
        }],
    beatId: beat.id,
    noteId: note.id,
    pitch,
  };
}

function performanceForBeat(
  beat: ScoreBeat,
  sourceEvents: ScorePerformanceEvent[],
  createId: () => string,
): ScorePerformanceEvent[] {
  const byNote = new Map(sourceEvents.map((event) => [event.note_id, event]));
  return beat.notes.map((note) => {
    const source = byNote.get(note.id);
    return {
      id: newStableId("performance", createId),
      note_id: note.id,
      start: beat.start,
      duration: beat.duration,
      velocity: source?.velocity ?? 80,
      controls: deepClone(source?.controls ?? []),
    };
  });
}

export function makeBeatClipboard(
  document: ScoreDocument,
  context: BeatContext,
): BeatClipboard {
  const byNote = new Map(document.performance.events.map((event) => [event.note_id, event]));
  return {
    sourceTrackId: context.track.id,
    beat: deepClone(context.beat),
    performanceEvents: context.beat.notes
      .map((note) => byNote.get(note.id))
      .filter((event): event is ScorePerformanceEvent => Boolean(event))
      .map(deepClone),
  };
}

export function prepareBeatAfter(
  context: BeatContext,
  kind: "notes" | "rest",
  duration: ScoreRational,
  createId: () => string = () => crypto.randomUUID(),
): PreparedBeatInsert {
  const gap = availableAfter(context);
  if (compareRational(gap, duration) < 0) {
    throw new Error("There is not enough room after the selected beat for that duration.");
  }
  const start = addRational(context.beat.start, context.beat.duration);
  const note = kind === "notes"
    ? defaultNote(context.track, context.beat.voice, context.beat.staff_id, createId)
    : null;
  const beat: ScoreBeat = {
    id: newStableId("beat", createId),
    start,
    duration,
    voice: context.beat.voice,
    staff_id: context.beat.staff_id,
    kind,
    notes: note ? [note] : [],
    tie_in: false,
    tie_out: false,
    properties: {},
  };
  return {
    operation: {
      kind: "insert_beat",
      track_id: context.track.id,
      measure_id: context.measure.id,
      beat,
      performance_events: performanceForBeat(beat, [], createId),
    },
    beatId: beat.id,
    noteId: note?.id ?? null,
  };
}

export function prepareClipboardAfter(
  context: BeatContext,
  clipboard: BeatClipboard,
  createId: () => string = () => crypto.randomUUID(),
): PreparedBeatInsert {
  if (clipboard.sourceTrackId !== context.track.id) {
    throw new Error("This editing slice pastes only within the source track.");
  }
  const gap = availableAfter(context);
  if (compareRational(gap, clipboard.beat.duration) < 0) {
    throw new Error("There is not enough room after the selected beat for the copied rhythm.");
  }
  const noteIdMap = new Map<string, string>();
  const beat = deepClone(clipboard.beat);
  beat.id = newStableId("beat", createId);
  beat.start = addRational(context.beat.start, context.beat.duration);
  beat.staff_id = context.beat.staff_id;
  beat.voice = context.beat.voice;
  beat.tie_in = false;
  beat.tie_out = false;
  for (const note of beat.notes) {
    const sourceId = note.id;
    note.id = newStableId("note", createId);
    note.source = null;
    note.technique_ids = [];
    noteIdMap.set(sourceId, note.id);
  }
  const sourceEvents = clipboard.performanceEvents
    .map((event) => {
      const noteId = noteIdMap.get(event.note_id);
      return noteId ? { ...event, note_id: noteId } : null;
    })
    .filter((event): event is ScorePerformanceEvent => Boolean(event));
  return {
    operation: {
      kind: "insert_beat",
      track_id: context.track.id,
      measure_id: context.measure.id,
      beat,
      performance_events: performanceForBeat(beat, sourceEvents, createId),
    },
    beatId: beat.id,
    noteId: beat.notes[0]?.id ?? null,
  };
}

function alignedMeasureGroup(
  document: ScoreDocument,
  measureNumber: number,
): Array<{ track: ScoreTrack; measure: ScoreMeasure }> {
  const group = document.tracks.map((track) => ({
    track,
    measure: track.measures.find((measure) => measure.number === measureNumber),
  }));
  if (group.some((entry) => !entry.measure)) {
    throw new Error(`Bar ${measureNumber} is not aligned across every track.`);
  }
  const resolved = group as Array<{ track: ScoreTrack; measure: ScoreMeasure }>;
  const first = resolved[0]?.measure;
  if (!first || resolved.some(({ measure }) => (
    !equalRational(measure.start, first.start) ||
    !equalRational(measure.duration, first.duration) ||
    measure.numerator !== first.numerator ||
    measure.denominator !== first.denominator
  ))) {
    throw new Error(`Bar ${measureNumber} has inconsistent timing across tracks.`);
  }
  return resolved;
}

/** Build one score-wide bar insertion, matching Guitar Pro's global bar structure. */
export function prepareMeasureAfter(
  document: ScoreDocument,
  measureNumber: number,
  activeTrackId: string,
  mode: "empty" | "duplicate",
  createId: () => string = () => crypto.randomUUID(),
): PreparedMeasureInsert {
  const sources = alignedMeasureGroup(document, measureNumber);
  const reference = sources[0]?.measure;
  if (!reference) throw new Error("The selected bar is not available.");
  const insertionStart = addRational(reference.start, reference.duration);
  const insertionNumber = reference.number + 1;
  const sourceNoteIds = new Set(
    sources.flatMap(({ measure }) => (
      measure.beats.flatMap((beat) => beat.notes.map((note) => note.id))
    )),
  );
  const sourceTechniques = document.techniques.filter((technique) => (
    technique.note_ids.some((noteId) => sourceNoteIds.has(noteId))
  ));
  if (sourceTechniques.some((technique) => (
    !technique.note_ids.every((noteId) => sourceNoteIds.has(noteId))
  ))) {
    throw new Error("A linked technique crosses this bar boundary; remove or retarget it first.");
  }
  const techniqueIdMap = new Map(
    sourceTechniques.map((technique) => [technique.id, newStableId("technique", createId)]),
  );
  const noteIdMap = new Map<string, string>();
  const entries = sources.map(({ track, measure }) => {
    const next: ScoreMeasure = {
      id: newStableId("measure", createId),
      number: insertionNumber,
      start: insertionStart,
      duration: deepClone(reference.duration),
      numerator: reference.numerator,
      denominator: reference.denominator,
      beats: [],
      annotations: mode === "duplicate" ? deepClone(measure.annotations) : {},
    };
    if (mode === "empty") {
      const staff = track.staves[0];
      if (!staff) throw new Error(`${track.name} has no staff for a new bar.`);
      next.beats.push({
        id: newStableId("beat", createId),
        start: insertionStart,
        duration: deepClone(reference.duration),
        voice: 1,
        staff_id: staff.id,
        kind: "rest",
        notes: [],
        tie_in: false,
        tie_out: false,
        properties: {},
      });
    } else {
      next.beats = measure.beats.map((sourceBeat) => {
        const beat = deepClone(sourceBeat);
        beat.id = newStableId("beat", createId);
        beat.start = addRational(sourceBeat.start, reference.duration);
        beat.tie_in = false;
        beat.tie_out = false;
        beat.notes = sourceBeat.notes.map((sourceNote) => {
          const note = deepClone(sourceNote);
          note.id = newStableId("note", createId);
          note.source = null;
          note.technique_ids = sourceNote.technique_ids
            .map((techniqueId) => techniqueIdMap.get(techniqueId))
            .filter((techniqueId): techniqueId is string => Boolean(techniqueId));
          noteIdMap.set(sourceNote.id, note.id);
          return note;
        });
        return beat;
      });
    }
    return { track_id: track.id, measure: next };
  });

  const sourceEventByNote = new Map(
    document.performance.events.map((event) => [event.note_id, event]),
  );
  const performanceEvents = mode === "duplicate"
    ? [...noteIdMap.entries()].map(([sourceNoteId, noteId]) => {
        const source = sourceEventByNote.get(sourceNoteId);
        if (!source) throw new Error(`Note ${sourceNoteId} has no performance event.`);
        return {
          ...deepClone(source),
          id: newStableId("performance", createId),
          note_id: noteId,
          start: addRational(source.start, reference.duration),
        };
      })
    : [];
  const techniques: ScoreTechnique[] = mode === "duplicate"
    ? sourceTechniques.map((source) => ({
        ...deepClone(source),
        id: techniqueIdMap.get(source.id) as string,
        note_ids: source.note_ids.map((noteId) => noteIdMap.get(noteId) as string),
        confidence: 1,
        reason: "duplicated measure",
      }))
    : [];
  const activeEntry = entries.find((entry) => entry.track_id === activeTrackId);
  const selectedBeat = activeEntry?.measure.beats[0] ?? null;
  return {
    operation: {
      kind: "insert_measure_group",
      entries,
      performance_events: performanceEvents,
      techniques,
      tempo_changes: [],
      time_signatures: [],
    },
    measureIds: entries.map((entry) => entry.measure.id),
    selectedBeatId: selectedBeat?.id ?? null,
    selectedNoteId: selectedBeat?.notes[0]?.id ?? null,
  };
}

export function prepareMeasureDelete(
  document: ScoreDocument,
  measureNumber: number,
  activeTrackId: string,
): PreparedMeasureDelete {
  const group = alignedMeasureGroup(document, measureNumber);
  if (group.some(({ track }) => track.measures.length <= 1)) {
    throw new Error("A score must keep at least one bar.");
  }
  const activeTrack = document.tracks.find((track) => track.id === activeTrackId);
  const surviving = activeTrack?.measures
    .filter((measure) => measure.number !== measureNumber)
    .sort((left, right) => (
      Math.abs(left.number - measureNumber) - Math.abs(right.number - measureNumber) ||
      right.number - left.number
    ))
    .find((measure) => measure.beats.length > 0);
  const fallbackBeat = surviving?.beats[0] ?? null;
  return {
    operation: {
      kind: "delete_measure_group",
      measure_ids: group.map(({ measure }) => measure.id),
      expected_measure_hashes: {},
    },
    measureIds: group.map(({ measure }) => measure.id),
    fallbackBeatId: fallbackBeat?.id ?? null,
    fallbackNoteId: fallbackBeat?.notes[0]?.id ?? null,
  };
}

function shiftMeasureTailLocally(
  document: ScoreDocument,
  index: number,
  delta: ScoreRational,
): void {
  const shiftedNoteIds = new Set<string>();
  for (const track of document.tracks) {
    const ordered = [...track.measures].sort((left, right) => (
      left.number - right.number || left.id.localeCompare(right.id)
    ));
    for (const measure of ordered.slice(index)) {
      measure.start = addRational(measure.start, delta);
      for (const beat of measure.beats) {
        beat.start = addRational(beat.start, delta);
        beat.notes.forEach((note) => shiftedNoteIds.add(note.id));
      }
    }
  }
  for (const event of document.performance.events) {
    if (shiftedNoteIds.has(event.note_id)) {
      event.start = addRational(event.start, delta);
    }
  }
}

function renumberMeasuresLocally(document: ScoreDocument): void {
  for (const track of document.tracks) {
    track.measures.sort((left, right) => (
      compareRational(left.start, right.start) ||
      left.number - right.number ||
      left.id.localeCompare(right.id)
    ));
    track.measures.forEach((measure, index) => { measure.number = index + 1; });
  }
}

export function applyOperationsLocally(
  document: ScoreDocument,
  operations: ScoreOperation[],
): ScoreDocument {
  const next = deepClone(document);
  for (const operation of operations) {
    if (operation.kind === "set_track_name") {
      const track = next.tracks.find((candidate) => candidate.id === operation.track_id);
      if (!track) throw new Error(`Track ${operation.track_id} is not available locally.`);
      track.name = operation.name;
      continue;
    }
    if (operation.kind === "set_track_instrument") {
      const track = next.tracks.find((candidate) => candidate.id === operation.track_id);
      if (!track) throw new Error(`Track ${operation.track_id} is not available locally.`);
      track.instrument = deepClone(operation.instrument);
      continue;
    }
    if (operation.kind === "set_track_notation_mode") {
      const track = next.tracks.find((candidate) => candidate.id === operation.track_id);
      if (!track) throw new Error(`Track ${operation.track_id} is not available locally.`);
      track.notation_mode = operation.notation_mode;
      continue;
    }
    if (operation.kind === "set_track_mixer") {
      const track = next.tracks.find((candidate) => candidate.id === operation.track_id);
      if (!track) throw new Error(`Track ${operation.track_id} is not available locally.`);
      track.mixer = deepClone(operation.mixer);
      continue;
    }
    if (operation.kind === "reorder_tracks") {
      const orderById = new Map(operation.track_ids.map((trackId, order) => [trackId, order]));
      if (orderById.size !== next.tracks.length) {
        throw new Error("Track order must contain every track exactly once.");
      }
      for (const track of next.tracks) {
        const order = orderById.get(track.id);
        if (order === undefined) throw new Error(`Track ${track.id} is missing from the order.`);
        track.order = order;
      }
      continue;
    }
    if (operation.kind === "insert_track") {
      if (next.tracks.some((track) => track.id === operation.track.id)) {
        throw new Error(`Track ${operation.track.id} already exists locally.`);
      }
      next.tracks.forEach((track) => {
        if (track.order >= operation.track.order) track.order += 1;
      });
      next.tracks.push(deepClone(operation.track));
      continue;
    }
    if (operation.kind === "delete_track") {
      const track = next.tracks.find((candidate) => candidate.id === operation.track_id);
      if (!track) throw new Error(`Track ${operation.track_id} is not available locally.`);
      next.tracks = next.tracks.filter((candidate) => candidate.id !== operation.track_id);
      next.tracks.forEach((candidate) => {
        if (candidate.order > track.order) candidate.order -= 1;
      });
      continue;
    }
    if (operation.kind === "set_note_pitch" || operation.kind === "set_note_fretting") {
      const note = next.tracks
        .flatMap((track) => track.measures)
        .flatMap((measure) => measure.beats)
        .flatMap((beat) => beat.notes)
        .find((candidate) => candidate.id === operation.note_id);
      if (!note) throw new Error(`Note ${operation.note_id} is not available locally.`);
      if (operation.kind === "set_note_pitch") note.pitch = operation.pitch;
      else {
        note.realization.string = operation.string;
        note.realization.fret = operation.fret;
      }
      continue;
    }
    if (operation.kind === "set_beat_duration") {
      const context = findBeat(next, operation.beat_id);
      if (!context) throw new Error(`Beat ${operation.beat_id} is not available locally.`);
      context.beat.duration = operation.duration;
      continue;
    }
    if (operation.kind === "set_beat_tie") {
      const context = findBeat(next, operation.beat_id);
      if (!context) throw new Error(`Beat ${operation.beat_id} is not available locally.`);
      context.beat.tie_in = operation.tie_in;
      context.beat.tie_out = operation.tie_out;
      continue;
    }
    if (operation.kind === "set_beat_dynamic") {
      const context = findBeat(next, operation.beat_id);
      if (!context) throw new Error(`Beat ${operation.beat_id} is not available locally.`);
      if (operation.dynamic === null) delete context.beat.properties.dynamic;
      else context.beat.properties.dynamic = operation.dynamic;
      continue;
    }
    if (operation.kind === "set_performance_velocity") {
      const event = next.performance.events.find(
        (candidate) => candidate.note_id === operation.note_id,
      );
      if (!event) {
        throw new Error(`Performance event for note ${operation.note_id} is unavailable locally.`);
      }
      event.velocity = operation.velocity;
      continue;
    }
    if (operation.kind === "set_beat_voice") {
      const context = findBeat(next, operation.beat_id);
      if (!context) throw new Error(`Beat ${operation.beat_id} is not available locally.`);
      context.beat.voice = operation.voice;
      continue;
    }
    if (operation.kind === "add_note") {
      const context = findBeat(next, operation.beat_id);
      if (!context) throw new Error(`Beat ${operation.beat_id} is not available locally.`);
      if (context.beat.notes.some((note) => note.id === operation.note.id)) {
        throw new Error(`Note ${operation.note.id} already exists locally.`);
      }
      context.beat.kind = "notes";
      context.beat.notes.push(deepClone(operation.note));
      next.performance.events.push(deepClone(operation.performance_event));
      continue;
    }
    if (operation.kind === "delete_note") {
      const context = findBeat(next, operation.beat_id);
      if (!context) throw new Error(`Beat ${operation.beat_id} is not available locally.`);
      if (!context.beat.notes.some((note) => note.id === operation.note_id)) {
        throw new Error(`Note ${operation.note_id} is not available locally.`);
      }
      if (next.techniques.some((technique) => {
        const noteIds = Array.isArray(technique.note_ids) ? technique.note_ids : [];
        return noteIds.includes(operation.note_id);
      })) {
        throw new Error("Remove or retarget the note technique before deleting this note.");
      }
      context.beat.notes = context.beat.notes.filter((note) => note.id !== operation.note_id);
      context.beat.kind = context.beat.notes.length > 0 ? "notes" : "rest";
      next.performance.events = next.performance.events.filter(
        (event) => event.note_id !== operation.note_id,
      );
      continue;
    }
    if (operation.kind === "add_technique") {
      if (next.techniques.some((technique) => technique.id === operation.technique.id)) {
        throw new Error(`Technique ${operation.technique.id} already exists locally.`);
      }
      for (const noteId of operation.technique.note_ids) {
        const context = findNote(next, noteId);
        if (!context) throw new Error(`Note ${noteId} is not available locally.`);
        if (!context.note.technique_ids.includes(operation.technique.id)) {
          context.note.technique_ids.push(operation.technique.id);
        }
      }
      next.techniques.push(deepClone(operation.technique));
      continue;
    }
    if (operation.kind === "delete_technique") {
      const technique = next.techniques.find(
        (candidate) => candidate.id === operation.technique_id,
      );
      if (!technique) {
        throw new Error(`Technique ${operation.technique_id} is not available locally.`);
      }
      for (const noteId of technique.note_ids) {
        const context = findNote(next, noteId);
        if (context) {
          context.note.technique_ids = context.note.technique_ids.filter(
            (techniqueId) => techniqueId !== technique.id,
          );
        }
      }
      next.techniques = next.techniques.filter(
        (candidate) => candidate.id !== operation.technique_id,
      );
      continue;
    }
    if (operation.kind === "insert_beat") {
      const track = next.tracks.find((candidate) => candidate.id === operation.track_id);
      const measure = track?.measures.find((candidate) => candidate.id === operation.measure_id);
      if (!measure) throw new Error(`Measure ${operation.measure_id} is not available locally.`);
      measure.beats.push(deepClone(operation.beat));
      next.performance.events.push(...deepClone(operation.performance_events));
      continue;
    }
    if (operation.kind === "delete_beat") {
      const context = findBeat(next, operation.beat_id);
      if (!context) throw new Error(`Beat ${operation.beat_id} is not available locally.`);
      const noteIds = new Set(context.beat.notes.map((note) => note.id));
      context.measure.beats = context.measure.beats.filter(
        (beat) => beat.id !== operation.beat_id,
      );
      next.performance.events = next.performance.events.filter(
        (event) => !noteIds.has(event.note_id),
      );
      continue;
    }
    if (operation.kind === "insert_measure_group") {
      const first = operation.entries[0]?.measure;
      if (!first) throw new Error("The measure group is empty.");
      const insertionIndex = first.number - 1;
      shiftMeasureTailLocally(next, insertionIndex, first.duration);
      next.tempo_map.forEach((tempo) => {
        if (compareRational(tempo.position, first.start) >= 0) {
          tempo.position = addRational(tempo.position, first.duration);
        }
      });
      next.time_signatures.forEach((signature) => {
        if (compareRational(signature.position, first.start) >= 0) {
          signature.position = addRational(signature.position, first.duration);
        }
      });
      for (const entry of operation.entries) {
        const track = next.tracks.find((candidate) => candidate.id === entry.track_id);
        if (!track) throw new Error(`Track ${entry.track_id} is not available locally.`);
        track.measures.splice(insertionIndex, 0, deepClone(entry.measure));
      }
      next.performance.events.push(...deepClone(operation.performance_events));
      next.techniques.push(...deepClone(operation.techniques));
      next.tempo_map.push(...deepClone(operation.tempo_changes));
      next.time_signatures.push(...deepClone(operation.time_signatures));
      for (const technique of operation.techniques) {
        for (const noteId of technique.note_ids) {
          const context = findNote(next, noteId);
          if (context && !context.note.technique_ids.includes(technique.id)) {
            context.note.technique_ids.push(technique.id);
          }
        }
      }
      renumberMeasuresLocally(next);
      continue;
    }
    const resolved = operation.measure_ids.map((measureId) => {
      for (const track of next.tracks) {
        const measure = track.measures.find((candidate) => candidate.id === measureId);
        if (measure) return { track, measure };
      }
      throw new Error(`Measure ${measureId} is not available locally.`);
    });
    const first = resolved[0]?.measure;
    if (!first) throw new Error("The measure group is empty.");
    const deletionIndex = first.number - 1;
    const end = addRational(first.start, first.duration);
    const noteIds = new Set(
      resolved.flatMap(({ measure }) => (
        measure.beats.flatMap((beat) => beat.notes.map((note) => note.id))
      )),
    );
    const crossing = next.techniques.some((technique) => (
      technique.note_ids.some((noteId) => noteIds.has(noteId)) &&
      !technique.note_ids.every((noteId) => noteIds.has(noteId))
    ));
    if (crossing) {
      throw new Error("A linked technique crosses this bar boundary.");
    }
    resolved.forEach(({ track, measure }) => {
      track.measures = track.measures.filter((candidate) => candidate.id !== measure.id);
    });
    next.performance.events = next.performance.events.filter(
      (event) => !noteIds.has(event.note_id),
    );
    next.techniques = next.techniques.filter(
      (technique) => !technique.note_ids.some((noteId) => noteIds.has(noteId)),
    );
    next.tempo_map = next.tempo_map.filter((tempo) => !(
      compareRational(tempo.position, first.start) >= 0 &&
      compareRational(tempo.position, end) < 0
    ));
    next.time_signatures = next.time_signatures.filter((signature) => !(
      compareRational(signature.position, first.start) >= 0 &&
      compareRational(signature.position, end) < 0
    ));
    const negativeDuration = rational(-first.duration.numerator, first.duration.denominator);
    shiftMeasureTailLocally(next, deletionIndex, negativeDuration);
    next.tempo_map.forEach((tempo) => {
      if (compareRational(tempo.position, end) >= 0) {
        tempo.position = subtractRational(tempo.position, first.duration);
      }
    });
    next.time_signatures.forEach((signature) => {
      if (compareRational(signature.position, end) >= 0) {
        signature.position = subtractRational(signature.position, first.duration);
      }
    });
    renumberMeasuresLocally(next);
  }
  return next;
}
