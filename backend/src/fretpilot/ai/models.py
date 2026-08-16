"""LLM layer data models — request/response/policy structures.

The LLM only outputs *decisions* (style label, note rewrite suggestions).
It never touches MIDI data directly. Deterministic code validates and
executes every decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class AIProviderIdentity:
    """Identifies the LLM provider and model in use."""

    provider: str  # "openai_compatible"
    model: str
    base_url: str = ""


@dataclass(slots=True)
class TrackFeatures:
    """Summary features of a guitar track for style inference.

    The LLM receives these (not raw MIDI) to infer a style label.
    """

    note_count: int
    pitch_min: int
    pitch_max: int
    pitch_range_semitones: int
    mean_velocity: float
    mean_duration_beats: float
    short_note_ratio: float
    chord_onset_ratio: float
    mean_polyphony: float
    low_register_ratio: float
    repeated_pitch_ratio: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "note_count": self.note_count,
            "pitch_min": self.pitch_min,
            "pitch_max": self.pitch_max,
            "pitch_range_semitones": self.pitch_range_semitones,
            "mean_velocity": round(self.mean_velocity, 2),
            "mean_duration_beats": round(self.mean_duration_beats, 4),
            "short_note_ratio": round(self.short_note_ratio, 4),
            "chord_onset_ratio": round(self.chord_onset_ratio, 4),
            "mean_polyphony": round(self.mean_polyphony, 4),
            "low_register_ratio": round(self.low_register_ratio, 4),
            "repeated_pitch_ratio": round(self.repeated_pitch_ratio, 4),
        }


@dataclass(frozen=True, slots=True)
class ShadowRewritePolicy:
    """Policy parameters controlling LLM rewrite aggressiveness.

    The LLM uses midi_fidelity to decide how aggressively to suggest
    deletions/transpositions. Deterministic code still validates every
    suggestion.
    """

    midi_fidelity: float = 0.5
    max_deletions: int = 50
    max_transpositions: int = 20
    knowledge_snapshot_version: str = ""


@dataclass(slots=True)
class RewriteRequest:
    """A request to the LLM for note rewrite decisions."""

    features: TrackFeatures
    style_label: str
    policy: ShadowRewritePolicy
    note_summaries: list[dict[str, Any]] = field(default_factory=list)
    knowledge_snapshot_version: str = ""
    tuning_info: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RewriteDecision:
    """A single LLM-proposed rewrite decision (pre-validation)."""

    index: int
    operation: str  # delete / transpose
    pitch: int | None = None
    reason: str = ""


@dataclass(slots=True)
class RewriteResponse:
    """The LLM's response containing proposed decisions."""

    decisions: list[RewriteDecision] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class AIProviderError(Exception):
    """Raised when the LLM provider call fails (triggers degraded mode)."""


__all__ = [
    "AIProviderIdentity",
    "TrackFeatures",
    "ShadowRewritePolicy",
    "RewriteRequest",
    "RewriteDecision",
    "RewriteResponse",
    "AIProviderError",
]
