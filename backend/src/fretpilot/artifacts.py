"""Reproducible artifact manifests for BandPilot repair runs."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(slots=True)
class ArtifactRecord:
    name: str
    sha256: str
    size_bytes: int


@dataclass(slots=True)
class ArtifactManifest:
    run_id: str
    created_at: str
    source_sha256: str
    song_schema_version: str
    application_version: str
    knowledge_snapshot: str
    model_provider: str
    model_name: str
    prompt_version: str
    arrangement_mode: str
    settings: dict[str, Any]
    validation_status: str
    artifacts: list[ArtifactRecord] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        source_sha256: str,
        song_schema_version: str,
        application_version: str,
        knowledge_snapshot: str,
        model_provider: str,
        model_name: str,
        prompt_version: str,
        arrangement_mode: str,
        settings: dict[str, Any],
        validation_status: str,
    ) -> ArtifactManifest:
        return cls(
            run_id=str(uuid4()),
            created_at=datetime.now(timezone.utc).isoformat(),
            source_sha256=source_sha256,
            song_schema_version=song_schema_version,
            application_version=application_version,
            knowledge_snapshot=knowledge_snapshot,
            model_provider=model_provider,
            model_name=model_name,
            prompt_version=prompt_version,
            arrangement_mode=arrangement_mode,
            settings=settings,
            validation_status=validation_status,
        )

    def capture(self, project_dir: Path, filenames: list[str]) -> None:
        self.artifacts = []
        for filename in filenames:
            path = project_dir / filename
            if path.is_file():
                self.artifacts.append(
                    ArtifactRecord(
                        name=filename,
                        sha256=file_sha256(path),
                        size_bytes=path.stat().st_size,
                    )
                )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["ArtifactManifest", "ArtifactRecord", "file_sha256"]
