"""Tests for the statistics extractor (P1-1).

Verifies open_string_rate, hand_position_distribution, string_distribution,
chord shapes, string skip, note overlap, staccato rate, and fret distribution.
"""

from __future__ import annotations

from fretpilot.elearning.models import GroundTruthNote, GroundTruthTab
from fretpilot.elearning.stats_extractor import StatsExtractor


# ─── Helpers ───


def _note(
    measure: int, beat: float, pitch: int, string: int, fret: int,
    hp: int = 1, dur: float = 1.0,
) -> GroundTruthNote:
    return GroundTruthNote(
        measure_number=measure,
        beat_in_measure=beat,
        pitch=pitch,
        string=string,
        fret=fret,
        hand_position=hp,
        duration_beats=dur,
        is_tie=False,
        velocity=80,
    )


def _tab(notes: list[GroundTruthNote], style: str = "rock", path: str = "song.gp5") -> GroundTruthTab:
    return GroundTruthTab(
        file_path=path,
        title="test",
        style_label=style,
        tempo_bpm=120.0,
        time_signature=(4, 4),
        tuning_pitches=[40, 45, 50, 55, 59, 64],
        notes=notes,
        track_name="Guitar",
    )


# ─── Tests ───


class TestOpenStringRate:
    """Verify open_string_rate computation."""

    def test_all_open(self):
        notes = [_note(1, 0.0, 64, 1, 0), _note(1, 1.0, 59, 2, 0)]
        extractor = StatsExtractor()
        rate = extractor._compute_open_string_rate(notes)
        assert rate == 1.0

    def test_no_open(self):
        notes = [_note(1, 0.0, 64, 1, 5), _note(1, 1.0, 59, 2, 3)]
        extractor = StatsExtractor()
        rate = extractor._compute_open_string_rate(notes)
        assert rate == 0.0

    def test_half_open(self):
        notes = [
            _note(1, 0.0, 64, 1, 0),
            _note(1, 1.0, 65, 1, 1),
        ]
        extractor = StatsExtractor()
        rate = extractor._compute_open_string_rate(notes)
        assert rate == 0.5

    def test_empty(self):
        extractor = StatsExtractor()
        assert extractor._compute_open_string_rate([]) == 0.0


class TestHandPositionDist:
    """Verify hand_position_distribution."""

    def test_distribution(self):
        notes = [
            _note(1, 0.0, 64, 1, 5, hp=5),
            _note(1, 1.0, 65, 1, 5, hp=5),
            _note(1, 2.0, 67, 1, 7, hp=7),
        ]
        extractor = StatsExtractor()
        dist = extractor._compute_hand_position_dist(notes)
        assert dist[5] == round(2 / 3, 6)
        assert dist[7] == round(1 / 3, 6)

    def test_empty(self):
        extractor = StatsExtractor()
        assert extractor._compute_hand_position_dist([]) == {}


class TestStringDistribution:
    """Verify string_distribution."""

    def test_distribution(self):
        notes = [
            _note(1, 0.0, 64, 1, 0),
            _note(1, 1.0, 59, 2, 0),
            _note(1, 2.0, 64, 1, 0),
        ]
        extractor = StatsExtractor()
        dist = extractor._compute_string_distribution(notes)
        assert dist[1] == round(2 / 3, 6)
        assert dist[2] == round(1 / 3, 6)


class TestChordShapes:
    """Verify chord shape extraction."""

    def test_chord_detected(self):
        """Two notes at the same onset form a chord."""
        notes = [
            _note(1, 0.0, 60, 6, 1),
            _note(1, 0.0, 64, 4, 2),
        ]
        extractor = StatsExtractor()
        shapes = extractor._compute_chord_shapes(notes)
        assert len(shapes) == 1
        # Key should be sorted by string: s4f2,s6f1
        assert "s4f2,s6f1" in shapes

    def test_single_notes_not_chords(self):
        """Single notes at different onsets are not chords."""
        notes = [
            _note(1, 0.0, 64, 1, 0),
            _note(1, 1.0, 65, 1, 1),
        ]
        extractor = StatsExtractor()
        shapes = extractor._compute_chord_shapes(notes)
        assert len(shapes) == 0

    def test_repeated_chord(self):
        """Same chord appearing twice → count = 2."""
        notes = [
            _note(1, 0.0, 60, 6, 1),
            _note(1, 0.0, 64, 4, 2),
            _note(1, 2.0, 60, 6, 1),
            _note(1, 2.0, 64, 4, 2),
        ]
        extractor = StatsExtractor()
        shapes = extractor._compute_chord_shapes(notes)
        assert len(shapes) == 1
        assert list(shapes.values())[0] == 2

    def test_duplicate_pairs_deduped(self):
        """A doubled note at an onset must not corrupt the shape key.

        Regression: GP files sometimes carry a duplicated note on the same
        string/fret at the same onset (tie artifacts).  These produced
        impossible keys like ``s2f0,s2f0``.
        """
        notes = [
            _note(1, 0.0, 60, 6, 1),
            _note(1, 0.0, 60, 6, 1),  # duplicate of the same (string, fret)
            _note(1, 0.0, 64, 4, 2),
        ]
        extractor = StatsExtractor()
        shapes = extractor._compute_chord_shapes(notes)
        assert len(shapes) == 1
        # The duplicate collapses → real chord shape only.
        assert "s6f1,s4f2" in shapes or "s4f2,s6f1" in shapes

    def test_all_duplicates_not_a_chord(self):
        """Onset with only duplicated notes → not a real chord → skipped."""
        notes = [
            _note(1, 0.0, 60, 6, 1),
            _note(1, 0.0, 60, 6, 1),
        ]
        extractor = StatsExtractor()
        shapes = extractor._compute_chord_shapes(notes)
        assert len(shapes) == 0


class TestAvgStringSkip:
    """Verify average string skip."""

    def test_no_skip(self):
        notes = [
            _note(1, 0.0, 64, 1, 0),
            _note(1, 1.0, 65, 1, 1),
            _note(1, 2.0, 67, 1, 3),
        ]
        extractor = StatsExtractor()
        skip = extractor._compute_avg_string_skip(notes)
        assert skip == 0.0

    def test_skip_of_1(self):
        notes = [
            _note(1, 0.0, 64, 1, 0),
            _note(1, 1.0, 59, 2, 0),
        ]
        extractor = StatsExtractor()
        skip = extractor._compute_avg_string_skip(notes)
        assert skip == 1.0

    def test_single_note(self):
        notes = [_note(1, 0.0, 64, 1, 0)]
        extractor = StatsExtractor()
        assert extractor._compute_avg_string_skip(notes) == 0.0


class TestNoteOverlap:
    """Verify note overlap rate."""

    def test_no_overlap(self):
        notes = [
            _note(1, 0.0, 64, 1, 0, dur=0.5),
            _note(1, 1.0, 65, 1, 1, dur=0.5),
        ]
        extractor = StatsExtractor()
        rate = extractor._compute_note_overlap_rate(notes)
        assert rate == 0.0

    def test_full_overlap(self):
        notes = [
            _note(1, 0.0, 64, 1, 0, dur=2.0),
            _note(1, 0.5, 65, 1, 1, dur=1.0),
        ]
        extractor = StatsExtractor()
        rate = extractor._compute_note_overlap_rate(notes)
        assert rate == 1.0


class TestStaccatoRate:
    """Verify staccato rate."""

    def test_all_staccato(self):
        notes = [
            _note(1, 0.0, 64, 1, 0, dur=0.1),
            _note(1, 0.5, 65, 1, 1, dur=0.2),
        ]
        extractor = StatsExtractor()
        rate = extractor._compute_staccato_rate(notes)
        assert rate == 1.0

    def test_no_staccato(self):
        notes = [
            _note(1, 0.0, 64, 1, 0, dur=1.0),
            _note(1, 1.0, 65, 1, 1, dur=2.0),
        ]
        extractor = StatsExtractor()
        rate = extractor._compute_staccato_rate(notes)
        assert rate == 0.0


class TestFretDistribution:
    """Verify fret distribution."""

    def test_distribution(self):
        notes = [
            _note(1, 0.0, 64, 1, 0),
            _note(1, 1.0, 65, 1, 1),
            _note(1, 2.0, 67, 1, 3),
            _note(1, 3.0, 69, 1, 5),
        ]
        extractor = StatsExtractor()
        dist = extractor._compute_fret_distribution(notes)
        assert dist[0] == 0.25
        assert dist[1] == 0.25
        assert dist[3] == 0.25
        assert dist[5] == 0.25


class TestExtractIntegration:
    """Verify the full extract() flow."""

    def test_extract_single_style(self):
        tabs = [
            _tab([_note(1, 0.0, 64, 1, 0), _note(1, 1.0, 65, 1, 5, hp=5)], style="rock"),
            _tab([_note(1, 0.0, 64, 1, 0), _note(1, 1.0, 65, 1, 7, hp=7)], style="rock"),
        ]
        extractor = StatsExtractor()
        result = extractor.extract(tabs)

        assert "rock" in result
        stats = result["rock"]
        assert stats.style_label == "rock"
        assert stats.sample_count == 2
        assert stats.total_notes == 4
        assert stats.open_string_rate == 0.5

    def test_extract_multiple_styles(self):
        tabs = [
            _tab([_note(1, 0.0, 64, 1, 0)], style="rock", path="r.gp5"),
            _tab([_note(1, 0.0, 64, 1, 5, hp=5)], style="pop", path="p.gp5"),
        ]
        extractor = StatsExtractor()
        result = extractor.extract(tabs)

        assert set(result.keys()) == {"rock", "pop"}
        assert result["rock"].open_string_rate == 1.0
        assert result["pop"].open_string_rate == 0.0

    def test_extract_empty_tabs(self):
        extractor = StatsExtractor()
        result = extractor.extract([])
        assert result == {}

    def test_extract_skips_style_with_no_notes(self):
        tabs = [_tab([], style="unknown")]
        extractor = StatsExtractor()
        result = extractor.extract(tabs)
        assert "unknown" not in result
