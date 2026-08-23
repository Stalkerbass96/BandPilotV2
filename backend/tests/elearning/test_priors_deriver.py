"""Tests for the priors deriver (P1-2).

Verifies that empirical priors are correctly derived from StyleStats,
clamped to [0.3, 2.0], tagged with source_type="empirical", and have
appropriate confidence values.
"""

from __future__ import annotations

from fretpilot.elearning.models import StyleStats
from fretpilot.elearning.priors_deriver import PriorsDeriver

# ─── Helpers ───


def _make_stats(
    style: str = "rock",
    samples: int = 10,
    notes: int = 100,
    open_rate: float = 0.15,
    skip: float = 1.0,
    overlap: float = 0.5,
    staccato: float = 0.15,
) -> StyleStats:
    return StyleStats(
        style_label=style,
        sample_count=samples,
        total_notes=notes,
        open_string_rate=open_rate,
        hand_position_distribution={1: 0.5, 5: 0.5},
        string_distribution={1: 0.5, 2: 0.5},
        avg_string_skip=skip,
        chord_shape_top_k={"s1f0,s2f2": 5, "s1f0,s2f3": 3},
        note_overlap_rate=overlap,
        staccato_rate=staccato,
        fret_distribution={0: 0.15, 2: 0.3, 5: 0.55},
    )


# ─── Tests ───


class TestDeriveBasic:
    """Verify basic derive() functionality."""

    def test_derive_returns_list(self):
        stats = {"rock": _make_stats("rock")}
        deriver = PriorsDeriver()
        result = deriver.derive(stats, {"rock": ["song1.gp5"]})
        assert isinstance(result, list)
        assert len(result) == 1

    def test_derive_correct_kb_id(self):
        stats = {"rock": _make_stats("rock")}
        deriver = PriorsDeriver()
        result = deriver.derive(stats, {"rock": ["song1.gp5"]})
        assert result[0].knowledge_id == "kb2-rock-lead-performance"

    def test_derive_all_styles(self):
        stats = {
            "metal": _make_stats("metal"),
            "rock": _make_stats("rock"),
            "pop": _make_stats("pop"),
            "funk": _make_stats("funk"),
        }
        deriver = PriorsDeriver()
        result = deriver.derive(stats, {s: [f"{s}.gp5"] for s in stats})
        ids = [p.knowledge_id for p in result]
        assert "kb2-metal-performance" in ids
        assert "kb2-rock-lead-performance" in ids
        assert "kb2-pop-performance" in ids
        assert "kb2-funk-performance" in ids

    def test_unknown_style_skipped(self):
        stats = {"unknown": _make_stats("unknown")}
        deriver = PriorsDeriver()
        result = deriver.derive(stats, {"unknown": ["song.gp5"]})
        assert len(result) == 0

    def test_empty_stats(self):
        deriver = PriorsDeriver()
        result = deriver.derive({}, {})
        assert result == []

    def test_undersampled_style_skipped(self):
        """Styles with too few samples must not overwrite hand-authored KB."""
        stats = {
            "metal": _make_stats("metal", samples=1),
            "rock": _make_stats("rock", samples=10),
        }
        deriver = PriorsDeriver()
        result = deriver.derive(stats, {s: [f"{s}.gp5"] for s in stats})
        assert [p.style_label for p in result] == ["rock"]


class TestClamping:
    """Verify all priors are clamped to [0.3, 2.0]."""

    def test_all_priors_in_range(self):
        stats = {
            "rock": _make_stats("rock", open_rate=0.0, skip=10.0, overlap=1.0, staccato=1.0),
        }
        deriver = PriorsDeriver()
        result = deriver.derive(stats, {"rock": ["s.gp5"]})
        payload = result[0].payload
        for key, value in payload.items():
            if isinstance(value, dict):
                continue  # chord_shapes is a nested mapping, not a scalar prior
            assert 0.3 <= value <= 2.0, f"{key}={value} out of range"

    def test_open_string_bias_clamped_high(self):
        """Very high open_string_rate → clamped to 2.0."""
        stats = {"rock": _make_stats("rock", open_rate=0.9)}
        deriver = PriorsDeriver()
        result = deriver.derive(stats, {"rock": ["s.gp5"]})
        assert result[0].payload["open_string_bias"] == 2.0

    def test_open_string_bias_clamped_low(self):
        """Zero open_string_rate → clamped to 0.3."""
        stats = {"rock": _make_stats("rock", open_rate=0.0)}
        deriver = PriorsDeriver()
        result = deriver.derive(stats, {"rock": ["s.gp5"]})
        assert result[0].payload["open_string_bias"] == 0.3

    def test_open_string_bias_neutral(self):
        """15% open_string_rate → ratio = 1.0."""
        stats = {"rock": _make_stats("rock", open_rate=0.15)}
        deriver = PriorsDeriver()
        result = deriver.derive(stats, {"rock": ["s.gp5"]})
        assert abs(result[0].payload["open_string_bias"] - 1.0) < 0.001


class TestPayloadKeys:
    """Verify the payload contains all expected prior keys."""

    def test_payload_has_all_keys(self):
        stats = {"rock": _make_stats("rock")}
        deriver = PriorsDeriver()
        result = deriver.derive(stats, {"rock": ["s.gp5"]})
        payload = result[0].payload
        expected_keys = {
            "open_string_bias",
            "hand_position_stability",
            "shape_reuse",
            "note_overlap",
            "staccato",
            "string_skip_penalty",
            "chord_shapes",
        }
        assert set(payload.keys()) == expected_keys

    def test_payload_contains_top_chord_shapes(self):
        """The empirical top-K chord shapes must be embedded in the payload."""
        stats = {"rock": _make_stats("rock")}
        deriver = PriorsDeriver()
        result = deriver.derive(stats, {"rock": ["s.gp5"]})
        chord_shapes = result[0].payload["chord_shapes"]
        assert isinstance(chord_shapes, dict)
        # _make_stats uses {"s1f0,s2f2": 5, "s1f0,s2f3": 3}; both fit in top-5.
        assert chord_shapes == {"s1f0,s2f2": 5, "s1f0,s2f3": 3}

    def test_payload_chord_shapes_limited_to_top_5(self):
        """At most 5 chord shapes are stored in the payload."""
        from dataclasses import replace

        many_shapes = {f"s1f{i}": 10 - i for i in range(10)}
        stats = {"rock": replace(_make_stats("rock"), chord_shape_top_k=many_shapes)}
        deriver = PriorsDeriver()
        result = deriver.derive(stats, {"rock": ["s.gp5"]})
        assert len(result[0].payload["chord_shapes"]) <= 5


class TestProvenanceAndConfidence:
    """Verify provenance and confidence."""

    def test_source_ids_recorded(self):
        stats = {"rock": _make_stats("rock")}
        deriver = PriorsDeriver()
        result = deriver.derive(stats, {"rock": ["a.gp5", "b.gp5", "c.gp5"]})
        assert set(result[0].source_ids) == {"a.gp5", "b.gp5", "c.gp5"}

    def test_derivation_method(self):
        stats = {"rock": _make_stats("rock")}
        deriver = PriorsDeriver()
        result = deriver.derive(stats, {"rock": ["a.gp5"]})
        assert result[0].derivation_method == "statistical_mapping"

    def test_stats_snapshot_populated(self):
        stats = {"rock": _make_stats("rock")}
        deriver = PriorsDeriver()
        result = deriver.derive(stats, {"rock": ["a.gp5"]})
        snap = result[0].stats_snapshot
        assert "open_string_rate" in snap
        assert "sample_count" in snap
        assert snap["sample_count"] == 10

    def test_confidence_increases_with_samples(self):
        """More samples → higher confidence."""
        deriver = PriorsDeriver()
        low = deriver._compute_confidence(1, 10)
        high = deriver._compute_confidence(20, 200)
        assert high > low

    def test_confidence_zero_for_no_data(self):
        deriver = PriorsDeriver()
        assert deriver._compute_confidence(0, 0) == 0.0

    def test_confidence_max_1(self):
        deriver = PriorsDeriver()
        conf = deriver._compute_confidence(100, 1000)
        assert conf <= 1.0


class TestIndividualPriors:
    """Verify individual prior derivation formulas."""

    def test_note_overlap_uses_rate_directly(self):
        """note_overlap = clamp(rate, 0.3, 2.0)."""
        deriver = PriorsDeriver()
        stats = _make_stats("rock", overlap=0.7)
        val = deriver._derive_note_overlap(stats)
        assert val == 0.7

    def test_string_skip_penalty(self):
        """string_skip_penalty = clamp(1 + skip * 0.15, 0.3, 2.0)."""
        deriver = PriorsDeriver()
        stats = _make_stats("rock", skip=2.0)
        val = deriver._derive_string_skip_penalty(stats)
        # 1 + 2.0 * 0.15 = 1.3
        assert abs(val - 1.3) < 0.001

    def test_staccato_neutral(self):
        """staccato at baseline 0.15 → ratio = 1.0."""
        deriver = PriorsDeriver()
        stats = _make_stats("rock", staccato=0.15)
        val = deriver._derive_staccato(stats)
        assert abs(val - 1.0) < 0.001
