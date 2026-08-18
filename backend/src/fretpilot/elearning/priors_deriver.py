"""P1-2: KB2 priors deriver — reverse-engineers priors from statistics.

Converts :class:`StyleStats` into :class:`DerivedPriors` using statistical
mapping.  Each statistical measure maps to a prior weight via a simple
ratio formula, then clamped to ``[0.3, 2.0]`` to avoid extreme values.

Mapping table (from ARCH doc §4.4):

  | Statistic                | Priors key                  | Formula                              |
  |--------------------------|-----------------------------|--------------------------------------|
  | open_string_rate         | open_string_bias            | clamp(rate / 0.15, 0.3, 2.0)        |
  | hand_position change rate| hand_position_stability     | clamp(1/(1+change_rate), 0.3, 2.0)  |
  | top chord shape freq     | shape_reuse                 | clamp(freq / 0.1, 0.3, 2.0)         |
  | note_overlap_rate        | note_overlap                | clamp(rate, 0.3, 2.0)               |
  | staccato_rate            | staccato                    | clamp(rate / 0.15, 0.3, 2.0)        |
  | avg_string_skip          | string_skip_penalty         | clamp(1 + skip * 0.15, 0.3, 2.0)    |

All derived priors are tagged ``source_type = "empirical"``.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from fretpilot.elearning.models import DerivedPriors, StyleStats

logger = logging.getLogger("fretpilot.elearning.priors_deriver")

# Neutral baseline rates (from ARCH doc §4.4).
_OPEN_STRING_BASELINE = 0.15
_STACCATO_BASELINE = 0.15
_SHAPE_REUSE_BASELINE = 0.10
_STRING_SKIP_WEIGHT = 0.15


class PriorsDeriver:
    """Derives KB2 priors from fingering-pattern statistics."""

    # KB2 knowledge_id mapping per style.
    STYLE_TO_KB_ID: dict[str, str] = {
        "metal": "kb2-metal-performance",
        "rock": "kb2-rock-lead-performance",  # default to lead
        "pop": "kb2-pop-performance",
        "funk": "kb2-funk-performance",
    }

    # Priors clamp range.
    PRIOR_RANGE: tuple[float, float] = (0.3, 2.0)

    # Minimum sample counts for meaningful confidence.
    _MIN_SAMPLES_FOR_CONFIDENCE = 5
    _MIN_NOTES_FOR_CONFIDENCE = 50

    def derive(
        self,
        style_stats: dict[str, StyleStats],
        source_ids_map: dict[str, list[str]],
    ) -> list[DerivedPriors]:
        """Derive empirical priors from per-style statistics.

        Args:
            style_stats: Mapping from style label to :class:`StyleStats`.
            source_ids_map: Mapping from style label to list of source tab
                file paths (for provenance tracking).

        Returns:
            A list of :class:`DerivedPriors`, one per style with a known
            KB2 knowledge_id.  Styles without a mapping (e.g. ``unknown``)
            are skipped.
        """
        results: list[DerivedPriors] = []

        for style, stats in style_stats.items():
            kb_id = self.STYLE_TO_KB_ID.get(style)
            if kb_id is None:
                logger.debug("No KB2 mapping for style %r; skipping", style)
                continue
            if stats.sample_count < self._MIN_SAMPLES_FOR_CONFIDENCE:
                logger.info(
                    "Style %r has only %d sample(s) (< %d); skipping derivation "
                    "to avoid replacing hand-authored priors with noise",
                    style, stats.sample_count, self._MIN_SAMPLES_FOR_CONFIDENCE,
                )
                continue

            payload: dict[str, Any] = {
                "open_string_bias": self._derive_open_string_bias(stats),
                "hand_position_stability": self._derive_hand_position_stability(stats),
                "shape_reuse": self._derive_shape_reuse(stats),
                "note_overlap": self._derive_note_overlap(stats),
                "staccato": self._derive_staccato(stats),
                "string_skip_penalty": self._derive_string_skip_penalty(stats),
                # Empirical chord shape patterns (top-K by frequency).
                "chord_shapes": dict(list(stats.chord_shape_top_k.items())[:5]),
            }

            source_ids = source_ids_map.get(style, [])
            confidence = self._compute_confidence(stats.sample_count, stats.total_notes)

            # Build a stats snapshot for provenance traceability.
            stats_snapshot: dict[str, Any] = {
                "open_string_rate": stats.open_string_rate,
                "avg_string_skip": stats.avg_string_skip,
                "note_overlap_rate": stats.note_overlap_rate,
                "staccato_rate": stats.staccato_rate,
                "sample_count": stats.sample_count,
                "total_notes": stats.total_notes,
                "top_chord_shapes": dict(list(stats.chord_shape_top_k.items())[:5]),
            }

            derived = DerivedPriors(
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
                "Derived priors for %s (kb_id=%s): %s (confidence=%.2f)",
                style, kb_id, payload, confidence,
            )

        return results

    # ─── Individual prior derivation methods ───

    def _derive_open_string_bias(self, stats: StyleStats) -> float:
        """open_string_bias = clamp(rate / 0.15, 0.3, 2.0).

        A higher open-string usage rate increases the bias toward open strings.
        """
        ratio = stats.open_string_rate / _OPEN_STRING_BASELINE
        return self._clamp(ratio)

    def _derive_hand_position_stability(self, stats: StyleStats) -> float:
        """hand_position_stability = clamp(1 / (1 + change_rate), 0.3, 2.0).

        ``change_rate`` is approximated by the normalised entropy of the
        hand position distribution.  Higher entropy → more position changes
        → lower stability.
        """
        dist = stats.hand_position_distribution
        if not dist:
            return self._clamp(1.0)

        total = sum(dist.values())
        if total <= 0:
            return self._clamp(1.0)

        # Normalised entropy.
        entropy = 0.0
        for freq in dist.values():
            if freq > 0:
                p = freq / total
                entropy -= p * math.log2(p) if p > 0 else 0.0

        # Max entropy for n positions = log2(n).
        n = len(dist)
        max_entropy = math.log2(n) if n > 1 else 1.0
        normalised_entropy = entropy / max_entropy if max_entropy > 0 else 0.0

        # change_rate ≈ normalised_entropy (proxy).
        change_rate = normalised_entropy
        stability = 1.0 / (1.0 + change_rate)
        return self._clamp(stability)

    def _derive_shape_reuse(self, stats: StyleStats) -> float:
        """shape_reuse = clamp(top_shape_freq / 0.1, 0.3, 2.0).

        ``top_shape_freq`` is the frequency of the most common chord shape
        relative to total chords.  Higher reuse → higher prior.
        """
        if not stats.chord_shape_top_k:
            return self._clamp(1.0)

        # The top shape's count relative to the sum of all chord shapes.
        total_shapes = sum(stats.chord_shape_top_k.values())
        if total_shapes <= 0:
            return self._clamp(1.0)

        top_count = max(stats.chord_shape_top_k.values())
        top_freq = top_count / total_shapes
        ratio = top_freq / _SHAPE_REUSE_BASELINE
        return self._clamp(ratio)

    def _derive_note_overlap(self, stats: StyleStats) -> float:
        """note_overlap = clamp(empirical_rate, 0.3, 2.0).

        The overlap rate directly maps to the prior (already in [0, 1]).
        """
        return self._clamp(stats.note_overlap_rate)

    def _derive_staccato(self, stats: StyleStats) -> float:
        """staccato = clamp(rate / 0.15, 0.3, 2.0).

        Higher staccato rate → higher staccato prior.
        """
        ratio = stats.staccato_rate / _STACCATO_BASELINE
        return self._clamp(ratio)

    def _derive_string_skip_penalty(self, stats: StyleStats) -> float:
        """string_skip_penalty = clamp(1 + skip * 0.15, 0.3, 2.0).

        Higher average string skip → higher penalty.
        """
        penalty = 1.0 + stats.avg_string_skip * _STRING_SKIP_WEIGHT
        return self._clamp(penalty)

    def _compute_confidence(self, sample_count: int, total_notes: int) -> float:
        """Compute confidence based on sample size.

        Uses a saturating function:
          - 0 samples → 0.0
          - >= 5 samples AND >= 50 notes → 0.8+
          - Saturates at 1.0 for >= 20 samples AND >= 200 notes.
        """
        if sample_count <= 0 or total_notes <= 0:
            return 0.0

        # Sample-based component (saturating at 20 samples).
        sample_factor = min(1.0, sample_count / 20.0)

        # Note-based component (saturating at 200 notes).
        note_factor = min(1.0, total_notes / 200.0)

        # Combined confidence (weighted average, then scaled to [0, 1]).
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
        """Clamp a value to ``[PRIOR_RANGE[0], PRIOR_RANGE[1]]``."""
        lo, hi = self.PRIOR_RANGE
        return round(max(lo, min(hi, value)), 6)


__all__ = ["PriorsDeriver"]
