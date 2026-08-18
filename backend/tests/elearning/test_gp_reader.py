"""Tests for GPReader — GP file parsing."""

import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from fretpilot.elearning.gp_reader import GPReader


# We'll use a synthetic GP5 file for testing.  Since creating a GP5 binary
# is complex, we test with actual files from the reference zip if available.
REFERENCE_ZIP = Path("/Users/stevenwang/Desktop/【GTP谱】.zip")


def _make_track(name, is_percussion, n_strings, n_notes):
    """Build a duck-typed fake track with the attributes GPReader touches."""
    measures = [
        SimpleNamespace(
            voices=[SimpleNamespace(beats=[SimpleNamespace(notes=list(range(n_notes)))])]
        )
    ]
    return SimpleNamespace(
        name=name,
        isPercussionTrack=is_percussion,
        strings=list(range(n_strings)),
        measures=measures,
    )


def _make_song(*tracks):
    return SimpleNamespace(tracks=list(tracks))


class TestSelectGuitarTrack:
    """Selection must exclude percussion and prefer guitar-named tracks."""

    def test_prefers_guitar_named_track_over_more_notes(self):
        """A guitar-named 6-string track beats a flute with more notes."""
        reader = GPReader()
        song = _make_song(
            _make_track("Drums", True, 6, 300),       # percussion, huge note count
            _make_track("Flute", False, 6, 200),      # non-percussion, 6 strings
            _make_track("Lead Guitar", False, 6, 50), # guitar hint
        )
        selected = reader._select_guitar_track(song)
        assert selected.name == "Lead Guitar"

    def test_excludes_percussion_from_candidates(self):
        """A generic 6-string track is chosen over a busier drum track."""
        reader = GPReader()
        song = _make_song(
            _make_track("Drums", True, 6, 300),
            _make_track("Flute", False, 6, 100),
        )
        selected = reader._select_guitar_track(song)
        assert selected.name == "Flute"

    def test_falls_back_to_non_percussion_with_fewer_strings(self):
        """Without any ≥6-string non-percussion track, use the busiest one."""
        reader = GPReader()
        song = _make_song(
            _make_track("Drums", True, 6, 300),
            _make_track("Bass", False, 4, 100),
        )
        selected = reader._select_guitar_track(song)
        assert selected.name == "Bass"

    def test_prefers_six_strings_within_same_tier(self):
        """Among non-percussion tracks without guitar hints, prefer ≥6 strings."""
        reader = GPReader()
        song = _make_song(
            _make_track("Flute", False, 6, 100),
            _make_track("Piano", False, 5, 200),
        )
        selected = reader._select_guitar_track(song)
        assert selected.name == "Flute"

    def test_raises_when_only_percussion_tracks(self):
        """A file with only drum tracks is rejected, not silently misread."""
        reader = GPReader()
        song = _make_song(
            _make_track("Drums", True, 6, 300),
        )
        with pytest.raises(ValueError):
            reader._select_guitar_track(song)


@pytest.mark.skipif(not REFERENCE_ZIP.exists(), reason="Reference zip not available")
def test_real_drum_track_not_selected():
    """Regression: a guitar song must not pick its Drums track.

    The X-Japan "Art of Life" file has a drum track with more notes than the
    guitar tracks; its percussion pitches were previously read as frets.
    """
    zf = zipfile.ZipFile(str(REFERENCE_ZIP), "r")
    target = next(
        (n for n in zf.namelist() if "Art of Life" in n and n.endswith(".gp3")),
        None,
    )
    if target is None:
        pytest.skip("Art of Life.gp3 not in reference zip")

    with tempfile.NamedTemporaryFile(suffix=".gp3", delete=False) as tmp:
        tmp.write(zf.read(target))
        tmp_path = Path(tmp.name)
    try:
        reader = GPReader()
        tab = reader.parse(tmp_path)
        assert tab.track_name != "Drums"
        for note in tab.notes:
            assert note.fret <= 24, f"Impossible fret {note.fret} on {tab.track_name}"
    finally:
        tmp_path.unlink(missing_ok=True)


@pytest.fixture
def sample_gp5():
    """Extract a sample GP5 file from the reference zip."""
    if not REFERENCE_ZIP.exists():
        pytest.skip("Reference zip not available")
    zf = zipfile.ZipFile(str(REFERENCE_ZIP), "r")
    gp5_files = [n for n in zf.namelist() if n.endswith(".gp5")]
    if not gp5_files:
        pytest.skip("No GP5 files in reference zip")
    with tempfile.NamedTemporaryFile(suffix=".gp5", delete=False) as tmp:
        tmp.write(zf.read(gp5_files[0]))
        tmp_path = Path(tmp.name)
    yield tmp_path
    tmp_path.unlink(missing_ok=True)


def test_parse_returns_ground_truth_tab(sample_gp5):
    """GPReader.parse() returns a GroundTruthTab with notes."""
    reader = GPReader()
    tab = reader.parse(sample_gp5)

    assert tab.title  # Non-empty title
    assert len(tab.notes) > 0
    assert tab.tempo_bpm > 0
    assert len(tab.tuning_pitches) == 6  # Standard guitar
    assert tab.measure_count > 0


def test_notes_have_valid_string_fret(sample_gp5):
    """All ground truth notes have valid string (1-6) and fret (>=0)."""
    reader = GPReader()
    tab = reader.parse(sample_gp5)

    for note in tab.notes:
        assert 1 <= note.string <= 6, f"String {note.string} out of range"
        assert note.fret >= 0, f"Fret {note.fret} negative"
        assert note.pitch > 0, f"Pitch {note.pitch} invalid"
        assert note.measure_number >= 1
        assert note.beat_in_measure >= 0


def test_hand_position_computed(sample_gp5):
    """Hand positions are computed (fretted = max(1, fret), open = previous)."""
    reader = GPReader()
    tab = reader.parse(sample_gp5)

    for note in tab.notes:
        assert note.hand_position >= 1, f"Hand position {note.hand_position} < 1"
        if note.fret > 0:
            assert note.hand_position == max(1, note.fret)


def test_tie_notes_skipped(sample_gp5):
    """Tie notes are not included in the ground truth."""
    reader = GPReader()
    tab = reader.parse(sample_gp5)

    for note in tab.notes:
        assert not note.is_tie, "Tie note should be skipped"


def test_style_label_inferred(sample_gp5):
    """Style label is inferred from the file path."""
    reader = GPReader()
    tab = reader.parse(sample_gp5)
    assert tab.style_label  # Non-empty
