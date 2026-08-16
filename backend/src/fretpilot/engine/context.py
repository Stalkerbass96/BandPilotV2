"""Pipeline intermediate types and context.

These dataclasses flow between the 7 repair stages. Each stage reads from
and writes to the PipelineContext, keeping stages decoupled and independently
testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fretpilot.ir.models import Transformation
from fretpilot.knowledge.tunings import GuitarTuning
from fretpilot.midi.models import NormalizedTimeline, NormalizedTrack

if TYPE_CHECKING:
    from fretpilot.ai.providers.base import RewriteAdvisor
    from fretpilot.detection.separation import SeparationReport
    from fretpilot.knowledge.registry import KnowledgeRegistry


# ─── Intermediate note types (one per stage group) ───


@dataclass(slots=True)
class QuantizedNote:
    """Output of S1: a note with onset/duration snapped to a grid."""

    source_index: int
    pitch: int
    velocity: int
    original_start_beat: float
    original_duration_beats: float
    quantized_start_beat: float
    quantized_duration_beats: float
    confidence: float


@dataclass(slots=True)
class MeasureBoundary:
    """A measure boundary computed from tempo/time-signature maps."""

    number: int
    start_beat: float
    end_beat: float
    numerator: int
    denominator: int


@dataclass(slots=True)
class SplitNote:
    """Output of S2: a note fragment, possibly split across measures."""

    source_index: int
    pitch: int
    velocity: int
    start_beat: float
    duration_beats: float
    measure_number: int
    beat_in_measure: float
    tie_in: bool
    tie_out: bool
    original_start_beat: float
    original_duration_beats: float
    voice: int = 1
    let_ring: bool = False
    legato_candidate: bool = False


@dataclass(slots=True)
class VoicedNote:
    """Output of S4: a note with final voice assignment."""

    source_index: int
    pitch: int
    velocity: int
    start_beat: float
    duration_beats: float
    measure_number: int
    beat_in_measure: float
    tie_in: bool
    tie_out: bool
    original_start_beat: float
    original_duration_beats: float
    voice: int
    let_ring: bool
    legato_candidate: bool
    stream: str = "lead"  # "lead" | "rhythm" — assigned by stream_separation


@dataclass(slots=True)
class FingeredNote:
    """Output of S5: a note with string/fret/hand-position assignment."""

    source_index: int
    pitch: int
    velocity: int
    start_beat: float
    duration_beats: float
    measure_number: int
    beat_in_measure: float
    tie_in: bool
    tie_out: bool
    original_start_beat: float
    original_duration_beats: float
    voice: int
    let_ring: bool
    legato_candidate: bool
    string: int | None
    fret: int | None
    fretting_digit: int | None
    hand_position: int | None
    fingering_confidence: float
    stream: str = "lead"  # "lead" | "rhythm" — carried through from VoicedNote


@dataclass(slots=True)
class ArticulationDecision:
    """Output of S6: an articulation inference for a note."""

    note_index: int  # source_index
    type: str
    confidence: float
    reason: str
    source_note_id: str | None = None
    parameters: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class NoteRewriteDecision:
    """An LLM-proposed note rewrite decision (validated by deterministic code)."""

    index: int
    operation: str  # delete / transpose / insert
    pitch: int | None = None
    reason: str = ""


# ─── Pipeline context ───


@dataclass
class PipelineContext:
    """Mutable context that flows between pipeline stages."""

    timeline: NormalizedTimeline
    track: NormalizedTrack
    knowledge: "KnowledgeRegistry"
    style_label: str
    midi_fidelity: float
    advisor: "RewriteAdvisor | None"
    track_id: str = "guitar-1"
    track_role: str = "unknown"
    source_track_index: int | None = None
    degraded_mode: bool = False
    tuning: GuitarTuning | None = None  # resolved tuning (knowledge.tunings.GuitarTuning)

    # Stage outputs
    quantized_notes: list[QuantizedNote] = field(default_factory=list)
    measures: list[MeasureBoundary] = field(default_factory=list)
    split_notes: list[SplitNote] = field(default_factory=list)
    voiced_notes: list[VoicedNote] = field(default_factory=list)
    fingered_notes: list[FingeredNote] = field(default_factory=list)
    separation: "SeparationReport | None" = None
    articulation_decisions: list[ArticulationDecision] = field(default_factory=list)
    rewrite_decisions: list[NoteRewriteDecision] = field(default_factory=list)
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
    "QuantizedNote",
    "MeasureBoundary",
    "SplitNote",
    "VoicedNote",
    "FingeredNote",
    "ArticulationDecision",
    "NoteRewriteDecision",
    "PipelineContext",
]
