"""S2: Measure split stage.

Computes measure boundaries from the tempo/time-signature map, then splits
notes that cross measure boundaries into tied fragments.
"""

from __future__ import annotations

from fretpilot.engine.context import MeasureBoundary, PipelineContext, SplitNote

_EPSILON = 1e-8


def _compute_measure_boundaries(
    ctx: PipelineContext,
    end_beat: float,
) -> list[MeasureBoundary]:
    """Build measure boundaries from the timeline's time-signature events."""
    signatures = sorted(ctx.timeline.time_signature_events, key=lambda e: e.beat)
    if not signatures:
        raise ValueError("Timeline must contain at least one time signature.")

    boundaries: list[MeasureBoundary] = []
    cursor = 0.0
    sig_index = 0
    current = signatures[0]
    measure_number = 1
    required_end = max(end_beat, 0.0)

    while cursor < required_end - _EPSILON or not boundaries:
        sig_index, current = _advance_signature(signatures, sig_index, cursor)
        measure_length = current.numerator * (4.0 / current.denominator)
        if measure_length <= 0:
            raise ValueError("Time signature produced a non-positive measure length.")
        natural_end = cursor + measure_length
        measure_end = _clip_at_next_change(
            signatures, sig_index, cursor, natural_end, measure_number, ctx
        )
        boundaries.append(
            MeasureBoundary(
                number=measure_number,
                start_beat=cursor,
                end_beat=measure_end,
                numerator=current.numerator,
                denominator=current.denominator,
            )
        )
        cursor = measure_end
        measure_number += 1

    return boundaries


def _advance_signature(signatures, sig_index: int, cursor: float):
    """Advance to the time signature active at cursor beat."""
    current = signatures[sig_index]
    while (
        sig_index + 1 < len(signatures)
        and signatures[sig_index + 1].beat <= cursor + _EPSILON
    ):
        sig_index += 1
        current = signatures[sig_index]
    return sig_index, current


def _clip_at_next_change(signatures, sig_index, cursor, natural_end, number, ctx):
    """Clip a measure end at the next time-signature change if needed."""
    measure_end = natural_end
    if sig_index + 1 < len(signatures):
        next_change = signatures[sig_index + 1].beat
        if next_change > cursor + _EPSILON and next_change < natural_end - _EPSILON:
            measure_end = next_change
            ctx.warnings.append(
                f"Time-signature change inside measure {number}; truncated at beat {next_change:.4f}."
            )
    return measure_end


def _find_measure(boundaries: list[MeasureBoundary], beat: float) -> MeasureBoundary:
    """Return the measure boundary containing the given beat."""
    for boundary in boundaries:
        if boundary.start_beat - _EPSILON <= beat < boundary.end_beat - _EPSILON:
            return boundary
    return boundaries[-1]


def _split_note_across_measures(
    note, boundaries: list[MeasureBoundary]
) -> list[tuple[MeasureBoundary, float, float]]:
    """Split a quantized note into (measure, start, duration) fragments."""
    fragments: list[tuple[MeasureBoundary, float, float]] = []
    cursor = note.quantized_start_beat
    end_beat = note.quantized_start_beat + note.quantized_duration_beats
    while cursor < end_beat - _EPSILON:
        measure = _find_measure(boundaries, cursor)
        fragment_end = min(end_beat, measure.end_beat)
        fragments.append((measure, cursor, fragment_end - cursor))
        cursor = fragment_end
    return fragments


def _build_split_note(note, measure, start, duration, frag_idx, frag_count) -> SplitNote:
    """Construct a SplitNote fragment from a quantized note."""
    return SplitNote(
        source_index=note.source_index,
        pitch=note.pitch,
        velocity=note.velocity,
        start_beat=start,
        duration_beats=duration,
        measure_number=measure.number,
        beat_in_measure=start - measure.start_beat,
        tie_in=frag_idx > 0,
        tie_out=frag_idx < frag_count - 1,
        original_start_beat=note.original_start_beat,
        original_duration_beats=note.original_duration_beats,
    )


class MeasureSplitStage:
    """S2: Split notes at measure boundaries and compute measure structure."""

    name = "measure_split"

    def run(self, ctx: PipelineContext) -> PipelineContext:
        if not ctx.quantized_notes:
            ctx.record_stage(self.name)
            return ctx

        max_end = max(
            n.quantized_start_beat + n.quantized_duration_beats
            for n in ctx.quantized_notes
        )
        ctx.measures = _compute_measure_boundaries(ctx, max_end)

        for note in ctx.quantized_notes:
            fragments = _split_note_across_measures(note, ctx.measures)
            if not fragments:
                continue
            for frag_idx, (measure, start, duration) in enumerate(fragments):
                ctx.split_notes.append(
                    _build_split_note(note, measure, start, duration, frag_idx, len(fragments))
                )

        ctx.record_stage(self.name)
        return ctx


__all__ = ["MeasureSplitStage"]
