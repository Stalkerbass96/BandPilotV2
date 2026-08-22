"""S4: Pattern detection stage.

Classifies each measure as "beat" or "fill" based on note density and
distribution. Also detects the overall drum style.

Detection heuristics:
  - **Fill**: high tom density, many different pieces in a short span,
    often precedes a section change.
  - **Beat**: consistent kick/snare pattern, repetitive hi-hat, low tom usage.
  - **Transition**: sparse measure between beat and fill.
"""

from __future__ import annotations

from collections import Counter

from fretpilot.engine.drum_context import (
    DrumPipelineContext,
    MappedNote,
    PatternNote,
)

# ─── Thresholds ───

_TOM_DENSITY_FILL_THRESHOLD = 0.3  # >30% toms → likely fill
_PIECE_VARIETY_FILL_THRESHOLD = 6  # >6 distinct pieces in one measure → fill
_KICK_SNARE_BEAT_RATIO = 0.3  # >=30% kick+snare → likely beat
_BEAT_REPETITION_MIN_MEASURES = 4  # need at least 4 measures to detect repetition


def _group_by_measure(
    notes: list[MappedNote],
) -> dict[int, list[MappedNote]]:
    """Group mapped notes by measure number."""
    groups: dict[int, list[MappedNote]] = {}
    for note in notes:
        groups.setdefault(note.measure_number, []).append(note)
    return groups


def _classify_measure(notes: list[MappedNote]) -> str:
    """Classify a single measure as "beat", "fill", or "transition".

    Args:
        notes: All MappedNotes in this measure.

    Returns:
        The pattern label.
    """
    if not notes:
        return "transition"

    total = len(notes)
    piece_counts = Counter(n.piece for n in notes)
    distinct_pieces = len(piece_counts)

    # Tom density: fraction of notes that are toms.
    tom_count = sum(
        count for piece, count in piece_counts.items() if piece.startswith("tom_")
    )
    tom_density = tom_count / total

    # Kick + snare ratio: backbone of a beat pattern.
    kick_snare = piece_counts.get("kick", 0) + piece_counts.get("snare", 0)
    kick_snare_ratio = kick_snare / total

    # Fill signals: high tom density or many distinct pieces.
    if tom_density >= _TOM_DENSITY_FILL_THRESHOLD:
        return "fill"
    if distinct_pieces > _PIECE_VARIETY_FILL_THRESHOLD and tom_count > 0:
        return "fill"

    # Beat signals: consistent kick/snare backbone.
    if kick_snare_ratio >= _KICK_SNARE_BEAT_RATIO:
        return "beat"

    # If there are a few notes but no strong signal, it's a transition.
    if total <= 3:
        return "transition"

    return "beat"


def _detect_style(measure_patterns: dict[int, str]) -> str:
    """Detect the overall drum style from measure pattern distribution.

    This is a simple heuristic; the knowledge base can refine it later.

    Args:
        measure_patterns: Mapping of measure number → pattern label.

    Returns:
        A style label: "metal", "rock", "pop", "funk", or "unknown".
    """
    if not measure_patterns:
        return "unknown"

    fill_count = sum(1 for p in measure_patterns.values() if p == "fill")
    beat_count = sum(1 for p in measure_patterns.values() if p == "beat")
    total = len(measure_patterns)

    fill_rate = fill_count / total

    # High fill rate → metal or funk.
    if fill_rate > 0.25:
        return "metal"
    if fill_rate > 0.15:
        return "funk"
    if beat_count / total > 0.7:
        return "rock"
    return "pop"


class PatternDetectStage:
    """S4: Classify measures as beat vs fill and detect drum style.

    Reads ``ctx.mapped_notes`` (output of S3 DrumMap) and produces
    ``ctx.pattern_notes`` with per-measure pattern classification.
    Also sets ``ctx.measure_patterns`` and ``ctx.detected_style``.
    """

    name = "pattern_detect"

    def run(self, ctx: DrumPipelineContext) -> DrumPipelineContext:
        if not ctx.mapped_notes:
            ctx.record_stage(self.name)
            return ctx

        by_measure = _group_by_measure(ctx.mapped_notes)

        # Classify each measure.
        for measure_number in sorted(by_measure):
            notes = by_measure[measure_number]
            pattern = _classify_measure(notes)
            ctx.measure_patterns[measure_number] = pattern

        # Detect overall style.
        ctx.detected_style = _detect_style(ctx.measure_patterns)
        if ctx.style_label == "unknown":
            ctx.style_label = ctx.detected_style

        # Build PatternNotes.
        for note in ctx.mapped_notes:
            pattern = ctx.measure_patterns.get(note.measure_number, "unknown")
            ctx.pattern_notes.append(
                PatternNote(
                    mapped=note,
                    measure_pattern=pattern,
                    is_fill=(pattern == "fill"),
                )
            )

        ctx.record_stage(self.name)
        return ctx


__all__ = ["PatternDetectStage"]
