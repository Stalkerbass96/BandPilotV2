"""Tests for KBWriter — version management and KB writing."""

import json
import tempfile
from pathlib import Path

import pytest

from fretpilot.elearning.kb_writer import KBWriter
from fretpilot.elearning.models import DerivedPriors


@pytest.fixture
def kb_root(tmp_path):
    """Create a minimal KB root directory with a kb2_performance.json."""
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    versions_dir = tmp_path / "versions"
    versions_dir.mkdir()

    # Copy the real kb2_performance.json structure
    kb2_data = {
        "snapshot_version": "2026.08.3",
        "schema_version": "1",
        "status": "approved",
        "entries": [
            {
                "knowledge_id": "kb2-rock-lead-performance",
                "domain": "kb2_performance",
                "kind": "fingering_priors",
                "schema_version": "1",
                "knowledge_version": "2026.08.3",
                "status": "approved",
                "payload": {
                    "same_string_legato": 1.2,
                    "hand_position_stability": 1.1,
                    "open_string_bias": 0.8,
                    "note_overlap": 0.85,
                },
                "scope": {"style": ["rock"], "role": ["lead"]},
                "provenance": {
                    "source_type": "hand_authored",
                    "source_ids": ["rock-lead-guitar"],
                },
                "evaluation": {"status": "approved", "confidence": 0.0},
            },
        ],
    }
    (assets_dir / "kb2_performance.json").write_text(
        json.dumps(kb2_data, indent=2), encoding="utf-8",
    )

    # Also write kb1, kb3, kb4 (minimal)
    for name in ("kb1_arrangement", "kb3_notation", "kb4_instruments"):
        (assets_dir / f"{name}.json").write_text(
            json.dumps({
                "snapshot_version": "2026.08.3",
                "schema_version": "1",
                "status": "approved",
                "entries": [],
            }, indent=2),
            encoding="utf-8",
        )

    yield tmp_path


def test_write_creates_version(kb_root):
    """KBWriter.write creates a new version directory."""
    writer = KBWriter(kb_root)
    derived = [DerivedPriors(
        style_label="rock",
        knowledge_id="kb2-rock-lead-performance",
        payload={"open_string_bias": 1.2, "hand_position_stability": 1.3},
        source_ids=["song1.gp5", "song2.gp5"],
        confidence=0.85,
        derivation_method="statistical_mapping",
        stats_snapshot={"sample_count": 2},
    )]

    version = writer.write(derived, snapshot_version="2026.09.1")

    version_dir = kb_root / "versions" / "2026.09.1"
    assert version_dir.exists()
    assert (version_dir / "kb2_performance.json").exists()
    assert version == "2026.09.1"


def test_write_updates_payload(kb_root):
    """Written KB has updated payload with empirical values."""
    writer = KBWriter(kb_root)
    derived = [DerivedPriors(
        style_label="rock",
        knowledge_id="kb2-rock-lead-performance",
        payload={"open_string_bias": 1.5},
        source_ids=["song1.gp5"],
        confidence=0.8,
        derivation_method="statistical_mapping",
        stats_snapshot={},
    )]

    writer.write(derived, snapshot_version="2026.09.1")

    version_path = kb_root / "versions" / "2026.09.1" / "kb2_performance.json"
    data = json.loads(version_path.read_text(encoding="utf-8"))

    entry = data["entries"][0]
    assert entry["payload"]["open_string_bias"] == 1.5
    assert entry["provenance"]["source_type"] == "empirical"
    assert entry["evaluation"]["confidence"] == 0.8


def test_write_copies_nested_chord_shapes(kb_root):
    """Nested chord_shapes in the payload must survive the write round-trip."""
    writer = KBWriter(kb_root)
    derived = [DerivedPriors(
        style_label="rock",
        knowledge_id="kb2-rock-lead-performance",
        payload={
            "open_string_bias": 1.5,
            "chord_shapes": {"s1f0,s2f2": 5, "s1f0,s2f3": 3},
        },
        source_ids=["song1.gp5"],
        confidence=0.8,
        derivation_method="statistical_mapping",
        stats_snapshot={},
    )]

    writer.write(derived, snapshot_version="2026.09.1", promote=True)

    version_data = json.loads(
        (kb_root / "versions" / "2026.09.1" / "kb2_performance.json").read_text(encoding="utf-8")
    )
    active_data = json.loads(
        (kb_root / "assets" / "kb2_performance.json").read_text(encoding="utf-8")
    )
    for data in (version_data, active_data):
        entry = data["entries"][0]
        assert entry["payload"]["open_string_bias"] == 1.5
        assert entry["payload"]["chord_shapes"] == {"s1f0,s2f2": 5, "s1f0,s2f3": 3}


def test_promote_updates_active(kb_root):
    """When promote=True, the active assets/ KB is updated."""
    writer = KBWriter(kb_root)
    derived = [DerivedPriors(
        style_label="rock",
        knowledge_id="kb2-rock-lead-performance",
        payload={"open_string_bias": 1.5},
        source_ids=["song1.gp5"],
        confidence=0.8,
        derivation_method="statistical_mapping",
        stats_snapshot={},
    )]

    writer.write(derived, snapshot_version="2026.09.1", promote=True)

    active_path = kb_root / "assets" / "kb2_performance.json"
    data = json.loads(active_path.read_text(encoding="utf-8"))
    assert data["entries"][0]["payload"]["open_string_bias"] == 1.5


def test_list_versions(kb_root):
    """list_versions returns all written versions."""
    writer = KBWriter(kb_root)
    derived = [DerivedPriors(
        style_label="rock",
        knowledge_id="kb2-rock-lead-performance",
        payload={"open_string_bias": 1.5},
        source_ids=["s"],
        confidence=0.8,
        derivation_method="statistical_mapping",
        stats_snapshot={},
    )]

    writer.write(derived, snapshot_version="2026.09.1")
    writer.write(derived, snapshot_version="2026.09.2")

    versions = writer.list_versions()
    assert len(versions) == 2
    assert versions[0]["version"] == "2026.09.1"
    assert versions[1]["version"] == "2026.09.2"


def test_write_stamps_snapshot_version_on_all_domain_files(kb_root):
    """Regression: every domain file in a written version must share the
    new snapshot_version so KnowledgeRegistry can load the version dir."""
    writer = KBWriter(kb_root)
    derived = [DerivedPriors(
        style_label="rock",
        knowledge_id="kb2-rock-lead-performance",
        payload={"open_string_bias": 1.5},
        source_ids=["s"],
        confidence=0.8,
        derivation_method="statistical_mapping",
        stats_snapshot={},
    )]

    writer.write(derived, snapshot_version="2026.09.1")

    version_dir = kb_root / "versions" / "2026.09.1"
    for filename in ("kb1_arrangement", "kb2_performance", "kb3_notation", "kb4_instruments"):
        data = json.loads((version_dir / f"{filename}.json").read_text(encoding="utf-8"))
        assert data["snapshot_version"] == "2026.09.1", filename

    # The version directory must be loadable as a consistent snapshot.
    from fretpilot.knowledge.registry import KnowledgeRegistry
    registry = KnowledgeRegistry.from_version_dir(version_dir)
    assert registry.snapshot.snapshot_version == "2026.09.1"


def test_diff_versions(kb_root):
    """diff_versions shows payload differences between two versions."""
    writer = KBWriter(kb_root)

    # Write version A with one value
    writer.write([DerivedPriors(
        style_label="rock", knowledge_id="kb2-rock-lead-performance",
        payload={"open_string_bias": 1.0}, source_ids=["s"],
        confidence=0.8, derivation_method="statistical_mapping",
        stats_snapshot={},
    )], snapshot_version="2026.09.1")

    # Write version B with different value
    writer.write([DerivedPriors(
        style_label="rock", knowledge_id="kb2-rock-lead-performance",
        payload={"open_string_bias": 1.5}, source_ids=["s"],
        confidence=0.8, derivation_method="statistical_mapping",
        stats_snapshot={},
    )], snapshot_version="2026.09.2")

    diff = writer.diff_versions("2026.09.1", "2026.09.2")
    assert diff["version_a"] == "2026.09.1"
    assert diff["version_b"] == "2026.09.2"
    assert "kb2-rock-lead-performance" in diff["entry_diffs"]
    payload_diff = diff["entry_diffs"]["kb2-rock-lead-performance"]["payload_diff"]
    assert "open_string_bias" in payload_diff
