"""Tests for evaluation integration and stats/priors extraction."""

import pytest

from fretpilot.elearning.models import (
    GroundTruthNote,
    GroundTruthTab,
    StyleStats,
    DerivedPriors,
)
from fretpilot.elearning.stats_extractor import StatsExtractor
from fretpilot.elearning.priors_deriver import PriorsDeriver


def _make_tab(style, notes):
    return GroundTruthTab(
        f"test_{style}.gp5", f"Test {style}", style, 120, (4, 4),
        [40, 45, 50, 55, 59, 64], notes, "Track",
    )


def _make_note(measure, beat, pitch, string, fret, hp=1, dur=1.0):
    return GroundTruthNote(measure, beat, pitch, string, fret, hp, dur, False, 95)


class TestStatsExtractor:
    def test_open_string_rate(self):
        """Open string rate is correctly computed."""
        notes = [
            _make_note(1, 0, 64, 1, 0),  # open
            _make_note(1, 1, 65, 1, 1),  # fretted
            _make_note(1, 2, 67, 1, 3),  # fretted
            _make_note(1, 3, 64, 1, 0),  # open
        ]
        tab = _make_tab("rock", notes)
        extractor = StatsExtractor()
        stats = extractor.extract([tab])
        assert "rock" in stats
        assert stats["rock"].open_string_rate == 0.5  # 2/4

    def test_string_distribution(self):
        """String distribution covers all used strings."""
        notes = [
            _make_note(1, 0, 64, 1, 0),
            _make_note(1, 1, 59, 2, 0),
            _make_note(1, 2, 64, 1, 0),
        ]
        tab = _make_tab("pop", notes)
        extractor = StatsExtractor()
        stats = extractor.extract([tab])
        dist = stats["pop"].string_distribution
        assert dist[1] == pytest.approx(2/3)
        assert dist[2] == pytest.approx(1/3)

    def test_chord_shapes(self):
        """Chord shapes are detected for 2+ note onsets."""
        notes = [
            _make_note(1, 0, 64, 1, 0),
            _make_note(1, 0, 59, 2, 0),  # Same onset = chord
            _make_note(1, 1, 64, 1, 0),
            _make_note(1, 1, 59, 2, 0),  # Same shape again
        ]
        tab = _make_tab("rock", notes)
        extractor = StatsExtractor()
        stats = extractor.extract([tab])
        shapes = stats["rock"].chord_shape_top_k
        assert len(shapes) > 0
        # The shape "s1f0,s2f0" should appear twice
        assert "s1f0,s2f0" in shapes
        assert shapes["s1f0,s2f0"] == 2

    def test_staccato_rate(self):
        """Staccato rate counts notes with duration < 0.25 beat."""
        notes = [
            _make_note(1, 0, 64, 1, 0, dur=1.0),
            _make_note(1, 1, 65, 1, 1, dur=0.2),  # staccato
        ]
        tab = _make_tab("funk", notes)
        extractor = StatsExtractor()
        stats = extractor.extract([tab])
        assert stats["funk"].staccato_rate == 0.5

    def test_multiple_styles(self):
        """Multiple styles produce separate stats."""
        tab1 = _make_tab("rock", [_make_note(1, 0, 64, 1, 0)])
        tab2 = _make_tab("pop", [_make_note(1, 0, 60, 1, 0)])
        extractor = StatsExtractor()
        stats = extractor.extract([tab1, tab2])
        assert "rock" in stats
        assert "pop" in stats


class TestPriorsDeriver:
    def test_derive_returns_priors(self):
        """Derive produces DerivedPriors with valid payload."""
        notes = [
            _make_note(1, 0, 64, 1, 0),
            _make_note(1, 1, 65, 1, 1),
            _make_note(1, 2, 64, 1, 0),
        ]
        tabs = [_make_tab("rock", notes) for _ in range(5)]  # ≥ min samples
        extractor = StatsExtractor()
        stats = extractor.extract(tabs)

        deriver = PriorsDeriver()
        derived = deriver.derive(stats, {"rock": ["test.gp5"] * 5})

        assert len(derived) == 1
        assert derived[0].style_label == "rock"
        assert "open_string_bias" in derived[0].payload
        assert derived[0].payload["open_string_bias"] > 0
        assert "chord_shapes" in derived[0].payload

    def test_priors_clamped(self):
        """All scalar derived priors are within [0.3, 2.0]."""
        notes = [_make_note(1, 0, 64, 1, 0)]
        tabs = [_make_tab("metal", notes) for _ in range(5)]  # ≥ min samples
        extractor = StatsExtractor()
        stats = extractor.extract(tabs)

        deriver = PriorsDeriver()
        derived = deriver.derive(stats, {"metal": ["test.gp5"] * 5})

        for key, value in derived[0].payload.items():
            if isinstance(value, dict):
                continue  # chord_shapes is a nested mapping, not a scalar prior
            assert 0.3 <= value <= 2.0, f"{key}={value} out of range"

    def test_provenance_empirical(self):
        """Derived priors use statistical_mapping method."""
        notes = [_make_note(1, 0, 64, 1, 0)]
        tabs = [_make_tab("rock", notes) for _ in range(5)]  # ≥ min samples
        extractor = StatsExtractor()
        stats = extractor.extract(tabs)

        deriver = PriorsDeriver()
        derived = deriver.derive(stats, {"rock": ["test.gp5"] * 5})

        assert derived[0].derivation_method == "statistical_mapping"
        assert derived[0].knowledge_id == "kb2-rock-lead-performance"

    def test_confidence_increases_with_samples(self):
        """More samples → higher confidence."""
        # 5 samples (minimum for derivation)
        tab1 = _make_tab("rock", [_make_note(1, 0, 64, 1, 0)])
        extractor = StatsExtractor()
        stats1 = extractor.extract([tab1] * 5)
        deriver = PriorsDeriver()
        d1 = deriver.derive(stats1, {"rock": ["a"] * 5})[0]

        # 50 samples
        tabs = [_make_tab("rock", [_make_note(1, i, 64, 1, 0)]) for i in range(50)]
        stats50 = extractor.extract(tabs)
        d50 = deriver.derive(stats50, {"rock": [f"f{i}" for i in range(50)]})[0]

        assert d50.confidence > d1.confidence
