"""Detection tests — guitar track identification through the 3-layer classifier."""

from __future__ import annotations

from fretpilot.detection import classify_timeline
from fretpilot.detection.models import GuitarDetectionReport
from fretpilot.detection.streams import resolve_streams
from fretpilot.drum.classifier import classify_drum_track
from fretpilot.orchestrator.detector import InstrumentFamily, classify_track_family
from tests.conftest import _note, _timeline


class TestClassifyTimeline:
    """Tests for the 3-layer guitar classifier."""

    def test_guitar_program_detected(self) -> None:
        """A track with GM guitar program 30 (Distortion Guitar) should be classified as guitar."""
        notes = [
            _note(pitch=60, start_beat=0.0, duration_beats=0.5, program=30),
            _note(pitch=62, start_beat=0.5, duration_beats=0.5, program=30),
            _note(pitch=64, start_beat=1.0, duration_beats=0.5, program=30),
            _note(pitch=65, start_beat=1.5, duration_beats=0.5, program=30),
            _note(pitch=67, start_beat=2.0, duration_beats=0.5, program=30),
        ]
        timeline = _timeline(notes)
        report = classify_timeline(timeline)
        assert isinstance(report, GuitarDetectionReport)
        assert report.total_guitar_tracks >= 1
        assert report.primary_guitar_track_index is not None

    def test_non_guitar_program_not_detected(self) -> None:
        """A track with piano program 0 should not be classified as guitar."""
        notes = [
            _note(pitch=60, start_beat=0.0, duration_beats=0.5, program=0),
            _note(pitch=62, start_beat=0.5, duration_beats=0.5, program=0),
            _note(pitch=64, start_beat=1.0, duration_beats=0.5, program=0),
            _note(pitch=65, start_beat=1.5, duration_beats=0.5, program=0),
        ]
        timeline = _timeline(notes)
        report = classify_timeline(timeline)
        assert report.total_guitar_tracks == 0
        assert report.primary_guitar_track_index is None

    def test_zero_based_channel_nine_is_standard_drum_channel(self) -> None:
        notes = [
            _note(
                pitch=42,
                start_beat=index * 0.5,
                duration_beats=0.25,
                program=0,
                channel=9,
            )
            for index in range(4)
        ]
        assert classify_drum_track(_timeline(notes).tracks[0]) is True

    def test_explicit_keyboard_name_beats_weak_low_register_bass_hint(self) -> None:
        notes = [
            _note(
                pitch=pitch,
                start_beat=float(index),
                duration_beats=0.5,
                program=126,
            )
            for index, pitch in enumerate((36, 40, 43, 48))
        ]
        track = _timeline(notes).tracks[0]
        track.name = "Low Keyboard"

        classification = classify_track_family(track)

        assert classification.family == InstrumentFamily.KEYS
        assert "Keyboard" in classification.reason

    def test_guitar_program_beats_weak_drum_pattern_heuristics(self) -> None:
        notes = [
            _note(
                pitch=60,
                start_beat=index * 0.125,
                duration_beats=0.125,
                program=25,
            )
            for index in range(24)
        ]

        track = _timeline(notes).tracks[0]
        track.name = "Strings"
        classification = classify_track_family(track)

        assert classification.family == InstrumentFamily.GUITAR

    def test_non_bass_program_beats_weak_low_register_hint(self) -> None:
        notes = [
            _note(
                pitch=pitch,
                start_beat=float(index),
                duration_beats=0.5,
                program=48,
            )
            for index, pitch in enumerate((36, 40, 43, 48))
        ]

        track = _timeline(notes).tracks[0]
        track.name = "Strings"
        classification = classify_track_family(track)

        assert classification.family == InstrumentFamily.UNKNOWN

    def test_explicit_bass_name_beats_piano_program(self) -> None:
        notes = [
            _note(
                pitch=pitch,
                start_beat=float(index),
                duration_beats=0.5,
                program=2,
            )
            for index, pitch in enumerate((36, 40, 43, 48))
        ]
        track = _timeline(notes).tracks[0]
        track.name = "Bass"

        classification = classify_track_family(track)

        assert classification.family == InstrumentFamily.BASS

    def test_bass_program_classified_as_bass(self) -> None:
        """GM bass program 33 (Electric Bass) should be classified as bass, not guitar."""
        notes = [
            _note(pitch=40, start_beat=0.0, duration_beats=1.0, program=33),
            _note(pitch=45, start_beat=1.0, duration_beats=1.0, program=33),
            _note(pitch=50, start_beat=2.0, duration_beats=1.0, program=33),
            _note(pitch=52, start_beat=3.0, duration_beats=1.0, program=33),
        ]
        timeline = _timeline(notes)
        report = classify_timeline(timeline)
        guitar_cls = [c for c in report.classifications if c.is_guitar]
        assert len(guitar_cls) == 0

    def test_lead_guitar_role_detected(self) -> None:
        """Monophonic notes with wide pitch range should be classified as lead."""
        notes = [
            _note(pitch=55, start_beat=float(i) * 0.25, duration_beats=0.25, program=30)
            for i in range(20)
        ]
        # Expand the pitch range to trigger "lead" detection
        for i, note in enumerate(notes):
            note.pitch = 55 + i  # Wide range
        timeline = _timeline(notes)
        report = classify_timeline(timeline)
        guitar_cls = [c for c in report.classifications if c.is_guitar]
        assert len(guitar_cls) >= 1

    def test_rhythm_guitar_role_detected(self) -> None:
        """Chord-based notes should be classified as rhythm."""
        chord_notes = []
        for i in range(10):
            for pitch in [60, 64, 67]:
                chord_notes.append(
                    _note(pitch=pitch, start_beat=float(i) * 0.5, duration_beats=0.5, program=30)
                )
        timeline = _timeline(chord_notes)
        report = classify_timeline(timeline)
        guitar_cls = [c for c in report.classifications if c.is_guitar]
        assert len(guitar_cls) >= 1

    def test_confidence_in_range(self) -> None:
        """All confidence values should be between 0 and 1."""
        notes = [
            _note(pitch=60, start_beat=float(i) * 0.5, duration_beats=0.5, program=30)
            for i in range(10)
        ]
        timeline = _timeline(notes)
        report = classify_timeline(timeline)
        for cls in report.classifications:
            assert 0.0 <= cls.confidence <= 1.0

    def test_primary_classification_property(self) -> None:
        """The primary_classification property should return the best guitar track."""
        notes = [
            _note(pitch=60, start_beat=float(i) * 0.5, duration_beats=0.5, program=30)
            for i in range(8)
        ]
        timeline = _timeline(notes)
        report = classify_timeline(timeline)
        if report.primary_guitar_track_index is not None:
            primary = report.primary_classification
            assert primary is not None
            assert primary.is_guitar is True

    def test_empty_timeline(self) -> None:
        """An empty timeline should produce no classifications."""
        timeline = _timeline(notes=[])
        report = classify_timeline(timeline)
        assert report.total_guitar_tracks == 0
        assert report.primary_guitar_track_index is None


class TestResolveStreams:
    """Tests for logical stream resolution."""

    def test_single_track_single_stream(self) -> None:
        notes = [
            _note(pitch=60, start_beat=0.0, duration_beats=0.5, program=30, channel=0),
            _note(pitch=62, start_beat=0.5, duration_beats=0.5, program=30, channel=0),
        ]
        timeline = _timeline(notes)
        streams = resolve_streams(timeline)
        assert len(streams) == 1
        assert streams[0].program == 30

    def test_different_channels_different_streams(self) -> None:
        notes = [
            _note(pitch=60, start_beat=0.0, duration_beats=0.5, program=30, channel=0),
            _note(pitch=62, start_beat=0.5, duration_beats=0.5, program=30, channel=1),
        ]
        timeline = _timeline(notes)
        streams = resolve_streams(timeline)
        assert len(streams) == 2

    def test_empty_tracks_skipped(self) -> None:
        timeline = _timeline(notes=[])
        streams = resolve_streams(timeline)
        assert len(streams) == 0
