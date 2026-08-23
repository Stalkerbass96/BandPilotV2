"""Knowledge provenance, scope resolution, and source-governance tests."""

from __future__ import annotations

import json

import pytest

from fretpilot.knowledge.models import KnowledgeEntry, KnowledgeSnapshot
from fretpilot.knowledge.registry import KnowledgeRegistry
from fretpilot.knowledge.sources import KnowledgeSourceCatalog, KnowledgeSourceError


def _entry(
    knowledge_id: str,
    payload: dict[str, float],
    scope: dict[str, list[str]],
) -> KnowledgeEntry:
    return KnowledgeEntry.from_dict(
        {
            "knowledge_id": knowledge_id,
            "domain": "kb2_performance",
            "kind": "fingering_priors",
            "payload": payload,
            "scope": scope,
            "provenance": {
                "source_type": "hand_authored",
                "source_ids": ["policy"],
            },
        }
    )


def test_role_specific_entry_does_not_match_style_only_query() -> None:
    entry = _entry("rock-lead", {"bend": 1.4}, {"style": ["rock"], "role": ["lead"]})

    assert not entry.matches_scope({"style": ["rock"]})
    assert entry.matches_scope({"style": ["rock"], "role": ["lead"]})


def test_payload_layers_generic_then_specific() -> None:
    snapshot = KnowledgeSnapshot(
        snapshot_version="test",
        schema_version="2",
        status="approved",
        entries=(
            _entry("default", {"stability": 1.0, "overlap": 1.0}, {}),
            _entry("rock", {"stability": 1.2}, {"style": ["rock"]}),
            _entry(
                "rock-lead",
                {"stability": 1.4},
                {"style": ["rock"], "role": ["lead"]},
            ),
        ),
    )

    payload = KnowledgeRegistry(snapshot).query_payload(
        domain="kb2_performance", scope={"style": ["rock"], "role": ["lead"]}
    )

    assert payload == {"stability": 1.4, "overlap": 1.0}


def test_candidate_entry_is_inspectable_but_inactive() -> None:
    raw = _entry("candidate", {"stability": 2.0}, {"style": ["rock"]}).to_dict()
    raw["status"] = "candidate"
    candidate = KnowledgeEntry.from_dict(raw)
    registry = KnowledgeRegistry(KnowledgeSnapshot("test", "2", "approved", (candidate,)))

    assert registry.query(domain="kb2_performance", scope={"style": ["rock"]}) == []
    assert registry.query(
        domain="kb2_performance",
        scope={"style": ["rock"]},
        include_inactive=True,
    ) == [candidate]


def test_catalog_rejects_local_path_and_unknown_source(tmp_path) -> None:
    path = tmp_path / "sources.json"
    path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_id": "policy",
                        "title": "Policy",
                        "source_type": "internal_policy",
                        "license_id": "internal",
                        "rights_verified": True,
                        "permitted_uses": ["author_rules"],
                        "redistribution": "with_project",
                        "accessed_at": "2026-08-23",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    catalog = KnowledgeSourceCatalog.from_file(path)

    with pytest.raises(KnowledgeSourceError, match="local path"):
        catalog.validate_entry_sources(
            knowledge_id="bad", source_type="hand_authored", source_ids=["/tmp/song.gp5"]
        )
    with pytest.raises(KnowledgeSourceError, match="unknown source"):
        catalog.validate_entry_sources(
            knowledge_id="bad", source_type="hand_authored", source_ids=["missing"]
        )


def test_catalog_requires_rights_for_empirical_derivation(tmp_path) -> None:
    path = tmp_path / "sources.json"
    path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_id": "private-tabs",
                        "title": "Private tabs",
                        "source_type": "private_corpus",
                        "license_id": "unknown",
                        "rights_verified": False,
                        "permitted_uses": ["private_evaluation"],
                        "redistribution": "none",
                        "accessed_at": "2026-08-23",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    catalog = KnowledgeSourceCatalog.from_file(path)

    with pytest.raises(KnowledgeSourceError, match="rights-verified"):
        catalog.validate_entry_sources(
            knowledge_id="unsafe-priors",
            source_type="empirical",
            source_ids=["private-tabs"],
        )


def test_bundled_assets_have_resolvable_safe_sources(assets_dir) -> None:
    registry = KnowledgeRegistry.from_assets_dir(assets_dir)

    assert registry.snapshot.entries
    assert all(
        not source_id.startswith("/")
        for entry in registry.snapshot.entries
        for source_id in entry.provenance.source_ids
    )


def test_packaged_knowledge_has_no_private_local_path_leak(assets_dir) -> None:
    forbidden = ("/tmp/", "/var/folders/", '"file_path"')

    for path in assets_dir.parent.rglob("*.json"):
        content = path.read_text(encoding="utf-8")
        assert all(marker not in content for marker in forbidden), path


def test_manifest_active_version_is_a_loadable_complete_snapshot(assets_dir) -> None:
    knowledge_root = assets_dir.parent
    manifest = json.loads((knowledge_root / "version_manifest.json").read_text(encoding="utf-8"))
    active = manifest["active_version"]

    registry = KnowledgeRegistry.from_version_dir(knowledge_root / "versions" / active)

    assert registry.snapshot_version == active
    assert len(registry.snapshot.entries) == len(
        KnowledgeRegistry.from_assets_dir(assets_dir).snapshot.entries
    )
