import { useCallback, useEffect, useRef, useState } from "react";
import type { AlphaTabApi, Settings } from "@coderline/alphatab";
import type { ScoreDocument } from "../api/types";
import type { AlphaTabScoreAdapterResult } from "../editor/alphaTabAdapter";
import { playbackRangeForBeatGroups } from "../editor/playbackTransport";

interface UseScoreDocumentAlphaTabOptions {
  document: ScoreDocument | null;
  activeTrackId: string | null;
  selectedBeatId: string | null;
  selectedBeatIds?: string[];
  selectedNoteId: string | null;
  onSelectBeat(beatId: string): void;
  onSelectNote(noteId: string): void;
}

interface UseScoreDocumentAlphaTabResult {
  containerRef: React.RefObject<HTMLDivElement>;
  isLoading: boolean;
  error: string | null;
  playerReady: boolean;
  isPlaying: boolean;
  scoreScale: number;
  scoreLayout: "page" | "horizontal";
  playbackSpeed: number;
  metronomeEnabled: boolean;
  countInEnabled: boolean;
  loopSelectionEnabled: boolean;
  canLoopSelection: boolean;
  setScoreScale(scale: number): void;
  setScoreLayout(layout: "page" | "horizontal"): void;
  setPlaybackSpeed(speed: number): void;
  toggleMetronome(): void;
  toggleCountIn(): void;
  toggleLoopSelection(): void;
  togglePlayback(): void;
  stopPlayback(): void;
}

/** Render the canonical editor document directly; no GP5 round-trip is involved. */
export function useScoreDocumentAlphaTab({
  document,
  activeTrackId,
  selectedBeatId,
  selectedBeatIds = [],
  selectedNoteId,
  onSelectBeat,
  onSelectNote,
}: UseScoreDocumentAlphaTabOptions): UseScoreDocumentAlphaTabResult {
  const containerRef = useRef<HTMLDivElement>(null);
  const apiRef = useRef<AlphaTabApi | null>(null);
  const settingsRef = useRef<Settings | null>(null);
  const layoutModeValuesRef = useRef<{
    page: Settings["display"]["layoutMode"];
    horizontal: Settings["display"]["layoutMode"];
  } | null>(null);
  const adaptedRef = useRef<AlphaTabScoreAdapterResult | null>(null);
  const pointerHandlerRef = useRef<{
    container: HTMLDivElement;
    handler: (event: PointerEvent) => void;
  } | null>(null);
  const renderStartedAtRef = useRef<number | null>(null);
  const selectedBeatIdRef = useRef(selectedBeatId);
  const selectedBeatIdsRef = useRef(selectedBeatIds);
  const selectedNoteIdRef = useRef(selectedNoteId);
  const onSelectBeatRef = useRef(onSelectBeat);
  const onSelectNoteRef = useRef(onSelectNote);
  const skipNextSelectionHighlightRef = useRef(false);
  const scoreScaleRef = useRef(1);
  const scoreLayoutRef = useRef<"page" | "horizontal">("page");
  const transportRef = useRef({
    playbackSpeed: 1,
    metronomeEnabled: false,
    countInEnabled: false,
    loopSelectionEnabled: false,
  });
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [playerReady, setPlayerReady] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [rendererReady, setRendererReady] = useState(false);
  const [scoreScale, setScoreScaleState] = useState(1);
  const [scoreLayout, setScoreLayoutState] = useState<"page" | "horizontal">("page");
  const [playbackSpeed, setPlaybackSpeedState] = useState(1);
  const [metronomeEnabled, setMetronomeEnabled] = useState(false);
  const [countInEnabled, setCountInEnabled] = useState(false);
  const [loopSelectionEnabled, setLoopSelectionEnabled] = useState(false);
  const [canLoopSelection, setCanLoopSelection] = useState(false);

  useEffect(() => {
    selectedBeatIdRef.current = selectedBeatId;
    selectedBeatIdsRef.current = selectedBeatIds;
    selectedNoteIdRef.current = selectedNoteId;
    onSelectBeatRef.current = onSelectBeat;
    onSelectNoteRef.current = onSelectNote;
  }, [onSelectBeat, onSelectNote, selectedBeatId, selectedBeatIds, selectedNoteId]);

  const highlightSelection = useCallback(() => {
    if (skipNextSelectionHighlightRef.current) {
      skipNextSelectionHighlightRef.current = false;
      return;
    }
    const api = apiRef.current;
    const adapted = adaptedRef.current;
    if (!api || !adapted) return;
    if (selectedNoteIdRef.current) {
      const note = adapted.stableNoteModels.get(selectedNoteIdRef.current)?.[0];
      if (note) {
        api.highlightPlaybackRange(note.beat, note.beat);
      } else {
        api.clearPlaybackRangeHighlight();
      }
      return;
    }
    const ids = selectedBeatIdsRef.current.length > 0
      ? selectedBeatIdsRef.current
      : selectedBeatIdRef.current
        ? [selectedBeatIdRef.current]
        : [];
    const first = ids[0] ? adapted.stableBeatModels.get(ids[0])?.[0] : null;
    const lastId = ids[ids.length - 1];
    const last = lastId ? adapted.stableBeatModels.get(lastId)?.[0] : null;
    if (first && last) {
      api.highlightPlaybackRange(first, last);
    } else {
      api.clearPlaybackRangeHighlight();
    }
  }, []);

  const selectedPlaybackRange = useCallback(() => {
    const adapted = adaptedRef.current;
    if (!adapted) return null;
    const selectedNote = selectedNoteIdRef.current;
    if (selectedNote) {
      const notes = adapted.stableNoteModels.get(selectedNote) ?? [];
      return playbackRangeForBeatGroups(notes.map((note) => [note.beat]));
    }
    const beatIds = selectedBeatIdsRef.current.length > 0
      ? selectedBeatIdsRef.current
      : selectedBeatIdRef.current
        ? [selectedBeatIdRef.current]
        : [];
    return playbackRangeForBeatGroups(
      beatIds.map((beatId) => adapted.stableBeatModels.get(beatId) ?? []),
    );
  }, []);

  const applyTransportSettings = useCallback(() => {
    const api = apiRef.current;
    const container = containerRef.current;
    if (!api || !container) return;
    const selectedRange = selectedPlaybackRange();
    const loopEnabled = transportRef.current.loopSelectionEnabled && selectedRange !== null;
    if (transportRef.current.loopSelectionEnabled && !selectedRange) {
      transportRef.current.loopSelectionEnabled = false;
      setLoopSelectionEnabled(false);
    }
    setCanLoopSelection(selectedRange !== null);
    api.playbackSpeed = transportRef.current.playbackSpeed;
    api.metronomeVolume = transportRef.current.metronomeEnabled ? 0.6 : 0;
    api.countInVolume = transportRef.current.countInEnabled ? 0.6 : 0;
    api.playbackRange = loopEnabled ? selectedRange : null;
    api.isLooping = loopEnabled;
    container.dataset.bpPlaybackSpeed = transportRef.current.playbackSpeed.toFixed(2);
    container.dataset.bpScoreScale = scoreScaleRef.current.toFixed(2);
    container.dataset.bpScoreLayout = scoreLayoutRef.current;
    container.dataset.bpMetronomeEnabled = String(transportRef.current.metronomeEnabled);
    container.dataset.bpCountInEnabled = String(transportRef.current.countInEnabled);
    container.dataset.bpLoopEnabled = String(loopEnabled);
    if (loopEnabled && selectedRange) {
      container.dataset.bpLoopStartTick = String(selectedRange.startTick);
      container.dataset.bpLoopEndTick = String(selectedRange.endTick);
    } else {
      delete container.dataset.bpLoopStartTick;
      delete container.dataset.bpLoopEndTick;
    }
  }, [selectedPlaybackRange]);

  useEffect(() => {
    highlightSelection();
    applyTransportSettings();
  }, [
    applyTransportSettings,
    highlightSelection,
    selectedBeatId,
    selectedBeatIds,
    selectedNoteId,
  ]);

  const destroy = useCallback(() => {
    const pointerHandler = pointerHandlerRef.current;
    pointerHandlerRef.current = null;
    if (pointerHandler) {
      pointerHandler.container.removeEventListener(
        "pointerdown",
        pointerHandler.handler,
        { capture: true },
      );
    }
    const api = apiRef.current;
    apiRef.current = null;
    settingsRef.current = null;
    adaptedRef.current = null;
    if (api) {
      try {
        api.destroy();
      } catch {
        // The host element may already have been removed by React.
      }
    }
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !document || apiRef.current) return;
    let cancelled = false;
    setError(null);

    void (async () => {
      try {
        const alphaTab = await import("@coderline/alphatab");
        if (cancelled) return;
        container.replaceChildren();

        const settings = new alphaTab.Settings();
        layoutModeValuesRef.current = {
          page: alphaTab.LayoutMode.Page,
          horizontal: alphaTab.LayoutMode.Horizontal,
        };
        settings.core.engine = "svg";
        settings.core.useWorkers = false;
        settings.core.includeNoteBounds = true;
        settings.core.enableLazyLoading = true;
        settings.core.fontDirectory = "/font/";
        settings.display.scale = 1;
        settings.display.stretchForce = 0.9;
        settings.player.enablePlayer = true;
        settings.player.soundFont = "/soundfont/sonivox.sf3";

        const api = new alphaTab.AlphaTabApi(container, settings);
        apiRef.current = api;
        settingsRef.current = settings;

        // AlphaTab's native mouse hit testing can miss note heads on a
        // multi-staff SVG when the host has padding or is inside a scroller.
        // Resolve the same public bounds lookup from the stable adapter so a
        // visible note always remains directly editable. Native AlphaTab
        // events still handle playback selection and are harmlessly
        // idempotent when they identify the same beat/note.
        const handlePointerDown = (event: PointerEvent): void => {
          if (event.button !== 0) return;
          const selectionStartedAt = performance.now();
          const lookup = api.boundsLookup;
          const adapted = adaptedRef.current;
          if (!lookup || !adapted) return;
          const hitSurface = container.querySelector<HTMLElement>(".at-surface");
          const bounds = (hitSurface ?? container).getBoundingClientRect();
          const x = event.clientX - bounds.left;
          const y = event.clientY - bounds.top;
          let beat = lookup.getBeatAtPos(x, y);
          let note = beat ? lookup.getNoteAtPos(beat, x, y) : null;

          // A grand staff can contain several AlphaTab beats at the same X
          // position. BoundsLookup picks one staff before it considers note
          // heads, so a treble note may be hidden by the bass-staff beat. In
          // that case resolve the rendered note head directly and use its own
          // beat as the selection target.
          if (!note) {
            const hitPadding = 2;
            outer: for (const system of lookup.staffSystems) {
              for (const masterBar of system.bars) {
                for (const bar of masterBar.bars) {
                  for (const beatBounds of bar.beats) {
                    for (const noteBounds of beatBounds.notes ?? []) {
                      const head = noteBounds.noteHeadBounds;
                      if (
                        x >= head.x - hitPadding
                        && x <= head.x + head.w + hitPadding
                        && y >= head.y - hitPadding
                        && y <= head.y + head.h + hitPadding
                      ) {
                        note = noteBounds.note;
                        beat = note.beat;
                        break outer;
                      }
                    }
                  }
                }
              }
            }
          }
          if (!beat) return;
          if (note) {
            const stableNoteId = adapted.alphaNoteIds.get(note.id);
            if (stableNoteId) {
              event.preventDefault();
              event.stopPropagation();
              skipNextSelectionHighlightRef.current = true;
              onSelectNoteRef.current(stableNoteId);
              requestAnimationFrame(() => {
                const selectionPaintMs = performance.now() - selectionStartedAt;
                performance.clearMeasures("bandpilot:score-selection-paint");
                performance.measure("bandpilot:score-selection-paint", {
                  start: selectionStartedAt,
                  end: performance.now(),
                });
                container.dataset.bpSelectionPaintMs = selectionPaintMs.toFixed(2);
                setTimeout(() => {
                  if (apiRef.current === api) {
                    api.highlightPlaybackRange(note.beat, note.beat);
                  }
                }, 0);
              });
              return;
            }
          }
          const stableBeatId = adapted.alphaBeatIds.get(beat.id);
          if (stableBeatId) {
            event.preventDefault();
            event.stopPropagation();
            skipNextSelectionHighlightRef.current = true;
            onSelectBeatRef.current(stableBeatId);
            requestAnimationFrame(() => {
              const selectionPaintMs = performance.now() - selectionStartedAt;
              performance.clearMeasures("bandpilot:score-selection-paint");
              performance.measure("bandpilot:score-selection-paint", {
                start: selectionStartedAt,
                end: performance.now(),
              });
              container.dataset.bpSelectionPaintMs = selectionPaintMs.toFixed(2);
              setTimeout(() => {
                if (apiRef.current === api) api.highlightPlaybackRange(beat, beat);
              }, 0);
            });
          }
        };
        container.addEventListener("pointerdown", handlePointerDown, { capture: true });
        pointerHandlerRef.current = { container, handler: handlePointerDown };

        api.beatMouseDown.on((beat) => {
          const stableId = adaptedRef.current?.alphaBeatIds.get(beat.id);
          if (!stableId) return;
          skipNextSelectionHighlightRef.current = true;
          onSelectBeatRef.current(stableId);
        });
        api.noteMouseDown.on((note) => {
          const stableId = adaptedRef.current?.alphaNoteIds.get(note.id);
          if (!stableId) return;
          skipNextSelectionHighlightRef.current = true;
          onSelectNoteRef.current(stableId);
        });
        api.postRenderFinished.on(() => {
          if (cancelled) return;
          const renderStartedAt = renderStartedAtRef.current;
          if (renderStartedAt !== null) {
            const renderMs = performance.now() - renderStartedAt;
            performance.clearMeasures("bandpilot:score-render");
            performance.measure("bandpilot:score-render", {
              start: renderStartedAt,
              end: performance.now(),
            });
            container.dataset.bpRenderMs = renderMs.toFixed(2);
            renderStartedAtRef.current = null;
          }
          highlightSelection();
          applyTransportSettings();
          setIsLoading(false);
        });
        api.playerReady.on(() => {
          if (!cancelled) {
            applyTransportSettings();
            setPlayerReady(true);
          }
        });
        api.playerStateChanged.on((event) => {
          if (!cancelled) setIsPlaying(event.state === alphaTab.synth.PlayerState.Playing);
        });
        setRendererReady(true);
      } catch (caught) {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "The score could not be rendered.");
          setIsLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
      destroy();
    };
  }, [Boolean(document), applyTransportSettings, destroy, highlightSelection]);

  useEffect(() => {
    const api = apiRef.current;
    const settings = settingsRef.current;
    if (!rendererReady || !api || !settings || !document) return;
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    void import("../editor/alphaTabAdapter")
      .then((adapter) => {
        if (cancelled) return;
        renderStartedAtRef.current = performance.now();
        const adapted = adapter.buildAlphaTabScore(document, settings);
        adaptedRef.current = adapted;
        // AlphaTab retains highlighted Beat model references across renders.
        // Those references belong to the previous score and can make its
        // post-render cursor restoration fail before our completion handler.
        api.clearPlaybackRangeHighlight();
        api.renderScore(
          adapted.score,
          adapter.alphaTrackIndexForStableId(adapted, activeTrackId),
        );
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "The score could not be rendered.");
          setIsLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [activeTrackId, document, rendererReady]);

  const togglePlayback = useCallback(() => {
    if (playerReady) apiRef.current?.playPause();
  }, [playerReady]);
  const stopPlayback = useCallback(() => {
    apiRef.current?.stop();
  }, []);
  const setScoreScale = useCallback((scale: number) => {
    const api = apiRef.current;
    const settings = settingsRef.current;
    if (!api || !settings || renderStartedAtRef.current !== null) return;
    const nextScale = Math.min(Math.max(scale, 0.75), 1.5);
    scoreScaleRef.current = nextScale;
    setScoreScaleState(nextScale);
    settings.display.scale = nextScale;
    setIsLoading(true);
    renderStartedAtRef.current = performance.now();
    api.clearPlaybackRangeHighlight();
    api.updateSettings();
    api.render();
  }, []);
  const setScoreLayout = useCallback((layout: "page" | "horizontal") => {
    const api = apiRef.current;
    const settings = settingsRef.current;
    const values = layoutModeValuesRef.current;
    if (!api || !settings || !values || renderStartedAtRef.current !== null) return;
    scoreLayoutRef.current = layout;
    setScoreLayoutState(layout);
    settings.display.layoutMode = values[layout];
    setIsLoading(true);
    renderStartedAtRef.current = performance.now();
    api.clearPlaybackRangeHighlight();
    api.updateSettings();
    api.render();
  }, []);
  const setPlaybackSpeed = useCallback((speed: number) => {
    const nextSpeed = Math.min(Math.max(speed, 0.5), 1.5);
    transportRef.current.playbackSpeed = nextSpeed;
    setPlaybackSpeedState(nextSpeed);
    applyTransportSettings();
  }, [applyTransportSettings]);
  const toggleMetronome = useCallback(() => {
    const nextEnabled = !transportRef.current.metronomeEnabled;
    transportRef.current.metronomeEnabled = nextEnabled;
    setMetronomeEnabled(nextEnabled);
    applyTransportSettings();
  }, [applyTransportSettings]);
  const toggleCountIn = useCallback(() => {
    const nextEnabled = !transportRef.current.countInEnabled;
    transportRef.current.countInEnabled = nextEnabled;
    setCountInEnabled(nextEnabled);
    applyTransportSettings();
  }, [applyTransportSettings]);
  const toggleLoopSelection = useCallback(() => {
    const range = selectedPlaybackRange();
    if (!range) return;
    const nextEnabled = !transportRef.current.loopSelectionEnabled;
    transportRef.current.loopSelectionEnabled = nextEnabled;
    setLoopSelectionEnabled(nextEnabled);
    applyTransportSettings();
  }, [applyTransportSettings, selectedPlaybackRange]);

  return {
    containerRef,
    isLoading,
    error,
    playerReady,
    isPlaying,
    scoreScale,
    scoreLayout,
    playbackSpeed,
    metronomeEnabled,
    countInEnabled,
    loopSelectionEnabled,
    canLoopSelection,
    setScoreScale,
    setScoreLayout,
    setPlaybackSpeed,
    toggleMetronome,
    toggleCountIn,
    toggleLoopSelection,
    togglePlayback,
    stopPlayback,
  };
}
