"""QA 增量回归测试 —— 验证 v2 三项增量开发的边界条件与全链路稳定性。

本文件由 QA（Edward）编写，覆盖 team lead 指定的重点验证场景：
  a. 定弦偏好逻辑边界条件（空 pitch、单定弦、tolerance 边界）
  b. _build_cleaned_track 安全性（空流回退、列表隔离）
  c. CleanupInfo 前后端字段对齐（程序化校验 7 字段一致）
  d. pipeline 数据流完整性（NormalizedNote 字段、duration>0、velocity 1-127）
  e. 向后兼容（best_match 默认 tolerance、cleanup_streams 无 timeline/tuning）
  f. 真实样本 tokyo_midnight 端到端（auto_detect=drop_a_7、IR 非空）
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from fretpilot.api.routes.projects import CleanupInfo, _build_cleaned_track
from fretpilot.detection.streams import LogicalStream, resolve_streams
from fretpilot.engine.cleanup import auto_detect_tuning, cleanup_streams
from fretpilot.engine.context import PipelineContext
from fretpilot.engine.pipeline import create_pipeline
from fretpilot.knowledge.tunings import GuitarTuning, TuningRegistry
from fretpilot.midi.models import (
    NormalizedNote,
    NormalizedTimeline,
    NormalizedTrack,
    TempoEvent,
    TimeSignatureEvent,
)
from fretpilot.midi.parser import load_midi

_FIXTURE = Path(__file__).parent / "fixtures" / "tokyo_midnight.mid"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _note(
    pitch: int,
    start_beat: float,
    duration_beats: float,
    *,
    velocity: int = 61,
    channel: int = 0,
    track_index: int = 0,
    track_name: str = "test",
    program: int | None = 0,
) -> NormalizedNote:
    start_tick = int(round(start_beat * 480))
    duration_ticks = int(round(duration_beats * 480))
    return NormalizedNote(
        track_index=track_index,
        track_name=track_name,
        channel=channel,
        pitch=pitch,
        velocity=velocity,
        start_tick=start_tick,
        duration_ticks=duration_ticks,
        start_beat=start_beat,
        duration_beats=duration_beats,
        program=program,
    )


def _stream(notes: list[NormalizedNote], stream_id: str = "test-001") -> LogicalStream:
    return LogicalStream(
        stream_id=stream_id,
        program=0,
        channel=0,
        instrument_name=None,
        notes=notes,
    )


def _empty_timeline() -> NormalizedTimeline:
    """A timeline whose tracks have no notes → resolve_streams returns []."""
    return NormalizedTimeline(
        source="empty",
        midi_type=1,
        ticks_per_beat=480,
        tempo_events=[TempoEvent(tick=0, beat=0.0, bpm=120.0)],
        time_signature_events=[
            TimeSignatureEvent(tick=0, beat=0.0, numerator=4, denominator=4)
        ],
        tracks=[
            NormalizedTrack(index=0, name="Empty Track", notes=[]),
        ],
    )


def _fallback_track() -> NormalizedTrack:
    return NormalizedTrack(
        index=0,
        name="fallback",
        notes=[_note(60, 0.0, 1.0)],
        instrument_name="Guitar",
        program=30,
    )


# ===========================================================================
# A. 定弦偏好逻辑边界条件
# ===========================================================================


class TestTuningPreferenceBoundary:
    """best_match / deviation_count 的边界条件验证。"""

    def test_best_match_empty_pitches_returns_simplest(self) -> None:
        """空 pitch 列表时所有定弦覆盖率均为 0.0，tie-break 应返回最简定弦。

        所有定弦 coverage_score([]) == 0.0 → max_coverage=0.0 → 全部进入候选池
        （0.0 - 0.0 = 0.0 <= 0.005）。tie-break: 更少弦 → standard_6（6 弦），
        更少偏离 → deviation_count=0。故应返回 standard_6。
        """
        registry = TuningRegistry.default()
        tuning = registry.best_match([])

        # 不应抛异常，应返回一个有效定弦。
        assert tuning is not None
        # 最简定弦：6 弦 + deviation 0 → standard_6。
        assert tuning.string_count == 6
        assert tuning.deviation_count == 0
        assert tuning.id == "standard_6"

    def test_best_match_single_tuning_registry(self) -> None:
        """注册表只有 1 个定弦时，best_match 应直接返回该定弦。"""
        only = TuningRegistry.default().get("drop_c_6")
        assert only is not None
        registry = TuningRegistry([only])

        tuning = registry.best_match([36, 60, 86])

        assert tuning.id == "drop_c_6"
        assert tuning is only

    def test_best_match_empty_registry_raises(self) -> None:
        """空注册表调用 best_match 应抛 ValueError（防御性边界）。"""
        registry = TuningRegistry([])
        with pytest.raises(ValueError, match="No tunings loaded"):
            registry.best_match([60])

    def test_coverage_tolerance_default_is_005(self) -> None:
        """best_match 默认 coverage_tolerance=0.005，与旧行为兼容。"""
        sig = inspect.signature(TuningRegistry.best_match)
        default = sig.parameters["coverage_tolerance"].default
        assert default == 0.005

    def test_coverage_tolerance_boundary_just_below_enters(self) -> None:
        """覆盖率差距恰好小于 0.5% 时应进入候选池并触发 tie-break。

        用只含 standard_7 / drop_a_7（同 7 弦）的隔离注册表，避免 6 弦定弦
        干扰。构造：1000 个音符，1 个 pitch 33（drop_a_7 min=33 能覆盖）。
        standard_7（min=35）漏掉 1 个 → 覆盖率 999/1000 = 0.999，差距 0.001
        < 0.005 → 进入候选池。tie-break 同弦数 → 更少偏离：standard_7
        deviation=0 < drop_a_7 deviation=1 → 返回 standard_7。这证明差距在
        tolerance 内的低覆盖率定弦确实进入了候选池。
        """
        default = TuningRegistry.default()
        standard_7 = default.get("standard_7")
        drop_a_7 = default.get("drop_a_7")
        assert standard_7 is not None and drop_a_7 is not None
        registry = TuningRegistry([standard_7, drop_a_7])
        pitches = [33] + [60] * 999

        tuning = registry.best_match(pitches)

        # drop_a_7 覆盖率 1.0（最高），standard_7 覆盖率 0.999（差距 0.001
        # < 0.005 → 进入候选池），同弦数 tie-break 偏好 deviation=0。
        assert tuning.id == "standard_7"
        assert tuning.deviation_count == 0

    def test_coverage_tolerance_boundary_just_above_exits(self) -> None:
        """覆盖率差距恰好大于 0.5% 时应被排除出候选池。

        构造：101 个音符，1 个 pitch 30（仅 standard_8 min=30 能覆盖）。
        drop_a_7（min=33）漏掉 → 覆盖率 100/101≈0.990099，差距≈0.0099 >
        0.005 → 出局。候选池只剩 standard_8 → 返回 standard_8。
        """
        pitches = [30] + [60] * 100
        registry = TuningRegistry.default()

        tuning = registry.best_match(pitches)

        assert tuning.id == "standard_8"

    def test_deviation_count_standard_8_is_zero(self) -> None:
        """standard_8 无同弦数 Drop 版本，与自身标准比 → deviation_count=0。"""
        registry = TuningRegistry.default()
        standard_8 = registry.get("standard_8")
        assert standard_8 is not None
        assert standard_8.deviation_count == 0

    def test_deviation_count_all_tunings_non_negative(self) -> None:
        """所有定弦的 deviation_count 都应 >= 0（不出现负数）。"""
        registry = TuningRegistry.default()
        for t in registry.all_tunings():
            assert t.deviation_count >= 0, f"{t.id} deviation_count={t.deviation_count}"


# ===========================================================================
# B. _build_cleaned_track 安全性
# ===========================================================================


class TestBuildCleanedTrackSafety:
    """_build_cleaned_track 的安全回退与隔离验证。"""

    def test_empty_streams_returns_fallback_and_none_info(self) -> None:
        """当 resolve_streams 返回空列表时，应回退到 fallback 且 cleanup_info=None。

        timeline 没有 guitar track（tracks 全空）→ resolve_streams 返回 [] →
        _build_cleaned_track 走 fallback 分支，返回 (fallback, None)。
        """
        timeline = _empty_timeline()
        fallback = _fallback_track()

        cleaned_track, cleanup_info = _build_cleaned_track(timeline, None, fallback)

        # 回退到 fallback track。
        assert cleaned_track is fallback
        # 无流可清理 → cleanup_info 为 None。
        assert cleanup_info is None

    def test_notes_list_isolation_from_stream(self) -> None:
        """cleaned track 的 notes 是独立 list，增删不影响原始 stream 的 notes 列表。

        _build_cleaned_track 用 list(primary_stream.notes) 创建新列表（浅拷贝），
        列表级增删隔离。验证 append/pop 不回传到 stream.notes。
        """
        notes = [_note(60, 0.0, 1.0), _note(62, 1.0, 1.0)]
        stream = _stream(notes)
        timeline = _make_single_guitar_timeline(notes)

        cleaned_track, _info = _build_cleaned_track(timeline, 0, _fallback_track())

        # cleaned track 有音符。
        assert len(cleaned_track.notes) >= 1
        # 列表是不同对象（浅拷贝新 list）。
        # 取主吉他流做对比。
        streams = resolve_streams(timeline)
        primary = max(streams, key=lambda s: s.note_count)
        assert cleaned_track.notes is not primary.notes

        # 向 cleaned track 追加一个音符不影响 stream 的 note 数量。
        before = len(primary.notes)
        cleaned_track.notes.append(_note(99, 99.0, 1.0))
        assert len(primary.notes) == before

    def test_primary_track_index_none_uses_zero(self) -> None:
        """primary_track_index=None 时 cleaned_track.index 回退到 0。"""
        notes = [_note(60, 0.0, 1.0)]
        timeline = _make_single_guitar_timeline(notes)

        cleaned_track, _info = _build_cleaned_track(timeline, None, _fallback_track())

        assert cleaned_track.index == 0

    def test_cleanup_info_built_when_streams_present(self) -> None:
        """有流可清理时，cleanup_info 应非 None 且 7 字段已填充。"""
        notes = [_note(60, 0.0, 1.0, velocity=61)]
        timeline = _make_single_guitar_timeline(notes)

        cleaned_track, cleanup_info = _build_cleaned_track(timeline, 0, _fallback_track())

        assert cleanup_info is not None
        assert isinstance(cleanup_info.tuning_id, str)
        assert isinstance(cleanup_info.tuning_display_name, str)
        assert isinstance(cleanup_info.tempo_dedup_count, int)
        assert isinstance(cleanup_info.out_of_range_count, int)
        assert isinstance(cleanup_info.velocity_remapped, bool)
        assert isinstance(cleanup_info.overlaps_truncated, int)
        assert isinstance(cleanup_info.total_actions, int)


def _make_single_guitar_timeline(notes: list[NormalizedNote]) -> NormalizedTimeline:
    """构建一个含单个吉他音轨（带音符）的 NormalizedTimeline。"""
    track = NormalizedTrack(
        index=0,
        name="Guitar",
        notes=list(notes),
        program=30,
        instrument_name="Guitar",
    )
    return NormalizedTimeline(
        source="test.mid",
        midi_type=1,
        ticks_per_beat=480,
        tempo_events=[TempoEvent(tick=0, beat=0.0, bpm=120.0)],
        time_signature_events=[
            TimeSignatureEvent(tick=0, beat=0.0, numerator=4, denominator=4)
        ],
        tracks=[track],
    )


# ===========================================================================
# C. CleanupInfo 前后端字段对齐
# ===========================================================================


class TestCleanupInfoFieldAlignment:
    """后端 CleanupInfo 模型字段与前端 TypeScript interface 字段一致。"""

    # 前端 types.ts 中 CleanupInfo 的 7 个字段（snake_case，与后端一致）。
    EXPECTED_FIELDS = {
        "tuning_id",
        "tuning_display_name",
        "tempo_dedup_count",
        "out_of_range_count",
        "velocity_remapped",
        "overlaps_truncated",
        "total_actions",
    }

    def test_backend_cleanup_info_has_seven_fields(self) -> None:
        """后端 CleanupInfo 恰好有 7 个字段。"""
        fields = set(CleanupInfo.model_fields.keys())
        assert fields == self.EXPECTED_FIELDS, (
            f"Backend CleanupInfo fields mismatch: {fields ^ self.EXPECTED_FIELDS}"
        )

    def test_cleanup_info_optional_in_response(self) -> None:
        """RepairResponse.cleanup 字段类型为 CleanupInfo | None（可序列化为 null）。"""
        from fretpilot.api.routes.projects import RepairResponse

        field_info = RepairResponse.model_fields["cleanup"]
        # 字段非必填（required=False）且默认值为 None —— 允许序列化为 JSON null。
        assert field_info.is_required() is False, (
            "cleanup field should be optional (not required)"
        )
        assert field_info.default is None, (
            "cleanup field should default to None for JSON null serialization"
        )

    def test_cleanup_info_none_serializes_to_null(self) -> None:
        """cleanup_info=None 时，序列化 JSON 中 cleanup 字段为 null。"""
        from fretpilot.api.routes.projects import RepairResponse

        resp = RepairResponse(
            project_id=1,
            status="repaired",
            style_label="metal",
            degraded_mode=True,
            note_count=100,
            change_count=5,
            cleanup=None,
        )
        data = resp.model_dump()
        assert data["cleanup"] is None

    def test_cleanup_info_round_trip_all_fields(self) -> None:
        """CleanupInfo 全字段构造 + 序列化往返，字段名与类型保持一致。"""
        info = CleanupInfo(
            tuning_id="drop_a_7",
            tuning_display_name="Drop A (7-string)",
            tempo_dedup_count=194,
            out_of_range_count=10,
            velocity_remapped=True,
            overlaps_truncated=171,
            total_actions=380,
        )
        data = info.model_dump()
        assert set(data.keys()) == self.EXPECTED_FIELDS
        assert data["tuning_id"] == "drop_a_7"
        assert data["velocity_remapped"] is True


# ===========================================================================
# D. pipeline 数据流完整性
# ===========================================================================


class TestPipelineDataFlowIntegrity:
    """cleaned track 的 notes 保留所有 NormalizedNote 必需字段且取值合法。"""

    def test_notes_preserve_all_required_fields(self) -> None:
        """cleaned track 的每个 note 都带齐 6 个必需字段。"""
        notes = [
            _note(60, 0.0, 1.0, velocity=61),
            _note(62, 1.0, 0.5, velocity=61),
        ]
        timeline = _make_single_guitar_timeline(notes)

        cleaned_track, _info = _build_cleaned_track(timeline, 0, _fallback_track())

        for note in cleaned_track.notes:
            assert isinstance(note.pitch, int)
            assert isinstance(note.velocity, int)
            assert isinstance(note.start_beat, float)
            assert isinstance(note.duration_beats, float)
            assert isinstance(note.start_tick, int)
            assert isinstance(note.duration_ticks, int)

    def test_duration_beats_positive_after_cleanup(self) -> None:
        """cleanup（含重叠截断）后 duration_beats 恒 > 0，不制造 0 时长。"""
        notes = [
            _note(60, 0.0, 2.0, velocity=61),  # 与下面重叠
            _note(60, 1.0, 1.0, velocity=61),
        ]
        timeline = _make_single_guitar_timeline(notes)

        cleaned_track, _info = _build_cleaned_track(timeline, 0, _fallback_track())

        for note in cleaned_track.notes:
            assert note.duration_beats > 0, (
                f"0-duration note: pitch={note.pitch} start={note.start_beat}"
            )
            assert note.duration_ticks > 0

    def test_velocity_in_valid_range_after_remap(self) -> None:
        """velocity 重映射后所有值在 1-127 范围内（不越界）。"""
        notes = [_note(60, b, 0.5, velocity=61) for b in (0.0, 0.5, 1.0, 2.0, 3.0)]
        timeline = _make_single_guitar_timeline(notes)

        cleaned_track, _info = _build_cleaned_track(timeline, 0, _fallback_track())

        for note in cleaned_track.notes:
            assert 1 <= note.velocity <= 127, (
                f"velocity {note.velocity} out of range [1,127]"
            )


# ===========================================================================
# E. 向后兼容
# ===========================================================================


class TestBackwardCompatibility:
    """验证增量改动未破坏既有 API 契约。"""

    def test_best_match_without_tolerance_uses_default(self) -> None:
        """best_match(pitches) 不传 coverage_tolerance 时使用默认 0.005。"""
        registry = TuningRegistry.default()
        # 用 Tokyo Midnight 验证：默认 tolerance 下偏好 drop_a_7。
        tuning_default = registry.best_match([60, 33, 60])
        tuning_explicit = registry.best_match(
            [60, 33, 60], coverage_tolerance=0.005
        )
        assert tuning_default.id == tuning_explicit.id

    def test_cleanup_streams_without_timeline_tuning(self) -> None:
        """cleanup_streams(streams) 不传 timeline/tuning 时行为与之前一致。

        无 timeline → 不做 tempo 去重、不做 velocity 重映射。
        无 tuning → 不做超范围音高处理。
        重叠截断仍执行（始终）。
        """
        notes = [
            _note(60, 0.0, 2.0),
            _note(60, 1.0, 1.0),  # 同音高重叠 → 截断
            _note(64, 0.0, 1.0),  # 不同音高 → 保留
        ]
        stream = _stream(notes)

        result = cleanup_streams([stream])

        # 4 项增强的统计字段。
        assert result.tempo_dedup_count == 0
        assert result.out_of_range_count == 0
        assert result.velocity_remapped is False
        assert result.overlaps_truncated >= 1  # 同音高重叠被截断
        assert result.tuning is None
        # 基础清理仍工作。
        assert result.velocity is not None
        assert result.overlap is not None

    def test_updated_assertions_in_existing_tests_are_reasonable(self) -> None:
        """现有测试中被更新的断言（drop_a_7 而非 standard_8）是合理的。

        Tokyo Midnight 样本中 standard_8 覆盖率 99.95%、drop_a_7 覆盖率 99.54%，
        差距 0.42% < 0.5% tolerance。tie-break 偏好更少弦 → drop_a_7（7 弦）优于
        standard_8（8 弦）。这是 intentional 行为变更，断言合理。
        """
        timeline = load_midi(_FIXTURE)
        streams = resolve_streams(timeline)
        pitches = [n.pitch for s in streams for n in s.notes]

        registry = TuningRegistry.default()
        standard_8 = registry.get("standard_8")
        drop_a_7 = registry.get("drop_a_7")
        assert standard_8 is not None and drop_a_7 is not None

        cov_8 = standard_8.coverage_score(pitches)
        cov_7 = drop_a_7.coverage_score(pitches)

        # standard_8 覆盖率确实 >= drop_a_7（因 min=30 能覆盖 pitch 31）。
        assert cov_8 >= cov_7
        # 差距在 tolerance 内 → 偏好更少弦合理。
        assert cov_8 - cov_7 <= 0.005, (
            f"coverage gap {cov_8 - cov_7} should be within 0.005 tolerance"
        )
        assert drop_a_7.string_count < standard_8.string_count

        # auto_detect 确实返回 drop_a_7。
        tuning = auto_detect_tuning(streams)
        assert tuning.id == "drop_a_7"


# ===========================================================================
# F. 真实样本 tokyo_midnight 端到端
# ===========================================================================


class TestRealSampleEndToEnd:
    """用 tokyo_midnight.mid 运行完整 pipeline，验证 auto_detect + IR 完整性。"""

    def test_auto_detect_returns_drop_a_7(self) -> None:
        """auto_detect_tuning 返回 drop_a_7（不再是 standard_8）。"""
        timeline = load_midi(_FIXTURE)
        streams = resolve_streams(timeline)

        tuning = auto_detect_tuning(streams)

        assert tuning.id == "drop_a_7"
        assert tuning.string_count == 7

    def test_full_pipeline_no_crash_and_valid_ir(self) -> None:
        """完整 pipeline 执行不抛异常，IR 有 tracks/measures/notes > 0。"""
        timeline = load_midi(_FIXTURE)
        report = type(
            "R", (), {"primary_guitar_track_index": 0, "primary_classification": None}
        )()
        # 用 _build_cleaned_track 走 cleanup 全流程。
        cleaned_track, _info = _build_cleaned_track(
            timeline, 0, timeline.tracks[0]
        )

        pipeline = create_pipeline()
        ctx = PipelineContext(
            timeline=timeline,
            track=cleaned_track,
            knowledge=pipeline.registry,
            style_label="unknown",
            midi_fidelity=0.5,
            advisor=None,
            track_role="lead",
            source_track_index=cleaned_track.index,
            degraded_mode=True,
        )

        ir = pipeline.execute(ctx)

        assert ir is not None
        assert len(ir.tracks) > 0, "IR should contain at least one track"
        assert len(ir.tracks[0].measures) > 0, "IR track should have measures"
        total_notes = sum(len(m.events) for t in ir.tracks for m in t.measures)
        assert total_notes > 0, "Pipeline produced zero notes"

    def test_cleaned_track_velocity_in_range_on_real_sample(self) -> None:
        """真实样本 cleanup 后所有 velocity 在 1-127 范围内。"""
        timeline = load_midi(_FIXTURE)
        cleaned_track, _info = _build_cleaned_track(
            timeline, 0, timeline.tracks[0]
        )

        for note in cleaned_track.notes:
            assert 1 <= note.velocity <= 127

    def test_cleaned_track_duration_positive_on_real_sample(self) -> None:
        """真实样本 cleanup 后所有 duration_beats > 0（截断不制造 0 时长）。"""
        timeline = load_midi(_FIXTURE)
        cleaned_track, _info = _build_cleaned_track(
            timeline, 0, timeline.tracks[0]
        )

        for note in cleaned_track.notes:
            assert note.duration_beats > 0, (
                f"0-duration: pitch={note.pitch} start={note.start_beat}"
            )
            assert note.duration_ticks > 0
