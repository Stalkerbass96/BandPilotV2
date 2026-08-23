"""Global configuration loaded from environment variables.

All secrets (JWT secret, BYOK master key) are read at startup. Missing required
secrets cause the app factory to fail fast with a clear message rather than
silently producing insecure defaults.
"""

from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path

from filelock import FileLock
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_job_root() -> str:
    return str(Path.cwd() / "job_root")


def _default_db_url() -> str:
    return f"sqlite:///{Path.cwd() / 'fretpilot.db'}"


class Settings(BaseSettings):
    """Application settings sourced from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="FRETPILOR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "FretPilot v2"
    debug: bool = False

    # Database
    database_url: str = Field(default_factory=_default_db_url)

    # JWT
    jwt_secret: str = Field(default="dev-secret-change-in-production")
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 7

    # BYOK master key (Fernet). If empty, a throwaway key is generated in dev.
    master_key: str = ""

    # Comma-separated administrator emails. Global KB mutation is admin-only.
    admin_emails: str = ""

    # File storage
    job_root: str = Field(default_factory=_default_job_root)
    max_upload_bytes: int = 20 * 1024 * 1024  # 20 MB

    # Knowledge assets root (defaults to package-bundled assets)
    knowledge_assets_dir: str = ""
    knowledge_root: str = "knowledge_store"

    # Comma-separated browser origins allowed by CORS.
    cors_origins: str = "http://localhost:5173"

    # LLM defaults (BYOK overrides per user)
    llm_request_timeout: float = 30.0

    @property
    def job_root_path(self) -> Path:
        path = Path(self.job_root)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def assets_dir(self) -> Path:
        if self.knowledge_assets_dir:
            return Path(self.knowledge_assets_dir)
        self.ensure_knowledge_store()
        return self.knowledge_root_path / "assets"

    @property
    def knowledge_root_path(self) -> Path:
        return Path(self.knowledge_root)

    @property
    def admin_email_set(self) -> set[str]:
        return {
            email.strip().lower()
            for email in self.admin_emails.split(",")
            if email.strip()
        }

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def ensure_knowledge_store(self) -> None:
        """Bootstrap the writable KB store from immutable packaged seed data."""
        root = self.knowledge_root_path
        seed = Path(__file__).resolve().parent / "knowledge"
        root.mkdir(parents=True, exist_ok=True)
        with FileLock(str(root / ".bootstrap.lock"), timeout=30):
            assets = root / "assets"
            if not assets.exists():
                shutil.copytree(seed / "assets", assets)

            manifest = root / "version_manifest.json"
            seed_manifest = seed / "version_manifest.json"
            if not manifest.exists() and seed_manifest.exists():
                shutil.copy2(seed_manifest, manifest)

            versions = root / "versions"
            seed_versions = seed / "versions"
            if not versions.exists() and seed_versions.exists():
                shutil.copytree(seed_versions, versions)
            else:
                versions.mkdir(parents=True, exist_ok=True)

    @property
    def profiles_dir(self) -> Path:
        return (
            Path(__file__).resolve().parent / "exporters" / "ample_midi" / "profiles"
        )

    def ensure_secrets(self) -> None:
        """Validate that required secrets are present for production use."""
        if self.debug:
            return
        if self.jwt_secret == "dev-secret-change-in-production":
            raise RuntimeError(
                "FRETPILOR_JWT_SECRET must be set in non-debug mode."
            )
        if not self.master_key:
            raise RuntimeError(
                "FRETPILOR_MASTER_KEY must be set in non-debug mode."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    settings = Settings()
    settings.ensure_secrets()
    return settings


def reset_settings_cache() -> None:
    """Clear the settings cache (used in tests)."""
    get_settings.cache_clear()


__all__ = ["Settings", "get_settings", "reset_settings_cache"]
