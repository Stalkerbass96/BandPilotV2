"""General MIDI program knowledge used during instrument detection.

Mido exposes program numbers as zero-based values. Display names use the
one-based numbering musicians usually see in General MIDI documentation.
"""

from __future__ import annotations

GUITAR_PROGRAM_NAMES: dict[int, str] = {
    24: "Acoustic Guitar (nylon)",
    25: "Acoustic Guitar (steel)",
    26: "Electric Guitar (jazz)",
    27: "Electric Guitar (clean)",
    28: "Electric Guitar (muted)",
    29: "Overdriven Guitar",
    30: "Distortion Guitar",
    31: "Guitar harmonics",
}

BASS_PROGRAM_NAMES: dict[int, str] = {
    32: "Acoustic Bass",
    33: "Electric Bass (finger)",
    34: "Electric Bass (pick)",
    35: "Fretless Bass",
    36: "Slap Bass 1",
    37: "Slap Bass 2",
    38: "Synth Bass 1",
    39: "Synth Bass 2",
}

_GUITAR_PROGRAMS = frozenset(GUITAR_PROGRAM_NAMES)
_BASS_PROGRAMS = frozenset(BASS_PROGRAM_NAMES)


def program_family(program: int) -> str:
    """Return a coarse General MIDI family for a zero-based program number."""
    if 0 <= program <= 7:
        return "piano"
    if 8 <= program <= 15:
        return "chromatic_percussion"
    if 16 <= program <= 23:
        return "organ"
    if 24 <= program <= 31:
        return "guitar"
    if 32 <= program <= 39:
        return "bass"
    if 40 <= program <= 47:
        return "strings"
    if 48 <= program <= 55:
        return "ensemble"
    if 56 <= program <= 63:
        return "brass"
    if 64 <= program <= 71:
        return "reed"
    if 72 <= program <= 79:
        return "pipe"
    if 80 <= program <= 87:
        return "synth_lead"
    if 88 <= program <= 95:
        return "synth_pad"
    if 96 <= program <= 103:
        return "synth_effect"
    if 104 <= program <= 111:
        return "ethnic"
    if 112 <= program <= 119:
        return "percussive"
    if 120 <= program <= 127:
        return "sound_effect"
    return "unknown"


def program_name(program: int) -> str:
    """Return an exact GM name where FretPilot needs one."""
    if program in GUITAR_PROGRAM_NAMES:
        return GUITAR_PROGRAM_NAMES[program]
    if program in BASS_PROGRAM_NAMES:
        return BASS_PROGRAM_NAMES[program]
    return f"General MIDI program {program + 1}"


def is_guitar_program(program: int | None) -> bool:
    """Return True if the program is a GM guitar family instrument."""
    return program is not None and program in _GUITAR_PROGRAMS


def is_bass_program(program: int | None) -> bool:
    """Return True if the program is a GM bass family instrument."""
    return program is not None and program in _BASS_PROGRAMS


__all__ = [
    "GUITAR_PROGRAM_NAMES",
    "BASS_PROGRAM_NAMES",
    "program_family",
    "program_name",
    "is_guitar_program",
    "is_bass_program",
]
