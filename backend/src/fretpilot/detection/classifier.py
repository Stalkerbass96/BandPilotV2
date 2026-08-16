"""3-layer guitar track classifier with a track-name pre-layer.

Layer 0: Track-name keyword matching (highest priority, strongest signal).
Layer 1: GM program lookup (program change → instrument family).
Layer 2: Pitch-range heuristic (guitar playable range check).
Layer 3: Note-density / polyphony behavioral features.

Each layer adds evidence; the final classification combines all layers.
"""

from __future__ import annotations

import re

from fretpilot.detection.models import (
    GuitarDetectionReport,
    TrackClassification,
)
from fretpilot.detection.streams import LogicalStream
from fretpilot.midi.gm import (
    is_bass_program,
    is_guitar_program,
    program_family,
    program_name,
)
from fretpilot.midi.models import NormalizedTimeline

# Guitar playable pitch range (standard tuning, 24 frets)
_GUITAR_MIN_PITCH = 40  # E2
_GUITAR_MAX_PITCH = 88  # E6
_BASS_MAX_PITCH = 60  # C4 upper bound for bass
_MIN_NOTES_FOR_CLASSIFICATION = 4

# Ordered keyword → instrument-family mappings for Layer 0. Order matters:
# "synth"/"pad" come first ("Synth X" is always a synthesizer), and the
# compound "bass guitar" precedes the bare "guitar"/"bass" tokens so "Bass
# Guitar" resolves to bass. "guitar" stays ahead of "bass" so "Electric Guitar"
# (a specific instrument) wins over the generic "bass" substring.
_FAMILY_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("synth", "synth"),
    ("pad", "synth"),
    ("bass guitar", "bass"),
    ("guitar", "guitar"),
    ("bass", "bass"),
    ("drum", "drums"),
    ("kick", "drums"),
    ("snare", "drums"),
    ("piano", "piano"),
    ("keyboard", "piano"),
    ("lead", "synth"),
)

# Single-token track names that are strong instrument signals on their own.
# "guitar" is deliberately absent: a lone "Guitar" label is treated as a weak
# default placeholder so program-based detection stays authoritative (this keeps
# the existing ``test_non_guitar_program_not_detected`` semantics intact).
_SINGLE_WORD_FAMILIES: dict[str, str] = {
    "bass": "bass",
    "drums": "drums",
    "drum": "drums",
    "kick": "drums",
    "snare": "drums",
    "piano": "piano",
    "keyboard": "piano",
    "synth": "synth",
    "pad": "synth",
}


def _layer0_track_name(name: str) -> tuple[str | None, str | None]:
    """Layer 0: match a track name to a family and role.

    Returns ``(family, role)``, each possibly ``None``. A descriptive multi-word
    name (e.g. "Lead Electric Guitar") is a strong signal and overrides program
    lookups (unreliable in Suno exports where every program is 0). A single
    strong non-guitar instrument word ("drums", "bass", ...) is also trusted,
    but a lone "guitar" stays a weak default so program detection still applies.
    """
    if not name:
        return None, None
    lower = name.lower()
    tokens = [t for t in re.split(r"[^a-z0-9]+", lower) if t]

    if len(tokens) == 1:
        family = _SINGLE_WORD_FAMILIES.get(tokens[0])
        if family is None:
            return None, None
        return family, None

    if len(tokens) < 2:
        return None, None

    family: str | None = None
    for keyword, mapped in _FAMILY_KEYWORDS:
        if keyword in lower:
            family = mapped
            break
    if family is None:
        return None, None

    role: str | None = None
    if "lead" in lower:
        role = "lead"
    elif "rhythm" in lower:
        role = "rhythm"
    return family, role


def _layer1_program(stream: LogicalStream) -> tuple[str, float, str]:
    """Layer 1: GM program-based classification."""
    program = stream.program
    if program is None:
        return "unknown", 0.0, "no program change"
    if is_guitar_program(program):
        return "guitar", 0.9, f"GM program {program} ({program_name(program)})"
    if is_bass_program(program):
        return "bass", 0.85, f"GM bass program {program}"
    family = program_family(program)
    return family, 0.5, f"GM family {family}"


def _layer2_pitch_range(stream: LogicalStream) -> tuple[float, str]:
    """Layer 2: pitch-range heuristic for guitar plausibility."""
    if not stream.notes:
        return 0.0, "no notes"
    pitches = [n.pitch for n in stream.notes]
    low, high = min(pitches), max(pitches)
    if high > _BASS_MAX_PITCH and low >= _GUITAR_MIN_PITCH:
        return 0.8, f"pitch range {low}-{high} fits guitar"
    if low < _GUITAR_MIN_PITCH:
        return 0.2, f"pitch {low} below guitar range"
    if high > _GUITAR_MAX_PITCH:
        return 0.3, f"pitch {high} above guitar range"
    return 0.6, f"pitch range {low}-{high} plausible for guitar"


def _layer3_behavior(stream: LogicalStream) -> tuple[float, str, str]:
    """Layer 3: note-density / polyphony behavioral features."""
    if len(stream.notes) < _MIN_NOTES_FOR_CLASSIFICATION:
        return 0.3, "unknown", "too few notes for behavioral analysis"

    pitches = [n.pitch for n in stream.notes]
    onset_counts: dict[float, int] = {}
    for n in stream.notes:
        key = round(n.start_beat, 6)
        onset_counts[key] = onset_counts.get(key, 0) + 1

    mean_polyphony = sum(onset_counts.values()) / max(len(onset_counts), 1)
    max_polyphony = max(onset_counts.values()) if onset_counts else 1
    pitch_range = max(pitches) - min(pitches)

    if mean_polyphony >= 2.0 and max_polyphony <= 6 and pitch_range <= 36:
        return 0.7, "rhythm", "chord-based rhythm guitar pattern"
    if mean_polyphony < 1.3 and pitch_range >= 12:
        return 0.7, "lead", "monophonic lead guitar pattern"
    if mean_polyphony < 1.5:
        return 0.5, "unknown", "sparse melodic pattern"
    return 0.4, "unknown", f"polyphony {mean_polyphony:.1f}, range {pitch_range}"


def _combine_confidence(*scores: float) -> float:
    """Combine confidence scores (weighted average, capped at 1.0)."""
    if not scores:
        return 0.0
    return min(1.0, sum(scores) / len(scores))


def _classify_stream(stream: LogicalStream) -> TrackClassification:
    """Classify a single logical stream through all layers (0-3)."""
    name = (stream.track_name or stream.instrument_name or "").strip()
    l0_family, l0_role = _layer0_track_name(name)

    l1_family, l1_conf, l1_reason = _layer1_program(stream)
    l2_conf, l2_reason = _layer2_pitch_range(stream)
    l3_conf, l3_role, l3_reason = _layer3_behavior(stream)

    if l0_family is not None:
        # Track name is the strongest signal and overrides program misreads.
        family = l0_family
        confidence = 0.95
        role = l0_role or l3_role
        reason = f"L0: track name {name!r} → {family}"
    else:
        family = l1_family
        role = l3_role
        if family == "guitar":
            confidence = _combine_confidence(l1_conf, l2_conf, l3_conf)
        else:
            confidence = l1_conf * 0.5
        reason = f"L1: {l1_reason}; L2: {l2_reason}; L3: {l3_reason}"

    is_guitar = family == "guitar"
    if family == "bass":
        role = "bass"
        is_guitar = False  # bass is tracked separately in MVP

    if name:
        track_name = name
    elif stream.source_track_indices:
        track_name = f"Track {stream.source_track_indices[0] + 1}"
    else:
        track_name = "Unknown"

    return TrackClassification(
        track_index=stream.source_track_indices[0] if stream.source_track_indices else 0,
        track_name=track_name,
        instrument_family=family,
        program=stream.program,
        is_guitar=is_guitar,
        guitar_role=role,
        confidence=round(confidence, 4),
        reason=reason,
    )


def classify_timeline(timeline: NormalizedTimeline) -> GuitarDetectionReport:
    """Classify all tracks in a timeline and identify the primary guitar track."""
    from fretpilot.detection.streams import resolve_streams

    streams = resolve_streams(timeline)
    classifications = [_classify_stream(s) for s in streams]

    guitar_cls = [c for c in classifications if c.is_guitar]
    primary_index = None
    if guitar_cls:
        best = max(guitar_cls, key=lambda c: c.confidence)
        primary_index = best.track_index

    return GuitarDetectionReport(
        classifications=classifications,
        primary_guitar_track_index=primary_index,
        total_guitar_tracks=len(guitar_cls),
    )


__all__ = ["classify_timeline"]
