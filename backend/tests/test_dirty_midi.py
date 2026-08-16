"""Dirty Suno MIDI tests — tolerant parse, name-based detection, cleanup.

These tests exercise the real ``SoD Lead Electric Guitar.mid`` fixture (a Suno
stem export) which crashes a stock ``mido`` parser with an invalid key
signature, mislabels every channel as piano (program 0), and scatters 2269
notes across 12 channels with duplicates, micro-notes, velocity spikes, and
overlapping onsets.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fretpilot.detection import classify_timeline
from fretpilot.detection.classifier import _layer0_track_name
from fretpilot.detection.models import TrackClassification
from fretpilot.detection.streams import resolve_streams
from fretpilot.engine.cleanup import cleanup_streams
from fretpilot.midi.parser import load_midi

_FIXTURE = Path(__file__).parent / "fixtures" / "sod_lead.mid"


class TestDirtyMidiParsing:
    """The dirty fixture must parse without crashing and keep every note."""

    def test_load_dirty_midi_no_crash(self) -> None:
        timeline = load_midi(_FIXTURE)
        # 2269 notes survive despite the invalid key signature and 86 tempos.
        assert timeline.note_count == 2269
        assert len(timeline.tracks) == 13

        codes = {d.code for d in timeline.diagnostics}
        assert "invalid_key_signature" in codes
        # The invalid key signature is downgraded to a warning, never an error.
        assert all(d.level != "error" for d in timeline.diagnostics)

    def test_load_dirty_midi_tempos(self) -> None:
        timeline = load_midi(_FIXTURE)
        # Suno writes the same 126 BPM tempo 86 times; all are preserved.
        assert len(timeline.tempo_events) == 86
        assert abs(timeline.tempo_events[0].bpm - 126.0) < 0.01


class TestDirtyMidiDetection:
    """Track-name detection must override the (wrong) piano program."""

    def test_detect_guitar_from_track_name(self) -> None:
        timeline = load_midi(_FIXTURE)
        report = classify_timeline(timeline)

        assert report.primary_guitar_track_index is not None
        primary = report.primary_classification
        assert primary is not None
        # Program is 0 (piano) everywhere, but the track name says guitar.
        assert primary.instrument_family == "guitar"
        assert primary.is_guitar is True
        assert primary.guitar_role == "lead"
        assert "guitar" in primary.track_name.lower()
        assert primary.confidence >= 0.9


class TestLayer0KeywordOrder:
    """Layer 0 track-name matching must order compound keywords correctly."""

    @pytest.mark.parametrize(
        ("name", "expected_family"),
        [
            ("Bass Guitar", "bass"),
            ("Synth Bass", "synth"),
            ("drums", "drums"),
        ],
    )
    def test_track_name_keyword_order(
        self, name: str, expected_family: str
    ) -> None:
        family, _role = _layer0_track_name(name)
        assert family == expected_family


class TestClassificationOverride:
    """The classification result must be user-overridable data."""

    def test_track_classification_override(self) -> None:
        cls = TrackClassification(
            track_index=0,
            track_name="Track 1",
            instrument_family="piano",
            program=0,
            is_guitar=False,
            guitar_role="unknown",
            confidence=0.5,
            reason="auto",
        )
        cls.apply_override("guitar", "lead")

        assert cls.user_override is True
        assert cls.overridden_family == "guitar"
        assert cls.overridden_role == "lead"
        assert cls.instrument_family == "guitar"
        assert cls.is_guitar is True
        assert cls.guitar_role == "lead"
        assert cls.confidence == 1.0

    def test_track_classification_override_bass_defaults_role(self) -> None:
        cls = TrackClassification(
            track_index=0,
            track_name="Track 1",
            instrument_family="guitar",
            program=30,
            is_guitar=True,
            guitar_role="lead",
            confidence=0.9,
            reason="auto",
        )
        cls.apply_override("bass")

        assert cls.is_guitar is False
        assert cls.instrument_family == "bass"
        assert cls.guitar_role == "bass"


class TestDirtyMidiCleanup:
    """Cleanup must deduplicate streams and remove micro-notes traceably."""

    def test_cleanup_reduces_notes(self) -> None:
        timeline = load_midi(_FIXTURE)
        streams = resolve_streams(timeline)
        original = timeline.note_count

        result = cleanup_streams(streams)

        # Duplicate channels + micro-notes are removed: 2269 -> ~2153.
        assert result.note_count < original
        assert result.note_count <= 2200
        assert result.removed_note_count >= 100

        # Velocity spike (~31%) and overlap (~39%) are reported, not destroyed.
        assert result.velocity is not None
        assert 0.25 <= result.velocity.max_velocity_ratio <= 0.4
        assert result.overlap is not None
        assert 0.3 <= result.overlap.overlap_ratio <= 0.5

        kinds = {a.kind for a in result.actions}
        assert "merge_stream" in kinds
        assert "remove_micro_note" in kinds

    def test_cleanup_actions_are_traceable(self) -> None:
        timeline = load_midi(_FIXTURE)
        streams = resolve_streams(timeline)

        result = cleanup_streams(streams)

        # Every removal carries identifying detail, never a silent drop.
        merge_actions = [a for a in result.actions if a.kind == "merge_stream"]
        assert merge_actions and merge_actions[0].merged_stream_ids
        micro_actions = [
            a for a in result.actions if a.kind == "remove_micro_note"
        ]
        assert micro_actions
        assert sum(a.removed_note_count for a in micro_actions) > 0
        # Micro-note removals record the individual notes that were dropped.
        assert all(a.notes for a in micro_actions)
