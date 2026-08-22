"""S8: Drum assemble stage.

Assembles the final DrumProjectIR from all intermediate state accumulated
across the pipeline stages. This is the drum equivalent of the guitar
AssembleStage (S8 in FretPilot).

The assembled IR contains:
  - Tempo and time-signature maps from the source timeline.
  - One DrumTrackIR with measures populated from the notated notes.
  - All transformation records (provenance).
  - All warnings collected during repair.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from fretpilot.engine.drum_context import DrumPipelineContext, NotatedNote
from fretpilot.ir.drum_models import (
    DrumHitLocation,
    DrumMeasure,
    DrumNoteEvent,
    DrumProjectIR,
    DrumTrackIR,
)
from fretpilot.ir.models import (
    IRTempoEvent,
    IRTimeSignatureEvent,
    IRKnowledgeReference,
    NoteConfidence,
    PerformanceTiming,
    ScoreTiming,
)


def _build_tempo_map(ctx: DrumPipelineContext) -> list[IRTempoEvent]:
    """Extract tempo events from the timeline."""
    return [
        IRTempoEvent(beat=e.beat, bpm=e.bpm)
        for e in ctx.timeline.tempo_events
    ]


def _build_time_signatures(ctx: DrumPipelineContext) -> list[IRTimeSignatureEvent]:
    """Extract time-signature events from the timeline."""
    return [
        IRTimeSignatureEvent(beat=e.beat, numerator=e.numerator, denominator=e.denominator)
        for e in ctx.timeline.time_signature_events
    ]


def _build_drum_note_event(
    note: NotatedNote,
    index: int,
) -> DrumNoteEvent:
    """Build a DrumNoteEvent from a NotatedNote.

    Args:
        note: The notated note (output of S7).
        index: 0-based index for stable ID generation.

    Returns:
        A DrumNoteEvent with score/performance timing and hit location.
    """
    mapped = note.sticked.velocity.pattern.mapped
    velocity_note = note.sticked.velocity

    score = ScoreTiming(
        start_beat=mapped.start_beat,
        duration_beats=mapped.duration_beats,
        measure_number=mapped.measure_number,
        beat_in_measure=mapped.beat_in_measure,
    )
    performance = PerformanceTiming(
        source_start_beat=mapped.original_start_beat,
        source_duration_beats=mapped.original_duration_beats,
        velocity=velocity_note.normalized_velocity,
    )
    location = DrumHitLocation(
        piece=mapped.piece,
        sticking=note.sticked.sticking,
        technique=velocity_note.technique,
    )
    confidence = NoteConfidence(
        rhythm=1.0,  # quantized notes are deterministic
        fingering=1.0,  # sticking is deterministic
        articulation=1.0 if velocity_note.technique == "normal" else 0.9,
    )

    return DrumNoteEvent(
        id=f"n-{index + 1:05d}",
        source_note_index=mapped.source_index,
        pitch=mapped.pitch,
        piece=mapped.piece,
        score=score,
        performance=performance,
        location=location,
        confidence=confidence,
    )


def _group_notated_by_measure(
    notes: list[NotatedNote],
) -> dict[int, list[NotatedNote]]:
    """Group notated notes by measure number, excluding redundant hits."""
    groups: dict[int, list[NotatedNote]] = defaultdict(list)
    for note in notes:
        if note.is_redundant:
            continue
        measure = note.sticked.velocity.pattern.mapped.measure_number
        groups[measure].append(note)
    return groups


def _build_measures(
    ctx: DrumPipelineContext,
    notated_by_measure: dict[int, list[NotatedNote]],
) -> list[DrumMeasure]:
    """Build DrumMeasure objects from grouped notes and measure boundaries."""
    measures: list[DrumMeasure] = []
    event_index = 0

    for boundary in ctx.measures:
        measure_notes = notated_by_measure.get(boundary.number, [])
        events = []
        for note in measure_notes:
            event = _build_drum_note_event(note, event_index)
            events.append(event)
            event_index += 1

        pattern = ctx.measure_patterns.get(boundary.number, "unknown")
        measures.append(
            DrumMeasure(
                number=boundary.number,
                start_beat=boundary.start_beat,
                duration_beats=boundary.end_beat - boundary.start_beat,
                numerator=boundary.numerator,
                denominator=boundary.denominator,
                pattern=pattern,
                events=events,
            )
        )

    return measures


def _build_knowledge_ref(ctx: DrumPipelineContext) -> IRKnowledgeReference | None:
    """Build a knowledge reference from the context's registry."""
    try:
        snapshot = ctx.knowledge.snapshot_version  # type: ignore[attr-defined]
    except AttributeError:
        snapshot = "unknown"
    return IRKnowledgeReference(
        snapshot_version=snapshot,
        kb_versions={},
        entry_ids=[],
    )


class DrumAssembleStage:
    """S8: Assemble the final DrumProjectIR from all intermediate state.

    Reads all prior stage outputs from ``ctx`` and builds a DrumProjectIR
    via :meth:`build_ir`. The ``run`` method is a no-op that just records
    the stage as complete; ``build_ir`` does the actual assembly.
    """

    name = "drum_assemble"

    def run(self, ctx: DrumPipelineContext) -> DrumPipelineContext:
        """Mark the assemble stage as complete.

        The actual IR assembly happens in :meth:`build_ir`, called by the
        pipeline orchestrator after all stages have run.
        """
        ctx.record_stage(self.name)
        return ctx

    def build_ir(self, ctx: DrumPipelineContext) -> DrumProjectIR:
        """Assemble the final DrumProjectIR from the pipeline context.

        Args:
            ctx: The pipeline context after all 8 stages have run.

        Returns:
            A complete DrumProjectIR.
        """
        notated_by_measure = _group_notated_by_measure(ctx.notated_notes)
        measures = _build_measures(ctx, notated_by_measure)

        kit_name = ctx.kit.name if ctx.kit else "standard_5pc"
        track_name = (ctx.track.name or "").strip() or "Drums"

        track = DrumTrackIR(
            id=ctx.track_id,
            name=track_name,
            source_track_index=ctx.source_track_index,
            kit=kit_name,
            style=ctx.detected_style,
            measures=measures,
        )

        return DrumProjectIR(
            title=track_name,
            source=ctx.timeline.source,
            tempo_map=_build_tempo_map(ctx),
            time_signatures=_build_time_signatures(ctx),
            tracks=[track],
            knowledge=_build_knowledge_ref(ctx),
            style_label=ctx.style_label,
            changes=list(ctx.transformations),
            warnings=list(ctx.warnings),
        )


__all__ = ["DrumAssembleStage"]
