import type {
  ScoreDocument,
  ScoreOperation,
  ScoreStaff,
  ScoreTrack,
} from "../api/types";

export const TRACK_FAMILIES = ["guitar", "bass", "drums", "keys", "generic"] as const;
export type TrackFamily = (typeof TRACK_FAMILIES)[number];

export const TRACK_NOTATION_MODES: Record<TrackFamily, Array<{ value: string; label: string }>> = {
  guitar: [
    { value: "standard_tab", label: "Standard + TAB" },
    { value: "tablature", label: "TAB only" },
    { value: "standard", label: "Standard only" },
  ],
  bass: [
    { value: "standard_tab", label: "Standard + TAB" },
    { value: "tablature", label: "TAB only" },
    { value: "standard", label: "Standard only" },
  ],
  drums: [{ value: "percussion", label: "Five-line percussion" }],
  keys: [
    { value: "grand_staff", label: "Grand staff" },
    { value: "standard", label: "Single staff" },
  ],
  generic: [{ value: "standard", label: "Standard notation" }],
};

function defaultInstrument(family: TrackFamily): Record<string, unknown> {
  if (family === "guitar") {
    return { tuning: [40, 45, 50, 55, 59, 64], tuning_name: "Standard", fret_count: 24, capo: 0, program: 25 };
  }
  if (family === "bass") {
    return { tuning: [28, 33, 38, 43], tuning_name: "Standard", fret_count: 24, capo: 0, program: 33 };
  }
  if (family === "drums") return { kit: "standard_5pc" };
  if (family === "keys") return { program: 0 };
  return { program: 0 };
}

function staves(trackId: string, family: TrackFamily): ScoreStaff[] {
  if (family === "guitar" || family === "bass") {
    return [{ id: `${trackId}:staff:standard-tab`, order: 0, kind: "standard_tab", line_count: 5 }];
  }
  if (family === "drums") {
    return [{ id: `${trackId}:staff:percussion`, order: 0, kind: "percussion", line_count: 5 }];
  }
  if (family === "keys") {
    return [
      { id: `${trackId}:staff:treble`, order: 0, kind: "treble", line_count: 5 },
      { id: `${trackId}:staff:bass`, order: 1, kind: "bass", line_count: 5 },
    ];
  }
  return [{ id: `${trackId}:staff:standard`, order: 0, kind: "standard", line_count: 5 }];
}

export function createEmptyTrack(
  document: ScoreDocument,
  family: TrackFamily,
  createId: () => string = () => crypto.randomUUID(),
): ScoreTrack {
  const reference = [...(document.tracks[0]?.measures ?? [])].sort((left, right) => left.number - right.number);
  if (reference.length === 0) throw new Error("A new track requires an existing score timeline.");
  const trackId = `track:${createId()}`;
  const trackStaves = staves(trackId, family);
  return {
    id: trackId,
    order: document.tracks.length,
    name: `${family === "generic" ? "Notation" : family[0]!.toUpperCase() + family.slice(1)} ${document.tracks.length + 1}`,
    family,
    role: "unknown",
    source_track_indices: [],
    instrument: defaultInstrument(family),
    staves: trackStaves,
    measures: reference.map((measure) => ({
      ...structuredClone(measure),
      id: `${trackId}:measure:${measure.number}:${createId()}`,
      beats: [],
    })),
    notation_mode: TRACK_NOTATION_MODES[family][0]!.value,
    mixer: { volume: 0.8, pan: 0, mute: false, solo: false },
  };
}

export interface TrackSetupInput {
  name: string;
  notationMode: string;
  program: number;
  capo: number;
  tuning: number[] | null;
}

export function prepareTrackSetup(track: ScoreTrack, input: TrackSetupInput): ScoreOperation[] {
  const name = input.name.trim();
  if (!name) throw new Error("Track name cannot be empty.");
  if (!Number.isInteger(input.program) || input.program < 0 || input.program > 127) {
    throw new Error("MIDI program must be between 0 and 127.");
  }
  if (!Number.isInteger(input.capo) || input.capo < 0 || input.capo > 24) {
    throw new Error("Capo must be between 0 and 24.");
  }
  const fretted = track.family === "guitar" || track.family === "bass";
  if (fretted && (!input.tuning || input.tuning.length < 4 || input.tuning.length > 7)) {
    throw new Error("Guitar and bass tuning must contain 4–7 MIDI pitches.");
  }
  if (input.tuning?.some((pitch) => !Number.isInteger(pitch) || pitch < 0 || pitch > 127)) {
    throw new Error("Every tuning pitch must be a MIDI integer in 0..127.");
  }

  const operations: ScoreOperation[] = [];
  if (name !== track.name) {
    operations.push({ kind: "set_track_name", track_id: track.id, name, expected_name: track.name });
  }
  if (input.notationMode !== track.notation_mode) {
    operations.push({
      kind: "set_track_notation_mode",
      track_id: track.id,
      notation_mode: input.notationMode,
      expected_notation_mode: track.notation_mode,
    });
  }
  const instrument: Record<string, unknown> = { ...track.instrument, program: input.program };
  if (fretted && input.tuning) {
    instrument.tuning = [...input.tuning];
    instrument.capo = input.capo;
  }
  if (JSON.stringify(instrument) !== JSON.stringify(track.instrument)) {
    operations.push({
      kind: "set_track_instrument",
      track_id: track.id,
      instrument,
      expected_instrument: structuredClone(track.instrument),
    });
  }

  if (fretted && input.tuning) {
    const fretCount = Number(instrument.fret_count ?? 24);
    for (const measure of track.measures) {
      for (const beat of measure.beats) {
        for (const note of beat.notes) {
          const stringNumber = note.realization.string;
          if (stringNumber === null || stringNumber < 1 || stringNumber > input.tuning.length) {
            throw new Error(`Note ${note.id} has no valid string in the requested tuning.`);
          }
          const openPitch = input.tuning[input.tuning.length - stringNumber]!;
          const fret = note.pitch - openPitch - input.capo;
          if (fret < 0 || fret > fretCount) {
            throw new Error(`The requested tuning cannot preserve note ${note.id} on its current string.`);
          }
          if (fret !== note.realization.fret) {
            operations.push({
              kind: "set_note_fretting",
              note_id: note.id,
              string: stringNumber,
              fret,
              expected_string: stringNumber,
              expected_fret: note.realization.fret,
            });
          }
        }
      }
    }
  }
  return operations;
}

export function parseTuning(value: string): number[] {
  const pitchClasses: Record<string, number> = {
    C: 0, "C#": 1, Db: 1, D: 2, "D#": 3, Eb: 3, E: 4,
    F: 5, "F#": 6, Gb: 6, G: 7, "G#": 8, Ab: 8, A: 9,
    "A#": 10, Bb: 10, B: 11,
  };
  const pitches = value.split(/[\s,]+/).filter(Boolean).map((token) => {
    if (/^\d+$/.test(token)) return Number(token);
    const match = /^([a-gA-G])([#b]?)(-1|\d)$/.exec(token);
    if (!match) return Number.NaN;
    const name = `${match[1]!.toUpperCase()}${match[2] ?? ""}`;
    const pitchClass = pitchClasses[name];
    return pitchClass === undefined ? Number.NaN : (Number(match[3]) + 1) * 12 + pitchClass;
  });
  if (pitches.some((pitch) => !Number.isInteger(pitch) || pitch < 0 || pitch > 127)) {
    throw new Error("Use note names such as E2 A2 D3 G3 B3 E4, or MIDI pitch integers.");
  }
  return pitches;
}

export function formatTuning(pitches: number[]): string {
  const names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  return pitches.map((pitch) => `${names[pitch % 12]}${Math.floor(pitch / 12) - 1}`).join(" ");
}
