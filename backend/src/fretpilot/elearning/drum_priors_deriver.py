"""Drum KB2 priors deriver — reverse-engineers sticking priors from statistics.

Converts :class:`DrumStyleStats` into :class:`DrumDerivedPriors` using
statistical mapping.  Each statistical measure maps to a prior via a simple
ratio formula, clamped to ``[0.3, 2.0]`` for weight-like priors and to
``[0.0, 1.0]`` for rate-like priors.

The payload keys match the hand-authored ``drum_kb2_sticking.json`` entries:

  | Statistic               | Priors key           | Formula                               |
  |-------------------------|----------------------|---------------------------------------|
  | right_hand_rate         | right_hand_bias      | clamp(rate / 0.5, 0.3, 2.0)           |
  | double_stroke_rate      | double_stroke_rate   | clamp(rate, 0.0, 1.0)                 |
  | flam_rate               | flam_rate            | clamp(rate, 0.0, 1.0)                 |
  | hand_switch_pattern     | hand_switch_pattern  | dominant 4-letter pattern              |
  | avg_inter_hit_gap       | single_stroke_speed  | clamp(0.25 / gap, 0.3, 2.0)          |
"""

from __future__ import annotations

import logging
from typing import Any

from fretpilot.elearning.drum_models import DrumDerivedPriors, DrumStyleStats

logger = logging.getLogger("fretpilot.elearning.drum_priors_deriver")

# Neutral baseline rates for ratio mapping.
_RIGHT_HAND_BASELINE = 0.5  # balanced hands
# Reference inter-hit gap (beats) for 16th-note single strokes at ~120bpm.
_REFERENCE_GAP_BEATS = 0.25

# Weight-like priors clamp range.
_WEIGHT_RANGE: tuple[float, float] = (0.3, 2.0)


class DrumPriorsDeriver:
    """Derives drum KB2 sticking priors from drum statistics."""

    # drum_kb2_sticking knowledge_id mapping per style (matches the
    # hand-authored drum_kb2_sticking.json entries).
    STYLE_TO_KB_ID: dict[str, str] = {
        "metal": "drum_kb2-metal-sticking",
        "rock": "drum_kb2-rock-sticking",
        "pop": "drum_kb2-pop-sticking",
        "funk": "drum_kb2-funk-sticking",
        "jazz": "drum_kb2-jazz-sticking",
    }

    # Minimum sample counts for meaningful confidence.
    _MIN_SAMPLES_FOR_CONFIDENCE = 5
    _MIN_NOTES_FOR_CONFIDENCE = 50

    def derive(
        self,
        style_stats: dict[str, DrumStyleStats],
        source_ids_map: dict[str, list[str]],
    ) -> list[DrumDerivedPriors]:
        """Derive empirical sticking priors from per-style statistics.

        Args:
            style_stats: Mapping from style label to :class:`DrumStyleStats`.
            source_ids_map: Mapping from style label to list of source tab
                file paths (for provenance tracking).

        Returns:
            A list of :class:`DrumDerivedPriors`, one per style with a known
            drum KB2 knowledge_id.  Styles without a mapping (e.g. ``unknown``)
            are skipped.
        """
        results: list[DrumDerivedPriors] = []

        for style, stats in style_stats.items():
            kb_id = self.STYLE_TO_KB_ID.get(style)
            if kb_id is None:
                logger.debug("No drum KB2 mapping for style %r; skipping", style)
                continue
            if stats.sample_count < self._MIN_SAMPLES_FOR_CONFIDENCE:
                logger.info(
                    "Style %r has only %d sample(s) (< %d); skipping derivation "
                    "to avoid replacing hand-authored priors with noise",
                    style, stats.sample_count, self._MIN_SAMPLES_FOR_CONFIDENCE,
                )
                continue

            payload: dict[str, Any] = {
                "right_hand_bias": self._derive_right_hand_bias(stats),
                "double_stroke_rate": round(
                    max(0.0, min(1.0, stats.double_stroke_rate)), 4
                ),
                "flam_rate": round(max(0.0, min(1.0, stats.flam_rate)), 4),
                "hand_switch_pattern": stats.hand_switch_pattern or "RLRL",
                "single_stroke_speed": self._derive_single_stroke_speed(stats),
            }

            source_ids = source_ids_map.get(style, [])
            confidence = self._compute_confidence(stats.sample_count, stats.total_notes)

            stats_snapshot: dict[str, Any] = {
                "hit_density": stats.hit_density,
                "avg_inter_hit_gap_beats": stats.avg_inter_hit_gap_beats,
                "velocity_mean": stats.velocity_mean,
                "accent_rate": stats.accent_rate,
                "ghost_note_rate": stats.ghost_note_rate,
                "right_hand_rate": stats.right_hand_rate,
                "sample_count": stats.sample_count,
                "total_notes": stats.total_notes,
                "top_pieces": dict(list(stats.piece_distribution.items())[:6]),
                "quarter_or_shorter_rate": stats.quarter_or_shorter_rate,
                "voice_two_rate": stats.voice_two_rate,
                "foot_voice_two_rate": stats.foot_voice_two_rate,
                "top_written_durations": dict(
                    list(stats.duration_distribution.items())[:6]
                ),
            }

            derived = DrumDerivedPriors(
                style_label=style,
                knowledge_id=kb_id,
                payload=payload,
                source_ids=list(source_ids),
                confidence=confidence,
                derivation_method="statistical_mapping",
                stats_snapshot=stats_snapshot,
            )
            results.append(derived)
            logger.info(
                "Derived drum priors for %s (kb_id=%s): %s (confidence=%.2f)",
                style, kb_id, payload, confidence,
            )

        return results

    # ─── Individual prior derivation methods ───

    def _derive_right_hand_bias(self, stats: DrumStyleStats) -> float:
        """right_hand_bias = clamp(rate / 0.5, 0.3, 2.0).

        A rate above 0.5 (right-hand-led) raises the bias above 1.0.
        """
        ratio = stats.right_hand_rate / _RIGHT_HAND_BASELINE if _RIGHT_HAND_BASELINE else 1.0
        return self._clamp(ratio)

    def _derive_single_stroke_speed(self, stats: DrumStyleStats) -> float:
        """single_stroke_speed = clamp(0.25 / avg_gap, 0.3, 2.0).

        A smaller inter-hit gap (faster playing) yields a higher speed prior.
        Falls back to 1.0 when no gap data is available.
        """
        gap = stats.avg_inter_hit_gap_beats
        if gap <= 0:
            return 1.0
        ratio = _REFERENCE_GAP_BEATS / gap
        return self._clamp(ratio)

    def _compute_confidence(self, sample_count: int, total_notes: int) -> float:
        """Compute confidence based on sample size (same curve as guitar).

        Saturating function:
          - 0 samples → 0.0
          - >= 5 samples AND >= 50 notes → 0.8+
          - Saturates at 1.0 for >= 20 samples AND >= 200 notes.
        """
        if sample_count <= 0 or total_notes <= 0:
            return 0.0

        sample_factor = min(1.0, sample_count / 20.0)
        note_factor = min(1.0, total_notes / 200.0)

        if sample_count < self._MIN_SAMPLES_FOR_CONFIDENCE:
            base = 0.3
        elif total_notes < self._MIN_NOTES_FOR_CONFIDENCE:
            base = 0.5
        else:
            base = 0.7

        confidence = base + 0.3 * (sample_factor + note_factor) / 2.0
        return round(min(1.0, confidence), 4)

    # ─── Utility ───

    def _clamp(self, value: float) -> float:
        """Clamp a weight to ``[_WEIGHT_RANGE[0], _WEIGHT_RANGE[1]]``."""
        lo, hi = _WEIGHT_RANGE
        return round(max(lo, min(hi, value)), 6)


__all__ = ["DrumPriorsDeriver"]
