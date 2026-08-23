"""P1-1: Fingering-pattern statistics extractor.

Extracts statistical patterns from a collection of :class:`GroundTruthTab`
objects, grouped by style label.  The statistics are the empirical basis for
deriving KB2 priors via :class:`PriorsDeriver`.

Statistics computed per style:
  - open_string_rate: fraction of notes with fret == 0
  - hand_position_distribution: {position: frequency}
  - string_distribution: {string_number: frequency}
  - avg_string_skip: mean |string_diff| between consecutive notes
  - chord_shape_top_k: top-K ``(string, fret)`` combinations per onset
  - note_overlap_rate: fraction of adjacent notes with overlapping durations
  - staccato_rate: fraction of notes with duration < 0.25 beat
  - fret_distribution: {fret: frequency}
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict

from fretpilot.elearning.models import GroundTruthNote, GroundTruthTab, StyleStats

logger = logging.getLogger("fretpilot.elearning.stats_extractor")

# Threshold for staccato detection (in beats).
_STACCATO_THRESHOLD = 0.25
# Maximum number of chord shapes to retain in top-K.
_DEFAULT_TOP_K = 20


class StatsExtractor:
    """Extracts fingering-pattern statistics from ground-truth tabs."""

    def extract(
        self,
        tabs: list[GroundTruthTab],
    ) -> dict[str, StyleStats]:
        """Extract statistics, grouped by ``style_label``.

        Args:
            tabs: A list of parsed ground-truth tabs.

        Returns:
            A dict mapping style label to :class:`StyleStats`.
        """
        # Group tabs by style.
        by_style: dict[str, list[GroundTruthTab]] = defaultdict(list)
        for tab in tabs:
            by_style[tab.style_label].append(tab)

        result: dict[str, StyleStats] = {}
        for style, style_tabs in by_style.items():
            all_notes: list[GroundTruthNote] = []
            for tab in style_tabs:
                all_notes.extend(tab.notes)

            if not all_notes:
                logger.warning("Style %r has no notes; skipping", style)
                continue

            chord_shapes: Counter[str] = Counter()
            skip_total = overlap_total = 0.0
            transition_count = 0
            for tab in style_tabs:
                chord_shapes.update(
                    self._compute_chord_shapes(tab.notes, top_k=max(1, len(tab.notes)))
                )
                if len(tab.notes) >= 2:
                    pairs = len(tab.notes) - 1
                    skip_total += self._compute_avg_string_skip(tab.notes) * pairs
                    beats_per_measure = tab.time_signature[0] * 4 / tab.time_signature[1]
                    overlap_total += (
                        self._compute_note_overlap_rate(
                            tab.notes, beats_per_measure=beats_per_measure
                        )
                        * pairs
                    )
                    transition_count += pairs

            stats = StyleStats(
                style_label=style,
                sample_count=len(style_tabs),
                total_notes=len(all_notes),
                open_string_rate=self._compute_open_string_rate(all_notes),
                hand_position_distribution=self._compute_hand_position_dist(all_notes),
                string_distribution=self._compute_string_distribution(all_notes),
                avg_string_skip=(
                    round(skip_total / transition_count, 6)
                    if transition_count else 0.0
                ),
                chord_shape_top_k=dict(chord_shapes.most_common(_DEFAULT_TOP_K)),
                note_overlap_rate=(
                    round(overlap_total / transition_count, 6)
                    if transition_count else 0.0
                ),
                staccato_rate=self._compute_staccato_rate(all_notes),
                fret_distribution=self._compute_fret_distribution(all_notes),
                technique_rates=self._compute_technique_rates(style_tabs, len(all_notes)),
            )
            result[style] = stats
            logger.info(
                "Extracted stats for style %r: %d notes from %d tabs",
                style, len(all_notes), len(style_tabs),
            )

        return result

    # ─── Individual statistics ───

    @staticmethod
    def _compute_open_string_rate(notes: list[GroundTruthNote]) -> float:
        """Fraction of notes with fret == 0 (open string)."""
        if not notes:
            return 0.0
        open_count = sum(1 for n in notes if n.fret == 0)
        return round(open_count / len(notes), 6)

    @staticmethod
    def _compute_hand_position_dist(notes: list[GroundTruthNote]) -> dict[int, float]:
        """Histogram of hand_position values → {position: frequency}."""
        if not notes:
            return {}
        counter: Counter[int] = Counter(n.hand_position for n in notes)
        total = len(notes)
        return {pos: round(count / total, 6) for pos, count in sorted(counter.items())}

    @staticmethod
    def _compute_string_distribution(notes: list[GroundTruthNote]) -> dict[int, float]:
        """Histogram of string numbers → {string: frequency}."""
        if not notes:
            return {}
        counter: Counter[int] = Counter(n.string for n in notes)
        total = len(notes)
        return {s: round(count / total, 6) for s, count in sorted(counter.items())}

    @staticmethod
    def _compute_chord_shapes(
        notes: list[GroundTruthNote],
        top_k: int = _DEFAULT_TOP_K,
    ) -> dict[str, int]:
        """Top-K chord shapes by frequency.

        A chord shape is the sorted set of ``(string, fret)`` pairs at the
        same onset (measure_number + beat_in_measure).  Only onsets with
        more than one note are considered chords.

        The shape key is formatted as ``"s1f0,s2f2,s3f2"`` (sorted by string).
        """
        # Group by onset.
        groups: dict[tuple[int, float], list[GroundTruthNote]] = defaultdict(list)
        for n in notes:
            key = (n.measure_number, round(n.beat_in_measure, 4))
            groups[key].append(n)

        shape_counter: Counter[str] = Counter()
        for members in groups.values():
            if len(members) < 2:
                continue  # Skip single notes.
            # A shape is a *set* of (string, fret) pairs: dedupe identical
            # pairs so doubled notes (e.g. a note + its tie artifact) do not
            # corrupt the shape key with entries like "s2f0,s2f0".
            pairs = {(n.string, n.fret) for n in members}
            if len(pairs) < 2:
                continue  # Still not a real chord after dedup.
            # Sort by string number for a canonical key.
            shape_key = ",".join(
                f"s{string}f{fret}" for string, fret in sorted(pairs)
            )
            shape_counter[shape_key] += 1

        # Return top-K.
        return dict(shape_counter.most_common(top_k))

    @staticmethod
    def _compute_avg_string_skip(notes: list[GroundTruthNote]) -> float:
        """Mean absolute string difference between consecutive notes.

        Notes are sorted by absolute time position (measure, beat) before
        computing skips.  Returns 0.0 for fewer than 2 notes.
        """
        if len(notes) < 2:
            return 0.0

        sorted_notes = sorted(
            notes,
            key=lambda n: (n.measure_number, n.beat_in_measure),
        )
        skips = [
            abs(sorted_notes[i].string - sorted_notes[i - 1].string)
            for i in range(1, len(sorted_notes))
        ]
        return round(sum(skips) / len(skips), 6)

    @staticmethod
    def _compute_note_overlap_rate(
        notes: list[GroundTruthNote], beats_per_measure: float = 4.0
    ) -> float:
        """Fraction of adjacent note pairs with overlapping durations.

        Two notes overlap if the second starts before the first ends
        (in absolute time).  Notes are sorted by onset.
        """
        if len(notes) < 2:
            return 0.0

        sorted_notes = sorted(
            notes,
            key=lambda n: (n.measure_number, n.beat_in_measure),
        )

        overlaps = 0
        total_pairs = 0
        for i in range(1, len(sorted_notes)):
            prev = sorted_notes[i - 1]
            curr = sorted_notes[i]
            prev_end = (
                (prev.measure_number - 1) * beats_per_measure
                + prev.beat_in_measure
                + prev.duration_beats
            )
            curr_start = (
                (curr.measure_number - 1) * beats_per_measure
                + curr.beat_in_measure
            )
            if curr_start < prev_end:
                overlaps += 1
            total_pairs += 1

        return round(overlaps / total_pairs, 6) if total_pairs > 0 else 0.0

    @staticmethod
    def _compute_staccato_rate(notes: list[GroundTruthNote]) -> float:
        """Fraction of notes with duration < 0.25 beat (16th note)."""
        if not notes:
            return 0.0
        staccato_count = sum(1 for n in notes if n.duration_beats < _STACCATO_THRESHOLD)
        return round(staccato_count / len(notes), 6)

    @staticmethod
    def _compute_fret_distribution(notes: list[GroundTruthNote]) -> dict[int, float]:
        """Histogram of fret values → {fret: frequency}."""
        if not notes:
            return {}
        counter: Counter[int] = Counter(n.fret for n in notes)
        total = len(notes)
        return {f: round(count / total, 6) for f, count in sorted(counter.items())}

    @staticmethod
    def _compute_technique_rates(
        tabs: list[GroundTruthTab], total_notes: int
    ) -> dict[str, float]:
        """Observed explicit GP technique relations per ground-truth note."""

        if total_notes <= 0:
            return {}
        counter = Counter(
            technique.type for tab in tabs for technique in tab.techniques
        )
        return {
            name: round(count / total_notes, 6)
            for name, count in sorted(counter.items())
        }


__all__ = ["StatsExtractor"]
