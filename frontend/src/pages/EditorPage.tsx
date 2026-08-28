import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  ButtonGroup,
  CircularProgress,
  Divider,
  IconButton,
  Tooltip,
  Typography,
} from "@mui/material";
import {
  ArrowBackIcon,
  BoltIcon,
  DownloadIcon,
  GraphicEqIcon,
  MusicNoteIcon,
  PauseIcon,
  PlayArrowIcon,
  RedoIcon,
  RefreshIcon,
  RepeatIcon,
  SpeedIcon,
  StopIcon,
  TuneIcon,
  UndoIcon,
} from "../icons";
import { exportsApi, projectsApi, scoreDocumentsApi } from "../api/client";
import type {
  ProjectDetail,
  ScoreCommandRequest,
  ScoreDocumentEnvelope,
  ScoreOperation,
  ScoreRational,
  ScoreSelectionAnchor,
} from "../api/types";
import { useScoreDocumentAlphaTab } from "../hooks/useScoreDocumentAlphaTab";
import { createFirstNoteBeat, createFirstRestBeat } from "../editor/scoreFactories";
import {
  addRational,
  applyOperationsLocally,
  availableAfter,
  compareRational,
  contiguousBeatIds,
  equalRational,
  findBeat,
  findNote,
  isFretted,
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
  WRITTEN_DURATIONS,
  type BeatClipboard,
  type BeatContext,
} from "../editor/scoreEditing";
import { acknowledgeOptimisticCommand } from "../editor/commandAcknowledgement";
import { CommandPalette, type EditorCommand } from "../editor/CommandPalette";
import { stepPlaybackSpeed } from "../editor/playbackTransport";
import { stepScoreScale } from "../editor/scoreView";
import { SelectionInspector } from "../editor/SelectionInspector";
import { EditionToolbar, EditorStatusBar } from "../editor/EditorChrome";
import { TrackRail } from "../editor/TrackRail";
import {
  createEmptyTrack,
  prepareTrackSetup,
  type TrackFamily,
  type TrackSetupInput,
} from "../editor/trackEditing";
import { palette } from "../styles/tokens";
import { apiErrorMessage } from "../utils/apiError";

interface HistoryEntry {
  commandId: string;
  intent: string;
  operations: ScoreOperation[];
  selection: ScoreSelectionAnchor;
}

type SaveState = "saved" | "saving" | "conflict";

interface SaveTiming {
  apiMs: number;
  totalMs: number;
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function selectionForBeat(
  context: BeatContext,
  noteIds: string[] = context.beat.notes.map((note) => note.id),
): ScoreSelectionAnchor {
  return {
    scope: noteIds.length > 0 ? "notes" : "beats",
    track_ids: [context.track.id],
    beat_ids: [context.beat.id],
    note_ids: noteIds,
    start: context.beat.start,
    end: addRational(context.beat.start, context.beat.duration),
  };
}

function selectionForBeats(contexts: BeatContext[]): ScoreSelectionAnchor {
  const ordered = [...contexts].sort((left, right) => (
    compareRational(left.beat.start, right.beat.start) ||
    left.beat.id.localeCompare(right.beat.id)
  ));
  const first = ordered[0];
  const last = ordered[ordered.length - 1];
  return {
    scope: "beats",
    track_ids: [...new Set(ordered.map((context) => context.track.id))],
    beat_ids: ordered.map((context) => context.beat.id),
    note_ids: ordered.flatMap((context) => context.beat.notes.map((note) => note.id)),
    start: first?.beat.start ?? null,
    end: last ? addRational(last.beat.start, last.beat.duration) : null,
  };
}

function selectionForMeasureEntries(
  entries: Array<{
    track_id: string;
    measure: ScoreDocumentEnvelope["document"]["tracks"][number]["measures"][number];
  }>,
): ScoreSelectionAnchor {
  const measures = entries.map((entry) => entry.measure);
  const first = measures[0];
  return {
    scope: "measures",
    track_ids: entries.map((entry) => entry.track_id),
    measure_ids: measures.map((measure) => measure.id),
    beat_ids: measures.flatMap((measure) => measure.beats.map((beat) => beat.id)),
    note_ids: measures.flatMap((measure) => (
      measure.beats.flatMap((beat) => beat.notes.map((note) => note.id))
    )),
    start: first?.start ?? null,
    end: first ? addRational(first.start, first.duration) : null,
  };
}

function selectionForTracks(trackIds: string[]): ScoreSelectionAnchor {
  return {
    scope: "tracks",
    track_ids: trackIds,
    beat_ids: [],
    note_ids: [],
    start: null,
    end: null,
  };
}

export default function EditorPage(): JSX.Element {
  const { id } = useParams<{ id: string }>();
  const projectId = Number(id);
  const navigate = useNavigate();
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [envelope, setEnvelope] = useState<ScoreDocumentEnvelope | null>(null);
  const [activeTrackId, setActiveTrackId] = useState<string | null>(null);
  const [selectedBeatId, setSelectedBeatId] = useState<string | null>(null);
  const [selectedBeatIds, setSelectedBeatIds] = useState<string[]>([]);
  const [selectionAnchorBeatId, setSelectionAnchorBeatId] = useState<string | null>(null);
  const [selectedNoteId, setSelectedNoteId] = useState<string | null>(null);
  const [caretString, setCaretString] = useState<number | null>(1);
  const [inputDuration, setInputDuration] = useState<ScoreRational>({ numerator: 1, denominator: 1 });
  const [pitchOctave, setPitchOctave] = useState(4);
  const [fretBuffer, setFretBuffer] = useState("");
  const fretBufferRef = useRef("");
  const fretTimerRef = useRef<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [lastSaveTiming, setLastSaveTiming] = useState<SaveTiming | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [commandHistory, setCommandHistory] = useState<HistoryEntry[]>([]);
  const [redoHistory, setRedoHistory] = useState<HistoryEntry[]>([]);
  const [clipboard, setClipboard] = useState<BeatClipboard | null>(null);
  const [exporting, setExporting] = useState<string | null>(null);
  const [lastExport, setLastExport] = useState<{
    format: "GP5" | "XML" | "MIDI";
    revision: number;
  } | null>(null);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);

  const load = useCallback(async (preserveSelection = true): Promise<void> => {
    if (!Number.isInteger(projectId)) return;
    try {
      const projectValue = await projectsApi.get(projectId);
      const documentValue = projectValue.status === "repaired" || projectValue.status === "partial"
        ? await scoreDocumentsApi.promotePrepared(projectId)
        : await scoreDocumentsApi.get(projectId);
      setProject(projectValue);
      setEnvelope(documentValue);
      setActiveTrackId((current) => (
        current && documentValue.document.tracks.some((track) => track.id === current)
          ? current
          : documentValue.document.tracks[0]?.id ?? null
      ));
      if (!preserveSelection) {
        setSelectedBeatId(null);
        setSelectedBeatIds([]);
        setSelectionAnchorBeatId(null);
        setSelectedNoteId(null);
      }
      setSaveState("saved");
    } catch (caught) {
      setMessage(apiErrorMessage(caught, "The score could not be loaded."));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { void load(false); }, [load]);

  const selectedBeat = useMemo(
    () => findBeat(envelope?.document ?? null, selectedBeatId),
    [envelope, selectedBeatId],
  );
  const selectedNote = useMemo(
    () => findNote(envelope?.document ?? null, selectedNoteId),
    [envelope, selectedNoteId],
  );
  const navigableBeats = useMemo(
    () => orderedBeatContexts(envelope?.document ?? null, activeTrackId),
    [activeTrackId, envelope],
  );
  const selectedBeatContexts = useMemo(
    () => selectedBeatIds
      .map((beatId) => findBeat(envelope?.document ?? null, beatId))
      .filter((context): context is BeatContext => Boolean(context)),
    [envelope, selectedBeatIds],
  );
  const displayedDuration = selectedBeat?.beat.duration ?? inputDuration;
  const durationState = useMemo(
    () => writtenDurationState(displayedDuration),
    [displayedDuration],
  );
  const activeDynamic = useMemo(() => {
    const contexts = selectedBeatContexts.length > 0
      ? selectedBeatContexts
      : selectedBeat ? [selectedBeat] : [];
    const values = new Set(contexts.map((context) => context.beat.properties.dynamic));
    if (values.size !== 1) return null;
    const value = [...values][0];
    return typeof value === "string" ? value : null;
  }, [selectedBeat, selectedBeatContexts]);
  const tiePreview = useMemo(() => {
    try {
      return prepareTie(navigableBeats, selectedBeatIds, selectedBeatId);
    } catch {
      return null;
    }
  }, [navigableBeats, selectedBeatId, selectedBeatIds]);
  const selectedTechniqueNoteIds = useMemo(() => {
    if (selectedNote) return [selectedNote.note.id];
    const contexts = selectedBeatContexts.length > 0
      ? selectedBeatContexts
      : selectedBeat ? [selectedBeat] : [];
    return contexts.flatMap((context) => context.beat.notes.map((note) => note.id));
  }, [selectedBeat, selectedBeatContexts, selectedNote]);
  const activeTechniqueTypes = useMemo(() => {
    if (!envelope || selectedTechniqueNoteIds.length === 0) return [];
    const selectedIds = new Set(selectedTechniqueNoteIds);
    return [...new Set(
      envelope.document.techniques
        .filter((technique) => (
          technique.note_ids.length > 0 &&
          technique.note_ids.every((noteId) => selectedIds.has(noteId))
        ))
        .map((technique) => technique.type),
    )];
  }, [envelope, selectedTechniqueNoteIds]);
  const selectedNoteTechniqueLabels = useMemo(() => {
    if (!envelope || !selectedNote) return [];
    const typeById = new Map(
      envelope.document.techniques.map((technique) => [technique.id, technique.type]),
    );
    const labels: Record<string, string> = {
      palm_mute: "Palm mute",
      let_ring: "Let ring",
      staccato: "Staccato",
      accent: "Accent",
      heavy_accent: "Heavy accent",
      ghost_note: "Ghost note",
      bend: "Bend",
      harmonic: "Natural harmonic",
      vibrato: "Vibrato",
      hammer_on: "Hammer-on",
      pull_off: "Pull-off",
      slide: "Slide",
    };
    return selectedNote.note.technique_ids.map((techniqueId) => {
      const type = typeById.get(techniqueId) ?? techniqueId;
      return labels[type] ?? type.replace(/_/g, " ");
    });
  }, [envelope, selectedNote]);
  const selectBeat = useCallback((beatId: string) => {
    setSelectedBeatId(beatId);
    setSelectedBeatIds([beatId]);
    setSelectionAnchorBeatId(beatId);
    setSelectedNoteId(null);
  }, []);
  const selectNote = useCallback((noteId: string) => {
    const context = findNote(envelope?.document ?? null, noteId);
    if (context) {
      setSelectedBeatId(context.beat.id);
      setSelectedBeatIds([context.beat.id]);
      setSelectionAnchorBeatId(context.beat.id);
      if (typeof context.note.realization.string === "number") {
        setCaretString(context.note.realization.string);
      }
    }
    setSelectedNoteId(noteId);
  }, [envelope]);
  const viewer = useScoreDocumentAlphaTab({
    document: envelope?.document ?? null,
    activeTrackId,
    selectedBeatId,
    selectedBeatIds,
    selectedNoteId,
    onSelectBeat: selectBeat,
    onSelectNote: selectNote,
  });

  useEffect(() => {
    if (!envelope) return;
    if (selectedBeatId && !findBeat(envelope.document, selectedBeatId)) {
      setSelectedBeatId(null);
      setSelectedBeatIds([]);
      setSelectionAnchorBeatId(null);
      setSelectedNoteId(null);
    }
    if (selectedNoteId && !findNote(envelope.document, selectedNoteId)) {
      setSelectedNoteId(null);
    }
  }, [envelope, selectedBeatId, selectedNoteId]);

  useEffect(() => {
    const track = envelope?.document.tracks.find((candidate) => candidate.id === activeTrackId);
    const stringCount = Array.isArray(track?.instrument.tuning)
      ? track.instrument.tuning.length
      : 0;
    if (track?.family === "guitar" || track?.family === "bass") {
      setCaretString((current) => Math.min(Math.max(current ?? 1, 1), stringCount || 1));
    } else {
      setCaretString(null);
    }
  }, [activeTrackId, envelope]);

  useEffect(() => {
    if (
      selectedNote &&
      (selectedNote.track.family === "keys" || selectedNote.track.family === "generic")
    ) {
      setPitchOctave(Math.floor(selectedNote.note.pitch / 12) - 1);
    }
  }, [selectedNote]);

  const submit = useCallback(async (
    intent: string,
    operations: ScoreOperation[],
    selection: ScoreSelectionAnchor,
    clearRedo = true,
  ): Promise<boolean> => {
    if (!envelope) return false;
    const saveStartedAt = window.performance.now();
    let optimisticDocument: ScoreDocumentEnvelope["document"];
    try {
      optimisticDocument = applyOperationsLocally(envelope.document, operations);
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "The edit is not valid locally.");
      return false;
    }
    setSaveState("saving");
    setMessage(null);
    const command: ScoreCommandRequest = {
      schema_version: "1.0",
      command_id: crypto.randomUUID(),
      base_revision: envelope.revision.number,
      origin: "manual",
      intent,
      operations,
      selection,
      created_at: new Date().toISOString(),
    };
    setEnvelope({ ...envelope, document: optimisticDocument });
    try {
      const apiStartedAt = window.performance.now();
      const result = await scoreDocumentsApi.submit(projectId, command);
      const apiCompletedAt = window.performance.now();
      if (!result.idempotent_replay) {
        setCommandHistory((history) => [...history, {
          commandId: command.command_id,
          intent,
          operations,
          selection,
        }]);
        if (clearRedo) setRedoHistory([]);
      }
      const acknowledged = acknowledgeOptimisticCommand(optimisticDocument, result);
      setEnvelope(acknowledged ?? await scoreDocumentsApi.get(projectId));
      setLastSaveTiming({
        apiMs: apiCompletedAt - apiStartedAt,
        totalMs: window.performance.now() - saveStartedAt,
      });
      setSaveState("saved");
      return true;
    } catch (caught) {
      const status = (caught as { response?: { status?: number } }).response?.status;
      if (status === 409) {
        setSaveState("conflict");
        await load(true);
        setMessage("This passage changed elsewhere. The latest revision is loaded; review it before trying again.");
      } else {
        setSaveState("saved");
        await load(true);
        setMessage(apiErrorMessage(caught, "The edit could not be saved."));
      }
      return false;
    }
  }, [envelope, load, projectId]);

  const changePitch = useCallback((pitch: number): void => {
    if (!selectedNote || pitch < 0 || pitch > 127 || pitch === selectedNote.note.pitch) return;
    const operations: ScoreOperation[] = [{
      kind: "set_note_pitch",
      note_id: selectedNote.note.id,
      pitch,
      expected_pitch: selectedNote.note.pitch,
    }];
    if (isFretted(selectedNote)) {
      const currentFret = selectedNote.note.realization.fret as number;
      const nextFret = currentFret + pitch - selectedNote.note.pitch;
      const fretCount = Number(selectedNote.track.instrument.fret_count ?? 24);
      if (nextFret < 0 || nextFret > fretCount) {
        setMessage(`That pitch is outside the current string's 0–${fretCount} fret range.`);
        return;
      }
      operations.push({
        kind: "set_note_fretting",
        note_id: selectedNote.note.id,
        string: selectedNote.note.realization.string as number,
        fret: nextFret,
        expected_string: selectedNote.note.realization.string,
        expected_fret: currentFret,
      });
    }
    void submit(
      `Set ${selectedNote.note.id} to MIDI pitch ${pitch}`,
      operations,
      selectionForBeat(selectedNote, [selectedNote.note.id]),
    );
  }, [selectedNote, submit]);

  const changeString = useCallback((stringNumber: number): void => {
    if (!selectedNote || !isFretted(selectedNote)) return;
    const tuning = selectedNote.track.instrument.tuning;
    if (!Array.isArray(tuning)) return;
    const openPitch = Number(tuning[tuning.length - stringNumber]);
    const capo = Number(selectedNote.track.instrument.capo ?? 0);
    const fret = selectedNote.note.pitch - openPitch - capo;
    void submit(
      `Move ${selectedNote.note.id} to string ${stringNumber}`,
      [{
        kind: "set_note_fretting",
        note_id: selectedNote.note.id,
        string: stringNumber,
        fret,
        expected_string: selectedNote.note.realization.string,
        expected_fret: selectedNote.note.realization.fret,
      }],
      selectionForBeat(selectedNote, [selectedNote.note.id]),
    );
  }, [selectedNote, submit]);

  const addFirst = useCallback((kind: "notes" | "rest"): void => {
    if (!envelope || !activeTrackId) return;
    const track = envelope.document.tracks.find((candidate) => candidate.id === activeTrackId);
    if (!track) return;
    const noteBeat = kind === "notes" ? createFirstNoteBeat(track) : null;
    const restBeat = kind === "rest" ? createFirstRestBeat(track) : null;
    const first = noteBeat ?? restBeat;
    if (!first) return;
    first.beat.duration = inputDuration;
    if (noteBeat) {
      noteBeat.performanceEvents = noteBeat.performanceEvents.map((event) => ({
        ...event,
        duration: inputDuration,
      }));
    }
    const operation: ScoreOperation = {
      kind: "insert_beat",
      track_id: track.id,
      measure_id: first.measureId,
      beat: first.beat,
      performance_events: noteBeat?.performanceEvents ?? [],
    };
    const measure = track.measures.find((candidate) => candidate.id === first.measureId);
    if (!measure) return;
    setSelectedBeatId(first.beat.id);
    setSelectedBeatIds([first.beat.id]);
    setSelectionAnchorBeatId(first.beat.id);
    setSelectedNoteId(noteBeat?.noteId ?? null);
    void submit(
      `Add first ${track.family} ${kind === "notes" ? "note" : "rest"}`,
      [operation],
      selectionForBeat({ track, measure, beat: first.beat }),
    );
  }, [activeTrackId, envelope, inputDuration, submit]);

  const changeDuration = useCallback((duration: ScoreRational): void => {
    setInputDuration(duration);
    if (!selectedBeat || equalRational(selectedBeat.beat.duration, duration)) return;
    const maximum = addRational(selectedBeat.beat.duration, availableAfter(selectedBeat));
    if (compareRational(duration, maximum) > 0) {
      setMessage("That duration would overlap the next event in this voice.");
      return;
    }
    void submit(
      `Set ${selectedBeat.beat.id} duration`,
      [{
        kind: "set_beat_duration",
        beat_id: selectedBeat.beat.id,
        duration,
        expected_duration: selectedBeat.beat.duration,
      }],
      selectionForBeat(selectedBeat),
    );
  }, [selectedBeat, submit]);

  const changeDurationModifier = useCallback((modifier: "dot" | "triplet"): void => {
    try {
      changeDuration(toggleWrittenDurationModifier(displayedDuration, modifier));
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "That duration modifier is unavailable.");
    }
  }, [changeDuration, displayedDuration]);

  const changeVoice = useCallback((voice: number): void => {
    if (voice < 1 || voice > 4) return;
    const contexts = selectedBeatContexts.length > 0
      ? selectedBeatContexts
      : selectedBeat ? [selectedBeat] : [];
    const operations: ScoreOperation[] = contexts
      .filter((context) => context.beat.voice !== voice)
      .map((context) => ({
        kind: "set_beat_voice",
        beat_id: context.beat.id,
        voice,
        expected_voice: context.beat.voice,
      }));
    if (operations.length === 0) return;
    void submit(
      `Move ${contexts.length} selected beat${contexts.length === 1 ? "" : "s"} to voice ${voice}`,
      operations,
      selectionForBeats(contexts),
    );
  }, [selectedBeat, selectedBeatContexts, submit]);

  const changeDynamic = useCallback((label: string, velocity: number): void => {
    if (!envelope) return;
    const contexts = selectedBeatContexts.length > 0
      ? selectedBeatContexts
      : selectedBeat ? [selectedBeat] : [];
    const performanceByNote = new Map(
      envelope.document.performance.events.map((event) => [event.note_id, event]),
    );
    const operations: ScoreOperation[] = [];
    for (const context of contexts) {
      const current = context.beat.properties.dynamic;
      if (current !== label) {
        operations.push({
          kind: "set_beat_dynamic",
          beat_id: context.beat.id,
          dynamic: label,
          expected_dynamic: typeof current === "string" ? current : null,
        });
      }
      for (const note of context.beat.notes) {
        const performance = performanceByNote.get(note.id);
        if (performance && performance.velocity !== velocity) {
          operations.push({
            kind: "set_performance_velocity",
            note_id: note.id,
            velocity,
            expected_velocity: performance.velocity,
          });
        }
      }
    }
    if (operations.length === 0) return;
    void submit(
      `Set ${contexts.length} beat${contexts.length === 1 ? "" : "s"} to ${label}`,
      operations,
      selectionForBeats(contexts),
    );
  }, [envelope, selectedBeat, selectedBeatContexts, submit]);

  const selectTrack = useCallback((trackId: string): void => {
    setActiveTrackId(trackId);
    setSelectedBeatId(null);
    setSelectedBeatIds([]);
    setSelectionAnchorBeatId(null);
    setSelectedNoteId(null);
  }, []);

  const addTrack = useCallback((family: TrackFamily): void => {
    if (!envelope) return;
    try {
      const track = createEmptyTrack(envelope.document, family);
      selectTrack(track.id);
      void submit(
        `Add ${family} track`,
        [{ kind: "insert_track", track }],
        selectionForTracks([track.id]),
      );
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "The track could not be created.");
    }
  }, [envelope, selectTrack, submit]);

  const moveTrack = useCallback((trackId: string, direction: -1 | 1): void => {
    if (!envelope) return;
    const ordered = [...envelope.document.tracks].sort((left, right) => left.order - right.order);
    const index = ordered.findIndex((track) => track.id === trackId);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= ordered.length) return;
    const previousIds = ordered.map((track) => track.id);
    [ordered[index], ordered[target]] = [ordered[target]!, ordered[index]!];
    void submit(
      `Move ${ordered[target]!.name} ${direction < 0 ? "up" : "down"}`,
      [{
        kind: "reorder_tracks",
        track_ids: ordered.map((track) => track.id),
        expected_track_ids: previousIds,
      }],
      selectionForTracks(previousIds),
    );
  }, [envelope, submit]);

  const changeTrackMixer = useCallback((trackId: string, mixer: ScoreDocumentEnvelope["document"]["tracks"][number]["mixer"]): void => {
    const track = envelope?.document.tracks.find((candidate) => candidate.id === trackId);
    if (!track) return;
    if (
      track.mixer.volume === mixer.volume &&
      track.mixer.pan === mixer.pan &&
      track.mixer.mute === mixer.mute &&
      track.mixer.solo === mixer.solo
    ) return;
    void submit(
      `Update ${track.name} mixer`,
      [{ kind: "set_track_mixer", track_id: track.id, mixer, expected_mixer: track.mixer }],
      selectionForTracks([track.id]),
    );
  }, [envelope, submit]);

  const changeTrackSetup = useCallback((trackId: string, input: TrackSetupInput): boolean => {
    const track = envelope?.document.tracks.find((candidate) => candidate.id === trackId);
    if (!track) return false;
    try {
      const operations = prepareTrackSetup(track, input);
      if (operations.length === 0) return true;
      void submit(
        `Update ${track.name} setup`,
        operations,
        selectionForTracks([track.id]),
      );
      return true;
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "The track setup is not playable.");
      return false;
    }
  }, [envelope, submit]);

  const deleteEmptyTrack = useCallback((trackId: string): void => {
    if (!envelope) return;
    const ordered = [...envelope.document.tracks].sort((left, right) => left.order - right.order);
    const index = ordered.findIndex((track) => track.id === trackId);
    const fallback = ordered[index - 1] ?? ordered[index + 1];
    if (index < 0 || !fallback) return;
    selectTrack(fallback.id);
    void submit(
      `Delete empty track ${ordered[index]!.name}`,
      [{ kind: "delete_track", track_id: trackId, expected_track_hash: null }],
      selectionForTracks([trackId]),
    );
  }, [envelope, selectTrack, submit]);

  const toggleTie = useCallback((): void => {
    try {
      const prepared = prepareTie(navigableBeats, selectedBeatIds, selectedBeatId);
      const contexts = [prepared.sourceBeatId, prepared.targetBeatId]
        .map((beatId) => findBeat(envelope?.document ?? null, beatId))
        .filter((context): context is BeatContext => Boolean(context));
      void submit(
        `${prepared.active ? "Remove" : "Add"} tie`,
        prepared.operations,
        selectionForBeats(contexts),
      );
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "That tie cannot be created.");
    }
  }, [envelope, navigableBeats, selectedBeatId, selectedBeatIds, submit]);

  const insertAfter = useCallback((kind: "notes" | "rest"): void => {
    if (!selectedBeat || !envelope) return;
    try {
      const prepared = prepareBeatAfter(selectedBeat, kind, inputDuration);
      setSelectedBeatId(prepared.beatId);
      setSelectedBeatIds([prepared.beatId]);
      setSelectionAnchorBeatId(prepared.beatId);
      setSelectedNoteId(prepared.noteId);
      const inserted = findBeat(
        applyOperationsLocally(envelope.document, [prepared.operation]),
        prepared.beatId,
      );
      if (!inserted) throw new Error("The inserted beat could not be selected.");
      void submit(
        `Insert ${kind === "notes" ? "note" : "rest"} after ${selectedBeat.beat.id}`,
        [prepared.operation],
        selectionForBeat(inserted),
      );
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "The beat could not be inserted.");
    }
  }, [envelope, inputDuration, selectedBeat, submit]);

  const copyBeat = useCallback((): void => {
    if (!envelope || !selectedBeat) return;
    setClipboard(makeBeatClipboard(envelope.document, selectedBeat));
    setMessage(null);
  }, [envelope, selectedBeat]);

  const pasteAfter = useCallback((): void => {
    if (!envelope || !selectedBeat || !clipboard) return;
    try {
      const prepared = prepareClipboardAfter(selectedBeat, clipboard);
      const optimistic = applyOperationsLocally(envelope.document, [prepared.operation]);
      const inserted = findBeat(optimistic, prepared.beatId);
      if (!inserted) throw new Error("The pasted beat could not be selected.");
      setSelectedBeatId(prepared.beatId);
      setSelectedBeatIds([prepared.beatId]);
      setSelectionAnchorBeatId(prepared.beatId);
      setSelectedNoteId(prepared.noteId);
      void submit(
        `Paste beat after ${selectedBeat.beat.id}`,
        [prepared.operation],
        selectionForBeat(inserted),
      );
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "The beat could not be pasted.");
    }
  }, [clipboard, envelope, selectedBeat, submit]);

  const insertMeasureAfter = useCallback((mode: "empty" | "duplicate"): void => {
    if (!envelope || !activeTrackId || !selectedBeat) return;
    const previousBeatId = selectedBeatId;
    const previousBeatIds = selectedBeatIds;
    const previousAnchor = selectionAnchorBeatId;
    const previousNoteId = selectedNoteId;
    try {
      const prepared = prepareMeasureAfter(
        envelope.document,
        selectedBeat.measure.number,
        activeTrackId,
        mode,
      );
      setSelectedBeatId(prepared.selectedBeatId);
      setSelectedBeatIds(prepared.selectedBeatId ? [prepared.selectedBeatId] : []);
      setSelectionAnchorBeatId(prepared.selectedBeatId);
      setSelectedNoteId(prepared.selectedNoteId);
      void submit(
        `${mode === "duplicate" ? "Duplicate" : "Insert"} bar ${selectedBeat.measure.number}`,
        [prepared.operation],
        selectionForMeasureEntries(prepared.operation.entries),
      ).then((success) => {
        if (success) return;
        setSelectedBeatId(previousBeatId);
        setSelectedBeatIds(previousBeatIds);
        setSelectionAnchorBeatId(previousAnchor);
        setSelectedNoteId(previousNoteId);
      });
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "The bar could not be inserted.");
    }
  }, [
    activeTrackId,
    envelope,
    selectedBeat,
    selectedBeatId,
    selectedBeatIds,
    selectedNoteId,
    selectionAnchorBeatId,
    submit,
  ]);

  const enterDrumPiece = useCallback((piece: string): void => {
    if (!envelope || !activeTrackId) return;
    const track = envelope.document.tracks.find((candidate) => candidate.id === activeTrackId);
    if (!track || track.family !== "drums") return;
    const context = selectedBeat?.track.id === track.id ? selectedBeat : null;
    try {
      const prepared = prepareDrumInput(track, context, piece, inputDuration);
      setSelectedBeatId(prepared.beatId);
      setSelectedBeatIds([prepared.beatId]);
      setSelectionAnchorBeatId(prepared.beatId);
      setSelectedNoteId(prepared.noteId);
      if (prepared.operations.length === 0) return;
      const optimistic = applyOperationsLocally(envelope.document, prepared.operations);
      const inserted = findBeat(optimistic, prepared.beatId);
      if (!inserted) throw new Error("The drum hit could not be selected.");
      void submit(
        `Enter ${piece.replace(/_/g, " ")}`,
        prepared.operations,
        selectionForBeat(inserted, [prepared.noteId]),
      );
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "The drum hit could not be entered.");
    }
  }, [activeTrackId, envelope, inputDuration, selectedBeat, submit]);

  const enterPitchedNote = useCallback((pitchClass: number): void => {
    if (!envelope || !activeTrackId) return;
    const track = envelope.document.tracks.find((candidate) => candidate.id === activeTrackId);
    if (!track || (track.family !== "keys" && track.family !== "generic")) return;
    const pitch = (pitchOctave + 1) * 12 + pitchClass;
    const context = selectedBeat?.track.id === track.id ? selectedBeat : null;
    const noteId = selectedNote?.track.id === track.id ? selectedNote.note.id : null;
    try {
      const prepared = preparePitchedInput(
        track,
        context,
        noteId,
        pitch,
        inputDuration,
      );
      setSelectedBeatId(prepared.beatId);
      setSelectedBeatIds([prepared.beatId]);
      setSelectionAnchorBeatId(prepared.beatId);
      setSelectedNoteId(prepared.noteId);
      if (prepared.operations.length === 0) return;
      const optimistic = applyOperationsLocally(envelope.document, prepared.operations);
      const inserted = findBeat(optimistic, prepared.beatId);
      if (!inserted) throw new Error("The pitched note could not be selected.");
      void submit(
        `Enter MIDI pitch ${pitch}`,
        prepared.operations,
        selectionForBeat(inserted, [prepared.noteId]),
      );
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "The note could not be entered.");
    }
  }, [
    activeTrackId,
    envelope,
    inputDuration,
    pitchOctave,
    selectedBeat,
    selectedNote,
    submit,
  ]);

  const deleteMeasure = useCallback((): void => {
    if (!envelope || !activeTrackId || !selectedBeat) return;
    const previousBeatId = selectedBeatId;
    const previousBeatIds = selectedBeatIds;
    const previousAnchor = selectionAnchorBeatId;
    const previousNoteId = selectedNoteId;
    try {
      const prepared = prepareMeasureDelete(
        envelope.document,
        selectedBeat.measure.number,
        activeTrackId,
      );
      const entries = envelope.document.tracks.map((track) => ({
        track_id: track.id,
        measure: track.measures.find(
          (measure) => measure.number === selectedBeat.measure.number,
        ),
      }));
      if (entries.some((entry) => !entry.measure)) {
        throw new Error("The selected bar is not aligned across every track.");
      }
      setSelectedBeatId(prepared.fallbackBeatId);
      setSelectedBeatIds(prepared.fallbackBeatId ? [prepared.fallbackBeatId] : []);
      setSelectionAnchorBeatId(prepared.fallbackBeatId);
      setSelectedNoteId(prepared.fallbackNoteId);
      void submit(
        `Delete bar ${selectedBeat.measure.number}`,
        [prepared.operation],
        selectionForMeasureEntries(entries as Array<{
          track_id: string;
          measure: NonNullable<(typeof entries)[number]["measure"]>;
        }>),
      ).then((success) => {
        if (success) return;
        setSelectedBeatId(previousBeatId);
        setSelectedBeatIds(previousBeatIds);
        setSelectionAnchorBeatId(previousAnchor);
        setSelectedNoteId(previousNoteId);
      });
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "The bar could not be deleted.");
    }
  }, [
    activeTrackId,
    envelope,
    selectedBeat,
    selectedBeatId,
    selectedBeatIds,
    selectedNoteId,
    selectionAnchorBeatId,
    submit,
  ]);

  const selectCaretString = useCallback((stringNumber: number): void => {
    setCaretString(stringNumber);
    if (!selectedBeat) return;
    const note = selectedBeat.beat.notes.find(
      (candidate) => candidate.realization.string === stringNumber,
    );
    setSelectedNoteId(note?.id ?? null);
  }, [selectedBeat]);

  const navigateCaret = useCallback((direction: -1 | 1, extend: boolean): void => {
    if (navigableBeats.length === 0) return;
    const currentIndex = selectedBeatId
      ? navigableBeats.findIndex((context) => context.beat.id === selectedBeatId)
      : -1;
    const targetIndex = currentIndex < 0
      ? direction > 0 ? 0 : navigableBeats.length - 1
      : Math.min(Math.max(currentIndex + direction, 0), navigableBeats.length - 1);
    const target = navigableBeats[targetIndex];
    if (!target) return;
    setSelectedBeatId(target.beat.id);
    if (extend) {
      const anchor = selectionAnchorBeatId ?? selectedBeatId ?? target.beat.id;
      setSelectionAnchorBeatId(anchor);
      setSelectedBeatIds(contiguousBeatIds(navigableBeats, anchor, target.beat.id));
      setSelectedNoteId(null);
      return;
    }
    setSelectionAnchorBeatId(target.beat.id);
    setSelectedBeatIds([target.beat.id]);
    const caretNote = caretString === null
      ? target.beat.notes[0]
      : target.beat.notes.find((note) => note.realization.string === caretString);
    setSelectedNoteId(caretNote?.id ?? null);
  }, [caretString, navigableBeats, selectedBeatId, selectionAnchorBeatId]);

  const deleteSelectedNote = useCallback(async (): Promise<void> => {
    if (!selectedNote) return;
    const previousNoteId = selectedNote.note.id;
    setSelectedNoteId(null);
    const success = await submit(
      `Delete note ${selectedNote.note.id}`,
      [{
        kind: "delete_note",
        beat_id: selectedNote.beat.id,
        note_id: selectedNote.note.id,
        expected_note_hash: null,
      }],
      selectionForBeat(selectedNote, [selectedNote.note.id]),
    );
    if (!success) setSelectedNoteId(previousNoteId);
  }, [selectedNote, submit]);

  const makeSelectionRest = useCallback(async (): Promise<void> => {
    const contexts = selectedBeatContexts.length > 0
      ? selectedBeatContexts
      : selectedBeat ? [selectedBeat] : [];
    const operations: ScoreOperation[] = contexts.flatMap((context) => (
      context.beat.notes.map((note) => ({
        kind: "delete_note" as const,
        beat_id: context.beat.id,
        note_id: note.id,
        expected_note_hash: null,
      }))
    ));
    if (operations.length === 0) return;
    const previousNoteId = selectedNoteId;
    setSelectedNoteId(null);
    const success = await submit(
      `Convert ${contexts.length} selected beat${contexts.length === 1 ? "" : "s"} to rest`,
      operations,
      selectionForBeats(contexts),
    );
    if (!success) setSelectedNoteId(previousNoteId);
  }, [selectedBeat, selectedBeatContexts, selectedNoteId, submit]);

  const toggleTechnique = useCallback((type: string): void => {
    if (!envelope || selectedTechniqueNoteIds.length === 0) return;
    const linked = type === "hammer_on" || type === "pull_off" || type === "slide";
    const selectedIds = new Set(selectedTechniqueNoteIds);
    const orderedNoteIds = navigableBeats.flatMap((context) => (
      context.beat.notes
        .filter((note) => selectedIds.has(note.id))
        .map((note) => note.id)
    ));
    const targetNoteIds = linked ? orderedNoteIds : selectedTechniqueNoteIds;
    if (linked) {
      if (targetNoteIds.length !== 2) {
        setMessage(`${type.replace(/_/g, " ")} requires exactly two selected notes.`);
        return;
      }
      const source = findNote(envelope.document, targetNoteIds[0]!);
      const target = findNote(envelope.document, targetNoteIds[1]!);
      if (
        !source || !target ||
        source.track.id !== target.track.id ||
        !isFretted(source) ||
        source.note.realization.string === null ||
        source.note.realization.string !== target.note.realization.string
      ) {
        setMessage("Hammer-ons, pull-offs and slides must connect two notes on the same fretted string.");
        return;
      }
      const sourceFret = source.note.realization.fret;
      const targetFret = target.note.realization.fret;
      if (type === "hammer_on" && (sourceFret === null || targetFret === null || targetFret <= sourceFret)) {
        setMessage("A hammer-on must move to a higher fret on the same string.");
        return;
      }
      if (type === "pull_off" && (sourceFret === null || targetFret === null || targetFret >= sourceFret)) {
        setMessage("A pull-off must move to a lower fret on the same string.");
        return;
      }
    }
    const existing = envelope.document.techniques.filter((technique) => (
      technique.type === type &&
      technique.note_ids.length > 0 &&
      technique.note_ids.every((noteId) => selectedIds.has(noteId)) &&
      (!linked || (
        technique.note_ids.length === targetNoteIds.length &&
        technique.note_ids.every((noteId, index) => noteId === targetNoteIds[index])
      ))
    ));
    const operations: ScoreOperation[] = existing.length > 0
      ? existing.map((technique) => ({
          kind: "delete_technique",
          technique_id: technique.id,
          expected_technique_hash: null,
        }))
      : [{
          kind: "add_technique",
          technique: {
            id: `technique:${crypto.randomUUID()}`,
            type,
            note_ids: targetNoteIds,
            confidence: 1,
            reason: "manual editor command",
            parameters: type === "bend"
              ? { semitones: 1 }
              : type === "vibrato" ? { width: 1 } : {},
          },
        }];
    const contexts = selectedBeatContexts.length > 0
      ? selectedBeatContexts
      : selectedBeat ? [selectedBeat] : [];
    void submit(
      `${existing.length > 0 ? "Remove" : "Add"} ${type.replace(/_/g, " ")}`,
      operations,
      selectionForBeats(contexts),
    );
  }, [envelope, navigableBeats, selectedBeat, selectedBeatContexts, selectedTechniqueNoteIds, submit]);

  const transposeSelection = useCallback((semitones: number): void => {
    const contexts = selectedBeatContexts.length > 0
      ? selectedBeatContexts
      : selectedBeat ? [selectedBeat] : [];
    if (contexts.some((context) => context.track.family === "drums")) {
      setMessage("Drum kit pieces are changed from the kit palette, not transposed.");
      return;
    }
    const selectedIds = new Set(selectedTechniqueNoteIds);
    const operations: ScoreOperation[] = [];
    for (const context of contexts) {
      for (const note of context.beat.notes) {
        if (!selectedIds.has(note.id)) continue;
        const pitch = note.pitch + semitones;
        if (pitch < 0 || pitch > 127) {
          setMessage("That transposition exceeds the supported MIDI pitch range.");
          return;
        }
        operations.push({
          kind: "set_note_pitch",
          note_id: note.id,
          pitch,
          expected_pitch: note.pitch,
        });
        if (
          (context.track.family === "guitar" || context.track.family === "bass") &&
          note.realization.string !== null &&
          note.realization.fret !== null
        ) {
          const fret = note.realization.fret + semitones;
          const fretCount = Number(context.track.instrument.fret_count ?? 24);
          if (fret < 0 || fret > fretCount) {
            setMessage(
              `Transposition would exceed the current string's 0–${fretCount} fret range.`,
            );
            return;
          }
          operations.push({
            kind: "set_note_fretting",
            note_id: note.id,
            string: note.realization.string,
            fret,
            expected_string: note.realization.string,
            expected_fret: note.realization.fret,
          });
        }
      }
    }
    if (operations.length === 0) return;
    void submit(
      `Transpose selection ${semitones > 0 ? "+" : ""}${semitones} semitones`,
      operations,
      selectionForBeats(contexts),
    );
  }, [selectedBeat, selectedBeatContexts, selectedTechniqueNoteIds, submit]);

  const commitFretInput = useCallback((fret: number): void => {
    if (!envelope || !activeTrackId || caretString === null) return;
    const track = envelope.document.tracks.find((candidate) => candidate.id === activeTrackId);
    if (!track || (track.family !== "guitar" && track.family !== "bass")) return;
    let context = selectedBeat;
    if (!context && navigableBeats.length > 0) context = navigableBeats[0] ?? null;
    if (!context) {
      const created = createFirstNoteBeat(track);
      const note = created.beat.notes[0];
      const tuning = Array.isArray(track.instrument.tuning) ? track.instrument.tuning : [];
      const openPitch = Number(tuning[tuning.length - caretString]);
      const capo = Number(track.instrument.capo ?? 0);
      const fretCount = Number(track.instrument.fret_count ?? 24);
      if (!note || !Number.isFinite(openPitch) || fret < 0 || fret > fretCount) {
        setMessage(`Fret must be between 0 and ${fretCount}.`);
        return;
      }
      note.pitch = openPitch + capo + fret;
      note.realization.string = caretString;
      note.realization.fret = fret;
      created.beat.duration = inputDuration;
      created.performanceEvents = created.performanceEvents.map((event) => ({
        ...event,
        duration: inputDuration,
      }));
      const measure = track.measures.find((candidate) => candidate.id === created.measureId);
      if (!measure) return;
      setSelectedBeatId(created.beat.id);
      setSelectedBeatIds([created.beat.id]);
      setSelectionAnchorBeatId(created.beat.id);
      setSelectedNoteId(note.id);
      void submit(
        `Enter fret ${fret} on string ${caretString}`,
        [{
          kind: "insert_beat",
          track_id: track.id,
          measure_id: created.measureId,
          beat: created.beat,
          performance_events: created.performanceEvents,
        }],
        selectionForBeat({ track, measure, beat: created.beat }, [note.id]),
      );
      return;
    }
    try {
      const prepared = prepareFretInput(context, caretString, fret);
      setSelectedBeatId(context.beat.id);
      setSelectedBeatIds([context.beat.id]);
      setSelectionAnchorBeatId(context.beat.id);
      setSelectedNoteId(prepared.noteId);
      if (prepared.operations.length > 0) {
        void submit(
          `Enter fret ${fret} on string ${caretString}`,
          prepared.operations,
          selectionForBeat(context, [prepared.noteId]),
        );
      }
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "The fret could not be entered.");
    }
  }, [activeTrackId, caretString, envelope, inputDuration, navigableBeats, selectedBeat, submit]);

  const clearFretBuffer = useCallback((): void => {
    if (fretTimerRef.current !== null) window.clearTimeout(fretTimerRef.current);
    fretTimerRef.current = null;
    fretBufferRef.current = "";
    setFretBuffer("");
  }, []);

  const queueFretDigit = useCallback((digit: string): void => {
    const track = envelope?.document.tracks.find((candidate) => candidate.id === activeTrackId);
    if (!track || (track.family !== "guitar" && track.family !== "bass")) return;
    const next = `${fretBufferRef.current}${digit}`.replace(/^0+(?=\d)/, "");
    const value = Number(next);
    const fretCount = Number(track.instrument.fret_count ?? 24);
    if (!Number.isInteger(value) || value > fretCount) {
      clearFretBuffer();
      setMessage(`Fret must be between 0 and ${fretCount}.`);
      return;
    }
    if (fretTimerRef.current !== null) window.clearTimeout(fretTimerRef.current);
    fretBufferRef.current = next;
    setFretBuffer(next);
    fretTimerRef.current = window.setTimeout(() => {
      const committed = Number(fretBufferRef.current);
      clearFretBuffer();
      commitFretInput(committed);
    }, 420);
  }, [activeTrackId, clearFretBuffer, commitFretInput, envelope]);

  useEffect(() => () => clearFretBuffer(), [clearFretBuffer]);

  const removeSelectedBeat = useCallback(async (intent: string): Promise<boolean> => {
    if (!selectedBeat) return false;
    const previousBeatId = selectedBeat.beat.id;
    const previousNoteId = selectedNoteId;
    setSelectedBeatId(null);
    setSelectedBeatIds([]);
    setSelectionAnchorBeatId(null);
    setSelectedNoteId(null);
    const success = await submit(
      intent,
      [{
        kind: "delete_beat",
        beat_id: selectedBeat.beat.id,
        note_ids: selectedBeat.beat.notes.map((note) => note.id),
        expected_beat_hash: null,
      }],
      selectionForBeat(selectedBeat),
    );
    if (!success) {
      setSelectedBeatId(previousBeatId);
      setSelectedBeatIds([previousBeatId]);
      setSelectionAnchorBeatId(previousBeatId);
      setSelectedNoteId(previousNoteId);
    }
    return success;
  }, [selectedBeat, selectedNoteId, submit]);

  const deleteBeat = useCallback(async (): Promise<void> => {
    if (!selectedBeat) return;
    await removeSelectedBeat(`Delete ${selectedBeat.beat.id}`);
  }, [removeSelectedBeat, selectedBeat]);

  const cutBeat = useCallback(async (): Promise<void> => {
    if (!envelope || !selectedBeat) return;
    setClipboard(makeBeatClipboard(envelope.document, selectedBeat));
    setMessage(null);
    await removeSelectedBeat(`Cut beat ${selectedBeat.beat.id}`);
  }, [envelope, removeSelectedBeat, selectedBeat]);

  const deleteSelection = useCallback(async (): Promise<void> => {
    if (selectedNote) {
      await deleteSelectedNote();
    } else {
      await deleteBeat();
    }
  }, [deleteBeat, deleteSelectedNote, selectedNote]);

  const undo = useCallback(async (): Promise<void> => {
    const target = commandHistory[commandHistory.length - 1];
    if (!target) return;
    setSaveState("saving");
    setMessage(null);
    try {
      await scoreDocumentsApi.undo(projectId, target.commandId, crypto.randomUUID(), new Date().toISOString());
      setCommandHistory((history) => history.slice(0, -1));
      setRedoHistory((history) => [...history, target]);
      setEnvelope(await scoreDocumentsApi.get(projectId));
      setSaveState("saved");
    } catch (caught) {
      setSaveState("saved");
      setMessage(apiErrorMessage(caught, "The last edit could not be undone."));
    }
  }, [commandHistory, projectId]);

  const redo = useCallback(async (): Promise<void> => {
    const target = redoHistory[redoHistory.length - 1];
    if (!target) return;
    const success = await submit(target.intent, target.operations, target.selection, false);
    if (success) setRedoHistory((history) => history.slice(0, -1));
  }, [redoHistory, submit]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent): void => {
      const commandKey = event.metaKey || event.ctrlKey;
      const key = event.key.toLowerCase();
      if (commandKey && key === "k") {
        event.preventDefault();
        setCommandPaletteOpen(true);
        return;
      }
      const target = event.target as HTMLElement | null;
      if (
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.isContentEditable
      ) return;
      const canMutate = saveState !== "saving";
      if (commandKey && (event.key === "+" || event.key === "=") && !viewer.isLoading) {
        event.preventDefault();
        viewer.setScoreScale(stepScoreScale(viewer.scoreScale, 1));
      } else if (commandKey && (event.key === "-" || event.key === "_") && !viewer.isLoading) {
        event.preventDefault();
        viewer.setScoreScale(stepScoreScale(viewer.scoreScale, -1));
      } else if (commandKey && event.key === "0" && !viewer.isLoading) {
        event.preventDefault();
        viewer.setScoreScale(1);
      } else if (event.code === "Space" && viewer.playerReady) {
        event.preventDefault();
        viewer.togglePlayback();
      } else if (event.key === "Escape" && viewer.playerReady) {
        event.preventDefault();
        viewer.stopPlayback();
      } else if (!commandKey && event.shiftKey && key === "m" && viewer.playerReady) {
        event.preventDefault();
        viewer.toggleCountIn();
      } else if (!commandKey && key === "m" && viewer.playerReady) {
        event.preventDefault();
        viewer.toggleMetronome();
      } else if (!commandKey && key === "l" && viewer.playerReady && viewer.canLoopSelection) {
        event.preventDefault();
        viewer.toggleLoopSelection();
      } else if (commandKey && key === "z" && event.shiftKey && redoHistory.length > 0 && canMutate) {
        event.preventDefault();
        void redo();
      } else if (commandKey && key === "z" && commandHistory.length > 0 && canMutate) {
        event.preventDefault();
        void undo();
      } else if (commandKey && key === "y" && redoHistory.length > 0 && canMutate) {
        event.preventDefault();
        void redo();
      } else if (commandKey && event.shiftKey && event.key === "Enter" && selectedBeat && canMutate) {
        event.preventDefault();
        insertMeasureAfter("empty");
      } else if (commandKey && key === "d" && selectedBeat && canMutate) {
        event.preventDefault();
        insertMeasureAfter("duplicate");
      } else if (
        commandKey &&
        (event.key === "Backspace" || event.key === "Delete") &&
        selectedBeat &&
        canMutate
      ) {
        event.preventDefault();
        deleteMeasure();
      } else if (commandKey && key === "a" && navigableBeats.length > 0) {
        event.preventDefault();
        setSelectedBeatId(navigableBeats[navigableBeats.length - 1]!.beat.id);
        setSelectedBeatIds(navigableBeats.map((context) => context.beat.id));
        setSelectionAnchorBeatId(navigableBeats[0]!.beat.id);
        setSelectedNoteId(null);
      } else if (commandKey && /^[1-4]$/.test(event.key) && selectedBeat && canMutate) {
        event.preventDefault();
        changeVoice(Number(event.key));
      } else if (commandKey && key === "c" && selectedBeat) {
        event.preventDefault();
        copyBeat();
      } else if (commandKey && key === "x" && selectedBeat && canMutate) {
        event.preventDefault();
        void cutBeat();
      } else if (commandKey && key === "v" && selectedBeat && clipboard && canMutate) {
        event.preventDefault();
        pasteAfter();
      } else if ((event.key === "Delete" || event.key === "Backspace") && fretBufferRef.current) {
        event.preventDefault();
        clearFretBuffer();
      } else if ((event.key === "Delete" || event.key === "Backspace") && selectedBeat && canMutate) {
        event.preventDefault();
        void deleteSelection();
      } else if (event.altKey && event.shiftKey && event.key === "ArrowUp" && canMutate) {
        event.preventDefault();
        transposeSelection(1);
      } else if (event.altKey && event.shiftKey && event.key === "ArrowDown" && canMutate) {
        event.preventDefault();
        transposeSelection(-1);
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        navigateCaret(-1, event.shiftKey);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        navigateCaret(1, event.shiftKey);
      } else if (event.key === "Home" && navigableBeats.length > 0) {
        event.preventDefault();
        const targetBeat = navigableBeats[0]!.beat.id;
        setSelectedBeatId(targetBeat);
        setSelectedBeatIds([targetBeat]);
        setSelectionAnchorBeatId(targetBeat);
        setSelectedNoteId(null);
      } else if (event.key === "End" && navigableBeats.length > 0) {
        event.preventDefault();
        const targetBeat = navigableBeats[navigableBeats.length - 1]!.beat.id;
        setSelectedBeatId(targetBeat);
        setSelectedBeatIds([targetBeat]);
        setSelectionAnchorBeatId(targetBeat);
        setSelectedNoteId(null);
      } else if (event.key === "ArrowUp" || event.key === "ArrowDown") {
        const track = envelope?.document.tracks.find((candidate) => candidate.id === activeTrackId);
        const stringCount = Array.isArray(track?.instrument.tuning) ? track.instrument.tuning.length : 0;
        if ((track?.family === "guitar" || track?.family === "bass") && stringCount > 0) {
          event.preventDefault();
          const current = caretString ?? 1;
          const next = event.key === "ArrowUp"
            ? Math.max(1, current - 1)
            : Math.min(stringCount, current + 1);
          selectCaretString(next);
        }
      } else if (event.key === "Tab") {
        const tracks = envelope?.document.tracks ?? [];
        if (tracks.length > 1) {
          event.preventDefault();
          const current = tracks.findIndex((track) => track.id === activeTrackId);
          const offset = event.shiftKey ? -1 : 1;
          const next = (current + offset + tracks.length) % tracks.length;
          setActiveTrackId(tracks[next]?.id ?? activeTrackId);
          setSelectedBeatId(null);
          setSelectedBeatIds([]);
          setSelectionAnchorBeatId(null);
          setSelectedNoteId(null);
        }
      } else if (/^\d$/.test(event.key) && !commandKey && canMutate) {
        event.preventDefault();
        queueFretDigit(event.key);
      } else if (event.key === "Enter" && fretBufferRef.current && canMutate) {
        event.preventDefault();
        const fret = Number(fretBufferRef.current);
        clearFretBuffer();
        commitFretInput(fret);
      } else if ((event.key === "+" || event.key === "=") && canMutate) {
        event.preventDefault();
        const current = WRITTEN_DURATIONS.findIndex((item) => equalRational(item.value, inputDuration));
        const next = WRITTEN_DURATIONS[Math.min(current < 0 ? 3 : current + 1, WRITTEN_DURATIONS.length - 1)];
        if (next) changeDuration(next.value);
      } else if ((event.key === "-" || event.key === "_") && canMutate) {
        event.preventDefault();
        const current = WRITTEN_DURATIONS.findIndex((item) => equalRational(item.value, inputDuration));
        const next = WRITTEN_DURATIONS[Math.max(current < 0 ? 2 : current - 1, 0)];
        if (next) changeDuration(next.value);
      } else if (event.key === "." && canMutate) {
        event.preventDefault();
        changeDurationModifier("dot");
      } else if (event.key === "/" && canMutate) {
        event.preventDefault();
        changeDurationModifier("triplet");
      } else if (key === "t" && tiePreview && canMutate) {
        event.preventDefault();
        toggleTie();
      } else if (key === "i" && selectedTechniqueNoteIds.length > 0 && canMutate) {
        event.preventDefault();
        toggleTechnique("let_ring");
      } else if (key === "p" && selectedTechniqueNoteIds.length > 0 && canMutate) {
        event.preventDefault();
        toggleTechnique("palm_mute");
      } else if (key === "o" && selectedTechniqueNoteIds.length > 0 && canMutate) {
        event.preventDefault();
        toggleTechnique("ghost_note");
      } else if (event.key === ";" && selectedTechniqueNoteIds.length > 0 && canMutate) {
        event.preventDefault();
        toggleTechnique("accent");
      } else if (key === "r" && selectedBeat && canMutate) {
        event.preventDefault();
        void makeSelectionRest();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    activeTrackId,
    caretString,
    changePitch,
    changeDuration,
    changeDurationModifier,
    changeVoice,
    clearFretBuffer,
    clipboard,
    commitFretInput,
    commandHistory.length,
    copyBeat,
    cutBeat,
    deleteMeasure,
    deleteSelection,
    envelope,
    inputDuration,
    insertMeasureAfter,
    makeSelectionRest,
    navigateCaret,
    navigableBeats,
    pasteAfter,
    queueFretDigit,
    redo,
    redoHistory.length,
    saveState,
    selectedBeat,
    selectedTechniqueNoteIds.length,
    selectCaretString,
    toggleTechnique,
    tiePreview,
    toggleTie,
    transposeSelection,
    undo,
    viewer.canLoopSelection,
    viewer.isLoading,
    viewer.playerReady,
    viewer.scoreScale,
    viewer.setScoreScale,
    viewer.stopPlayback,
    viewer.toggleCountIn,
    viewer.toggleLoopSelection,
    viewer.toggleMetronome,
    viewer.togglePlayback,
  ]);

  const exportCurrent = useCallback(async (format: "gp5" | "musicxml" | "humanized_midi"): Promise<void> => {
    if (!envelope) return;
    const revision = envelope.revision.number;
    setExporting(format);
    setMessage(null);
    try {
      const result = await exportsApi.exportAndDownload(
        projectId,
        format,
        revision,
      );
      downloadBlob(result.blob, result.filename);
      setLastExport({
        format: format === "gp5" ? "GP5" : format === "musicxml" ? "XML" : "MIDI",
        revision,
      });
    } catch (caught) {
      setMessage(apiErrorMessage(caught, "This revision could not be exported."));
    } finally {
      setExporting(null);
    }
  }, [envelope, projectId]);

  const editorCommands = useMemo<EditorCommand[]>(() => {
    const canMutate = saveState !== "saving";
    const hasBeatSelection = Boolean(selectedBeat);
    const selectBoundaryBeat = (position: "start" | "end"): void => {
      const context = position === "start"
        ? navigableBeats[0]
        : navigableBeats[navigableBeats.length - 1];
      if (!context) return;
      setSelectedBeatId(context.beat.id);
      setSelectedBeatIds([context.beat.id]);
      setSelectionAnchorBeatId(context.beat.id);
      setSelectedNoteId(null);
    };
    const measureCommands: EditorCommand[] = [];
    const seenMeasureIds = new Set<string>();
    for (const context of navigableBeats) {
      if (seenMeasureIds.has(context.measure.id)) continue;
      seenMeasureIds.add(context.measure.id);
      measureCommands.push({
        id: `go-to-measure:${context.measure.id}`,
        label: `Go to bar ${context.measure.number}`,
        group: "Navigate",
        description: `${context.track.name} · first editable beat`,
        keywords: [`measure ${context.measure.number}`],
        hiddenUntilSearch: true,
        run: () => {
          setSelectedBeatId(context.beat.id);
          setSelectedBeatIds([context.beat.id]);
          setSelectionAnchorBeatId(context.beat.id);
          setSelectedNoteId(null);
        },
      });
    }
    return [
      {
        id: "undo",
        label: "Undo last edit",
        group: "Edit",
        shortcut: "⌘Z",
        disabled: !canMutate || commandHistory.length === 0,
        run: () => { void undo(); },
      },
      {
        id: "redo",
        label: "Redo last edit",
        group: "Edit",
        shortcut: "⇧⌘Z",
        disabled: !canMutate || redoHistory.length === 0,
        run: () => { void redo(); },
      },
      {
        id: "copy-beat",
        label: "Copy selected beat",
        group: "Edit",
        shortcut: "⌘C",
        disabled: !hasBeatSelection,
        run: copyBeat,
      },
      {
        id: "cut-beat",
        label: "Cut selected beat",
        group: "Edit",
        shortcut: "⌘X",
        disabled: !canMutate || !hasBeatSelection,
        run: () => { void cutBeat(); },
      },
      {
        id: "paste-beat",
        label: "Paste beat after selection",
        group: "Edit",
        shortcut: "⌘V",
        disabled: !canMutate || !hasBeatSelection || !clipboard,
        run: pasteAfter,
      },
      {
        id: "make-rest",
        label: "Make selection a rest",
        group: "Edit",
        shortcut: "R",
        disabled: !canMutate || !hasBeatSelection,
        run: () => { void makeSelectionRest(); },
      },
      {
        id: "delete-selection",
        label: "Delete selected note or beat",
        group: "Edit",
        shortcut: "Delete",
        disabled: !canMutate || !hasBeatSelection,
        run: () => { void deleteSelection(); },
      },
      {
        id: "insert-bar",
        label: "Add bar after selection",
        group: "Edit",
        shortcut: "⇧⌘Enter",
        disabled: !canMutate || !hasBeatSelection,
        run: () => insertMeasureAfter("empty"),
      },
      {
        id: "duplicate-bar",
        label: "Duplicate selected bar",
        group: "Edit",
        shortcut: "⌘D",
        disabled: !canMutate || !hasBeatSelection,
        run: () => insertMeasureAfter("duplicate"),
      },
      {
        id: "score-start",
        label: "Go to start of active track",
        group: "Navigate",
        shortcut: "Home",
        keywords: ["first beat", "beginning"],
        disabled: navigableBeats.length === 0,
        run: () => selectBoundaryBeat("start"),
      },
      {
        id: "score-end",
        label: "Go to end of active track",
        group: "Navigate",
        shortcut: "End",
        keywords: ["last beat"],
        disabled: navigableBeats.length === 0,
        run: () => selectBoundaryBeat("end"),
      },
      {
        id: "select-track",
        label: "Select every beat in active track",
        group: "Navigate",
        shortcut: "⌘A",
        disabled: navigableBeats.length === 0,
        run: () => {
          const first = navigableBeats[0];
          const last = navigableBeats[navigableBeats.length - 1];
          if (!first || !last) return;
          setSelectedBeatId(last.beat.id);
          setSelectedBeatIds(navigableBeats.map((context) => context.beat.id));
          setSelectionAnchorBeatId(first.beat.id);
          setSelectedNoteId(null);
        },
      },
      ...measureCommands,
      {
        id: "zoom-out",
        label: "Zoom notation out",
        group: "Navigate",
        shortcut: "⌘−",
        keywords: ["score scale", "smaller"],
        disabled: viewer.isLoading || viewer.scoreScale <= 0.75,
        run: () => viewer.setScoreScale(stepScoreScale(viewer.scoreScale, -1)),
      },
      {
        id: "zoom-reset",
        label: "Reset notation zoom to 100%",
        group: "Navigate",
        shortcut: "⌘0",
        keywords: ["score scale", "normal"],
        disabled: viewer.isLoading || viewer.scoreScale === 1,
        run: () => viewer.setScoreScale(1),
      },
      {
        id: "zoom-in",
        label: "Zoom notation in",
        group: "Navigate",
        shortcut: "⌘+",
        keywords: ["score scale", "larger"],
        disabled: viewer.isLoading || viewer.scoreScale >= 1.5,
        run: () => viewer.setScoreScale(stepScoreScale(viewer.scoreScale, 1)),
      },
      {
        id: "page-layout",
        label: "Use page score layout",
        group: "Navigate",
        keywords: ["view", "vertical", "wrap"],
        disabled: viewer.isLoading || viewer.scoreLayout === "page",
        run: () => viewer.setScoreLayout("page"),
      },
      {
        id: "horizontal-layout",
        label: "Use horizontal score layout",
        group: "Navigate",
        keywords: ["view", "continuous", "single row"],
        disabled: viewer.isLoading || viewer.scoreLayout === "horizontal",
        run: () => viewer.setScoreLayout("horizontal"),
      },
      {
        id: "play-pause",
        label: viewer.isPlaying ? "Pause playback" : "Start playback",
        group: "Playback",
        shortcut: "Space",
        disabled: !viewer.playerReady,
        run: viewer.togglePlayback,
      },
      {
        id: "stop",
        label: "Stop playback",
        group: "Playback",
        shortcut: "Esc",
        disabled: !viewer.playerReady,
        run: viewer.stopPlayback,
      },
      {
        id: "loop-selection",
        label: viewer.loopSelectionEnabled ? "Disable selection loop" : "Loop selected passage",
        group: "Playback",
        shortcut: "L",
        keywords: ["repeat", "practice"],
        disabled: !viewer.playerReady || !viewer.canLoopSelection,
        run: viewer.toggleLoopSelection,
      },
      {
        id: "metronome",
        label: viewer.metronomeEnabled ? "Turn metronome off" : "Turn metronome on",
        group: "Playback",
        shortcut: "M",
        disabled: !viewer.playerReady,
        run: viewer.toggleMetronome,
      },
      {
        id: "count-in",
        label: viewer.countInEnabled ? "Turn count-in off" : "Turn count-in on",
        group: "Playback",
        shortcut: "⇧M",
        keywords: ["countoff", "practice"],
        disabled: !viewer.playerReady,
        run: viewer.toggleCountIn,
      },
      {
        id: "slower",
        label: "Decrease playback speed",
        group: "Playback",
        keywords: ["tempo", "practice", "slower"],
        disabled: !viewer.playerReady || viewer.playbackSpeed <= 0.5,
        run: () => viewer.setPlaybackSpeed(stepPlaybackSpeed(viewer.playbackSpeed, -1)),
      },
      {
        id: "normal-speed",
        label: "Reset playback speed to 100%",
        group: "Playback",
        keywords: ["tempo", "normal"],
        disabled: !viewer.playerReady || viewer.playbackSpeed === 1,
        run: () => viewer.setPlaybackSpeed(1),
      },
      {
        id: "faster",
        label: "Increase playback speed",
        group: "Playback",
        keywords: ["tempo", "practice", "faster"],
        disabled: !viewer.playerReady || viewer.playbackSpeed >= 1.5,
        run: () => viewer.setPlaybackSpeed(stepPlaybackSpeed(viewer.playbackSpeed, 1)),
      },
      {
        id: "reload",
        label: "Reload committed revision",
        group: "Project",
        keywords: ["refresh", "server"],
        run: () => { void load(true); },
      },
      {
        id: "export-gp5",
        label: "Export current revision as GP5",
        group: "Project",
        disabled: exporting !== null || saveState === "saving" || !envelope,
        run: () => { void exportCurrent("gp5"); },
      },
      {
        id: "export-xml",
        label: "Export current revision as MusicXML",
        group: "Project",
        disabled: exporting !== null || saveState === "saving" || !envelope,
        run: () => { void exportCurrent("musicxml"); },
      },
      {
        id: "export-midi",
        label: "Export current revision as humanized MIDI",
        group: "Project",
        disabled: exporting !== null || saveState === "saving" || !envelope,
        run: () => { void exportCurrent("humanized_midi"); },
      },
      ...(project?.source_filename ? [{
        id: "prepare-score",
        label: "Open score preparation tools",
        group: "Project" as const,
        keywords: ["repair", "humanize", "LLM"],
        run: () => navigate(`/projects/${projectId}`),
      }] : []),
    ];
  }, [
    clipboard,
    commandHistory.length,
    copyBeat,
    cutBeat,
    deleteSelection,
    envelope,
    exportCurrent,
    exporting,
    insertMeasureAfter,
    load,
    makeSelectionRest,
    navigate,
    navigableBeats,
    pasteAfter,
    project?.source_filename,
    projectId,
    redo,
    redoHistory.length,
    saveState,
    selectedBeat,
    undo,
    viewer.canLoopSelection,
    viewer.countInEnabled,
    viewer.isPlaying,
    viewer.isLoading,
    viewer.loopSelectionEnabled,
    viewer.metronomeEnabled,
    viewer.playbackSpeed,
    viewer.playerReady,
    viewer.scoreLayout,
    viewer.scoreScale,
    viewer.setPlaybackSpeed,
    viewer.setScoreLayout,
    viewer.setScoreScale,
    viewer.stopPlayback,
    viewer.toggleCountIn,
    viewer.toggleLoopSelection,
    viewer.toggleMetronome,
    viewer.togglePlayback,
  ]);

  if (loading) {
    return <Box className="h-full flex items-center justify-center gap-3"><CircularProgress size={26} /><Typography sx={{ color: palette.textSecondary }}>Opening score…</Typography></Box>;
  }
  if (!project || !envelope) {
    return <Box className="h-full flex items-center justify-center"><Alert severity="error">{message ?? "Score not found."}</Alert></Box>;
  }

  const isUnprepared = envelope.document.tracks.some(
    (track) => track.instrument.realization_status === "unprepared",
  );
  const activeTrack = envelope.document.tracks.find((track) => track.id === activeTrackId) ?? null;
  const activeTrackBeatCount = activeTrack?.measures.reduce(
    (total, measure) => total + measure.beats.length,
    0,
  ) ?? 0;
  const activeStringCount = Array.isArray(activeTrack?.instrument.tuning)
    ? activeTrack.instrument.tuning.length
    : 0;
  const activeVoice = selectedBeat?.beat.voice ?? 1;

  return (
    <Box
      className="h-full min-h-0 flex flex-col"
      data-bp-save-api-ms={lastSaveTiming?.apiMs.toFixed(2)}
      data-bp-save-total-ms={lastSaveTiming?.totalMs.toFixed(2)}
      sx={{ background: "#ECE9E2" }}
    >
      <Box className="flex items-center gap-2 px-3 sm:px-4 flex-shrink-0" sx={{ minHeight: 58, background: "#FFFFFF", borderBottom: `1px solid ${palette.borderDefault}` }}>
        <Box className="flex items-center gap-2 pr-2 mr-1" sx={{ borderRight: `1px solid ${palette.borderDefault}` }}>
          <Box className="flex items-center justify-center" sx={{ width: 28, height: 28, borderRadius: 1.75, background: palette.brandPrimary, color: "#FFFFFF", fontWeight: 900, fontSize: 11 }}>BP</Box>
          <Typography sx={{ display: { xs: "none", sm: "block" }, color: palette.textPrimary, fontSize: 12, fontWeight: 850 }}>Studio</Typography>
        </Box>
        <Tooltip title="Back to projects"><IconButton component={Link} to="/" size="small"><ArrowBackIcon fontSize="small" /></IconButton></Tooltip>
        <Box className="min-w-0 mr-auto">
          <Typography className="truncate" sx={{ color: palette.textPrimary, fontWeight: 820, fontSize: 14 }}>{project.title}</Typography>
          <Box className="flex items-center gap-1.5">
            <Typography sx={{ color: palette.textTertiary, fontSize: 10.5 }}>Revision {envelope.revision.number}</Typography>
            <Box sx={{ width: 5, height: 5, borderRadius: "50%", background: saveState === "conflict" ? palette.error : saveState === "saving" ? palette.warning : palette.success }} />
            <Typography sx={{ color: palette.textTertiary, fontSize: 10.5 }}>{saveState === "saving" ? "Saving…" : saveState === "conflict" ? "Review conflict" : "Saved"}</Typography>
          </Box>
        </Box>
        <Tooltip title="Undo last edit from this session"><span><IconButton aria-label="Undo" disabled={saveState === "saving" || commandHistory.length === 0} onClick={() => void undo()} size="small"><UndoIcon fontSize="small" /></IconButton></span></Tooltip>
        <Tooltip title="Redo"><span><IconButton aria-label="Redo" disabled={saveState === "saving" || redoHistory.length === 0} onClick={() => void redo()} size="small"><RedoIcon fontSize="small" /></IconButton></span></Tooltip>
        <Tooltip title="Reload current revision"><IconButton onClick={() => void load(true)} size="small"><RefreshIcon fontSize="small" /></IconButton></Tooltip>
        <Tooltip title="Commands · ⌘K"><IconButton aria-label="Open command palette" onClick={() => setCommandPaletteOpen(true)} size="small"><BoltIcon fontSize="small" /></IconButton></Tooltip>
        <Divider orientation="vertical" flexItem sx={{ my: 1.5 }} />
        <Tooltip title={viewer.playerReady ? (viewer.isPlaying ? "Pause" : "Play") : "Loading playback sounds"}><span><IconButton aria-label={viewer.isPlaying ? "Pause" : "Play"} disabled={!viewer.playerReady} onClick={viewer.togglePlayback} size="small">{viewer.isPlaying ? <PauseIcon fontSize="small" /> : <PlayArrowIcon fontSize="small" />}</IconButton></span></Tooltip>
        <Tooltip title="Stop"><span><IconButton aria-label="Stop" disabled={!viewer.playerReady} onClick={viewer.stopPlayback} size="small"><StopIcon fontSize="small" /></IconButton></span></Tooltip>
        <Tooltip title={viewer.canLoopSelection ? "Loop the selected passage" : "Select a note or passage to loop"}>
          <span>
            <IconButton
              aria-label="Loop selection"
              aria-pressed={viewer.loopSelectionEnabled}
              color={viewer.loopSelectionEnabled ? "primary" : "default"}
              disabled={!viewer.playerReady || !viewer.canLoopSelection}
              onClick={viewer.toggleLoopSelection}
              size="small"
            >
              <RepeatIcon fontSize="small" />
            </IconButton>
          </span>
        </Tooltip>
        <Tooltip title={viewer.metronomeEnabled ? "Turn metronome off" : "Turn metronome on"}>
          <span>
            <IconButton
              aria-label="Toggle metronome"
              aria-pressed={viewer.metronomeEnabled}
              color={viewer.metronomeEnabled ? "primary" : "default"}
              disabled={!viewer.playerReady}
              onClick={viewer.toggleMetronome}
              size="small"
            >
              <GraphicEqIcon fontSize="small" />
            </IconButton>
          </span>
        </Tooltip>
        <Tooltip title={viewer.countInEnabled ? "Turn count-in off" : "Turn count-in on"}>
          <span>
            <IconButton
              aria-label="Toggle count-in"
              aria-pressed={viewer.countInEnabled}
              color={viewer.countInEnabled ? "primary" : "default"}
              disabled={!viewer.playerReady}
              onClick={viewer.toggleCountIn}
              size="small"
            >
              <MusicNoteIcon fontSize="small" />
            </IconButton>
          </span>
        </Tooltip>
        <ButtonGroup
          aria-label="Playback speed"
          size="small"
          variant="outlined"
          sx={{ display: { xs: "none", lg: "inline-flex" }, whiteSpace: "nowrap" }}
        >
          <Button
            aria-label="Decrease playback speed"
            disabled={!viewer.playerReady || viewer.playbackSpeed <= 0.5}
            onClick={() => viewer.setPlaybackSpeed(stepPlaybackSpeed(viewer.playbackSpeed, -1))}
            sx={{ minWidth: 28, px: 0.5 }}
          >
            −
          </Button>
          <Button
            aria-label={`Playback speed ${Math.round(viewer.playbackSpeed * 100)}%`}
            disabled
            startIcon={<SpeedIcon fontSize="small" />}
            sx={{ minWidth: 74, px: 1, "&.Mui-disabled": { color: palette.textSecondary } }}
          >
            {Math.round(viewer.playbackSpeed * 100)}%
          </Button>
          <Button
            aria-label="Increase playback speed"
            disabled={!viewer.playerReady || viewer.playbackSpeed >= 1.5}
            onClick={() => viewer.setPlaybackSpeed(stepPlaybackSpeed(viewer.playbackSpeed, 1))}
            sx={{ minWidth: 28, px: 0.5 }}
          >
            +
          </Button>
        </ButtonGroup>
        {project.source_filename && (
          <Button onClick={() => navigate(`/projects/${projectId}`)} startIcon={<TuneIcon />} color="inherit" size="small" sx={{ display: { xs: "none", md: "inline-flex" } }}>
            Prepare score
          </Button>
        )}
        {lastExport && (
          <Typography
            sx={{
              color: palette.success,
              display: { xs: "none", xl: "block" },
              fontSize: 10.5,
              fontWeight: 750,
              whiteSpace: "nowrap",
            }}
          >
            Rev {lastExport.revision} · {lastExport.format} exported
          </Typography>
        )}
        <Tooltip title={`Export committed revision ${envelope.revision.number}`}>
          <ButtonGroup variant="contained" size="small" aria-label="Export current revision">
            {([
              ["gp5", "GP5"],
              ["musicxml", "XML"],
              ["humanized_midi", "MIDI"],
            ] as const).map(([format, label]) => (
              <Button
                key={format}
                disabled={exporting !== null || saveState === "saving"}
                onClick={() => void exportCurrent(format)}
                startIcon={exporting === format ? <CircularProgress size={14} /> : format === "gp5" ? <DownloadIcon /> : undefined}
                sx={{ minWidth: 0, px: 1 }}
              >
                {label}
              </Button>
            ))}
          </ButtonGroup>
        </Tooltip>
      </Box>

      <CommandPalette
        commands={editorCommands}
        onClose={() => setCommandPaletteOpen(false)}
        open={commandPaletteOpen}
      />

      {message && <Alert severity={saveState === "conflict" ? "warning" : "error"} onClose={() => setMessage(null)} sx={{ borderRadius: 0 }}>{message}</Alert>}
      {isUnprepared && (
        <Alert severity="info" icon={<TuneIcon />} sx={{ borderRadius: 0, py: 0.25 }}>
          This is the truthful raw MIDI notation. Run <strong>Prepare score</strong> before expecting playable fingering, drum assignment and articulations.
        </Alert>
      )}

      <EditionToolbar
        duration={displayedDuration}
        durationModifier={durationState?.modifier ?? null}
        family={activeTrack?.family ?? null}
        voice={activeVoice}
        caretString={caretString}
        activeDrumPiece={
          selectedNote?.track.family === "drums"
            ? selectedNote.note.realization.piece ?? null
            : null
        }
        pitchOctave={pitchOctave}
        activePitch={
          selectedNote &&
          (selectedNote.track.family === "keys" || selectedNote.track.family === "generic")
            ? selectedNote.note.pitch
            : null
        }
        stringCount={activeStringCount}
        selectionCount={selectedBeatIds.length}
        selectedNoteCount={selectedTechniqueNoteIds.length}
        activeTechniques={activeTechniqueTypes}
        activeDynamic={activeDynamic}
        canTie={Boolean(tiePreview)}
        tieActive={tiePreview?.active ?? false}
        canTranspose={activeTrack?.family !== "drums"}
        canEditMeasure={Boolean(selectedBeat)}
        canDeleteMeasure={Boolean(
          selectedBeat && envelope.document.tracks.every((track) => track.measures.length > 1),
        )}
        disabled={saveState === "saving"}
        onDuration={changeDuration}
        onDurationModifier={changeDurationModifier}
        onVoice={changeVoice}
        onString={selectCaretString}
        onDrumPiece={enterDrumPiece}
        onPitchOctave={setPitchOctave}
        onPitchedNote={enterPitchedNote}
        onInsert={(kind) => {
          if (!selectedBeat && !project.source_filename && activeTrackBeatCount === 0) addFirst(kind);
          else insertAfter(kind);
        }}
        onMakeRest={() => void makeSelectionRest()}
        onTechnique={toggleTechnique}
        onDynamic={changeDynamic}
        onTie={toggleTie}
        onTranspose={transposeSelection}
        onInsertMeasure={() => insertMeasureAfter("empty")}
        onDuplicateMeasure={() => insertMeasureAfter("duplicate")}
        onDeleteMeasure={deleteMeasure}
      />

      <Box className="flex-1 min-h-0 grid" sx={{ gridTemplateColumns: { xs: "1fr", lg: "208px minmax(0, 1fr) 288px" } }}>
        <Box className="hidden lg:flex flex-col min-h-0" sx={{ background: "#F8F6F1", borderRight: `1px solid ${palette.borderDefault}` }}>
          <TrackRail
            tracks={envelope.document.tracks}
            activeTrackId={activeTrackId}
            disabled={saveState === "saving"}
            onSelect={selectTrack}
            onAdd={addTrack}
            onMove={moveTrack}
            onMixer={changeTrackMixer}
            onSetup={changeTrackSetup}
            onDelete={deleteEmptyTrack}
          />
        </Box>

        <Box className="min-w-0 min-h-0 overflow-auto p-3">
          <Box sx={{ minWidth: 760, maxWidth: 1180, mx: "auto", background: "#FFFFFF", border: `1px solid ${palette.borderDefault}`, boxShadow: "0 3px 16px rgba(23,25,29,.08)", overflow: "hidden", position: "relative" }}>
            {viewer.isLoading && <Box className="absolute inset-0 z-10 flex items-center justify-center" sx={{ background: "rgba(255,255,255,.8)" }}><CircularProgress size={26} /></Box>}
            {viewer.error && <Alert severity="error" sx={{ borderRadius: 0 }}>{viewer.error}</Alert>}
            <Box ref={viewer.containerRef} className="bp-editor-score" sx={{ minHeight: 360, py: 1 }} />
          </Box>
        </Box>

        <Box className="hidden lg:block min-h-0 overflow-y-auto" sx={{ background: "#FFFFFF", borderLeft: `1px solid ${palette.borderDefault}` }}>
          <SelectionInspector
            beatContext={selectedBeat}
            noteContext={selectedNote}
            disabled={saveState === "saving"}
            canAddFirst={!project.source_filename && activeTrackBeatCount === 0}
            canPaste={Boolean(clipboard && clipboard.sourceTrackId === activeTrackId)}
            selectionCount={selectedBeatIds.length}
            techniqueLabels={selectedNoteTechniqueLabels}
            onAddFirst={addFirst}
            onInsertAfter={insertAfter}
            onDuration={changeDuration}
            onDelete={() => void deleteSelection()}
            onCopy={copyBeat}
            onCut={() => void cutBeat()}
            onPaste={pasteAfter}
            onPitch={changePitch}
            onString={changeString}
          />
        </Box>
      </Box>
      <EditorStatusBar
        trackName={activeTrack?.name ?? null}
        family={activeTrack?.family ?? null}
        measure={selectedBeat?.measure.number ?? null}
        voice={activeVoice}
        caretString={caretString}
        selectedBeatCount={selectedBeatIds.length}
        fretBuffer={fretBuffer}
        scoreLayout={viewer.scoreLayout}
        scoreScale={viewer.scoreScale}
      />
    </Box>
  );
}
