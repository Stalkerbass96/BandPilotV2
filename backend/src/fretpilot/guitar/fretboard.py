"""Fretboard physics — mapping MIDI pitches to candidate string/fret positions."""

from __future__ import annotations

from dataclasses import dataclass

from fretpilot.guitar.instrument import STANDARD_TUNING, GuitarTuning


@dataclass(frozen=True, slots=True)
class FretPosition:
    """A single playable position on the fretboard."""

    string: int  # 1=high E ... 6=low E
    fret: int
    pitch: int


def candidate_positions(
    pitch: int,
    *,
    tuning: GuitarTuning = STANDARD_TUNING,
    max_fret: int | None = None,
) -> list[FretPosition]:
    """Return every playable string/fret location for a MIDI pitch.

    Positions are ordered from high string (1) to low string (6), which matches
    the typical visual top-to-bottom order in guitar tablature.
    """
    limit = max_fret if max_fret is not None else tuning.fret_count
    positions: list[FretPosition] = []
    for string, open_pitch in sorted(tuning.open_strings):
        fret = pitch - open_pitch
        if 0 <= fret <= limit:
            positions.append(FretPosition(string=string, fret=fret, pitch=pitch))
    return positions


def is_pitch_playable(
    pitch: int,
    *,
    tuning: GuitarTuning = STANDARD_TUNING,
    max_fret: int | None = None,
) -> bool:
    """Return True if a pitch can be played on the given tuning."""
    return len(candidate_positions(pitch, tuning=tuning, max_fret=max_fret)) > 0


def playable_range(tuning: GuitarTuning = STANDARD_TUNING) -> tuple[int, int]:
    """Return (min_pitch, max_pitch) playable on the tuning across all frets."""
    min_pitch = min(p for _s, p in tuning.open_strings)
    max_pitch = max(p for _s, p in tuning.open_strings) + tuning.fret_count
    return min_pitch, max_pitch


__all__ = [
    "FretPosition",
    "candidate_positions",
    "is_pitch_playable",
    "playable_range",
]
