"""E-learning module — learning loop for knowledge system.

Implements the round-trip evaluation pipeline:
    GP tab → MIDI → FretPilot pipeline → reconstructed GP5 → compare with original

Key components:
    - GPReader: parse GP3/GP4/GP5 files to extract ground truth fingering
    - GPMidiConverter: convert GP songs to MIDI for pipeline input
    - PipelineRunner: run FretPilot pipeline on MIDI
    - NoteAligner: align ground truth and reconstructed notes
    - DeviationCalculator: compute deviation metrics
    - BatchEvaluator: orchestrate batch evaluation with CLI
    - StatsExtractor / PriorsDeriver: extract knowledge from ground truth
    - KBWriter: write empirical priors back to knowledge base
"""

from fretpilot.elearning.models import (
    AlignedNotePair,
    BatchEvaluationResult,
    DerivedPriors,
    EvaluationMetrics,
    EvaluationReport,
    GroundTruthNote,
    GroundTruthTab,
    StyleStats,
)

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
