import { AlphaTabApi, Settings, model } from "@coderline/alphatab";
import "./probe.css";

const MEASURE_COUNT = 104;

type AlphaScore = InstanceType<typeof model.Score>;
type AlphaTrack = InstanceType<typeof model.Track>;
type AlphaStaff = InstanceType<typeof model.Staff>;
type AlphaVoice = InstanceType<typeof model.Voice>;
type AlphaBeat = InstanceType<typeof model.Beat>;
type AlphaNote = InstanceType<typeof model.Note>;

interface ProbeState {
  api: AlphaTabApi;
  score: AlphaScore;
  beatIds: Map<number, string>;
  noteIds: Map<number, string>;
  selectedNote: AlphaNote | null;
  selectedBeat: AlphaBeat | null;
  renderStartedAt: number;
  initialRenderMs: number | null;
  rerenderMs: number | null;
  playerReady: boolean;
  midiReady: boolean;
  firstNotePoint: { x: number; y: number } | null;
}

declare global {
  interface Window {
    __alphaTabProbe: ProbeState;
  }
}

const element = <T extends HTMLElement>(id: string): T => {
  const value = document.getElementById(id);
  if (!value) throw new Error(`Missing probe element ${id}`);
  return value as T;
};

const settings = new Settings();
settings.core.engine = "svg";
settings.core.useWorkers = false;
settings.core.includeNoteBounds = true;
settings.core.enableLazyLoading = false;
settings.core.fontDirectory = "/font/";
settings.player.enablePlayer = true;
settings.player.soundFont = "/soundfont/sonivox.sf2";

const score = new model.Score();
score.title = "BandPilot E0 AlphaTab probe";

const beatIds = new Map<number, string>();
const noteIds = new Map<number, string>();

function createTrack(
  name: string,
  staffDefinitions: Array<{
    id: string;
    percussion?: boolean;
    tablature?: boolean;
    tuning?: number[];
  }>,
): { track: AlphaTrack; staves: AlphaStaff[] } {
  const track = new model.Track();
  track.name = name;
  track.shortName = name.slice(0, 4);
  score.addTrack(track);
  const staves = staffDefinitions.map((definition) => {
    const staff = new model.Staff();
    staff.showStandardNotation = true;
    staff.showTablature = definition.tablature ?? false;
    staff.isPercussion = definition.percussion ?? false;
    staff.standardNotationLineCount = 5;
    if (definition.tuning) {
      staff.stringTuning = new model.Tuning(
        "BandPilot probe",
        definition.tuning,
        true,
      );
    }
    track.addStaff(staff);
    return staff;
  });
  return { track, staves };
}

const guitar = createTrack("Guitar", [
  {
    id: "track:guitar:staff:standard-tab",
    tablature: true,
    tuning: [64, 59, 55, 50, 45, 40],
  },
]);
const bass = createTrack("Bass", [
  {
    id: "track:bass:staff:standard-tab",
    tablature: true,
    tuning: [43, 38, 33, 28],
  },
]);
const drums = createTrack("Drums", [
  { id: "track:drums:staff:percussion", percussion: true },
]);
const keys = createTrack("Keys", [
  { id: "track:keys:staff:treble" },
  { id: "track:keys:staff:bass" },
]);
const generic = createTrack("Strings", [
  { id: "track:generic:staff:standard" },
]);

function pitchedNote(pitch: number): AlphaNote {
  const note = new model.Note();
  note.octave = Math.floor(pitch / 12);
  note.tone = pitch % 12;
  return note;
}

function stringNote(bandPilotString: number, fret: number, stringCount: number): AlphaNote {
  const note = new model.Note();
  note.string = stringCount + 1 - bandPilotString;
  note.fret = fret;
  return note;
}

function percussionNote(gmPitch: number): AlphaNote {
  const note = new model.Note();
  note.percussionArticulation = gmPitch;
  return note;
}

function addBeat(
  voice: AlphaVoice,
  stableBeatId: string,
  stableNoteId: string,
  note: AlphaNote,
): void {
  const beat = new model.Beat();
  beat.duration = model.Duration.Quarter;
  beat.addNote(note);
  voice.addBeat(beat);
  beatIds.set(beat.id, stableBeatId);
  noteIds.set(note.id, stableNoteId);
}

function addBar(
  staff: AlphaStaff,
  stableStaffId: string,
  measureIndex: number,
  voices: Array<(voice: AlphaVoice, beatIndex: number) => void>,
): void {
  const bar = new model.Bar();
  staff.addBar(bar);
  voices.forEach((populate, voiceIndex) => {
    const voice = new model.Voice();
    bar.addVoice(voice);
    for (let beatIndex = 0; beatIndex < 4; beatIndex += 1) {
      populate(voice, beatIndex);
    }
    void voiceIndex;
  });
  bar.style = undefined;
  void stableStaffId;
  void measureIndex;
}

for (let measureIndex = 0; measureIndex < MEASURE_COUNT; measureIndex += 1) {
  const masterBar = new model.MasterBar();
  masterBar.timeSignatureNumerator = 4;
  masterBar.timeSignatureDenominator = 4;
  score.addMasterBar(masterBar);

  addBar(
    guitar.staves[0],
    "track:guitar:staff:standard-tab",
    measureIndex,
    [
      (voice, beatIndex) =>
        addBeat(
          voice,
          `track:guitar:measure:${measureIndex + 1}:beat:${beatIndex + 1}`,
          `note:guitar:${measureIndex + 1}:${beatIndex + 1}`,
          stringNote(1 + (beatIndex % 3), beatIndex, 6),
        ),
    ],
  );
  addBar(
    bass.staves[0],
    "track:bass:staff:standard-tab",
    measureIndex,
    [
      (voice, beatIndex) =>
        addBeat(
          voice,
          `track:bass:measure:${measureIndex + 1}:beat:${beatIndex + 1}`,
          `note:bass:${measureIndex + 1}:${beatIndex + 1}`,
          stringNote(1 + (beatIndex % 2), beatIndex, 4),
        ),
    ],
  );
  addBar(
    drums.staves[0],
    "track:drums:staff:percussion",
    measureIndex,
    [
      (voice, beatIndex) =>
        addBeat(
          voice,
          `track:drums:measure:${measureIndex + 1}:hands:${beatIndex + 1}`,
          `note:drums:snare:${measureIndex + 1}:${beatIndex + 1}`,
          percussionNote(beatIndex % 2 === 0 ? 42 : 38),
        ),
      (voice, beatIndex) =>
        addBeat(
          voice,
          `track:drums:measure:${measureIndex + 1}:feet:${beatIndex + 1}`,
          `note:drums:kick:${measureIndex + 1}:${beatIndex + 1}`,
          percussionNote(36),
        ),
    ],
  );
  addBar(
    keys.staves[0],
    "track:keys:staff:treble",
    measureIndex,
    [
      (voice, beatIndex) =>
        addBeat(
          voice,
          `track:keys:treble:measure:${measureIndex + 1}:beat:${beatIndex + 1}`,
          `note:keys:right:${measureIndex + 1}:${beatIndex + 1}`,
          pitchedNote(72 + (beatIndex % 3)),
        ),
    ],
  );
  addBar(
    keys.staves[1],
    "track:keys:staff:bass",
    measureIndex,
    [
      (voice, beatIndex) =>
        addBeat(
          voice,
          `track:keys:bass:measure:${measureIndex + 1}:beat:${beatIndex + 1}`,
          `note:keys:left:${measureIndex + 1}:${beatIndex + 1}`,
          pitchedNote(48 + (beatIndex % 3)),
        ),
    ],
  );
  addBar(
    generic.staves[0],
    "track:generic:staff:standard",
    measureIndex,
    [
      (voice, beatIndex) =>
        addBeat(
          voice,
          `track:generic:measure:${measureIndex + 1}:beat:${beatIndex + 1}`,
          `note:generic:${measureIndex + 1}:${beatIndex + 1}`,
          pitchedNote(60 + (beatIndex % 5)),
        ),
    ],
  );
}

score.finish(settings);

const container = element<HTMLDivElement>("score");
const api = new AlphaTabApi(container, settings);
const probeState: ProbeState = {
  api,
  score,
  beatIds,
  noteIds,
  selectedNote: null,
  selectedBeat: null,
  renderStartedAt: performance.now(),
  initialRenderMs: null,
  rerenderMs: null,
  playerReady: false,
  midiReady: false,
  firstNotePoint: null,
};
window.__alphaTabProbe = probeState;

const state = element<HTMLElement>("state");
const renderMs = element<HTMLElement>("render-ms");
const rerenderMs = element<HTMLElement>("rerender-ms");
const boundNotes = element<HTMLElement>("bound-notes");
const selectedId = element<HTMLElement>("selected-id");
const playerState = element<HTMLElement>("player-state");
const mutateButton = element<HTMLButtonElement>("mutate");
const playButton = element<HTMLButtonElement>("play-note");

function updatePlayerState(): void {
  playerState.textContent = probeState.playerReady
    ? probeState.midiReady
      ? "ready + MIDI mapped"
      : "ready"
    : "loading";
}

function inspectBounds(): void {
  const lookup = api.boundsLookup;
  if (!lookup) return;
  const noteBounds = lookup.staffSystems.flatMap((system) =>
    system.bars.flatMap((master) =>
      master.bars.flatMap((bar) =>
        bar.beats.flatMap((beat) => beat.notes ?? []),
      ),
    ),
  );
  boundNotes.textContent = noteBounds.length.toLocaleString();
  const first = noteBounds[0];
  if (first) {
    const rect = container.getBoundingClientRect();
    probeState.firstNotePoint = {
      x: rect.left + first.noteHeadBounds.x + first.noteHeadBounds.w / 2,
      y: rect.top + first.noteHeadBounds.y + first.noteHeadBounds.h / 2,
    };
  }
}

api.noteMouseDown.on((note) => {
  probeState.selectedNote = note;
  probeState.selectedBeat = note.beat;
  const stableId = noteIds.get(note.id) ?? "unmapped";
  selectedId.textContent = stableId;
  mutateButton.disabled = stableId === "unmapped";
  playButton.disabled = stableId === "unmapped" || !probeState.playerReady;
  api.highlightPlaybackRange(note.beat, note.beat);
});

api.beatMouseDown.on((beat) => {
  probeState.selectedBeat = beat;
  if (!probeState.selectedNote) {
    selectedId.textContent = beatIds.get(beat.id) ?? "unmapped beat";
  }
});

api.postRenderFinished.on(() => {
  const elapsed = performance.now() - probeState.renderStartedAt;
  if (probeState.initialRenderMs === null) {
    probeState.initialRenderMs = elapsed;
    renderMs.textContent = `${Math.round(elapsed)} ms`;
    state.textContent = "ready";
    state.dataset.ready = "true";
  } else {
    probeState.rerenderMs = elapsed;
    rerenderMs.textContent = `${Math.round(elapsed)} ms`;
    state.textContent = "mutated + rerendered";
    state.dataset.rerendered = "true";
  }
  inspectBounds();
});

api.playerReady.on(() => {
  probeState.playerReady = true;
  playButton.disabled = probeState.selectedNote === null;
  updatePlayerState();
});

api.midiLoaded.on(() => {
  probeState.midiReady = api.tickCache !== null;
  updatePlayerState();
});

mutateButton.addEventListener("click", () => {
  const note = probeState.selectedNote;
  if (!note) return;
  if (note.isStringed) note.fret += 1;
  else note.tone = (note.tone + 1) % 12;
  score.finish(settings);
  probeState.renderStartedAt = performance.now();
  api.renderScore(score, score.tracks.map((track) => track.index));
});

playButton.addEventListener("click", () => {
  if (probeState.selectedNote) api.playNote(probeState.selectedNote);
});

api.renderScore(score, score.tracks.map((track) => track.index));
