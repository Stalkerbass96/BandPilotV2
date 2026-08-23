"""Tests for the shadow rewrite feature — LLM note-level decision wiring.

Tests cover:
1. build_note_summaries — suspicious note prioritization, cap, tuning range
2. apply_rewrite_decisions — delete, transpose, mixed, index ordering
3. validate_decisions — bounds, limits, invalid operations
4. End-to-end with mock advisor — track modified, transformations recorded
5. Degraded mode — no rewrites when advisor is None
"""

from __future__ import annotations

from fretpilot.ai.advisor import (
    ShadowRewriteAdvisor,
    apply_rewrite_decisions,
    build_note_summaries,
    build_policy,
    extract_features,
    validate_decisions,
)
from fretpilot.ai.models import (
    AIProviderError,
    RewriteDecision,
    RewriteRequest,
    RewriteResponse,
    ShadowRewritePolicy,
    TrackFeatures,
)
from fretpilot.knowledge.tunings import TuningRegistry
from fretpilot.midi.models import NormalizedNote, NormalizedTrack
from tests.conftest import _note

# ─── Helpers ───


def _make_track(notes: list[NormalizedNote]) -> NormalizedTrack:
    return NormalizedTrack(
        index=0,
        name="Guitar",
        notes=notes,
        instrument_name="Guitar",
        program=30,
    )


def _make_features(note_count: int = 10) -> TrackFeatures:
    return TrackFeatures(
        note_count=note_count,
        pitch_min=40,
        pitch_max=76,
        pitch_range_semitones=36,
        mean_velocity=80.0,
        mean_duration_beats=0.5,
        short_note_ratio=0.3,
        chord_onset_ratio=0.2,
        mean_polyphony=1.5,
        low_register_ratio=0.3,
        repeated_pitch_ratio=0.1,
    )


class _RewriteMockAdvisor:
    """Mock advisor that returns specific rewrite decisions."""

    def __init__(self, decisions: list[RewriteDecision]) -> None:
        from fretpilot.ai.models import AIProviderIdentity

        self.identity = AIProviderIdentity(provider="mock", model="mock-rewrite")
        self._decisions = decisions

    def infer_style(self, features: TrackFeatures) -> str:
        return "rock"

    def propose_rewrite(self, request: RewriteRequest) -> RewriteResponse:
        return RewriteResponse(decisions=list(self._decisions))


# ─── build_note_summaries tests ───


class TestBuildNoteSummaries:
    """Tests for build_note_summaries()."""

    def test_empty_track(self) -> None:
        track = _make_track([])
        assert build_note_summaries(track) == []

    def test_in_range_notes(self) -> None:
        """Normal notes are included with in_tuning_range=True."""
        track = _make_track([
            _note(pitch=60, start_beat=0.0, duration_beats=0.5),
            _note(pitch=64, start_beat=0.5, duration_beats=0.5),
        ])
        summaries = build_note_summaries(track)
        assert len(summaries) == 2
        for s in summaries:
            assert s["in_tuning_range"] is True

    def test_out_of_range_prioritized(self) -> None:
        """Out-of-range notes should appear before in-range notes."""
        track = _make_track([
            _note(pitch=60, start_beat=0.0, duration_beats=0.5),   # in range
            _note(pitch=20, start_beat=0.5, duration_beats=0.5),   # out of range
            _note(pitch=64, start_beat=1.0, duration_beats=0.5),   # in range
            _note(pitch=100, start_beat=1.5, duration_beats=0.5),  # out of range
        ])
        tuning = TuningRegistry.default().get("standard_6")
        summaries = build_note_summaries(track, tuning)
        # First two should be the out-of-range notes
        assert summaries[0]["in_tuning_range"] is False
        assert summaries[1]["in_tuning_range"] is False
        # Last two should be in-range
        assert summaries[2]["in_tuning_range"] is True
        assert summaries[3]["in_tuning_range"] is True

    def test_short_notes_prioritized(self) -> None:
        """Very short notes (< 1/64) should be treated as suspicious."""
        track = _make_track([
            _note(pitch=60, start_beat=0.0, duration_beats=0.5),    # normal
            _note(pitch=60, start_beat=0.5, duration_beats=0.03),   # suspicious (short)
        ])
        summaries = build_note_summaries(track)
        # Short note should come first
        assert summaries[0]["duration_beats"] == 0.03
        assert summaries[1]["duration_beats"] == 0.5

    def test_velocity_zero_prioritized(self) -> None:
        """Velocity 0 notes should be treated as suspicious."""
        track = _make_track([
            _note(pitch=60, start_beat=0.0, duration_beats=0.5, velocity=80),
            _note(pitch=60, start_beat=0.5, duration_beats=0.5, velocity=0),
        ])
        summaries = build_note_summaries(track)
        # Velocity 0 note should come first
        assert summaries[0]["velocity"] == 0
        assert summaries[1]["velocity"] == 80

    def test_max_summaries_cap(self) -> None:
        """Should cap at max_summaries."""
        notes = [_note(pitch=60, start_beat=i * 0.5, duration_beats=0.5) for i in range(10)]
        track = _make_track(notes)
        summaries = build_note_summaries(track, max_summaries=3)
        assert len(summaries) == 3

    def test_index_field_present(self) -> None:
        """Each summary should include the original note index."""
        track = _make_track([
            _note(pitch=60, start_beat=0.0, duration_beats=0.5),
            _note(pitch=64, start_beat=0.5, duration_beats=0.5),
        ])
        summaries = build_note_summaries(track)
        assert summaries[0]["index"] == 0
        assert summaries[1]["index"] == 1

    def test_tuning_range_flag(self) -> None:
        """in_tuning_range should reflect the tuning's pitch range."""
        track = _make_track([
            _note(pitch=30, start_beat=0.0, duration_beats=0.5),  # below E2
            _note(pitch=64, start_beat=0.5, duration_beats=0.5),  # in range
        ])
        tuning = TuningRegistry.default().get("standard_6")
        summaries = build_note_summaries(track, tuning)
        # Find by index
        s0 = next(s for s in summaries if s["index"] == 0)
        s1 = next(s for s in summaries if s["index"] == 1)
        assert s0["in_tuning_range"] is False
        assert s1["in_tuning_range"] is True


# ─── apply_rewrite_decisions tests ───


class TestApplyRewriteDecisions:
    """Tests for apply_rewrite_decisions()."""

    def test_delete_removes_note(self) -> None:
        track = _make_track([
            _note(pitch=60, start_beat=0.0, duration_beats=0.5),
            _note(pitch=64, start_beat=0.5, duration_beats=0.5),
            _note(pitch=67, start_beat=1.0, duration_beats=0.5),
        ])
        decisions = [RewriteDecision(index=1, operation="delete", reason="noise")]
        new_track, applied = apply_rewrite_decisions(track, decisions)
        assert len(new_track.notes) == 2
        assert new_track.notes[0].pitch == 60
        assert new_track.notes[1].pitch == 67
        assert len(applied) == 1
        assert applied[0]["operation"] == "delete"
        assert applied[0]["pitch"] == 64

    def test_transpose_changes_pitch(self) -> None:
        track = _make_track([
            _note(pitch=30, start_beat=0.0, duration_beats=0.5),
        ])
        decisions = [RewriteDecision(index=0, operation="transpose", pitch=40, reason="too low")]
        new_track, applied = apply_rewrite_decisions(track, decisions)
        assert new_track.notes[0].pitch == 40
        assert len(applied) == 1
        assert applied[0]["operation"] == "transpose"
        assert applied[0]["old_pitch"] == 30
        assert applied[0]["new_pitch"] == 40

    def test_multiple_deletes_highest_first(self) -> None:
        """Deleting multiple notes should not shift earlier indices."""
        track = _make_track([
            _note(pitch=60, start_beat=0.0, duration_beats=0.5),
            _note(pitch=61, start_beat=0.5, duration_beats=0.5),
            _note(pitch=62, start_beat=1.0, duration_beats=0.5),
            _note(pitch=63, start_beat=1.5, duration_beats=0.5),
        ])
        decisions = [
            RewriteDecision(index=1, operation="delete", reason="noise1"),
            RewriteDecision(index=3, operation="delete", reason="noise2"),
        ]
        new_track, applied = apply_rewrite_decisions(track, decisions)
        assert len(new_track.notes) == 2
        assert new_track.notes[0].pitch == 60
        assert new_track.notes[1].pitch == 62
        assert len(applied) == 2

    def test_mixed_operations(self) -> None:
        """Transpose first, then delete — indices stay valid."""
        track = _make_track([
            _note(pitch=30, start_beat=0.0, duration_beats=0.5),
            _note(pitch=60, start_beat=0.5, duration_beats=0.5),
            _note(pitch=100, start_beat=1.0, duration_beats=0.5),
        ])
        decisions = [
            RewriteDecision(index=0, operation="transpose", pitch=40, reason="too low"),
            RewriteDecision(index=2, operation="delete", reason="too high"),
        ]
        new_track, applied = apply_rewrite_decisions(track, decisions)
        assert len(new_track.notes) == 2
        assert new_track.notes[0].pitch == 40  # transposed
        assert new_track.notes[1].pitch == 60  # unchanged
        assert len(applied) == 2
        ops = {a["operation"] for a in applied}
        assert ops == {"transpose", "delete"}

    def test_preserves_track_metadata(self) -> None:
        """Track metadata (index, name, program) should be preserved."""
        track = _make_track([_note(pitch=60, start_beat=0.0, duration_beats=0.5)])
        decisions = [RewriteDecision(index=0, operation="transpose", pitch=64)]
        new_track, _ = apply_rewrite_decisions(track, decisions)
        assert new_track.index == track.index
        assert new_track.name == track.name
        assert new_track.program == track.program

    def test_no_decisions(self) -> None:
        """Empty decision list should return the same track unchanged."""
        track = _make_track([_note(pitch=60, start_beat=0.0, duration_beats=0.5)])
        new_track, applied = apply_rewrite_decisions(track, [])
        assert len(new_track.notes) == 1
        assert new_track.notes[0].pitch == 60
        assert applied == []

    def test_transpose_preserves_other_fields(self) -> None:
        """Transposed note should preserve all fields except pitch."""
        original = _note(
            pitch=30, start_beat=1.5, duration_beats=0.25,
            velocity=95, channel=1, program=24,
        )
        track = _make_track([original])
        decisions = [RewriteDecision(index=0, operation="transpose", pitch=40)]
        new_track, _ = apply_rewrite_decisions(track, decisions)
        n = new_track.notes[0]
        assert n.pitch == 40
        assert n.start_beat == original.start_beat
        assert n.duration_beats == original.duration_beats
        assert n.velocity == original.velocity
        assert n.channel == original.channel
        assert n.program == original.program


# ─── validate_decisions tests ───


class TestValidateDecisions:
    """Tests for validate_decisions()."""

    def test_valid_decisions(self) -> None:
        decisions = [
            RewriteDecision(index=0, operation="delete"),
            RewriteDecision(index=1, operation="transpose", pitch=60),
        ]
        policy = ShadowRewritePolicy(max_deletions=5, max_transpositions=5)
        valid = validate_decisions(decisions, 10, policy)
        assert len(valid) == 2

    def test_out_of_bounds_index(self) -> None:
        decisions = [
            RewriteDecision(index=-1, operation="delete"),
            RewriteDecision(index=10, operation="delete"),
        ]
        policy = ShadowRewritePolicy(max_deletions=5, max_transpositions=5)
        valid = validate_decisions(decisions, 10, policy)
        assert len(valid) == 0

    def test_exceeds_max_deletions(self) -> None:
        decisions = [
            RewriteDecision(index=i, operation="delete") for i in range(5)
        ]
        policy = ShadowRewritePolicy(max_deletions=2, max_transpositions=5)
        valid = validate_decisions(decisions, 10, policy)
        assert len(valid) == 2  # only first 2 allowed

    def test_exceeds_max_transpositions(self) -> None:
        decisions = [
            RewriteDecision(index=i, operation="transpose", pitch=60) for i in range(5)
        ]
        policy = ShadowRewritePolicy(max_deletions=5, max_transpositions=2)
        valid = validate_decisions(decisions, 10, policy)
        assert len(valid) == 2

    def test_invalid_operation(self) -> None:
        decisions = [
            RewriteDecision(index=0, operation="insert"),
            RewriteDecision(index=1, operation="modify"),
        ]
        policy = ShadowRewritePolicy(max_deletions=5, max_transpositions=5)
        valid = validate_decisions(decisions, 10, policy)
        assert len(valid) == 0

    def test_transpose_without_pitch(self) -> None:
        decisions = [
            RewriteDecision(index=0, operation="transpose", pitch=None),
        ]
        policy = ShadowRewritePolicy(max_deletions=5, max_transpositions=5)
        valid = validate_decisions(decisions, 10, policy)
        assert len(valid) == 0

    def test_transpose_invalid_pitch(self) -> None:
        decisions = [
            RewriteDecision(index=0, operation="transpose", pitch=-1),
            RewriteDecision(index=1, operation="transpose", pitch=128),
        ]
        policy = ShadowRewritePolicy(max_deletions=5, max_transpositions=5)
        valid = validate_decisions(decisions, 10, policy)
        assert len(valid) == 0


# ─── ShadowRewriteAdvisor integration tests ───


class TestShadowRewriteAdvisor:
    """Tests for the advisor's propose_rewrite with degraded mode."""

    def test_degraded_no_provider(self) -> None:
        """With no provider, propose_rewrite returns empty + degraded=True."""
        advisor = ShadowRewriteAdvisor(None)
        request = RewriteRequest(
            features=_make_features(),
            style_label="rock",
            policy=build_policy(0.5),
        )
        response, degraded = advisor.propose_rewrite(request)
        assert degraded is True
        assert len(response.decisions) == 0

    def test_with_mock_provider(self) -> None:
        """With a mock provider, propose_rewrite returns decisions."""
        decisions = [
            RewriteDecision(index=0, operation="delete", reason="noise"),
            RewriteDecision(index=1, operation="transpose", pitch=60, reason="too low"),
        ]
        provider = _RewriteMockAdvisor(decisions)
        advisor = ShadowRewriteAdvisor(provider)
        request = RewriteRequest(
            features=_make_features(),
            style_label="rock",
            policy=build_policy(0.5),
        )
        response, degraded = advisor.propose_rewrite(request)
        assert degraded is False
        assert len(response.decisions) == 2

    def test_provider_error_falls_back(self) -> None:
        """When the provider raises AIProviderError, fall back to degraded."""

        class ErrorProvider:
            identity = None

            def infer_style(self, features: TrackFeatures) -> str:
                return "rock"

            def propose_rewrite(self, request: RewriteRequest) -> RewriteResponse:
                raise AIProviderError("network timeout")

        advisor = ShadowRewriteAdvisor(ErrorProvider())
        request = RewriteRequest(
            features=_make_features(),
            style_label="rock",
            policy=build_policy(0.5),
        )
        response, degraded = advisor.propose_rewrite(request)
        assert degraded is True
        assert len(response.decisions) == 0


# ─── End-to-end: features + summaries + rewrite + apply ───


class TestEndToEndRewriteFlow:
    """Integration tests simulating the repair flow's rewrite step."""

    def test_full_rewrite_flow(self) -> None:
        """Simulate: build summaries → mock LLM → validate → apply."""
        track = _make_track([
            _note(pitch=30, start_beat=0.0, duration_beats=0.5),   # out of range
            _note(pitch=60, start_beat=0.5, duration_beats=0.5),   # normal
            _note(pitch=100, start_beat=1.0, duration_beats=0.5),  # out of range
        ])
        tuning = TuningRegistry.default().get("standard_6")

        # Step 1: build summaries
        summaries = build_note_summaries(track, tuning)
        assert len(summaries) == 3
        # Out-of-range notes should be first
        assert summaries[0]["in_tuning_range"] is False
        assert summaries[1]["in_tuning_range"] is False
        assert summaries[2]["in_tuning_range"] is True

        # Step 2: mock LLM response
        decisions = [
            RewriteDecision(index=0, operation="transpose", pitch=40, reason="too low"),
            RewriteDecision(index=2, operation="delete", reason="too high"),
        ]

        # Step 3: validate
        policy = build_policy(0.5)
        valid = validate_decisions(decisions, len(track.notes), policy)
        assert len(valid) == 2

        # Step 4: apply
        new_track, applied = apply_rewrite_decisions(track, valid)
        assert len(new_track.notes) == 2
        assert new_track.notes[0].pitch == 40  # transposed
        assert new_track.notes[1].pitch == 60  # unchanged
        assert len(applied) == 2

    def test_degraded_mode_no_changes(self) -> None:
        """In degraded mode, the track should be unchanged."""
        track = _make_track([
            _note(pitch=30, start_beat=0.0, duration_beats=0.5),
            _note(pitch=60, start_beat=0.5, duration_beats=0.5),
        ])
        tuning = TuningRegistry.default().get("standard_6")

        # Degraded mode: no advisor
        advisor = ShadowRewriteAdvisor(None)
        features = extract_features(track)
        request = RewriteRequest(
            features=features,
            style_label="rock",
            policy=build_policy(0.5),
            note_summaries=build_note_summaries(track, tuning),
        )
        response, degraded = advisor.propose_rewrite(request)
        assert degraded is True
        assert len(response.decisions) == 0

        # Track should remain unchanged
        assert len(track.notes) == 2

    def test_policy_limits_enforced(self) -> None:
        """max_deletions from policy should limit applied decisions."""
        notes = [_note(pitch=60, start_beat=i * 0.5, duration_beats=0.5) for i in range(10)]
        track = _make_track(notes)

        # LLM proposes 5 deletions
        decisions = [
            RewriteDecision(index=i, operation="delete", reason=f"noise{i}")
            for i in range(5)
        ]
        # Policy only allows 2 deletions (high fidelity)
        policy = ShadowRewritePolicy(midi_fidelity=0.9, max_deletions=2, max_transpositions=5)
        valid = validate_decisions(decisions, len(track.notes), policy)
        assert len(valid) == 2

        new_track, applied = apply_rewrite_decisions(track, valid)
        assert len(new_track.notes) == 8  # 10 - 2 = 8

    def test_features_extracted_from_cleaned_track(self) -> None:
        """extract_features should work on the post-cleanup track."""
        track = _make_track([
            _note(pitch=60, start_beat=0.0, duration_beats=0.5, velocity=80),
            _note(pitch=64, start_beat=0.5, duration_beats=0.5, velocity=90),
        ])
        features = extract_features(track)
        assert features.note_count == 2
        assert features.pitch_min == 60
        assert features.pitch_max == 64
        assert features.mean_velocity == 85.0
