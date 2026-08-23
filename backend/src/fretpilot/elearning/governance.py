"""Quality and data-rights gates for the professional-score learning loop."""

from __future__ import annotations

from dataclasses import dataclass, field

from fretpilot.elearning.models import ProfessionalScoreCorpus


class CorpusGovernanceError(ValueError):
    """Raised when learning data or a candidate snapshot is not promotable."""


@dataclass(frozen=True, slots=True)
class PromotionPolicy:
    min_sources: int = 5
    min_evaluated_files: int = 3
    min_fingering_delta: float = 0.0
    min_pitch_delta: float = -0.005
    min_chord_shape_delta: float = -0.01
    max_position_deviation_delta: float = 0.1


@dataclass(slots=True)
class PromotionAssessment:
    passed: bool
    reasons: list[str] = field(default_factory=list)


def validate_corpus(corpus: list[ProfessionalScoreCorpus]) -> None:
    """Reject unlicensed, unreviewed, or train/eval-leaking corpus inputs."""

    if not corpus:
        raise CorpusGovernanceError("The corpus is empty.")
    splits_by_hash: dict[str, set[str]] = {}
    for song in corpus:
        provenance = song.provenance
        if provenance is None:
            raise CorpusGovernanceError(f"Missing provenance for {song.file_path}.")
        if not provenance.permitted_for_training or provenance.license_id == "unverified":
            raise CorpusGovernanceError(
                f"Training rights are not verified for {provenance.source_id}."
            )
        if provenance.quality_tier not in {"reviewed", "expert"}:
            raise CorpusGovernanceError(
                f"Source {provenance.source_id} has not passed score-quality review."
            )
        if provenance.split not in {"train", "validation", "test"}:
            raise CorpusGovernanceError(
                f"Invalid corpus split {provenance.split!r} for {provenance.source_id}."
            )
        splits_by_hash.setdefault(provenance.content_sha256, set()).add(provenance.split)

    leaked = [digest for digest, splits in splits_by_hash.items() if len(splits) > 1]
    if leaked:
        raise CorpusGovernanceError(
            "Identical score content appears in more than one dataset split."
        )


def assess_promotion(
    *,
    source_count: int,
    comparison: dict,
    policy: PromotionPolicy = PromotionPolicy(),
) -> PromotionAssessment:
    """Apply deterministic no-regression gates to an A/B evaluation result."""

    reasons: list[str] = []
    candidate_files = int(comparison.get("result_b_summary", {}).get("successful", 0))
    deltas = comparison.get("overall_delta", {})
    checks = (
        (source_count >= policy.min_sources, f"requires >= {policy.min_sources} sources"),
        (
            candidate_files >= policy.min_evaluated_files,
            f"requires >= {policy.min_evaluated_files} evaluated files",
        ),
        (
            float(deltas.get("overall_fingering_accuracy", -1.0))
            >= policy.min_fingering_delta,
            "overall fingering accuracy regressed",
        ),
        (
            float(deltas.get("pitch_accuracy", -1.0)) >= policy.min_pitch_delta,
            "pitch accuracy regressed beyond tolerance",
        ),
        (
            float(deltas.get("chord_shape_match", -1.0))
            >= policy.min_chord_shape_delta,
            "chord-shape accuracy regressed beyond tolerance",
        ),
        (
            float(deltas.get("position_deviation", 1.0))
            <= policy.max_position_deviation_delta,
            "hand-position deviation regressed beyond tolerance",
        ),
    )
    reasons.extend(message for passed, message in checks if not passed)
    return PromotionAssessment(passed=not reasons, reasons=reasons)


__all__ = [
    "CorpusGovernanceError",
    "PromotionAssessment",
    "PromotionPolicy",
    "assess_promotion",
    "validate_corpus",
]
