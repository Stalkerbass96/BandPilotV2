"""S4: Voice assignment stage.

Normalizes ringing overlaps within voice 1. Voice 2 is reserved for
out-of-range (unplayable) notes, which the fingering stage (S5) fills in later.

遵循 "auto-detect + user override" 原则：系统自动把超范围音符分离到
voice 2，用户随后在 Guitar Pro 里按声部筛选决定保留还是删除。和弦 release
不再 promote 到 voice 2 —— 同 onset 不同 duration 的和弦交给 gp5 导出的
tie 机制表达。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace

from fretpilot.engine.context import PipelineContext, SplitNote, VoicedNote

_EPSILON = 1e-8


def _normalize_ringing(notes: list[SplitNote]) -> list[SplitNote]:
    """Clip written durations at the next *distinct* onset within each voice.

    不能按「排序后紧邻的下一个音符」截断：同一个 onset 可能是和弦（多个音符
    同 onset），此时紧邻音符的 onset 相同，``available = 0`` 会直接跳过，导致
    长音符越过下一个不同 onset 也不被截断。改为按 onset 分组，每个 onset 组里
    所有音符的时值都不超过「下一个不同 onset - 当前 onset」。
    """
    normalized = list(notes)
    for voice in (1, 2):
        by_onset: dict[float, list[int]] = defaultdict(list)
        for idx, note in enumerate(normalized):
            if note.voice == voice:
                by_onset[round(note.start_beat, 9)].append(idx)

        onsets = sorted(by_onset)
        for k, onset in enumerate(onsets):
            if k + 1 >= len(onsets):
                continue
            available = onsets[k + 1] - onset
            if available <= _EPSILON:
                continue
            for idx in by_onset[onset]:
                note = normalized[idx]
                if note.duration_beats > available + _EPSILON:
                    normalized[idx] = replace(
                        normalized[idx],
                        duration_beats=available,
                        let_ring=True,
                    )
    return normalized


def _to_voiced(note: SplitNote) -> VoicedNote:
    """Convert a SplitNote to a VoicedNote (carrying all fields)."""
    return VoicedNote(
        source_index=note.source_index,
        pitch=note.pitch,
        velocity=note.velocity,
        start_beat=note.start_beat,
        duration_beats=note.duration_beats,
        measure_number=note.measure_number,
        beat_in_measure=note.beat_in_measure,
        tie_in=note.tie_in,
        tie_out=note.tie_out,
        original_start_beat=note.original_start_beat,
        original_duration_beats=note.original_duration_beats,
        voice=note.voice,
        let_ring=note.let_ring,
        legato_candidate=note.legato_candidate,
    )


class VoiceStage:
    """S4: Assign voices and normalize ringing overlaps.

    All normal notes stay in voice 1. Voice 2 is reserved for out-of-range
    notes and is populated by the fingering stage (S5).
    """

    name = "voice"

    def run(self, ctx: PipelineContext) -> PipelineContext:
        if not ctx.split_notes:
            ctx.record_stage(self.name)
            return ctx

        # 和弦 release 不再 promote 到 voice 2；voice 2 专归超范围音符。
        voiced = _normalize_ringing(ctx.split_notes)
        ctx.voiced_notes = [_to_voiced(n) for n in voiced]

        ctx.record_stage(self.name)
        return ctx


__all__ = ["VoiceStage"]
