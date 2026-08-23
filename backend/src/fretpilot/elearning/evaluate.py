"""Batch evaluator — orchestrates the full round-trip evaluation.

CLI entry point: ``python -m fretpilot.elearning evaluate --input-dir <dir>``
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fretpilot.elearning.deviation import DeviationCalculator
from fretpilot.elearning.gp_reader import GPReader
from fretpilot.elearning.gp_to_midi import GPMidiConverter
from fretpilot.elearning.models import (
    BatchEvaluationResult,
    EvaluationMetrics,
    EvaluationReport,
)
from fretpilot.elearning.note_aligner import NoteAligner
from fretpilot.elearning.pipeline_runner import PipelineRunner

logger = logging.getLogger("fretpilot.elearning.evaluate")

SUPPORTED_EXTENSIONS = {".gp3", ".gp4", ".gp5"}
SKIP_EXTENSIONS = {".gtp"}  # v2.21 not supported by PyGuitarPro


class BatchEvaluator:
    """P0-6: Orchestrate batch evaluation across a directory of GP files."""

    def __init__(self, knowledge_dir: str | None = None) -> None:
        self._reader = GPReader()
        self._converter = GPMidiConverter()
        self._runner = PipelineRunner(knowledge_dir)
        self._aligner = NoteAligner()
        self._calculator = DeviationCalculator()

    def evaluate_file(
        self, gp_path: str | Path, style_override: str | None = None
    ) -> EvaluationReport:
        """Evaluate a single GP file (full round-trip).

        If *style_override* is given it replaces the auto-inferred style
        label, ensuring KB2 priors are actually looked up.
        """
        gp_path = Path(gp_path)
        warnings: list[str] = []

        # 1. Parse GP → ground truth
        gt_tab = self._reader.parse(gp_path)
        if style_override:
            gt_tab.style_label = style_override

        # 2. Convert GP → MIDI
        fd, midi_path = tempfile.mkstemp(suffix=".mid", prefix="elearning_")
        os.close(fd)
        try:
            self._converter.convert(gt_tab, midi_path)

            # 3. Run pipeline → IR
            ir = self._runner.run(
                midi_path,
                style_label=gt_tab.style_label,
                tuning_pitches=gt_tab.tuning_pitches,
            )

            # 4. Align ground truth with IR
            pairs = self._aligner.align(gt_tab, ir)

            # 5. Calculate deviations
            report = self._calculator.calculate(pairs, gt_tab, ir, warnings)
            return report
        finally:
            try:
                os.unlink(midi_path)
            except OSError:
                pass

    def evaluate_dir(
        self,
        input_dir: str | Path,
        output_path: str | Path | None = None,
        max_files: int | None = None,
    ) -> BatchEvaluationResult:
        """Batch-evaluate all GP files in a directory tree."""
        input_dir = Path(input_dir)
        gp_files = self._scan_gp_files(input_dir, max_files)

        reports: list[EvaluationReport] = []
        failed = 0

        for i, gp_path in enumerate(gp_files):
            try:
                report = self.evaluate_file(gp_path)
                reports.append(report)
                logger.info(
                    "[%d/%d] %s: overall=%.1f%%",
                    i + 1,
                    len(gp_files),
                    gp_path.name,
                    report.metrics.overall_fingering_accuracy * 100,
                )
            except Exception as exc:
                failed += 1
                logger.warning("Failed: %s — %s", gp_path.name, exc)

        # Aggregate
        overall = self._aggregate_overall(reports)
        per_style = self._aggregate_per_style(reports)
        worst = self._worst_files(reports, n=10)

        result = BatchEvaluationResult(
            total_files=len(gp_files),
            successful=len(reports),
            failed=failed,
            skipped=0,
            overall_metrics=overall,
            per_style=per_style,
            worst_files=worst,
            timestamp=datetime.now(timezone.utc).isoformat(),
            kb_snapshot_version="current",
        )

        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info("Report saved: %s", output_path)

        self._print_summary(result)
        return result

    def _scan_gp_files(self, input_dir: Path, max_files: int | None) -> list[Path]:
        """Scan directory for supported GP files."""
        files: list[Path] = []
        for ext in SUPPORTED_EXTENSIONS:
            files.extend(input_dir.rglob(f"*{ext}"))
        files.sort()
        if max_files:
            files = files[:max_files]
        return files

    def _aggregate_overall(self, reports: list[EvaluationReport]) -> EvaluationMetrics:
        """Aggregate metrics across all reports (weighted by aligned count)."""
        if not reports:
            return EvaluationMetrics.empty()

        total_aligned = sum(r.metrics.total_aligned for r in reports)
        total_gt = sum(r.metrics.total_gt_notes for r in reports)
        total_ir = sum(r.metrics.total_ir_notes for r in reports)
        total_unmatched = sum(r.metrics.total_unmatched for r in reports)

        if total_aligned == 0:
            return EvaluationMetrics.empty()

        # Weighted average
        def weighted(metric: str) -> float:
            return sum(
                getattr(report.metrics, metric) * report.metrics.total_aligned
                for report in reports
            ) / total_aligned

        return EvaluationMetrics(
            string_match_rate=weighted("string_match_rate"),
            fret_match_rate=weighted("fret_match_rate"),
            position_deviation=weighted("position_deviation"),
            chord_shape_match=weighted("chord_shape_match"),
            overall_fingering_accuracy=weighted("overall_fingering_accuracy"),
            pitch_accuracy=weighted("pitch_accuracy"),
            note_count_match=total_ir / total_gt if total_gt else 0.0,
            measure_alignment_rate=weighted("measure_alignment_rate"),
            total_aligned=total_aligned,
            total_gt_notes=total_gt,
            total_ir_notes=total_ir,
            total_unmatched=total_unmatched,
        )

    def _aggregate_per_style(
        self, reports: list[EvaluationReport]
    ) -> dict[str, EvaluationMetrics]:
        """Aggregate metrics per style label."""
        style_groups: dict[str, list[EvaluationReport]] = {}
        for r in reports:
            style_groups.setdefault(r.style_label, []).append(r)
        return {
            style: self._aggregate_overall(group)
            for style, group in style_groups.items()
        }

    def _worst_files(
        self, reports: list[EvaluationReport], n: int = 10
    ) -> list[dict[str, Any]]:
        """Return the N files with the lowest fingering accuracy."""
        sorted_reports = sorted(
            reports,
            key=lambda r: r.metrics.overall_fingering_accuracy,
        )
        return [
            {
                "file": r.file_path,
                "style": r.style_label,
                "overall_accuracy": round(r.metrics.overall_fingering_accuracy, 3),
                "string_match": round(r.metrics.string_match_rate, 3),
                "fret_match": round(r.metrics.fret_match_rate, 3),
                "aligned": r.metrics.total_aligned,
            }
            for r in sorted_reports[:n]
        ]

    def _print_summary(self, result: BatchEvaluationResult) -> None:
        """Print a summary table to console."""
        m = result.overall_metrics
        print("\n" + "=" * 60)
        print("  FretPilot Learning Loop — Evaluation Summary")
        print("=" * 60)
        print(f"  Files evaluated:  {result.successful}/{result.total_files}")
        print(f"  Failed:           {result.failed}")
        print(f"  Total aligned:    {m.total_aligned}")
        print(f"  Total GT notes:   {m.total_gt_notes}")
        print(f"  Total IR notes:   {m.total_ir_notes}")
        print("-" * 60)
        print(f"  String Match Rate:      {m.string_match_rate:.1%}")
        print(f"  Fret Match Rate:        {m.fret_match_rate:.1%}")
        print(f"  Overall Fingering Acc:  {m.overall_fingering_accuracy:.1%}")
        print(f"  Position Deviation:     {m.position_deviation:.2f} frets")
        print(f"  Chord Shape Match:      {m.chord_shape_match:.1%}")
        print(f"  Pitch Accuracy:         {m.pitch_accuracy:.1%}")
        print(f"  Note Count Match:       {m.note_count_match:.1%}")
        print("-" * 60)
        if result.per_style:
            print("  Per-style breakdown:")
            for style, metrics in sorted(result.per_style.items()):
                print(
                    f"    {style:12s}  acc={metrics.overall_fingering_accuracy:.1%}  "
                    f"str={metrics.string_match_rate:.1%}  "
                    f"frt={metrics.fret_match_rate:.1%}  "
                    f"n={metrics.total_aligned}"
                )
        print("=" * 60 + "\n")


__all__ = ["BatchEvaluator"]
