"""BandPilot SongIR 2.0 — canonical multi-instrument score contract.

SongIR separates immutable source metadata, musical analysis, notation,
performance, techniques, validation, and reproducibility pins. Instrument
pipelines may keep their focused working IRs, but persisted/exported products
must pass through this contract so every format observes the same score truth.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from fretpilot.ir.models import (
    IRKnowledgeReference,
    IRTempoEvent,
    IRTimeSignatureEvent,
    NoteConfidence,
    ScoreTiming,
    Transformation,
)

SONG_SCHEMA_VERSION = "2.0"


@dataclass(slots=True)
class SourceTrackIR:
    index: int
    name: str
    instrument_name: str | None
    program: int | None
    note_count: int


@dataclass(slots=True)
class SourceLayer:
    filename: str
    sha256: str
    midi_type: int
    ticks_per_beat: int
    note_count: int
    duration_beats: float
    tracks: list[SourceTrackIR] = field(default_factory=list)


@dataclass(slots=True)
class TrackAssignment:
    source_track_index: int
    family: str
    confidence: float
    reason: str
    user_overridden: bool = False


@dataclass(slots=True)
class UnresolvedSourceEvent:
    """A source note deliberately excluded from professional notation.

    Exclusion is explicit and reproducible: exporters never invent a playable
    position for an impossible note and never silently discard source data.
    """

    source_track_index: int
    source_note_index: int
    pitch: int
    start_beat: float
    duration_beats: float
    reason: str


@dataclass(slots=True)
class AnalysisLayer:
    style_label: str = "unknown"
    key_signature: str | None = None
    sections: list[dict[str, Any]] = field(default_factory=list)
    chord_symbols: list[dict[str, Any]] = field(default_factory=list)
    track_assignments: list[TrackAssignment] = field(default_factory=list)
    unresolved_events: list[UnresolvedSourceEvent] = field(default_factory=list)


@dataclass(slots=True)
class SourceNoteReference:
    source_track_index: int
    source_note_index: int
    origin: str = "midi"


@dataclass(slots=True)
class InstrumentRealization:
    """Typed union-like realization shared by instrument families.

    Fields which do not apply to a family remain ``None``. ``kind`` is the
    discriminator and is always one of guitar, drums, bass, keys, or generic.
    """

    kind: str
    string: int | None = None
    fret: int | None = None
    fretting_digit: int | None = None
    hand_position: int | None = None
    piece: str | None = None
    sticking: str | None = None
    hit_technique: str | None = None
    hand: str | None = None
    finger: int | None = None
    pedal: str | None = None


@dataclass(slots=True)
class ScoreEventIR:
    id: str
    pitch: int
    score: ScoreTiming
    source: SourceNoteReference
    realization: InstrumentRealization
    technique_ids: list[str] = field(default_factory=list)
    confidence: NoteConfidence | None = None


@dataclass(slots=True)
class ScoreMeasureIR:
    number: int
    start_beat: float
    duration_beats: float
    numerator: int
    denominator: int
    events: list[ScoreEventIR] = field(default_factory=list)
    annotations: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class InstrumentTrackIR:
    id: str
    name: str
    family: str
    role: str
    source_track_indices: list[int]
    instrument: dict[str, Any]
    measures: list[ScoreMeasureIR] = field(default_factory=list)


@dataclass(slots=True)
class TechniqueIR:
    """A note relation or span such as slide, bend, palm mute, or legato."""

    id: str
    type: str
    note_ids: list[str]
    confidence: float
    reason: str
    parameters: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class ScoreLayer:
    tempo_map: list[IRTempoEvent] = field(default_factory=list)
    time_signatures: list[IRTimeSignatureEvent] = field(default_factory=list)
    tracks: list[InstrumentTrackIR] = field(default_factory=list)
    techniques: list[TechniqueIR] = field(default_factory=list)


@dataclass(slots=True)
class PerformanceEventIR:
    note_id: str
    start_beat: float
    duration_beats: float
    velocity: int
    controls: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class PerformanceLayer:
    profile_id: str = "source-preserved"
    events: list[PerformanceEventIR] = field(default_factory=list)


@dataclass(slots=True)
class ValidationIssue:
    code: str
    severity: str
    message: str
    track_id: str | None = None
    note_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ValidationLayer:
    status: str = "not_validated"
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues)


@dataclass(slots=True)
class ReproducibilityPins:
    application_version: str
    knowledge_snapshot: str
    model_provider: str = "none"
    model_name: str = "none"
    prompt_version: str = "none"
    sound_profile: str = "none"


@dataclass(slots=True)
class SongIR:
    title: str
    source: SourceLayer
    analysis: AnalysisLayer
    score: ScoreLayer
    performance: PerformanceLayer
    validation: ValidationLayer
    pins: ReproducibilityPins
    schema_version: str = SONG_SCHEMA_VERSION
    arrangement_mode: str = "faithful"
    knowledge: IRKnowledgeReference | None = None
    changes: list[Transformation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "SONG_SCHEMA_VERSION",
    "AnalysisLayer",
    "InstrumentRealization",
    "InstrumentTrackIR",
    "PerformanceEventIR",
    "PerformanceLayer",
    "ReproducibilityPins",
    "ScoreEventIR",
    "ScoreLayer",
    "ScoreMeasureIR",
    "SongIR",
    "SourceLayer",
    "SourceNoteReference",
    "SourceTrackIR",
    "TechniqueIR",
    "TrackAssignment",
    "UnresolvedSourceEvent",
    "ValidationIssue",
    "ValidationLayer",
]
