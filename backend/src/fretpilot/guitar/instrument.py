"""Guitar physical model — tuning, string count, fret count."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GuitarTuning:
    """A guitar tuning definition.

    open_strings maps string number (1=high E ... 6=low E) to open-string MIDI pitch.
    """

    name: str
    string_count: int
    open_strings: tuple[tuple[int, int], ...]  # (string_number, midi_pitch)
    fret_count: int = 24

    def pitch_for_string(self, string_number: int) -> int:
        """Return the open-string MIDI pitch for a given string number."""
        for string, pitch in self.open_strings:
            if string == string_number:
                return pitch
        raise ValueError(f"String {string_number} not found in tuning {self.name}.")

    @property
    def open_pitches(self) -> list[int]:
        """Open-string pitches ordered from low string (6) to high string (1)."""
        return [pitch for _string, pitch in sorted(self.open_strings, reverse=True)]


STANDARD_TUNING = GuitarTuning(
    name="Standard E A D G B E",
    string_count=6,
    open_strings=(
        (6, 40),  # Low E2
        (5, 45),  # A2
        (4, 50),  # D3
        (3, 55),  # G3
        (2, 59),  # B3
        (1, 64),  # High E4
    ),
    fret_count=24,
)

DROP_D_TUNING = GuitarTuning(
    name="Drop D",
    string_count=6,
    open_strings=(
        (6, 38),  # D2 (dropped)
        (5, 45),
        (4, 50),
        (3, 55),
        (2, 59),
        (1, 64),
    ),
    fret_count=24,
)


__all__ = ["GuitarTuning", "STANDARD_TUNING", "DROP_D_TUNING"]
