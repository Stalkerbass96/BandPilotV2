"""MIDI data models produced by the import layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class TempoEvent:
    """A tempo change event with both tick and beat positions."""

    tick: int
    beat: float
    bpm: float


@dataclass(slots=True)
class TimeSignatureEvent:
    """A time-signature change event."""

    tick: int
    beat: float
    numerator: int
    denominator: int


@dataclass(slots=True)
class ProgramEvent:
    """A program-change (instrument) event."""

    track_index: int
    channel: int
    tick: int
    beat: float
    program: int
    program_name: str
    family: str


@dataclass(slots=True)
class NormalizedNote:
    """A single MIDI note with resolved beat-based timing."""

    track_index: int
    track_name: str
    channel: int
    pitch: int
    velocity: int
    start_tick: int
    duration_ticks: int
    start_beat: float
    duration_beats: float
    program: int | None = None

    @property
    def end_tick(self) -> int:
        return self.start_tick + self.duration_ticks

    @property
    def end_beat(self) -> float:
        return self.start_beat + self.duration_beats


@dataclass(slots=True)
class NormalizedTrack:
    """A physical MIDI track with its notes and instrument metadata."""

    index: int
    name: str
    notes: list[NormalizedNote] = field(default_factory=list)
    instrument_name: str | None = None
    program: int | None = None


@dataclass(slots=True)
class Diagnostic:
    """A parsing diagnostic (warning/info) that does not block import."""

    level: str
    code: str
    message: str
    track_index: int | None = None
    tick: int | None = None


@dataclass(slots=True)
class NormalizedTimeline:
    """The fully normalized representation of a MIDI file."""

    source: str
    midi_type: int
    ticks_per_beat: int
    tempo_events: list[TempoEvent]
    time_signature_events: list[TimeSignatureEvent]
    tracks: list[NormalizedTrack]
    program_events: list[ProgramEvent] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def note_count(self) -> int:
        return sum(len(track.notes) for track in self.tracks)

    @property
    def duration_beats(self) -> float:
        end_beats = [note.end_beat for track in self.tracks for note in track.notes]
        return max(end_beats, default=0.0)

    @property
    def initial_bpm(self) -> float:
        return self.tempo_events[0].bpm if self.tempo_events else 120.0

    @property
    def initial_time_signature(self) -> tuple[int, int]:
        if self.time_signature_events:
            event = self.time_signature_events[0]
            return event.numerator, event.denominator
        return 4, 4

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def source_name(cls, path: str | Path) -> str:
        return str(Path(path))


__all__ = [
    "TempoEvent",
    "TimeSignatureEvent",
    "ProgramEvent",
    "NormalizedNote",
    "NormalizedTrack",
    "Diagnostic",
    "NormalizedTimeline",
]
