"""Guitar physical model package."""

from fretpilot.guitar.fretboard import (
    FretPosition,
    candidate_positions,
    is_pitch_playable,
    playable_range,
)
from fretpilot.guitar.instrument import (
    DROP_D_TUNING,
    STANDARD_TUNING,
    GuitarTuning,
)

__all__ = [
    "GuitarTuning",
    "STANDARD_TUNING",
    "DROP_D_TUNING",
    "FretPosition",
    "candidate_positions",
    "is_pitch_playable",
    "playable_range",
]
