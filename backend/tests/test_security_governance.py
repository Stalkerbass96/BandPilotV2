"""Security regression tests for BYOK, admin gates, and production secrets."""

from __future__ import annotations

import pytest

from fretpilot.ai.url_security import UnsafeProviderUrl, validate_provider_base_url
from fretpilot.config import Settings


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000/v1",
        "http://127.0.0.1/v1",
        "http://10.0.0.1/v1",
        "http://169.254.169.254/latest/meta-data",
        "file:///etc/passwd",
        "https://user:password@example.com/v1",
    ],
)
def test_provider_url_rejects_non_public_targets(url: str) -> None:
    with pytest.raises(UnsafeProviderUrl):
        validate_provider_base_url(url)


def test_byok_api_rejects_private_base_url(client, auth_token: str) -> None:
    response = client.post(
        "/api/byok",
        json={
            "provider": "openai_compatible",
            "api_key": "secret",
            "base_url": "http://127.0.0.1:8000/v1",
            "model": "local",
        },
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 422


def test_byok_test_endpoint_requires_auth(client) -> None:
    response = client.post(
        "/api/byok/test",
        json={"provider": "openai_compatible", "api_key": "secret"},
    )
    assert response.status_code == 401


def test_knowledge_versions_requires_admin(client) -> None:
    registration = client.post(
        "/api/auth/register",
        json={"email": "member@example.com", "password": "password123"},
    )
    token = registration.json()["token"]
    response = client.get(
        "/api/elearning/versions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_production_requires_both_secrets(tmp_path) -> None:
    settings = Settings(
        debug=False,
        database_url=f"sqlite:///{tmp_path / 'app.db'}",
        jwt_secret="x" * 32,
        master_key="",
    )
    with pytest.raises(RuntimeError, match="MASTER_KEY"):
        settings.ensure_secrets()
