"""Tokyo Midnight 全链路集成测试 —— parse → detect → cleanup → pipeline → IR。

用真实脏样本 ``tokyo_midnight.mid`` 跑完整 repair pipeline，验证 cleanup
集成后下游各 stage（quantize → measure_split → tie → voice → fingering →
articulation → assemble）不会因 cleaned track（从 LogicalStream 构建）或
超范围音高而崩溃，最终产出有效的 GuitarProjectIR。

样本特征：2151 个音符、pitch 31..89（超 6 弦标准定弦音域）、195 个近似
重复 tempo、全部 velocity 61、171 处同音高重叠。cleanup 以 flag 模式运行
（不删音符），超范围音高流入 fingering stage 时被标记为不可按弦
（string/fret=None），不会引发异常。
"""

from __future__ import annotations

from pathlib import Path

from fretpilot.detection import classify_timeline, resolve_streams
from fretpilot.engine.cleanup import auto_detect_tuning, cleanup_streams
from fretpilot.engine.context import PipelineContext
from fretpilot.engine.pipeline import create_pipeline
from fretpilot.midi.models import NormalizedTrack
from fretpilot.midi.parser import load_midi

_FIXTURE = Path(__file__).parent / "fixtures" / "tokyo_midnight.mid"


def _build_cleaned_track(timeline) -> tuple[NormalizedTrack, str]:
    """parse → detect → cleanup → 从 cleaned stream 构建 NormalizedTrack。

    返回 ``(cleaned_track, guitar_role)``。取 note_count 最多的流作为主吉他流。
    """
    report = classify_timeline(timeline)
    assert report.primary_guitar_track_index is not None

    streams = resolve_streams(timeline)
    tuning = auto_detect_tuning(streams)
    clean_result = cleanup_streams(streams, timeline=timeline, tuning=tuning)

    # flag 模式不删音符，流必非空。
    assert clean_result.streams, "cleanup should retain at least one stream"
    primary_stream = max(clean_result.streams, key=lambda s: s.note_count)
    cleaned_track = NormalizedTrack(
        index=report.primary_guitar_track_index or 0,
        name=primary_stream.track_name,
        notes=list(primary_stream.notes),
        instrument_name=primary_stream.instrument_name,
        program=primary_stream.program,
    )
    role = (
        report.primary_classification.guitar_role
        if report.primary_classification
        else "unknown"
    )
    return cleaned_track, role


class TestFullPipelineTokyoMidnight:
    """完整 pipeline 在 Tokyo Midnight 脏样本上的端到端验证。"""

    def test_full_pipeline_tokyo_midnight(self) -> None:
        """完整 pipeline: parse → detect → cleanup → quantize → ... → assemble。"""
        timeline = load_midi(_FIXTURE)
        cleaned_track, role = _build_cleaned_track(timeline)

        # cleaned track 必须携带音符（与原始 NormalizedTrack 字段一致）。
        assert cleaned_track.notes, "cleaned track should carry notes"
        assert len(cleaned_track.notes) > 0

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

        # 关键断言：pipeline 不应因 cleaned track / 超范围音高而抛异常。
        ir = pipeline.execute(ctx)

        # 验证 IR 结构完整。
        assert ir is not None
        assert len(ir.tracks) > 0, "IR should contain at least one track"
        assert len(ir.tracks[0].measures) > 0, "IR track should have measures"

        total_notes = sum(len(m.events) for t in ir.tracks for m in t.measures)
        assert total_notes > 0, "Pipeline produced zero notes"
        assert len(ir.changes) >= 0
        # warnings 字段存在（可能含 measure-split 提示等）。
        assert isinstance(ir.warnings, list)

    def test_cleanup_to_pipeline_data_flow(self) -> None:
        """cleanup 产出的 cleaned track 字段与原始 NormalizedTrack 一致。

        QuantizeStage 读取 ``ctx.track.notes`` 的 start_beat / duration_beats /
        pitch / velocity，cleaned track 必须保留这些字段且类型正确。
        """
        timeline = load_midi(_FIXTURE)
        cleaned_track, _ = _build_cleaned_track(timeline)

        for note in cleaned_track.notes:
            assert isinstance(note.pitch, int)
            assert isinstance(note.velocity, int)
            assert isinstance(note.start_beat, float)
            assert isinstance(note.duration_beats, float)
            assert note.duration_beats > 0, "cleanup must not leave 0-duration notes"

    def test_out_of_range_pitches_do_not_crash_fingering(self) -> None:
        """超范围音高（pitch 31..39 / 89）流入 fingering 不应崩溃。

        Tokyo Midnight 的 pitch 31..89 超出 6 弦标准定弦音域（40-88），
        fingering stage 会把它们标记为不可按弦（string/fret=None），而非抛异常。
        """
        timeline = load_midi(_FIXTURE)
        cleaned_track, role = _build_cleaned_track(timeline)
        pitches = {n.pitch for n in cleaned_track.notes}
        # 样本确实含超 6 弦音域的音高（31..39 与 89）。
        out_of_range = {p for p in pitches if p < 40 or p > 88}
        assert out_of_range, "sample should contain out-of-range pitches"

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

        # 超范围音高被保留为不可按弦事件（string/fret=None），pipeline 仍产出音符。
        unplayable = [
            e
            for t in ir.tracks
            for m in t.measures
            for e in m.events
            if not e.fingering.playable
        ]
        assert unplayable, "out-of-range pitches should be marked unplayable, not dropped"
        total_notes = sum(len(m.events) for t in ir.tracks for m in t.measures)
        assert total_notes > 0
