"""Instrument family detection — classifies tracks for sub-module routing.

Uses existing guitar classifier (``detection.classifier``) and drum classifier
(``drum.classifier``) to determine which sub-module pipeline should process
each track.

Priority order:
  1. Drum channel 10 → drums (strongest signal).
  2. Guitar signals (track name, GM program, pitch range) → guitar.
  3. Bass program / pitch range → bass.
  4. Keys / piano program → keys.
  5. Else → unknown (passthrough, no repair).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from fretpilot.detection.streams import LogicalStream, resolve_streams
from fretpilot.drum.classifier import classify_drum_track, detect_drum_family
from fretpilot.midi.gm import is_bass_program, is_guitar_program
from fretpilot.midi.models import NormalizedTimeline, NormalizedTrack


class InstrumentFamily(str, Enum):
    """Detectable instrument families for sub-module routing.

    Values are lowercase strings stored in the database ``instrument_family``
    column and returned in API responses.
    """

    GUITAR = "guitar"
    DRUMS = "drums"
    BASS = "bass"
    KEYS = "keys"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class TrackFamilyClassification:
    """Classification result for a single track's instrument family.

    Attributes:
        track_index: Index into the timeline's track list.
        track_name: Human-readable track name.
        family: Detected instrument family.
        confidence: Detection confidence (0.0–1.0).
        reason: Human-readable explanation.
        is_guitar: Convenience flag (family == GUITAR).
        is_drum: Convenience flag (family == DRUMS).
        guitar_role: Guitar role ("lead"/"rhythm"/"bass") if family is guitar.
        kit_type: Detected drum kit type name if family is drums.
        detected_pieces: Drum piece names detected if family is drums.
        note_count: Number of notes in the track.
    """

    track_index: int
    track_name: str
    family: InstrumentFamily
    confidence: float
    reason: str
    is_guitar: bool = False
    is_drum: bool = False
    guitar_role: str = "unknown"
    kit_type: str = ""
    detected_pieces: list[str] = field(default_factory=list)
    note_count: int = 0


# ─── Pitch-range constants ───

_BASS_MAX_PITCH = 60  # C4 upper bound for bass
_GUITAR_MIN_PITCH = 40  # E2


def _is_keys_program(program: int | None) -> bool:
    """Return True if the program is a GM piano/keys family instrument."""
    if program is None:
        return False
    return 0 <= program <= 7  # GM piano family (programs 1-8, 0-indexed 0-7)


def _is_bass_by_pitch_range(track: NormalizedTrack) -> bool:
    """Heuristic: pitches consistently below the guitar range suggest bass."""
    if not track.notes:
        return False
    pitches = [n.pitch for n in track.notes]
    return max(pitches) <= _BASS_MAX_PITCH and min(pitches) >= 24  # below guitar, above sub-bass


def classify_track_family(track: NormalizedTrack) -> TrackFamilyClassification:
    """Classify a single track into an instrument family.

    Priority order:
      1. Drum channel 10 / drum track-name keywords / drum pitch range → drums.
      2. Guitar signals (GM program, track name, pitch range) → guitar.
      3. Bass GM program or bass pitch range → bass.
      4. Piano/keys GM program → keys.
      5. Else → unknown.

    Args:
        track: A physical MIDI track from the normalized timeline.

    Returns:
        A ``TrackFamilyClassification`` with the detected family and metadata.
    """
    name = (track.name or "").strip() or f"Track {track.index + 1}"
    note_count = len(track.notes)

    # ── Priority 1: Drums ──
    # The drum classifier already combines channel-10, track-name, pitch-range,
    # and rapid-repeat signals with the correct priority ordering.
    if classify_drum_track(track):
        drum_cls_list = detect_drum_family(
            NormalizedTimeline(
                source="",
                midi_type=1,
                ticks_per_beat=480,
                tempo_events=[],
                time_signature_events=[],
                tracks=[track],
            )
        )
        drum_cls = drum_cls_list[0] if drum_cls_list else None
        kit_type = drum_cls.kit_type if drum_cls else ""
        detected_pieces = drum_cls.detected_pieces if drum_cls else []
        confidence = drum_cls.confidence if drum_cls else 0.8
        reason = drum_cls.reason if drum_cls else "drum signals detected"
        return TrackFamilyClassification(
            track_index=track.index,
            track_name=name,
            family=InstrumentFamily.DRUMS,
            confidence=confidence,
            reason=reason,
            is_drum=True,
            kit_type=kit_type,
            detected_pieces=detected_pieces,
            note_count=note_count,
        )

    # ── Priority 2: Guitar ──
    # Use the existing guitar classifier via resolve_streams to get a
    # full TrackClassification, then check its is_guitar flag.
    program = track.program
    if track.notes:
        # Check program first (fast path).
        if is_guitar_program(program):
            return TrackFamilyClassification(
                track_index=track.index,
                track_name=name,
                family=InstrumentFamily.GUITAR,
                confidence=0.9,
                reason=f"GM guitar program {program}",
                is_guitar=True,
                guitar_role="unknown",
                note_count=note_count,
            )
        # Track-name keyword check for guitar.
        lower_name = name.lower()
        if "guitar" in lower_name and "bass" not in lower_name:
            role = "lead" if "lead" in lower_name else ("rhythm" if "rhythm" in lower_name else "unknown")
            return TrackFamilyClassification(
                track_index=track.index,
                track_name=name,
                family=InstrumentFamily.GUITAR,
                confidence=0.95,
                reason=f"track name {name!r} → guitar",
                is_guitar=True,
                guitar_role=role,
                note_count=note_count,
            )

    # ── Priority 3: Bass ──
    if is_bass_program(program):
        return TrackFamilyClassification(
            track_index=track.index,
            track_name=name,
            family=InstrumentFamily.BASS,
            confidence=0.85,
            reason=f"GM bass program {program}",
            note_count=note_count,
        )
    if "bass" in name.lower():
        return TrackFamilyClassification(
            track_index=track.index,
            track_name=name,
            family=InstrumentFamily.BASS,
            confidence=0.9,
            reason=f"track name {name!r} → bass",
            note_count=note_count,
        )
    if _is_bass_by_pitch_range(track):
        return TrackFamilyClassification(
            track_index=track.index,
            track_name=name,
            family=InstrumentFamily.BASS,
            confidence=0.6,
            reason="pitch range suggests bass",
            note_count=note_count,
        )

    # ── Priority 4: Keys ──
    if _is_keys_program(program):
        return TrackFamilyClassification(
            track_index=track.index,
            track_name=name,
            family=InstrumentFamily.KEYS,
            confidence=0.7,
            reason=f"GM piano/keys program {program}",
            note_count=note_count,
        )
    lower_name = name.lower()
    if any(kw in lower_name for kw in ("piano", "keyboard", "keys")):
        return TrackFamilyClassification(
            track_index=track.index,
            track_name=name,
            family=InstrumentFamily.KEYS,
            confidence=0.85,
            reason=f"track name {name!r} → keys",
            note_count=note_count,
        )

    # ── Priority 5: Unknown (passthrough) ──
    return TrackFamilyClassification(
        track_index=track.index,
        track_name=name,
        family=InstrumentFamily.UNKNOWN,
        confidence=0.0,
        reason="no instrument family signals detected",
        note_count=note_count,
    )


__all__ = [
    "InstrumentFamily",
    "TrackFamilyClassification",
    "classify_track_family",
]
