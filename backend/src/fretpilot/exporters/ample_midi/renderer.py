"""Ample Guitar MIDI renderer — IR → playable MIDI with keyswitches.

Consumes PerformanceTiming (source timing) + articulations + AmpleGuitarProfile.
Outputs a MIDI file with keyswitch events inserted before each note based on
its articulation. The renderer only reads the IR — it never modifies it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import mido

from fretpilot.exporters.ample_midi.profile import AmpleGuitarProfile
from fretpilot.exporters.base import ExportResult
from fretpilot.ir.models import GuitarNoteEvent, GuitarProjectIR, IRArticulation

logger = logging.getLogger("fretpilot.exporters.ample_midi")


@dataclass(slots=True)
class _SourceNote:
    """Internal representation of a source note for MIDI rendering."""

    source_note_index: int
    pitch: int
    start_tick: int
    end_tick: int
    velocity: int
    articulations: list[IRArticulation] = field(default_factory=list)


def _beat_to_tick(beat: float, ticks_per_beat: int) -> int:
    """Convert a beat position to a MIDI tick."""
    return int(round(beat * ticks_per_beat))


def _collect_source_notes(
    project: GuitarProjectIR, ticks_per_beat: int, offset: int
) -> tuple[dict[int, _SourceNote], dict[str, int]]:
    """Collect unique source notes and map event IDs to source indices."""
    source_notes: dict[int, _SourceNote] = {}
    event_id_to_source: dict[str, int] = {}

    for track in project.tracks:
        for measure in track.measures:
            for event in measure.events:
                event_id_to_source[event.id] = event.source_note_index
                if event.source_note_index in source_notes:
                    _merge_articulations(source_notes[event.source_note_index], event)
                    continue
                source_notes[event.source_note_index] = _build_source_note(
                    event, ticks_per_beat, offset
                )
    return source_notes, event_id_to_source


def _build_source_note(
    event: GuitarNoteEvent, ticks_per_beat: int, offset: int
) -> _SourceNote:
    """Build a _SourceNote from a GuitarNoteEvent."""
    start = _beat_to_tick(event.performance.source_start_beat, ticks_per_beat) + offset
    duration = max(1, _beat_to_tick(event.performance.source_duration_beats, ticks_per_beat))
    return _SourceNote(
        source_note_index=event.source_note_index,
        pitch=event.pitch,
        start_tick=start,
        end_tick=start + duration,
        velocity=max(1, min(127, event.performance.velocity)),
        articulations=list(event.articulations),
    )


def _merge_articulations(note: _SourceNote, event: GuitarNoteEvent) -> None:
    """Merge articulations from a tied fragment into the source note."""
    known = {
        (a.type, a.source_note_id, round(a.confidence, 6))
        for a in note.articulations
    }
    for articulation in event.articulations:
        key = (articulation.type, articulation.source_note_id, round(articulation.confidence, 6))
        if key not in known:
            note.articulations.append(articulation)
            known.add(key)


def _add_keyswitch(
    events: list[tuple[int, int, mido.Message]],
    emitted: set[tuple[int, int]],
    tick: int,
    note: int,
    profile: AmpleGuitarProfile,
) -> bool:
    """Add a keyswitch note_on/off pair; return True if newly emitted."""
    key = (tick, note)
    if key in emitted:
        return False
    emitted.add(key)
    events.append((tick, 0, mido.Message(
        "note_on", channel=profile.note_channel, note=note,
        velocity=profile.keyswitch_velocity, time=0,
    )))
    events.append((tick + profile.keyswitch_length_ticks, 1, mido.Message(
        "note_off", channel=profile.note_channel, note=note, velocity=0, time=0,
    )))
    return True


def _should_revert_to_sustain(profile: AmpleGuitarProfile, articulation_type: str) -> bool:
    """Return True if an articulation should revert to sustain after its note.

    An articulation reverts when it is persistent (stays active until changed)
    or explicitly declares a ``revert_to`` target (e.g. slide_in_out).
    """
    art = profile.articulation_def(articulation_type)
    if art is None:
        return False
    return art.persist or bool(art.revert_to)


def _schedule_keyswitches(
    source_notes: dict[int, _SourceNote],
    event_id_to_source: dict[str, int],
    profile: AmpleGuitarProfile,
    events: list[tuple[int, int, mido.Message]],
    warnings: list[str],
) -> int:
    """Schedule keyswitch events for all articulations; return keyswitch count."""
    emitted: set[tuple[int, int]] = set()
    count = 0

    # Default sustain at start.
    sustain_note = profile.keyswitch_note("sustain")
    if sustain_note is not None and _add_keyswitch(events, emitted, 0, sustain_note, profile):
        count += 1

    for note in source_notes.values():
        for articulation in note.articulations:
            ks_note = profile.keyswitch_note(articulation.type)
            if ks_note is None:
                if articulation.type not in ("let_ring", "vibrato", "sustain"):
                    warnings.append(f"Unsupported articulation {articulation.type!r} on note {note.source_note_index}.")
                continue

            trigger_tick = max(0, note.start_tick - profile.keyswitch_preroll_ticks)
            if _add_keyswitch(events, emitted, trigger_tick, ks_note, profile):
                count += 1

            # Persistent / reverting articulations return to sustain after the note.
            if sustain_note is not None and _should_revert_to_sustain(profile, articulation.type):
                if _add_keyswitch(events, emitted, note.end_tick + 1, sustain_note, profile):
                    count += 1

    return count


def _write_track(
    track: mido.MidiTrack,
    events: list[tuple[int, int, mido.Message | mido.MetaMessage]],
) -> None:
    """Write absolute-tick events to a MIDI track with delta times."""
    previous = 0
    for absolute_tick, _priority, message in sorted(events, key=lambda e: (e[0], e[1])):
        delta = max(0, absolute_tick - previous)
        track.append(message.copy(time=delta))
        previous = absolute_tick


class AmpleMidiExporter:
    """Guitar IR → playable MIDI with Ample Guitar keyswitches."""

    format_id = "ample_midi"

    def __init__(self, profile: AmpleGuitarProfile, ticks_per_beat: int = 480) -> None:
        self.profile = profile
        self._ticks_per_beat = ticks_per_beat

    def export(self, ir: GuitarProjectIR, output_path: Path | str) -> ExportResult:
        """Render the IR as a playable MIDI file with keyswitches.

        Multiple guitar tracks (e.g. a separated Lead + Rhythm pair) are merged
        into the single performance track — the renderer reads every track's
        source notes and schedules one keyswitch stream.
        """
        if not ir.tracks:
            raise ValueError("Ample MIDI exporter requires at least one guitar track.")

        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        offset = self.profile.keyswitch_preroll_ticks

        source_notes, event_id_map = _collect_source_notes(
            ir, self._ticks_per_beat, offset
        )

        warnings: list[str] = []
        perf_events: list[tuple[int, int, mido.Message]] = []
        keyswitch_count = _schedule_keyswitches(
            source_notes, event_id_map, self.profile, perf_events, warnings
        )

        _add_note_events(source_notes, self.profile, perf_events, warnings)

        midi = mido.MidiFile(type=1, ticks_per_beat=self._ticks_per_beat)
        _build_tracks(ir, self.profile, self._ticks_per_beat, perf_events, midi)

        midi.save(destination)
        return ExportResult(
            format_id=self.format_id,
            path=str(destination),
            measure_count=len(ir.tracks[0].measures),
            note_count=len(source_notes),
            warnings=warnings,
        )


def _note_playable_range(note: _SourceNote, profile: AmpleGuitarProfile) -> tuple[int, int]:
    """Return the playable range for a note based on its articulations.

    Uses the first defined articulation's per-articulation range; falls back
    to the global playable range when the note has no recognised articulation.
    """
    for art in note.articulations:
        art_def = profile.articulation_def(art.type)
        if art_def is not None:
            return (art_def.playable_min, art_def.playable_max)
    return (profile.playable_min, profile.playable_max)


def _add_note_events(
    source_notes: dict[int, _SourceNote],
    profile: AmpleGuitarProfile,
    events: list[tuple[int, int, mido.Message]],
    warnings: list[str],
) -> None:
    """Add note_on/note_off events for all source notes."""
    for note in sorted(source_notes.values(), key=lambda n: (n.start_tick, n.pitch)):
        lo, hi = _note_playable_range(note, profile)
        if not lo <= note.pitch <= hi:
            warnings.append(
                f"MIDI note {note.pitch} outside {profile.product} range "
                f"{lo}-{hi}."
            )
        events.append((note.start_tick, 2, mido.Message(
            "note_on", channel=profile.note_channel, note=note.pitch,
            velocity=note.velocity, time=0,
        )))
        events.append((max(note.start_tick + 1, note.end_tick), 3, mido.Message(
            "note_off", channel=profile.note_channel, note=note.pitch,
            velocity=profile.note_off_velocity, time=0,
        )))


def _build_tracks(
    ir: GuitarProjectIR,
    profile: AmpleGuitarProfile,
    ticks_per_beat: int,
    perf_events: list[tuple[int, int, mido.Message]],
    midi: mido.MidiFile,
) -> None:
    """Build the meta track and performance track for the MIDI file."""
    meta_track = mido.MidiTrack()
    perf_track = mido.MidiTrack()
    midi.tracks.extend([meta_track, perf_track])

    meta_track.append(mido.MetaMessage("track_name", name="FretPilot Tempo", time=0))
    meta_events: list[tuple[int, int, mido.MetaMessage]] = []
    for event in ir.tempo_map:
        meta_events.append((
            _beat_to_tick(event.beat, ticks_per_beat), 0,
            mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(event.bpm), time=0),
        ))
    for event in ir.time_signatures:
        meta_events.append((
            _beat_to_tick(event.beat, ticks_per_beat), 1,
            mido.MetaMessage("time_signature", numerator=event.numerator,
                             denominator=event.denominator, time=0),
        ))
    _write_track(meta_track, meta_events)

    perf_track.append(mido.MetaMessage("track_name", name=f"FretPilot · {profile.product}", time=0))
    _write_track(perf_track, perf_events)


__all__ = ["AmpleMidiExporter"]
