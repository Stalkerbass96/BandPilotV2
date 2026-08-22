"""Core data models for the e-learning module.

All models use ``@dataclass(slots=True)`` consistent with the project style.
Models are designed to be JSON-serializable for report persistence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class GroundTruthNote:
    """A single note extracted from a professional GP tab (ground truth).

    String numbering: 1=high E, 6=low E (same as FretPilot IR).
    """

    measure_number: int
    beat_in_measure: float
    pitch: int
    string: int
    fret: int
    hand_position: int
    duration_beats: float
    is_tie: bool
    velocity: int


@dataclass(slots=True)
class GroundTruthTab:
    """Complete ground truth extracted from one GP file."""

    file_path: str
    title: str
    style_label: str
    tempo_bpm: float
    time_signature: tuple[int, int]
    tuning_pitches: list[int]  # low → high (string 6 → string 1)
    notes: list[GroundTruthNote]
    track_name: str

    @property
    def note_count(self) -> int:
        return len(self.notes)

    @property
    def measure_count(self) -> int:
        return max((n.measure_number for n in self.notes), default=0)


@dataclass(slots=True)
class AlignedNotePair:
    """An aligned pair of ground truth note and reconstructed IR note."""

    gt_note: GroundTruthNote
    ir_string: int | None
    ir_fret: int | None
    ir_hand_position: int | None
    alignment_confidence: float
    beat_delta: float
    ir_note_id: str


@dataclass(slots=True)
class EvaluationMetrics:
    """Evaluation metrics for a single file or aggregated across files."""

    # Core metrics
    string_match_rate: float
    fret_match_rate: float
    position_deviation: float
    chord_shape_match: float
    overall_fingering_accuracy: float
    # Auxiliary metrics
    pitch_accuracy: float
    note_count_match: float
    measure_alignment_rate: float
    # Statistics
    total_aligned: int
    total_gt_notes: int
    total_ir_notes: int
    total_unmatched: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def empty(cls) -> EvaluationMetrics:
        return cls(
            string_match_rate=0.0,
            fret_match_rate=0.0,
            position_deviation=0.0,
            chord_shape_match=0.0,
            overall_fingering_accuracy=0.0,
            pitch_accuracy=0.0,
            note_count_match=0.0,
            measure_alignment_rate=0.0,
            total_aligned=0,
            total_gt_notes=0,
            total_ir_notes=0,
            total_unmatched=0,
        )


@dataclass(slots=True)
class EvaluationReport:
    """Complete evaluation report for a single GP file."""

    file_path: str
    style_label: str
    metrics: EvaluationMetrics
    per_note: list[dict[str, Any]] = field(default_factory=list)
    per_measure: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file_path,
            "style": self.style_label,
            "timestamp": self.timestamp,
            "metrics": self.metrics.to_dict(),
            "per_note": self.per_note,
            "per_measure": self.per_measure,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvaluationReport:
        metrics_data = data.get("metrics", {})
        return cls(
            file_path=data.get("file", ""),
            style_label=data.get("style", "unknown"),
            metrics=EvaluationMetrics(**metrics_data),
            per_note=data.get("per_note", []),
            per_measure=data.get("per_measure", []),
            warnings=data.get("warnings", []),
            timestamp=data.get("timestamp", ""),
        )


@dataclass(slots=True)
class BatchEvaluationResult:
    """Aggregated results from batch evaluation."""

    total_files: int
    successful: int
    failed: int
    skipped: int
    overall_metrics: EvaluationMetrics
    per_style: dict[str, EvaluationMetrics]
    worst_files: list[dict[str, Any]]
    timestamp: str
    kb_snapshot_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_files": self.total_files,
            "successful": self.successful,
            "failed": self.failed,
            "skipped": self.skipped,
            "overall_metrics": self.overall_metrics.to_dict(),
            "per_style": {k: v.to_dict() for k, v in self.per_style.items()},
            "worst_files": self.worst_files,
            "timestamp": self.timestamp,
            "kb_snapshot_version": self.kb_snapshot_version,
        }


@dataclass(slots=True)
class StyleStats:
    """Fingering pattern statistics for a style group."""

    style_label: str
    sample_count: int
    total_notes: int
    open_string_rate: float
    hand_position_distribution: dict[int, float]
    string_distribution: dict[int, float]
    avg_string_skip: float
    chord_shape_top_k: dict[str, int]
    note_overlap_rate: float
    staccato_rate: float
    fret_distribution: dict[int, float]


@dataclass(slots=True)
class DerivedPriors:
    """KB2 priors derived from empirical statistics."""

    style_label: str
    knowledge_id: str
    payload: dict[str, Any]
    source_ids: list[str]
    confidence: float
    derivation_method: str
    stats_snapshot: dict[str, Any]
    # Target KB domain file and entry kind. Guitar fingering priors default
    # to "kb2_performance"; drum sticking priors use "drum_kb2_sticking".
    domain: str = "kb2_performance"
    kind: str = "fingering_priors"


__all__ = [
    "GroundTruthNote",
    "GroundTruthTab",
    "AlignedNotePair",
    "EvaluationMetrics",
    "EvaluationReport",
    "BatchEvaluationResult",
    "StyleStats",
    "DerivedPriors",
]
