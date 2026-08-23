"""S7: Drum notation cleanup stage.

Cleans up the notation for export:
  - Remove redundant hits (same piece, same tick — likely double-triggered).
  - Optimize rest placement (mark positions where rests can be implicit).
  - Detect repeated patterns that could use repeat signs (future enhancement).

This is the drum equivalent of the guitar articulation stage (S6 in
FretPilot), but focused on notation clarity rather than playing technique.
"""

from __future__ import annotations

from fretpilot.engine.drum_context import (
    DrumPipelineContext,
    NotatedNote,
    StickedNote,
)

# ─── Thresholds ───

_REduNDANT_TICK_EPSILON = 1e-6  # same tick tolerance (in beats)
_REST_GAP_THRESHOLD = 1.0  # gaps >= 1 beat → mark rest-optimized


def _find_redundant_hits(
    notes: list[StickedNote],
) -> set[int]:
    """Identify indices of redundant hits.

    A hit is redundant if another hit on the same piece occurs at the exact
    same tick (within epsilon). The first occurrence is kept; subsequent
    duplicates are marked redundant.

    Args:
        notes: StickedNotes ordered by start beat.

    Returns:
        Set of indices to mark as redundant.
    """
    seen: dict[tuple[str, float], bool] = {}
    redundant: set[int] = set()

    for i, note in enumerate(notes):
        piece = note.velocity.pattern.mapped.piece
        start = note.velocity.pattern.mapped.start_beat
        key = (piece, round(start, 6))
        if key in seen:
            redundant.add(i)
        else:
            seen[key] = True

    return redundant


def _find_rest_positions(
    notes: list[StickedNote],
) -> set[int]:
    """Identify note indices that follow a significant rest gap.

    These positions can benefit from optimized rest placement (implicit
    rests rather than explicit rest notation).

    Args:
        notes: StickedNotes ordered by start beat.

    Returns:
        Set of indices where rest optimization applies.
    """
    rest_positions: set[int] = set()
    for i in range(1, len(notes)):
        prev_end = (
            notes[i - 1].velocity.pattern.mapped.start_beat
            + notes[i - 1].velocity.pattern.mapped.duration_beats
        )
        curr_start = notes[i].velocity.pattern.mapped.start_beat
        gap = curr_start - prev_end
        if gap >= _REST_GAP_THRESHOLD:
            rest_positions.add(i)
    return rest_positions


class DrumNotationStage:
    """S7: Clean up drum notation for export.

    Reads ``ctx.sticked_notes`` (output of S6 Sticking) and produces
    ``ctx.notated_notes`` with redundant hits flagged and rest positions
    optimized.
    """

    name = "drum_notation"

    def run(self, ctx: DrumPipelineContext) -> DrumPipelineContext:
        if not ctx.sticked_notes:
            ctx.record_stage(self.name)
            return ctx

        # Sort by start beat for consistent processing.
        sorted_notes = sorted(
            ctx.sticked_notes,
            key=lambda n: n.velocity.pattern.mapped.start_beat,
        )

        redundant = _find_redundant_hits(sorted_notes)
        rest_positions = _find_rest_positions(sorted_notes)

        for i, note in enumerate(sorted_notes):
            is_redundant = i in redundant
            rest_optimized = i in rest_positions

            if is_redundant:
                ctx.add_transformation(
                    stage="drum_notation_redundant",
                    source_note_index=note.velocity.pattern.mapped.source_index,
                    before={"redundant": False},
                    after={"redundant": True},
                    confidence=1.0,
                    reason="duplicate hit on same piece at same tick",
                )

            ctx.notated_notes.append(
                NotatedNote(
                    sticked=note,
                    is_redundant=is_redundant,
                    rest_optimized=rest_optimized,
                )
            )

        if redundant:
            ctx.warnings.append(
                f"Removed {len(redundant)} redundant drum hits "
                f"(same piece, same tick)."
            )

        ctx.record_stage(self.name)
        return ctx


__all__ = ["DrumNotationStage"]
