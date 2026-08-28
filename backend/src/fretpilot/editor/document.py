"""ScoreDocument 3.0 — canonical editable score snapshot.

The current production workflow still persists SongIR 2.x.  ScoreDocument is
introduced as a derived, strictly serialized contract during E0 so the editor
can prove stable identity, exact score time and deterministic revision hashes
before any existing write path is migrated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction
from functools import total_ordering
from typing import Any

SCORE_DOCUMENT_SCHEMA_VERSION = "3.0"
MAX_SCORE_TIME_DENOMINATOR = 15_360


@total_ordering
@dataclass(frozen=True, slots=True, eq=False)
class Rational:
    """A normalized exact musical position or duration."""

    numerator: int
    denominator: int = 1

    def __post_init__(self) -> None:
        if isinstance(self.numerator, bool) or isinstance(self.denominator, bool):
            raise TypeError("Rational values must be integers, not booleans")
        if not isinstance(self.numerator, int) or not isinstance(self.denominator, int):
            raise TypeError("Rational numerator and denominator must be integers")
        if self.denominator == 0:
            raise ValueError("Rational denominator cannot be zero")
        value = Fraction(self.numerator, self.denominator)
        object.__setattr__(self, "numerator", value.numerator)
        object.__setattr__(self, "denominator", value.denominator)

    @classmethod
    def from_value(cls, value: Rational | int | float | str | dict[str, Any]) -> Rational:
        if isinstance(value, cls):
            return value
        if isinstance(value, bool):
            raise TypeError("Boolean values are not valid score time")
        if isinstance(value, dict):
            return cls(int(value["numerator"]), int(value["denominator"]))
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("Score time must be finite")
            fraction = Fraction(str(value)).limit_denominator(MAX_SCORE_TIME_DENOMINATOR)
        else:
            fraction = Fraction(value).limit_denominator(MAX_SCORE_TIME_DENOMINATOR)
        return cls(fraction.numerator, fraction.denominator)

    def to_dict(self) -> dict[str, int]:
        return {"numerator": self.numerator, "denominator": self.denominator}

    def to_float(self) -> float:
        return self.numerator / self.denominator

    def __add__(self, other: Rational | int) -> Rational:
        value = self.as_fraction() + Rational.from_value(other).as_fraction()
        return Rational(value.numerator, value.denominator)

    def __sub__(self, other: Rational | int) -> Rational:
        value = self.as_fraction() - Rational.from_value(other).as_fraction()
        return Rational(value.numerator, value.denominator)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, (Rational, int)):
            return NotImplemented
        return self.as_fraction() < Rational.from_value(other).as_fraction()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, (Rational, int)):
            return NotImplemented
        value = Rational.from_value(other)
        return self.numerator == value.numerator and self.denominator == value.denominator

    def __hash__(self) -> int:
        return hash((self.numerator, self.denominator))

    def as_fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)


ZERO = Rational(0)


@dataclass(slots=True)
class DocumentSourceTrack:
    id: str
    index: int
    name: str
    instrument_name: str | None
    program: int | None
    note_count: int


@dataclass(slots=True)
class DocumentSource:
    filename: str
    sha256: str
    midi_type: int
    ticks_per_beat: int
    note_count: int
    duration: Rational
    tracks: list[DocumentSourceTrack] = field(default_factory=list)


@dataclass(slots=True)
class DocumentTrackAssignment:
    source_track_index: int
    family: str
    confidence: float
    reason: str
    user_overridden: bool = False


@dataclass(slots=True)
class AnalysisSnapshot:
    style_label: str = "unknown"
    key_signature: str | None = None
    sections: list[dict[str, Any]] = field(default_factory=list)
    chord_symbols: list[dict[str, Any]] = field(default_factory=list)
    track_assignments: list[DocumentTrackAssignment] = field(default_factory=list)


@dataclass(slots=True)
class SourceNoteReference:
    source_track_index: int
    source_note_index: int
    origin: str = "midi"


@dataclass(slots=True)
class InstrumentRealization:
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
class ScoreNote:
    id: str
    pitch: int
    source: SourceNoteReference | None
    realization: InstrumentRealization
    technique_ids: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScoreBeat:
    id: str
    start: Rational
    duration: Rational
    voice: int
    staff_id: str
    kind: str = "notes"
    notes: list[ScoreNote] = field(default_factory=list)
    tie_in: bool = False
    tie_out: bool = False
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScoreMeasure:
    id: str
    number: int
    start: Rational
    duration: Rational
    numerator: int
    denominator: int
    beats: list[ScoreBeat] = field(default_factory=list)
    annotations: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScoreStaff:
    id: str
    order: int
    kind: str
    line_count: int = 5


@dataclass(slots=True)
class TrackMixer:
    """Normalized editable playback state independent from a renderer."""

    volume: float = 0.8
    pan: float = 0.0
    mute: bool = False
    solo: bool = False


@dataclass(slots=True)
class ScoreTrack:
    id: str
    order: int
    name: str
    family: str
    role: str
    source_track_indices: list[int]
    instrument: dict[str, Any]
    staves: list[ScoreStaff]
    measures: list[ScoreMeasure] = field(default_factory=list)
    notation_mode: str = "standard"
    mixer: TrackMixer = field(default_factory=TrackMixer)


@dataclass(slots=True)
class ScoreTechnique:
    id: str
    type: str
    note_ids: list[str]
    confidence: float
    reason: str
    parameters: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class TempoChange:
    id: str
    position: Rational
    bpm: float


@dataclass(slots=True)
class TimeSignatureChange:
    id: str
    position: Rational
    numerator: int
    denominator: int


@dataclass(slots=True)
class PerformanceEvent:
    id: str
    note_id: str
    start: Rational
    duration: Rational
    velocity: int
    controls: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class PerformanceLayer:
    profile_id: str = "source-preserved"
    events: list[PerformanceEvent] = field(default_factory=list)


@dataclass(slots=True)
class UnresolvedSourceEvent:
    id: str
    source_track_index: int
    source_note_index: int
    pitch: int
    start: Rational
    duration: Rational
    reason: str


@dataclass(slots=True)
class DocumentValidationIssue:
    code: str
    severity: str
    message: str
    entity_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DocumentValidationState:
    status: str = "not_validated"
    issues: list[DocumentValidationIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues)


@dataclass(slots=True)
class DocumentPins:
    application_version: str
    knowledge_snapshot: str
    model_provider: str = "none"
    model_name: str = "none"
    prompt_version: str = "none"
    sound_profile: str = "none"


@dataclass(slots=True)
class KnowledgeReference:
    snapshot_version: str
    kb_versions: dict[str, str] = field(default_factory=dict)
    entry_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DocumentTransformation:
    id: str
    stage: str
    source_note_index: int
    before: dict[str, Any]
    after: dict[str, Any]
    confidence: float
    reason: str
    knowledge_ref: str | None = None


@dataclass(slots=True)
class ScoreDocument:
    id: str
    title: str
    source: DocumentSource
    analysis: AnalysisSnapshot
    tracks: list[ScoreTrack]
    tempo_map: list[TempoChange]
    time_signatures: list[TimeSignatureChange]
    techniques: list[ScoreTechnique]
    performance: PerformanceLayer
    unresolved_events: list[UnresolvedSourceEvent]
    validation: DocumentValidationState
    pins: DocumentPins
    schema_version: str = SCORE_DOCUMENT_SCHEMA_VERSION
    arrangement_mode: str = "faithful"
    knowledge: KnowledgeReference | None = None
    transformations: list[DocumentTransformation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


__all__ = [
    "MAX_SCORE_TIME_DENOMINATOR",
    "SCORE_DOCUMENT_SCHEMA_VERSION",
    "ZERO",
    "AnalysisSnapshot",
    "DocumentPins",
    "DocumentSource",
    "DocumentSourceTrack",
    "DocumentTrackAssignment",
    "DocumentTransformation",
    "DocumentValidationIssue",
    "DocumentValidationState",
    "InstrumentRealization",
    "KnowledgeReference",
    "PerformanceEvent",
    "PerformanceLayer",
    "Rational",
    "ScoreBeat",
    "ScoreDocument",
    "ScoreMeasure",
    "ScoreNote",
    "ScoreStaff",
    "ScoreTechnique",
    "ScoreTrack",
    "SourceNoteReference",
    "TempoChange",
    "TimeSignatureChange",
    "UnresolvedSourceEvent",
]
