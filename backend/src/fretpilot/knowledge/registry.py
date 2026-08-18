"""Knowledge registry — loads versioned JSON assets and provides query access.

The registry validates schema version, snapshot version, and status on load.
It never holds Python-coded priors — all knowledge data comes from JSON files.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fretpilot.knowledge.models import KnowledgeEntry, KnowledgeSnapshot

logger = logging.getLogger("fretpilot.knowledge.registry")

SUPPORTED_SCHEMA_VERSIONS = frozenset({"1", "2"})
REQUIRED_STATUS = "approved"

_KB_DOMAINS = (
    "kb1_arrangement",
    "kb2_performance",
    "kb3_notation",
    "kb4_instruments",
)


class KnowledgeVersionMismatch(ValueError):
    """Raised when a knowledge asset has an incompatible version or status."""


def _load_asset_file(path: Path) -> dict[str, Any]:
    """Read and parse a single JSON asset file."""
    if not path.exists():
        raise FileNotFoundError(f"Knowledge asset not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Knowledge asset {path} root must be a JSON object.")
    return data


def _validate_asset(data: dict[str, Any], filename: str) -> str:
    """Validate schema_version and status; return the snapshot_version."""
    schema_version = str(data.get("schema_version", ""))
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise KnowledgeVersionMismatch(
            f"{filename}: schema_version {schema_version!r} not in {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )
    status = str(data.get("status", ""))
    if status != REQUIRED_STATUS:
        raise KnowledgeVersionMismatch(
            f"{filename}: status {status!r} != {REQUIRED_STATUS!r}"
        )
    return str(data.get("snapshot_version", "unknown"))


def _build_snapshot_from_assets(
    assets_dir: Path,
) -> KnowledgeSnapshot:
    """Load all KB*.json files from a directory into a single snapshot."""
    entries: list[KnowledgeEntry] = []
    snapshot_version = "unknown"
    sources: list[str] = []

    for domain in _KB_DOMAINS:
        path = assets_dir / f"{domain}.json"
        if not path.exists():
            logger.warning("Knowledge asset missing: %s", path)
            continue
        data = _load_asset_file(path)
        version = _validate_asset(data, path.name)
        if snapshot_version == "unknown":
            snapshot_version = version
        elif version != snapshot_version:
            raise KnowledgeVersionMismatch(
                f"Snapshot version mismatch: {path.name} has {version}, "
                f"expected {snapshot_version}"
            )
        for raw_entry in data.get("entries", []):
            entries.append(KnowledgeEntry.from_dict(raw_entry))
        sources.append(path.name)

    return KnowledgeSnapshot(
        snapshot_version=snapshot_version,
        schema_version=max(SUPPORTED_SCHEMA_VERSIONS),
        status=REQUIRED_STATUS,
        entries=tuple(entries),
        sources=tuple(sources),
    )


class KnowledgeRegistry:
    """Read-only query interface over a loaded KnowledgeSnapshot."""

    def __init__(self, snapshot: KnowledgeSnapshot) -> None:
        self._snapshot = snapshot
        self._by_id: dict[str, KnowledgeEntry] = {
            e.knowledge_id: e for e in snapshot.entries
        }

    @classmethod
    def from_assets_dir(cls, assets_dir: Path | str) -> "KnowledgeRegistry":
        """Load all KB assets from a directory."""
        return cls(_build_snapshot_from_assets(Path(assets_dir)))

    @classmethod
    def from_version_dir(cls, version_dir: Path | str) -> "KnowledgeRegistry":
        """Load KB assets from a versioned snapshot directory.

        Used by :class:`KBWriter` to load specific KB versions for A/B
        comparison.  Reuses the same ``_build_snapshot_from_assets()``
        logic since version directories have the same structure as the
        active assets directory.

        Args:
            version_dir: Path to a ``versions/<version>/`` directory
                containing ``kb*.json`` files.

        Returns:
            A :class:`KnowledgeRegistry` loaded from the version directory.
        """
        return cls(_build_snapshot_from_assets(Path(version_dir)))

    @property
    def snapshot(self) -> KnowledgeSnapshot:
        return self._snapshot

    @property
    def snapshot_version(self) -> str:
        return self._snapshot.snapshot_version

    @property
    def kb_versions(self) -> dict[str, str]:
        return self._snapshot.kb_versions

    def get(self, knowledge_id: str) -> KnowledgeEntry | None:
        """Return a single entry by ID, or None."""
        return self._by_id.get(knowledge_id)

    def query(
        self,
        *,
        domain: str | None = None,
        scope: dict[str, str | list[str]] | None = None,
        kind: str | None = None,
    ) -> list[KnowledgeEntry]:
        """Query entries by domain, scope, and/or kind."""
        results: list[KnowledgeEntry] = []
        for entry in self._snapshot.entries:
            if domain and entry.domain != domain:
                continue
            if kind and entry.kind != kind:
                continue
            if scope and not entry.matches_scope(scope):
                continue
            results.append(entry)
        return results

    def query_payload(
        self,
        *,
        domain: str,
        scope: dict[str, str | list[str]] | None = None,
    ) -> dict[str, Any]:
        """Return the merged payload of the first matching entry (empty if none)."""
        entries = self.query(domain=domain, scope=scope)
        if not entries:
            return {}
        return dict(entries[0].payload)

    def entry_ids(self) -> list[str]:
        """Return all entry IDs in the snapshot."""
        return list(self._by_id.keys())


__all__ = [
    "KnowledgeVersionMismatch",
    "KnowledgeRegistry",
]
