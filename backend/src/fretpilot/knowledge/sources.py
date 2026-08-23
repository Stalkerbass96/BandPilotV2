"""Typed, rights-aware catalogue for knowledge-base sources.

Knowledge entries contain stable source identifiers only. URLs, licences,
checksums, and permitted uses live here so they can be audited without
leaking local paths or copyrighted score titles into runtime assets.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


class KnowledgeSourceError(ValueError):
    """Raised when source provenance is missing or unsafe."""


@dataclass(frozen=True, slots=True)
class KnowledgeSource:
    """One traceable source and its allowed uses inside BandPilot."""

    source_id: str
    title: str
    source_type: str
    url: str
    license_id: str
    rights_verified: bool
    permitted_uses: tuple[str, ...]
    redistribution: str
    accessed_at: str
    artifact_hash: str = ""
    attribution: str = ""
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KnowledgeSource":
        return cls(
            source_id=str(data["source_id"]),
            title=str(data["title"]),
            source_type=str(data["source_type"]),
            url=str(data.get("url", "")),
            license_id=str(data.get("license_id", "unknown")),
            rights_verified=bool(data.get("rights_verified", False)),
            permitted_uses=tuple(str(v) for v in data.get("permitted_uses", [])),
            redistribution=str(data.get("redistribution", "none")),
            accessed_at=str(data.get("accessed_at", "")),
            artifact_hash=str(data.get("artifact_hash", "")),
            attribution=str(data.get("attribution", "")),
            notes=str(data.get("notes", "")),
        )


class KnowledgeSourceCatalog:
    """Read-only source catalogue with promotion-safety validation."""

    def __init__(self, sources: Iterable[KnowledgeSource]) -> None:
        self._by_id: dict[str, KnowledgeSource] = {}
        for source in sources:
            if not source.source_id or source.source_id in self._by_id:
                raise KnowledgeSourceError(
                    f"Duplicate or empty knowledge source id: {source.source_id!r}"
                )
            self._by_id[source.source_id] = source

    @classmethod
    def from_file(cls, path: str | Path) -> "KnowledgeSourceCatalog":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("sources"), list):
            raise KnowledgeSourceError("source_catalog.json must contain a sources list")
        return cls(KnowledgeSource.from_dict(item) for item in raw["sources"])

    def get(self, source_id: str) -> KnowledgeSource | None:
        return self._by_id.get(source_id)

    def validate_entry_sources(
        self,
        *,
        knowledge_id: str,
        source_type: str,
        source_ids: Iterable[str],
    ) -> None:
        """Reject unknown IDs, local paths, and unlicensed empirical promotion."""

        ids = tuple(source_ids)
        if not ids:
            raise KnowledgeSourceError(f"{knowledge_id}: provenance.source_ids is empty")

        resolved: list[KnowledgeSource] = []
        for source_id in ids:
            if Path(source_id).is_absolute() or source_id.startswith(("~/", "file://")):
                raise KnowledgeSourceError(
                    f"{knowledge_id}: local path is not a stable source id"
                )
            source = self.get(source_id)
            if source is None:
                raise KnowledgeSourceError(
                    f"{knowledge_id}: unknown source id {source_id!r}"
                )
            resolved.append(source)

        if source_type in {"empirical", "derived"}:
            dataset_types = {
                "public_dataset",
                "private_corpus",
                "restricted_dataset",
            }
            datasets = [source for source in resolved if source.source_type in dataset_types]
            if not datasets or any(
                not source.rights_verified
                or "derive_aggregates" not in source.permitted_uses
                for source in datasets
            ):
                raise KnowledgeSourceError(
                    f"{knowledge_id}: every empirical dataset must be rights-verified "
                    "and permit aggregate derivation"
                )

    def ids(self) -> tuple[str, ...]:
        return tuple(self._by_id)


__all__ = [
    "KnowledgeSource",
    "KnowledgeSourceCatalog",
    "KnowledgeSourceError",
]
