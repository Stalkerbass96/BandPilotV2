"""Stream cleanup: deduplicate duplicate streams, remove micro-notes, report noise.

Runs after stream resolution and classification, before the repair pipeline.
Every removal is traceable via :class:`CleanupAction` (the "break the black
box" contract). Overlapping onsets and velocity spikes are *reported* but not
silently dropped, because in a single-track context they may be chords or
intentional accents.

本模块在原有 cleanup 能力之上扩展了 4 项增强（针对脏 MIDI 样本 Tokyo
Midnight Highway 暴露的缺口）：

1. **Tempo 去重** —— 合并 BPM 差值 < 0.1 的连续 tempo 事件（:func:`deduplicate_tempos`）。
2. **超范围音高处理** —— 基于吉他定弦知识库，对超出可演奏音域的音高进行
   flag / remove / transpose（:func:`handle_out_of_range_pitches`）。
3. **Velocity 重映射** —— 当 velocity 几乎完全平坦时，按节拍位置重新分配动态
   （:func:`remap_flat_velocity`）。
4. **重叠截断** —— 截断同通道同音高的重叠音符（和弦交给 voice separation）
   （:func:`truncate_overlaps`）。
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from fretpilot.detection.streams import LogicalStream
from fretpilot.knowledge.tunings import GuitarTuning, TuningRegistry
from fretpilot.midi.models import NormalizedNote, NormalizedTimeline, TempoEvent

# Notes shorter than this many beats are considered inaudible micro-noise.
MICRO_NOTE_DURATION_BEATS = 0.02
# Duplicate streams must share at least this fraction of their pitch multisets.
_DUPLICATE_MULTISET_SIMILARITY = 0.9
# Maximum note-count and pitch-range drift between two duplicate streams.
_DUPLICATE_MAX_COUNT_DELTA = 2
_DUPLICATE_MAX_RANGE_DELTA = 2

# --- Tempo 去重参数 ---------------------------------------------------------
# 连续两个 tempo 的 BPM 差值小于该阈值即视为近似重复，丢弃后者。
TEMPO_DEDUP_BPM_THRESHOLD = 0.1

# --- Velocity 重映射参数 -----------------------------------------------------
# 所有音符 velocity 的总体方差低于该阈值时，判定为"平坦 velocity"，执行重映射。
VELOCITY_FLAT_VARIANCE = 5.0
# 强拍（小节第 1 拍）velocity 增量。
_VELOCITY_STRONG_DELTA = 20
# 弱拍（4/4 中第 3 拍 / 小节中点）velocity 增量。
_VELOCITY_WEAK_DELTA = 10
# 非拍点 velocity 衰减。
_VELOCITY_OFFBEAT_DELTA = 10
# velocity 的合法上下界。
_VELOCITY_MIN = 1
_VELOCITY_MAX = 127

# --- 超范围音高参数 ---------------------------------------------------------
# 一个八度等于 12 个半音，transpose 模式按八度平移。
_OCTAVE = 12

# --- 节拍位置判断浮点容差 ---------------------------------------------------
_BEAT_EPSILON = 1e-6


@dataclass(slots=True)
class VelocityAnalysis:
    """Velocity statistics for a collection of notes."""

    total_notes: int
    max_velocity_notes: int
    max_velocity_ratio: float
    mean_velocity: float


@dataclass(slots=True)
class OverlapAnalysis:
    """Onset-overlap statistics for a collection of notes."""

    onset_points: int
    overlapped_onset_points: int
    overlap_ratio: float
    max_simultaneous: int


@dataclass(slots=True)
class CleanupAction:
    """A single traceable cleanup operation.

    ``notes`` 字段承载每次操作的细节快照（被丢弃/截断/重映射的音符信息），
    让每一个变更都可追溯，绝不静默删除。
    """

    kind: str  # merge_stream / remove_micro_note / dedup_tempo /
    # out_of_range_pitch / remap_velocity / truncate_overlap
    description: str
    removed_note_count: int = 0
    notes: list[dict] = field(default_factory=list)
    merged_stream_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CleanupResult:
    """Result of stream cleanup.

    扩展字段记录 4 项增强的执行情况：使用了哪个定弦、超范围音符数、tempo
    去重丢弃数、是否执行了 velocity 重映射、重叠截断次数。
    """

    streams: list[LogicalStream]
    actions: list[CleanupAction]
    velocity: VelocityAnalysis | None = None
    overlap: OverlapAnalysis | None = None
    # NEW —— 4 项增强的可追溯状态
    tuning: GuitarTuning | None = None
    out_of_range_count: int = 0
    tempo_dedup_count: int = 0
    velocity_remapped: bool = False
    overlaps_truncated: int = 0

    @property
    def note_count(self) -> int:
        """Total notes remaining after cleanup."""
        return sum(s.note_count for s in self.streams)

    @property
    def removed_note_count(self) -> int:
        """Total notes removed across all cleanup actions."""
        return sum(a.removed_note_count for a in self.actions)


def _note_ref(note: NormalizedNote) -> dict:
    """Return an identifying snapshot of a note for traceability."""
    return {
        "track_index": note.track_index,
        "channel": note.channel,
        "pitch": note.pitch,
        "start_beat": round(note.start_beat, 6),
        "duration_beats": round(note.duration_beats, 6),
    }


def _pitch_range(notes: list[NormalizedNote]) -> tuple[int, int]:
    """Return (min_pitch, max_pitch) for a note list, or (0, 0) when empty."""
    if not notes:
        return 0, 0
    pitches = [n.pitch for n in notes]
    return min(pitches), max(pitches)


def _pitch_multiset_similarity(
    a: list[NormalizedNote], b: list[NormalizedNote]
) -> float:
    """Jaccard similarity between two notes' pitch multisets."""
    counter_a = Counter(n.pitch for n in a)
    counter_b = Counter(n.pitch for n in b)
    intersection = sum((counter_a & counter_b).values())
    union = sum((counter_a | counter_b).values())
    return intersection / union if union else 0.0


def _are_duplicate_streams(a: LogicalStream, b: LogicalStream) -> bool:
    """Return True if two streams are near-duplicates of the same material.

    Duplicates share a pitch range, a close note count, and a highly similar
    pitch multiset — e.g. Suno's ch4/5/6/7 (same 35-67 range, ~30 notes each,
    same melody). Note counts and ranges are compared with a small tolerance,
    which keeps genuinely different parts (ch1's 1094 notes) apart.
    """
    if a.stream_id == b.stream_id:
        return True
    if abs(a.note_count - b.note_count) > _DUPLICATE_MAX_COUNT_DELTA:
        return False
    a_lo, a_hi = _pitch_range(a.notes)
    b_lo, b_hi = _pitch_range(b.notes)
    if abs(a_lo - b_lo) > _DUPLICATE_MAX_RANGE_DELTA:
        return False
    if abs(a_hi - b_hi) > _DUPLICATE_MAX_RANGE_DELTA:
        return False
    return (
        _pitch_multiset_similarity(a.notes, b.notes)
        >= _DUPLICATE_MULTISET_SIMILARITY
    )


def _find_duplicate_groups(
    streams: list[LogicalStream],
) -> list[list[LogicalStream]]:
    """Cluster streams into duplicate groups (size > 1) via union-find."""
    parent = list(range(len(streams)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        root_i, root_j = find(i), find(j)
        if root_i != root_j:
            parent[root_j] = root_i

    for i in range(len(streams)):
        for j in range(i + 1, len(streams)):
            if _are_duplicate_streams(streams[i], streams[j]):
                union(i, j)

    groups: dict[int, list[LogicalStream]] = {}
    for i, stream in enumerate(streams):
        groups.setdefault(find(i), []).append(stream)
    return [group for group in groups.values() if len(group) > 1]


def _merge_duplicate_groups(
    streams: list[LogicalStream],
    groups: list[list[LogicalStream]],
) -> tuple[list[LogicalStream], list[CleanupAction]]:
    """Keep one canonical stream per duplicate group; drop the redundant ones."""
    removed_ids = {
        stream.stream_id for group in groups for stream in group[1:]
    }
    kept = [s for s in streams if s.stream_id not in removed_ids]

    actions: list[CleanupAction] = []
    for group in groups:
        canonical = max(group, key=lambda s: (s.note_count, s.stream_id))
        removed = [s for s in group if s.stream_id != canonical.stream_id]
        actions.append(
            CleanupAction(
                kind="merge_stream",
                description=(
                    f"Merged {len(group)} duplicate streams into {canonical.stream_id} "
                    f"(kept one copy, dropped {len(removed)} redundant layers)."
                ),
                removed_note_count=sum(s.note_count for s in removed),
                merged_stream_ids=[s.stream_id for s in removed],
            )
        )
    return kept, actions


def _remove_micro_notes(
    streams: list[LogicalStream], threshold_beats: float
) -> tuple[list[LogicalStream], list[CleanupAction]]:
    """Drop notes shorter than ``threshold_beats``, recording each removal."""
    actions: list[CleanupAction] = []
    for stream in streams:
        kept_notes: list[NormalizedNote] = []
        removed_notes: list[NormalizedNote] = []
        for note in stream.notes:
            if note.duration_beats < threshold_beats:
                removed_notes.append(note)
            else:
                kept_notes.append(note)
        if removed_notes:
            actions.append(
                CleanupAction(
                    kind="remove_micro_note",
                    description=(
                        f"Removed {len(removed_notes)} micro-notes (< {threshold_beats} beats) "
                        f"from {stream.stream_id}."
                    ),
                    removed_note_count=len(removed_notes),
                    notes=[_note_ref(n) for n in removed_notes],
                )
            )
        stream.notes = kept_notes
    return streams, actions


def analyze_velocity(notes: list[NormalizedNote]) -> VelocityAnalysis:
    """Compute velocity statistics, exposing the velocity-127 spike ratio."""
    if not notes:
        return VelocityAnalysis(0, 0, 0.0, 0.0)
    velocities = [n.velocity for n in notes]
    max_velocity_notes = sum(1 for v in velocities if v >= 127)
    return VelocityAnalysis(
        total_notes=len(notes),
        max_velocity_notes=max_velocity_notes,
        max_velocity_ratio=round(max_velocity_notes / len(notes), 4),
        mean_velocity=round(statistics.fmean(velocities), 3),
    )


def analyze_overlap(notes: list[NormalizedNote]) -> OverlapAnalysis:
    """Compute onset-overlap statistics, exposing simultaneous-note clusters."""
    if not notes:
        return OverlapAnalysis(0, 0, 0.0, 0)
    onset_counts: dict[float, int] = {}
    for note in notes:
        key = round(note.start_beat, 6)
        onset_counts[key] = onset_counts.get(key, 0) + 1
    onset_points = len(onset_counts)
    overlapped = sum(1 for count in onset_counts.values() if count > 1)
    return OverlapAnalysis(
        onset_points=onset_points,
        overlapped_onset_points=overlapped,
        overlap_ratio=round(overlapped / onset_points, 4),
        max_simultaneous=max(onset_counts.values()),
    )


# =============================================================================
# 功能 1：Tempo 去重
# =============================================================================


def deduplicate_tempos(
    timeline: NormalizedTimeline,
) -> tuple[list[TempoEvent], list[CleanupAction]]:
    """合并 BPM 差值 < 0.1 的连续 tempo 事件，保留第一个，丢弃后续近似重复。

    Tokyo Midnight 有 195 个 tempo 事件，BPM 范围 137.9945-138.0265（差值
    仅 0.032），全部近似重复，去重后应只剩 1 个事件。比较基准是"最近保留
    的事件"：一旦某个 tempo 与当前保留的参考值差值 < 阈值即丢弃，从而把
    漂移序列合并到首个保留值上。

    返回去重后的 tempo 列表 + 每个被丢弃事件的 :class:`CleanupAction`
    （kind="dedup_tempo"）。
    """
    tempos = list(timeline.tempo_events)
    if not tempos:
        return [], []
    kept: list[TempoEvent] = [tempos[0]]
    actions: list[CleanupAction] = []
    for event in tempos[1:]:
        reference = kept[-1]
        if abs(event.bpm - reference.bpm) < TEMPO_DEDUP_BPM_THRESHOLD:
            # 近似重复：丢弃当前事件，保留参考值。
            actions.append(
                CleanupAction(
                    kind="dedup_tempo",
                    description=(
                        f"Dropped near-duplicate tempo (bpm={event.bpm}) "
                        f"keeping retained bpm={reference.bpm} "
                        f"(delta={abs(event.bpm - reference.bpm):.6f})."
                    ),
                    notes=[
                        {
                            "tick": event.tick,
                            "beat": round(event.beat, 6),
                            "bpm": event.bpm,
                            "kept_bpm": reference.bpm,
                            "delta": round(abs(event.bpm - reference.bpm), 6),
                        }
                    ],
                )
            )
        else:
            kept.append(event)
    return kept, actions


# =============================================================================
# 功能 2：吉他定弦知识库 + 超范围音高处理
# =============================================================================


def auto_detect_tuning(streams: list[LogicalStream]) -> GuitarTuning:
    """自动检测最佳定弦：收集所有音符 pitch，返回覆盖率最高的定弦。

    遵循 "auto-detect + user override" 原则中的自动检测部分。用户覆盖路径
    为直接通过 ``TuningRegistry.get(tuning_id)`` 取得特定定弦后传入
    :func:`cleanup_streams` 的 ``tuning`` 参数。
    """
    pitches = [n.pitch for s in streams for n in s.notes]
    registry = TuningRegistry.default()
    return registry.best_match(pitches)


def _transpose_into_range(pitch: int, tuning: GuitarTuning) -> int | None:
    """尝试把超范围音高升降一个八度挪入定弦音域，成功返回新 pitch，否则 None。"""
    if pitch < tuning.min_pitch:
        candidate = pitch + _OCTAVE
        if tuning.is_pitch_in_range(candidate):
            return candidate
        return None
    if pitch > tuning.max_pitch:
        candidate = pitch - _OCTAVE
        if tuning.is_pitch_in_range(candidate):
            return candidate
        return None
    return None


def handle_out_of_range_pitches(
    streams: list[LogicalStream],
    tuning: GuitarTuning,
    mode: str = "flag",
) -> tuple[list[LogicalStream], list[CleanupAction]]:
    """处理超出定弦可演奏音域的音高。

    - ``mode="flag"``：不删除，只记录 :class:`CleanupAction`
      （kind="out_of_range_pitch"）列出所有超范围音符。
    - ``mode="remove"``：删除超范围音符，并记录每次删除。
    - ``mode="transpose"``：尝试升/降八度挪入音域，成功则改写 pitch；若升降
      一个八度后仍无法进入音域则保留原音符（仅记录未处理项）。

    每个被处理的音符详情都写入 CleanupAction 的 ``notes`` 字段。
    """
    if mode not in {"flag", "remove", "transpose"}:
        raise ValueError(
            f"Unknown out_of_range_mode {mode!r}; expected flag/remove/transpose."
        )
    actions: list[CleanupAction] = []
    for stream in streams:
        if mode == "flag":
            actions.extend(_flag_out_of_range(stream, tuning))
        elif mode == "remove":
            actions.extend(_remove_out_of_range(stream, tuning))
        else:  # transpose
            actions.extend(_transpose_out_of_range(stream, tuning))
    return streams, actions


def _flag_out_of_range(
    stream: LogicalStream, tuning: GuitarTuning
) -> list[CleanupAction]:
    """flag 模式：标记超范围音符但不删除。"""
    flagged = [
        {
            "track_index": n.track_index,
            "channel": n.channel,
            "pitch": n.pitch,
            "start_beat": round(n.start_beat, 6),
        }
        for n in stream.notes
        if not tuning.is_pitch_in_range(n.pitch)
    ]
    if not flagged:
        return []
    return [
        CleanupAction(
            kind="out_of_range_pitch",
            description=(
                f"Flagged {len(flagged)} out-of-range pitch(es) in {stream.stream_id} "
                f"(tuning={tuning.display_name}, range={tuning.min_pitch}-{tuning.max_pitch})."
            ),
            notes=flagged,
        )
    ]


def _remove_out_of_range(
    stream: LogicalStream, tuning: GuitarTuning
) -> list[CleanupAction]:
    """remove 模式：删除超范围音符。"""
    kept_notes: list[NormalizedNote] = []
    removed: list[NormalizedNote] = []
    for note in stream.notes:
        if tuning.is_pitch_in_range(note.pitch):
            kept_notes.append(note)
        else:
            removed.append(note)
    if not removed:
        return []
    stream.notes = kept_notes
    return [
        CleanupAction(
            kind="out_of_range_pitch",
            description=(
                f"Removed {len(removed)} out-of-range pitch(es) from {stream.stream_id} "
                f"(tuning={tuning.display_name}, range={tuning.min_pitch}-{tuning.max_pitch})."
            ),
            removed_note_count=len(removed),
            notes=[_note_ref(n) for n in removed],
        )
    ]


def _transpose_out_of_range(
    stream: LogicalStream, tuning: GuitarTuning
) -> list[CleanupAction]:
    """transpose 模式：尝试升降八度挪入音域。"""
    transposed: list[dict] = []
    unchanged: list[dict] = []
    for note in stream.notes:
        if tuning.is_pitch_in_range(note.pitch):
            continue
        new_pitch = _transpose_into_range(note.pitch, tuning)
        if new_pitch is not None:
            transposed.append(
                {
                    "track_index": note.track_index,
                    "channel": note.channel,
                    "old_pitch": note.pitch,
                    "new_pitch": new_pitch,
                    "start_beat": round(note.start_beat, 6),
                }
            )
            note.pitch = new_pitch
        else:
            unchanged.append(
                {
                    "track_index": note.track_index,
                    "channel": note.channel,
                    "pitch": note.pitch,
                    "start_beat": round(note.start_beat, 6),
                    "reason": "octave shift out of range",
                }
            )
    if not transposed and not unchanged:
        return []
    detail = (
        f"Transposed {len(transposed)} out-of-range pitch(es) by an octave in "
        f"{stream.stream_id} (tuning={tuning.display_name}); "
        f"{len(unchanged)} could not be moved."
    )
    return [
        CleanupAction(
            kind="out_of_range_pitch",
            description=detail,
            notes=transposed + unchanged,
        )
    ]


# =============================================================================
# 功能 3：Velocity 重映射
# =============================================================================


def _beats_per_measure_from_timeline(timeline: NormalizedTimeline) -> int:
    """从时间签名推导每小节的拍数（以四分音符为 1 拍）。

    4/4 → 4 拍；3/4 → 3 拍；6/8 → 3 拍（6 个八分 = 3 个四分）。
    """
    numerator, denominator = timeline.initial_time_signature
    if denominator <= 0:
        return 4
    return max(1, numerator * 4 // denominator)


def _velocity_for_beat(
    start_beat: float, base: int, beats_per_measure: int
) -> int:
    """根据音符在小节中的拍位返回重映射后的 velocity。

    - 强拍（小节第 1 拍，beat 0）：base + 20（上限 127）
    - 弱拍（小节中点拍，4/4 的第 3 拍即 beat 2）：base + 10（上限 127）
    - 偶数拍（其余整数拍，4/4 的第 2/4 拍即 beat 1/3）：base
    - 非拍点（off-beat，非整数拍）：base - 10（下限 1）
    """
    nearest = round(start_beat)
    on_beat = abs(start_beat - nearest) < _BEAT_EPSILON
    if not on_beat:
        return max(_VELOCITY_MIN, base - _VELOCITY_OFFBEAT_DELTA)
    beat_idx = int(nearest) % beats_per_measure
    if beat_idx == 0:
        return min(_VELOCITY_MAX, base + _VELOCITY_STRONG_DELTA)
    if beats_per_measure >= 2 and beat_idx == beats_per_measure // 2:
        return min(_VELOCITY_MAX, base + _VELOCITY_WEAK_DELTA)
    return base


def remap_flat_velocity(
    streams: list[LogicalStream],
    *,
    threshold_variance: float = VELOCITY_FLAT_VARIANCE,
    beats_per_measure: int = 4,
) -> tuple[list[LogicalStream], list[CleanupAction]]:
    """当所有音符 velocity 方差 < threshold（几乎完全平坦）时按节拍位置重映射。

    重映射策略（base = 原始 velocity 值，Tokyo Midnight 的情况是 61）：

    - 强拍（每小节第 1 拍）：velocity = base + 20（上限 127）
    - 弱拍（4/4 第 3 拍）：velocity = base + 10
    - 偶数拍（第 2、4 拍）：velocity = base
    - 非拍点（off-beat）：velocity = base - 10（下限 1）

    当 velocity 已有自然变化（方差 >= threshold）时不执行，保留原动态。
    每次重映射记录 :class:`CleanupAction`（kind="remap_velocity"），列出
    每个被改写音符的 old/new velocity。
    """
    all_velocities = [n.velocity for s in streams for n in s.notes]
    if not all_velocities:
        return streams, []
    if statistics.pvariance(all_velocities) >= threshold_variance:
        # velocity 已有变化，不执行重映射。
        return streams, []
    base = round(statistics.fmean(all_velocities))
    actions: list[CleanupAction] = []
    for stream in streams:
        changed: list[dict] = []
        for note in stream.notes:
            new_velocity = _velocity_for_beat(
                note.start_beat, base, beats_per_measure
            )
            if new_velocity != note.velocity:
                changed.append(
                    {
                        "track_index": note.track_index,
                        "channel": note.channel,
                        "pitch": note.pitch,
                        "start_beat": round(note.start_beat, 6),
                        "beat_in_measure": round(
                            note.start_beat % beats_per_measure, 6
                        ),
                        "old_velocity": note.velocity,
                        "new_velocity": new_velocity,
                    }
                )
                note.velocity = new_velocity
        if changed:
            actions.append(
                CleanupAction(
                    kind="remap_velocity",
                    description=(
                        f"Remapped {len(changed)} flat velocities (base={base}) "
                        f"in {stream.stream_id} by beat position "
                        f"({beats_per_measure} beats/measure)."
                    ),
                    notes=changed,
                )
            )
    return streams, actions


# =============================================================================
# 功能 4：重叠截断
# =============================================================================


def truncate_overlaps(
    streams: list[LogicalStream],
) -> tuple[list[LogicalStream], list[CleanupAction]]:
    """截断同通道同音高的重叠音符。

    只处理 **同通道同音高** 的重叠：若音符 A 的 end_tick > 音符 B 的
    start_tick 且 A.pitch == B.pitch，则把 A 的 duration 截断到 B 的起始
    时刻。**不同音高的重叠不处理**（这是和弦，留给 voice separation 阶段）。

    实现要点：按 (channel, pitch) 分组，组内按 start_tick 排序，遍历相邻同
    pitch 音符，前一个 end 越过后一个 start 即截断前一个。
    """
    actions: list[CleanupAction] = []
    for stream in streams:
        groups: dict[tuple[int | None, int], list[NormalizedNote]] = defaultdict(
            list
        )
        for note in stream.notes:
            groups[(note.channel, note.pitch)].append(note)
        stream_truncations: list[dict] = []
        for (_channel, _pitch), group_notes in groups.items():
            group_notes.sort(key=lambda n: n.start_tick)
            for i in range(len(group_notes) - 1):
                current = group_notes[i]
                following = group_notes[i + 1]
                # 仅当后续音符严格晚开始且当前音符结尾越过其起始时才截断，
                # 避免制造 0 时长音符（同时开始的同音高重复属另一类清理）。
                if current.end_tick <= following.start_tick:
                    continue
                if following.start_tick <= current.start_tick:
                    continue
                old_duration_ticks = current.duration_ticks
                old_duration_beats = current.duration_beats
                new_duration_ticks = following.start_tick - current.start_tick
                new_duration_beats = following.start_beat - current.start_beat
                current.duration_ticks = new_duration_ticks
                current.duration_beats = new_duration_beats
                stream_truncations.append(
                    {
                        "track_index": current.track_index,
                        "channel": current.channel,
                        "pitch": current.pitch,
                        "start_tick": current.start_tick,
                        "old_duration_ticks": old_duration_ticks,
                        "new_duration_ticks": new_duration_ticks,
                        "old_duration_beats": round(old_duration_beats, 6),
                        "new_duration_beats": round(new_duration_beats, 6),
                    }
                )
        if stream_truncations:
            actions.append(
                CleanupAction(
                    kind="truncate_overlap",
                    description=(
                        f"Truncated {len(stream_truncations)} same-pitch overlap(s) "
                        f"in {stream.stream_id}."
                    ),
                    notes=stream_truncations,
                )
            )
    return streams, actions


# =============================================================================
# 集成入口 cleanup_streams
# =============================================================================


def cleanup_streams(
    streams: list[LogicalStream],
    *,
    micro_note_threshold_beats: float = MICRO_NOTE_DURATION_BEATS,
    timeline: NormalizedTimeline | None = None,
    tuning: GuitarTuning | None = None,
    out_of_range_mode: str = "flag",  # flag / remove / transpose
) -> CleanupResult:
    """Deduplicate duplicate streams, remove micro-notes, and report noise.

    执行顺序：
    1. 去重 duplicate streams（已有）
    2. 去除 micro-notes（已有）
    3. **NEW** Tempo 去重（当 timeline 传入时）
    4. **NEW** 超范围音高处理（当 tuning 传入时）
    5. **NEW** Velocity 重映射（当 timeline 传入且 velocity 平坦时）
    6. **NEW** 重叠截断（始终执行）
    7. 分析 velocity 和 overlap（已有）

    Merge is conservative (keeps one copy of duplicated material); overlapping
    onsets and velocity spikes are only analyzed, never silently deleted. 所有
    新功能的 CleanupAction 都包含足够的描述信息，可追溯。
    """
    # 1. 去重 duplicate streams
    groups = _find_duplicate_groups(streams)
    merged_streams, merge_actions = _merge_duplicate_groups(streams, groups)
    # 2. 去除 micro-notes
    cleaned_streams, micro_actions = _remove_micro_notes(
        merged_streams, micro_note_threshold_beats
    )

    all_actions: list[CleanupAction] = merge_actions + micro_actions
    tempo_dedup_count = 0
    out_of_range_count = 0
    velocity_remapped = False
    overlaps_truncated = 0

    # 3. Tempo 去重（当 timeline 传入时）
    if timeline is not None:
        _deduped_tempos, tempo_actions = deduplicate_tempos(timeline)
        tempo_dedup_count = len(tempo_actions)
        all_actions.extend(tempo_actions)

    # 4. 超范围音高处理（当 tuning 传入时）
    if tuning is not None:
        cleaned_streams, oor_actions = handle_out_of_range_pitches(
            cleaned_streams, tuning, mode=out_of_range_mode
        )
        out_of_range_count = sum(len(a.notes) for a in oor_actions)
        all_actions.extend(oor_actions)

    # 5. Velocity 重映射（当 timeline 传入且 velocity 平坦时）
    if timeline is not None:
        beats_per_measure = _beats_per_measure_from_timeline(timeline)
        cleaned_streams, vel_actions = remap_flat_velocity(
            cleaned_streams, beats_per_measure=beats_per_measure
        )
        if vel_actions:
            velocity_remapped = True
            all_actions.extend(vel_actions)

    # 6. 重叠截断（始终执行）
    cleaned_streams, overlap_actions = truncate_overlaps(cleaned_streams)
    # 统计截断次数（每个 action 的 notes 列出了该流内的所有截断）。
    overlaps_truncated = sum(len(a.notes) for a in overlap_actions)
    all_actions.extend(overlap_actions)

    # 7. 分析 velocity 和 overlap
    all_notes = [n for s in cleaned_streams for n in s.notes]
    return CleanupResult(
        streams=cleaned_streams,
        actions=all_actions,
        velocity=analyze_velocity(all_notes),
        overlap=analyze_overlap(all_notes),
        tuning=tuning,
        out_of_range_count=out_of_range_count,
        tempo_dedup_count=tempo_dedup_count,
        velocity_remapped=velocity_remapped,
        overlaps_truncated=overlaps_truncated,
    )


__all__ = [
    "MICRO_NOTE_DURATION_BEATS",
    "TEMPO_DEDUP_BPM_THRESHOLD",
    "VELOCITY_FLAT_VARIANCE",
    "VelocityAnalysis",
    "OverlapAnalysis",
    "CleanupAction",
    "CleanupResult",
    "analyze_velocity",
    "analyze_overlap",
    "cleanup_streams",
    "deduplicate_tempos",
    "handle_out_of_range_pitches",
    "auto_detect_tuning",
    "remap_flat_velocity",
    "truncate_overlaps",
]
