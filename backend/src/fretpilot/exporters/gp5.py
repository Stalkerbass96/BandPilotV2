"""Guitar IR → Guitar Pro 5 (.gp5) exporter.

Consumes ScoreTiming (notation timing) + IRFingering + articulations.
Outputs a .gp5 file readable by Guitar Pro. Uses PyGuitarPro for writing.

Helpers are kept small (≤80 lines) to avoid the god-function anti-pattern.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Iterable

import guitarpro as gp

from fretpilot.exporters.base import ExportResult, UnsupportedGuitarIR
from fretpilot.ir.models import GuitarMeasure, GuitarNoteEvent, GuitarProjectIR


def _build_duration_candidates() -> list[gp.Duration]:
    """Pre-compute all candidate GP durations (with dotted/tuplet variants)."""
    candidates: dict[int, tuple[int, gp.Duration]] = {}
    for value in (
        gp.Duration.whole, gp.Duration.half, gp.Duration.quarter,
        gp.Duration.eighth, gp.Duration.sixteenth,
        gp.Duration.thirtySecond, gp.Duration.sixtyFourth,
    ):
        for dotted in (False, True):
            for enters, times in ((1, 1), (3, 2)):
                duration = gp.Duration(
                    value=value, isDotted=dotted,
                    tuplet=gp.Tuplet(enters=enters, times=times),
                )
                complexity = (2 if enters != times else 0) + (1 if dotted else 0)
                existing = candidates.get(duration.time)
                if existing is None or complexity < existing[0]:
                    candidates[duration.time] = (complexity, duration)
    return [
        item[1] for item in sorted(
            candidates.values(), key=lambda i: (-i[1].time, i[0], i[1].value)
        )
    ]


_DURATION_CANDIDATES = _build_duration_candidates()


@lru_cache(maxsize=512)
def _split_duration_ticks(total_ticks: int) -> tuple[gp.Duration, ...]:
    """Split a tick count into the minimal set of GP durations."""
    if total_ticks <= 0:
        raise UnsupportedGuitarIR("GP5 duration must be positive.")
    try:
        return (gp.Duration.fromTime(total_ticks),)
    except (ValueError, OverflowError):
        pass

    best: list[gp.Duration] | None = None

    def search(remaining: int, chosen: list[gp.Duration]) -> None:
        nonlocal best
        if remaining == 0:
            if best is None or len(chosen) < len(best):
                best = list(chosen)
            return
        if best is not None and len(chosen) >= len(best):
            return
        for candidate in _DURATION_CANDIDATES:
            if candidate.time > remaining:
                continue
            chosen.append(candidate)
            search(remaining - candidate.time, chosen)
            chosen.pop()

    search(total_ticks, [])
    if best is None:
        raise UnsupportedGuitarIR(f"Duration {total_ticks} ticks cannot be represented.")
    return tuple(best)


def _beats_to_ticks(beats: float) -> int:
    """Convert beat count to GP ticks (quarter note = 960 ticks)."""
    return int(round(beats * gp.Duration.quarterTime))


def _make_rest_beats(
    voice: gp.Voice, absolute_start: int, duration_ticks: int
) -> list[gp.Beat]:
    """Create rest beats filling a gap."""
    beats: list[gp.Beat] = []
    cursor = absolute_start
    for duration in _split_duration_ticks(duration_ticks):
        beat = gp.Beat(voice, duration=duration, start=cursor, status=gp.BeatStatus.rest)
        beats.append(beat)
        cursor += duration.time
    return beats


def _apply_note_effects(event: GuitarNoteEvent, note: gp.Note) -> None:
    """Apply direct articulation effects (vibrato/let_ring/palm_mute/staccato)."""
    for articulation in event.articulations:
        if articulation.type == "vibrato":
            note.effect.vibrato = True
        elif articulation.type == "let_ring":
            note.effect.letRing = True
        elif articulation.type == "palm_mute":
            note.effect.palmMute = True
        elif articulation.type == "staccato":
            note.effect.staccato = True


def _apply_linked_effects(
    events: Iterable[GuitarNoteEvent],
    note_lookup: dict[str, gp.Note],
    warnings: list[str],
) -> None:
    """Apply linked articulations (hammer_on/pull_off/slide) to source notes."""
    for event in events:
        for articulation in event.articulations:
            if articulation.type not in {"hammer_on", "pull_off", "slide"}:
                continue
            if not articulation.source_note_id:
                warnings.append(f"Skipped {articulation.type} on {event.id}: no source ID.")
                continue
            source = note_lookup.get(articulation.source_note_id)
            if source is None:
                warnings.append(
                    f"Skipped {articulation.type} on {event.id}: source note not exported."
                )
                continue
            if articulation.type in {"hammer_on", "pull_off"}:
                source.effect.hammer = True
            elif articulation.type == "slide":
                source.effect.slides.append(gp.SlideType.shiftSlideTo)


def _group_events_by_onset(
    measure: GuitarMeasure, voice_number: int
) -> list[tuple[float, list[GuitarNoteEvent]]]:
    """Group measure events by onset beat for a given voice."""
    grouped: dict[float, list[GuitarNoteEvent]] = {}
    for event in measure.events:
        if event.score.voice == voice_number:
            grouped.setdefault(event.score.start_beat, []).append(event)
    return sorted(grouped.items(), key=lambda item: item[0])


# 各弦的空弦音高（string number → MIDI pitch），用于超范围音符的占位 fingering。
_OPEN_PITCHES = {6: 40, 5: 45, 4: 50, 3: 55, 2: 59, 1: 64}


def _placeholder_fingering(pitch: int, used: set[int]) -> tuple[int, int]:
    """Return a placeholder (string, fret) for an out-of-range pitch.

    IR 语义：unplayable 音符保持 string/fret=None（真相）。GP5 是"呈现"层，
    需要一个可写入的占位 fingering，让超范围音符出现在 voice 2 中供用户
    一眼识别并批量删除：

    - pitch < 最低弦 E2（40）：fret = pitch - 空弦音高（负数）；
    - pitch > 最高弦 E6 24 品（88）：fret = pitch - 空弦音高（超过 24）。

    优先用最贴近的弦（低音用 low E 弦 6、高音用 high E 弦 1）；当该弦已被
    同和弦其他音符占用时，顺延到相邻未占用弦，保证 fret 仍超范围。
    """
    order = (6, 5, 4, 3, 2, 1) if pitch < 40 else (1, 2, 3, 4, 5, 6)
    for string in order:
        if string not in used:
            return string, pitch - _OPEN_PITCHES[string]
    # 极端情况（和弦超过 6 根弦）：退回最贴近的弦，fret 仍超范围。
    return (6 if pitch < 40 else 1, pitch - (40 if pitch < 40 else 64))


def _chord_fingerings(
    events: list[GuitarNoteEvent],
    warnings: list[str],
) -> list[tuple[GuitarNoteEvent, int, int]]:
    """Assign distinct (string, fret) to every note in a same-onset chord.

    IR 的 fingering 是"真相"，但同 onset 和弦里多根音符可能落到同一根弦
    （脏 MIDI 量化后把琶音压成和弦导致），而 Guitar Pro 无法表示同弦重复音
    （写出的 .gp5 会损坏）。本函数在呈现层做两件事：

    1. unplayable 音符（string/fret=None）用占位 fingering（voice 2 专用）；
    2. 与已占用弦冲突的音符，改到 fretboard 上第一个未被占用的合法候选位。

    当和弦音符数超过可用弦数（无法分配到不同弦，例如 6 个低音音符挤不进
    5 根可用弦）时，丢弃无法落弦的音符并记录告警，保证导出的 .gp5 始终可被
    Guitar Pro 读取、绝不出损坏文件。
    """
    from fretpilot.guitar.fretboard import candidate_positions

    used: set[int] = set()
    pairs: list[tuple[GuitarNoteEvent, int, int]] = []
    for event in events:
        string = event.fingering.string
        fret = event.fingering.fret
        if string is None or fret is None:
            string, fret = _placeholder_fingering(event.pitch, used)
        elif string in used:
            alternate = next(
                (p for p in candidate_positions(event.pitch) if p.string not in used),
                None,
            )
            if alternate is not None:
                string, fret = alternate.string, alternate.fret
            else:
                warnings.append(
                    f"Dropped note {event.id}: chord exceeds playable strings."
                )
                continue
        if string in used:
            warnings.append(
                f"Dropped note {event.id}: no free string in chord."
            )
            continue
        used.add(string)
        pairs.append((event, string, fret))
    return pairs


def _create_note(
    beat: gp.Beat,
    event: GuitarNoteEvent,
    string: int,
    fret: int,
    is_tie: bool,
) -> gp.Note:
    """Create a GP Note from a GuitarNoteEvent with an explicit string/fret."""
    return gp.Note(
        beat,
        value=fret,
        velocity=max(1, min(127, event.performance.velocity)),
        string=string,
        type=gp.NoteType.tie if is_tie else gp.NoteType.normal,
    )


def _populate_voice(
    ir_measure: GuitarMeasure,
    gp_measure: gp.Measure,
    voice_number: int,
    note_lookup: dict[str, gp.Note],
) -> tuple[int, list[str]]:
    """Populate a single voice with beats and notes."""
    warnings: list[str] = []
    voice = gp_measure.voices[voice_number - 1]
    voice.beats.clear()
    grouped = _group_events_by_onset(ir_measure, voice_number)
    if not grouped and voice_number == 2:
        return 0, warnings

    cursor = gp_measure.start
    note_count = 0
    for absolute_start_beat, events in grouped:
        start_tick = gp_measure.start + _beats_to_ticks(absolute_start_beat - ir_measure.start_beat)
        if start_tick > cursor:
            voice.beats.extend(_make_rest_beats(voice, cursor, start_tick - cursor))
            cursor = start_tick
        grouped_count, consumed = _populate_beat_group(
            voice, events, cursor, gp_measure.end, note_lookup, warnings
        )
        note_count += grouped_count
        cursor += consumed

    if cursor < gp_measure.end:
        voice.beats.extend(_make_rest_beats(voice, cursor, gp_measure.end - cursor))
    return note_count, warnings


def _populate_beat_group(
    voice: gp.Voice,
    events: list[GuitarNoteEvent],
    cursor: int,
    measure_end: int,
    note_lookup: dict[str, gp.Note],
    warnings: list[str],
) -> tuple[int, int]:
    """Populate one beat (chord or single note) in a voice.

    返回 ``(note_count, consumed_ticks)``。同 onset 不同 duration 的和弦
    （和弦 release）用 tie 表达：主 beat 取最短 duration 承载全部音符，长音符
    超出最短的部分按 distinct 时值从短到长分层拆成 tie 延长 beat，每一层
    一个 beat 承载所有"时值 >= 该层终点"的音符（并行延长）。这样既满足 GP5
    "同 onset 同 duration"的约束，又保留了长音符的延音，且不会因串行推进
    导致小节时值溢出。

    ``measure_end`` 用于防御性保护：任何 beat（尤其 tie 延长 beat）都不得越过
    小节结束，否则会写坏 .gp5 文件（字节流错位）。即使 IR 异常也能保持文件可读。
    """
    start_cursor = cursor
    fingerings = _chord_fingerings(events, warnings)
    if not fingerings:
        return 0, 0
    durations = [
        _beats_to_ticks(event.score.duration_beats) for event, _s, _f in fingerings
    ]
    short_ticks = min(durations)

    note_count = 0
    # 主 beat：最短 duration 承载全部音符（可能按 tick 再拆成多个 tie segment）。
    for seg_idx, duration in enumerate(_split_duration_ticks(short_ticks)):
        beat = gp.Beat(voice, duration=duration, start=cursor, status=gp.BeatStatus.normal)
        voice.beats.append(beat)
        for event, string, fret in fingerings:
            is_tie = event.score.tie_in or seg_idx > 0
            note = _create_note(beat, event, string, fret, is_tie)
            if seg_idx == 0:
                _apply_note_effects(event, note)
                note_lookup[event.id] = note
            beat.notes.append(note)
            note_count += 1
        cursor += duration.time

    # 长音符超出最短 duration 的部分：按 distinct 时值从短到长分层并行 tie。
    # 同 onset 和弦音符时值不同时，将延长拆成若干层，每层用一个 beat 承载
    # 所有"时值 >= 该层终点"的音符（同一时间区间内并行延长），避免把每个
    # 长音符的延长串行推进，导致小节时值溢出（Guitar Pro 红音符）。
    distinct = sorted(set(durations))
    if len(distinct) > 1:
        prev = distinct[0]
        for layer_end in distinct[1:]:
            layer_dur = layer_end - prev
            layer_fingerings = [
                (event, s, f)
                for (event, s, f), d in zip(fingerings, durations, strict=True)
                if d >= layer_end
            ]
            # 防御：tie 延长不得超过小节结束，避免 tick 溢出损坏文件。
            room = measure_end - cursor
            if room <= 0:
                warnings.append(
                    f"Skipped tie extension at layer end {layer_end} ticks: "
                    f"measure overflow."
                )
                break
            if layer_dur > room:
                warnings.append(
                    f"Truncated tie extension at layer end {layer_end} ticks "
                    f"({layer_dur} -> {room} ticks) at measure end."
                )
                layer_dur = room
            for seg_dur in _split_duration_ticks(layer_dur):
                beat = gp.Beat(voice, duration=seg_dur, start=cursor, status=gp.BeatStatus.normal)
                voice.beats.append(beat)
                for event, string, fret in layer_fingerings:
                    note = _create_note(beat, event, string, fret, True)
                    beat.notes.append(note)
                    note_count += 1
                cursor += seg_dur.time
            prev = layer_end
            if cursor >= measure_end:
                break

    return note_count, cursor - start_cursor


def _configure_track(gp_track: gp.Track, ir_track, number: int) -> None:
    """Apply name / fret-count / tuning from an IR track onto a GP track."""
    gp_track.number = number
    gp_track.name = ir_track.name[:40] or "FretPilot Guitar"
    gp_track.fretCount = ir_track.fret_count
    gp_track.strings = [
        gp.GuitarString(number=i + 1, value=pitch)
        for i, pitch in enumerate(reversed(ir_track.tuning))
    ]


def _configure_song(project: GuitarProjectIR) -> gp.Song:
    """Set up the GP Song structure from the IR project.

    Supports one or more guitar tracks.  All tracks share the same
    ``measureHeaders`` (derived from the first track's measures); extra tracks
    are appended with their own tuning/fret-count but the same measure count.
    """
    ir_tracks = project.tracks
    if not ir_tracks:
        raise UnsupportedGuitarIR("The Guitar IR contains no tracks.")
    if not ir_tracks[0].measures:
        raise UnsupportedGuitarIR("The Guitar IR contains no measures.")

    measure_count = len(ir_tracks[0].measures)
    for ir_track in ir_tracks:
        if len(ir_track.measures) != measure_count:
            raise UnsupportedGuitarIR(
                "All tracks must share the same measure structure."
            )

    song = gp.Song()
    song.title = project.title
    if project.tempo_map:
        song.tempo = max(1, int(round(project.tempo_map[0].bpm)))
    song.tempoName = "FretPilot"

    while len(song.measureHeaders) < measure_count:
        song.newMeasure()
    if len(song.measureHeaders) > measure_count:
        song.measureHeaders = song.measureHeaders[:measure_count]
        for track in song.tracks:
            track.measures = track.measures[:measure_count]

    # Time signatures come from the first track's measures (shared by all).
    start = gp.Duration.quarterTime
    for ir_measure, header in zip(
        ir_tracks[0].measures, song.measureHeaders, strict=True
    ):
        header.number = ir_measure.number
        header.start = start
        header.timeSignature = gp.TimeSignature(
            numerator=ir_measure.numerator,
            denominator=gp.Duration(value=ir_measure.denominator),
        )
        start = header.end

    # Configure the default track, then append and configure the rest.
    _configure_track(song.tracks[0], ir_tracks[0], 1)
    for idx, ir_track in enumerate(ir_tracks[1:], start=2):
        track = gp.Track(song, number=idx)
        _configure_track(track, ir_track, idx)
        song.tracks.append(track)

    return song


class GP5Exporter:
    """Guitar IR → Guitar Pro 5 (.gp5). Consumes ScoreTiming."""

    format_id = "gp5"

    def export(self, ir: GuitarProjectIR, output_path: Path | str) -> ExportResult:
        """Write the IR as a Guitar Pro 5.1 file."""
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)

        song = _configure_song(ir)
        warnings: list[str] = []
        total_note_count = 0

        # ``note_lookup`` is per-track so hammer_on/pull_off/slide links never
        # cross between the Lead and Rhythm tracks.
        for ir_track, gp_track in zip(ir.tracks, song.tracks, strict=True):
            note_lookup: dict[str, gp.Note] = {}
            note_count = 0
            for ir_measure, gp_measure in zip(
                ir_track.measures, gp_track.measures, strict=True
            ):
                for voice_number in (1, 2):
                    exported, voice_warnings = _populate_voice(
                        ir_measure, gp_measure, voice_number, note_lookup
                    )
                    note_count += exported
                    warnings.extend(voice_warnings)

            all_events = [e for m in ir_track.measures for e in m.events]
            _apply_linked_effects(all_events, note_lookup, warnings)
            total_note_count += note_count

        gp.write(song, destination, version=(5, 1, 0))
        return ExportResult(
            format_id=self.format_id,
            path=str(destination),
            measure_count=len(ir.tracks[0].measures),
            note_count=total_note_count,
            warnings=warnings,
        )


__all__ = ["GP5Exporter"]
