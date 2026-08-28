"""API endpoint tests — auth, BYOK, projects, exports.

Uses the FastAPI TestClient with an in-memory SQLite database and
mock auth. No real LLM calls are made.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import _make_midi_file


class TestAuthEndpoints:
    """Tests for /api/auth/* endpoints."""

    def test_register_creates_user(self, client: TestClient) -> None:
        res = client.post(
            "/api/auth/register",
            json={
                "email": "newuser@test.dev",
                "password": "password123",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert "token" in data
        assert data["user"]["email"] == "newuser@test.dev"

    def test_register_duplicate_email_fails(self, client: TestClient) -> None:
        client.post(
            "/api/auth/register",
            json={
                "email": "dup@test.dev",
                "password": "password123",
            },
        )
        res = client.post(
            "/api/auth/register",
            json={
                "email": "dup@test.dev",
                "password": "password456",
            },
        )
        assert res.status_code == 409

    def test_login_success(self, client: TestClient) -> None:
        client.post(
            "/api/auth/register",
            json={
                "email": "login@test.dev",
                "password": "password123",
            },
        )
        res = client.post(
            "/api/auth/login",
            json={
                "email": "login@test.dev",
                "password": "password123",
            },
        )
        assert res.status_code == 200
        assert "token" in res.json()

    def test_login_wrong_password(self, client: TestClient) -> None:
        client.post(
            "/api/auth/register",
            json={
                "email": "wrongpw@test.dev",
                "password": "password123",
            },
        )
        res = client.post(
            "/api/auth/login",
            json={
                "email": "wrongpw@test.dev",
                "password": "wrongpassword",
            },
        )
        assert res.status_code == 401

    def test_login_nonexistent_user(self, client: TestClient) -> None:
        res = client.post(
            "/api/auth/login",
            json={
                "email": "nobody@test.dev",
                "password": "password123",
            },
        )
        assert res.status_code == 401

    def test_me_requires_auth(self, client: TestClient) -> None:
        res = client.get("/api/auth/me")
        assert res.status_code == 401

    def test_me_returns_user(self, client: TestClient, auth_token: str) -> None:
        res = client.get(
            "/api/auth/me",
            headers={
                "Authorization": f"Bearer {auth_token}",
            },
        )
        assert res.status_code == 200
        assert res.json()["email"] == "test@fretpilot.dev"

    def test_register_short_password_fails(self, client: TestClient) -> None:
        res = client.post(
            "/api/auth/register",
            json={
                "email": "short@test.dev",
                "password": "12345",
            },
        )
        assert res.status_code == 422  # Validation error


class TestByokEndpoints:
    """Tests for /api/byok/* endpoints."""

    def test_get_byok_returns_none_when_not_configured(
        self, client: TestClient, auth_token: str
    ) -> None:
        res = client.get(
            "/api/byok",
            headers={
                "Authorization": f"Bearer {auth_token}",
            },
        )
        assert res.status_code == 200
        assert res.json() is None

    def test_save_byok(self, client: TestClient, auth_token: str) -> None:
        res = client.post(
            "/api/byok",
            json={
                "provider": "openai_compatible",
                "api_key": "sk-test-key-12345",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o-mini",
            },
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["provider"] == "openai_compatible"
        assert "****" in data["key_masked"]
        assert data["model"] == "gpt-4o-mini"

    def test_get_byok_after_save(self, client: TestClient, auth_token: str) -> None:
        client.post(
            "/api/byok",
            json={
                "provider": "openai_compatible",
                "api_key": "sk-test-key-67890",
                "base_url": None,
                "model": None,
            },
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        res = client.get(
            "/api/byok",
            headers={
                "Authorization": f"Bearer {auth_token}",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data is not None
        assert data["provider"] == "openai_compatible"

    def test_delete_byok(self, client: TestClient, auth_token: str) -> None:
        client.post(
            "/api/byok",
            json={
                "provider": "openai_compatible",
                "api_key": "sk-delete-me",
                "base_url": None,
                "model": None,
            },
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        res = client.delete(
            "/api/byok",
            headers={
                "Authorization": f"Bearer {auth_token}",
            },
        )
        assert res.status_code == 200

        # Verify it's gone
        res = client.get(
            "/api/byok",
            headers={
                "Authorization": f"Bearer {auth_token}",
            },
        )
        assert res.json() is None

    def test_byok_requires_auth(self, client: TestClient) -> None:
        res = client.get("/api/byok")
        assert res.status_code == 401


class TestProjectEndpoints:
    """Tests for /api/projects/* endpoints."""

    def test_list_projects_empty(self, client: TestClient, auth_token: str) -> None:
        res = client.get(
            "/api/projects",
            headers={
                "Authorization": f"Bearer {auth_token}",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["code"] == 0
        assert data["data"]["items"] == []
        assert data["data"]["total"] == 0

    def test_create_project_with_midi(
        self, client: TestClient, auth_token: str, tmp_path: Path
    ) -> None:
        midi_path = _make_midi_file(tmp_path / "upload_test.mid")
        with open(midi_path, "rb") as f:
            res = client.post(
                "/api/projects",
                files={"file": ("upload_test.mid", f, "audio/midi")},
                data={"title": "Test Song"},
                headers={"Authorization": f"Bearer {auth_token}"},
            )
        assert res.status_code == 200
        data = res.json()
        assert data["code"] == 0
        assert data["data"]["title"] == "Test Song"
        assert data["data"]["status"] == "imported"
        assert data["data"]["id"] > 0
        document = client.get(
            f"/api/projects/{data['data']['id']}/document",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert document.status_code == 200
        assert document.json()["data"]["revision"]["number"] == 0
        assert document.json()["data"]["document"]["tracks"][0]["family"] == "generic"

    def test_create_blank_project_has_revision_zero(
        self, client: TestClient, auth_token: str
    ) -> None:
        created = client.post(
            "/api/projects/blank",
            json={
                "title": "New drum chart",
                "instrument_family": "drums",
                "bpm": 138,
                "numerator": 4,
                "denominator": 4,
            },
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert created.status_code == 200, created.text
        project = created.json()["data"]
        assert project["status"] == "draft"
        loaded = client.get(
            f"/api/projects/{project['id']}/document",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert loaded.status_code == 200
        document = loaded.json()["data"]["document"]
        assert document["tracks"][0]["family"] == "drums"
        assert document["tempo_map"][0]["bpm"] == 138

        track = document["tracks"][0]
        measure = track["measures"][0]
        staff = track["staves"][0]
        beat = {
            "id": "beat:first-drum-hit",
            "start": measure["start"],
            "duration": {"numerator": 1, "denominator": 1},
            "voice": 1,
            "staff_id": staff["id"],
            "kind": "notes",
            "notes": [
                {
                    "id": "note:first-snare",
                    "pitch": 38,
                    "source": None,
                    "realization": {
                        "kind": "drums",
                        "piece": "snare",
                        "hit_technique": "center",
                    },
                    "technique_ids": [],
                    "properties": {},
                }
            ],
            "tie_in": False,
            "tie_out": False,
            "properties": {},
        }
        inserted = client.post(
            f"/api/projects/{project['id']}/commands",
            json={
                "command_id": "api:blank-first-hit",
                "base_revision": 0,
                "intent": "Add first drum hit",
                "operations": [
                    {
                        "kind": "insert_beat",
                        "track_id": track["id"],
                        "measure_id": measure["id"],
                        "beat": beat,
                        "performance_events": [
                            {
                                "id": "performance:first-snare",
                                "note_id": "note:first-snare",
                                "start": beat["start"],
                                "duration": beat["duration"],
                                "velocity": 80,
                                "controls": [],
                            }
                        ],
                    }
                ],
            },
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert inserted.status_code == 200, inserted.text
        assert inserted.json()["data"]["revision"] == 1

        chord_note = {
            "id": "note:first-hihat",
            "pitch": 42,
            "source": None,
            "realization": {
                "kind": "drums",
                "piece": "hihat_closed",
                "hit_technique": "closed",
            },
            "technique_ids": [],
            "properties": {},
        }
        added = client.post(
            f"/api/projects/{project['id']}/commands",
            json={
                "command_id": "api:add-hihat-to-beat",
                "base_revision": 1,
                "intent": "Add closed hi-hat to the selected beat",
                "operations": [
                    {
                        "kind": "add_note",
                        "beat_id": beat["id"],
                        "note": chord_note,
                        "performance_event": {
                            "id": "performance:first-hihat",
                            "note_id": chord_note["id"],
                            "start": beat["start"],
                            "duration": beat["duration"],
                            "velocity": 72,
                            "controls": [],
                        },
                        "expected_beat_kind": "notes",
                    }
                ],
            },
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert added.status_code == 200, added.text
        assert added.json()["data"]["revision"] == 2

        deleted = client.post(
            f"/api/projects/{project['id']}/commands",
            json={
                "command_id": "api:delete-hihat-from-beat",
                "base_revision": 2,
                "intent": "Delete the selected hi-hat chord tone",
                "operations": [
                    {
                        "kind": "delete_note",
                        "beat_id": beat["id"],
                        "note_id": chord_note["id"],
                        "expected_note_hash": None,
                    }
                ],
            },
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["data"]["revision"] == 3
        current = client.get(
            f"/api/projects/{project['id']}/document",
            headers={"Authorization": f"Bearer {auth_token}"},
        ).json()["data"]["document"]
        current_beat = current["tracks"][0]["measures"][0]["beats"][0]
        assert [note["id"] for note in current_beat["notes"]] == ["note:first-snare"]

        inserted_measure_id = "measure:second-drum-bar"
        inserted_rest_id = "beat:second-drum-rest"
        inserted_measure = client.post(
            f"/api/projects/{project['id']}/commands",
            json={
                "command_id": "api:insert-second-bar",
                "base_revision": 3,
                "intent": "Insert an empty second bar",
                "operations": [
                    {
                        "kind": "insert_measure_group",
                        "entries": [
                            {
                                "track_id": track["id"],
                                "measure": {
                                    "id": inserted_measure_id,
                                    "number": 2,
                                    "start": {"numerator": 4, "denominator": 1},
                                    "duration": {"numerator": 4, "denominator": 1},
                                    "numerator": 4,
                                    "denominator": 4,
                                    "beats": [
                                        {
                                            "id": inserted_rest_id,
                                            "start": {"numerator": 4, "denominator": 1},
                                            "duration": {"numerator": 4, "denominator": 1},
                                            "voice": 1,
                                            "staff_id": staff["id"],
                                            "kind": "rest",
                                            "notes": [],
                                            "tie_in": False,
                                            "tie_out": False,
                                            "properties": {},
                                        }
                                    ],
                                    "annotations": {},
                                },
                            }
                        ],
                        "performance_events": [],
                        "techniques": [],
                        "tempo_changes": [],
                        "time_signatures": [],
                    }
                ],
            },
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert inserted_measure.status_code == 200, inserted_measure.text
        assert inserted_measure.json()["data"]["revision"] == 4

        deleted_measure = client.post(
            f"/api/projects/{project['id']}/commands",
            json={
                "command_id": "api:delete-second-bar",
                "base_revision": 4,
                "intent": "Delete the second bar",
                "operations": [
                    {
                        "kind": "delete_measure_group",
                        "measure_ids": [inserted_measure_id],
                        "expected_measure_hashes": {},
                    }
                ],
            },
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert deleted_measure.status_code == 200, deleted_measure.text
        assert deleted_measure.json()["data"]["revision"] == 5
        after_measure_delete = client.get(
            f"/api/projects/{project['id']}/document",
            headers={"Authorization": f"Bearer {auth_token}"},
        ).json()["data"]["document"]
        assert len(after_measure_delete["tracks"][0]["measures"]) == 1

    def test_create_project_rejects_non_midi(self, client: TestClient, auth_token: str) -> None:
        res = client.post(
            "/api/projects",
            files={"file": ("test.txt", b"not a midi file", "text/plain")},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert res.status_code == 415

    def test_create_project_rejects_invalid_midi_without_orphan(
        self, client: TestClient, auth_token: str
    ) -> None:
        response = client.post(
            "/api/projects",
            files={"file": ("broken.mid", b"not-midi", "audio/midi")},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 422
        projects = client.get(
            "/api/projects", headers={"Authorization": f"Bearer {auth_token}"}
        ).json()["data"]
        assert projects["total"] == 0

    def test_get_project_detail(self, client: TestClient, auth_token: str, tmp_path: Path) -> None:
        midi_path = _make_midi_file(tmp_path / "detail_test.mid")
        with open(midi_path, "rb") as f:
            create_res = client.post(
                "/api/projects",
                files={"file": ("detail_test.mid", f, "audio/midi")},
                headers={"Authorization": f"Bearer {auth_token}"},
            )
        project_id = create_res.json()["data"]["id"]

        res = client.get(
            f"/api/projects/{project_id}",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["id"] == project_id
        assert "tracks" in data

    def test_get_nonexistent_project_404(self, client: TestClient, auth_token: str) -> None:
        res = client.get(
            "/api/projects/99999",
            headers={
                "Authorization": f"Bearer {auth_token}",
            },
        )
        assert res.status_code == 404

    def test_repair_project(self, client: TestClient, auth_token: str, tmp_path: Path) -> None:
        midi_path = _make_midi_file(tmp_path / "repair_test.mid")
        with open(midi_path, "rb") as f:
            create_res = client.post(
                "/api/projects",
                files={"file": ("repair_test.mid", f, "audio/midi")},
                headers={"Authorization": f"Bearer {auth_token}"},
            )
        project_id = create_res.json()["data"]["id"]

        res = client.post(
            f"/api/projects/{project_id}/repair",
            json={"midi_fidelity": 0.5},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["status"] == "repaired"
        assert data["project_id"] == project_id
        assert data["style_label"] != "unknown"
        assert data["note_count"] > 0
        # cleanup 摘要应随 repair 响应返回（Task 2：cleanup 暴露到 API）。
        cleanup = data["cleanup"]
        assert cleanup is not None
        assert cleanup["tuning_id"] == "standard_6"
        assert "tuning_display_name" in cleanup
        assert isinstance(cleanup["tempo_dedup_count"], int)
        assert isinstance(cleanup["out_of_range_count"], int)
        assert isinstance(cleanup["velocity_remapped"], bool)
        assert isinstance(cleanup["overlaps_truncated"], int)
        assert isinstance(cleanup["total_actions"], int)

    def test_async_repair_persists_pollable_result(
        self, client: TestClient, auth_token: str, tmp_path: Path
    ) -> None:
        midi_path = _make_midi_file(tmp_path / "async_repair.mid")
        with open(midi_path, "rb") as midi_file:
            created = client.post(
                "/api/projects",
                files={"file": ("async_repair.mid", midi_file, "audio/midi")},
                headers={"Authorization": f"Bearer {auth_token}"},
            )
        project_id = created.json()["data"]["id"]

        started = client.post(
            f"/api/projects/{project_id}/repair-async",
            json={"midi_fidelity": 0.5, "arrangement_mode": "faithful"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert started.status_code == 202
        accepted = started.json()["data"]
        assert accepted["project_id"] == project_id
        job_id = accepted["job"]["id"]

        polled = client.get(
            f"/api/projects/{project_id}/repair-jobs/{job_id}",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert polled.status_code == 200
        job = polled.json()["data"]
        assert job["status"] == "repaired"
        assert job["progress"] == 1.0
        assert job["result"]["job_id"] == job_id
        assert job["result"]["validation_status"] == "passed"

    def test_repair_report(self, client: TestClient, auth_token: str, tmp_path: Path) -> None:
        midi_path = _make_midi_file(tmp_path / "report_test.mid")
        with open(midi_path, "rb") as f:
            create_res = client.post(
                "/api/projects",
                files={"file": ("report_test.mid", f, "audio/midi")},
                headers={"Authorization": f"Bearer {auth_token}"},
            )
        project_id = create_res.json()["data"]["id"]

        # Run repair first
        client.post(
            f"/api/projects/{project_id}/repair",
            json={"midi_fidelity": 0.5},
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        res = client.get(
            f"/api/projects/{project_id}/report",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert res.status_code == 200
        data = res.json()["data"]
        assert "changes" in data
        assert "summary" in data
        assert data["summary"]["style_label"] != "unknown"

    def test_repair_report_before_repair_404(
        self, client: TestClient, auth_token: str, tmp_path: Path
    ) -> None:
        midi_path = _make_midi_file(tmp_path / "no_repair.mid")
        with open(midi_path, "rb") as f:
            create_res = client.post(
                "/api/projects",
                files={"file": ("no_repair.mid", f, "audio/midi")},
                headers={"Authorization": f"Bearer {auth_token}"},
            )
        project_id = create_res.json()["data"]["id"]

        res = client.get(
            f"/api/projects/{project_id}/report",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert res.status_code == 404


class TestScoreDocumentEndpoints:
    """E1-A transport contract for immutable snapshots and typed commands."""

    @pytest.fixture
    def repaired_project_id(self, client: TestClient, auth_token: str, tmp_path: Path) -> int:
        midi_path = _make_midi_file(tmp_path / "editor_contract.mid")
        with open(midi_path, "rb") as source:
            created = client.post(
                "/api/projects",
                files={"file": ("editor_contract.mid", source, "audio/midi")},
                headers={"Authorization": f"Bearer {auth_token}"},
            )
        project_id = created.json()["data"]["id"]
        repaired = client.post(
            f"/api/projects/{project_id}/repair",
            json={"midi_fidelity": 0.5},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert repaired.status_code == 200, repaired.text
        return project_id

    def test_midi_import_creates_raw_document_before_preparation(
        self, client: TestClient, auth_token: str, tmp_path: Path
    ) -> None:
        midi_path = _make_midi_file(tmp_path / "raw_only.mid")
        with open(midi_path, "rb") as source:
            created = client.post(
                "/api/projects",
                files={"file": ("raw_only.mid", source, "audio/midi")},
                headers={"Authorization": f"Bearer {auth_token}"},
            )
        project_id = created.json()["data"]["id"]
        loaded = client.get(
            f"/api/projects/{project_id}/document",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert loaded.status_code == 200
        initial_hash = loaded.json()["data"]["revision"]["hash"]
        response = client.post(
            f"/api/projects/{project_id}/document/bootstrap",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["revision"]["hash"] == initial_hash

    def test_prepared_score_is_promoted_once_into_revision_history(
        self,
        client: TestClient,
        auth_token: str,
        repaired_project_id: int,
    ) -> None:
        headers = {"Authorization": f"Bearer {auth_token}"}
        promoted = client.post(
            f"/api/projects/{repaired_project_id}/document/promote-prepared",
            headers=headers,
        )
        assert promoted.status_code == 200, promoted.text
        data = promoted.json()["data"]
        assert data["revision"]["number"] == 1
        assert all(
            track["instrument"].get("realization_status") != "unprepared"
            for track in data["document"]["tracks"]
        )
        repeated = client.post(
            f"/api/projects/{repaired_project_id}/document/promote-prepared",
            headers=headers,
        )
        assert repeated.status_code == 200
        assert repeated.json()["data"]["revision"] == data["revision"]
        catchup = client.get(
            f"/api/projects/{repaired_project_id}/commands?after=0",
            headers=headers,
        ).json()["data"]
        assert catchup["items"][0]["transaction"]["origin"] == "repair"

    def test_bootstrap_edit_replay_conflict_catchup_and_integrity_snapshot(
        self,
        client: TestClient,
        auth_token: str,
        repaired_project_id: int,
    ) -> None:
        headers = {"Authorization": f"Bearer {auth_token}"}
        bootstrapped = client.post(
            f"/api/projects/{repaired_project_id}/document/bootstrap",
            headers=headers,
        )
        assert bootstrapped.status_code == 200, bootstrapped.text
        initial = bootstrapped.json()["data"]
        assert initial["revision"]["number"] == 0
        assert len(initial["revision"]["hash"]) == 64
        document = initial["document"]

        # Bootstrap is idempotent and never replaces an existing history.
        repeated = client.post(
            f"/api/projects/{repaired_project_id}/document/bootstrap",
            headers=headers,
        )
        assert repeated.status_code == 200
        assert repeated.json()["data"]["revision"]["hash"] == initial["revision"]["hash"]

        track = document["tracks"][0]
        beat = next(beat for measure in track["measures"] for beat in measure["beats"])
        note = beat["notes"][0]
        next_pitch = note["pitch"] + 1
        command = {
            "command_id": "api:edit-one-note",
            "base_revision": 0,
            "intent": "Raise one selected raw MIDI note",
            "operations": [
                {
                    "kind": "set_note_pitch",
                    "note_id": note["id"],
                    "pitch": next_pitch,
                    "expected_pitch": note["pitch"],
                },
            ],
        }
        accepted = client.post(
            f"/api/projects/{repaired_project_id}/commands",
            json=command,
            headers=headers,
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["data"]["revision"] == 1
        assert accepted.json()["data"]["idempotent_replay"] is False
        accepted_revision_id = accepted.json()["data"]["revision_id"]
        assert accepted_revision_id.startswith("revision:")

        replayed = client.post(
            f"/api/projects/{repaired_project_id}/commands",
            json=command,
            headers=headers,
        )
        assert replayed.status_code == 200, replayed.text
        assert replayed.json()["data"]["idempotent_replay"] is True
        assert replayed.json()["data"]["revision"] == 1
        assert replayed.json()["data"]["revision_id"] == accepted_revision_id

        loaded = client.get(
            f"/api/projects/{repaired_project_id}/document",
            headers=headers,
        )
        assert loaded.status_code == 200
        assert loaded.json()["data"]["revision"]["number"] == 1
        assert loaded.json()["data"]["revision"]["id"] == accepted_revision_id
        revision_zero = client.get(
            f"/api/projects/{repaired_project_id}/document?revision=0",
            headers=headers,
        )
        assert revision_zero.status_code == 200
        assert revision_zero.json()["data"]["revision"]["is_current"] is False

        commands = client.get(
            f"/api/projects/{repaired_project_id}/commands?after=0",
            headers=headers,
        ).json()["data"]
        assert commands["current_revision"] == 1
        assert [item["command_id"] for item in commands["items"]] == ["api:edit-one-note"]

        stale = {
            **command,
            "command_id": "api:stale-same-note",
            "operations": [
                {
                    "kind": "set_note_pitch",
                    "note_id": note["id"],
                    "pitch": note["pitch"] + 2,
                    "expected_pitch": note["pitch"],
                }
            ],
        }
        conflict = client.post(
            f"/api/projects/{repaired_project_id}/commands",
            json=stale,
            headers=headers,
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "revision_conflict"

        invalid = {
            "command_id": "api:invalid-duration",
            "base_revision": 1,
            "intent": "Create an invalid negative duration",
            "operations": [
                {
                    "kind": "set_beat_duration",
                    "beat_id": beat["id"],
                    "duration": {"numerator": -1, "denominator": 1},
                    "expected_duration": beat["duration"],
                }
            ],
        }
        rejected = client.post(
            f"/api/projects/{repaired_project_id}/commands",
            json=invalid,
            headers=headers,
        )
        assert rejected.status_code == 422
        assert rejected.json()["detail"]["code"] == "validation_failed"
        assert (
            client.get(f"/api/projects/{repaired_project_id}/document", headers=headers).json()[
                "data"
            ]["revision"]["number"]
            == 1
        )

        for format_id in ("gp5", "musicxml", "humanized_midi"):
            exact_export = client.post(
                f"/api/projects/{repaired_project_id}/export",
                json={"format": format_id, "revision": 1},
                headers=headers,
            )
            assert exact_export.status_code == 200, exact_export.text
            exact_data = exact_export.json()["data"]
            assert exact_data["revision_id"] == loaded.json()["data"]["revision"]["id"]
            assert exact_data["revision_hash"] == loaded.json()["data"]["revision"]["hash"]

        undo_request = {
            "command_id": "api:undo-edit-one-note",
            "created_at": "2026-08-26T01:00:00+00:00",
        }
        undone = client.post(
            (f"/api/projects/{repaired_project_id}/commands/api:edit-one-note/undo"),
            json=undo_request,
            headers=headers,
        )
        assert undone.status_code == 200, undone.text
        assert undone.json()["data"]["revision"] == 2
        undo_revision_id = undone.json()["data"]["revision_id"]
        assert undo_revision_id.startswith("revision:")
        replayed_undo = client.post(
            (f"/api/projects/{repaired_project_id}/commands/api:edit-one-note/undo"),
            json=undo_request,
            headers=headers,
        )
        assert replayed_undo.status_code == 200
        assert replayed_undo.json()["data"]["idempotent_replay"] is True
        assert replayed_undo.json()["data"]["revision_id"] == undo_revision_id
        after_undo = client.get(
            f"/api/projects/{repaired_project_id}/document", headers=headers
        ).json()["data"]
        restored_note = next(
            candidate
            for score_track in after_undo["document"]["tracks"]
            for measure in score_track["measures"]
            for score_beat in measure["beats"]
            for candidate in score_beat["notes"]
            if candidate["id"] == note["id"]
        )
        assert restored_note["pitch"] == note["pitch"]
        assert after_undo["revision"]["number"] == 2
        assert after_undo["revision"]["id"] == undo_revision_id

    def test_document_access_is_project_owner_scoped(
        self,
        client: TestClient,
        auth_token: str,
        repaired_project_id: int,
    ) -> None:
        owner_headers = {"Authorization": f"Bearer {auth_token}"}
        assert (
            client.post(
                f"/api/projects/{repaired_project_id}/document/bootstrap",
                headers=owner_headers,
            ).status_code
            == 200
        )
        registered = client.post(
            "/api/auth/register",
            json={"email": "other-editor@test.dev", "password": "password123"},
        )
        assert registered.status_code == 200, registered.text
        other_headers = {"Authorization": f"Bearer {registered.json()['token']}"}
        assert (
            client.get(
                f"/api/projects/{repaired_project_id}/document", headers=other_headers
            ).status_code
            == 404
        )


class TestExportEndpoints:
    """Tests for /api/projects/{id}/export and related endpoints."""

    @pytest.fixture
    def repaired_project_id(self, client: TestClient, auth_token: str, tmp_path: Path) -> int:
        """Create and repair a project, returning its ID."""
        midi_path = _make_midi_file(tmp_path / "export_test.mid")
        with open(midi_path, "rb") as f:
            create_res = client.post(
                "/api/projects",
                files={"file": ("export_test.mid", f, "audio/midi")},
                headers={"Authorization": f"Bearer {auth_token}"},
            )
        project_id = create_res.json()["data"]["id"]
        client.post(
            f"/api/projects/{project_id}/repair",
            json={"midi_fidelity": 0.5},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        return project_id

    def test_export_gp5(
        self, client: TestClient, auth_token: str, repaired_project_id: int
    ) -> None:
        res = client.post(
            f"/api/projects/{repaired_project_id}/export",
            json={"format": "gp5"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["format_id"] == "gp5"
        assert data["note_count"] > 0
        assert "download_url" in data
        assert data["revision_id"] is None
        assert data["revision_hash"] is None

    def test_export_ample_midi(
        self, client: TestClient, auth_token: str, repaired_project_id: int
    ) -> None:
        res = client.post(
            f"/api/projects/{repaired_project_id}/export",
            json={"format": "ample_midi"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["format_id"] == "ample_midi"

    @pytest.mark.parametrize(
        "format_id",
        ["musicxml", "humanized_midi", "humanized_ample_eclipse_midi"],
    )
    def test_export_phase_5_6_formats(
        self,
        client: TestClient,
        auth_token: str,
        repaired_project_id: int,
        format_id: str,
    ) -> None:
        res = client.post(
            f"/api/projects/{repaired_project_id}/export",
            json={"format": format_id},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert res.status_code == 200, res.text
        assert res.json()["data"]["format_id"] == format_id

    def test_export_unsupported_format(
        self, client: TestClient, auth_token: str, repaired_project_id: int
    ) -> None:
        res = client.post(
            f"/api/projects/{repaired_project_id}/export",
            json={"format": "wav"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert res.status_code == 400

    def test_list_exports(
        self, client: TestClient, auth_token: str, repaired_project_id: int
    ) -> None:
        # Create an export first
        client.post(
            f"/api/projects/{repaired_project_id}/export",
            json={"format": "gp5"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        res = client.get(
            f"/api/projects/{repaired_project_id}/exports",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert res.status_code == 200
        items = res.json()["data"]["items"]
        assert len(items) >= 1
        assert "revision_id" in items[0]
        assert "revision_hash" in items[0]

    def test_download_export(
        self, client: TestClient, auth_token: str, repaired_project_id: int
    ) -> None:
        export_res = client.post(
            f"/api/projects/{repaired_project_id}/export",
            json={"format": "gp5"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        # Extract export ID from download_url
        download_url = export_res.json()["data"]["download_url"]
        # download_url format: /api/projects/{id}/exports/{export_id}/download
        export_id = download_url.split("/")[-2]

        res = client.get(
            f"/api/projects/{repaired_project_id}/exports/{export_id}/download",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert res.status_code == 200
        assert len(res.content) > 0

    def test_export_before_repair_fails(
        self, client: TestClient, auth_token: str, tmp_path: Path
    ) -> None:
        midi_path = _make_midi_file(tmp_path / "no_export.mid")
        with open(midi_path, "rb") as f:
            create_res = client.post(
                "/api/projects",
                files={"file": ("no_export.mid", f, "audio/midi")},
                headers={"Authorization": f"Bearer {auth_token}"},
            )
        project_id = create_res.json()["data"]["id"]

        res = client.post(
            f"/api/projects/{project_id}/export",
            json={"format": "gp5"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert res.status_code == 400


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_returns_ok(self, client: TestClient) -> None:
        res = client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data["code"] == 0
        assert data["data"]["status"] == "ok"
