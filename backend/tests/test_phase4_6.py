"""Phase 4–6 multi-instrument and export acceptance tests."""

from __future__ import annotations

from xml.etree import ElementTree as ET

import guitarpro as gp
import mido

from fretpilot.config import get_settings
from fretpilot.engine.pitched_pipeline import PitchedRepairPipeline
from fretpilot.exporters.registry import SongExporterRegistry
from fretpilot.ir.song_adapter import build_song_ir
from fretpilot.knowledge.registry import KnowledgeRegistry
from fretpilot.midi.models import (
    NormalizedNote,
    NormalizedTimeline,
    NormalizedTrack,
    TempoEvent,
    TimeSignatureEvent,
)
from fretpilot.orchestrator.detector import InstrumentFamily, TrackFamilyClassification
from fretpilot.validation import validate_song


def _track(index: int, name: str, program: int, pitches: list[tuple[int, float]]) -> NormalizedTrack:
    notes = [
        NormalizedNote(
            track_index=index,
            track_name=name,
            channel=index,
            pitch=pitch,
            velocity=76 + note_index,
            start_tick=int(start * 480),
            duration_ticks=240,
            start_beat=start,
            duration_beats=0.5,
            program=program,
        )
        for note_index, (pitch, start) in enumerate(pitches)
    ]
    return NormalizedTrack(
        index=index,
        name=name,
        notes=notes,
        instrument_name=name,
        program=program,
    )


def _song():
    bass = _track(0, "Electric Bass", 33, [(40, 0.0), (43, 0.5), (45, 1.0), (47, 1.5)])
    keys = _track(
        1,
        "Piano",
        0,
        [
            (48, 0.0),
            (52, 0.0),
            (55, 0.0),
            (60, 0.0),
            (64, 0.0),
            (67, 0.0),
            (71, 0.0),
            (74, 0.0),
        ],
    )
    generic = _track(2, "Strings", 48, [(60, 0.0), (62, 1.0), (64, 2.0)])
    timeline = NormalizedTimeline(
        source="phase4.mid",
        midi_type=1,
        ticks_per_beat=480,
        tempo_events=[TempoEvent(tick=0, beat=0.0, bpm=112.0)],
        time_signature_events=[
            TimeSignatureEvent(tick=0, beat=0.0, numerator=4, denominator=4)
        ],
        tracks=[bass, keys, generic],
    )
    registry = KnowledgeRegistry.from_assets_dir(get_settings().assets_dir)
    projects = [
        PitchedRepairPipeline(family).execute(
            track=track,
            timeline=timeline,
            registry=registry,
            settings={"title": "Phase 4–6", "midi_fidelity": 0.5},
        )
        for family, track in (("bass", bass), ("keys", keys), ("generic", generic))
    ]
    classifications = [
        TrackFamilyClassification(
            track_index=track.index,
            track_name=track.name,
            family=family,
            confidence=1.0,
            reason="test fixture",
            note_count=len(track.notes),
        )
        for family, track in (
            (InstrumentFamily.BASS, bass),
            (InstrumentFamily.KEYS, keys),
            (InstrumentFamily.UNKNOWN, generic),
        )
    ]
    return build_song_ir(
        title="Phase 4–6",
        source_path=None,
        source_filename="phase4.mid",
        timeline=timeline,
        classifications=classifications,
        guitar=None,
        drums=None,
        pitched=projects,
    )


def test_bass_keys_and_generic_have_professional_realizations() -> None:
    song = _song()
    assert validate_song(song).status == "passed"
    tracks = {track.family: track for track in song.score.tracks}
    assert set(tracks) == {"bass", "keys", "generic"}
    bass_events = [event for measure in tracks["bass"].measures for event in measure.events]
    assert all(event.realization.string and event.realization.fret is not None for event in bass_events)
    tuning = tracks["bass"].instrument["tuning"]
    assert all(
        tuning[len(tuning) - event.realization.string] + event.realization.fret == event.pitch
        for event in bass_events
    )
    key_events = [event for measure in tracks["keys"].measures for event in measure.events]
    assert {event.realization.hand for event in key_events} == {"left", "right"}
    assert all(1 <= event.realization.finger <= 5 for event in key_events)


def test_musicxml_gp5_and_humanized_midi_are_real_parseable_exports(tmp_path) -> None:
    song = _song()
    exporters = SongExporterRegistry.default()
    assert {"gp5", "musicxml", "humanized_midi"}.issubset(exporters.formats)

    xml_path = tmp_path / "score.musicxml"
    xml_result = exporters.export("musicxml", song, xml_path)
    xml = ET.parse(xml_path).getroot()
    assert xml.tag == "score-partwise"
    assert len(xml.findall("./part-list/score-part")) == 3
    assert len(xml.findall(".//note[pitch]")) == xml_result.note_count
    assert xml.findall(".//technical/string")
    assert xml.findall(".//technical/fingering")

    midi_a = tmp_path / "human-a.mid"
    midi_b = tmp_path / "human-b.mid"
    midi_result = exporters.export("humanized_midi", song, midi_a)
    exporters.export("humanized_midi", song, midi_b)
    assert midi_a.read_bytes() == midi_b.read_bytes()
    rendered = mido.MidiFile(midi_a)
    assert len(rendered.tracks) == 4
    assert sum(message.type == "note_on" for track in rendered.tracks for message in track) == midi_result.note_count

    gp5_path = tmp_path / "score.gp5"
    gp_result = exporters.export("gp5", song, gp5_path)
    parsed = gp.parse(gp5_path)
    assert len(parsed.tracks) == 3
    assert gp_result.note_count >= midi_result.note_count
    # GP8 rejects pitched GP5 tracks with fewer than four strings.  Sparse
    # keys/generic projections must still emit a compatible track shape.
    assert all(len(track.strings) >= 4 for track in parsed.tracks)
    piano_notes = [
        note
        for measure in parsed.tracks[1].measures
        for voice in measure.voices
        for beat in voice.beats
        for note in beat.notes
    ]
    assert len(piano_notes) == 8
    assert {note.string for note in piano_notes} <= set(range(1, 8))
