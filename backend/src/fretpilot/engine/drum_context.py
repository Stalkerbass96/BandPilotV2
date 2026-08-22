"""Drum pipeline intermediate types and context.

Mirrors engine/context.py but with drum-specific intermediate note types:
  S1/S2 reuse the guitar QuantizedNote / SplitNote (generic MIDI timing).
  S3  → MappedNote      (pitch → drum piece)
  S4  → PatternNote     (beat/fill classification per measure)
  S5  → VelocityNote    (velocity normalization, ghost/accent detection)
  S6  → StickedNote     (R/L hand sticking suggestion)
  S7  → NotatedNote     (notation cleanup, redundant hit removal)
  S8  → DrumProjectIR   (final assembly)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fretpilot.engine.context import MeasureBoundary, QuantizedNote, SplitNote
from fretpilot.ir.models import Transformation
from fretpilot.midi.models import NormalizedTimeline, NormalizedTrack

if TYPE_CHECKING:
    from fretpilot.drum.drumkit import DrumKit
    from fretpilot.knowledge.registry import KnowledgeRegistry


# ─── Intermediate note types (drum-specific stages S3–S7) ───


@dataclass(slots=True)
class MappedNote:
    """Output of S3 (DrumMap): a split note with its drum piece resolved.

    Attributes:
        source_index: Index into the source MIDI track's note list.
        pitch: Original MIDI pitch.
        velocity: MIDI velocity (1–127).
        start_beat: Quantized start beat.
        duration_beats: Quantized duration in beats.
        measure_number: 1-indexed measure number.
        beat_in_measure: Beat offset within the measure.
        piece: Mapped drum piece name (e.g. "kick", "snare").
        piece_category: Category of the piece ("kick", "snare", "tom", ...).
        original_start_beat: Original (pre-quantize) start beat.
        original_duration_beats: Original (pre-quantize) duration.
    """

    source_index: int
    pitch: int
    velocity: int
    start_beat: float
    duration_beats: float
    measure_number: int
    beat_in_measure: float
    piece: str
    piece_category: str
    original_start_beat: float
    original_duration_beats: float


@dataclass(slots=True)
class PatternNote:
    """Output of S4 (PatternDetect): a mapped note with pattern classification.

    Attributes:
        mapped: The underlying MappedNote data.
        measure_pattern: Classification of the containing measure —
            "beat", "fill", "transition", or "unknown".
        is_fill: Convenience flag (True if measure_pattern == "fill").
    """

    mapped: MappedNote
    measure_pattern: str = "unknown"
    is_fill: bool = False


@dataclass(slots=True)
class VelocityNote:
    """Output of S5 (Velocity): a pattern note with normalized velocity.

    Attributes:
        pattern: The underlying PatternNote data.
        original_velocity: Velocity before normalization.
        normalized_velocity: Velocity after per-piece normalization (1–127).
        technique: Velocity-derived technique — "normal", "ghost", or "accent".
    """

    pattern: PatternNote
    original_velocity: int
    normalized_velocity: int
    technique: str = "normal"


@dataclass(slots=True)
class StickedNote:
    """Output of S6 (Sticking): a velocity note with R/L hand assignment.

    Attributes:
        velocity: The underlying VelocityNote data.
        sticking: Suggested hand — "R", "L", "both" (for flams), or "".
        stroke_type: Stroke classification — "single", "double", "flam",
            "drag", or "roll".
    """

    velocity: VelocityNote
    sticking: str = ""
    stroke_type: str = "single"


@dataclass(slots=True)
class NotatedNote:
    """Output of S7 (Notation): a sticked note after notation cleanup.

    Attributes:
        sticked: The underlying StickedNote data.
        is_redundant: True if this note was marked redundant (same piece,
            same tick as another hit) and should be excluded from export.
        rest_optimized: True if a rest was inserted/optimized at this position.
    """

    sticked: StickedNote
    is_redundant: bool = False
    rest_optimized: bool = False


# ─── Pipeline context ───


@dataclass
class DrumPipelineContext:
    """Mutable context that flows between drum pipeline stages.

    Reuses QuantizedNote and SplitNote from the guitar pipeline for S1/S2
    (generic MIDI timing). Stages S3–S7 use drum-specific intermediate types.

    Attributes:
        timeline: The full normalized MIDI timeline.
        track: The drum track being repaired.
        knowledge: Knowledge registry for KB lookups.
        style_label: Detected style label (e.g. "metal", "rock").
        midi_fidelity: MIDI fidelity score (0.0–1.0).
        track_id: Stable track identifier.
        track_role: Role label ("kit", "perc", ...).
        source_track_index: Index into the source MIDI track list.
        degraded_mode: Whether the pipeline is running in degraded (no-KB) mode.
        kit: Resolved DrumKit.
    """

    timeline: NormalizedTimeline
    track: NormalizedTrack
    knowledge: "KnowledgeRegistry"
    style_label: str
    midi_fidelity: float
    track_id: str = "drum-1"
    track_role: str = "kit"
    source_track_index: int | None = None
    degraded_mode: bool = False
    kit: "DrumKit | None" = None

    # Stage outputs — S1/S2 (reused from guitar pipeline)
    quantized_notes: list[QuantizedNote] = field(default_factory=list)
    measures: list[MeasureBoundary] = field(default_factory=list)
    split_notes: list[SplitNote] = field(default_factory=list)

    # Stage outputs — S3–S7 (drum-specific)
    mapped_notes: list[MappedNote] = field(default_factory=list)
    pattern_notes: list[PatternNote] = field(default_factory=list)
    velocity_notes: list[VelocityNote] = field(default_factory=list)
    sticked_notes: list[StickedNote] = field(default_factory=list)
    notated_notes: list[NotatedNote] = field(default_factory=list)

    # Measure pattern classifications (measure_number → pattern label)
    measure_patterns: dict[int, str] = field(default_factory=dict)

    # Detected drum style
    detected_style: str = "unknown"

    # Provenance
    transformations: list[Transformation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stage_progress: dict[str, bool] = field(default_factory=dict)

    def record_stage(self, name: str) -> None:
        """Mark a stage as completed."""
        self.stage_progress[name] = True

    def add_transformation(
        self,
        *,
        stage: str,
        source_note_index: int,
        before: dict[str, Any],
        after: dict[str, Any],
        confidence: float,
        reason: str,
        knowledge_ref: str | None = None,
    ) -> None:
        """Append a Transformation record with an auto-incremented ID."""
        index = len(self.transformations)
        self.transformations.append(
            Transformation(
                id=f"chg-{index + 1:05d}",
                stage=stage,
                source_note_index=source_note_index,
                before=before,
                after=after,
                confidence=confidence,
                reason=reason,
                knowledge_ref=knowledge_ref,
            )
        )


__all__ = [
    "MappedNote",
    "PatternNote",
    "VelocityNote",
    "StickedNote",
    "NotatedNote",
    "DrumPipelineContext",
]
