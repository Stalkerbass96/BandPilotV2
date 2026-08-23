"""Working IR for bass, keyboard, and generic pitched-instrument plugins.

This IR is deliberately instrument-neutral at the timing layer while keeping
family-specific physical realizations explicit.  It is transient: SongIR is
the only persisted editable score contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fretpilot.ir.models import (
    IRKnowledgeReference,
    IRTempoEvent,
    IRTimeSignatureEvent,
    NoteConfidence,
    PerformanceTiming,
    ScoreTiming,
    Transformation,
)


@dataclass(slots=True)
class PitchedRealization:
    """Physical realization selected by an instrument plugin."""

    kind: str
    string: int | None = None
    fret: int | None = None
    fretting_digit: int | None = None
    hand_position: int | None = None
    hand: str | None = None
    finger: int | None = None
    pedal: str | None = None


@dataclass(slots=True)
class PitchedNoteEvent:
    id: str
    source_note_index: int
    pitch: int
    score: ScoreTiming
    performance: PerformanceTiming
    realization: PitchedRealization
    confidence: NoteConfidence | None = None
    unresolved_reason: str | None = None


@dataclass(slots=True)
class PitchedMeasure:
    number: int
    start_beat: float
    duration_beats: float
    numerator: int
    denominator: int
    events: list[PitchedNoteEvent] = field(default_factory=list)


@dataclass(slots=True)
class PitchedTrackIR:
    id: str
    name: str
    source_track_index: int
    family: str
    role: str
    instrument: dict[str, object]
    measures: list[PitchedMeasure] = field(default_factory=list)


@dataclass(slots=True)
class PitchedProjectIR:
    title: str
    source: str
    family: str
    tempo_map: list[IRTempoEvent] = field(default_factory=list)
    time_signatures: list[IRTimeSignatureEvent] = field(default_factory=list)
    tracks: list[PitchedTrackIR] = field(default_factory=list)
    knowledge: IRKnowledgeReference | None = None
    style_label: str = "unknown"
    changes: list[Transformation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


__all__ = [
    "PitchedMeasure",
    "PitchedNoteEvent",
    "PitchedProjectIR",
    "PitchedRealization",
    "PitchedTrackIR",
]
