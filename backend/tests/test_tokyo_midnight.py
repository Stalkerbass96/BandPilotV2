"""Tokyo Midnight Highway (Guitar).mid — 4 项 cleanup 增强集成测试。

这个脏样本暴露了现有 pipeline 的 4 个缺口：195 个近似重复的 tempo 事件
（BPM 差值仅 0.032）、超低/超高音高（pitch 31..89）、完全平坦的 velocity
（全部 61）、以及 171 处同音高重叠。本文件覆盖 tempo 去重、定弦自动检测、
超范围音高处理（flag/remove/transpose）、velocity 重映射（平坦执行 / 有变化
跳过）、同/异音高重叠截断、以及完整 cleanup 流程。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fretpilot.detection.streams import LogicalStream, resolve_streams
from fretpilot.engine.cleanup import (
    auto_detect_tuning,
    cleanup_streams,
    deduplicate_tempos,
    handle_out_of_range_pitches,
    remap_flat_velocity,
    truncate_overlaps,
)
from fretpilot.knowledge.tunings import TuningRegistry
from fretpilot.midi.models import NormalizedNote
from fretpilot.midi.parser import load_midi

_FIXTURE = Path(__file__).parent / "fixtures" / "tokyo_midnight.mid"


def _note(
    pitch: int,
    start_beat: float,
    duration_beats: float,
    *,
    velocity: int = 61,
    channel: int = 0,
    track_index: int = 0,
    track_name: str = "test",
) -> NormalizedNote:
    """构造一个测试用 NormalizedNote（1 拍 = 480 tick）。"""
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
    )


def _tokyo_streams() -> list[LogicalStream]:
    """加载 Tokyo Midnight 样本并解析为 logical streams。"""
    timeline = load_midi(_FIXTURE)
    return resolve_streams(timeline)


def _tokyo_timeline():
    return load_midi(_FIXTURE)


# =============================================================================
# 功能 1：Tempo 去重
# =============================================================================


class TestTempoDedup:
    """195 个近似重复 tempo 事件去重后应只剩 1 个。"""

    def test_tempo_dedup(self) -> None:
        timeline = _tokyo_timeline()
        assert len(timeline.tempo_events) == 195

        kept, actions = deduplicate_tempos(timeline)

        # 全部 BPM 落在 137.9945-138.0265（差值 0.032 < 0.1），去重后只剩首个。
        assert len(kept) == 1
        assert len(actions) == 194
        assert all(a.kind == "dedup_tempo" for a in actions)
        # 保留的是第一个事件。
        assert kept[0].bpm == timeline.tempo_events[0].bpm
        # 每个被丢弃事件都有可追溯的详情。
        assert all(a.notes for a in actions)
        assert all("bpm" in a.notes[0] for a in actions)


# =============================================================================
# 功能 2：定弦自动检测 + 超范围音高处理
# =============================================================================


class TestTuningAutoDetect:
    """自动检测应返回覆盖率最高的定弦。"""

    def test_tuning_auto_detect(self) -> None:
        streams = _tokyo_streams()
        pitches = [n.pitch for s in streams for n in s.notes]

        tuning = auto_detect_tuning(streams)

        # 新偏好逻辑：覆盖率相近（standard_8 99.95% vs drop_a_7 99.54%，
        # 差 0.42% < 0.5% tolerance）时偏好更少弦，故返回 drop_a_7（7 弦）。
        assert tuning.coverage_score(pitches) >= 0.99
        # 接受 drop_a_7 或覆盖率最高的 standard_8。
        assert tuning.id in {"standard_8", "drop_a_7"}
        # 两种候选定弦都能覆盖中音区 pitch 60。
        assert tuning.is_pitch_in_range(60)


class TestOutOfRangeFlag:
    """flag 模式：不删除音符，但记录超范围音符数。"""

    def test_out_of_range_flag(self) -> None:
        streams = _tokyo_streams()
        original_count = sum(s.note_count for s in streams)
        standard_6 = TuningRegistry.default().get("standard_6")
        assert standard_6 is not None

        cleaned, actions = handle_out_of_range_pitches(streams, standard_6, mode="flag")

        # flag 不删除任何音符。
        assert sum(s.note_count for s in cleaned) == original_count
        assert actions
        assert all(a.kind == "out_of_range_pitch" for a in actions)
        # standard_6 (40-88)：pitch <40 共 468 个 + pitch 89 共 1 个 = 469。
        flagged = sum(len(a.notes) for a in actions)
        assert flagged == 469
        # 被标记的音高全部确实落在 40-88 之外。
        for action in actions:
            for entry in action.notes:
                assert not (40 <= entry["pitch"] <= 88)


class TestOutOfRangeRemove:
    """remove 模式：删除超范围音符。"""

    def test_out_of_range_remove(self) -> None:
        streams = _tokyo_streams()
        original_count = sum(s.note_count for s in streams)
        standard_6 = TuningRegistry.default().get("standard_6")
        assert standard_6 is not None

        cleaned, actions = handle_out_of_range_pitches(streams, standard_6, mode="remove")

        removed = sum(a.removed_note_count for a in actions)
        assert removed == 469
        assert sum(s.note_count for s in cleaned) == original_count - 469
        # 剩余音符全部落在 standard_6 音域内。
        for s in cleaned:
            for n in s.notes:
                assert standard_6.is_pitch_in_range(n.pitch)


class TestOutOfRangeTranspose:
    """transpose 模式：尝试升降八度挪入音域。"""

    def test_out_of_range_transpose(self) -> None:
        streams = _tokyo_streams()
        original_count = sum(s.note_count for s in streams)
        standard_6 = TuningRegistry.default().get("standard_6")
        assert standard_6 is not None

        cleaned, actions = handle_out_of_range_pitches(
            streams, standard_6, mode="transpose"
        )

        # transpose 不删除音符（只改写 pitch）。
        assert sum(s.note_count for s in cleaned) == original_count
        assert actions
        # 所有原超范围音高经八度平移后都已进入音域（38→50、37→49、36→48、
        # 34→46、33→45、31→43、89→77）。
        for s in cleaned:
            for n in s.notes:
                assert standard_6.is_pitch_in_range(n.pitch), (
                    f"pitch {n.pitch} 仍超出 standard_6 音域"
                )
        # 记录了 old_pitch → new_pitch 的迁移详情。
        transposed_entries = [
            e for a in actions for e in a.notes if "new_pitch" in e
        ]
        assert transposed_entries
        # pitch 89 应被降八度到 77。
        assert any(
            e["old_pitch"] == 89 and e["new_pitch"] == 77 for e in transposed_entries
        )
        # 低音 38 应被升八度到 50。
        assert any(
            e["old_pitch"] == 38 and e["new_pitch"] == 50 for e in transposed_entries
        )


# =============================================================================
# 功能 3：Velocity 重映射
# =============================================================================


class TestVelocityRemap:
    """全部 velocity=61（平坦）时执行重映射；velocity 有变化时跳过。"""

    def test_velocity_remap_flat(self) -> None:
        streams = _tokyo_streams()
        velocities_before = [n.velocity for s in streams for n in s.notes]
        assert set(velocities_before) == {61}  # Tokyo 全部为 61

        cleaned, actions = remap_flat_velocity(streams)

        # 执行了重映射。
        assert actions
        assert all(a.kind == "remap_velocity" for a in actions)
        # velocity 不再单一，应有强拍(+20=81)/弱拍(+10=71)/off-beat(-10=51) 等。
        velocities_after = [n.velocity for s in cleaned for n in s.notes]
        assert len(set(velocities_after)) > 1
        # off-beat 衰减到 51，强拍提升到 81。
        assert 51 in velocities_after
        assert 81 in velocities_after
        # 记录了 old/new velocity 详情。
        assert all(a.notes for a in actions)
        assert all(
            "old_velocity" in e and "new_velocity" in e
            for a in actions
            for e in a.notes
        )

    def test_velocity_remap_skipped_when_varied(self) -> None:
        # 构造 velocity 已有变化的流（方差 400 >> 5）。
        notes = [
            _note(60, 0.0, 1.0, velocity=50),
            _note(62, 1.0, 1.0, velocity=90),
        ]
        stream = LogicalStream(
            stream_id="test-001",
            program=0,
            channel=0,
            instrument_name=None,
            notes=notes,
        )
        velocities_before = [n.velocity for n in stream.notes]

        cleaned, actions = remap_flat_velocity([stream])

        # velocity 已有变化，不执行重映射。
        assert actions == []
        assert [n.velocity for n in cleaned[0].notes] == velocities_before


# =============================================================================
# 功能 4：重叠截断
# =============================================================================


class TestOverlapTruncation:
    """同音高重叠被截断；不同音高重叠（和弦）保留。"""

    def test_overlap_truncation_same_pitch(self) -> None:
        # 音符 A (pitch 60) end_tick=480 越过音符 B (pitch 60) start_tick=240。
        a = _note(60, 0.0, 1.0)  # start_tick=0, duration_ticks=480, end=480
        b = _note(60, 0.5, 0.5)  # start_tick=240, duration_ticks=240
        stream = LogicalStream(
            stream_id="test-002",
            program=0,
            channel=0,
            instrument_name=None,
            notes=[a, b],
        )

        cleaned, actions = truncate_overlaps([stream])

        assert actions
        assert actions[0].kind == "truncate_overlap"
        # A 被截断到 B 的起始（duration_ticks 480→240）。
        assert cleaned[0].notes[0].duration_ticks == 240
        assert cleaned[0].notes[0].duration_beats == pytest.approx(0.5)
        # 截断后 A 的 end_tick 恰好等于 B 的 start_tick。
        assert cleaned[0].notes[0].end_tick == cleaned[0].notes[1].start_tick
        # 记录了 old/new duration 详情。
        detail = actions[0].notes[0]
        assert detail["old_duration_ticks"] == 480
        assert detail["new_duration_ticks"] == 240
        # B 不受影响。
        assert cleaned[0].notes[1].duration_ticks == 240

    def test_overlap_preserved_different_pitch(self) -> None:
        # 和弦：A (pitch 60) 与 B (pitch 64) 重叠但音高不同 —— 不截断。
        a = _note(60, 0.0, 1.0)  # end_tick=480
        b = _note(64, 0.5, 0.5)  # start_tick=240
        stream = LogicalStream(
            stream_id="test-003",
            program=0,
            channel=0,
            instrument_name=None,
            notes=[a, b],
        )
        a_dur_before = a.duration_ticks
        b_dur_before = b.duration_ticks

        cleaned, actions = truncate_overlaps([stream])

        # 不同音高重叠属和弦，留给 voice separation，不截断。
        assert actions == []
        assert cleaned[0].notes[0].duration_ticks == a_dur_before
        assert cleaned[0].notes[1].duration_ticks == b_dur_before


# =============================================================================
# 完整 cleanup 流程
# =============================================================================


class TestFullCleanupPipeline:
    """完整 cleanup 流程在 Tokyo Midnight 上的综合测试。"""

    def test_full_cleanup_pipeline(self) -> None:
        timeline = _tokyo_timeline()
        streams = resolve_streams(timeline)
        original_count = sum(s.note_count for s in streams)
        assert original_count == 2151

        # auto-detect + user override 原则：自动检测最佳定弦。
        # 新偏好逻辑：standard_8 覆盖 99.95%、drop_a_7 覆盖 99.54%，差距
        # 0.42% < 0.5% tolerance，故偏好更少弦 → 返回 drop_a_7（7 弦）。
        tuning = auto_detect_tuning(streams)
        assert tuning.id == "drop_a_7"

        result = cleanup_streams(
            streams,
            timeline=timeline,
            tuning=tuning,
            out_of_range_mode="flag",
        )

        # 1. Tempo 去重：195 → 1，丢弃 194 个。
        assert result.tempo_dedup_count == 194

        # 2. 超范围音高（drop_a_7 音域 33-88）：pitch 31（9 个）+ pitch 89（1 个）= 10 个。
        assert result.out_of_range_count == 10

        # 3. Velocity 重映射：全部 61（平坦）→ 执行。
        assert result.velocity_remapped is True
        remapped_velocities = [n.velocity for s in result.streams for n in s.notes]
        assert len(set(remapped_velocities)) > 1

        # 4. 重叠截断：171 处同音高重叠。
        assert result.overlaps_truncated == 171

        # flag 模式不删除音符，重叠截断只改 duration 不删音符 → 音符数不变。
        assert result.note_count == original_count

        # CleanupResult 记录了使用的定弦。
        assert result.tuning is not None
        assert result.tuning.id == "drop_a_7"

        # 所有 4 项新功能的 action kind 都出现，且可追溯。
        kinds = {a.kind for a in result.actions}
        assert "dedup_tempo" in kinds
        assert "out_of_range_pitch" in kinds
        assert "remap_velocity" in kinds
        assert "truncate_overlap" in kinds
        # 每个 action 都带有描述与（如适用）notes 详情。
        assert all(a.description for a in result.actions)
