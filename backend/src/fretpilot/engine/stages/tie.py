"""S3: Tie / legato identification stage.

Identifies consecutive same-pitch notes that are legato candidates
(hammer_on / pull_off / slide). Since fingering is not yet assigned (S5),
this stage works at the pitch level and marks candidates; S6 confirms
using fingering data.
"""

from __future__ import annotations

from fretpilot.engine.context import PipelineContext

_EPSILON = 1e-8
_LEGATO_MAX_GAP_BEATS = 0.5  # notes must be within this gap to be legato candidates


def _are_legato_candidates(prev_note, curr_note) -> bool:
    """Return True if two sequential notes could be a legato pair."""
    if prev_note.source_index == curr_note.source_index:
        return False  # same source note (tied fragments)
    if prev_note.pitch != curr_note.pitch:
        return False
    gap = curr_note.start_beat - (prev_note.start_beat + prev_note.duration_beats)
    if gap > _LEGATO_MAX_GAP_BEATS + _EPSILON:
        return False
    if gap < -_EPSILON:
        return False  # overlapping, not legato
    return True


def _mark_legato_in_sequence(notes: list) -> None:
    """Mark legato candidates in a time-ordered note sequence (in place)."""
    for i in range(1, len(notes)):
        if _are_legato_candidates(notes[i - 1], notes[i]):
            notes[i].legato_candidate = True


class TieStage:
    """S3: Identify tie/legato relationships between consecutive notes."""

    name = "tie"

    def run(self, ctx: PipelineContext) -> PipelineContext:
        if not ctx.split_notes:
            ctx.record_stage(self.name)
            return ctx

        # Group notes by source_index to handle tied fragments correctly,
        # then process the sequence in time order.
        sorted_notes = sorted(
            ctx.split_notes,
            key=lambda n: (n.start_beat, n.pitch, n.source_index),
        )

        # Mark legato candidates only on first fragments (tie_in=False)
        # to avoid marking tied continuations.
        first_fragments = [n for n in sorted_notes if not n.tie_in]
        _mark_legato_in_sequence(first_fragments)

        # Propagate legato_candidate flag to tied fragments of the same source.
        legato_sources = {
            n.source_index for n in first_fragments if n.legato_candidate
        }
        for note in ctx.split_notes:
            if note.source_index in legato_sources:
                note.legato_candidate = True

        ctx.record_stage(self.name)
        return ctx


__all__ = ["TieStage"]
