"""Knowledge rule engine — consumes JSON assets, produces repair decisions.

The engine holds NO priors dictionaries. All "what" knowledge (weights,
keymaps, conventions) comes from the KnowledgeRegistry (JSON assets).
This module only contains "how" logic: how to apply priors, how to select
grids, how to score fingerings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fretpilot.knowledge.registry import KnowledgeRegistry


@dataclass(frozen=True, slots=True)
class GridStep:
    """A quantization grid step."""

    name: str
    step_beats: float  # e.g. 0.25 = 1/16 note at 4/4


# Predefined grid steps (in beats, assuming quarter-note = 1 beat)
_GRID_QUARTER = GridStep("quarter", 1.0)
_GRID_EIGHTH = GridStep("eighth", 0.5)
_GRID_SIXTEENTH = GridStep("sixteenth", 0.25)
_GRID_THIRTYSECOND = GridStep("thirtysecond", 0.125)


class KnowledgeEngine:
    """Rule engine: consumes knowledge assets, produces repair decisions.

    Holds no priors dictionaries — all data comes from the registry.
    """

    def __init__(self, registry: KnowledgeRegistry) -> None:
        self.registry = registry

    def select_grid(self, style_label: str, fidelity: float) -> GridStep:
        """Select a quantization grid based on style and fidelity.

        Higher fidelity → finer grid (less aggressive quantization).
        Lower fidelity → coarser grid (more aggressive quantization).
        """
        density_range = self._get_density_range(style_label)
        if density_range:
            avg_density = sum(density_range) / 2
            if avg_density >= 8:
                # Dense styles (metal/funk) benefit from finer grids
                base = _GRID_SIXTEENTH if fidelity >= 0.4 else _GRID_EIGHTH
            else:
                base = _GRID_EIGHTH if fidelity >= 0.4 else _GRID_QUARTER
        else:
            base = _GRID_SIXTEENTH

        if fidelity >= 0.75:
            return _GRID_THIRTYSECOND
        if fidelity <= 0.25:
            return _GRID_QUARTER if base.step_beats >= 0.5 else _GRID_EIGHTH
        return base

    def _get_density_range(self, style_label: str) -> tuple[int, int] | None:
        """Look up the note_density_range from KB1 for a style."""
        payload = self.registry.query_payload(
            domain="kb1_arrangement",
            scope={"style": [style_label]},
        )
        raw = payload.get("note_density_range")
        if isinstance(raw, list) and len(raw) == 2:
            return int(raw[0]), int(raw[1])
        return None

    def _query_kb2_payload(self, style_label: str, role: str) -> dict[str, Any]:
        """Resolve the KB2 entry payload for a style (+ optional role)."""
        scope: dict[str, list[str]] = {"style": [style_label]}
        if role and role != "unknown":
            scope["role"] = [role]
        payload = self.registry.query_payload(
            domain="kb2_performance", scope=scope
        )
        if not payload and role:
            payload = self.registry.query_payload(
                domain="kb2_performance", scope={"style": [style_label]}
            )
        return payload or {}

    def get_fingering_priors(
        self, style_label: str, role: str = ""
    ) -> dict[str, float]:
        """Return KB2 fingering priors for a style (+ optional role)."""
        payload = self._query_kb2_payload(style_label, role)
        return {
            k: float(v)
            for k, v in payload.items()
            if isinstance(v, (int, float))
        }

    def get_fingering_chord_shapes(
        self, style_label: str, role: str = ""
    ) -> dict[str, int]:
        """Return the style's empirically learned top-K chord shapes.

        Shape keys are canonical ``s1f0,s2f2,...`` strings; values are the
        observed occurrence counts from the reference GP corpus.

        For unknown / unmatched styles — or styles whose entry has no
        ``chord_shapes`` (e.g. undersampled metal) — returns the merged
        ensemble across all style entries, so the learned knowledge still
        applies instead of degrading to pure defaults.
        """
        payload = self._query_kb2_payload(style_label, role)
        shapes = payload.get("chord_shapes")
        if isinstance(shapes, dict) and shapes:
            return {str(k): int(v) for k, v in shapes.items()}

        merged: dict[str, int] = {}
        for entry in self.registry.query(domain="kb2_performance"):
            cs = entry.payload.get("chord_shapes")
            if isinstance(cs, dict):
                for key, count in cs.items():
                    merged[str(key)] = merged.get(str(key), 0) + int(count)
        return merged

    def get_notation_convention(
        self, format_id: str
    ) -> dict[str, Any]:
        """Return KB3 notation conventions for a format (gp5/ample_midi)."""
        return self.registry.query_payload(
            domain="kb3_notation",
            scope={"format": [format_id]},
        )

    def score_fingering_candidate(
        self,
        priors: dict[str, float],
        *,
        fret: int,
        string: int,
        hand_position: int | None,
        prev_hand_position: int | None,
        is_open: bool,
    ) -> float:
        """Score a fingering candidate using KB2 priors.

        Lower score = better. Combines hand-position stability, open-string
        bias, and shape reuse heuristics.
        """
        score = 0.0
        stability = priors.get("hand_position_stability", 1.0)
        open_bias = priors.get("open_string_bias", 1.0)

        if is_open:
            score -= 0.5 * open_bias
        if hand_position is not None and prev_hand_position is not None:
            shift = abs(hand_position - prev_hand_position)
            score += shift * 0.3 * stability
        # Prefer lower frets (less finger stretch)
        score += fret * 0.05
        # Prefer middle strings (2-5) slightly over extremes
        if string in (1, 6):
            score += 0.1
        return score


__all__ = ["GridStep", "KnowledgeEngine"]
