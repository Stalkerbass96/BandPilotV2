"""S5: Velocity normalization stage.

Normalizes velocities per drum piece and detects ghost notes and accent
notes based on statistical thresholds.

Detection heuristics:
  - **Ghost note**: velocity < 30% of the piece's average velocity.
  - **Accent note**: velocity > 90th percentile of the piece's velocities.
  - **Normal**: everything else.

Normalization maps each piece's velocity range to a consistent scale,
preserving relative dynamics while ensuring cross-piece balance.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import mean

from fretpilot.engine.drum_context import (
    DrumPipelineContext,
    PatternNote,
    VelocityNote,
)

# ─── Thresholds ───

_GHOST_RATIO = 0.30  # <30% of average → ghost
_ACCENT_PERCENTILE = 90  # >90th percentile → accent
_MIN_NOTES_FOR_STATS = 3  # need at least 3 notes for meaningful statistics


def _percentile(values: list[int], pct: int) -> float:
    """Compute the pct-th percentile of a list of integers.

    Uses linear interpolation between closest ranks.
    """
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    rank = (pct / 100) * (len(sorted_vals) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_vals) - 1)
    frac = rank - lower
    return sorted_vals[lower] + frac * (sorted_vals[upper] - sorted_vals[lower])


def _compute_piece_stats(
    notes: list[PatternNote],
) -> dict[str, dict[str, float]]:
    """Compute per-piece velocity statistics.

    Returns:
        A dict mapping piece name → {"avg": float, "p90": float}.
    """
    by_piece: dict[str, list[int]] = defaultdict(list)
    for note in notes:
        by_piece[note.mapped.piece].append(note.mapped.velocity)

    stats: dict[str, dict[str, float]] = {}
    for piece, velocities in by_piece.items():
        if len(velocities) >= _MIN_NOTES_FOR_STATS:
            stats[piece] = {
                "avg": mean(velocities),
                "p90": _percentile(velocities, _ACCENT_PERCENTILE),
            }
        else:
            # Too few notes for statistics; use flat values.
            avg = mean(velocities) if velocities else 64.0
            stats[piece] = {"avg": avg, "p90": avg}
    return stats


def _classify_velocity(
    velocity: int,
    piece_stats: dict[str, float],
) -> str:
    """Classify a single velocity as "ghost", "accent", or "normal".

    Args:
        velocity: The note's MIDI velocity.
        piece_stats: {"avg": float, "p90": float} for this piece.

    Returns:
        The technique label.
    """
    avg = piece_stats["avg"]
    p90 = piece_stats["p90"]

    if avg > 0 and velocity < avg * _GHOST_RATIO:
        return "ghost"
    if velocity > p90:
        return "accent"
    return "normal"


def _normalize_velocity(
    velocity: int,
    piece_avg: float,
    global_avg: float,
) -> int:
    """Normalize a velocity to balance cross-piece dynamics.

    Scales the velocity by the ratio of global average to piece average,
    clamped to the valid MIDI range [1, 127].

    Args:
        velocity: The original velocity.
        piece_avg: Average velocity for this piece.
        global_avg: Average velocity across all pieces.

    Returns:
        The normalized velocity (1–127).
    """
    if piece_avg <= 0:
        return velocity
    # Scale toward the global average, preserving relative dynamics.
    scale = global_avg / piece_avg
    normalized = round(velocity * scale)
    return max(1, min(127, normalized))


class VelocityStage:
    """S5: Normalize velocities per drum piece and detect ghost/accent notes.

    Reads ``ctx.pattern_notes`` (output of S4 PatternDetect) and produces
    ``ctx.velocity_notes`` with normalized velocities and technique labels.
    """

    name = "velocity"

    def run(self, ctx: DrumPipelineContext) -> DrumPipelineContext:
        if not ctx.pattern_notes:
            ctx.record_stage(self.name)
            return ctx

        # Compute per-piece statistics.
        piece_stats = _compute_piece_stats(ctx.pattern_notes)

        # Compute global average across all pieces.
        all_avgs = [s["avg"] for s in piece_stats.values()]
        global_avg = mean(all_avgs) if all_avgs else 64.0

        for note in ctx.pattern_notes:
            piece = note.mapped.piece
            stats = piece_stats.get(piece, {"avg": 64.0, "p90": 100.0})

            original_velocity = note.mapped.velocity
            technique = _classify_velocity(original_velocity, stats)
            normalized = _normalize_velocity(
                original_velocity, stats["avg"], global_avg
            )

            # Record transformation if velocity changed.
            if normalized != original_velocity:
                ctx.add_transformation(
                    stage="velocity_normalize",
                    source_note_index=note.mapped.source_index,
                    before={"velocity": original_velocity, "technique": "normal"},
                    after={"velocity": normalized, "technique": technique},
                    confidence=0.9,
                    reason=f"normalize {piece} velocity ({technique})",
                )

            ctx.velocity_notes.append(
                VelocityNote(
                    pattern=note,
                    original_velocity=original_velocity,
                    normalized_velocity=normalized,
                    technique=technique,
                )
            )

        ctx.record_stage(self.name)
        return ctx


__all__ = ["VelocityStage"]
