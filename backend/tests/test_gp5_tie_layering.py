"""GP5 同 onset 多时值和弦的分层 tie 导出测试。

回归 bug：旧实现把和弦里多个长音符的 tie 延长串行推进（每个长音符单独一个
beat、cursor 依次前进），导致小节时值溢出（Guitar Pro 红音符）。修复后按
distinct 时值从短到长分层，每一层一个 beat 承载所有仍在持续的音符（并行），
同 onset 多时值和弦的延长不再累积成非法时值。
"""

from __future__ import annotations

from pathlib import Path

import guitarpro as gp
import pytest

from fretpilot.engine.context import PipelineContext
from fretpilot.engine.pipeline import create_pipeline
from fretpilot.exporters.gp5 import GP5Exporter
from fretpilot.midi.parser import load_midi
from tests.test_multivoice import _FIXTURE, _make_event, _make_ir, _tokyo_cleaned_track

_QUARTER = gp.Duration.quarterTime  # 960 ticks


def _note_ticks(measure: gp.Measure, voice_index: int = 0) -> int:
    """Return total ticks of non-rest beats in a voice (the consumed duration)."""
    return sum(
        b.duration.time
        for b in measure.voices[voice_index].beats
        if b.status != gp.BeatStatus.rest
    )


def _voice_ticks(measure: gp.Measure, voice_index: int = 0) -> int:
    """Return total ticks of all beats (incl. trailing rests) in a voice."""
    return sum(b.duration.time for b in measure.voices[voice_index].beats)


def _export_and_parse(ir, tmp_path: Path, name: str = "out.gp5"):
    """Export IR to GP5 and parse it back, returning ``(result, song)``."""
    out = tmp_path / name
    result = GP5Exporter().export(ir, out)
    with open(out, "rb") as f:
        song = gp.parse(f)
    return result, song


class TestGP5TieLayering:
    """同 onset 不同时值和弦的分层 tie 导出验证。"""

    def test_chord_unequal_durations_tie_layered(self, tmp_path: Path) -> None:
        """同 onset 和弦 (1.75/1.75/1.0/0.5) 分层后总时值 = 1.75 拍，不溢出。"""
        events = [
            _make_event(0, 45, 0.0, 1.75, voice=1, string=5, fret=0),
            _make_event(1, 50, 0.0, 1.75, voice=1, string=4, fret=0),
            _make_event(2, 53, 0.0, 1.0, voice=1, string=3, fret=0),
            _make_event(3, 65, 0.0, 0.5, voice=1, string=1, fret=1),
        ]
        ir = _make_ir(events)
        result, song = _export_and_parse(ir, tmp_path, "layered.gp5")

        measure = song.tracks[0].measures[0]
        capacity = measure.end - measure.start

        # 主 0.5 + 层1 0.5 + 层2 0.75 = 1.75 拍 = 1680 ticks（并行分层，不串行）。
        assert _note_ticks(measure) == 1680
        # 整 voice（含尾部 rest 补齐）不超过小节容量。
        assert _voice_ticks(measure) <= capacity
        # 4 主 + 3 层1 + 2 层2 = 9 个 note。
        assert result.note_count == 9

    def test_chord_two_durations_tie_layered(self, tmp_path: Path) -> None:
        """同 onset 和弦 (4×1.0 + 0.5) 分层后总时值 = 1.0 拍（不是串行的 2.5）。"""
        events = [
            _make_event(0, 43, 0.0, 1.0, voice=1, string=5, fret=3),
            _make_event(1, 50, 0.0, 1.0, voice=1, string=4, fret=0),
            _make_event(2, 55, 0.0, 1.0, voice=1, string=3, fret=0),
            _make_event(3, 58, 0.0, 1.0, voice=1, string=2, fret=3),
            _make_event(4, 82, 0.0, 0.5, voice=1, string=1, fret=18),
        ]
        ir = _make_ir(events)
        result, song = _export_and_parse(ir, tmp_path, "two_dur.gp5")

        measure = song.tracks[0].measures[0]

        # 主 0.5 + 层1 0.5 = 1.0 拍 = 960 ticks。串行实现会得到 2.5 拍 = 2400。
        assert _note_ticks(measure) == 960
        assert result.note_count == 9  # 5 主 + 4 层1

    def test_tie_extension_respects_measure_end(self, tmp_path: Path) -> None:
        """长音符越过小节末尾时被截断，文件仍可回读、不溢出。"""
        events = [
            _make_event(0, 60, 0.0, 4.5, voice=1, string=4, fret=10),
            _make_event(1, 64, 0.0, 0.5, voice=1, string=1, fret=0),
        ]
        ir = _make_ir(events)
        result, song = _export_and_parse(ir, tmp_path, "overflow.gp5")

        measure = song.tracks[0].measures[0]
        capacity = measure.end - measure.start

        # 触发防御性截断告警。
        assert any(
            "truncated" in w.lower() or "measure overflow" in w.lower()
            for w in result.warnings
        )
        assert song is not None
        assert len(song.tracks[0].measures) >= 1
        assert _voice_ticks(measure) <= capacity


class TestTokyoMidnightNoOverflow:
    """真实脏样本端到端：measure 60 / 72 不再时值溢出（红音符消除）。"""

    def test_tokyo_midnight_measures_no_overflow(self, tmp_path: Path) -> None:
        timeline = load_midi(_FIXTURE)
        cleaned_track, role = _tokyo_cleaned_track(timeline)

        pipeline = create_pipeline()
        ctx = PipelineContext(
            timeline=timeline,
            track=cleaned_track,
            knowledge=pipeline.registry,
            style_label="unknown",
            midi_fidelity=0.5,
            advisor=None,
            track_role=role,
            source_track_index=cleaned_track.index,
            degraded_mode=True,
        )
        ir = pipeline.execute(ctx)

        result, song = _export_and_parse(ir, tmp_path, "tokyo.gp5")
        assert result.note_count > 0

        measures = song.tracks[0].measures
        by_number = {m.number: m for m in measures}
        # 修复目标是 60 / 72 小节（4/4 容量 4 拍 = 3840 ticks）。
        for target in (60, 72):
            assert target in by_number, f"measure {target} should exist in output"
            measure = by_number[target]
            capacity = measure.end - measure.start
            for voice in measure.voices:
                total = sum(b.duration.time for b in voice.beats)
                assert total <= capacity, (
                    f"measure {target} voice overflow: {total} > {capacity}"
                )
