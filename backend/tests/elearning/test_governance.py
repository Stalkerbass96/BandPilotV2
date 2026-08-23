"""Learning-corpus rights, split isolation, and promotion quality gates."""

from __future__ import annotations

import pytest

from fretpilot.elearning.governance import (
    CorpusGovernanceError,
    assess_promotion,
    validate_corpus,
)
from fretpilot.elearning.models import CorpusProvenance, ProfessionalScoreCorpus


def _corpus(*, digest: str, split: str, permitted: bool = True):
    return ProfessionalScoreCorpus(
        file_path="score.gp5",
        title="Score",
        artist="Artist",
        style_label="rock",
        tempo_map=[{"beat": 0.0, "bpm": 120.0}],
        time_signature_map=[{"beat": 0.0, "numerator": 4, "denominator": 4}],
        tracks=[],
        provenance=CorpusProvenance(
            source_id=f"{digest}-{split}",
            content_sha256=digest,
            license_id="licensed-corpus-v1",
            permitted_for_training=permitted,
            quality_tier="expert",
            split=split,
        ),
    )


def test_corpus_requires_training_rights() -> None:
    with pytest.raises(CorpusGovernanceError, match="rights"):
        validate_corpus([_corpus(digest="abc", split="train", permitted=False)])


def test_corpus_rejects_train_test_content_leakage() -> None:
    with pytest.raises(CorpusGovernanceError, match="more than one dataset split"):
        validate_corpus(
            [
                _corpus(digest="same", split="train"),
                _corpus(digest="same", split="test"),
            ]
        )


def test_promotion_gate_accepts_measured_non_regression() -> None:
    assessment = assess_promotion(
        source_count=8,
        comparison={
            "result_b_summary": {"successful": 5},
            "overall_delta": {
                "overall_fingering_accuracy": 0.02,
                "pitch_accuracy": 0.0,
                "chord_shape_match": 0.01,
                "position_deviation": -0.2,
            },
        },
    )
    assert assessment.passed is True
    assert assessment.reasons == []


def test_promotion_gate_blocks_accuracy_regression() -> None:
    assessment = assess_promotion(
        source_count=8,
        comparison={
            "result_b_summary": {"successful": 5},
            "overall_delta": {
                "overall_fingering_accuracy": -0.01,
                "pitch_accuracy": 0.0,
                "chord_shape_match": 0.0,
                "position_deviation": 0.0,
            },
        },
    )
    assert assessment.passed is False
    assert "overall fingering accuracy regressed" in assessment.reasons
