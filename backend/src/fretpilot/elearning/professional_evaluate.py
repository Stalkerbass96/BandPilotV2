"""Batch GTP → MIDI → BandPilot → GP5 → parse-back evaluator."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fretpilot.elearning.gp_reader import GPReader
from fretpilot.elearning.gp_to_midi import GPMidiConverter
from fretpilot.elearning.pipeline_runner import PipelineRunner
from fretpilot.elearning.score_roundtrip import (
    ProfessionalScoreComparator,
    ScoreRoundTripReport,
)
from fretpilot.exporters.gp5 import GP5Exporter

logger = logging.getLogger("fretpilot.elearning.professional_evaluate")
SUPPORTED_EXTENSIONS = frozenset({".gp3", ".gp4", ".gp5"})


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _even_sample(files: list[Path], maximum: int | None) -> list[Path]:
    """Deterministically sample across the full sorted corpus, not its first folder."""
    if maximum is None or maximum >= len(files):
        return files
    if maximum <= 0:
        return []
    if maximum == 1:
        return [files[len(files) // 2]]
    indexes = {
        round(index * (len(files) - 1) / (maximum - 1))
        for index in range(maximum)
    }
    return [files[index] for index in sorted(indexes)]


class ProfessionalRoundTripEvaluator:
    """Evaluate the real serialized GP5 product boundary."""

    def __init__(self, knowledge_dir: str | None = None) -> None:
        self._reader = GPReader()
        self._converter = GPMidiConverter()
        self._runner = PipelineRunner(knowledge_dir)
        self._exporter = GP5Exporter()
        self._comparator = ProfessionalScoreComparator()

    def evaluate_file(
        self,
        gp_path: str | Path,
        *,
        generated_path: str | Path | None = None,
        style_override: str | None = None,
    ) -> ScoreRoundTripReport:
        source_path = Path(gp_path)
        source_score = self._reader.parse(source_path, style_label=style_override)
        midi_fd, midi_name = tempfile.mkstemp(suffix=".mid", prefix="bandpilot-roundtrip-")
        os.close(midi_fd)
        owns_gp_output = generated_path is None
        if generated_path is None:
            gp_fd, gp_name = tempfile.mkstemp(suffix=".gp5", prefix="bandpilot-roundtrip-")
            os.close(gp_fd)
            generated = Path(gp_name)
        else:
            generated = Path(generated_path)
            generated.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._converter.convert(source_score, midi_name)
            repaired = self._runner.run(
                midi_name,
                style_label=source_score.style_label,
                tuning_pitches=source_score.tuning_pitches,
            )
            export_result = self._exporter.export(repaired, generated)
            generated_score = self._reader.parse(
                generated,
                style_label=source_score.style_label,
            )
            warnings = list(export_result.warnings)
            if len(source_score.tuning_pitches) != len(generated_score.tuning_pitches):
                warnings.append("Generated score string count differs from source track.")
            return self._comparator.compare(
                source_score,
                generated_score,
                generated_file=str(generated) if not owns_gp_output else "ephemeral",
                warnings=warnings,
            )
        finally:
            Path(midi_name).unlink(missing_ok=True)
            if owns_gp_output:
                generated.unlink(missing_ok=True)

    def scan_files(self, input_dir: str | Path, *, deduplicate: bool = True) -> tuple[list[Path], int]:
        root = Path(input_dir)
        files = sorted(
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
        )
        if not deduplicate:
            return files, 0
        unique: list[Path] = []
        seen: set[str] = set()
        duplicates = 0
        for path in files:
            digest = _file_digest(path)
            if digest in seen:
                duplicates += 1
                continue
            seen.add(digest)
            unique.append(path)
        return unique, duplicates

    def evaluate_dir(
        self,
        input_dir: str | Path,
        *,
        output_path: str | Path | None = None,
        generated_dir: str | Path | None = None,
        max_files: int | None = None,
    ) -> dict[str, Any]:
        root = Path(input_dir)
        files, duplicates = self.scan_files(root)
        selected = _even_sample(files, max_files)
        generated_root = Path(generated_dir) if generated_dir else None
        reports: list[ScoreRoundTripReport] = []
        failures: list[dict[str, str]] = []
        for index, source_path in enumerate(selected, start=1):
            generated_path = None
            if generated_root is not None:
                relative = source_path.relative_to(root).with_suffix(".generated.gp5")
                generated_path = generated_root / relative
            try:
                report = self.evaluate_file(source_path, generated_path=generated_path)
                reports.append(report)
                logger.info(
                    "[%d/%d] %.1f%% %s",
                    index,
                    len(selected),
                    report.metrics.professional_score_score * 100,
                    source_path.name,
                )
            except Exception as exc:
                failures.append(
                    {
                        "file": str(source_path),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
                logger.warning("[%d/%d] failed %s: %s", index, len(selected), source_path, exc)

        result = self._batch_result(
            root=root,
            candidates=len(files),
            selected=len(selected),
            duplicate_files=duplicates,
            reports=reports,
            failures=failures,
        )
        if output_path is not None:
            destination = Path(output_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return result

    def _batch_result(
        self,
        *,
        root: Path,
        candidates: int,
        selected: int,
        duplicate_files: int,
        reports: list[ScoreRoundTripReport],
        failures: list[dict[str, str]],
    ) -> dict[str, Any]:
        weights = [report.metrics.source_notes for report in reports]
        total_weight = sum(weights)

        def weighted(name: str) -> float:
            if not total_weight:
                return 0.0
            return sum(
                float(getattr(report.metrics, name)) * weight
                for report, weight in zip(reports, weights, strict=True)
            ) / total_weight

        metric_names = (
            "note_recall",
            "note_precision",
            "onset_exact_rate",
            "duration_exact_rate",
            "onset_mae_beats",
            "duration_mae_beats",
            "string_match_rate",
            "fret_match_rate",
            "exact_fingering_rate",
            "chord_shape_match_rate",
            "technique_precision",
            "technique_recall",
            "technique_f1",
            "professional_score_score",
        )
        overall = {name: weighted(name) for name in metric_names}
        source_techniques = sum(
            report.metrics.source_techniques for report in reports
        )
        generated_techniques = sum(
            report.metrics.generated_techniques for report in reports
        )
        aligned_techniques = sum(
            report.metrics.aligned_techniques for report in reports
        )
        technique_precision = (
            aligned_techniques / generated_techniques
            if generated_techniques
            else (1.0 if not source_techniques else 0.0)
        )
        technique_recall = (
            aligned_techniques / source_techniques if source_techniques else 1.0
        )
        overall.update(
            {
                "technique_precision": technique_precision,
                "technique_recall": technique_recall,
                "technique_f1": (
                    2
                    * technique_precision
                    * technique_recall
                    / (technique_precision + technique_recall)
                    if technique_precision + technique_recall
                    else 0.0
                ),
                "source_techniques": source_techniques,
                "generated_techniques": generated_techniques,
                "aligned_techniques": aligned_techniques,
            }
        )
        totals = Counter()
        for report in reports:
            totals.update(report.mismatch_counts)
        per_style_reports: dict[str, list[ScoreRoundTripReport]] = defaultdict(list)
        for report in reports:
            per_style_reports[report.style_label].append(report)
        per_style = {
            style: {
                "files": len(items),
                "source_notes": sum(item.metrics.source_notes for item in items),
                "professional_score_score": (
                    sum(
                        item.metrics.professional_score_score * item.metrics.source_notes
                        for item in items
                    )
                    / sum(item.metrics.source_notes for item in items)
                ),
            }
            for style, items in sorted(per_style_reports.items())
        }
        worst = sorted(
            reports, key=lambda report: report.metrics.professional_score_score
        )[:20]
        return {
            "schema_version": "1.0",
            "evaluation_scope": "primary_non_percussion_track_actual_gp5_parseback",
            "corpus_root": str(root),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "candidate_files": candidates,
            "duplicate_files_skipped": duplicate_files,
            "selected_files": selected,
            "successful_files": len(reports),
            "failed_files": len(failures),
            "overall": overall,
            "mismatch_totals": dict(totals),
            "per_style": per_style,
            "worst_files": [
                {
                    "file": report.source_file,
                    "score": report.metrics.professional_score_score,
                    "metrics": report.metrics.to_dict(),
                }
                for report in worst
            ],
            "failures": failures,
            "reports": [report.to_dict() for report in reports],
        }


__all__ = ["ProfessionalRoundTripEvaluator", "SUPPORTED_EXTENSIONS"]
