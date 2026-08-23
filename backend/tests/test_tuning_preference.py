"""定弦偏好逻辑测试 —— 覆盖率相近时偏好更少弦 / 更少偏离标准定弦。

当多个定弦的覆盖率都在 ``coverage_tolerance``（默认 0.5%）以内时，
``TuningRegistry.best_match`` 不再盲目返回列表中靠前者，而是按
"更少弦数 → 更少偏离标准定弦 → 更高覆盖率" 的优先级 tie-break。
本文件覆盖 5 个场景：更少弦优先、标准优先于 Drop、无并列时取最高覆盖率、
deviation_count 计算、以及 Tokyo Midnight 样本的端到端偏好验证。
"""

from __future__ import annotations

from pathlib import Path

from fretpilot.detection.streams import resolve_streams
from fretpilot.engine.cleanup import auto_detect_tuning
from fretpilot.knowledge.tunings import TuningRegistry
from fretpilot.midi.parser import load_midi

_FIXTURE = Path(__file__).parent / "fixtures" / "tokyo_midnight.mid"


def _default_registry() -> TuningRegistry:
    """加载默认定弦注册表（12 个定弦）。"""
    return TuningRegistry.default()


# =============================================================================
# 场景 1：更少弦数优先
# =============================================================================


class TestPrefersFewerStrings:
    """覆盖率相近时，应返回弦数更少的定弦。"""

    def test_best_match_prefers_fewer_strings(self) -> None:
        # pitch 33 仅 drop_a_7（min=33）与 standard_8（min=30）能覆盖；
        # standard_7（min=35）及所有 6 弦都漏掉 pitch 33。
        # 100 个音符中 1 个 pitch 33 + 99 个 pitch 60：
        #   drop_a_7  覆盖率 1.0（7 弦）
        #   standard_8 覆盖率 1.0（8 弦）
        #   standard_7 覆盖率 99/100=0.99，与最高差 0.01 > 0.005 → 出局
        # 候选只剩 drop_a_7 与 standard_8，更少弦 → drop_a_7。
        pitches = [33] + [60] * 99
        registry = _default_registry()

        tuning = registry.best_match(pitches)

        assert tuning.id == "drop_a_7"
        assert tuning.string_count == 7


# =============================================================================
# 场景 2：更少偏离标准定弦优先（同弦数时标准优于 Drop）
# =============================================================================


class TestPrefersStandardOverDrop:
    """同弦数、同覆盖率时，标准定弦（deviation=0）优于 Drop 定弦。"""

    def test_best_match_prefers_standard_over_drop(self) -> None:
        # 构造只含 standard_6 与 drop_d_6 的注册表，隔离 deviation tie-break。
        # 两者音域都覆盖 40-88，pitch 集合全部命中 → 覆盖率均为 1.0。
        default = _default_registry()
        standard_6 = default.get("standard_6")
        drop_d_6 = default.get("drop_d_6")
        assert standard_6 is not None and drop_d_6 is not None
        registry = TuningRegistry([standard_6, drop_d_6])
        pitches = [40, 50, 60, 70, 80, 88]

        tuning = registry.best_match(pitches)

        # 同为 6 弦、覆盖率同为 1.0 → deviation 决胜负：standard_6=0 < drop_d_6=1。
        assert tuning.id == "standard_6"
        assert tuning.deviation_count == 0
        # 确认 drop_d_6 覆盖率与 standard_6 相同（确属 deviation tie-break）。
        assert drop_d_6.coverage_score(pitches) == standard_6.coverage_score(pitches)


# =============================================================================
# 场景 3：无并列时直接返回最高覆盖率
# =============================================================================


class TestNoTieReturnsHighest:
    """覆盖率差距 > tolerance 时，直接返回唯一最高覆盖率的定弦。"""

    def test_best_match_no_tie_returns_highest(self) -> None:
        # pitch 30 仅 standard_8（min=30）能覆盖；drop_a_7（min=33）漏掉。
        # 101 个音符中 1 个 pitch 30 + 100 个 pitch 60：
        #   standard_8 覆盖率 1.0
        #   drop_a_7  覆盖率 100/101≈0.9901，差 0.0099 > 0.005 → 出局
        # 候选只剩 standard_8，无并列。
        pitches = [30] + [60] * 100
        registry = _default_registry()

        tuning = registry.best_match(pitches)

        assert tuning.id == "standard_8"
        assert tuning.coverage_score(pitches) == 1.0


# =============================================================================
# 场景 4：deviation_count 计算
# =============================================================================


class TestDeviationCount:
    """验证 deviation_count：与同弦数标准定弦相比的偏离弦数。"""

    def test_deviation_count(self) -> None:
        registry = _default_registry()

        standard_6 = registry.get("standard_6")
        drop_d_6 = registry.get("drop_d_6")
        full_step_down_6 = registry.get("full_step_down_6")
        standard_7 = registry.get("standard_7")
        drop_a_7 = registry.get("drop_a_7")
        standard_8 = registry.get("standard_8")
        assert all(
            t is not None
            for t in (
                standard_6,
                drop_d_6,
                full_step_down_6,
                standard_7,
                drop_a_7,
                standard_8,
            )
        )

        # standard_6 = [40,45,50,55,59,64] 与自身比 → 0 偏离。
        assert standard_6.deviation_count == 0
        # drop_d_6 = [38,45,50,55,59,64]，仅第 1 弦不同 → 1。
        assert drop_d_6.deviation_count == 1
        # full_step_down_6 = [38,43,48,53,57,62]，6 弦全变 → 6。
        assert full_step_down_6.deviation_count == 6
        # standard_7 自身 → 0。
        assert standard_7.deviation_count == 0
        # drop_a_7 = [33,40,45,50,55,59,64]，仅第 1 弦不同 → 1。
        assert drop_a_7.deviation_count == 1
        # standard_8 无同弦数 Drop 版本 → 0。
        assert standard_8.deviation_count == 0


# =============================================================================
# 场景 5：Tokyo Midnight 端到端偏好验证
# =============================================================================


class TestTokyoMidnightTuningPreference:
    """Tokyo Midnight 样本：auto_detect_tuning 应偏好更少弦的定弦。"""

    def test_tokyo_midnight_tuning_preference(self) -> None:
        timeline = load_midi(_FIXTURE)
        streams = resolve_streams(timeline)
        pitches = [n.pitch for s in streams for n in s.notes]

        registry = _default_registry()
        standard_8 = registry.get("standard_8")
        assert standard_8 is not None

        tuning = auto_detect_tuning(streams)

        # standard_8 覆盖率（99.95%）实际上略高于 drop_a_7（99.54%），
        # 但差距 0.42% < 0.5% tolerance，故偏好更少弦 → 返回 drop_a_7。
        assert standard_8.coverage_score(pitches) >= tuning.coverage_score(pitches)
        assert tuning.id == "drop_a_7"
        assert tuning.string_count == 7
        # 不再盲目选 standard_8（8 弦）。
        assert tuning.string_count < standard_8.string_count
