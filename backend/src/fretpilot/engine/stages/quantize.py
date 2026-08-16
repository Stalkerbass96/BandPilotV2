"""S1: Quantization stage.

Snaps note onset and duration to a rhythmic grid determined by style and
midi_fidelity. This is a deterministic operation — no LLM involvement.
"""

from __future__ import annotations

from collections import Counter
from math import floor

from fretpilot.engine.context import PipelineContext, QuantizedNote
from fretpilot.knowledge.engine import GridStep, KnowledgeEngine
from fretpilot.midi.models import NormalizedNote

_EPSILON = 1e-8

# 微音符阈值（beat）：低于此值视为噪声，不参与最短时值统计。
_MIN_SIGNIFICANT_DURATION = 0.06
# 显著占比阈值：占比低于此值的极短音符视为噪声，不主导网格选择。
_MIN_SIGNIFICANT_RATIO = 0.01


def _round_to_grid(value: float, step: float) -> float:
    """Round a beat value to the nearest grid multiple."""
    if step <= 0:
        return value
    units = max(0, int(floor(value / step + 0.5)))
    return units * step


def _quantize_duration(duration: float, step: float) -> float:
    """Quantize a duration to at least one grid step."""
    snapped = _round_to_grid(duration, step)
    return max(snapped, step)


def _shortest_significant_duration(notes: list[NormalizedNote]) -> float | None:
    """返回最短的显著时值（忽略微音符和占比 < 1% 的极短噪声音符）。

    - 忽略 duration < 0.06 的微音符（cleanup 已处理更短的，这里保守兜底）
    - 忽略占比 < 1% 的极短音符（如个别 0.119 的噪声，避免网格被拉到 32 分）
    - 返回剩余音符的最短 duration，无音符返回 None
    """
    durations = [
        n.duration_beats
        for n in notes
        if n.duration_beats >= _MIN_SIGNIFICANT_DURATION
    ]
    if not durations:
        return None
    total = len(durations)
    counter = Counter(round(d, 3) for d in durations)
    significant = [
        d for d, c in counter.items() if c / total >= _MIN_SIGNIFICANT_RATIO
    ]
    return min(significant) if significant else min(durations)


def _grid_step_for_duration(min_duration: float) -> float:
    """返回能容纳 min_duration 的最粗网格步长（4分/8分/16分/32分）。

    从粗到细找第一个 ≤ min_duration 的步长，例如 min_duration=0.25 → 0.25。
    """
    for step in (1.0, 0.5, 0.25, 0.125):
        if step <= min_duration:
            return step
    return 0.125


def _compute_confidence(
    original_start: float,
    quantized_start: float,
    original_duration: float,
    quantized_duration: float,
    step: float,
) -> float:
    """Estimate quantization confidence from the snap distance."""
    start_offset = abs(original_start - quantized_start)
    duration_offset = abs(original_duration - quantized_duration)
    total_offset = start_offset + duration_offset
    # Confidence drops as offset grows relative to the grid step.
    if step <= 0:
        return 1.0
    ratio = total_offset / step
    return max(0.0, min(1.0, 1.0 - ratio * 0.5))


class QuantizeStage:
    """S1: Snap note onsets and durations to a rhythmic grid."""

    name = "quantize"

    def __init__(self, engine: KnowledgeEngine) -> None:
        self._engine = engine

    def run(self, ctx: PipelineContext) -> PipelineContext:
        grid = self._engine.select_grid(ctx.style_label, ctx.midi_fidelity)
        # 自适应：网格不能粗于音符的最短显著时值，否则吞掉真实存在的短音符。
        min_duration = _shortest_significant_duration(ctx.track.notes)
        if min_duration is not None:
            required_step = _grid_step_for_duration(min_duration)
            if required_step < grid.step_beats:
                grid = GridStep(f"adaptive_{grid.name}", required_step)
                ctx.warnings.append(
                    f"Grid refined to {required_step} beats (shortest significant "
                    f"duration {min_duration:.3f} beats)."
                )
        ctx.warnings.append(f"Selected grid: {grid.name} (step={grid.step_beats})")

        for index, note in enumerate(ctx.track.notes):
            quantized_start = _round_to_grid(note.start_beat, grid.step_beats)
            quantized_duration = _quantize_duration(
                note.duration_beats, grid.step_beats
            )
            confidence = _compute_confidence(
                note.start_beat,
                quantized_start,
                note.duration_beats,
                quantized_duration,
                grid.step_beats,
            )
            if abs(note.start_beat - quantized_start) > _EPSILON:
                ctx.add_transformation(
                    stage="quantize_onset",
                    source_note_index=index,
                    before={"start_beat": note.start_beat},
                    after={"start_beat": quantized_start},
                    confidence=confidence,
                    reason=f"snap_to_{grid.name}_grid",
                )
            ctx.quantized_notes.append(
                QuantizedNote(
                    source_index=index,
                    pitch=note.pitch,
                    velocity=note.velocity,
                    original_start_beat=note.start_beat,
                    original_duration_beats=note.duration_beats,
                    quantized_start_beat=quantized_start,
                    quantized_duration_beats=quantized_duration,
                    confidence=confidence,
                )
            )

        ctx.record_stage(self.name)
        return ctx


__all__ = [
    "QuantizeStage",
    "_shortest_significant_duration",
    "_grid_step_for_duration",
]
