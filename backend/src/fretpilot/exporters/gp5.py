"""Guitar IR → Guitar Pro 5 (.gp5) exporter.

Consumes ScoreTiming (notation timing) + IRFingering + articulations.
Outputs a .gp5 file readable by Guitar Pro. Uses PyGuitarPro for writing.

Also supports drum tracks (DrumProjectIR) via GM percussion channel 10.

Helpers are kept small (≤80 lines) to avoid the god-function anti-pattern.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Iterable

import guitarpro as gp

from fretpilot.exporters.base import ExportResult, UnsupportedGuitarIR
from fretpilot.ir.drum_models import DrumMeasure, DrumNoteEvent, DrumProjectIR, DrumTrackIR
from fretpilot.ir.models import GuitarMeasure, GuitarNoteEvent, GuitarProjectIR

# Guitar Pro 8 rejects GP5 pitched tracks with fewer than four strings even
# though PyGuitarPro can serialize and parse them.  Keep this compatibility
# limit explicit so an export can never report success for a file GP8 refuses.
GP5_MIN_PITCHED_STRINGS = 4
GP5_MAX_PITCHED_STRINGS = 7


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
    # PyGuitarPro derives some measure ends with true division for unusual
    # meters, so an integral tick count can arrive as ``960.0``. Its
    # Duration.fromTime implementation requires an integer/Fraction.
    total_ticks = int(round(total_ticks))
    if total_ticks <= 0:
        raise UnsupportedGuitarIR("GP5 duration must be positive.")
    try:
        return (gp.Duration.fromTime(total_ticks),)
    except (AttributeError, ValueError, OverflowError):
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
    cursor = int(round(absolute_start))
    for duration in _split_duration_ticks(duration_ticks):
        beat = gp.Beat(voice, duration=duration, start=cursor, status=gp.BeatStatus.rest)
        beats.append(beat)
        cursor += duration.time
    return beats


def _apply_note_effects(event: GuitarNoteEvent, note: gp.Note) -> None:
    """Apply direct Guitar Pro note effects without rewriting the score."""
    for articulation in event.articulations:
        if articulation.type == "vibrato":
            note.effect.vibrato = True
        elif articulation.type == "let_ring":
            note.effect.letRing = True
        elif articulation.type == "palm_mute":
            note.effect.palmMute = True
        elif articulation.type == "staccato":
            note.effect.staccato = True
        elif articulation.type == "ghost_note":
            note.effect.ghostNote = True
        elif articulation.type == "accent":
            note.effect.accentuatedNote = True
        elif articulation.type == "heavy_accent":
            note.effect.heavyAccentuatedNote = True
        elif articulation.type == "harmonic":
            note.effect.harmonic = gp.NaturalHarmonic()
        elif articulation.type == "bend":
            semitones = max(0.25, min(6.0, articulation.parameters.get("semitones", 1.0)))
            bend_value = max(1, round(semitones * gp.BendEffect.semitoneLength))
            note.effect.bend = gp.BendEffect(
                type=gp.BendType.bend,
                value=bend_value,
                points=[
                    gp.BendPoint(position=0, value=0),
                    gp.BendPoint(
                        position=gp.BendEffect.maxPosition,
                        value=bend_value,
                    ),
                ],
            )


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


def _chord_fingerings(
    events: list[GuitarNoteEvent],
    warnings: list[str],
) -> list[tuple[GuitarNoteEvent, int, int]]:
    """Read validated chord fingerings without repairing score semantics."""
    used: set[int] = set()
    pairs: list[tuple[GuitarNoteEvent, int, int]] = []
    for event in events:
        string = event.fingering.string
        fret = event.fingering.fret
        if string is None or fret is None:
            raise UnsupportedGuitarIR(
                f"Note {event.id} has no playable fingering; validate the score before export."
            )
        if string in used:
            raise UnsupportedGuitarIR(
                f"Chord assigns multiple notes to string {string}; exporter will not rewrite it."
            )
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
    *,
    fill_empty: bool = False,
) -> tuple[int, list[str]]:
    """Populate a single voice with beats and notes."""
    warnings: list[str] = []
    voice = gp_measure.voices[voice_number - 1]
    voice.beats.clear()
    grouped = _group_events_by_onset(ir_measure, voice_number)
    if not grouped and voice_number == 2 and not fill_empty:
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


def _gp5_safe_text(value: str, *, fallback: str, maximum: int) -> str:
    """Return metadata representable by GP5's legacy cp1252 byte strings."""
    safe = value.encode("cp1252", errors="replace").decode("cp1252")[:maximum]
    if not safe.strip() or not any(character != "?" for character in safe if not character.isspace()):
        return fallback[:maximum]
    return safe


def _requires_metadata_fallback(value: str) -> bool:
    try:
        value.encode("cp1252")
    except UnicodeEncodeError:
        return True
    return False


def _configure_track(gp_track: gp.Track, ir_track, number: int) -> None:
    """Apply name / fret-count / tuning from an IR track onto a GP track."""
    if not GP5_MIN_PITCHED_STRINGS <= len(ir_track.tuning) <= GP5_MAX_PITCHED_STRINGS:
        raise UnsupportedGuitarIR(
            f"GP5 pitched tracks require {GP5_MIN_PITCHED_STRINGS} to "
            f"{GP5_MAX_PITCHED_STRINGS} strings for Guitar Pro compatibility, but "
            f"track {ir_track.name!r} uses {len(ir_track.tuning)}. Choose a "
            "compatible tuning or export MusicXML."
        )
    gp_track.number = number
    gp_track.name = _gp5_safe_text(
        ir_track.name,
        fallback=f"FretPilot Track {number}",
        maximum=40,
    )
    gp_track.fretCount = ir_track.fret_count
    gp_track.offset = ir_track.capo
    gp_track.strings = [
        gp.GuitarString(number=i + 1, value=pitch)
        for i, pitch in enumerate(reversed(ir_track.tuning))
    ]
    if ir_track.program is not None:
        gp_track.channel.instrument = max(0, min(127, ir_track.program))
    elif ir_track.role == "bass":
        gp_track.channel.instrument = 33
    elif ir_track.role == "keys":
        gp_track.channel.instrument = 0
    mixer = ir_track.mixer
    gp_track.channel.volume = round(float(mixer.get("volume", 0.8)) * 127)
    gp_track.channel.balance = round((float(mixer.get("pan", 0.0)) + 1) * 63.5)
    gp_track.isMute = bool(mixer.get("mute", False))
    gp_track.isSolo = bool(mixer.get("solo", False))


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
    song.title = _gp5_safe_text(project.title, fallback="BandPilot", maximum=127)
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
        if any(
            _requires_metadata_fallback(value)
            for value in (ir.title, *(track.name for track in ir.tracks))
        ):
            warnings.append(
                "GP5 uses legacy cp1252 metadata; unsupported Unicode title/track "
                "characters were replaced. MusicXML preserves full Unicode metadata."
            )
        total_note_count = 0

        # ``note_lookup`` is per-track so hammer_on/pull_off/slide links never
        # cross between the Lead and Rhythm tracks.
        for ir_track, gp_track in zip(ir.tracks, song.tracks, strict=True):
            note_lookup: dict[str, gp.Note] = {}
            note_count = 0
            uses_voice_two = any(
                event.score.voice == 2
                for measure in ir_track.measures
                for event in measure.events
            )
            for ir_measure, gp_measure in zip(
                ir_track.measures, gp_track.measures, strict=True
            ):
                for voice_number in (1, 2):
                    exported, voice_warnings = _populate_voice(
                        ir_measure,
                        gp_measure,
                        voice_number,
                        note_lookup,
                        fill_empty=voice_number == 2 and uses_voice_two,
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


__all__ = ["GP5Exporter", "export_bandpilot"]


# ─── Drum track support ───

# Drum piece → GM MIDI pitch (for GP5 percussion track on channel 10).
_DRUM_PIECE_TO_PITCH: dict[str, int] = {
    "kick": 36,
    "snare": 38,
    "side_stick": 37,
    "hand_clap": 39,
    "hihat_closed": 42,
    "hihat_pedal": 44,
    "hihat_open": 46,
    "tom_high": 50,
    "tom_mid": 48,
    "tom_low": 45,
    "tom_floor": 43,
    "crash": 49,
    "crash_2": 57,
    "ride": 51,
    "ride_bell": 53,
    "ride_2": 59,
    "china": 52,
    "splash": 55,
    "tambourine": 54,
    "cowbell": 56,
    "vibraslap": 58,
}


def _configure_drum_track(gp_track: gp.Track, ir_track: DrumTrackIR, number: int) -> None:
    """Configure a GP track as a percussion/drum track."""
    gp_track.number = number
    gp_track.name = _gp5_safe_text(
        ir_track.name,
        fallback=f"Drums {number}",
        maximum=40,
    )
    # GP5 requires virtual strings as serialization slots for simultaneous
    # percussion notes. They are not visual staff lines: the rendered score
    # is a standard five-line percussion staff with tablature hidden.
    gp_track.isPercussionTrack = True
    gp_track.settings.notation = True
    gp_track.settings.tablature = False
    gp_track.channel.channel = 9  # General MIDI channel 10 (zero-based here).
    gp_track.channel.effectChannel = 9
    mixer = ir_track.mixer
    gp_track.channel.volume = round(float(mixer.get("volume", 0.8)) * 127)
    gp_track.channel.balance = round((float(mixer.get("pan", 0.0)) + 1) * 63.5)
    gp_track.isMute = bool(mixer.get("mute", False))
    gp_track.isSolo = bool(mixer.get("solo", False))
    gp_track.strings = [
        gp.GuitarString(number=i + 1, value=0)
        for i in range(6)
    ]


def _populate_drum_voice(
    ir_measure: DrumMeasure,
    gp_measure: gp.Measure,
    voice_number: int,
    *,
    fill_empty: bool = False,
) -> tuple[int, list[str]]:
    """Populate a drum measure's voice with beats and notes.

    Drum notes use GM percussion pitches on channel 10. Simultaneous hits use
    separate virtual strings because GP5 serializes a beat with a string
    bitmask; those slots are hidden from the notation-only drum staff.
    """
    warnings: list[str] = []
    voice = gp_measure.voices[voice_number - 1]
    voice.beats.clear()
    voice.direction = (
        gp.VoiceDirection.up if voice_number == 1 else gp.VoiceDirection.down
    )

    # Group events by onset beat.
    grouped: dict[float, list[DrumNoteEvent]] = {}
    for event in ir_measure.events:
        if event.score.voice != voice_number:
            continue
        grouped.setdefault(event.score.start_beat, []).append(event)
    grouped_list = sorted(grouped.items(), key=lambda item: item[0])
    if not grouped_list and voice_number == 2 and not fill_empty:
        return 0, warnings

    cursor = gp_measure.start
    note_count = 0

    for group_index, (absolute_start_beat, events) in enumerate(grouped_list):
        events = sorted(events, key=lambda event: (event.pitch, event.id))
        if len(events) > len(gp_measure.track.strings):
            raise UnsupportedGuitarIR(
                f"Drum onset at beat {absolute_start_beat} contains {len(events)} "
                f"hits but GP5 exposes only {len(gp_measure.track.strings)} "
                "simultaneous virtual strings."
            )
        start_tick = gp_measure.start + _beats_to_ticks(
            absolute_start_beat - ir_measure.start_beat
        )
        if start_tick > cursor:
            voice.beats.extend(_make_rest_beats(voice, cursor, start_tick - cursor))
            cursor = start_tick
        elif start_tick < cursor:
            raise UnsupportedGuitarIR(
                f"Drum onset at beat {absolute_start_beat} overlaps a previous "
                f"beat in voice {voice_number}; repair/validate the score first."
            )

        # Reject score durations that cross the next onset or barline. The
        # pipeline/validator normally guarantees this; keeping the export
        # guard prevents malformed legacy IR from producing red GP notes.
        durations = [
            _beats_to_ticks(e.score.duration_beats) for e in events
        ]
        short_ticks = min(durations) if durations else gp.Duration.quarterTime
        next_start_tick = (
            gp_measure.start
            + _beats_to_ticks(grouped_list[group_index + 1][0] - ir_measure.start_beat)
            if group_index + 1 < len(grouped_list)
            else gp_measure.end
        )
        available_ticks = max(1, next_start_tick - start_tick)
        if short_ticks > available_ticks:
            raise UnsupportedGuitarIR(
                f"Drum duration at beat {absolute_start_beat} overlaps the next "
                f"onset or barline in voice {voice_number}; repair/validate the "
                "score first."
            )

        for seg_idx, duration in enumerate(_split_duration_ticks(short_ticks)):
            beat = gp.Beat(
                voice,
                duration=duration,
                start=cursor,
                status=gp.BeatStatus.normal,
            )
            voice.beats.append(beat)
            # GP5 encodes notes in a beat using a string bitmask. Writing
            # multiple drum hits to the same virtual string emits extra note
            # payloads that the reader cannot count and corrupts the rest of
            # the file. Drum strings are purely serialization slots, so assign
            # one distinct slot per simultaneous hit.
            for virtual_string, event in enumerate(events, start=1):
                # The source GM pitch is score identity (e.g. 35 vs 36 kick,
                # 38 vs 40 snare, 49 vs 57 crash) and must survive round-trip.
                pitch = (
                    event.pitch
                    if 1 <= event.pitch <= 127
                    else _DRUM_PIECE_TO_PITCH.get(event.piece, 38)
                )
                note = gp.Note(
                    beat,
                    value=pitch,
                    velocity=max(
                        1, min(127, event.performance.velocity)
                    ),
                    string=virtual_string,
                    type=gp.NoteType.normal,
                )
                # Apply technique as effect
                tech = event.location.technique
                if tech == "ghost":
                    note.effect.ghostNote = True
                elif tech == "accent":
                    note.effect.accentuatedNote = True
                elif tech == "flam":
                    note.effect.graceType = gp.GraceType.simple
                beat.notes.append(note)
                note_count += 1
            cursor += duration.time

    if cursor < gp_measure.end:
        voice.beats.extend(_make_rest_beats(voice, cursor, gp_measure.end - cursor))

    return note_count, warnings


def _fill_rest_measure(
    gp_measure: gp.Measure, *, fill_voice_two: bool = False
) -> None:
    """Fill a GP measure's voice 1 with a full-measure rest.

    BandPilot guitar and drum IRs are produced by independent pipelines and
    may span different numbers of measures (e.g. a 4-measure drum groove vs
    a 2-measure guitar riff). The .gp5 requires one shared measure count, so
    the shorter track's trailing measures are written as empty (rest-only).
    """
    voice = gp_measure.voices[0]
    voice.beats.clear()
    voice.beats.extend(
        _make_rest_beats(voice, gp_measure.start, gp_measure.end - gp_measure.start)
    )
    if fill_voice_two:
        second_voice = gp_measure.voices[1]
        second_voice.beats.clear()
        second_voice.beats.extend(
            _make_rest_beats(
                second_voice,
                gp_measure.start,
                gp_measure.end - gp_measure.start,
            )
        )


def _measure_by_number(
    measures: list, gp_measure: gp.Measure
) -> object | None:
    """Return the IR measure matching a GP measure's number, or ``None``.

    IR measures are numbered from 1 contiguously; GP measures inherit the
    header numbers set in ``export_bandpilot``. When an IR is shorter than
    the shared measure count, later GP measures have no IR counterpart.
    """
    number = gp_measure.number
    if not measures or number < 1 or number > len(measures):
        return None
    return measures[number - 1]


def export_bandpilot(
    guitar_ir: GuitarProjectIR | None,
    drum_ir: DrumProjectIR | None,
    output_path: Path | str,
    *,
    track_order: Iterable[str] | None = None,
) -> ExportResult:
    """Export guitar + drum IRs as a single multi-track .gp5 file.

    Args:
        guitar_ir: Guitar project IR (may be None for drum-only projects).
        drum_ir: Drum project IR (may be None for guitar-only projects).
        output_path: Destination .gp5 file path.
        track_order: Optional stable track-ID order from the source score.

    Returns:
        ExportResult with combined note count and warnings.

    The guitar and drum IRs come from independent pipelines and may span
    different numbers of measures; the track with fewer measures has its
    trailing measures written as rests so all tracks share one measure count.
    """
    if guitar_ir is None and drum_ir is None:
        raise UnsupportedGuitarIR("At least one IR (guitar or drum) is required.")

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    # Use guitar IR as the base if available, otherwise create from drum IR.
    base_ir = guitar_ir if guitar_ir is not None else drum_ir
    song = gp.Song()
    song.title = _gp5_safe_text(base_ir.title, fallback="BandPilot", maximum=127)
    if base_ir.tempo_map:
        song.tempo = max(1, int(round(base_ir.tempo_map[0].bpm)))
    song.tempoName = "BandPilot"

    guitar_tracks = guitar_ir.tracks if guitar_ir else []
    drum_tracks = drum_ir.tracks if drum_ir else []

    # Shared measure count = the longest IR (per family, first track).
    measure_count = 0
    for tracks in (guitar_tracks, drum_tracks):
        if tracks and tracks[0].measures:
            measure_count = max(measure_count, len(tracks[0].measures))
    if measure_count == 0:
        raise UnsupportedGuitarIR("No measures found in any IR.")

    while len(song.measureHeaders) < measure_count:
        song.newMeasure()
    if len(song.measureHeaders) > measure_count:
        song.measureHeaders = song.measureHeaders[:measure_count]
        for track in song.tracks:
            track.measures = track.measures[:measure_count]

    # Time signatures come from the longer IR so late time-signature changes
    # (e.g. in a longer drum part) are reflected; shorter tracks repeat the
    # last known signature in their padded tail.
    ts_source: list = []
    for tracks in (guitar_tracks, drum_tracks):
        if tracks and tracks[0].measures and len(tracks[0].measures) > len(ts_source):
            ts_source = tracks[0].measures
    start = gp.Duration.quarterTime
    last_number = 0
    last_numerator, last_denominator = 4, 4
    for idx, header in enumerate(song.measureHeaders):
        if idx < len(ts_source):
            ir_measure = ts_source[idx]
            last_number = ir_measure.number
            last_numerator = ir_measure.numerator
            last_denominator = ir_measure.denominator
        else:
            last_number += 1
        header.number = last_number
        header.start = start
        header.timeSignature = gp.TimeSignature(
            numerator=last_numerator,
            denominator=gp.Duration(value=last_denominator),
        )
        start = header.end

    warnings: list[str] = []
    metadata_values = [
        base_ir.title,
        *(track.name for track in guitar_tracks),
        *(track.name for track in drum_tracks),
    ]
    if any(_requires_metadata_fallback(value) for value in metadata_values):
        warnings.append(
            "GP5 uses legacy cp1252 metadata; unsupported Unicode title/track "
            "characters were replaced. MusicXML preserves full Unicode metadata."
        )
    total_note_count = 0
    track_number = 1
    exported_track_ids: list[str] = []
    gp_tracks_by_id: dict[str, gp.Track] = {}

    # ── Guitar tracks ──
    for ir_track in guitar_tracks:
        if track_number == 1:
            gp_track = song.tracks[0]
        else:
            gp_track = gp.Track(song, number=track_number)
            song.tracks.append(gp_track)
        _configure_track(gp_track, ir_track, track_number)
        exported_track_ids.append(ir_track.id)
        gp_tracks_by_id[ir_track.id] = gp_track

        note_lookup: dict[str, gp.Note] = {}
        uses_voice_two = any(
            event.score.voice == 2
            for measure in ir_track.measures
            for event in measure.events
        )
        for gp_measure in gp_track.measures:
            ir_measure = _measure_by_number(ir_track.measures, gp_measure)
            if ir_measure is None:
                _fill_rest_measure(
                    gp_measure, fill_voice_two=uses_voice_two
                )
                continue
            for voice_number in (1, 2):
                exported, voice_warnings = _populate_voice(
                    ir_measure,
                    gp_measure,
                    voice_number,
                    note_lookup,
                    fill_empty=voice_number == 2 and uses_voice_two,
                )
                total_note_count += exported
                warnings.extend(voice_warnings)

        all_events = [e for m in ir_track.measures for e in m.events]
        _apply_linked_effects(all_events, note_lookup, warnings)
        track_number += 1

    # ── Drum tracks ──
    for ir_track in drum_tracks:
        if track_number == 1:
            gp_track = song.tracks[0]
        else:
            gp_track = gp.Track(song, number=track_number)
            song.tracks.append(gp_track)
        _configure_drum_track(gp_track, ir_track, track_number)
        exported_track_ids.append(ir_track.id)
        gp_tracks_by_id[ir_track.id] = gp_track
        uses_voice_two = any(
            event.score.voice == 2
            for measure in ir_track.measures
            for event in measure.events
        )

        for gp_measure in gp_track.measures:
            ir_measure = _measure_by_number(ir_track.measures, gp_measure)
            if ir_measure is None:
                _fill_rest_measure(gp_measure, fill_voice_two=uses_voice_two)
                continue
            for voice_number in (1, 2):
                exported, drum_warnings = _populate_drum_voice(
                    ir_measure,
                    gp_measure,
                    voice_number,
                    fill_empty=voice_number == 2 and uses_voice_two,
                )
                total_note_count += exported
                warnings.extend(drum_warnings)
        track_number += 1

    if track_order is not None:
        requested: list[str] = []
        for track_id in track_order:
            if track_id in gp_tracks_by_id and track_id not in requested:
                requested.append(track_id)
        requested.extend(
            track_id for track_id in exported_track_ids if track_id not in requested
        )
        song.tracks = [gp_tracks_by_id[track_id] for track_id in requested]
        for number, gp_track in enumerate(song.tracks, start=1):
            gp_track.number = number

    gp.write(song, destination, version=(5, 1, 0))
    return ExportResult(
        format_id="gp5",
        path=str(destination),
        measure_count=measure_count,
        note_count=total_note_count,
        warnings=warnings,
    )
