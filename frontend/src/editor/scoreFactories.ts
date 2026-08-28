import type {
  ScoreBeat,
  ScoreNote,
  ScorePerformanceEvent,
  ScoreTrack,
} from "../api/types";

export interface FirstNoteBeat {
  beat: ScoreBeat;
  measureId: string;
  noteId: string;
  performanceEvents: ScorePerformanceEvent[];
}

export interface FirstRestBeat {
  beat: ScoreBeat;
  measureId: string;
}

/** Build the smallest valid editable event for a new blank instrument track. */
export function createFirstNoteBeat(
  track: ScoreTrack,
  createId: () => string = () => crypto.randomUUID(),
): FirstNoteBeat {
  const measure = track.measures[0];
  const staff = track.staves[0];
  if (!measure || !staff) throw new Error("A blank track requires a measure and staff.");
  const noteId = `note:${createId()}`;
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
    pitch = 38;
    realization.piece = "snare";
    realization.hit_technique = "center";
  } else if (track.family === "keys") {
    realization.hand = "right";
    realization.finger = 1;
  }
  const beat: ScoreBeat = {
    id: `beat:${createId()}`,
    start: measure.start,
    duration: { numerator: 1, denominator: 1 },
    voice: 1,
    staff_id: staff.id,
    kind: "notes",
    notes: [{
      id: noteId,
      pitch,
      source: null,
      realization,
      technique_ids: [],
      properties: {},
    }],
    tie_in: false,
    tie_out: false,
    properties: {},
  };
  return {
    measureId: measure.id,
    noteId,
    beat,
    performanceEvents: [{
      id: `performance:${createId()}`,
      note_id: noteId,
      start: beat.start,
      duration: beat.duration,
      velocity: 80,
      controls: [],
    }],
  };
}

/** Build an explicit quarter rest at the beginning of a blank track. */
export function createFirstRestBeat(
  track: ScoreTrack,
  createId: () => string = () => crypto.randomUUID(),
): FirstRestBeat {
  const measure = track.measures[0];
  const staff = track.staves[0];
  if (!measure || !staff) throw new Error("A blank track requires a measure and staff.");
  return {
    measureId: measure.id,
    beat: {
      id: `beat:${createId()}`,
      start: measure.start,
      duration: { numerator: 1, denominator: 1 },
      voice: 1,
      staff_id: staff.id,
      kind: "rest",
      notes: [],
      tie_in: false,
      tie_out: false,
      properties: {},
    },
  };
}
