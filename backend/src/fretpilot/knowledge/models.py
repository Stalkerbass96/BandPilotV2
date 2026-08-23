"""Knowledge base data models.

Knowledge entries are data assets (JSON), not code. These dataclasses provide
the typed Python representation loaded from JSON asset files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class KnowledgeProvenance:
    """Tracks where a knowledge entry came from."""

    source_type: str  # hand_authored / empirical / derived
    source_ids: tuple[str, ...] = ()
    authored_by: str = ""
    notes: str = ""


@dataclass(frozen=True, slots=True)
class KnowledgeEvaluation:
    """Evaluation status of a knowledge entry."""

    status: str  # candidate / evaluated / approved / deprecated
    confidence: float = 0.0
    tested_against: tuple[str, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class KnowledgeEntry:
    """A single knowledge entry loaded from a JSON asset file.

    The ``payload`` dict holds the domain-specific content (priors weights,
    keymaps, notation conventions). The ``scope`` dict defines applicability
    (e.g. {"style": ["metal"]}).
    """

    knowledge_id: str
    domain: str  # kb1_arrangement / kb2_performance / kb3_notation / kb4_instruments
    kind: str  # style_priors / fingering_priors / notation_convention / instrument_profile
    schema_version: str
    knowledge_version: str
    status: str
    payload: dict[str, Any]
    scope: dict[str, tuple[str, ...]] = field(default_factory=dict)
    provenance: KnowledgeProvenance = field(
        default_factory=lambda: KnowledgeProvenance(source_type="hand_authored")
    )
    evaluation: KnowledgeEvaluation = field(
        default_factory=lambda: KnowledgeEvaluation(status="approved")
    )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KnowledgeEntry":
        """Construct a KnowledgeEntry from a JSON-loaded dict."""
        provenance_raw = data.get("provenance", {})
        evaluation_raw = data.get("evaluation", {})
        scope_raw = data.get("scope", {})
        return cls(
            knowledge_id=str(data["knowledge_id"]),
            domain=str(data["domain"]),
            kind=str(data["kind"]),
            schema_version=str(data.get("schema_version", "1")),
            knowledge_version=str(data.get("knowledge_version", "0")),
            status=str(data.get("status", "approved")),
            payload=dict(data.get("payload", {})),
            scope={
                str(k): tuple(str(v) for v in vals)
                for k, vals in scope_raw.items()
            },
            provenance=KnowledgeProvenance(
                source_type=str(provenance_raw.get("source_type", "hand_authored")),
                source_ids=tuple(provenance_raw.get("source_ids", [])),
                authored_by=str(provenance_raw.get("authored_by", "")),
                notes=str(provenance_raw.get("notes", "")),
            ),
            evaluation=KnowledgeEvaluation(
                status=str(evaluation_raw.get("status", data.get("status", "approved"))),
                confidence=float(evaluation_raw.get("confidence", 0.0)),
                tested_against=tuple(evaluation_raw.get("tested_against", [])),
                metrics=dict(evaluation_raw.get("metrics", {})),
            ),
        )

    def matches_scope(self, query: dict[str, str | list[str]]) -> bool:
        """Return whether every restriction on the entry is satisfied.

        A role-specific entry must not match a style-only query. The old
        query-driven comparison accidentally let e.g. ``rock/lead`` become
        the default for all rock parts.
        """
        for key, entry_values in self.scope.items():
            values = query.get(key)
            if values is None:
                return False
            query_values = values if isinstance(values, list) else [values]
            if not any(v in entry_values for v in query_values):
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict (inverse of :meth:`from_dict`).

        Tuples are converted to lists for JSON compatibility.  The output
        matches the on-disk JSON format used in ``kb*.json`` asset files.
        """
        return {
            "knowledge_id": self.knowledge_id,
            "domain": self.domain,
            "kind": self.kind,
            "schema_version": self.schema_version,
            "knowledge_version": self.knowledge_version,
            "status": self.status,
            "payload": dict(self.payload),
            "scope": {
                k: list(v) for k, v in self.scope.items()
            },
            "provenance": {
                "source_type": self.provenance.source_type,
                "source_ids": list(self.provenance.source_ids),
                "authored_by": self.provenance.authored_by,
                "notes": self.provenance.notes,
            },
            "evaluation": {
                "status": self.evaluation.status,
                "confidence": self.evaluation.confidence,
                "tested_against": list(self.evaluation.tested_against),
                "metrics": dict(self.evaluation.metrics),
            },
        }


@dataclass(frozen=True, slots=True)
class KnowledgeSnapshot:
    """A versioned snapshot of all knowledge entries across KB1-4."""

    snapshot_version: str
    schema_version: str
    status: str
    entries: tuple[KnowledgeEntry, ...] = ()
    sources: tuple[str, ...] = ()

    @property
    def kb_versions(self) -> dict[str, str]:
        """Return per-domain knowledge versions."""
        versions: dict[str, str] = {}
        for entry in self.entries:
            if entry.domain not in versions:
                versions[entry.domain] = entry.knowledge_version
        return versions


__all__ = [
    "KnowledgeProvenance",
    "KnowledgeEvaluation",
    "KnowledgeEntry",
    "KnowledgeSnapshot",
]
