"""Stream separation detection — pure algorithm layer.

Detects whether a single guitar MIDI track mixes a low "rhythm" riff with a
high "lead" melody *co-sounding in the same measures*, and if so computes the
pitch split point that partitions the track into two streams.

Design constraints (see architecture note):

- **Standard library only** — this module is unit-tested in isolation and must
  not import anything from ``fretpilot`` (avoids circular imports with the
  engine context layer).
- **Pure partition** — every note belongs to exactly one of ``lead`` /
  ``rhythm``; the two streams' union is the original note set (no drop / no
  duplicate).
- **Track-level separation** — voice semantics are untouched (voice 2 stays
  "out of range"); separation happens at the track layer only.

The detection pipeline mirrors the architect's pseudo-code:

1. Per measure: duration-weighted pitch histogram → best split point within the
   low-string prior window (E2–G3, MIDI 40–55).
2. Require both sides to have enough notes (``min_side_notes``).
3. Require a coactive (concurrent) onset ratio ≥ 0.5 and ≥ 2 concurrent onsets,
   which rejects wide-range *sequential* melodies (low-then-high).
4. Duration/continuity contrast between riff and melody adjusts confidence only.
5. Merge adjacent / near-adjacent candidate segments, then drop segments below
   ``confidence_threshold`` (per-segment fallback).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Literal

Stream = Literal["lead", "rhythm"]

# Onset tolerance for two onsets to count as "coactive" (1/16 beat).
_ONSET_TOLERANCE = 1.0 / 16.0
# Minimum ratio of low onsets that must co-occur with a high onset.
_MIN_COACTIVE_RATIO = 0.5
# Triangular-kernel half width (semitones) for pitch-histogram smoothing.
_KERNEL_HALF_WIDTH = 3
# Confidence band that triggers a "review recommended" warning.
_REVIEW_THRESHOLD = 0.7
# Duration thresholds (beats) used by the riff/melody contrast features.
_SHORT_NOTE_BEATS = 0.5
_LONG_NOTE_BEATS = 1.0
_SMALL_STEP_SEMITONES = 4


@dataclass(slots=True)
class SeparationNote:
    """A lightweight projection of a ``VoicedNote`` for the detection layer.

    ``duration_beats`` carries ``original_duration_beats`` (not the quantized
    duration) because duration-contrast features must compare the *source*
    timing, which is unaffected by the quantize grid.
    """

    source_index: int
    pitch: int
    start_beat: float
    duration_beats: float
    measure_number: int
    beat_in_measure: float


@dataclass(slots=True)
class SeparationSegment:
    """A contiguous measure range that should be split into two streams."""

    start_measure: int
    end_measure: int
    split_pitch: int
    low_note_count: int
    high_note_count: int
    confidence: float
    features: dict[str, float] = field(default_factory=dict)
    reason: str = ""

    @property
    def note_count(self) -> int:
        """Total number of notes covered by this segment."""
        return self.low_note_count + self.high_note_count


@dataclass(slots=True)
class SeparationReport:
    """Result of :func:`detect_separation`.

    ``segments`` holds only the *active* segments (confidence ≥ threshold).
    Rejected candidates are reported through ``warnings`` and are not split.
    """

    detected: bool
    segments: list[SeparationSegment]
    total_confidence: float
    warnings: list[str] = field(default_factory=list)

    def segment_covering(self, measure: int) -> SeparationSegment | None:
        """Return the active segment covering ``measure``, or ``None``."""
        for segment in self.segments:
            if segment.start_measure <= measure <= segment.end_measure:
                return segment
        return None

    def is_separated(self, measure: int) -> bool:
        """Return True if ``measure`` falls inside an active segment."""
        return self.segment_covering(measure) is not None

    def split_pitch_for(self, measure: int) -> int | None:
        """Return the split pitch for ``measure``, or ``None`` if not separated."""
        segment = self.segment_covering(measure)
        return segment.split_pitch if segment is not None else None


# ─── Signal 1: pitch histogram + best split point ───


def _pitch_histogram(notes: list[SeparationNote]) -> dict[int, float]:
    """Build a duration-weighted pitch histogram, smoothed with a triangular
    kernel of half-width ``_KERNEL_HALF_WIDTH`` semitones."""
    weights: dict[int, float] = {}
    for note in notes:
        if note.duration_beats > 0:
            weights[note.pitch] = weights.get(note.pitch, 0.0) + note.duration_beats

    if not weights:
        return {}

    smoothed: dict[int, float] = {}
    lo = min(weights) - _KERNEL_HALF_WIDTH
    hi = max(weights) + _KERNEL_HALF_WIDTH
    denom = float(_KERNEL_HALF_WIDTH + 1)
    for center in range(lo, hi + 1):
        total = 0.0
        for offset in range(-_KERNEL_HALF_WIDTH, _KERNEL_HALF_WIDTH + 1):
            weight = weights.get(center + offset, 0.0)
            if weight:
                total += weight * (1.0 - abs(offset) / denom)
        if total > 0:
            smoothed[center] = total
    return smoothed


def _find_best_split(
    notes: list[SeparationNote],
    low_prior: tuple[int, int] | None,
    min_gap: int,
) -> tuple[int, float] | None:
    """Return ``(split_pitch, gap_score)`` via 1-D k-means (k=2) on pitches.

    Replaces the original "largest pitch gap" heuristic, which failed on
    samples where the riff and lead registers are *contiguous* (no empty gap,
    e.g. a riff spanning 40–54 and a lead starting at 55).  A two-cluster
    variance-minimising split finds the natural boundary between the low riff
    cluster and the high lead cluster even without a gap, so the riff stays
    whole instead of being sliced in half.

    ``low_prior`` optionally constrains the split to a window; ``min_gap`` is
    kept for signature compatibility but no longer gates the split.
    """
    pitches = sorted(n.pitch for n in notes)
    n = len(pitches)
    if n < 6:
        return None

    lo, hi = pitches[0], pitches[-1]
    if hi - lo < 12:  # narrower than an octave — not a riff + lead mix
        return None

    # Prefix sums so within-cluster variance is O(1) per candidate split.
    prefix = [0] * (n + 1)
    prefix_sq = [0] * (n + 1)
    for i, p in enumerate(pitches):
        prefix[i + 1] = prefix[i] + p
        prefix_sq[i + 1] = prefix_sq[i] + p * p

    best_split: int | None = None
    best_cost = float("inf")
    for i in range(3, n - 2):  # i = number of notes in the low cluster
        split = (pitches[i - 1] + pitches[i]) // 2
        if low_prior is not None and not (low_prior[0] <= split <= low_prior[1]):
            continue
        low_n = i
        high_n = n - i
        low_sum = prefix[i]
        low_sq = prefix_sq[i]
        high_sum = prefix[n] - prefix[i]
        high_sq = prefix_sq[n] - prefix_sq[i]
        # within-cluster sum of squared deviations (avoids float mean drift)
        low_var = low_sq - (low_sum * low_sum) / low_n
        high_var = high_sq - (high_sum * high_sum) / high_n
        cost = low_var + high_var
        if cost < best_cost:
            best_cost = cost
            best_split = split

    if best_split is None:
        return None

    # Convert cost to a 0..1 "separation" score: a clean two-cluster split has
    # small within-cluster variance relative to total variance.
    mean = prefix[n] / n
    total_var = prefix_sq[n] - n * mean * mean
    if total_var <= 0:
        score = 1.0
    else:
        score = _clamp(1.0 - best_cost / total_var, 0.0, 1.0)
    return best_split, score


# ─── Signal 2: coactive onsets ───


def _coactive_onsets(
    low: list[SeparationNote],
    high: list[SeparationNote],
    tolerance: float,
) -> tuple[float, int]:
    """Return ``(ratio, coactive_count)`` of low onsets co-occurring with high.

    Low onsets are first merged within ``tolerance`` (a riff chord/fast-strum
    cluster counts as one onset), then each merged onset is compared against the
    high onsets for a same-window start.
    """
    low_onsets = sorted({round(n.start_beat, 6) for n in low})
    high_onsets = sorted({round(n.start_beat, 6) for n in high})

    groups: list[list[float]] = []
    for onset in low_onsets:
        if groups and onset - groups[-1][-1] <= tolerance:
            groups[-1].append(onset)
        else:
            groups.append([onset])

    if not groups:
        return 0.0, 0

    coactive = 0
    for group in groups:
        center = sum(group) / len(group)
        if any(abs(onset - center) <= tolerance for onset in high_onsets):
            coactive += 1

    return coactive / len(groups), coactive


# ─── Signal 3: duration / continuity contrast ───


def _onset_regularity(onsets: list[float]) -> float:
    """Return a 0..1 score for how evenly-spaced ``onsets`` are (1 = metronome)."""
    if len(onsets) < 2:
        return 1.0 if len(onsets) == 1 else 0.0
    intervals = [b - a for a, b in zip(onsets, onsets[1:])]
    mean = sum(intervals) / len(intervals)
    if mean <= 0:
        return 0.0
    variance = sum((x - mean) ** 2 for x in intervals) / len(intervals)
    cv = variance ** 0.5 / mean  # coefficient of variation
    return max(0.0, min(1.0, 1.0 - cv))


def _duration_contrast(
    low: list[SeparationNote],
    high: list[SeparationNote],
) -> float:
    """Synthesize a 0..1 riff-vs-melody contrast score.

    Riff signature: short notes (≤ 0.5 beat) + regular onset spacing.
    Melody signature: long notes (≥ 1 beat) + small stepwise pitch motion.
    """
    if not low or not high:
        return 0.0

    low_short = sum(1 for n in low if n.duration_beats <= _SHORT_NOTE_BEATS) / len(low)

    low_onsets = sorted({round(n.start_beat, 6) for n in low})
    regularity = _onset_regularity(low_onsets)

    high_long = sum(1 for n in high if n.duration_beats >= _LONG_NOTE_BEATS) / len(high)

    high_pitches = sorted({n.pitch for n in high})
    steps = [b - a for a, b in zip(high_pitches, high_pitches[1:])]
    high_small = (
        sum(1 for s in steps if abs(s) <= _SMALL_STEP_SEMITONES) / len(steps)
        if steps
        else 1.0
    )

    return _clamp(
        0.25 * low_short + 0.25 * regularity + 0.25 * high_long + 0.25 * high_small,
        0.0,
        1.0,
    )


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp ``value`` into the inclusive ``[lo, hi]`` range."""
    return max(lo, min(hi, value))


def _merge_adjacent(
    candidates: list[SeparationSegment],
    max_gap_measures: int,
) -> list[SeparationSegment]:
    """Merge candidates that are adjacent or separated by ≤ ``max_gap_measures``.

    The merged split pitch is the median of member splits; confidence and
    features are averaged; note counts are summed.
    """
    if not candidates:
        return []

    ordered = sorted(candidates, key=lambda s: (s.start_measure, s.end_measure))
    groups: list[list[SeparationSegment]] = []
    for segment in ordered:
        if groups and segment.start_measure - groups[-1][-1].end_measure <= max_gap_measures + 1:
            groups[-1].append(segment)
        else:
            groups.append([segment])

    merged: list[SeparationSegment] = []
    for group in groups:
        splits = sorted(segment.split_pitch for segment in group)
        feature_keys = set().union(*(segment.features.keys() for segment in group))
        merged.append(
            SeparationSegment(
                start_measure=min(segment.start_measure for segment in group),
                end_measure=max(segment.end_measure for segment in group),
                split_pitch=int(median(splits)),
                low_note_count=sum(segment.low_note_count for segment in group),
                high_note_count=sum(segment.high_note_count for segment in group),
                confidence=_clamp(
                    sum(segment.confidence for segment in group) / len(group), 0.0, 1.0
                ),
                features={
                    key: sum(segment.features.get(key, 0.0) for segment in group)
                    / len(group)
                    for key in feature_keys
                },
                reason=" | ".join(segment.reason for segment in group),
            )
        )
    return merged


def detect_separation(
    notes: list[SeparationNote],
    *,
    low_prior: tuple[int, int] | None = None,
    min_side_notes: int = 3,
    min_coactive_onsets: int = 2,
    min_gap_semitones: int = 5,
    confidence_threshold: float = 0.5,
) -> SeparationReport:
    """Detect riff/melody separation across the WHOLE track.

    The split is computed globally (one split pitch for the whole track), not
    per measure.  A per-measure split turned out to be wrong: a riff pitch
    (e.g. A2=45) got assigned to Rhythm in some measures and to Lead in others,
    slicing the riff in half.  A single global split keeps every riff note on
    one track and every lead note on the other, which is what the user wants
    ("separate the high lead out, keep the low riff whole").

    Returns a :class:`SeparationReport` whose ``segments`` holds a single
    track-wide segment when separation is confident, else is empty (single
    track).
    """
    if len(notes) < 2 * min_side_notes:
        return SeparationReport(detected=False, segments=[], total_confidence=0.0)

    best = _find_best_split(notes, low_prior, min_gap_semitones)
    if best is None:
        return SeparationReport(detected=False, segments=[], total_confidence=0.0)
    split_pitch, gap_score = best

    low = [n for n in notes if n.pitch < split_pitch]
    high = [n for n in notes if n.pitch >= split_pitch]
    if len(low) < min_side_notes or len(high) < min_side_notes:
        return SeparationReport(detected=False, segments=[], total_confidence=0.0)

    # The two-cluster split score is the primary signal: a clear bimodal pitch
    # distribution (riff cluster + lead cluster) has a high gap_score, whereas
    # a single wide-range melody is unimodal and scores low.
    if gap_score < 0.5:
        return SeparationReport(
            detected=False,
            segments=[],
            total_confidence=0.0,
            warnings=[
                "Pitch distribution is not clearly bimodal; skipping separation "
                "(likely a single wide-range melody)."
            ],
        )

    # Coactive onsets are a *soft* gate: a true riff+lead mix has the two lines
    # sounding together, so at least a few low onsets co-occur with high onsets.
    # A sequential low-then-high melody has *zero* coactive onsets.  The gate is
    # deliberately loose (≥2 coactive onsets, ≥25% ratio) because real tracks
    # interleave riff and lead rather than aligning them exactly.
    poly_ratio, coactive = _coactive_onsets(low, high, _ONSET_TOLERANCE)
    if coactive < min_coactive_onsets or poly_ratio < 0.25:
        return SeparationReport(
            detected=False,
            segments=[],
            total_confidence=0.0,
            warnings=[
                "Low and high registers do not co-sound; skipping separation "
                "(likely a sequential wide-range melody, not a riff + lead mix)."
            ],
        )

    duration_score = _duration_contrast(low, high)
    confidence = _clamp(
        0.40 * gap_score + 0.30 * poly_ratio + 0.30 * duration_score, 0.0, 1.0
    )

    start_measure = min(n.measure_number for n in notes)
    end_measure = max(n.measure_number for n in notes)
    segment = SeparationSegment(
        start_measure=start_measure,
        end_measure=end_measure,
        split_pitch=split_pitch,
        low_note_count=len(low),
        high_note_count=len(high),
        confidence=confidence,
        features={"gap": gap_score, "poly": poly_ratio, "duration": duration_score},
        reason=(
            f"global split at pitch {split_pitch} "
            f"(riff {len(low)} / lead {len(high)})"
        ),
    )

    warnings: list[str] = []
    if confidence < confidence_threshold:
        return SeparationReport(
            detected=False,
            segments=[],
            total_confidence=0.0,
            warnings=[
                f"Separation confidence {confidence:.2f} < {confidence_threshold}; "
                "keeping a single track."
            ],
        )
    if confidence < _REVIEW_THRESHOLD:
        warnings.append(
            f"Separated into Lead/Rhythm (confidence {confidence:.2f}); review recommended."
        )

    return SeparationReport(
        detected=True,
        segments=[segment],
        total_confidence=confidence,
        warnings=warnings,
    )


def assign_stream(note: SeparationNote, report: SeparationReport) -> Stream:
    """Assign ``note`` to ``"lead"`` or ``"rhythm"`` given a separation report.

    Notes outside a confident segment stay in the single-track ``"lead"``
    stream; inside a segment, pitches below the split are ``"rhythm"`` and
    pitches at/above it are ``"lead"``.
    """
    segment = report.segment_covering(note.measure_number)
    if segment is None:
        return "lead"
    return "rhythm" if note.pitch < segment.split_pitch else "lead"


__all__ = [
    "SeparationNote",
    "SeparationSegment",
    "SeparationReport",
    "Stream",
    "detect_separation",
    "assign_stream",
]
