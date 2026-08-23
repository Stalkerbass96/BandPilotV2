"""S4.5: Stream separation stage.

Runs after voice assignment (VoicedNote has pitch / quantized onset / duration /
measure number) and before fingering + articulation, so that hand-position
continuity and legato are computed *per track* rather than across the mixed
riff + melody.

The stage:

1. Projects every ``VoicedNote`` into a :class:`SeparationNote` (using the
   *original* duration for the contrast features).
2. Runs :func:`detect_separation` to find confident riff/melody segments.
3. Tags each note's ``stream`` ("lead" | "rhythm") via :func:`assign_stream`,
   then enforces per-``source_index`` consistency so tied fragments of the same
   physical note always stay in the same stream (pure partition).
4. Records a ``stream_separation`` transformation + warnings for traceability.

When no separation is detected, every note keeps the default ``"lead"`` stream
and downstream behaviour is bit-for-bit identical to the single-track path.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from fretpilot.detection.separation import (
    SeparationNote,
    assign_stream,
    detect_separation,
)
from fretpilot.engine.context import PipelineContext, VoicedNote

if TYPE_CHECKING:
    from fretpilot.knowledge.engine import KnowledgeEngine


def _project(note: VoicedNote) -> SeparationNote:
    """Project a ``VoicedNote`` into the detection layer's lightweight view."""
    return SeparationNote(
        source_index=note.source_index,
        pitch=note.pitch,
        start_beat=note.start_beat,
        duration_beats=note.original_duration_beats,
        measure_number=note.measure_number,
        beat_in_measure=note.beat_in_measure,
    )


def _assign_streams(
    notes: list[VoicedNote],
    report,
) -> dict[int, str]:
    """Return a ``source_index → stream`` map, keeping ties in one stream.

    ``assign_stream`` is computed per fragment, but a tied note split across
    measures can straddle a segment boundary (a low-pitched fragment inside a
    separated measure vs. a continuation outside it).  Since pitch is constant
    for one physical note, any ``"rhythm"`` assignment wins on conflict — this
    guarantees the pure-partition invariant (no note split across tracks).
    """
    by_source: dict[int, str] = {}
    for note in notes:
        assigned = assign_stream(note, report)
        previous = by_source.get(note.source_index)
        if previous is None:
            by_source[note.source_index] = assigned
        elif previous == "lead" and assigned == "rhythm":
            by_source[note.source_index] = "rhythm"
    return by_source


def _riff_register_prior(
    tuning,
    low_register_bias: float,
) -> tuple[int, int] | None:
    """Derive the riff-register split window from the tuning + style knowledge.

    The riff sits on the low strings; the split point that separates riff from
    melody must land within the open-pitch span of those strings.  The number
    of "riff strings" is scaled by the KB1 ``low_register_bias``: styles that
    favour the low register (metal) get a wider window, low-register-light
    styles (funk) a narrower one.

    Returns ``(riff_lo, riff_hi)`` (both MIDI pitches, inclusive), or ``None``
    when the tuning provides no string pitches (caller falls back to a purely
    statistical split).
    """
    if tuning is None or not tuning.string_pitches:
        return None

    pitches = tuning.string_pitches  # low → high
    riff_lo = pitches[0]

    if low_register_bias >= 1.2:
        riff_strings = 5
    elif low_register_bias >= 0.9:
        riff_strings = 4
    else:
        riff_strings = 3
    riff_strings = min(riff_strings, len(pitches))

    riff_hi = pitches[riff_strings - 1]
    return riff_lo, riff_hi


class StreamSeparationStage:
    """S4.5: Detect and apply riff/melody stream separation."""

    name = "stream_separation"

    def __init__(self, engine: "KnowledgeEngine | None" = None) -> None:
        self._engine = engine

    def _resolve_low_prior(self, ctx: PipelineContext) -> tuple[int, int] | None:
        """Resolve the riff-register split window for this track.

        Uses the KB1 ``low_register_bias`` for the track's style label when a
        knowledge engine is available; otherwise falls back to a neutral bias.
        """
        bias = 1.0
        if self._engine is not None:
            bias = self._engine.get_low_register_bias(ctx.style_label)
        return _riff_register_prior(ctx.tuning, bias)

    def run(self, ctx: PipelineContext) -> PipelineContext:
        if not ctx.voiced_notes:
            ctx.record_stage(self.name)
            return ctx

        # Out-of-range notes (below the tuning's lowest string) will be routed
        # to voice 2 by the fingering stage; they are NOT part of the riff or
        # the lead and must not skew the split detection (otherwise the split
        # lands inside the riff's register and slices it in half).  Keep them
        # in the "lead" stream (default) so they end up in the lead track's
        # voice 2, matching the pre-separation behaviour.
        min_pitch = 40
        if ctx.tuning is not None:
            min_pitch = ctx.tuning.min_pitch

        in_range = [n for n in ctx.voiced_notes if n.pitch >= min_pitch]
        projections = [_project(n) for n in in_range]
        low_prior = self._resolve_low_prior(ctx)
        report = detect_separation(projections, low_prior=low_prior)
        ctx.separation = report

        stream_by_source = _assign_streams(ctx.voiced_notes, report)
        ctx.voiced_notes = [
            replace(
                note,
                stream=(
                    "lead"
                    if note.pitch < min_pitch
                    else stream_by_source[note.source_index]
                ),
            )
            for note in ctx.voiced_notes
        ]

        # Traceability: one transformation per confident segment.
        for segment in report.segments:
            ctx.add_transformation(
                stage="stream_separation",
                source_note_index=-1,  # segment scope — no single source note
                before={
                    "measures": [segment.start_measure, segment.end_measure],
                    "tracks": 1,
                },
                after={
                    "tracks": 2,
                    "split_pitch": segment.split_pitch,
                    "lead": segment.high_note_count,
                    "rhythm": segment.low_note_count,
                },
                confidence=segment.confidence,
                reason=segment.reason,
            )

        ctx.warnings.extend(report.warnings)
        ctx.record_stage(self.name)
        return ctx


__all__ = ["StreamSeparationStage"]
