"""Actual GP5 parse-back score comparison tests."""

from __future__ import annotations

from fretpilot.elearning.full_score_evaluate import FullSongRoundTripEvaluator
from fretpilot.elearning.models import GroundTruthNote, GroundTruthTab
from fretpilot.elearning.professional_evaluate import ProfessionalRoundTripEvaluator
from fretpilot.elearning.score_roundtrip import ProfessionalScoreComparator
from fretpilot.exporters.gp5 import GP5Exporter
from tests.test_exporters import _build_simple_ir


def _tab(name: str, notes: list[GroundTruthNote]) -> GroundTruthTab:
    return GroundTruthTab(
        file_path=f"{name}.gp5",
        title=name,
        style_label="rock",
        tempo_bpm=120,
        time_signature=(4, 4),
        tuning_pitches=[40, 45, 50, 55, 59, 64],
        notes=notes,
        track_name="Guitar",
    )


def _note(
    note_id: str,
    pitch: int,
    onset: float,
    string: int,
    fret: int,
    duration: float = 0.5,
) -> GroundTruthNote:
    return GroundTruthNote(
        measure_number=1,
        beat_in_measure=onset,
        pitch=pitch,
        string=string,
        fret=fret,
        hand_position=max(1, fret),
        duration_beats=duration,
        is_tie=False,
        velocity=90,
        note_id=note_id,
        absolute_start_beat=onset,
    )


def test_comparator_reports_score_semantic_differences() -> None:
    source = _tab(
        "source",
        [_note("s1", 64, 0.0, 1, 0), _note("s2", 67, 0.5, 1, 3)],
    )
    generated = _tab(
        "generated",
        [_note("g1", 64, 0.0, 2, 5), _note("g2", 69, 0.5, 1, 5)],
    )
    report = ProfessionalScoreComparator().compare(
        source, generated, generated_file="generated.gp5"
    )
    assert report.metrics.aligned_notes == 1
    assert report.metrics.note_recall == 0.5
    assert report.metrics.note_precision == 0.5
    assert report.metrics.exact_fingering_rate == 0.0
    assert report.mismatch_counts["missing_notes"] == 1
    assert report.mismatch_counts["extra_notes"] == 1


def test_evaluator_runs_real_gp5_export_and_parseback(tmp_path) -> None:
    source = tmp_path / "source.gp5"
    generated = tmp_path / "generated.gp5"
    GP5Exporter().export(_build_simple_ir(), source)

    report = ProfessionalRoundTripEvaluator().evaluate_file(
        source, generated_path=generated
    )

    assert generated.is_file()
    assert report.metrics.source_notes == 4
    assert report.metrics.generated_notes >= 4
    assert report.metrics.note_recall > 0.0
    assert report.generated_file == str(generated)


def test_full_song_evaluator_uses_canonical_product_and_gp5_parseback(tmp_path) -> None:
    source = tmp_path / "source-full.gp5"
    generated = tmp_path / "generated-full.gp5"
    GP5Exporter().export(_build_simple_ir(), source)

    report = FullSongRoundTripEvaluator().evaluate_file(
        source,
        generated_path=generated,
    )

    assert generated.is_file()
    assert report["evaluation_scope"] == "full_song_actual_product_songir_gp5_parseback"
    assert report["source_track_count"] == 1
    assert report["generated_track_count"] >= 1
    assert report["overall"]["note_recall"] > 0.0
    assert report["validation_status"] == "passed"
