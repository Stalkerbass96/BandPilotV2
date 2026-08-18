"""P1-3, P1-4, P1-5: KB writer — versioned knowledge-base management.

Writes empirically-derived priors back to ``kb2_performance.json`` as a new
versioned snapshot, preserving old versions for rollback.  Supports A/B
comparison by running the full evaluator with two KB versions.

Directory layout::

    knowledge/
    ├── assets/                         ← active version (pipeline loads this)
    │   └── kb2_performance.json
    ├── versions/                       ← historical snapshots
    │   ├── 2026.08.3/
    │   │   └── kb2_performance.json
    │   └── 2026.08.4/
    │       └── kb2_performance.json
    └── version_manifest.json           ← version metadata index
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fretpilot.elearning.models import DerivedPriors, EvaluationMetrics

logger = logging.getLogger("fretpilot.elearning.kb_writer")

# KB2 asset filename (constant across versions).
_KB2_FILENAME = "kb2_performance.json"
# All KB domain filenames that should be copied to version snapshots.
_KB_DOMAIN_FILES = (
    "kb1_arrangement.json",
    "kb2_performance.json",
    "kb3_notation.json",
    "kb4_instruments.json",
)
# Manifest filename.
_MANIFEST_FILENAME = "version_manifest.json"


def _stamp_snapshot_version(path: Path, version: str) -> None:
    """Rewrite an asset's ``snapshot_version`` field in place.

    A knowledge snapshot must have one version across all domain files;
    copying an asset from an older snapshot (e.g. kb1/kb3/kb4 which are
    static) would otherwise leave the new version directory inconsistent.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    data["snapshot_version"] = version
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


class KBWriter:
    """Writes empirical priors to versioned KB snapshots."""

    def __init__(self, knowledge_root: str | Path) -> None:
        """Initialise the writer.

        Args:
            knowledge_root: Path to the ``knowledge/`` directory (containing
                ``assets/`` and ``versions/``).
        """
        self._root = Path(knowledge_root)
        self._assets_dir = self._root / "assets"
        self._versions_dir = self._root / "versions"
        self._versions_dir.mkdir(parents=True, exist_ok=True)
        self._manifest_path = self._root / _MANIFEST_FILENAME

    # ─── Write ───

    def write(
        self,
        derived_priors: list[DerivedPriors],
        snapshot_version: str | None = None,
        promote: bool = True,
    ) -> str:
        """Write a new KB version with empirical priors.

        Args:
            derived_priors: List of derived priors to merge into the KB.
            snapshot_version: Optional version string (e.g. ``"2026.08.4"``).
                When ``None``, a timestamp-based version is generated.
            promote: If True (default), copy the new version to ``assets/``
                (the active version used by the pipeline).

        Returns:
            The snapshot version string of the newly written version.
        """
        if snapshot_version is None:
            snapshot_version = datetime.now(timezone.utc).strftime("%Y.%m.%d-%H%M%S")

        version_dir = self._versions_dir / snapshot_version
        if version_dir.exists():
            raise ValueError(
                f"Version directory already exists: {version_dir}. "
                "Use a different snapshot_version or remove the existing one."
            )
        version_dir.mkdir(parents=True, exist_ok=False)

        # 1. Copy all KB assets from the active assets directory, re-stamping
        #    every domain file with the new snapshot version so the version
        #    directory is internally consistent (KnowledgeRegistry requires
        #    all assets in a snapshot to share the same snapshot_version).
        for filename in _KB_DOMAIN_FILES:
            src = self._assets_dir / filename
            dst = version_dir / filename
            if src.exists():
                shutil.copy2(src, dst)
                _stamp_snapshot_version(dst, snapshot_version)
            else:
                logger.debug("Source asset missing: %s", src)

        # 2. Load and update kb2_performance.json with derived priors.
        kb2_path = version_dir / _KB2_FILENAME
        if kb2_path.exists():
            kb2_data = json.loads(kb2_path.read_text(encoding="utf-8"))
        else:
            kb2_data = {
                "snapshot_version": snapshot_version,
                "schema_version": "1",
                "status": "approved",
                "entries": [],
            }

        # 3. Update entries with derived priors.
        kb2_data["snapshot_version"] = snapshot_version
        entries: list[dict[str, Any]] = kb2_data.get("entries", [])

        for prior in derived_priors:
            matched = False
            for entry in entries:
                if entry.get("knowledge_id") == prior.knowledge_id:
                    entry["payload"] = {**entry.get("payload", {}), **prior.payload}
                    entry["knowledge_version"] = snapshot_version
                    entry["provenance"] = {
                        "source_type": "empirical",
                        "source_ids": list(prior.source_ids),
                        "authored_by": "elearning/learning_loop",
                        "notes": (
                            f"Derived from {len(prior.source_ids)} ground truth tabs "
                            f"via {prior.derivation_method}"
                        ),
                    }
                    entry["evaluation"] = {
                        "status": "evaluated",
                        "confidence": prior.confidence,
                        "tested_against": list(prior.source_ids),
                    }
                    matched = True
                    break

            if not matched:
                scope: dict[str, list[str]] = {"style": [prior.style_label]}
                entries.append({
                    "knowledge_id": prior.knowledge_id,
                    "domain": "kb2_performance",
                    "kind": "fingering_priors",
                    "schema_version": "1",
                    "knowledge_version": snapshot_version,
                    "status": "approved",
                    "payload": dict(prior.payload),
                    "scope": scope,
                    "provenance": {
                        "source_type": "empirical",
                        "source_ids": list(prior.source_ids),
                        "authored_by": "elearning/learning_loop",
                        "notes": (
                            f"Derived from {len(prior.source_ids)} ground truth tabs "
                            f"via {prior.derivation_method}"
                        ),
                    },
                    "evaluation": {
                        "status": "evaluated",
                        "confidence": prior.confidence,
                        "tested_against": list(prior.source_ids),
                    },
                })

        kb2_data["entries"] = entries

        # 4. Write the updated KB2 file.
        kb2_path.write_text(
            json.dumps(kb2_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # 5. Update version manifest.
        self._update_manifest(snapshot_version, derived_priors)

        # 6. Promote to active assets directory.
        if promote:
            self._activate_version(snapshot_version)

        logger.info(
            "Wrote KB version %s with %d derived priors",
            snapshot_version, len(derived_priors),
        )
        return snapshot_version

    # ─── Version directory helpers ───

    def version_dir(self, version: str) -> Path:
        """Return the directory path for a specific version."""
        return self._versions_dir / version

    # ─── List / Load / Rollback / Diff ───

    def list_versions(self) -> list[dict[str, Any]]:
        """List all KB versions and their metadata, sorted by version string."""
        manifest = self._load_manifest()
        versions = manifest.get("versions", [])
        return sorted(versions, key=lambda v: v.get("version", ""))

    def load_version(self, version: str):
        """Load a specific KB version.

        Args:
            version: The snapshot version string.

        Returns:
            A :class:`KnowledgeRegistry` loaded from the version directory.
        """
        from fretpilot.knowledge.registry import KnowledgeRegistry

        vdir = self._versions_dir / version
        if not vdir.exists():
            raise FileNotFoundError(f"KB version not found: {version}")

        return KnowledgeRegistry.from_version_dir(vdir)

    def rollback(self, target_version: str) -> None:
        """Roll back the active KB to a specified version.

        Copies the target version's assets into the active ``assets/``
        directory.

        Args:
            target_version: The version to roll back to.
        """
        vdir = self._versions_dir / target_version
        if not vdir.exists():
            raise FileNotFoundError(f"KB version not found: {target_version}")

        self._assets_dir.mkdir(parents=True, exist_ok=True)
        for filename in _KB_DOMAIN_FILES:
            src = vdir / filename
            dst = self._assets_dir / filename
            if src.exists():
                shutil.copy2(src, dst)

        # Update manifest to mark the active version.
        manifest = self._load_manifest()
        manifest["active_version"] = target_version
        self._save_manifest(manifest)

        logger.info("Rolled back active KB to version %s", target_version)

    def diff_versions(
        self,
        version_a: str,
        version_b: str,
    ) -> dict[str, Any]:
        """Compare priors between two KB versions.

        Args:
            version_a: The baseline version.
            version_b: The comparison version.

        Returns:
            A dict with per-entry payload deltas.
        """
        kb2_a = self._load_version_kb2(version_a)
        kb2_b = self._load_version_kb2(version_b)

        entries_a = {e["knowledge_id"]: e for e in kb2_a.get("entries", [])}
        entries_b = {e["knowledge_id"]: e for e in kb2_b.get("entries", [])}

        all_ids = set(entries_a.keys()) | set(entries_b.keys())
        diffs: dict[str, Any] = {}

        for kid in sorted(all_ids):
            ea = entries_a.get(kid, {})
            eb = entries_b.get(kid, {})
            pa = ea.get("payload", {})
            pb = eb.get("payload", {})

            all_keys = set(pa.keys()) | set(pb.keys())
            payload_diff: dict[str, Any] = {}
            for key in sorted(all_keys):
                va = pa.get(key)
                vb = pb.get(key)
                if va != vb:
                    delta = None
                    if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
                        delta = round(vb - va, 6)
                    payload_diff[key] = {"a": va, "b": vb, "delta": delta}

            source_a = ea.get("provenance", {}).get("source_type", "N/A")
            source_b = eb.get("provenance", {}).get("source_type", "N/A")

            diffs[kid] = {
                "payload_diff": payload_diff,
                "source_type_a": source_a,
                "source_type_b": source_b,
            }

        return {
            "version_a": version_a,
            "version_b": version_b,
            "entry_diffs": diffs,
        }

    # ─── Private helpers ───

    def _load_version_kb2(self, version: str) -> dict[str, Any]:
        """Load the kb2_performance.json from a version directory."""
        path = self._versions_dir / version / _KB2_FILENAME
        if not path.exists():
            path = self._assets_dir / _KB2_FILENAME
        if not path.exists():
            return {"entries": []}
        return json.loads(path.read_text(encoding="utf-8"))

    def _update_manifest(
        self,
        version: str,
        derived_priors: list[DerivedPriors],
    ) -> None:
        """Add a new version entry to the manifest."""
        manifest = self._load_manifest()

        entry: dict[str, Any] = {
            "version": version,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_type": "empirical",
            "styles_updated": [p.style_label for p in derived_priors],
            "knowledge_ids_updated": [p.knowledge_id for p in derived_priors],
            "total_sources": sum(len(p.source_ids) for p in derived_priors),
            "avg_confidence": (
                sum(p.confidence for p in derived_priors) / len(derived_priors)
                if derived_priors else 0.0
            ),
            "method": "statistical_mapping",
        }

        manifest.setdefault("versions", []).append(entry)
        manifest["active_version"] = version
        manifest["last_updated"] = entry["timestamp"]

        self._save_manifest(manifest)

    def _activate_version(self, version: str) -> None:
        """Copy a version's assets to the active assets directory."""
        version_dir = self._versions_dir / version
        self._assets_dir.mkdir(parents=True, exist_ok=True)
        for filename in _KB_DOMAIN_FILES:
            src = version_dir / filename
            dst = self._assets_dir / filename
            if src.exists():
                shutil.copy2(src, dst)

    def _load_manifest(self) -> dict[str, Any]:
        """Load the version manifest, creating it if absent."""
        if not self._manifest_path.exists():
            return {"versions": [], "active_version": ""}
        return json.loads(self._manifest_path.read_text(encoding="utf-8"))

    def _save_manifest(self, manifest: dict[str, Any]) -> None:
        """Save the version manifest."""
        self._manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self._manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


class ABComparator:
    """P1-4: A/B evaluation comparator.

    Runs the full :class:`BatchEvaluator` with two different KB versions and
    compares the resulting metrics.
    """

    def __init__(self, knowledge_root: str | Path) -> None:
        """Initialise the comparator.

        Args:
            knowledge_root: Path to the ``knowledge/`` directory.
        """
        self._root = Path(knowledge_root)
        self._writer = KBWriter(knowledge_root)

    def compare(
        self,
        input_dir: str | Path,
        version_a: str,
        version_b: str,
    ) -> dict[str, Any]:
        """Compare two KB versions by running full evaluation on each.

        Args:
            input_dir: Directory of GP files to evaluate.
            version_a: Baseline KB version.
            version_b: Comparison KB version.

        Returns:
            A dict with per-style metric deltas and overall assessment.
        """
        from fretpilot.elearning.evaluate import BatchEvaluator

        dir_a = str(self._root / "versions" / version_a)
        dir_b = str(self._root / "versions" / version_b)

        evaluator_a = BatchEvaluator(knowledge_dir=dir_a)
        result_a = evaluator_a.evaluate_dir(input_dir)

        evaluator_b = BatchEvaluator(knowledge_dir=dir_b)
        result_b = evaluator_b.evaluate_dir(input_dir)

        overall_delta = self._compute_delta(result_a.overall_metrics, result_b.overall_metrics)

        per_style_delta: dict[str, dict[str, float]] = {}
        all_styles = set(result_a.per_style.keys()) | set(result_b.per_style.keys())
        for style in sorted(all_styles):
            ma = result_a.per_style.get(style)
            mb = result_b.per_style.get(style)
            if ma and mb:
                per_style_delta[style] = self._compute_delta(ma, mb)

        acc_delta = overall_delta.get("overall_fingering_accuracy", 0.0)
        assessment = "improvement" if acc_delta > 0 else ("regression" if acc_delta < 0 else "neutral")

        return {
            "version_a": version_a,
            "version_b": version_b,
            "overall_delta": overall_delta,
            "per_style_delta": per_style_delta,
            "assessment": assessment,
            "result_a_summary": {
                "successful": result_a.successful,
                "overall_fingering_accuracy": result_a.overall_metrics.overall_fingering_accuracy,
            },
            "result_b_summary": {
                "successful": result_b.successful,
                "overall_fingering_accuracy": result_b.overall_metrics.overall_fingering_accuracy,
            },
        }

    @staticmethod
    def _compute_delta(
        metrics_a: EvaluationMetrics,
        metrics_b: EvaluationMetrics,
    ) -> dict[str, float]:
        """Compute metric deltas (b - a)."""
        metric_attrs = [
            "string_match_rate",
            "fret_match_rate",
            "position_deviation",
            "chord_shape_match",
            "overall_fingering_accuracy",
            "pitch_accuracy",
            "note_count_match",
            "measure_alignment_rate",
        ]
        deltas: dict[str, float] = {}
        for attr in metric_attrs:
            va = getattr(metrics_a, attr)
            vb = getattr(metrics_b, attr)
            deltas[attr] = round(vb - va, 6)
        return deltas


__all__ = ["KBWriter", "ABComparator"]
