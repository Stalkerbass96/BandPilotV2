"""Tests for GPMidiConverter — GP tab to MIDI conversion."""

import tempfile
from pathlib import Path

from mido import MidiFile

from fretpilot.elearning.gp_to_midi import GPMidiConverter
from fretpilot.elearning.models import (
    GroundTruthNote,
    GroundTruthTab,
    GroundTruthTrack,
    ProfessionalScoreCorpus,
)


def _make_test_tab() -> GroundTruthTab:
    """Create a minimal GroundTruthTab for testing."""
    notes = [
        GroundTruthNote(
            measure_number=1, beat_in_measure=0.0, pitch=64,
            string=1, fret=0, hand_position=1,
            duration_beats=1.0, is_tie=False, velocity=95,
        ),
        GroundTruthNote(
            measure_number=1, beat_in_measure=1.0, pitch=59,
            string=2, fret=0, hand_position=1,
            duration_beats=1.0, is_tie=False, velocity=95,
        ),
        GroundTruthNote(
            measure_number=1, beat_in_measure=2.0, pitch=55,
            string=3, fret=0, hand_position=1,
            duration_beats=0.5, is_tie=False, velocity=95,
        ),
    ]
    return GroundTruthTab(
        file_path="test.gp5", title="Test Song", style_label="rock",
        tempo_bpm=120.0, time_signature=(4, 4),
        tuning_pitches=[40, 45, 50, 55, 59, 64],
        notes=notes, track_name="Track 1",
    )


def test_convert_produces_valid_midi():
    """GPMidiConverter produces a valid MIDI file."""
    tab = _make_test_tab()
    converter = GPMidiConverter()

    with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as tmp:
        output_path = converter.convert(tab, tmp.name)

    midi = MidiFile(str(output_path))
    assert midi.ticks_per_beat == 960
    assert len(midi.tracks) >= 2  # meta + music
    output_path.unlink(missing_ok=True)


def test_midi_contains_correct_notes():
    """MIDI file contains the correct pitches from the ground truth."""
    tab = _make_test_tab()
    converter = GPMidiConverter()

    with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as tmp:
        converter.convert(tab, tmp.name)
        midi = MidiFile(tmp.name)

    # Extract all note_on pitches from music track
    note_pitches = []
    for track in midi.tracks:
        for msg in track:
            if msg.type == "note_on" and msg.velocity > 0:
                note_pitches.append(msg.note)

    assert 64 in note_pitches  # High E
    assert 59 in note_pitches  # B
    assert 55 in note_pitches  # G
    tmp_path = Path(tmp.name)
    tmp_path.unlink(missing_ok=True)


def test_midi_has_tempo():
    """MIDI file contains a tempo meta event."""
    tab = _make_test_tab()
    converter = GPMidiConverter()

    with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as tmp:
        converter.convert(tab, tmp.name)
        midi = MidiFile(tmp.name)

    # Find tempo in first track
    tempos = [msg for track in midi.tracks for msg in track if msg.type == "set_tempo"]
    assert len(tempos) > 0
    tmp_path = Path(tmp.name)
    tmp_path.unlink(missing_ok=True)


def test_tie_notes_skipped():
    """Tie notes are not included in MIDI output."""
    tab = GroundTruthTab(
        file_path="test.gp5", title="Test", style_label="rock",
        tempo_bpm=120.0, time_signature=(4, 4),
        tuning_pitches=[40, 45, 50, 55, 59, 64],
        notes=[
            GroundTruthNote(1, 0.0, 64, 1, 0, 1, 1.0, False, 95),
            GroundTruthNote(1, 1.0, 64, 1, 0, 1, 1.0, True, 95),  # tie
        ],
        track_name="T",
    )
    converter = GPMidiConverter()

    with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as tmp:
        converter.convert(tab, tmp.name)
        midi = MidiFile(tmp.name)

    note_ons = [msg for track in midi.tracks for msg in track
                if msg.type == "note_on" and msg.velocity > 0]
    assert len(note_ons) == 1  # Only the non-tie note
    Path(tmp.name).unlink(missing_ok=True)


def test_convert_corpus_preserves_physical_tracks_and_drum_channel(tmp_path) -> None:
    guitar_note = GroundTruthNote(
        1, 0.0, 64, 1, 0, 1, 1.0, False, 95, absolute_start_beat=0.0
    )
    drum_note = GroundTruthNote(
        1, 0.0, 38, 1, 38, 1, 0.25, False, 100, absolute_start_beat=0.0
    )
    corpus = ProfessionalScoreCorpus(
        file_path="band.gp5",
        title="Band",
        artist="",
        style_label="rock",
        tempo_map=[{"beat": 0.0, "bpm": 128.0}],
        time_signature_map=[
            {"beat": 0.0, "numerator": 4, "denominator": 4},
            {"beat": 4.0, "numerator": 3, "denominator": 4},
        ],
        tracks=[
            GroundTruthTrack(
                id="track-1",
                name="Lead Guitar’s",
                program=30,
                is_percussion=False,
                tuning_pitches=[40, 45, 50, 55, 59, 64],
                capo=0,
                notes=[guitar_note],
            ),
            GroundTruthTrack(
                id="track-2",
                name="Drums",
                program=0,
                is_percussion=True,
                tuning_pitches=[0] * 6,
                capo=0,
                notes=[drum_note],
            ),
        ],
    )

    midi_path = GPMidiConverter().convert_corpus(corpus, tmp_path / "band.mid")
    midi = MidiFile(midi_path)

    assert len(midi.tracks) == 3
    assert [message.name for message in midi.tracks[1] if message.type == "track_name"] == [
        "Lead Guitar's"
    ]
    guitar_on = next(
        message
        for message in midi.tracks[1]
        if message.type == "note_on" and message.velocity > 0
    )
    drum_on = next(
        message
        for message in midi.tracks[2]
        if message.type == "note_on" and message.velocity > 0
    )
    assert guitar_on.channel == 0
    assert drum_on.channel == 9
    assert [
        (message.numerator, message.denominator)
        for message in midi.tracks[0]
        if message.type == "time_signature"
    ] == [(4, 4), (3, 4)]
