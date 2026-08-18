"""Tests for NoteAligner — ground truth vs IR note alignment."""

import pytest

from fretpilot.elearning.models import (
    AlignedNotePair,
    GroundTruthNote,
    GroundTruthTab,
)
from fretpilot.elearning.note_aligner import NoteAligner
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


def _make_gt_note(measure, beat, pitch, string=1, fret=0, hp=1):
    return GroundTruthNote(measure, beat, pitch, string, fret, hp, 1.0, False, 95)


def _make_ir_note(note_id, measure, beat, pitch, string=1, fret=0, hp=1):
    return GuitarNoteEvent(
        id=note_id,
        source_note_index=int(note_id.split("-")[1]) if "-" in note_id else 0,
        pitch=pitch,
        score=ScoreTiming(
            start_beat=measure * 4 + beat,
            duration_beats=1.0,
            measure_number=measure,
            beat_in_measure=beat,
        ),
        performance=PerformanceTiming(
            source_start_beat=measure * 4 + beat,
            source_duration_beats=1.0,
            velocity=95,
        ),
        fingering=IRFingering(string=string, fret=fret, hand_position=hp),
        confidence=NoteConfidence(rhythm=1.0, fingering=1.0),
    )


def _make_ir(notes):
    """Build a minimal IR from a list of GuitarNoteEvent."""
    measures_map = {}
    for n in notes:
        m_num = n.score.measure_number
        if m_num not in measures_map:
            measures_map[m_num] = GuitarMeasure(
                number=m_num, start_beat=(m_num - 1) * 4,
                duration_beats=4.0, numerator=4, denominator=4,
            )
        measures_map[m_num].events.append(n)

    track = GuitarTrackIR(
        id="guitar-1", name="Test", source_track_index=0,
        role="lead", tuning=[40, 45, 50, 55, 59, 64], fret_count=24,
        measures=list(measures_map.values()),
    )
    return GuitarProjectIR(
        title="Test", source="test.mid", tempo_map=[], time_signatures=[],
        tracks=[track],
    )


def test_perfect_alignment():
    """All notes align perfectly when GT and IR are identical."""
    gt_notes = [
        _make_gt_note(1, 0.0, 64, 1, 0, 1),
        _make_gt_note(1, 1.0, 59, 2, 0, 1),
        _make_gt_note(1, 2.0, 55, 3, 0, 1),
    ]
    ir_notes = [
        _make_ir_note("n-1", 1, 0.0, 64, 1, 0, 1),
        _make_ir_note("n-2", 1, 1.0, 59, 2, 0, 1),
        _make_ir_note("n-3", 1, 2.0, 55, 3, 0, 1),
    ]
    gt_tab = GroundTruthTab(
        "test.gp5", "Test", "rock", 120, (4, 4),
        [40, 45, 50, 55, 59, 64], gt_notes, "T",
    )
    ir = _make_ir(ir_notes)

    aligner = NoteAligner()
    pairs = aligner.align(gt_tab, ir)

    assert len(pairs) == 3
    for p in pairs:
        assert p.alignment_confidence == 1.0


def test_one_to_many():
    """One GT note matches only one IR note (greedy nearest)."""
    gt_notes = [_make_gt_note(1, 0.0, 64)]
    ir_notes = [
        _make_ir_note("n-1", 1, 0.0, 64, 1, 0, 1),
        _make_ir_note("n-2", 1, 0.1, 64, 1, 0, 1),  # close but second
    ]
    gt_tab = GroundTruthTab(
        "test.gp5", "Test", "rock", 120, (4, 4),
        [40, 45, 50, 55, 59, 64], gt_notes, "T",
    )
    ir = _make_ir(ir_notes)

    aligner = NoteAligner()
    pairs = aligner.align(gt_tab, ir)

    assert len(pairs) == 1
    assert pairs[0].ir_note_id == "n-1"  # Nearest match


def test_unmatched_outside_tolerance():
    """Notes outside beat tolerance are not matched."""
    gt_notes = [_make_gt_note(1, 0.0, 64)]
    ir_notes = [_make_ir_note("n-1", 1, 0.5, 64, 1, 0, 1)]  # 0.5 beat away > 0.25
    gt_tab = GroundTruthTab(
        "test.gp5", "Test", "rock", 120, (4, 4),
        [40, 45, 50, 55, 59, 64], gt_notes, "T",
    )
    ir = _make_ir(ir_notes)

    aligner = NoteAligner()
    pairs = aligner.align(gt_tab, ir)

    assert len(pairs) == 0


def test_partial_confidence():
    """Alignment confidence decreases with beat distance."""
    gt_notes = [_make_gt_note(1, 0.0, 64)]
    ir_notes = [_make_ir_note("n-1", 1, 0.1, 64, 1, 0, 1)]  # 0.1 beat away
    gt_tab = GroundTruthTab(
        "test.gp5", "Test", "rock", 120, (4, 4),
        [40, 45, 50, 55, 59, 64], gt_notes, "T",
    )
    ir = _make_ir(ir_notes)

    aligner = NoteAligner()
    pairs = aligner.align(gt_tab, ir)

    assert len(pairs) == 1
    assert 0.5 < pairs[0].alignment_confidence < 1.0
