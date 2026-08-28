"""Professional drum-set notation conventions shared by the pipeline/exporters.

The MIDI performance layer describes how long a sampler voice was held.  A
drum score describes rhythmic onsets instead, so the two durations must not be
treated as interchangeable.  This module keeps that policy in one place and
also defines the standard two-voice drum-set layout used by BandPilot:

* hands and cymbals: voice 1, stems up;
* feet (kick and pedal hi-hat): voice 2, stems down;
* five-line percussion staff with conventional noteheads/positions.
"""

from __future__ import annotations

FOOT_PIECES = frozenset({"kick", "hihat_pedal"})

# MusicXML display positions for a conventional five-line drum-set staff.
# These are notation positions, not sounding pitches.
DRUM_DISPLAY: dict[str, tuple[str, int]] = {
    "kick": ("F", 3),
    "snare": ("C", 5),
    "side_stick": ("C", 5),
    "hand_clap": ("C", 5),
    "tom_floor": ("F", 4),
    "tom_low": ("A", 4),
    "tom_mid": ("D", 5),
    "tom_high": ("F", 5),
    "hihat_closed": ("G", 5),
    "hihat_pedal": ("D", 4),
    "hihat_open": ("G", 5),
    "crash": ("A", 5),
    "crash_2": ("B", 5),
    "ride": ("F", 5),
    "ride_bell": ("F", 5),
    "ride_2": ("E", 5),
    "china": ("A", 5),
    "splash": ("G", 5),
    "tambourine": ("E", 5),
    "cowbell": ("E", 5),
    "vibraslap": ("B", 4),
}

DRUM_NOTEHEAD: dict[str, str] = {
    "side_stick": "x",
    "hand_clap": "x",
    "hihat_closed": "x",
    "hihat_pedal": "x",
    "hihat_open": "x",
    "crash": "x",
    "crash_2": "x",
    "ride": "x",
    "ride_2": "x",
    "china": "x",
    "splash": "x",
    "tambourine": "x",
    "ride_bell": "diamond",
    "cowbell": "diamond",
    "vibraslap": "diamond",
}


def notation_voice(piece: str) -> int:
    """Return the standard drum-set voice for ``piece``."""
    return 2 if piece in FOOT_PIECES else 1


def written_duration_beats(
    onset: float,
    next_onset: float | None,
    measure_end: float,
    *,
    preferred_duration: float | None = None,
) -> float:
    """Infer a safe written duration from rhythmic onsets.

    Drum note-off gates are sampler/performance data and frequently overlap
    later hits.  Written duration therefore closes at the next onset in the
    same voice (or the barline). If a clean quantized source duration is
    available it is preserved, but it can never cross that boundary. The
    caller is expected to pass quantized onsets.
    """
    boundary = measure_end if next_onset is None else min(next_onset, measure_end)
    available = boundary - onset
    if available <= 1e-8:
        return 1.0 / 64.0
    if preferred_duration is not None and preferred_duration > 1e-8:
        return min(preferred_duration, available)
    return min(1.0, available)


__all__ = [
    "DRUM_DISPLAY",
    "DRUM_NOTEHEAD",
    "FOOT_PIECES",
    "notation_voice",
    "written_duration_beats",
]
