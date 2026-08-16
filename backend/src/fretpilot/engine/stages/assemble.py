"""S7: IR assembly stage.

Assembles the final GuitarProjectIR from all pipeline intermediate state.
Collects every Transformation, builds measure/track/note structures, and
pins the knowledge snapshot reference.
"""

from __future__ import annotations

from pathlib import Path

from fretpilot.engine.context import (
    ArticulationDecision,
    FingeredNote,
    PipelineContext,
)
from fretpilot.ir.models import (
    GuitarMeasure,
    GuitarNoteEvent,
    GuitarProjectIR,
    GuitarTrackIR,
    IRArticulation,
    IRFingering,
    IRKnowledgeReference,
    IRTempoEvent,
    IRTimeSignatureEvent,
    NoteConfidence,
    PerformanceTiming,
    ScoreTiming,
)
from fretpilot.midi.models import NormalizedTimeline


def _build_note_event(
    note: FingeredNote,
    decisions: list[ArticulationDecision],
    event_id: str,
) -> GuitarNoteEvent:
    """Construct a GuitarNoteEvent from a FingeredNote + articulation decisions."""
    articulations = [
        IRArticulation(
            type=d.type,
            confidence=d.confidence,
            reason=d.reason,
            source_note_id=d.source_note_id,
            parameters=dict(d.parameters),
        )
        for d in decisions
        if d.note_index == note.source_index
    ]
    rhythm_confidence = 1.0  # computed during quantize; simplified here
    return GuitarNoteEvent(
        id=event_id,
        source_note_index=note.source_index,
        pitch=note.pitch,
        score=ScoreTiming(
            start_beat=note.start_beat,
            duration_beats=note.duration_beats,
            measure_number=note.measure_number,
            beat_in_measure=note.beat_in_measure,
            voice=note.voice,
            tie_in=note.tie_in,
            tie_out=note.tie_out,
        ),
        performance=PerformanceTiming(
            source_start_beat=note.original_start_beat,
            source_duration_beats=note.original_duration_beats,
            velocity=note.velocity,
        ),
        fingering=IRFingering(
            string=note.string,
            fret=note.fret,
            fretting_digit=note.fretting_digit,
            hand_position=note.hand_position,
        ),
        articulations=articulations,
        confidence=NoteConfidence(
            rhythm=rhythm_confidence,
            fingering=note.fingering_confidence,
            articulation=max((d.confidence for d in articulations), default=None),
        ),
        source_note_origin="midi",
    )


def _build_measures(ctx: PipelineContext, stream: str) -> list[GuitarMeasure]:
    """Build the GuitarMeasure list for a single stream ("lead" | "rhythm").

    Every measure boundary is emitted (even empty ones) so that all tracks
    share the same measure structure; notes are filtered by ``stream``.
    """
    measures_map: dict[int, GuitarMeasure] = {}
    for boundary in ctx.measures:
        measures_map[boundary.number] = GuitarMeasure(
            number=boundary.number,
            start_beat=boundary.start_beat,
            duration_beats=boundary.end_beat - boundary.start_beat,
            numerator=boundary.numerator,
            denominator=boundary.denominator,
        )

    event_counter: dict[int, int] = {}
    for note in ctx.fingered_notes:
        if note.stream != stream:
            continue
        measure = measures_map.get(note.measure_number)
        if measure is None:
            continue
        count = event_counter.get(note.source_index, 0)
        event_counter[note.source_index] = count + 1
        base_id = f"n-{note.source_index + 1:05d}"
        event_id = base_id if count == 0 else f"{base_id}-{count + 1}"
        measure.events.append(
            _build_note_event(note, ctx.articulation_decisions, event_id)
        )

    for measure in measures_map.values():
        measure.events.sort(
            key=lambda e: (e.score.start_beat, e.score.voice, e.pitch, e.id)
        )
    return list(measures_map.values())


def _resolve_tuning(ctx: PipelineContext) -> tuple[list[int], int]:
    """Return ``(tuning_pitches, fret_count)`` from the context or standard."""
    if ctx.tuning is not None:
        return ctx.tuning.string_pitches, 24
    from fretpilot.guitar.instrument import STANDARD_TUNING

    return list(STANDARD_TUNING.open_pitches), STANDARD_TUNING.fret_count


def _build_track(
    ctx: PipelineContext,
    measures: list[GuitarMeasure],
    *,
    track_id: str,
    name: str,
    role: str,
) -> GuitarTrackIR:
    """Build a :class:`GuitarTrackIR` with explicit identity/role overrides."""
    tuning_pitches, fret_count = _resolve_tuning(ctx)
    return GuitarTrackIR(
        id=track_id,
        name=name,
        source_track_index=ctx.source_track_index,
        role=role,
        tuning=tuning_pitches,
        fret_count=fret_count,
        measures=measures,
    )


def _build_knowledge_ref(ctx: PipelineContext) -> IRKnowledgeReference:
    """Build the IRKnowledgeReference pinning the used knowledge snapshot."""
    return IRKnowledgeReference(
        snapshot_version=ctx.knowledge.snapshot_version,
        kb_versions=ctx.knowledge.kb_versions,
        entry_ids=ctx.knowledge.entry_ids(),
    )


def _build_tempo_map(timeline: NormalizedTimeline) -> list[IRTempoEvent]:
    """Convert timeline tempo events to IR tempo events."""
    return [IRTempoEvent(beat=e.beat, bpm=e.bpm) for e in timeline.tempo_events]


def _build_time_signatures(timeline: NormalizedTimeline) -> list[IRTimeSignatureEvent]:
    """Convert timeline time-signature events to IR events."""
    return [
        IRTimeSignatureEvent(beat=e.beat, numerator=e.numerator, denominator=e.denominator)
        for e in timeline.time_signature_events
    ]


class AssembleStage:
    """S7: Assemble the final GuitarProjectIR."""

    name = "assemble"

    def run(self, ctx: PipelineContext) -> PipelineContext:
        ctx.record_stage(self.name)
        return ctx

    def build_ir(self, ctx: PipelineContext) -> GuitarProjectIR:
        """Assemble the GuitarProjectIR from pipeline context.

        Single track by default; when ``ctx.separation`` reports detected
        segments, produce ``[Lead, Rhythm]`` (Lead first, original track id,
        Rhythm second with ``-rhythm`` suffix).
        """
        report = ctx.separation
        if report is not None and report.detected:
            tracks = [
                _build_track(
                    ctx,
                    _build_measures(ctx, "lead"),
                    track_id=ctx.track_id,
                    name=f"{ctx.track.name} - Lead",
                    role="lead",
                ),
                _build_track(
                    ctx,
                    _build_measures(ctx, "rhythm"),
                    track_id=f"{ctx.track_id}-rhythm",
                    name=f"{ctx.track.name} - Rhythm",
                    role="rhythm",
                ),
            ]
        else:
            tracks = [
                _build_track(
                    ctx,
                    _build_measures(ctx, "lead"),
                    track_id=ctx.track_id,
                    name=ctx.track.name,
                    role=ctx.track_role,
                )
            ]

        return GuitarProjectIR(
            title=Path(ctx.timeline.source).stem or "Untitled",
            source=ctx.timeline.source,
            tempo_map=_build_tempo_map(ctx.timeline),
            time_signatures=_build_time_signatures(ctx.timeline),
            tracks=tracks,
            knowledge=_build_knowledge_ref(ctx),
            style_label=ctx.style_label,
            midi_fidelity=ctx.midi_fidelity,
            degraded_mode=ctx.degraded_mode,
            changes=list(ctx.transformations),
            warnings=list(ctx.warnings),
        )


__all__ = ["AssembleStage"]
