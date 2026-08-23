"""Pipeline runner — bridges MIDI to FretPilot's repair pipeline.

Encapsulates the full pipeline invocation (detect → cleanup → context →
execute) so the e-learning module treats the pipeline as a black box.
Runs in degraded mode (``advisor=None``) to avoid LLM dependency.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fretpilot.detection.classifier import classify_timeline
from fretpilot.detection.streams import resolve_streams
from fretpilot.engine.cleanup import auto_detect_tuning, cleanup_streams
from fretpilot.engine.context import PipelineContext
from fretpilot.engine.pipeline import create_pipeline
from fretpilot.ir.models import GuitarProjectIR
from fretpilot.knowledge.tunings import GuitarTuning
from fretpilot.midi.models import NormalizedTimeline, NormalizedTrack
from fretpilot.midi.parser import load_midi

logger = logging.getLogger("fretpilot.elearning.pipeline_runner")


class PipelineRunner:
    """P0-3: Run the FretPilot pipeline on a MIDI file and return the IR."""

    def __init__(self, knowledge_dir: str | None = None) -> None:
        self._knowledge_dir = knowledge_dir

    def run(
        self,
        midi_path: str,
        style_label: str = "unknown",
        tuning_pitches: list[int] | None = None,
        midi_fidelity: float = 0.5,
    ) -> GuitarProjectIR:
        """Execute the full pipeline and return the reconstructed IR.

        Parameters
        ----------
        midi_path
            Path to the MIDI file (produced by ``GPMidiConverter``).
        style_label
            KB2 style label for priors selection.
        tuning_pitches
            Open-string pitches (low → high) from the GP file.
            When ``None``, auto-detect is used.
        midi_fidelity
            MIDI quality estimate (0=worst, 1=best).  Fixed at 0.5 for
            consistent evaluation baselines.
        """
        timeline = load_midi(midi_path)
        report = classify_timeline(timeline)
        streams = resolve_streams(timeline)

        # Resolve tuning
        tuning: GuitarTuning | None = None
        if tuning_pitches:
            tuning = self._build_tuning(tuning_pitches)
        elif streams:
            tuning = auto_detect_tuning(streams)

        # Cleanup
        cleaned_track = self._build_cleaned_track(timeline, streams, tuning)

        # Build and run pipeline
        knowledge_dir = self._knowledge_dir or str(
            Path(__file__).resolve().parent.parent / "knowledge" / "assets"
        )
        pipeline = create_pipeline(knowledge_dir)
        track_role = (
            report.primary_classification.guitar_role
            if report.primary_classification
            else "unknown"
        )

        ctx = PipelineContext(
            timeline=timeline,
            track=cleaned_track,
            knowledge=pipeline.registry,
            style_label=style_label,
            midi_fidelity=midi_fidelity,
            advisor=None,
            track_role=track_role,
            source_track_index=cleaned_track.index,
            degraded_mode=True,
            tuning=tuning,
        )

        ir = pipeline.execute(ctx)
        logger.debug(
            "Pipeline completed: %s, %d tracks, %d measures",
            midi_path,
            len(ir.tracks),
            len(ir.tracks[0].measures) if ir.tracks else 0,
        )
        return ir

    def _build_tuning(self, pitches: list[int]) -> GuitarTuning:
        """Build a ``GuitarTuning`` from open-string pitches (low → high)."""
        return GuitarTuning(
            id="gp-source",
            name="GP Source Tuning",
            display_name="GP Source Tuning",
            string_count=len(pitches),
            string_pitches=list(pitches),
            min_pitch=min(pitches),
            max_pitch=max(pitches) + 24,
            description="Tuning extracted from GP file",
        )

    def _build_cleaned_track(
        self,
        timeline: NormalizedTimeline,
        streams: list,
        tuning: GuitarTuning | None,
    ) -> NormalizedTrack:
        """Build a cleaned NormalizedTrack from timeline streams."""
        if not streams:
            # Fallback: use first track with notes
            for t in timeline.tracks:
                if t.notes:
                    return t
            return NormalizedTrack(index=0, name="empty")

        clean_result = cleanup_streams(
            streams,
            timeline=timeline,
            tuning=tuning,
            out_of_range_mode="flag",
        )

        if clean_result and clean_result.streams:
            primary = max(clean_result.streams, key=lambda s: s.note_count)
            return NormalizedTrack(
                index=primary.source_track_indices[0] if primary.source_track_indices else 0,
                name=primary.track_name,
                notes=list(primary.notes),
                instrument_name=primary.instrument_name,
                program=primary.program,
            )

        # Fallback: first stream
        primary = max(streams, key=lambda s: s.note_count)
        return NormalizedTrack(
            index=primary.source_track_indices[0] if primary.source_track_indices else 0,
            name=primary.track_name,
            notes=list(primary.notes),
            instrument_name=primary.instrument_name,
            program=primary.program,
        )


__all__ = ["PipelineRunner"]
