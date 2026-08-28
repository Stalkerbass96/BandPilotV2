import { model, type Settings } from "@coderline/alphatab";
import type {
  ScoreBeat,
  ScoreDocument,
  ScoreMeasure,
  ScoreNote,
  ScoreRational,
  ScoreStaff,
  ScoreTechnique,
  ScoreTrack,
} from "../api/types";

type AlphaScore = InstanceType<typeof model.Score>;
type AlphaStaff = InstanceType<typeof model.Staff>;
type AlphaVoice = InstanceType<typeof model.Voice>;
type AlphaBeat = InstanceType<typeof model.Beat>;
type AlphaNote = InstanceType<typeof model.Note>;

interface FractionValue {
  numerator: number;
  denominator: number;
}

interface DurationToken {
  duration: model.Duration;
  dots: number;
  tupletNumerator: number;
  tupletDenominator: number;
  value: FractionValue;
}

const DYNAMIC_VALUES: Record<string, model.DynamicValue> = {
  ppp: model.DynamicValue.PPP,
  pp: model.DynamicValue.PP,
  p: model.DynamicValue.P,
  mp: model.DynamicValue.MP,
  mf: model.DynamicValue.MF,
  f: model.DynamicValue.F,
  ff: model.DynamicValue.FF,
  fff: model.DynamicValue.FFF,
};

export interface AlphaTabScoreAdapterResult {
  score: AlphaScore;
  alphaBeatIds: Map<number, string>;
  alphaNoteIds: Map<number, string>;
  alphaTrackIds: Map<number, string>;
  stableBeatModels: Map<string, AlphaBeat[]>;
  stableNoteModels: Map<string, AlphaNote[]>;
  warnings: string[];
}

/** A truthful adapter failure. The editor must show this instead of distorting notation. */
export class AlphaTabAdapterError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AlphaTabAdapterError";
  }
}

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

function fraction(numerator: number, denominator = 1): FractionValue {
  if (!Number.isInteger(numerator) || !Number.isInteger(denominator) || denominator === 0) {
    throw new AlphaTabAdapterError("Score time must use finite integer fractions.");
  }
  const sign = denominator < 0 ? -1 : 1;
  const divisor = gcd(numerator, denominator);
  return {
    numerator: (numerator / divisor) * sign,
    denominator: Math.abs(denominator / divisor),
  };
}

function rational(value: ScoreRational): FractionValue {
  return fraction(value.numerator, value.denominator);
}

function add(left: FractionValue, right: FractionValue): FractionValue {
  return fraction(
    left.numerator * right.denominator + right.numerator * left.denominator,
    left.denominator * right.denominator,
  );
}

function subtract(left: FractionValue, right: FractionValue): FractionValue {
  return fraction(
    left.numerator * right.denominator - right.numerator * left.denominator,
    left.denominator * right.denominator,
  );
}

function multiply(left: FractionValue, right: FractionValue): FractionValue {
  return fraction(left.numerator * right.numerator, left.denominator * right.denominator);
}

function compare(left: FractionValue, right: FractionValue): number {
  return left.numerator * right.denominator - right.numerator * left.denominator;
}

function toNumber(value: FractionValue): number {
  return value.numerator / value.denominator;
}

function equals(left: FractionValue, right: FractionValue): boolean {
  return compare(left, right) === 0;
}

function fractionKey(value: FractionValue): string {
  return `${value.numerator}/${value.denominator}`;
}

function baseDurationValue(duration: model.Duration): FractionValue {
  if (duration === model.Duration.QuadrupleWhole) return fraction(16);
  if (duration === model.Duration.DoubleWhole) return fraction(8);
  return fraction(4, duration);
}

function dottedMultiplier(dots: number): FractionValue {
  if (dots === 0) return fraction(1);
  if (dots === 1) return fraction(3, 2);
  return fraction(7, 4);
}

function makeDurationTokens(): DurationToken[] {
  const durations = [
    model.Duration.QuadrupleWhole,
    model.Duration.DoubleWhole,
    model.Duration.Whole,
    model.Duration.Half,
    model.Duration.Quarter,
    model.Duration.Eighth,
    model.Duration.Sixteenth,
    model.Duration.ThirtySecond,
    model.Duration.SixtyFourth,
    model.Duration.OneHundredTwentyEighth,
    model.Duration.TwoHundredFiftySixth,
  ];
  const tokens: DurationToken[] = [];
  const seen = new Set<string>();
  for (const duration of durations) {
    for (const dots of [0, 1, 2]) {
      const value = multiply(baseDurationValue(duration), dottedMultiplier(dots));
      const key = fractionKey(value);
      if (!seen.has(key)) {
        seen.add(key);
        tokens.push({ duration, dots, tupletNumerator: -1, tupletDenominator: -1, value });
      }
    }
    for (const [tupletNumerator, tupletDenominator] of [
      [3, 2],
      [5, 4],
      [6, 4],
      [7, 4],
      [9, 8],
    ]) {
      const value = multiply(
        baseDurationValue(duration),
        fraction(tupletDenominator, tupletNumerator),
      );
      const key = fractionKey(value);
      if (!seen.has(key)) {
        seen.add(key);
        tokens.push({ duration, dots: 0, tupletNumerator, tupletDenominator, value });
      }
    }
  }
  return tokens.sort((left, right) => compare(right.value, left.value));
}

const DURATION_TOKENS = makeDurationTokens();
const MAX_DURATION_PARTS = 64;

/** Convert exact quarter-note time into one or more legal notation values. */
export function decomposeScoreDuration(
  duration: ScoreRational,
  context = "duration",
): DurationToken[] {
  const target = rational(duration);
  if (compare(target, fraction(0)) <= 0) {
    throw new AlphaTabAdapterError(`${context} must be greater than zero.`);
  }
  const solve = (
    remaining: FractionValue,
    partsLeft: number,
    memo: Map<string, DurationToken[] | null>,
  ): DurationToken[] | null => {
    if (remaining.numerator === 0) return [];
    if (partsLeft === 0) return null;
    const key = `${fractionKey(remaining)}:${partsLeft}`;
    if (memo.has(key)) return memo.get(key) ?? null;
    for (const token of DURATION_TOKENS) {
      if (compare(token.value, remaining) > 0) continue;
      const tail = solve(subtract(remaining, token.value), partsLeft - 1, memo);
      if (tail) {
        const result = [token, ...tail];
        memo.set(key, result);
        return result;
      }
    }
    memo.set(key, null);
    return null;
  };
  let result: DurationToken[] | null = null;
  // Prefer the fewest written symbols. This avoids mathematically valid but
  // unreadable chains of exotic tuplets when a simple tied pair exists.
  for (let partCount = 1; partCount <= MAX_DURATION_PARTS && !result; partCount += 1) {
    result = solve(target, partCount, new Map());
  }
  if (!result) {
    throw new AlphaTabAdapterError(
      `${context} ${fractionKey(target)} quarter notes cannot be represented exactly by alphaTab.`,
    );
  }
  return result;
}

function applyDuration(target: AlphaBeat, token: DurationToken): void {
  target.duration = token.duration;
  target.dots = token.dots;
  target.tupletNumerator = token.tupletNumerator;
  target.tupletDenominator = token.tupletDenominator;
}

function createRest(voice: AlphaVoice, token: DurationToken): void {
  const beat = new model.Beat();
  beat.isEmpty = false;
  applyDuration(beat, token);
  voice.addBeat(beat);
}

function trackTuning(track: ScoreTrack): number[] | null {
  const candidate = track.instrument.tuning;
  if (!Array.isArray(candidate) || candidate.length === 0) return null;
  const tuning = candidate.filter((pitch): pitch is number => (
    typeof pitch === "number" && Number.isInteger(pitch)
  ));
  return tuning.length === candidate.length ? tuning : null;
}

function configureStaff(alphaStaff: AlphaStaff, staff: ScoreStaff, track: ScoreTrack): void {
  const kind = staff.kind.toLowerCase();
  alphaStaff.showStandardNotation = track.notation_mode !== "tablature";
  alphaStaff.showTablature = (
    (track.notation_mode === "standard_tab" || track.notation_mode === "tablature") &&
    (track.family === "guitar" || track.family === "bass")
  );
  alphaStaff.isPercussion = kind.includes("percussion") || track.family === "drums";
  alphaStaff.standardNotationLineCount = staff.line_count;
  alphaStaff.capo = Number(track.instrument.capo ?? 0);
  const tuning = trackTuning(track);
  if (alphaStaff.showTablature && tuning) {
    // ScoreDocument uses musician-facing string 1 = highest. AlphaTab uses 1 = lowest.
    alphaStaff.stringTuning = new model.Tuning(
      String(track.instrument.tuning_name ?? "BandPilot tuning"),
      [...tuning].reverse(),
      false,
    );
  }
}

function configureClef(bar: InstanceType<typeof model.Bar>, staff: ScoreStaff, track: ScoreTrack): void {
  const kind = staff.kind.toLowerCase();
  if (track.family === "drums" || kind.includes("percussion")) {
    bar.clef = model.Clef.Neutral;
  } else if (kind === "bass" || (track.family === "bass" && !kind.includes("treble"))) {
    bar.clef = model.Clef.F4;
  } else {
    bar.clef = model.Clef.G2;
  }
}

function createAlphaNote(
  note: ScoreNote,
  track: ScoreTrack,
  continuation: boolean,
  techniquesById: ReadonlyMap<string, ScoreTechnique>,
): AlphaNote {
  const alphaNote = new model.Note();
  const tuning = trackTuning(track);
  if (
    tuning &&
    note.realization.string !== null &&
    note.realization.fret !== null &&
    (track.family === "guitar" || track.family === "bass")
  ) {
    const stringNumber = note.realization.string;
    if (stringNumber < 1 || stringNumber > tuning.length) {
      throw new AlphaTabAdapterError(
        `Note ${note.id} uses string ${stringNumber}, outside this ${tuning.length}-string instrument.`,
      );
    }
    alphaNote.string = tuning.length + 1 - stringNumber;
    alphaNote.fret = note.realization.fret;
  } else if (track.family === "drums") {
    alphaNote.percussionArticulation = note.pitch;
  } else {
    alphaNote.octave = Math.floor(note.pitch / 12);
    alphaNote.tone = note.pitch % 12;
  }
  const techniques = note.technique_ids
    .map((techniqueId) => techniquesById.get(techniqueId))
    .filter((value): value is ScoreTechnique => Boolean(value));
  const techniqueTypes = new Set(
    techniques.map((technique) => technique.type),
  );
  alphaNote.isPalmMute = techniqueTypes.has("palm_mute");
  alphaNote.isLetRing = techniqueTypes.has("let_ring");
  alphaNote.isStaccato = techniqueTypes.has("staccato");
  alphaNote.isGhost = techniqueTypes.has("ghost_note");
  if (techniqueTypes.has("heavy_accent")) {
    alphaNote.accentuated = model.AccentuationType.Heavy;
  } else if (techniqueTypes.has("accent")) {
    alphaNote.accentuated = model.AccentuationType.Normal;
  }
  if (track.family !== "drums") {
    const bend = techniques.find((technique) => technique.type === "bend");
    if (bend && !continuation) {
      const semitones = Math.max(0.25, Math.min(6, bend.parameters.semitones ?? 1));
      alphaNote.bendType = model.BendType.Bend;
      alphaNote.bendPoints = [
        new model.BendPoint(0, 0),
        new model.BendPoint(model.BendPoint.MaxPosition, semitones * 2),
      ];
    }
    if (techniqueTypes.has("harmonic")) {
      alphaNote.harmonicType = model.HarmonicType.Natural;
      alphaNote.harmonicValue = note.realization.fret ?? 12;
    }
    const vibrato = techniques.find((technique) => technique.type === "vibrato");
    if (vibrato) {
      alphaNote.vibrato = (vibrato.parameters.width ?? 1) >= 2
        ? model.VibratoType.Wide
        : model.VibratoType.Slight;
    }
  }
  alphaNote.isTieDestination = continuation;
  return alphaNote;
}

function appendScoreBeat(
  voice: AlphaVoice,
  scoreBeat: ScoreBeat,
  track: ScoreTrack,
  maps: Pick<
    AlphaTabScoreAdapterResult,
    "alphaBeatIds" | "alphaNoteIds" | "stableBeatModels" | "stableNoteModels"
  >,
  techniquesById: ReadonlyMap<string, ScoreTechnique>,
): void {
  const tokens = decomposeScoreDuration(scoreBeat.duration, `Beat ${scoreBeat.id}`);
  tokens.forEach((token, tokenIndex) => {
    const alphaBeat = new model.Beat();
    alphaBeat.isEmpty = false;
    applyDuration(alphaBeat, token);
    const dynamic = scoreBeat.properties.dynamic;
    if (typeof dynamic === "string" && dynamic in DYNAMIC_VALUES) {
      alphaBeat.dynamics = DYNAMIC_VALUES[dynamic]!;
    }
    for (const note of scoreBeat.notes) {
      const alphaNote = createAlphaNote(
        note,
        track,
        tokenIndex > 0 || scoreBeat.tie_in,
        techniquesById,
      );
      alphaBeat.addNote(alphaNote);
      maps.alphaNoteIds.set(alphaNote.id, note.id);
      const models = maps.stableNoteModels.get(note.id) ?? [];
      models.push(alphaNote);
      maps.stableNoteModels.set(note.id, models);
    }
    voice.addBeat(alphaBeat);
    maps.alphaBeatIds.set(alphaBeat.id, scoreBeat.id);
    const beatModels = maps.stableBeatModels.get(scoreBeat.id) ?? [];
    beatModels.push(alphaBeat);
    maps.stableBeatModels.set(scoreBeat.id, beatModels);
  });
}

function measureDuration(measure: ScoreMeasure): FractionValue {
  return rational(measure.duration);
}

function measureSignatureDuration(measure: ScoreMeasure): FractionValue {
  return fraction(measure.numerator * 4, measure.denominator);
}

function assertCompatibleMeasure(reference: ScoreMeasure, candidate: ScoreMeasure, trackId: string): void {
  if (
    candidate.numerator !== reference.numerator ||
    candidate.denominator !== reference.denominator ||
    !equals(rational(candidate.start), rational(reference.start)) ||
    !equals(measureDuration(candidate), measureDuration(reference))
  ) {
    throw new AlphaTabAdapterError(
      `Track ${trackId} measure ${candidate.number} does not align with the document measure grid.`,
    );
  }
}

function populateVoice(
  voice: AlphaVoice,
  beats: ScoreBeat[],
  measure: ScoreMeasure,
  track: ScoreTrack,
  maps: Pick<
    AlphaTabScoreAdapterResult,
    "alphaBeatIds" | "alphaNoteIds" | "stableBeatModels" | "stableNoteModels"
  >,
  techniquesById: ReadonlyMap<string, ScoreTechnique>,
): void {
  let cursor = fraction(0);
  const measureStart = rational(measure.start);
  for (const beat of beats.sort((left, right) => compare(rational(left.start), rational(right.start)))) {
    const localStart = subtract(rational(beat.start), measureStart);
    if (compare(localStart, cursor) < 0) {
      throw new AlphaTabAdapterError(
        `Voice ${beat.voice + 1} overlaps at beat ${beat.id}; overlapping events are not silently shifted.`,
      );
    }
    const gap = subtract(localStart, cursor);
    if (gap.numerator > 0) {
      for (const token of decomposeScoreDuration(gap, `Gap before ${beat.id}`)) createRest(voice, token);
    }
    appendScoreBeat(voice, beat, track, maps, techniquesById);
    cursor = add(localStart, rational(beat.duration));
  }
  const remaining = subtract(measureDuration(measure), cursor);
  if (remaining.numerator < 0) {
    throw new AlphaTabAdapterError(
      `Voice content exceeds measure ${measure.number} in track ${track.name}.`,
    );
  }
  if (remaining.numerator > 0) {
    for (const token of decomposeScoreDuration(remaining, `Measure ${measure.number} rest`)) {
      createRest(voice, token);
    }
  }
}

function applyLinkedTechniques(
  document: ScoreDocument,
  stableNoteModels: ReadonlyMap<string, AlphaNote[]>,
): void {
  for (const technique of document.techniques) {
    if (!(["hammer_on", "pull_off", "slide"] as string[]).includes(technique.type)) {
      continue;
    }
    if (technique.note_ids.length !== 2) continue;
    const sourceModels = stableNoteModels.get(technique.note_ids[0]!);
    const targetModels = stableNoteModels.get(technique.note_ids[1]!);
    const source = sourceModels?.[sourceModels.length - 1];
    const target = targetModels?.[0];
    if (!source || !target) continue;
    if (technique.type === "slide") {
      source.slideOutType = model.SlideOutType.Shift;
      source.slideTarget = target;
      target.slideOrigin = source;
    } else {
      source.isHammerPullOrigin = true;
      source.hammerPullDestination = target;
      target.hammerPullOrigin = source;
    }
  }
}

function applyTempoMap(
  document: ScoreDocument,
  referenceMeasures: ScoreMeasure[],
  score: AlphaScore,
): void {
  const orderedTempoChanges = [...document.tempo_map].sort((left, right) => (
    compare(rational(left.position), rational(right.position))
  ));
  for (const tempo of orderedTempoChanges) {
    if (!Number.isFinite(tempo.bpm) || tempo.bpm <= 0) {
      throw new AlphaTabAdapterError(`Tempo ${tempo.id} must use a positive finite BPM.`);
    }
    const position = rational(tempo.position);
    const measureIndex = referenceMeasures.findIndex((measure) => {
      const start = rational(measure.start);
      return compare(position, start) >= 0
        && compare(position, add(start, measureDuration(measure))) < 0;
    });
    if (measureIndex < 0) {
      throw new AlphaTabAdapterError(
        `Tempo ${tempo.id} at ${fractionKey(position)} is outside the score timeline.`,
      );
    }
    const measure = referenceMeasures[measureIndex]!;
    const duration = measureDuration(measure);
    const offset = subtract(position, rational(measure.start));
    const automation = new model.Automation();
    automation.type = model.AutomationType.Tempo;
    automation.value = tempo.bpm;
    automation.ratioPosition = toNumber(offset) / toNumber(duration);
    automation.isLinear = false;
    automation.isVisible = true;
    score.masterBars[measureIndex]!.tempoAutomations.push(automation);
  }
}

/**
 * Build an ephemeral alphaTab view from the canonical ScoreDocument.
 * AlphaTab IDs are kept only in external maps and are never persisted.
 */
export function buildAlphaTabScore(
  document: ScoreDocument,
  settings: Settings,
): AlphaTabScoreAdapterResult {
  const orderedTracks = [...document.tracks].sort((left, right) => left.order - right.order);
  if (orderedTracks.length === 0) {
    throw new AlphaTabAdapterError("The score has no tracks to render.");
  }
  const referenceMeasures = [...orderedTracks[0].measures].sort((left, right) => left.number - right.number);
  if (referenceMeasures.length === 0) {
    throw new AlphaTabAdapterError("The score has no measures to render.");
  }

  const result: AlphaTabScoreAdapterResult = {
    score: new model.Score(),
    alphaBeatIds: new Map(),
    alphaNoteIds: new Map(),
    alphaTrackIds: new Map(),
    stableBeatModels: new Map(),
    stableNoteModels: new Map(),
    warnings: [],
  };
  result.score.title = document.title;
  const techniquesById = new Map(
    document.techniques.map((technique) => [technique.id, technique]),
  );

  for (const measure of referenceMeasures) {
    const masterBar = new model.MasterBar();
    masterBar.timeSignatureNumerator = measure.numerator;
    masterBar.timeSignatureDenominator = measure.denominator;
    masterBar.isAnacrusis = !equals(measureDuration(measure), measureSignatureDuration(measure));
    result.score.addMasterBar(masterBar);
  }
  applyTempoMap(document, referenceMeasures, result.score);

  for (const track of orderedTracks) {
    const alphaTrack = new model.Track();
    alphaTrack.name = track.name;
    alphaTrack.shortName = track.name.slice(0, 8);
    alphaTrack.playbackInfo.volume = Math.round(track.mixer.volume * 16);
    alphaTrack.playbackInfo.balance = Math.round((track.mixer.pan + 1) * 8);
    alphaTrack.playbackInfo.isMute = track.mixer.mute;
    alphaTrack.playbackInfo.isSolo = track.mixer.solo;
    alphaTrack.playbackInfo.program = Number(track.instrument.program ?? 0);
    result.score.addTrack(alphaTrack);
    result.alphaTrackIds.set(alphaTrack.index, track.id);
    const measuresByNumber = new Map(track.measures.map((measure) => [measure.number, measure]));

    for (const staff of [...track.staves].sort((left, right) => left.order - right.order)) {
      const alphaStaff = new model.Staff();
      configureStaff(alphaStaff, staff, track);
      alphaTrack.addStaff(alphaStaff);
      for (const referenceMeasure of referenceMeasures) {
        const measure = measuresByNumber.get(referenceMeasure.number);
        if (measure) assertCompatibleMeasure(referenceMeasure, measure, track.id);
        const activeMeasure = measure ?? referenceMeasure;
        const bar = new model.Bar();
        configureClef(bar, staff, track);
        alphaStaff.addBar(bar);
        const staffBeats = measure
          ? measure.beats.filter((beat) => beat.staff_id === staff.id)
          : [];
        const maximumVoiceIndex = staffBeats.reduce(
          (value, beat) => Math.max(value, beat.voice - 1),
          0,
        );
        if (maximumVoiceIndex > 3) {
          throw new AlphaTabAdapterError(
            `Staff ${staff.id} uses more than four notation voices.`,
          );
        }
        for (let voiceIndex = 0; voiceIndex <= maximumVoiceIndex; voiceIndex += 1) {
          const voice = new model.Voice();
          bar.addVoice(voice);
          populateVoice(
            voice,
            staffBeats.filter((beat) => beat.voice === voiceIndex + 1),
            activeMeasure,
            track,
            result,
            techniquesById,
          );
        }
      }
    }
  }

  applyLinkedTechniques(document, result.stableNoteModels);
  result.score.finish(settings);
  return result;
}

export function alphaTrackIndexForStableId(
  result: AlphaTabScoreAdapterResult,
  trackId: string | null,
): number[] {
  if (trackId === null) return result.score.tracks.map((track) => track.index);
  for (const [index, stableId] of result.alphaTrackIds) {
    if (stableId === trackId) return [index];
  }
  throw new AlphaTabAdapterError(`Track ${trackId} is not present in the rendered score.`);
}
