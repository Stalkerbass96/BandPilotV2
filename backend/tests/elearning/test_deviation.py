"""Tests for DeviationCalculator — metric computation."""

import pytest

from fretpilot.elearning.deviation import DeviationCalculator
from fretpilot.elearning.models import (
    AlignedNotePair,
    GroundTruthNote,
    GroundTruthTab,
    EvaluationMetrics,
)
from fretpilot.ir.models import (
    GuitarMeasure,
    GuitarNoteEvent,
    GuitarProjectIR,
    GuitarTrackIR,
    IRFingering,
    NoteConfidence,
    PerformanceTiming,
    ScoreTiming,
)


def _make_gt(pitch, string, fret, hp=1, measure=1, beat=0.0):
    return GroundTruthNote(measure, beat, pitch, string, fret, hp, 1.0, False, 95)


def _make_pair(gt, ir_string, ir_fret, ir_hp, conf=1.0):
    return AlignedNotePair(
        gt_note=gt,
        ir_string=ir_string, ir_fret=ir_fret, ir_hand_position=ir_hp,
        alignment_confidence=conf, beat_delta=0.0, ir_note_id="n-1",
    )


def _make_ir(note_count=1):
    """Build a minimal IR for testing."""
    measures = [GuitarMeasure(
        number=1, start_beat=0, duration_beats=4, numerator=4, denominator=4,
    )]
    for i in range(note_count):
        measures[0].events.append(GuitarNoteEvent(
            id=f"n-{i+1}", source_note_index=i, pitch=64,
            score=ScoreTiming(0, 1.0, 1, 0.0),
            performance=PerformanceTiming(0, 1.0, 95),
            fingering=IRFingering(string=1, fret=0, hand_position=1),
            confidence=NoteConfidence(1.0, 1.0),
        ))
    track = GuitarTrackIR(
        id="g", name="T", source_track_index=0, role="lead",
        tuning=[40,45,50,55,59,64], fret_count=24, measures=measures,
    )
    return GuitarProjectIR(
        title="T", source="t.mid", tempo_map=[], time_signatures=[],
        tracks=[track],
    )


def test_perfect_match():
    """All metrics should be 1.0 (except deviation=0) for identical fingerings."""
    gt = _make_gt(64, 1, 0, 1)
    pair = _make_pair(gt, ir_string=1, ir_fret=0, ir_hp=1)

    gt_tab = GroundTruthTab("t.gp5", "T", "rock", 120, (4, 4),
                           [40,45,50,55,59,64], [gt], "T")
    ir = _make_ir(1)

    calc = DeviationCalculator()
    report = calc.calculate([pair], gt_tab, ir)

    assert report.metrics.string_match_rate == 1.0
    assert report.metrics.fret_match_rate == 1.0
    assert report.metrics.overall_fingering_accuracy == 1.0
    assert report.metrics.position_deviation == 0.0


def test_string_mismatch():
    """String match rate < 1.0 when string differs."""
    gt = _make_gt(64, 1, 0, 1)
    pair = _make_pair(gt, ir_string=2, ir_fret=0, ir_hp=1)  # Wrong string

    gt_tab = GroundTruthTab("t.gp5", "T", "rock", 120, (4, 4),
                           [40,45,50,55,59,64], [gt], "T")
    ir = _make_ir(1)

    calc = DeviationCalculator()
    report = calc.calculate([pair], gt_tab, ir)

    assert report.metrics.string_match_rate == 0.0
    assert report.metrics.fret_match_rate == 1.0  # Fret still matches
    assert report.metrics.overall_fingering_accuracy == 0.0  # Both must match


def test_position_deviation():
    """Position deviation measures hand_position difference."""
    gt = _make_gt(64, 1, 5, 5)  # hand_position = 5
    pair = _make_pair(gt, ir_string=1, ir_fret=5, ir_hp=3)  # hp = 3

    gt_tab = GroundTruthTab("t.gp5", "T", "rock", 120, (4, 4),
                           [40,45,50,55,59,64], [gt], "T")
    ir = _make_ir(1)

    calc = DeviationCalculator()
    report = calc.calculate([pair], gt_tab, ir)

    assert report.metrics.position_deviation == 2.0  # |5-3| = 2


def test_empty_pairs():
    """Empty pairs produce zeroed metrics."""
    gt_tab = GroundTruthTab("t.gp5", "T", "rock", 120, (4, 4),
                           [40,45,50,55,59,64], [], "T")
    ir = _make_ir(0)

    calc = DeviationCalculator()
    report = calc.calculate([], gt_tab, ir)

    assert report.metrics.total_aligned == 0
    assert report.metrics.string_match_rate == 0.0


def test_per_note_details():
    """Per-note details include all expected fields."""
    gt = _make_gt(64, 1, 0, 1)
    pair = _make_pair(gt, ir_string=1, ir_fret=0, ir_hp=1)

    gt_tab = GroundTruthTab("t.gp5", "T", "rock", 120, (4, 4),
                           [40,45,50,55,59,64], [gt], "T")
    ir = _make_ir(1)

    calc = DeviationCalculator()
    report = calc.calculate([pair], gt_tab, ir)

    assert len(report.per_note) == 1
    entry = report.per_note[0]
    assert entry["pitch"] == 64
    assert entry["gt_string"] == 1
    assert entry["ir_string"] == 1
    assert entry["string_match"] is True
    assert entry["fret_match"] is True
