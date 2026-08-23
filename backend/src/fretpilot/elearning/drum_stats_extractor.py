"""Drum statistics extractor for StickPilot.

Extracts statistical patterns from a collection of
:class:`DrumGroundTruthTab` objects, grouped by style label.  These
statistics are the empirical basis for deriving drum KB2 sticking priors
via :class:`DrumPriorsDeriver`.

Statistics computed per style:
  - hit_density: mean hits per measure
  - avg_inter_hit_gap_beats: mean gap between consecutive hits
  - velocity_mean / accent_rate / ghost_note_rate: dynamics profile
  - flam_rate / double_stroke_rate: roll/ornament frequency
  - right_hand_rate / hand_switch_pattern: sticking tendency
  - piece_distribution: kit usage histogram
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict

from fretpilot.elearning.drum_models import (
    DrumGroundTruthNote,
    DrumGroundTruthTab,
    DrumStyleStats,
)

logger = logging.getLogger("fretpilot.elearning.drum_stats_extractor")

# Dynamics thresholds (aligned with drum_kb3_notation.json payload).
_GHOST_VELOCITY_THRESHOLD = 30
_ACCENT_VELOCITY_THRESHOLD = 90

# Sticking-relevant timing thresholds (aligned with the S6 StickingStage).
_FLAM_THRESHOLD_BEATS = 0.03
_DOUBLE_STROKE_THRESHOLD_BEATS = 0.06

# Pieces never played with hands (foot pedals).
_FOOT_PIECES = frozenset({"kick", "hihat_pedal"})


class DrumStatsExtractor:
    """Extracts drum statistics from ground-truth tabs."""

    def extract(
        self,
        tabs: list[DrumGroundTruthTab],
    ) -> dict[str, DrumStyleStats]:
        """Extract statistics, grouped by ``style_label``.

        Args:
            tabs: A list of parsed drum ground-truth tabs.

        Returns:
            A dict mapping style label to :class:`DrumStyleStats`.
        """
        # Group tabs by style.
        by_style: dict[str, list[DrumGroundTruthTab]] = defaultdict(list)
        for tab in tabs:
            by_style[tab.style_label].append(tab)

        result: dict[str, DrumStyleStats] = {}
        for style, style_tabs in by_style.items():
            all_notes: list[DrumGroundTruthNote] = []
            total_measures = 0
            for tab in style_tabs:
                all_notes.extend(tab.notes)
                total_measures += max(tab.measure_count, 1)

            if not all_notes:
                logger.warning("Style %r has no drum notes; skipping", style)
                continue

            stats = DrumStyleStats(
                style_label=style,
                sample_count=len(style_tabs),
                total_notes=len(all_notes),
                total_measures=total_measures,
                hit_density=self._compute_hit_density(len(all_notes), total_measures),
                avg_inter_hit_gap_beats=self._compute_avg_gap(all_notes),
                velocity_mean=self._compute_velocity_mean(all_notes),
                accent_rate=self._compute_rate(all_notes, _ACCENT_VELOCITY_THRESHOLD, above=True),
                ghost_note_rate=self._compute_rate(all_notes, _GHOST_VELOCITY_THRESHOLD, above=False),
                flam_rate=self._compute_ornament_rate(all_notes, "flam"),
                double_stroke_rate=self._compute_ornament_rate(all_notes, "double"),
                right_hand_rate=self._compute_right_hand_rate(all_notes),
                hand_switch_pattern=self._compute_hand_switch_pattern(all_notes),
                piece_distribution=self._compute_piece_distribution(all_notes),
            )
            result[style] = stats
            logger.info(
                "Extracted drum stats for style %r: %d notes from %d tabs",
                style, len(all_notes), len(style_tabs),
            )

        return result

    # ─── Individual statistics ───

    @staticmethod
    def _compute_hit_density(total_notes: int, total_measures: int) -> float:
        """Mean hits per measure across all tabs in the style."""
        if total_measures <= 0:
            return 0.0
        return round(total_notes / total_measures, 6)

    @staticmethod
    def _sort_chronological(
        notes: list[DrumGroundTruthNote],
    ) -> list[DrumGroundTruthNote]:
        """Sort notes by (measure_number, beat_in_measure)."""
        return sorted(
            notes,
            key=lambda n: (n.measure_number, n.beat_in_measure),
        )

    @classmethod
    def _compute_avg_gap(cls, notes: list[DrumGroundTruthNote]) -> float:
        """Mean gap (beats) between consecutive hits, within and across measures.

        Hits on the same piece within the same onset are treated as a single
        onset (flam/roll), so the gap reflects real playing pace.
        """
        sorted_notes = cls._sort_chronological(notes)
        if len(sorted_notes) < 2:
            return 0.0
        gaps: list[float] = []
        for i in range(1, len(sorted_notes)):
            prev = sorted_notes[i - 1]
            curr = sorted_notes[i]
            # Approximate measure length as 4 beats (sufficient for priors).
            gap = (curr.measure_number - prev.measure_number) * 4.0 + (
                curr.beat_in_measure - prev.beat_in_measure
            )
            if gap > 0:
                gaps.append(gap)
        if not gaps:
            return 0.0
        return round(sum(gaps) / len(gaps), 6)

    @staticmethod
    def _compute_velocity_mean(notes: list[DrumGroundTruthNote]) -> float:
        """Mean velocity of all hits."""
        if not notes:
            return 0.0
        return round(sum(n.velocity for n in notes) / len(notes), 6)

    @classmethod
    def _compute_rate(
        cls,
        notes: list[DrumGroundTruthNote],
        threshold: int,
        *,
        above: bool,
    ) -> float:
        """Fraction of notes above/below a velocity threshold."""
        if not notes:
            return 0.0
        if above:
            count = sum(1 for n in notes if n.velocity >= threshold)
        else:
            count = sum(1 for n in notes if n.velocity <= threshold)
        return round(count / len(notes), 6)

    @classmethod
    def _compute_ornament_rate(
        cls,
        notes: list[DrumGroundTruthNote],
        kind: str,
    ) -> float:
        """Fraction of hits that are part of a flam or double-stroke pair.

        A pair is two hits on the *same piece* within a tight timing window:
          - flam:   gap <= 0.03 beats (near-simultaneous)
          - double: 0.03 < gap <= 0.06 beats (rolled second hit)

        Returns the fraction of all hits that belong to such pairs.
        """
        sorted_notes = cls._sort_chronological(notes)
        if len(sorted_notes) < 2:
            return 0.0

        flagged = [False] * len(sorted_notes)
        for i in range(1, len(sorted_notes)):
            prev = sorted_notes[i - 1]
            curr = sorted_notes[i]
            if prev.piece != curr.piece:
                continue
            gap = (curr.measure_number - prev.measure_number) * 4.0 + (
                curr.beat_in_measure - prev.beat_in_measure
            )
            if kind == "flam" and gap <= _FLAM_THRESHOLD_BEATS:
                flagged[i - 1] = True
                flagged[i] = True
            elif (
                kind == "double"
                and _FLAM_THRESHOLD_BEATS < gap <= _DOUBLE_STROKE_THRESHOLD_BEATS
            ):
                flagged[i - 1] = True
                flagged[i] = True

        return round(sum(flagged) / len(sorted_notes), 6)

    @classmethod
    def _assign_sticking(
        cls,
        notes: list[DrumGroundTruthNote],
    ) -> list[str]:
        """Assign R/L/both sticking per hit using the S6 heuristic.

        Mirrors the StickingStage logic so learned priors reflect the same
        hand-assignment rules the pipeline applies at repair time:
          - kick / pedal hi-hat → foot, never a hand (marked "F")
          - flam pair → both hands ("B")
          - double stroke → repeat the previous hand
          - otherwise alternate R/L
        """
        sorted_notes = cls._sort_chronological(notes)
        sticking: list[str] = []
        last_hand: str = ""

        for i, note in enumerate(sorted_notes):
            if note.piece in _FOOT_PIECES:
                sticking.append("F")
                continue
            if i > 0:
                prev = sorted_notes[i - 1]
                if prev.piece == note.piece:
                    gap = (note.measure_number - prev.measure_number) * 4.0 + (
                        note.beat_in_measure - prev.beat_in_measure
                    )
                    if gap <= _FLAM_THRESHOLD_BEATS:
                        sticking.append("B")
                        last_hand = ""
                        continue
                    if gap <= _DOUBLE_STROKE_THRESHOLD_BEATS:
                        prev_sticking = sticking[-1] if sticking else ""
                        hand = prev_sticking if prev_sticking in ("R", "L") else "R"
                        sticking.append(hand)
                        last_hand = hand
                        continue
            if not last_hand or last_hand == "L":
                hand = "R"
            else:
                hand = "L"
            sticking.append(hand)
            last_hand = hand

        return sticking

    @classmethod
    def _compute_right_hand_rate(cls, notes: list[DrumGroundTruthNote]) -> float:
        """Fraction of hand-played hits assigned right hand."""
        sticking = cls._assign_sticking(notes)
        hands = [s for s in sticking if s in ("R", "L")]
        if not hands:
            return 0.0
        return round(hands.count("R") / len(hands), 6)

    @classmethod
    def _compute_hand_switch_pattern(cls, notes: list[DrumGroundTruthNote]) -> str:
        """Dominant 4-letter hand pattern (e.g. "RLRL", "RRLL", "RLLR").

        Slides a 4-window over the hand sequence and returns the most
        frequent pattern.  Empty/too-short sequences fall back to "RLRL".
        """
        sticking = cls._assign_sticking(notes)
        hands = [s for s in sticking if s in ("R", "L")]
        if len(hands) < 4:
            return "RLRL"
        counter: Counter[str] = Counter()
        for i in range(len(hands) - 3):
            window = "".join(hands[i:i + 4])
            counter[window] += 1
        return counter.most_common(1)[0][0]

    @staticmethod
    def _compute_piece_distribution(
        notes: list[DrumGroundTruthNote],
    ) -> dict[str, float]:
        """Histogram of drum pieces → {piece: frequency}."""
        if not notes:
            return {}
        counter: Counter[str] = Counter(n.piece for n in notes)
        total = len(notes)
        return {p: round(c / total, 6) for p, c in sorted(counter.items())}


__all__ = ["DrumStatsExtractor"]
