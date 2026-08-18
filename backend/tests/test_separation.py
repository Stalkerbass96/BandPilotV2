"""Unit tests for stream separation detection + assignment.

Covers the pure algorithm layer ``fretpilot.detection.separation`` with no
engine dependencies: pitch-gap split detection, coactive-onset gating,
per-segment fallback, segment merging, and note-to-stream assignment.
"""

from __future__ import annotations

from fretpilot.detection.separation import (
    SeparationNote,
    SeparationReport,
    SeparationSegment,
    assign_stream,
    detect_separation,
)
from fretpilot.engine.stages.separation import _riff_register_prior


def _mk(
    pitch: int,
    start_beat: float,
    duration_beats: float,
    measure_number: int = 1,
    source_index: int = 0,
) -> SeparationNote:
    """Build a :class:`SeparationNote` with an auto-incremented source index."""
    return SeparationNote(
        source_index=source_index,
        pitch=pitch,
        start_beat=start_beat,
        duration_beats=duration_beats,
        measure_number=measure_number,
        beat_in_measure=start_beat % 4.0,
    )


def _riff_melody_measure() -> list[SeparationNote]:
    """A clear co-sounding riff + melody in one measure.

    Low riff (E2/G2, short 16ths) at beats 0/0.5/1.0/1.5; high melody
    (E4/G4/A4, longer notes) at beats 0/0.5/1.0 — three of four riff onsets
    are coactive with the melody.
    """
    low = [
        _mk(40, 0.0, 0.25),
        _mk(43, 0.5, 0.25),
        _mk(40, 1.0, 0.25),
        _mk(43, 1.5, 0.25),
    ]
    high = [
        _mk(64, 0.0, 1.0),
        _mk(67, 0.5, 1.0),
        _mk(69, 1.0, 1.0),
    ]
    return low + high


class TestDetectSeparation:
    def test_detects_clear_riff_melody_separation(self) -> None:
        report = detect_separation(_riff_melody_measure())
        assert report.detected is True
        assert len(report.segments) == 1
        segment = report.segments[0]
        assert segment.start_measure == 1
        assert segment.end_measure == 1
        assert 43 < segment.split_pitch < 64  # split sits in the gap
        assert segment.low_note_count == 4
        assert segment.high_note_count == 3
        assert segment.confidence >= 0.5

    def test_no_separation_for_monophonic_melody(self) -> None:
        notes = [
            _mk(60, 0.0, 0.5),
            _mk(62, 0.5, 0.5),
            _mk(64, 1.0, 0.5),
            _mk(65, 1.5, 0.5),
            _mk(67, 2.0, 0.5),
            _mk(69, 2.5, 0.5),
        ]
        report = detect_separation(notes)
        assert report.detected is False
        assert report.segments == []

    def test_rejects_sequential_wide_range_melody(self) -> None:
        """A low-then-high melody (never co-sounding) must not be split."""
        notes = [
            _mk(40, 0.0, 0.25),
            _mk(43, 0.25, 0.25),
            _mk(45, 0.5, 0.25),
            _mk(64, 0.75, 0.25),
            _mk(67, 1.0, 0.25),
            _mk(69, 1.25, 0.25),
        ]
        report = detect_separation(notes)
        assert report.detected is False

    def test_segment_fallback_below_threshold(self) -> None:
        """Raising the threshold above a segment's confidence drops it."""
        report = detect_separation(
            _riff_melody_measure(), confidence_threshold=0.99
        )
        assert report.detected is False
        assert report.segments == []
        # The rejected candidate is surfaced as a warning.
        assert any("single track" in w for w in report.warnings)

    def test_review_warning_in_mid_band(self) -> None:
        """0.5 ≤ confidence < 0.7 emits a review-recommended warning."""
        # Moderate gap (50→56, split 53) with a weak duration contrast (low
        # notes long, high notes short — the *opposite* of the usual riff/lead
        # signature) keeps confidence inside the (0.5, 0.7) review band.
        mid_notes = [
            _mk(40, 0.0, 1.0),
            _mk(45, 0.5, 1.0),
            _mk(50, 1.0, 1.0),
            _mk(56, 0.0, 0.25),
            _mk(60, 0.5, 0.25),
            _mk(64, 1.75, 0.25),
        ]
        report = detect_separation(mid_notes, confidence_threshold=0.5)
        assert report.detected is True
        assert 0.5 <= report.segments[0].confidence < 0.7
        assert any("review recommended" in w for w in report.warnings)

    def test_merges_adjacent_segments(self) -> None:
        """Segments in measures 1 and 2 merge into one contiguous segment."""
        notes = _riff_melody_measure() + [
            _mk(40, 0.0, 0.25, measure_number=2),
            _mk(43, 0.5, 0.25, measure_number=2),
            _mk(40, 1.0, 0.25, measure_number=2),
            _mk(64, 0.0, 1.0, measure_number=2),
            _mk(67, 0.5, 1.0, measure_number=2),
            _mk(69, 1.0, 1.0, measure_number=2),
        ]
        report = detect_separation(notes)
        assert report.detected is True
        assert len(report.segments) == 1
        assert report.segments[0].start_measure == 1
        assert report.segments[0].end_measure == 2

    def test_split_pitch_inside_low_prior_window(self) -> None:
        report = detect_separation(_riff_melody_measure())
        assert report.detected is True
        assert 40 <= report.segments[0].split_pitch <= 55

    def test_detects_only_mixed_measures(self) -> None:
        """Per-measure detection: a pure-melody measure is NOT split.

        Measure 1 is a riff+melody mix; measure 2 is a pure melody (no low
        register).  Only measure 1 may be separated — measure 2 keeps the
        single-track "lead" stream.
        """
        mixed = _riff_melody_measure()  # measure 1
        pure = [
            _mk(64, 0.0, 0.5, measure_number=2),
            _mk(67, 0.5, 0.5, measure_number=2),
            _mk(69, 1.0, 0.5, measure_number=2),
            _mk(71, 1.5, 0.5, measure_number=2),
            _mk(72, 2.0, 0.5, measure_number=2),
            _mk(74, 2.5, 0.5, measure_number=2),
        ]
        report = detect_separation(mixed + pure)
        assert report.detected is True
        assert len(report.segments) == 1
        assert report.segments[0].start_measure == 1
        assert report.segments[0].end_measure == 1
        # The pure-melody measure is outside any active segment.
        assert report.is_separated(2) is False
        assert assign_stream(_mk(64, 0.0, 0.5, measure_number=2), report) == "lead"

    def test_low_prior_is_soft_prior(self) -> None:
        """A too-tight prior never suppresses a real split (soft fallback).

        The natural boundary between riff (43) and melody (64) is ~53.  A prior
        window (40, 50) contains no valid split midpoint, so the detector falls
        back to the unconstrained split instead of dropping the separation.
        """
        report = detect_separation(_riff_melody_measure(), low_prior=(40, 50))
        assert report.detected is True
        # A prior that contains the boundary keeps the split inside it.
        report2 = detect_separation(_riff_melody_measure(), low_prior=(40, 55))
        assert report2.detected is True
        assert 40 <= report2.segments[0].split_pitch <= 55


class _TuningStub:
    """Minimal tuning view exposing only ``string_pitches``."""

    def __init__(self, pitches: list[int]) -> None:
        self.string_pitches = pitches


class TestRiffRegisterPrior:
    """KB-informed riff-register window derivation."""

    _STANDARD = _TuningStub([40, 45, 50, 55, 59, 64])  # low → high

    def test_neutral_bias_defaults_to_four_strings(self) -> None:
        prior = _riff_register_prior(self._STANDARD, 1.0)
        assert prior == (40, 55)

    def test_high_bias_widens_window(self) -> None:
        # metal (bias 1.25) → 5 riff strings → up to B3 (59).
        prior = _riff_register_prior(self._STANDARD, 1.25)
        assert prior == (40, 59)

    def test_low_bias_narrows_window(self) -> None:
        # funk (bias 0.85) → 3 riff strings → up to D3 (50).
        prior = _riff_register_prior(self._STANDARD, 0.85)
        assert prior == (40, 50)

    def test_returns_none_without_tuning(self) -> None:
        assert _riff_register_prior(None, 1.0) is None
        assert _riff_register_prior(_TuningStub([]), 1.0) is None

    def test_window_capped_by_string_count(self) -> None:
        # A 3-string instrument can't reach 5 riff strings.
        prior = _riff_register_prior(_TuningStub([40, 45, 50]), 2.0)
        assert prior == (40, 50)


class TestAssignStream:
    def test_assign_lead_and_rhythm_within_segment(self) -> None:
        report = detect_separation(_riff_melody_measure())
        assert report.segments
        segment = report.segments[0]
        assert assign_stream(_mk(40, 0.0, 0.25), report) == "rhythm"
        assert assign_stream(_mk(64, 0.0, 1.0), report) == "lead"

    def test_assign_lead_outside_segment(self) -> None:
        report = SeparationReport(
            detected=True,
            segments=[
                SeparationSegment(
                    start_measure=2,
                    end_measure=2,
                    split_pitch=52,
                    low_note_count=3,
                    high_note_count=3,
                    confidence=0.8,
                    features={},
                    reason="test",
                )
            ],
            total_confidence=0.8,
            warnings=[],
        )
        # Measure 1 is not covered → single track → lead.
        assert assign_stream(_mk(40, 0.0, 0.25, measure_number=1), report) == "lead"
        assert assign_stream(_mk(64, 0.0, 0.25, measure_number=1), report) == "lead"
        # Measure 2 is covered → split by pitch.
        assert assign_stream(_mk(40, 0.0, 0.25, measure_number=2), report) == "rhythm"
        assert assign_stream(_mk(64, 0.0, 0.25, measure_number=2), report) == "lead"

    def test_report_helpers(self) -> None:
        report = SeparationReport(
            detected=True,
            segments=[
                SeparationSegment(
                    start_measure=3,
                    end_measure=4,
                    split_pitch=50,
                    low_note_count=3,
                    high_note_count=3,
                    confidence=0.8,
                    features={},
                    reason="test",
                )
            ],
            total_confidence=0.8,
            warnings=[],
        )
        assert report.is_separated(3) is True
        assert report.is_separated(4) is True
        assert report.is_separated(2) is False
        assert report.split_pitch_for(3) == 50
        assert report.split_pitch_for(2) is None
