"""Drum kit physical model — pieces, kit definitions, GM drum map.

Mirrors guitar/instrument.py: DrumPiece is the atomic unit (like a string),
DrumKit is the collection (like GuitarTuning), and the GM map provides
pitch-to-piece resolution for MIDI import.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DrumPiece:
    """A single drum piece definition.

    Attributes:
        name: Canonical piece name, e.g. "kick", "snare", "hihat_closed".
        midi_pitches: MIDI pitches that map to this piece (GM drum map).
        category: Broad category — "kick", "snare", "tom", "cymbal", "hihat".
        hand: Default sticking hand — "both", "right", or "left".
    """

    name: str
    midi_pitches: tuple[int, ...]
    category: str
    hand: str


@dataclass(frozen=True, slots=True)
class DrumKit:
    """A drum kit definition — a collection of DrumPieces.

    Attributes:
        name: Kit name, e.g. "standard_5pc", "standard_7pc", "extended".
        pieces: Tuple of DrumPiece definitions in canonical order.
    """

    name: str
    pieces: tuple[DrumPiece, ...]

    def piece_names(self) -> tuple[str, ...]:
        """Return the canonical piece name ordering."""
        return tuple(p.name for p in self.pieces)

    def piece_for_name(self, name: str) -> DrumPiece:
        """Look up a DrumPiece by name.

        Raises:
            ValueError: If no piece with the given name exists in this kit.
        """
        for piece in self.pieces:
            if piece.name == name:
                return piece
        raise ValueError(f"Drum piece {name!r} not found in kit {self.name!r}.")


# ─── Standard kit definitions ───

STANDARD_5PC = DrumKit(
    name="standard_5pc",
    pieces=(
        DrumPiece("kick", (35, 36), "kick", "right"),
        DrumPiece("side_stick", (37,), "snare", "left"),
        DrumPiece("snare", (38, 40), "snare", "left"),
        DrumPiece("hand_clap", (39,), "snare", "both"),
        DrumPiece("hihat_closed", (42,), "hihat", "right"),
        DrumPiece("hihat_pedal", (44,), "hihat", "right"),
        DrumPiece("hihat_open", (46,), "hihat", "right"),
        DrumPiece("tom_high", (50,), "tom", "right"),
        DrumPiece("tom_mid", (47, 48), "tom", "right"),
        DrumPiece("tom_low", (45,), "tom", "right"),
        DrumPiece("tom_floor", (41, 43), "tom", "right"),
        DrumPiece("crash", (49,), "cymbal", "right"),
        DrumPiece("crash_2", (57,), "cymbal", "right"),
        DrumPiece("ride", (51,), "cymbal", "right"),
        DrumPiece("ride_bell", (53,), "cymbal", "right"),
        DrumPiece("china", (52,), "cymbal", "right"),
        DrumPiece("splash", (55,), "cymbal", "right"),
        DrumPiece("tambourine", (54,), "percussion", "right"),
        DrumPiece("cowbell", (56,), "percussion", "right"),
        DrumPiece("vibraslap", (58,), "percussion", "right"),
        DrumPiece("ride_2", (59,), "cymbal", "right"),
    ),
)

STANDARD_7PC = DrumKit(
    name="standard_7pc",
    pieces=(
        DrumPiece("kick", (35, 36), "kick", "right"),
        DrumPiece("side_stick", (37,), "snare", "left"),
        DrumPiece("snare", (38, 40), "snare", "left"),
        DrumPiece("hand_clap", (39,), "snare", "both"),
        DrumPiece("hihat_closed", (42,), "hihat", "right"),
        DrumPiece("hihat_pedal", (44,), "hihat", "right"),
        DrumPiece("hihat_open", (46,), "hihat", "right"),
        DrumPiece("tom_high", (50,), "tom", "right"),
        DrumPiece("tom_mid", (48, 47), "tom", "right"),
        DrumPiece("tom_low", (45,), "tom", "right"),
        DrumPiece("tom_floor", (41, 43), "tom", "right"),
        DrumPiece("crash", (49,), "cymbal", "right"),
        DrumPiece("crash_2", (57,), "cymbal", "right"),
        DrumPiece("ride", (51,), "cymbal", "right"),
        DrumPiece("ride_bell", (53,), "cymbal", "right"),
        DrumPiece("china", (52,), "cymbal", "right"),
        DrumPiece("splash", (55,), "cymbal", "right"),
        DrumPiece("tambourine", (54,), "percussion", "right"),
        DrumPiece("cowbell", (56,), "percussion", "right"),
        DrumPiece("vibraslap", (58,), "percussion", "right"),
        DrumPiece("ride_2", (59,), "cymbal", "right"),
    ),
)


# ─── GM drum map ───

GM_DRUM_MAP: dict[int, str] = {}
"""MIDI pitch → drum piece name (built from STANDARD_5PC)."""

for _piece in STANDARD_5PC.pieces:
    for _pitch in _piece.midi_pitches:
        GM_DRUM_MAP[_pitch] = _piece.name


# ─── Helper functions ───


def map_pitch_to_piece(pitch: int) -> str:
    """Map a MIDI pitch to a drum piece name via the GM drum map.

    Returns:
        The drum piece name, or "unknown" if the pitch is outside the GM map.
    """
    return GM_DRUM_MAP.get(pitch, "unknown")


def detect_kit(pitches: list[int]) -> DrumKit:
    """Detect the most likely drum kit from the pitches used.

    Examines which GM drum pieces are present in the pitch list and returns
    the smallest kit that covers all detected pieces.

    Args:
        pitches: All MIDI pitches occurring in the drum track.

    Returns:
        A DrumKit (STANDARD_7PC if toms/cymbals suggest an extended kit,
        otherwise STANDARD_5PC).
    """
    piece_names = {map_pitch_to_piece(p) for p in pitches}
    piece_names.discard("unknown")

    # Heuristic: if we see multiple toms or extra cymbals, prefer 7pc.
    tom_count = sum(1 for name in piece_names if name.startswith("tom_"))
    cymbal_count = sum(
        1 for name in piece_names if name in ("crash", "crash_2", "china", "splash")
    )

    if tom_count >= 4 or cymbal_count >= 2:
        return STANDARD_7PC
    return STANDARD_5PC


__all__ = [
    "DrumPiece",
    "DrumKit",
    "STANDARD_5PC",
    "STANDARD_7PC",
    "GM_DRUM_MAP",
    "map_pitch_to_piece",
    "detect_kit",
]
