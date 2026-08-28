import { Settings, model } from "@coderline/alphatab";
import { performance } from "node:perf_hooks";

const measureCount = 104;
const settings = new Settings();
const score = new model.Score();
score.title = "BandPilot E0 core probe";
const beatIds = new Map();
const noteIds = new Map();

function track(name, { tuning = null, tablature = false, percussion = false, staves = 1 }) {
  const value = new model.Track();
  value.name = name;
  score.addTrack(value);
  const result = [];
  for (let index = 0; index < staves; index += 1) {
    const staff = new model.Staff();
    staff.showStandardNotation = true;
    staff.showTablature = tablature;
    staff.isPercussion = percussion;
    staff.standardNotationLineCount = 5;
    if (tuning) staff.stringTuning = new model.Tuning("Probe", tuning, true);
    value.addStaff(staff);
    result.push(staff);
  }
  return { track: value, staves: result };
}

const guitar = track("Guitar", {
  tuning: [64, 59, 55, 50, 45, 40],
  tablature: true,
});
const bass = track("Bass", { tuning: [43, 38, 33, 28], tablature: true });
const drums = track("Drums", { percussion: true });
const keys = track("Keys", { staves: 2 });
const generic = track("Strings", {});

function stringNote(string, fret, stringCount) {
  const note = new model.Note();
  note.string = stringCount + 1 - string;
  note.fret = fret;
  return note;
}

function pitchedNote(pitch) {
  const note = new model.Note();
  note.octave = Math.floor(pitch / 12);
  note.tone = pitch % 12;
  return note;
}

function drumNote(pitch) {
  const note = new model.Note();
  note.percussionArticulation = pitch;
  return note;
}

function addVoice(bar, prefix, noteFactory) {
  const voice = new model.Voice();
  bar.addVoice(voice);
  for (let beatIndex = 0; beatIndex < 4; beatIndex += 1) {
    const beat = new model.Beat();
    beat.duration = model.Duration.Quarter;
    const note = noteFactory(beatIndex);
    beat.addNote(note);
    voice.addBeat(beat);
    beatIds.set(beat.id, `${prefix}:beat:${beatIndex + 1}`);
    noteIds.set(note.id, `${prefix}:note:${beatIndex + 1}`);
  }
}

function addBar(staff, prefix, noteFactories) {
  const bar = new model.Bar();
  staff.addBar(bar);
  for (const noteFactory of noteFactories) addVoice(bar, prefix, noteFactory);
}

const startedAt = performance.now();
for (let measure = 1; measure <= measureCount; measure += 1) {
  const masterBar = new model.MasterBar();
  masterBar.timeSignatureNumerator = 4;
  masterBar.timeSignatureDenominator = 4;
  score.addMasterBar(masterBar);
  addBar(guitar.staves[0], `guitar:${measure}`, [
    (beat) => stringNote(1 + (beat % 3), beat, 6),
  ]);
  addBar(bass.staves[0], `bass:${measure}`, [
    (beat) => stringNote(1 + (beat % 2), beat, 4),
  ]);
  addBar(drums.staves[0], `drums-hands:${measure}`, [
    (beat) => drumNote(beat % 2 === 0 ? 42 : 38),
    () => drumNote(36),
  ]);
  addBar(keys.staves[0], `keys-right:${measure}`, [
    (beat) => pitchedNote(72 + (beat % 3)),
  ]);
  addBar(keys.staves[1], `keys-left:${measure}`, [
    (beat) => pitchedNote(48 + (beat % 3)),
  ]);
  addBar(generic.staves[0], `generic:${measure}`, [
    (beat) => pitchedNote(60 + beat),
  ]);
}
score.finish(settings);
const finishMs = performance.now() - startedAt;

const selected = guitar.staves[0].bars[0].voices[0].beats[0].notes[0];
const stableId = noteIds.get(selected.id);
const previousPitch = selected.realValue;
selected.fret += 1;
score.finish(settings);

const result = {
  measures: score.masterBars.length,
  tracks: score.tracks.length,
  staves: score.tracks.reduce((total, value) => total + value.staves.length, 0),
  mappedBeats: beatIds.size,
  mappedNotes: noteIds.size,
  finishMs: Math.round(finishMs * 100) / 100,
  mutation: {
    stableId,
    previousPitch,
    currentPitch: selected.realValue,
  },
};

if (result.measures !== measureCount || result.tracks !== 5 || result.mappedNotes !== 2912) {
  throw new Error(`AlphaTab core probe failed: ${JSON.stringify(result)}`);
}
if (!stableId || result.mutation.currentPitch !== previousPitch + 1) {
  throw new Error(`AlphaTab mutation mapping failed: ${JSON.stringify(result.mutation)}`);
}

process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
