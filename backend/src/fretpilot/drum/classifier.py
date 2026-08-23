"""Drum track detection — mirrors detection/classifier.py.

Detection signals (priority order):
1. Channel 10 (MIDI standard drum channel) — strongest signal.
2. Track name keywords: "drum", "perc", "beat", "kit", "sticks".
3. Note pitch range 35-81 (GM drum map).
4. Rapid repeats on the same pitch (drum hits vs melodic notes).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fretpilot.midi.models import NormalizedTimeline, NormalizedTrack

# ─── Constants ───

# mido and NormalizedNote use zero-based channels, so human-facing MIDI
# channel 10 is represented as integer 9.
_DRUM_CHANNEL = 9
_DRUM_MIN_PITCH = 35  # GM drum map lower bound
_DRUM_MAX_PITCH = 81  # GM drum map upper bound
_MIN_NOTES_FOR_CLASSIFICATION = 4
_RAPID_REPEAT_THRESHOLD_BEATS = 0.125  # 32nd note at 120 BPM

# Track-name keywords that signal a drum track.
_DRUM_KEYWORDS: tuple[str, ...] = (
    "drum",
    "perc",
    "beat",
    "kit",
    "sticks",
)


# ─── Classification result ───


@dataclass(slots=True)
class DrumTrackClassification:
    """Classification result for a single drum track candidate.

    Attributes:
        track_index: Index into the timeline's track list.
        track_name: Name of the track.
        is_drum: Whether this track is classified as drums.
        confidence: Detection confidence (0.0–1.0).
        reason: Human-readable explanation of the classification.
        detected_pieces: Piece names detected from pitches (if is_drum).
        kit_type: Detected kit type name (if is_drum).
    """

    track_index: int
    track_name: str
    is_drum: bool
    confidence: float
    reason: str
    detected_pieces: list[str] = field(default_factory=list)
    kit_type: str = ""


# ─── Detection layers ───


def _layer1_channel(track: NormalizedTrack) -> tuple[bool, float, str]:
    """Layer 1: Check if any note uses MIDI channel 10.

    Returns:
        (is_drum, confidence, reason).
    """
    if not track.notes:
        return False, 0.0, "no notes"
    channel_10_count = sum(1 for n in track.notes if n.channel == _DRUM_CHANNEL)
    if channel_10_count == 0:
        return False, 0.0, "no channel-10 notes"
    ratio = channel_10_count / len(track.notes)
    if ratio > 0.8:
        return True, 0.98, f"{channel_10_count}/{len(track.notes)} notes on channel 10"
    if ratio > 0.3:
        return True, 0.85, f"{channel_10_count}/{len(track.notes)} notes on channel 10"
    return False, 0.3, f"only {channel_10_count}/{len(track.notes)} notes on channel 10"


def _layer2_track_name(name: str) -> tuple[bool, float, str]:
    """Layer 2: Match track name against drum keywords.

    Returns:
        (is_drum, confidence, reason).
    """
    if not name:
        return False, 0.0, "no track name"
    lower = name.lower()
    for keyword in _DRUM_KEYWORDS:
        if keyword in lower:
            return True, 0.9, f"track name {name!r} contains {keyword!r}"
    return False, 0.0, f"track name {name!r} has no drum keywords"


def _layer3_pitch_range(track: NormalizedTrack) -> tuple[bool, float, str]:
    """Layer 3: Check if pitches fall within the GM drum range (35–81).

    Returns:
        (is_drum, confidence, reason).
    """
    if not track.notes:
        return False, 0.0, "no notes"
    pitches = [n.pitch for n in track.notes]
    low, high = min(pitches), max(pitches)
    in_range = sum(
        1 for p in pitches if _DRUM_MIN_PITCH <= p <= _DRUM_MAX_PITCH
    )
    ratio = in_range / len(pitches)
    if ratio > 0.8:
        return True, 0.75, f"{in_range}/{len(pitches)} pitches in GM drum range ({low}-{high})"
    if ratio > 0.5:
        return True, 0.5, f"{in_range}/{len(pitches)} pitches in GM drum range"
    return False, 0.2, f"only {in_range}/{len(pitches)} pitches in GM drum range"


def _layer4_rapid_repeats(track: NormalizedTrack) -> tuple[bool, float, str]:
    """Layer 4: Detect rapid repeats on the same pitch (drum-hit pattern).

    Drum tracks often have many notes on the same pitch fired in quick
    succession (e.g. a 16th-note hi-hat). Melodic tracks rarely do.

    Returns:
        (is_drum, confidence, reason).
    """
    if len(track.notes) < _MIN_NOTES_FOR_CLASSIFICATION:
        return False, 0.0, "too few notes"

    # Group notes by pitch, then count rapid repeats within each group.
    by_pitch: dict[int, list[float]] = {}
    for n in track.notes:
        by_pitch.setdefault(n.pitch, []).append(n.start_beat)

    rapid_count = 0
    for starts in by_pitch.values():
        starts.sort()
        for i in range(1, len(starts)):
            if starts[i] - starts[i - 1] <= _RAPID_REPEAT_THRESHOLD_BEATS:
                rapid_count += 1

    if rapid_count == 0:
        return False, 0.0, "no rapid repeats"
    ratio = rapid_count / len(track.notes)
    if ratio > 0.3:
        return True, 0.7, f"{rapid_count} rapid repeats ({ratio:.0%} of notes)"
    if ratio > 0.1:
        return True, 0.4, f"{rapid_count} rapid repeats ({ratio:.0%} of notes)"
    return False, 0.1, f"few rapid repeats ({rapid_count})"


# ─── Public API ───


def classify_drum_track(track: NormalizedTrack) -> bool:
    """Classify a single track as drum or non-drum.

    Uses a priority-ordered combination of the four detection layers.
    Channel 10 is the strongest signal and can independently confirm drums.

    Args:
        track: A physical MIDI track.

    Returns:
        True if the track is classified as drums.
    """
    name = (track.name or "").strip()

    d1, c1, r1 = _layer1_channel(track)
    if d1 and c1 >= 0.85:
        return True

    d2, c2, r2 = _layer2_track_name(name)
    if d2 and c2 >= 0.9:
        return True

    d3, c3, r3 = _layer3_pitch_range(track)
    d4, c4, r4 = _layer4_rapid_repeats(track)

    # Combine non-primary layers: need at least two positive signals.
    signals = [c for d, c, _ in [(d1, c1, r1), (d2, c2, r2), (d3, c3, r3), (d4, c4, r4)] if d]
    if len(signals) >= 2 and sum(signals) / len(signals) >= 0.5:
        return True

    return False


def detect_drum_family(
    timeline: NormalizedTimeline,
) -> list[DrumTrackClassification]:
    """Detect all drum tracks in a timeline.

    Args:
        timeline: The full normalized MIDI timeline.

    Returns:
        A list of DrumTrackClassification for every track, with ``is_drum``
        set accordingly.
    """
    from fretpilot.drum.drumkit import detect_kit, map_pitch_to_piece

    results: list[DrumTrackClassification] = []
    for track in timeline.tracks:
        name = (track.name or "").strip()

        d1, c1, r1 = _layer1_channel(track)
        d2, c2, r2 = _layer2_track_name(name)
        d3, c3, r3 = _layer3_pitch_range(track)
        d4, c4, r4 = _layer4_rapid_repeats(track)

        # Priority: channel 10 alone can confirm; otherwise combine signals.
        if d1 and c1 >= 0.85:
            is_drum = True
            confidence = c1
            reason = r1
        elif d2 and c2 >= 0.9:
            is_drum = True
            confidence = c2
            reason = r2
        else:
            signals = [
                (c, r)
                for d, c, r in [(d1, c1, r1), (d2, c2, r2), (d3, c3, r3), (d4, c4, r4)]
                if d
            ]
            if len(signals) >= 2:
                avg_conf = sum(c for c, _ in signals) / len(signals)
                is_drum = avg_conf >= 0.5
                confidence = avg_conf
                reason = "; ".join(r for _, r in signals)
            else:
                is_drum = False
                confidence = max(
                    (c for d, c, _ in [(d1, c1, r1), (d2, c2, r2), (d3, c3, r3), (d4, c4, r4)] if d),
                    default=0.0,
                )
                reason = "no drum signals detected"

        detected_pieces: list[str] = []
        kit_type = ""
        if is_drum and track.notes:
            pitches = [n.pitch for n in track.notes]
            piece_set = {map_pitch_to_piece(p) for p in pitches}
            piece_set.discard("unknown")
            detected_pieces = sorted(piece_set)
            kit_type = detect_kit(pitches).name

        results.append(
            DrumTrackClassification(
                track_index=track.index,
                track_name=name or f"Track {track.index + 1}",
                is_drum=is_drum,
                confidence=round(confidence, 4),
                reason=reason,
                detected_pieces=detected_pieces,
                kit_type=kit_type,
            )
        )

    return results


__all__ = [
    "DrumTrackClassification",
    "classify_drum_track",
    "detect_drum_family",
]
