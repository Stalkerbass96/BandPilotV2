"""Guitar IR Schema 1.0 — the frozen core contract of FretPilot v2.

All modules (engine, exporters, API) depend on these dataclasses. Schema
changes require an explicit version bump and migration.

Design principles:
  - ScoreTiming (notation) and PerformanceTiming (source MIDI) are separated.
  - Every note traces back to its source (source_note_index, source_note_origin).
  - The IR pins the knowledge snapshot used during repair (IRKnowledgeReference).
  - All dataclasses use slots=True for memory efficiency.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_VERSION = "1.0"


# ─── Time layer ───


@dataclass(slots=True)
class IRTempoEvent:
    """A tempo change at a given beat."""

    beat: float
    bpm: float


@dataclass(slots=True)
class IRTimeSignatureEvent:
    """A time-signature change at a given beat."""

    beat: float
    numerator: int
    denominator: int


@dataclass(slots=True)
class ScoreTiming:
    """Notation timing — serves gp5 score readability.

    Times are quantized to a grid and split at measure boundaries.
    """

    start_beat: float
    duration_beats: float
    measure_number: int
    beat_in_measure: float
    voice: int = 1
    tie_in: bool = False
    tie_out: bool = False


@dataclass(slots=True)
class PerformanceTiming:
    """Performance timing — serves playable-MIDI source playback.

    Preserves the exact source MIDI timing for Ample Guitar rendering.
    """

    source_start_beat: float
    source_duration_beats: float
    velocity: int


# ─── Performance information layer ───


@dataclass(slots=True)
class IRFingering:
    """Fretboard position and fingering information.

    String numbering: 1 = high E string, 6 = low E string.
    """

    string: int | None
    fret: int | None
    fretting_digit: int | None = None  # 1=index ... 4=pinky
    hand_position: int | None = None  # fret where index finger sits

    @property
    def playable(self) -> bool:
        """Return True if both string and fret are assigned."""
        return self.string is not None and self.fret is not None


@dataclass(slots=True)
class IRArticulation:
    """A playing technique marking (palm_mute, hammer_on, slide, ...)."""

    type: str
    confidence: float
    reason: str
    source_note_id: str | None = None
    parameters: dict[str, float] = field(default_factory=dict)


# ─── Confidence layer ───


@dataclass(slots=True)
class NoteConfidence:
    """Per-note confidence scores from the repair pipeline."""

    rhythm: float
    fingering: float
    articulation: float | None = None


# ─── Note event ───


@dataclass(slots=True)
class GuitarNoteEvent:
    """A complete guitar note representation in the IR."""

    id: str  # stable ID, format n-00001
    source_note_index: int
    pitch: int
    score: ScoreTiming
    performance: PerformanceTiming
    fingering: IRFingering
    articulations: list[IRArticulation] = field(default_factory=list)
    confidence: NoteConfidence | None = None
    source_note_origin: str = "midi"  # "midi" or "synthetic"


# ─── Measure ───


@dataclass(slots=True)
class GuitarMeasure:
    """A measure containing note events."""

    number: int
    start_beat: float
    duration_beats: float
    numerator: int
    denominator: int
    events: list[GuitarNoteEvent] = field(default_factory=list)


# ─── Track ───


@dataclass(slots=True)
class GuitarTrackIR:
    """A guitar track with measures, tuning, and metadata."""

    id: str
    name: str
    source_track_index: int | None
    role: str  # lead/rhythm/bass/unknown
    tuning: list[int]  # 6-string open-string MIDI pitches
    fret_count: int
    measures: list[GuitarMeasure] = field(default_factory=list)
    capo: int = 0
    program: int | None = None
    mixer: dict[str, object] = field(default_factory=dict)


# ─── Knowledge reference ───


@dataclass(slots=True)
class IRKnowledgeReference:
    """Pins the knowledge snapshot used during repair for reproducibility."""

    snapshot_version: str  # e.g. "2026.08.2"
    kb_versions: dict[str, str] = field(default_factory=dict)  # {"kb1": "...", ...}
    entry_ids: list[str] = field(default_factory=list)


# ─── Transformation / provenance ───


@dataclass(slots=True)
class Transformation:
    """A single repair change record — implements the 'break the black box' value."""

    id: str
    stage: str  # pipeline stage that produced this change
    source_note_index: int
    before: dict[str, Any]
    after: dict[str, Any]
    confidence: float
    reason: str
    knowledge_ref: str | None = None  # linked knowledge entry ID


# ─── Project-level IR (top-level container) ───


@dataclass(slots=True)
class GuitarProjectIR:
    """Guitar IR Schema 1.0 top-level container."""

    title: str
    source: str
    schema_version: str = SCHEMA_VERSION
    tempo_map: list[IRTempoEvent] = field(default_factory=list)
    time_signatures: list[IRTimeSignatureEvent] = field(default_factory=list)
    tracks: list[GuitarTrackIR] = field(default_factory=list)
    knowledge: IRKnowledgeReference | None = None
    style_label: str = "unknown"
    midi_fidelity: float = 0.5
    degraded_mode: bool = False
    changes: list[Transformation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the IR to a plain dict (for JSON persistence / API)."""
        return asdict(self)


__all__ = [
    "SCHEMA_VERSION",
    "IRTempoEvent",
    "IRTimeSignatureEvent",
    "ScoreTiming",
    "PerformanceTiming",
    "IRFingering",
    "IRArticulation",
    "NoteConfidence",
    "GuitarNoteEvent",
    "GuitarMeasure",
    "GuitarTrackIR",
    "IRKnowledgeReference",
    "Transformation",
    "GuitarProjectIR",
]
