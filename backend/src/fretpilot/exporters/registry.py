"""SongIR exporter registry and strict compatibility adapters."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from fretpilot.exporters.ample_midi.profile import load_profile
from fretpilot.exporters.ample_midi.renderer import AmpleMidiExporter
from fretpilot.exporters.base import ExportResult
from fretpilot.exporters.gp5 import GP5_MIN_PITCHED_STRINGS, export_bandpilot
from fretpilot.exporters.humanized_midi import (
    HumanizedMidiSongExporter,
    humanize_performance,
)
from fretpilot.exporters.musicxml import MusicXMLSongExporter
from fretpilot.ir.models import (
    GuitarMeasure,
    GuitarNoteEvent,
    GuitarProjectIR,
    GuitarTrackIR,
    IRFingering,
    NoteConfidence,
    PerformanceTiming,
)
from fretpilot.ir.song import SongIR
from fretpilot.ir.song_adapter import song_to_legacy
from fretpilot.validation import validate_song


class SongExporter(Protocol):
    format_id: str

    def export(self, song: SongIR, output_path: Path) -> ExportResult:
        """Serialize one validated SongIR without changing score semantics."""


class GP5SongExporter:
    format_id = "gp5"

    def export(self, song: SongIR, output_path: Path) -> ExportResult:
        validate_song(song, raise_on_error=True)
        guitar, drums = song_to_legacy(song)
        guitar, projected = _with_gp5_pitched_projection(song, guitar)
        result = export_bandpilot(guitar, drums, output_path)
        if projected:
            result.warnings.append(
                "GP5 represents non-fretted parts with pitch-preserving virtual strings; "
                "use MusicXML for native grand-staff notation."
            )
        return result


def _with_gp5_pitched_projection(
    song: SongIR,
    guitar: GuitarProjectIR | None,
) -> tuple[GuitarProjectIR | None, bool]:
    """Create a read-only GP5 serialization view for keys/generic tracks."""
    performance = {event.note_id: event for event in song.performance.events}
    projected_tracks: list[GuitarTrackIR] = []
    for track in song.score.tracks:
        if track.family not in {"keys", "generic"}:
            continue
        largest_chord = 1
        string_by_id: dict[str, int] = {}
        voice_by_id: dict[str, int] = {}
        for measure in track.measures:
            groups: dict[float, list] = {}
            for event in measure.events:
                groups.setdefault(event.score.start_beat, []).append(event)
            for events in groups.values():
                if len(events) > 14:
                    raise ValueError(
                        f"GP5 cannot project {len(events)} simultaneous notes; "
                        "two seven-string virtual voices are the format limit."
                    )
                largest_chord = max(largest_chord, min(7, len(events)))
                ordered = sorted(events, key=lambda item: item.pitch)
                for index, event in enumerate(ordered):
                    voice_by_id[event.id] = 1 if index < 7 else 2
                    string = index + 1 if index < 7 else index - 6
                    string_by_id[event.id] = string
        measures: list[GuitarMeasure] = []
        for measure in track.measures:
            events: list[GuitarNoteEvent] = []
            for event in measure.events:
                rendered = performance[event.id]
                events.append(
                    GuitarNoteEvent(
                        id=event.id,
                        source_note_index=event.source.source_note_index,
                        pitch=event.pitch,
                        score=replace(event.score, voice=voice_by_id[event.id]),
                        performance=PerformanceTiming(
                            source_start_beat=rendered.start_beat,
                            source_duration_beats=rendered.duration_beats,
                            velocity=rendered.velocity,
                        ),
                        fingering=IRFingering(
                            string=string_by_id[event.id],
                            fret=event.pitch,
                            fretting_digit=event.realization.finger,
                            hand_position=None,
                        ),
                        confidence=event.confidence or NoteConfidence(1.0, 1.0),
                    )
                )
            measures.append(
                GuitarMeasure(
                    number=measure.number,
                    start_beat=measure.start_beat,
                    duration_beats=measure.duration_beats,
                    numerator=measure.numerator,
                    denominator=measure.denominator,
                    events=events,
                )
            )
        # GP8 refuses GP5 pitched tracks with fewer than four strings.  Sparse
        # keyboard/generic parts commonly contain only one to three notes at
        # an onset, so pad their serialization-only tuning to the GP5 minimum.
        virtual_string_count = max(GP5_MIN_PITCHED_STRINGS, largest_chord)
        projected_tracks.append(
            GuitarTrackIR(
                id=track.id,
                name=track.name,
                source_track_index=(
                    track.source_track_indices[0] if track.source_track_indices else None
                ),
                role="keys" if track.family == "keys" else "generic",
                tuning=[0] * virtual_string_count,
                fret_count=127,
                measures=measures,
            )
        )
    if not projected_tracks:
        return guitar, False
    if guitar is None:
        guitar = GuitarProjectIR(
            title=song.title,
            source=song.source.filename,
            tempo_map=list(song.score.tempo_map),
            time_signatures=list(song.score.time_signatures),
            tracks=projected_tracks,
            knowledge=song.knowledge,
            style_label=song.analysis.style_label,
        )
    else:
        guitar.tracks.extend(projected_tracks)
    return guitar, True


class AmpleEclipseSongExporter:
    format_id = "ample_eclipse_midi"

    def export(self, song: SongIR, output_path: Path) -> ExportResult:
        validate_song(song, raise_on_error=True)
        guitar, _drums = song_to_legacy(song)
        if guitar is None:
            raise ValueError("Ample Eclipse export requires at least one guitar track.")
        return AmpleMidiExporter(load_profile("ample_eclipse")).export(guitar, output_path)


class HumanizedAmpleEclipseSongExporter:
    format_id = "humanized_ample_eclipse_midi"

    def export(self, song: SongIR, output_path: Path) -> ExportResult:
        validate_song(song, raise_on_error=True)
        rendered = deepcopy(song)
        rendered.performance.events = humanize_performance(rendered)
        rendered.performance.profile_id = "natural-band-v1+ample-eclipse"
        guitar, _drums = song_to_legacy(rendered)
        if guitar is None:
            raise ValueError("Humanized Ample Eclipse export requires a guitar track.")
        result = AmpleMidiExporter(load_profile("ample_eclipse")).export(guitar, output_path)
        result.format_id = self.format_id
        return result


class SongExporterRegistry:
    def __init__(self, exporters: list[SongExporter]) -> None:
        self._exporters = {exporter.format_id: exporter for exporter in exporters}
        if len(self._exporters) != len(exporters):
            raise ValueError("Duplicate SongIR exporter format ID")

    @classmethod
    def default(cls) -> SongExporterRegistry:
        return cls(
            [
                GP5SongExporter(),
                MusicXMLSongExporter(),
                HumanizedMidiSongExporter(),
                AmpleEclipseSongExporter(),
                HumanizedAmpleEclipseSongExporter(),
            ]
        )

    @property
    def formats(self) -> tuple[str, ...]:
        return tuple(sorted(self._exporters))

    def export(self, format_id: str, song: SongIR, output_path: Path) -> ExportResult:
        exporter = self._exporters.get(format_id)
        if exporter is None:
            raise KeyError(format_id)
        return exporter.export(song, output_path)


__all__ = [
    "AmpleEclipseSongExporter",
    "GP5SongExporter",
    "HumanizedAmpleEclipseSongExporter",
    "SongExporter",
    "SongExporterRegistry",
]
