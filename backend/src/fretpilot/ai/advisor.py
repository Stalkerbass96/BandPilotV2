"""Shadow Rewrite Advisor — LLM decision caller with rule-based fallback.

This module wraps a concrete RewriteAdvisor provider. If the LLM is
unavailable (no BYOK key, provider error, timeout), it falls back to
deterministic rules: default style "pop" + conservative rewrite policy.
The caller is informed via the ``degraded_mode`` flag.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from fretpilot.ai.models import (
    AIProviderError,
    RewriteDecision,
    RewriteRequest,
    RewriteResponse,
    ShadowRewritePolicy,
    TrackFeatures,
)
from fretpilot.ai.providers.base import RewriteAdvisor
from fretpilot.knowledge.tunings import GuitarTuning
from fretpilot.midi.models import NormalizedNote, NormalizedTrack

logger = logging.getLogger("fretpilot.ai.advisor")

DEFAULT_STYLE = "pop"


@dataclass(slots=True)
class StyleInferenceResult:
    """Result of style inference including degradation status."""

    style_label: str
    degraded_mode: bool
    reason: str


def extract_features(track: NormalizedTrack) -> TrackFeatures:
    """Compute summary features from a NormalizedTrack for style inference."""
    notes = track.notes
    if not notes:
        return TrackFeatures(
            note_count=0, pitch_min=0, pitch_max=0, pitch_range_semitones=0,
            mean_velocity=0.0, mean_duration_beats=0.0, short_note_ratio=0.0,
            chord_onset_ratio=0.0, mean_polyphony=0.0, low_register_ratio=0.0,
            repeated_pitch_ratio=0.0,
        )

    pitches = [n.pitch for n in notes]
    velocities = [n.velocity for n in notes]
    durations = [n.duration_beats for n in notes]
    pitch_min, pitch_max = min(pitches), max(pitches)
    short_count = sum(1 for d in durations if d <= 0.25)

    # Chord onset ratio: fraction of onsets with >1 simultaneous note.
    onset_counts: dict[float, int] = {}
    for n in notes:
        key = round(n.start_beat, 6)
        onset_counts[key] = onset_counts.get(key, 0) + 1
    chord_onsets = sum(1 for c in onset_counts.values() if c > 1)
    total_onsets = len(onset_counts) or 1

    # Low register ratio: notes below MIDI 48 (C3).
    low_count = sum(1 for p in pitches if p < 48)
    # Repeated pitch ratio.
    pitch_set = set(pitches)

    return TrackFeatures(
        note_count=len(notes),
        pitch_min=pitch_min,
        pitch_max=pitch_max,
        pitch_range_semitones=pitch_max - pitch_min,
        mean_velocity=sum(velocities) / len(velocities),
        mean_duration_beats=sum(durations) / len(durations),
        short_note_ratio=short_count / len(notes),
        chord_onset_ratio=chord_onsets / total_onsets,
        mean_polyphony=sum(onset_counts.values()) / total_onsets,
        low_register_ratio=low_count / len(notes),
        repeated_pitch_ratio=1.0 - len(pitch_set) / len(notes),
    )


def _rule_based_style(features: TrackFeatures) -> str:
    """Deterministic style inference as a fallback."""
    if features.low_register_ratio > 0.5 and features.short_note_ratio > 0.5:
        return "metal"
    if features.short_note_ratio > 0.4 and features.repeated_pitch_ratio > 0.2:
        return "funk"
    if features.chord_onset_ratio > 0.3:
        return "rock"
    return DEFAULT_STYLE


class ShadowRewriteAdvisor:
    """Wraps an LLM advisor with deterministic fallback (degraded mode)."""

    def __init__(self, provider: RewriteAdvisor | None = None) -> None:
        self._provider = provider

    @property
    def is_available(self) -> bool:
        """Return True if an LLM provider is configured."""
        return self._provider is not None

    def infer_style(self, features: TrackFeatures) -> StyleInferenceResult:
        """Infer style, falling back to rules if LLM is unavailable."""
        if self._provider is None:
            return StyleInferenceResult(
                style_label=_rule_based_style(features),
                degraded_mode=True,
                reason="no LLM provider configured",
            )
        try:
            label = self._provider.infer_style(features)
            return StyleInferenceResult(
                style_label=label, degraded_mode=False, reason="llm"
            )
        except AIProviderError as exc:
            logger.warning("LLM style inference failed, degrading: %s", exc)
            return StyleInferenceResult(
                style_label=_rule_based_style(features),
                degraded_mode=True,
                reason=f"llm_error: {exc}",
            )

    def propose_rewrite(
        self, request: RewriteRequest
    ) -> tuple[RewriteResponse, bool]:
        """Propose rewrites, returning (response, degraded_mode)."""
        if self._provider is None:
            return RewriteResponse(), True
        try:
            return self._provider.propose_rewrite(request), False
        except AIProviderError as exc:
            logger.warning("LLM rewrite failed, degrading: %s", exc)
            return RewriteResponse(), True


def build_policy(midi_fidelity: float, snapshot_version: str = "") -> ShadowRewritePolicy:
    """Build a ShadowRewritePolicy from midi_fidelity."""
    return ShadowRewritePolicy(
        midi_fidelity=midi_fidelity,
        max_deletions=int(50 * (1.0 - midi_fidelity)),
        max_transpositions=int(20 * (1.0 - midi_fidelity)),
        knowledge_snapshot_version=snapshot_version,
    )


def validate_decisions(
    decisions: list[RewriteDecision],
    note_count: int,
    policy: ShadowRewritePolicy,
) -> list[RewriteDecision]:
    """Validate LLM decisions deterministically; reject out-of-bounds ones.

    This is the critical guardrail: the LLM only *suggests*, deterministic
    code *validates and executes*. Invalid decisions are silently dropped.
    """
    valid: list[RewriteDecision] = []
    deletion_count = 0
    transposition_count = 0

    for decision in decisions:
        if decision.operation not in ("delete", "transpose"):
            continue
        if decision.index < 0 or decision.index >= note_count:
            continue
        if decision.operation == "delete":
            if deletion_count >= policy.max_deletions:
                continue
            deletion_count += 1
        elif decision.operation == "transpose":
            if decision.pitch is None or not (0 <= decision.pitch <= 127):
                continue
            if transposition_count >= policy.max_transpositions:
                continue
            transposition_count += 1
        valid.append(decision)

    return valid


def build_note_summaries(
    track: NormalizedTrack,
    tuning: GuitarTuning | None = None,
    max_summaries: int = 200,
) -> list[dict[str, Any]]:
    """Build note summaries for the LLM rewrite request.

    Prioritizes suspicious notes (out-of-range, very short, velocity outliers)
    so the LLM gets a focused set to evaluate. Always includes note index
    so decisions can be mapped back to the original note list.
    """
    notes = track.notes
    if not notes:
        return []

    # Compute tuning range if available.
    min_pitch = tuning.min_pitch if tuning else 0
    max_pitch = tuning.max_pitch if tuning else 127

    suspicious: list[dict[str, Any]] = []
    normal: list[dict[str, Any]] = []

    for i, note in enumerate(notes):
        in_range = min_pitch <= note.pitch <= max_pitch
        summary: dict[str, Any] = {
            "index": i,
            "pitch": note.pitch,
            "start_beat": round(note.start_beat, 4),
            "duration_beats": round(note.duration_beats, 4),
            "velocity": note.velocity,
            "in_tuning_range": in_range,
        }
        # Classify as suspicious: out of range, very short (< 1/64 note),
        # or velocity 0 (silent artifact).
        is_suspicious = (
            not in_range
            or note.duration_beats < 0.0625
            or note.velocity == 0
        )
        if is_suspicious:
            suspicious.append(summary)
        else:
            normal.append(summary)

    # Prioritize suspicious notes, fill remaining slots with normal notes.
    result = suspicious[:max_summaries]
    remaining = max_summaries - len(result)
    if remaining > 0:
        result.extend(normal[:remaining])
    return result


def apply_rewrite_decisions(
    track: NormalizedTrack,
    decisions: list[RewriteDecision],
) -> tuple[NormalizedTrack, list[dict[str, Any]]]:
    """Apply validated rewrite decisions to a track.

    Returns ``(new_track, applied_log)`` where ``applied_log`` describes each
    applied decision for transformation recording.

    Decisions are applied by index into the ORIGINAL note list. Delete
    operations remove notes; transpose operations change pitch. Indices are
    validated before calling this function. Transpositions are applied first
    (they do not shift indices), then deletions are applied highest-index
    first to avoid index shifting.
    """
    # Build a mutable copy of notes.
    notes = list(track.notes)
    applied: list[dict[str, Any]] = []

    transpositions = [d for d in decisions if d.operation == "transpose"]
    deletions = sorted(
        [d for d in decisions if d.operation == "delete"],
        key=lambda d: d.index,
        reverse=True,  # delete from end to avoid index shifting
    )

    # Apply transpositions (indices stay valid because no notes are removed yet).
    for d in transpositions:
        old_note = notes[d.index]
        old_pitch = old_note.pitch
        new_note = NormalizedNote(
            track_index=old_note.track_index,
            track_name=old_note.track_name,
            channel=old_note.channel,
            pitch=d.pitch,
            velocity=old_note.velocity,
            start_tick=old_note.start_tick,
            duration_ticks=old_note.duration_ticks,
            start_beat=old_note.start_beat,
            duration_beats=old_note.duration_beats,
            program=old_note.program,
        )
        notes[d.index] = new_note
        applied.append({
            "index": d.index,
            "operation": "transpose",
            "old_pitch": old_pitch,
            "new_pitch": d.pitch,
            "reason": d.reason,
        })

    # Apply deletions (highest index first so earlier indices stay valid).
    indices_to_delete: set[int] = set()
    for d in deletions:
        indices_to_delete.add(d.index)
        applied.append({
            "index": d.index,
            "operation": "delete",
            "pitch": notes[d.index].pitch,
            "reason": d.reason,
        })

    if indices_to_delete:
        notes = [n for i, n in enumerate(notes) if i not in indices_to_delete]

    new_track = NormalizedTrack(
        index=track.index,
        name=track.name,
        notes=notes,
        instrument_name=track.instrument_name,
        program=track.program,
    )
    return new_track, applied


__all__ = [
    "StyleInferenceResult",
    "ShadowRewriteAdvisor",
    "extract_features",
    "build_policy",
    "validate_decisions",
    "build_note_summaries",
    "apply_rewrite_decisions",
    "DEFAULT_STYLE",
]
