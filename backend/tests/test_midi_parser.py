"""MIDI parser tests — verify SMF parsing, note resolution, and diagnostics."""

from __future__ import annotations

from pathlib import Path

from fretpilot.midi.parser import load_midi
from fretpilot.midi.models import NormalizedTimeline

from tests.conftest import _make_midi_file


class TestLoadMidi:
    """Tests for the load_midi function."""

    def test_load_returns_normalized_timeline(self, midi_file: Path) -> None:
        timeline = load_midi(midi_file)
        assert isinstance(timeline, NormalizedTimeline)
        assert timeline.midi_type == 1
        assert timeline.ticks_per_beat > 0

    def test_load_extracts_tempo(self, midi_file: Path) -> None:
        timeline = load_midi(midi_file)
        assert len(timeline.tempo_events) >= 1
        assert timeline.tempo_events[0].bpm == 120.0

    def test_load_extracts_time_signature(self, midi_file: Path) -> None:
        timeline = load_midi(midi_file)
        assert len(timeline.time_signature_events) >= 1
        ts = timeline.time_signature_events[0]
        assert ts.numerator == 4
        assert ts.denominator == 4

    def test_load_extracts_notes(self, midi_file: Path) -> None:
        timeline = load_midi(midi_file)
        assert len(timeline.tracks) >= 2  # meta + guitar
        guitar_track = None
        for track in timeline.tracks:
            if track.notes:
                guitar_track = track
                break
        assert guitar_track is not None
        assert len(guitar_track.notes) == 8  # C major scale

    def test_load_note_pitches(self, midi_file: Path) -> None:
        timeline = load_midi(midi_file)
        guitar_track = next(t for t in timeline.tracks if t.notes)
        pitches = [n.pitch for n in guitar_track.notes]
        assert pitches == [60, 62, 64, 65, 67, 69, 71, 72]

    def test_load_note_beat_timing(self, midi_file: Path) -> None:
        timeline = load_midi(midi_file)
        guitar_track = next(t for t in timeline.tracks if t.notes)
        # Each note starts at i * 1.0 beats (tpb=480, step=480)
        for i, note in enumerate(guitar_track.notes):
            assert abs(note.start_beat - i * 1.0) < 0.001
        # Duration is 0.5 beats (240 ticks / 480 tpb)
        assert abs(guitar_track.notes[0].duration_beats - 0.5) < 0.001

    def test_load_program_change(self, midi_file: Path) -> None:
        timeline = load_midi(midi_file)
        assert len(timeline.program_events) >= 1
        assert timeline.program_events[0].program == 30  # Distortion Guitar

    def test_load_source_path(self, midi_file: Path) -> None:
        timeline = load_midi(midi_file)
        assert str(midi_file.name) in timeline.source or str(midi_file) == timeline.source

    def test_load_initial_bpm_property(self, midi_file: Path) -> None:
        timeline = load_midi(midi_file)
        assert timeline.initial_bpm == 120.0

    def test_load_initial_time_signature_property(self, midi_file: Path) -> None:
        timeline = load_midi(midi_file)
        assert timeline.initial_time_signature == (4, 4)

    def test_load_note_count_property(self, midi_file: Path) -> None:
        timeline = load_midi(midi_file)
        assert timeline.note_count == 8

    def test_load_with_velocity(self, midi_file: Path) -> None:
        timeline = load_midi(midi_file)
        guitar_track = next(t for t in timeline.tracks if t.notes)
        for note in guitar_track.notes:
            assert note.velocity == 80

    def test_load_empty_midi_file(self, tmp_path: Path) -> None:
        """An empty MIDI file (no note tracks) should still parse."""
        import mido

        mid = mido.MidiFile(type=1, ticks_per_beat=480)
        meta = mido.MidiTrack()
        meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=0))
        meta.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
        mid.tracks.append(meta)
        path = tmp_path / "empty.mid"
        mid.save(path)

        timeline = load_midi(path)
        assert timeline.note_count == 0
        assert len(timeline.tempo_events) >= 1

    def test_load_chord_notes(self, tmp_path: Path) -> None:
        """Multiple simultaneous notes should be parsed as a chord."""
        notes = [
            (60, 0, 480, 80),  # C
            (64, 0, 480, 80),  # E
            (67, 0, 480, 80),  # G
        ]
        path = _make_midi_file(tmp_path / "chord.mid", notes=notes)
        timeline = load_midi(path)
        guitar_track = next(t for t in timeline.tracks if t.notes)
        assert len(guitar_track.notes) == 3
        # All notes should start at beat 0
        for note in guitar_track.notes:
            assert abs(note.start_beat) < 0.001
