"""量化网格自适应测试 —— 网格不能粗于音符的最短显著时值。

回归背景：修复前 ``select_grid`` 只按风格密度选网格，rock（note_density_range
[3, 10]）在 fidelity=0.5 下返回 eighth（step=0.5），而 ``_quantize_duration``
强制 duration ≥ step，导致真实存在的 16 分音符（0.25）被拉到 0.5 吞掉。

修复后：QuantizeStage 会统计音符的最短显著时值，若风格网格粗于该值则自适应
细化，从而在任何 fidelity 下都保留 16 分音符。
"""

from __future__ import annotations

from math import isclose
from pathlib import Path

import pytest

from fretpilot.engine.context import PipelineContext
from fretpilot.engine.stages.quantize import (
    QuantizeStage,
    _grid_step_for_duration,
    _shortest_significant_duration,
)
from fretpilot.knowledge.engine import KnowledgeEngine
from fretpilot.midi.models import NormalizedTrack

from tests.conftest import _MockAdvisor, _note, _timeline

_FIXTURE = Path(__file__).parent / "fixtures" / "tokyo_midnight.mid"


def _build_ctx(
    notes,
    engine: KnowledgeEngine,
    *,
    style_label: str = "rock",
    fidelity: float = 0.5,
) -> PipelineContext:
    """构造最小 PipelineContext（degraded mode，风格默认 rock）。"""
    timeline = _timeline(notes)
    track = (
        timeline.tracks[0]
        if timeline.tracks
        else NormalizedTrack(index=0, name="Empty", notes=[])
    )
    return PipelineContext(
        timeline=timeline,
        track=track,
        knowledge=engine.registry,
        style_label=style_label,
        midi_fidelity=fidelity,
        advisor=_MockAdvisor(),
        track_role="rhythm",
        source_track_index=0,
        degraded_mode=True,
    )


class TestAdaptiveGridQuantization:
    """QuantizeStage 网格自适应行为。"""

    def test_sixteenth_notes_preserved(self, engine: KnowledgeEngine) -> None:
        """含 16 分音符的 rock track 量化后 duration 仍为 0.25（不变成 0.5）。"""
        notes = [
            _note(pitch=60, start_beat=i * 0.25, duration_beats=0.25)
            for i in range(8)
        ]
        ctx = _build_ctx(notes, engine, style_label="rock", fidelity=0.5)
        QuantizeStage(engine).run(ctx)

        assert len(ctx.quantized_notes) == 8
        for n in ctx.quantized_notes:
            assert isclose(n.quantized_duration_beats, 0.25, abs_tol=1e-6), (
                f"16 分音符被吞成 {n.quantized_duration_beats} beats"
            )

    def test_eighth_notes_not_over_refined(self, engine: KnowledgeEngine) -> None:
        """只含 8 分音符时，网格不被无谓细化到 16 分（仍是 0.5）。"""
        notes = [
            _note(pitch=60, start_beat=i * 0.5, duration_beats=0.5)
            for i in range(4)
        ]
        ctx = _build_ctx(notes, engine, style_label="rock", fidelity=0.5)
        QuantizeStage(engine).run(ctx)

        # rock @ 0.5 fidelity 默认 eighth(0.5)，最短显著时值也是 0.5 → 不细化。
        assert "step=0.5" in ctx.warnings[-1]
        assert all("adaptive" not in w for w in ctx.warnings)
        for n in ctx.quantized_notes:
            assert isclose(n.quantized_duration_beats, 0.5, abs_tol=1e-6)

    def test_noise_short_notes_ignored(self, engine: KnowledgeEngine) -> None:
        """占比 < 1% 的极短噪声音符不主导网格（不被拉到 0.125）。"""
        notes = [
            _note(pitch=60, start_beat=i * 0.5, duration_beats=0.5)
            for i in range(200)
        ]
        # 混入 1 个 0.119 的噪声短音符（占比 1/201 ≈ 0.5% < 1%）。
        notes.append(_note(pitch=62, start_beat=100.0, duration_beats=0.119))
        ctx = _build_ctx(notes, engine, style_label="rock", fidelity=0.5)
        QuantizeStage(engine).run(ctx)

        assert "step=0.5" in ctx.warnings[-1]
        assert all("adaptive" not in w for w in ctx.warnings)


class TestShortestSignificantDuration:
    """单元测试 ``_shortest_significant_duration``。"""

    def test_ignores_micro_notes(self) -> None:
        """duration < 0.06 的微音符被忽略。"""
        notes = [_note(60, 0.0, 0.04), _note(62, 1.0, 0.5)]
        assert _shortest_significant_duration(notes) == pytest.approx(0.5)

    def test_ignores_low_ratio_noise(self) -> None:
        """占比 < 1% 的极短音符被忽略，不拉低最短时值。"""
        notes = [_note(60, i * 0.5, 0.5) for i in range(200)]
        notes.append(_note(62, 100.0, 0.119))
        assert _shortest_significant_duration(notes) == pytest.approx(0.5)

    def test_returns_shortest_significant(self) -> None:
        """返回剩余显著音符中的最短 duration。"""
        notes = [_note(60, 0.0, 0.25), _note(62, 1.0, 0.5)]
        assert _shortest_significant_duration(notes) == pytest.approx(0.25)

    def test_empty_returns_none(self) -> None:
        """无音符返回 None。"""
        assert _shortest_significant_duration([]) is None

    def test_all_micro_returns_none(self) -> None:
        """全部是微音符时返回 None（兜底，不参与网格细化）。"""
        notes = [_note(60, 0.0, 0.04), _note(62, 1.0, 0.05)]
        assert _shortest_significant_duration(notes) is None


class TestGridStepForDuration:
    """单元测试 ``_grid_step_for_duration``。"""

    def test_sixteenth(self) -> None:
        assert _grid_step_for_duration(0.25) == 0.25

    def test_eighth(self) -> None:
        assert _grid_step_for_duration(0.5) == 0.5

    def test_quarter(self) -> None:
        assert _grid_step_for_duration(1.0) == 1.0

    def test_below_thirtysecond_clamps(self) -> None:
        """低于 32 分（0.125）时钳制到 0.125。"""
        assert _grid_step_for_duration(0.06) == 0.125


class TestTokyoMidnightSixteenthPreserved:
    """Tokyo Midnight 完整样本：修复前 16 分音符数量为 0，修复后应 > 0。"""

    def test_tokyo_midnight_sixteenth_preserved(
        self, engine: KnowledgeEngine
    ) -> None:
        timeline = _load_tokyo_timeline()
        cleaned_track = _build_cleaned_track(timeline)

        ctx = PipelineContext(
            timeline=timeline,
            track=cleaned_track,
            knowledge=engine.registry,
            style_label="rock",  # 复现根因：rock 默认 eighth(0.5)
            midi_fidelity=0.5,
            advisor=None,
            track_role="rhythm",
            source_track_index=cleaned_track.index,
            degraded_mode=True,
        )
        QuantizeStage(engine).run(ctx)

        sixteenths = [
            n
            for n in ctx.quantized_notes
            if isclose(n.quantized_duration_beats, 0.25, abs_tol=1e-6)
        ]
        assert len(sixteenths) > 0, "量化后应保留 16 分音符（duration 0.25）"
        # 16 分音符是样本中最多的时值类别（803 个），应显著保留。
        assert len(sixteenths) > 100


def _load_tokyo_timeline():
    """加载 Tokyo Midnight 样本。"""
    from fretpilot.midi.parser import load_midi

    return load_midi(_FIXTURE)


def _build_cleaned_track(timeline) -> NormalizedTrack:
    """parse → detect → cleanup → 从 cleaned stream 构建主吉他 NormalizedTrack。"""
    from fretpilot.detection import classify_timeline, resolve_streams
    from fretpilot.engine.cleanup import auto_detect_tuning, cleanup_streams

    report = classify_timeline(timeline)
    assert report.primary_guitar_track_index is not None

    streams = resolve_streams(timeline)
    tuning = auto_detect_tuning(streams)
    clean_result = cleanup_streams(streams, timeline=timeline, tuning=tuning)
    assert clean_result.streams, "cleanup should retain at least one stream"

    primary_stream = max(clean_result.streams, key=lambda s: s.note_count)
    return NormalizedTrack(
        index=report.primary_guitar_track_index or 0,
        name=primary_stream.track_name,
        notes=list(primary_stream.notes),
        instrument_name=primary_stream.instrument_name,
        program=primary_stream.program,
    )
