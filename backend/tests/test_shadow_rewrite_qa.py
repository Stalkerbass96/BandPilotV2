"""QA edge-case tests for the shadow rewrite feature.

Complements ``tests/test_shadow_rewrite.py`` with additional edge cases that
exercise boundary conditions, duplicate inputs, policy extremes, and the
end-to-end repair-flow wiring (tuning_info population + IR transformation
recording).

Coverage:
1. build_note_summaries with no tuning — all notes in_range=True
2. apply_rewrite_decisions with duplicate delete indices — deletes once
3. apply_rewrite_decisions transpose to same pitch — still recorded
4. RewriteRequest.tuning_info populated in the repair flow
5. IR transformation list includes stage="rewrite" entries
6. midi_fidelity=1.0 (preserve) blocks all rewrites
7. midi_fidelity=0.0 (aggressive) allows maximum rewrites
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from fretpilot.ai.advisor import (
    ShadowRewriteAdvisor,
    apply_rewrite_decisions,
    build_note_summaries,
    build_policy,
    validate_decisions,
)
from fretpilot.ai.models import (
    AIProviderIdentity,
    RewriteDecision,
    RewriteRequest,
    RewriteResponse,
    TrackFeatures,
)
from fretpilot.api.routes import projects as projects_module
from fretpilot.midi.models import NormalizedTrack
from tests.conftest import _make_midi_file, _note

# ─── Helpers ───


def _make_track(notes: list) -> NormalizedTrack:
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


class _CapturingProvider:
    """Mock provider that captures the RewriteRequest for inspection."""

    def __init__(self) -> None:
        self.identity = AIProviderIdentity(provider="mock", model="mock-capture")
        self.captured_request: RewriteRequest | None = None

    def infer_style(self, features: TrackFeatures) -> str:
        return "rock"

    def propose_rewrite(self, request: RewriteRequest) -> RewriteResponse:
        self.captured_request = request
        return RewriteResponse()  # empty decisions — no changes applied


class _DecisionProvider:
    """Mock provider that returns fixed rewrite decisions."""

    def __init__(self, decisions: list[RewriteDecision]) -> None:
        self.identity = AIProviderIdentity(provider="mock", model="mock-decisions")
        self._decisions = decisions

    def infer_style(self, features: TrackFeatures) -> str:
        return "rock"

    def propose_rewrite(self, request: RewriteRequest) -> RewriteResponse:
        return RewriteResponse(decisions=list(self._decisions))


# ─── build_note_summaries edge cases ───


class TestBuildNoteSummariesEdgeCases:
    """Edge cases for build_note_summaries()."""

    def test_no_tuning_all_notes_in_range(self) -> None:
        """Without a tuning, every note should be in_tuning_range=True.

        The default range is 0–127 (full MIDI spectrum), so even extreme
        pitches like 0, 100, and 127 should be considered in range.
        """
        track = _make_track([
            _note(pitch=0, start_beat=0.0, duration_beats=0.5),
            _note(pitch=40, start_beat=0.5, duration_beats=0.5),
            _note(pitch=100, start_beat=1.0, duration_beats=0.5),
            _note(pitch=127, start_beat=1.5, duration_beats=0.5),
        ])
        summaries = build_note_summaries(track)  # tuning=None
        assert len(summaries) == 4
        for s in summaries:
            assert s["in_tuning_range"] is True


# ─── apply_rewrite_decisions edge cases ───


class TestApplyRewriteDecisionsEdgeCases:
    """Edge cases for apply_rewrite_decisions()."""

    def test_duplicate_delete_indices_deletes_once(self) -> None:
        """Two delete decisions for the same index should remove the note
        only once — the set-based dedup prevents double-deletion / crashes.
        """
        track = _make_track([
            _note(pitch=60, start_beat=0.0, duration_beats=0.5),
            _note(pitch=64, start_beat=0.5, duration_beats=0.5),
            _note(pitch=67, start_beat=1.0, duration_beats=0.5),
        ])
        decisions = [
            RewriteDecision(index=1, operation="delete", reason="noise"),
            RewriteDecision(index=1, operation="delete", reason="noise2"),
        ]
        new_track, applied = apply_rewrite_decisions(track, decisions)
        # Only one note removed despite duplicate indices.
        assert len(new_track.notes) == 2
        assert new_track.notes[0].pitch == 60
        assert new_track.notes[1].pitch == 67

    def test_transpose_to_same_pitch_still_recorded(self) -> None:
        """Transposing a note to its current pitch should still produce
        an applied-log entry (old_pitch == new_pitch).
        """
        track = _make_track([
            _note(pitch=60, start_beat=0.0, duration_beats=0.5),
        ])
        decisions = [
            RewriteDecision(index=0, operation="transpose", pitch=60, reason="noop"),
        ]
        new_track, applied = apply_rewrite_decisions(track, decisions)
        assert len(applied) == 1
        assert applied[0]["operation"] == "transpose"
        assert applied[0]["old_pitch"] == 60
        assert applied[0]["new_pitch"] == 60
        # Note pitch is unchanged.
        assert new_track.notes[0].pitch == 60


# ─── build_policy fidelity bounds ───


class TestBuildPolicyFidelityBounds:
    """Tests for build_policy() at fidelity extremes."""

    def test_fidelity_1_blocks_all_rewrites(self) -> None:
        """midi_fidelity=1.0 (preserve) → max_deletions=0, max_transpositions=0.

        No rewrite decisions should pass validation.
        """
        policy = build_policy(1.0)
        assert policy.max_deletions == 0
        assert policy.max_transpositions == 0

        decisions = [
            RewriteDecision(index=0, operation="delete"),
            RewriteDecision(index=1, operation="transpose", pitch=60),
        ]
        valid = validate_decisions(decisions, 10, policy)
        assert len(valid) == 0

    def test_fidelity_0_allows_maximum_rewrites(self) -> None:
        """midi_fidelity=0.0 (aggressive) → max_deletions=50, max_transpositions=20.

        Many decisions should pass validation, up to the configured limits.
        """
        policy = build_policy(0.0)
        assert policy.max_deletions == 50
        assert policy.max_transpositions == 20

        # 60 delete decisions → only 50 pass (max_deletions cap).
        deletes = [
            RewriteDecision(index=i, operation="delete") for i in range(60)
        ]
        valid_d = validate_decisions(deletes, 100, policy)
        assert len(valid_d) == 50

        # 30 transpose decisions → only 20 pass (max_transpositions cap).
        transposes = [
            RewriteDecision(index=i, operation="transpose", pitch=60)
            for i in range(30)
        ]
        valid_t = validate_decisions(transposes, 100, policy)
        assert len(valid_t) == 20


# ─── RewriteRequest model edge cases ───


class TestRewriteRequestModel:
    """Tests for the RewriteRequest data model."""

    def test_tuning_info_defaults_to_empty_dict(self) -> None:
        """RewriteRequest.tuning_info should default to an empty dict."""
        request = RewriteRequest(
            features=_make_features(),
            style_label="rock",
            policy=build_policy(0.5),
        )
        assert request.tuning_info == {}

    def test_tuning_info_accepts_populated_dict(self) -> None:
        """RewriteRequest.tuning_info should accept a populated dict."""
        tuning_info = {
            "id": "standard_6",
            "display_name": "Standard E",
            "string_count": 6,
            "string_pitches": [40, 45, 50, 55, 59, 64],
            "min_pitch": 40,
            "max_pitch": 88,
        }
        request = RewriteRequest(
            features=_make_features(),
            style_label="rock",
            policy=build_policy(0.5),
            tuning_info=tuning_info,
        )
        assert request.tuning_info["id"] == "standard_6"
        assert request.tuning_info["string_count"] == 6


# ─── Repair flow integration (API) ───


class TestRepairFlowRewriteIntegration:
    """End-to-end tests for the shadow rewrite wiring in the repair flow."""

    def test_tuning_info_populated_in_repair_flow(
        self,
        client: TestClient,
        auth_token: str,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        """RewriteRequest.tuning_info should be populated with the resolved
        tuning's details when a tuning is available (auto-detected).

        We inject a capturing mock advisor via monkeypatch so we can inspect
        the exact RewriteRequest handed to ``propose_rewrite``.
        """
        provider = _CapturingProvider()
        advisor = ShadowRewriteAdvisor(provider)

        def fake_build_advisor(user, db):
            return advisor

        monkeypatch.setattr(projects_module, "_build_advisor", fake_build_advisor)

        midi_path = _make_midi_file(tmp_path / "tuning_info_test.mid")
        with open(midi_path, "rb") as f:
            create_res = client.post(
                "/api/projects",
                files={"file": ("tuning_info_test.mid", f, "audio/midi")},
                headers={"Authorization": f"Bearer {auth_token}"},
            )
        project_id = create_res.json()["data"]["id"]

        res = client.post(
            f"/api/projects/{project_id}/repair",
            json={"midi_fidelity": 0.5, "arrangement_mode": "creative_rewrite"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert res.status_code == 200

        # The advisor's propose_rewrite should have been called with a
        # RewriteRequest whose tuning_info is populated from the resolved
        # tuning (auto-detected standard_6 for a C-major scale MIDI).
        assert provider.captured_request is not None
        tuning_info = provider.captured_request.tuning_info
        assert tuning_info != {}
        assert tuning_info["id"] == "standard_6"
        assert tuning_info["string_count"] == 6
        assert isinstance(tuning_info["string_pitches"], list)
        assert len(tuning_info["string_pitches"]) == 6
        assert "min_pitch" in tuning_info
        assert "max_pitch" in tuning_info
        assert "display_name" in tuning_info

    def test_ir_changes_include_rewrite_stage(
        self,
        client: TestClient,
        auth_token: str,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        """When the LLM proposes rewrite decisions that are applied, the IR's
        transformation list should include entries with stage='rewrite'.
        """
        decisions = [
            RewriteDecision(
                index=0, operation="transpose", pitch=55, reason="too low"
            ),
            RewriteDecision(index=1, operation="delete", reason="noise"),
        ]
        provider = _DecisionProvider(decisions)
        advisor = ShadowRewriteAdvisor(provider)

        def fake_build_advisor(user, db):
            return advisor

        monkeypatch.setattr(projects_module, "_build_advisor", fake_build_advisor)

        midi_path = _make_midi_file(tmp_path / "rewrite_stage_test.mid")
        with open(midi_path, "rb") as f:
            create_res = client.post(
                "/api/projects",
                files={"file": ("rewrite_stage_test.mid", f, "audio/midi")},
                headers={"Authorization": f"Bearer {auth_token}"},
            )
        project_id = create_res.json()["data"]["id"]

        # midi_fidelity=0.0 → max rewrites allowed (max_deletions=50).
        repair_res = client.post(
            f"/api/projects/{project_id}/repair",
            json={"midi_fidelity": 0.0, "arrangement_mode": "creative_rewrite"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert repair_res.status_code == 200
        data = repair_res.json()["data"]
        # Rewrite should not be in degraded mode (provider is configured).
        assert data["rewrite"] is not None
        assert data["rewrite"]["degraded"] is False
        assert data["rewrite"]["total"] >= 1

        # Fetch the repair report and inspect transformations.
        report_res = client.get(
            f"/api/projects/{project_id}/report",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert report_res.status_code == 200
        changes = report_res.json()["data"]["changes"]

        rewrite_changes = [c for c in changes if c["stage"] == "rewrite"]
        assert len(rewrite_changes) >= 1
        # Should include at least one delete (present: True → False).
        assert any(
            c["before"].get("present") is True
            and c["after"].get("present") is False
            for c in rewrite_changes
        )
        # Should include at least one transpose (pitch in before & after).
        assert any(
            "pitch" in c["before"] and "pitch" in c["after"]
            for c in rewrite_changes
        )
