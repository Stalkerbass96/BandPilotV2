"""Drum IR Schema 1.0-drum — the frozen core contract of StickPilot.

Mirrors ir/models.py (guitar IR) but with drum-specific structures:
DrumHitLocation replaces IRFingering, DrumNoteEvent replaces GuitarNoteEvent,
DrumMeasure/DrumTrackIR/DrumProjectIR replace their guitar counterparts.

Design principles (same as guitar IR):
  - ScoreTiming (notation) and PerformanceTiming (source MIDI) are separated.
  - Every note traces back to its source (source_note_index).
  - The IR pins the knowledge snapshot used during repair.
  - All dataclasses use slots=True for memory efficiency.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from fretpilot.ir.models import (
    IRKnowledgeReference,
    IRTempoEvent,
    IRTimeSignatureEvent,
    NoteConfidence,
    PerformanceTiming,
    ScoreTiming,
    Transformation,
)

SCHEMA_VERSION = "1.0-drum"


# ─── Drum-specific location ───


@dataclass(slots=True)
class DrumHitLocation:
    """Drum-specific hit location — replaces IRFingering.

    Attributes:
        piece: Mapped drum piece name, e.g. "kick", "snare", "hihat_closed".
        sticking: Suggested sticking — "R", "L", "both", or "" (unassigned).
        technique: Hit technique — "normal", "ghost", "accent", "flam",
            "drag", or "roll".
    """

    piece: str
    sticking: str
    technique: str


# ─── Note event ───


@dataclass(slots=True)
class DrumNoteEvent:
    """A complete drum note (hit) representation in the IR.

    Attributes:
        id: Stable ID, format "n-00001".
        source_note_index: Index into the source MIDI track's note list.
        pitch: Original MIDI pitch (preserved for round-trip fidelity).
        piece: Mapped drum piece name.
        score: Notation timing (quantized, measure-split).
        performance: Source MIDI timing (exact, for playback).
        location: Drum hit location (piece, sticking, technique).
        confidence: Per-note confidence scores.
    """

    id: str
    source_note_index: int
    pitch: int
    piece: str
    score: ScoreTiming
    performance: PerformanceTiming
    location: DrumHitLocation
    confidence: NoteConfidence | None = None


# ─── Measure ───


@dataclass(slots=True)
class DrumMeasure:
    """A measure containing drum note events.

    Attributes:
        number: 1-indexed measure number.
        start_beat: Absolute beat position of the measure start.
        duration_beats: Duration of the measure in beats.
        numerator: Time signature numerator.
        denominator: Time signature denominator.
        pattern: Classification of this measure — "beat", "fill", "transition",
            or "unknown".
        events: Drum note events in this measure.
    """

    number: int
    start_beat: float
    duration_beats: float
    numerator: int
    denominator: int
    pattern: str = "unknown"
    events: list[DrumNoteEvent] = field(default_factory=list)


# ─── Track ───


@dataclass(slots=True)
class DrumTrackIR:
    """A drum track with measures, kit info, and metadata.

    Attributes:
        id: Stable track ID, e.g. "drum-1".
        name: Human-readable track name.
        source_track_index: Index into the source MIDI track list.
        kit: Drum kit name (e.g. "standard_5pc").
        style: Detected drum style (e.g. "metal", "rock", "pop").
        measures: Measures in this track, ordered by number.
    """

    id: str
    name: str
    source_track_index: int | None
    kit: str
    style: str = "unknown"
    measures: list[DrumMeasure] = field(default_factory=list)
    mixer: dict[str, object] = field(default_factory=dict)


# ─── Project-level IR (top-level container) ───


@dataclass(slots=True)
class DrumProjectIR:
    """Drum IR Schema 1.0-drum top-level container.

    Attributes:
        title: Project title.
        source: Source file path or identifier.
        schema_version: Always SCHEMA_VERSION ("1.0-drum").
        tempo_map: Tempo change events.
        time_signatures: Time signature change events.
        tracks: Drum tracks.
        knowledge: Knowledge snapshot reference.
        style_label: Detected style label.
        changes: Transformation records (provenance).
        warnings: Non-fatal warnings produced during repair.
    """

    title: str
    source: str
    schema_version: str = SCHEMA_VERSION
    tempo_map: list[IRTempoEvent] = field(default_factory=list)
    time_signatures: list[IRTimeSignatureEvent] = field(default_factory=list)
    tracks: list[DrumTrackIR] = field(default_factory=list)
    knowledge: IRKnowledgeReference | None = None
    style_label: str = "unknown"
    changes: list[Transformation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the IR to a plain dict (for JSON persistence / API)."""
        return asdict(self)


__all__ = [
    "SCHEMA_VERSION",
    "DrumHitLocation",
    "DrumNoteEvent",
    "DrumMeasure",
    "DrumTrackIR",
    "DrumProjectIR",
]
