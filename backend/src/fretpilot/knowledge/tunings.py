"""Guitar tuning knowledge — loads tuning profiles and provides pitch-range validation.

定弦知识库以 JSON 资产形式存储（不在代码里写先验数据）。本模块只提供
"how" 逻辑：如何加载定弦、如何判断音高是否在合理范围内、如何挑选覆盖率
最高的定弦。所有 "what"（具体定弦、音域范围）都来自
``assets/guitar_tunings.json``。

遵循 "auto-detect + user override" 原则：
- 自动检测：调用 ``best_match`` 选出覆盖率最高的定弦；
- 用户覆盖：直接通过 ``get(tuning_id)`` 取得特定定弦覆盖自动检测结果。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class GuitarTuning:
    """A single guitar tuning profile.

    ``string_pitches`` 从低音弦到高音弦排列（MIDI note number）。
    ``min_pitch`` / ``max_pitch`` 假设 24 品可演奏音域，用于判断音高是否
    落在该定弦的可演奏范围内。
    """

    id: str
    name: str
    display_name: str
    string_count: int
    string_pitches: list[int]  # low to high
    min_pitch: int
    max_pitch: int
    description: str = ""

    def is_pitch_in_range(self, pitch: int) -> bool:
        """Check if a pitch is playable on this tuning (assuming 24 frets)."""
        return self.min_pitch <= pitch <= self.max_pitch

    def out_of_range_pitches(self, pitches: list[int]) -> list[int]:
        """Return pitches that fall outside this tuning's range."""
        return [p for p in pitches if not self.is_pitch_in_range(p)]

    def coverage_score(self, pitches: list[int]) -> float:
        """Return fraction of pitches that fall within this tuning's range.

        返回 0.0-1.0：落在可演奏音域内的音符比例，越高表示该定弦越能
        覆盖给定的音高集合。
        """
        if not pitches:
            return 0.0
        in_range = sum(1 for p in pitches if self.is_pitch_in_range(p))
        return in_range / len(pitches)

    def to_instrument_tuning(self, fret_count: int = 24) -> "GuitarTuning":
        """Convert to guitar.instrument.GuitarTuning for fretboard physics.

        ``guitar.instrument.GuitarTuning`` uses a different internal
        representation: ``open_strings`` is a tuple of ``(string_number,
        midi_pitch)`` pairs where string 1 is the **highest** pitch and
        string *N* is the **lowest** pitch (matching the visual top-to-bottom
        order in guitar tablature).

        ``string_pitches`` in this class goes low → high, so we reverse the
        indexing: ``string_pitches[0]`` (lowest) becomes string
        ``string_count``, and ``string_pitches[-1]`` (highest) becomes
        string 1.
        """
        from fretpilot.guitar.instrument import (
            GuitarTuning as InstrumentTuning,
        )

        open_strings = tuple(
            (self.string_count - i, pitch)
            for i, pitch in enumerate(self.string_pitches)
        )
        return InstrumentTuning(
            name=self.name,
            string_count=self.string_count,
            open_strings=open_strings,
            fret_count=fret_count,
        )

    @property
    def deviation_count(self) -> int:
        """Count of strings differing from the standard tuning of the same string count.

        与同弦数的标准定弦逐弦比较，有几根弦的 pitch 不同即为偏离数。
        偏离越少说明该定弦越接近标准定弦（演奏者更熟悉、更简单）。

        - standard_6 = [40,45,50,55,59,64]，drop_d_6 = [38,45,50,55,59,64]
          只有第 1 根弦不同 → deviation_count = 1
        - full_step_down_6 = [38,43,48,53,57,62]，6 根全变 → deviation_count = 6
        - standard_8 没有同弦数的 drop 版本 → deviation_count = 0
        """
        # 各弦数对应的标准定弦 reference（low → high）。
        standards: dict[int, list[int]] = {
            6: [40, 45, 50, 55, 59, 64],  # Standard E
            7: [35, 40, 45, 50, 55, 59, 64],  # Standard B
            8: [30, 35, 40, 45, 50, 55, 59, 64],  # Standard F#
        }
        ref = standards.get(self.string_count)
        # 无标准可比或弦数对不上时，全部按偏离计。
        if ref is None or len(ref) != len(self.string_pitches):
            return len(self.string_pitches)
        return sum(1 for a, b in zip(self.string_pitches, ref) if a != b)


class TuningRegistry:
    """Loads and queries guitar tuning profiles from JSON.

    注册表是只读的查询接口，所有定弦数据都来自 JSON 资产文件。
    """

    def __init__(self, tunings: list[GuitarTuning]) -> None:
        self._tunings = tunings
        self._by_id = {t.id: t for t in tunings}

    @classmethod
    def from_json(cls, path: Path | str) -> "TuningRegistry":
        """从 JSON 资产文件加载定弦配置。"""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        tunings = [
            GuitarTuning(
                id=t["id"],
                name=t["name"],
                display_name=t["display_name"],
                string_count=t["string_count"],
                string_pitches=t["string_pitches"],
                min_pitch=t["min_pitch"],
                max_pitch=t["max_pitch"],
                description=t.get("description", ""),
            )
            for t in data["tunings"]
        ]
        return cls(tunings)

    @classmethod
    def default(cls) -> "TuningRegistry":
        """Load from the default assets directory."""
        assets_dir = Path(__file__).parent / "assets"
        return cls.from_json(assets_dir / "guitar_tunings.json")

    def all_tunings(self) -> list[GuitarTuning]:
        """返回所有已加载的定弦配置。"""
        return list(self._tunings)

    def get(self, tuning_id: str) -> GuitarTuning | None:
        """按 ID 取单个定弦，找不到返回 None（用于用户覆盖路径）。"""
        return self._by_id.get(tuning_id)

    def best_match(
        self, pitches: list[int], *, coverage_tolerance: float = 0.005
    ) -> GuitarTuning:
        """Return the best tuning for the given pitches.

        自动检测入口：在所有定弦中挑选覆盖率最高者。当多个定弦覆盖率
        相近（差距在 ``coverage_tolerance`` 以内，默认 0.5%）时，按以下
        优先级 tie-break，偏好"更简单"的定弦：

        1. **更少弦数优先**（``string_count`` 小）—— 6 弦优于 7 弦优于 8 弦；
        2. **更少偏离标准定弦优先**（``deviation_count`` 小）—— 标准定弦优于
           Drop / 降调定弦；
        3. **更高覆盖率优先** —— 仍无法分出胜负时回到覆盖率。

        这样当 standard_8（覆盖 99.95%）与 drop_a_7（覆盖 99.54%）覆盖率都
        接近 100% 时，会优先返回更少弦的 drop_a_7，而不是盲目选择列表中
        靠前的 8 弦定弦。
        """
        if not self._tunings:
            raise ValueError("No tunings loaded")
        scored = [(t, t.coverage_score(pitches)) for t in self._tunings]
        max_coverage = max(s for _, s in scored)
        # 在 max_coverage 的 tolerance 内筛选候选（覆盖率接近最高的都算候选）。
        candidates = [(t, s) for t, s in scored if max_coverage - s <= coverage_tolerance]
        # tie-break: 更少弦 → 更少偏离 → 更高覆盖率（用负覆盖率取 min 即更高覆盖）。
        # candidates 元素为 (tuning, score) 元组，min 返回的也是元组，取 [0] 得到定弦。
        best = min(
            candidates,
            key=lambda ts: (ts[0].string_count, ts[0].deviation_count, -ts[1]),
        )
        return best[0]


__all__ = ["GuitarTuning", "TuningRegistry"]
