"""Core data models for the drum e-learning module (StickPilot).

Mirrors ``elearning/models.py`` (guitar) but with drum-shaped ground truth:
a ``DrumGroundTruthNote`` carries the GM drum pitch, the mapped piece, and
velocity instead of string/fret/hand_position.

All models use ``@dataclass(slots=True)`` consistent with the project style
and are JSON-serializable for report persistence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class DrumGroundTruthNote:
    """A single drum hit extracted from a professional GP tab (ground truth).

    Attributes:
        measure_number: 1-indexed measure number.
        beat_in_measure: Beat offset within the measure (0 = start).
        pitch: GM drum MIDI pitch (e.g. 36 = kick, 38 = snare).
        piece: Mapped drum piece name (e.g. "kick", "snare").
        velocity: MIDI velocity (1–127) as recorded in the tab.
        duration_beats: Note duration in beats.
        is_tie: Whether the note is a tie continuation (should be excluded).
    """

    measure_number: int
    beat_in_measure: float
    pitch: int
    piece: str
    velocity: int
    duration_beats: float
    is_tie: bool


@dataclass(slots=True)
class DrumGroundTruthTab:
    """Complete ground truth extracted from one GP drum track."""

    file_path: str
    title: str
    style_label: str
    tempo_bpm: float
    time_signature: tuple[int, int]
    track_name: str
    notes: list[DrumGroundTruthNote]

    @property
    def note_count(self) -> int:
        return len(self.notes)

    @property
    def measure_count(self) -> int:
        return max((n.measure_number for n in self.notes), default=0)


@dataclass(slots=True)
class DrumStyleStats:
    """Drum playing statistics for a style group.

    These statistics are the empirical basis for deriving drum KB2
    (``drum_kb2_sticking``) priors via :class:`DrumPriorsDeriver`.
    """

    style_label: str
    sample_count: int
    total_notes: int
    total_measures: int
    # Density / speed
    hit_density: float  # mean hits per measure
    avg_inter_hit_gap_beats: float  # mean gap between consecutive hits (beats)
    # Dynamics
    velocity_mean: float
    accent_rate: float  # fraction of hits with velocity >= accent threshold
    ghost_note_rate: float  # fraction of hits with velocity <= ghost threshold
    # Sticking-relevant patterns
    flam_rate: float  # fraction of hits in a flam pair (same piece, near-simultaneous)
    double_stroke_rate: float  # fraction of hits in a double-stroke pair
    right_hand_rate: float  # fraction of hand-played hits assigned "R"
    hand_switch_pattern: str  # dominant 4-letter pattern, e.g. "RLRL", "RRLL"
    # Kit usage
    piece_distribution: dict[str, float]  # {piece: frequency}


@dataclass(slots=True)
class DrumDerivedPriors:
    """KB2 sticking priors derived from empirical drum statistics."""

    style_label: str
    knowledge_id: str
    payload: dict[str, Any]
    source_ids: list[str]
    confidence: float
    derivation_method: str
    stats_snapshot: dict[str, Any]
    # Target KB domain file and entry kind. Drum sticking priors default to
    # "drum_kb2_sticking" (mirrors DerivedPriors.domain for the guitar KB).
    domain: str = "drum_kb2_sticking"
    kind: str = "sticking_priors"


def _asdict(obj: Any) -> dict[str, Any]:
    return asdict(obj)


__all__ = [
    "DrumGroundTruthNote",
    "DrumGroundTruthTab",
    "DrumStyleStats",
    "DrumDerivedPriors",
    "_asdict",
]
