"""API endpoint tests — auth, BYOK, projects, exports.

Uses the FastAPI TestClient with an in-memory SQLite database and
mock auth. No real LLM calls are made.
"""

from __future__ import annotations

from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from fretpilot.db.session import get_db, init_db, _SessionLocal
from fretpilot.db.models import User
from fretpilot.api.security import hash_password, create_access_token

from tests.conftest import _make_midi_file


class TestAuthEndpoints:
    """Tests for /api/auth/* endpoints."""

    def test_register_creates_user(self, client: TestClient) -> None:
        res = client.post("/api/auth/register", json={
            "email": "newuser@test.dev",
            "password": "password123",
        })
        assert res.status_code == 200
        data = res.json()
        assert "token" in data
        assert data["user"]["email"] == "newuser@test.dev"

    def test_register_duplicate_email_fails(self, client: TestClient) -> None:
        client.post("/api/auth/register", json={
            "email": "dup@test.dev",
            "password": "password123",
        })
        res = client.post("/api/auth/register", json={
            "email": "dup@test.dev",
            "password": "password456",
        })
        assert res.status_code == 409

    def test_login_success(self, client: TestClient) -> None:
        client.post("/api/auth/register", json={
            "email": "login@test.dev",
            "password": "password123",
        })
        res = client.post("/api/auth/login", json={
            "email": "login@test.dev",
            "password": "password123",
        })
        assert res.status_code == 200
        assert "token" in res.json()

    def test_login_wrong_password(self, client: TestClient) -> None:
        client.post("/api/auth/register", json={
            "email": "wrongpw@test.dev",
            "password": "password123",
        })
        res = client.post("/api/auth/login", json={
            "email": "wrongpw@test.dev",
            "password": "wrongpassword",
        })
        assert res.status_code == 401

    def test_login_nonexistent_user(self, client: TestClient) -> None:
        res = client.post("/api/auth/login", json={
            "email": "nobody@test.dev",
            "password": "password123",
        })
        assert res.status_code == 401

    def test_me_requires_auth(self, client: TestClient) -> None:
        res = client.get("/api/auth/me")
        assert res.status_code == 401

    def test_me_returns_user(self, client: TestClient, auth_token: str) -> None:
        res = client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {auth_token}",
        })
        assert res.status_code == 200
        assert res.json()["email"] == "test@fretpilot.dev"

    def test_register_short_password_fails(self, client: TestClient) -> None:
        res = client.post("/api/auth/register", json={
            "email": "short@test.dev",
            "password": "12345",
        })
        assert res.status_code == 422  # Validation error


class TestByokEndpoints:
    """Tests for /api/byok/* endpoints."""

    def test_get_byok_returns_none_when_not_configured(
        self, client: TestClient, auth_token: str
    ) -> None:
        res = client.get("/api/byok", headers={
            "Authorization": f"Bearer {auth_token}",
        })
        assert res.status_code == 200
        assert res.json() is None

    def test_save_byok(self, client: TestClient, auth_token: str) -> None:
        res = client.post("/api/byok", json={
            "provider": "openai_compatible",
            "api_key": "sk-test-key-12345",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
        }, headers={"Authorization": f"Bearer {auth_token}"})
        assert res.status_code == 200
        data = res.json()
        assert data["provider"] == "openai_compatible"
        assert "****" in data["key_masked"]
        assert data["model"] == "gpt-4o-mini"

    def test_get_byok_after_save(self, client: TestClient, auth_token: str) -> None:
        client.post("/api/byok", json={
            "provider": "openai_compatible",
            "api_key": "sk-test-key-67890",
            "base_url": None,
            "model": None,
        }, headers={"Authorization": f"Bearer {auth_token}"})

        res = client.get("/api/byok", headers={
            "Authorization": f"Bearer {auth_token}",
        })
        assert res.status_code == 200
        data = res.json()
        assert data is not None
        assert data["provider"] == "openai_compatible"

    def test_delete_byok(self, client: TestClient, auth_token: str) -> None:
        client.post("/api/byok", json={
            "provider": "openai_compatible",
            "api_key": "sk-delete-me",
            "base_url": None,
            "model": None,
        }, headers={"Authorization": f"Bearer {auth_token}"})

        res = client.delete("/api/byok", headers={
            "Authorization": f"Bearer {auth_token}",
        })
        assert res.status_code == 200

        # Verify it's gone
        res = client.get("/api/byok", headers={
            "Authorization": f"Bearer {auth_token}",
        })
        assert res.json() is None

    def test_byok_requires_auth(self, client: TestClient) -> None:
        res = client.get("/api/byok")
        assert res.status_code == 401


class TestProjectEndpoints:
    """Tests for /api/projects/* endpoints."""

    def test_list_projects_empty(self, client: TestClient, auth_token: str) -> None:
        res = client.get("/api/projects", headers={
            "Authorization": f"Bearer {auth_token}",
        })
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

    def test_create_project_rejects_non_midi(
        self, client: TestClient, auth_token: str
    ) -> None:
        res = client.post(
            "/api/projects",
            files={"file": ("test.txt", b"not a midi file", "text/plain")},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert res.status_code == 415

    def test_get_project_detail(
        self, client: TestClient, auth_token: str, tmp_path: Path
    ) -> None:
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

    def test_get_nonexistent_project_404(
        self, client: TestClient, auth_token: str
    ) -> None:
        res = client.get("/api/projects/99999", headers={
            "Authorization": f"Bearer {auth_token}",
        })
        assert res.status_code == 404

    def test_repair_project(
        self, client: TestClient, auth_token: str, tmp_path: Path
    ) -> None:
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

    def test_repair_report(
        self, client: TestClient, auth_token: str, tmp_path: Path
    ) -> None:
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


class TestExportEndpoints:
    """Tests for /api/projects/{id}/export and related endpoints."""

    @pytest.fixture
    def repaired_project_id(
        self, client: TestClient, auth_token: str, tmp_path: Path
    ) -> int:
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
