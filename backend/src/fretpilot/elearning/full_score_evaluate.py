"""Full-song GP → MIDI → BandPilot → GP5 parse-back evaluation."""

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

from fretpilot.ai.advisor import ShadowRewriteAdvisor
from fretpilot.elearning.gp_reader import GPReader
from fretpilot.elearning.gp_to_midi import GPMidiConverter
from fretpilot.elearning.models import (
    GroundTruthTab,
    GroundTruthTrack,
    ProfessionalScoreCorpus,
)
from fretpilot.elearning.professional_evaluate import SUPPORTED_EXTENSIONS
from fretpilot.elearning.score_roundtrip import ProfessionalScoreComparator
from fretpilot.exporters.registry import SongExporterRegistry
from fretpilot.midi.parser import load_midi
from fretpilot.services.repair import RepairService

logger = logging.getLogger("fretpilot.elearning.full_score_evaluate")


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _even_sample(files: list[Path], maximum: int | None) -> list[Path]:
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


def _source_family(track: GroundTruthTrack) -> str:
    if track.is_percussion:
        return "drums"
    name = track.name.lower()
    if 32 <= track.program <= 39:
        return "bass"
    if 24 <= track.program <= 31:
        return "guitar"
    if "bass" in name or "贝斯" in name:
        return "bass"
    if 0 <= track.program <= 7:
        return "keys"
    if any(
        hint in name for hint in ("piano", "keyboard", "keys", "钢琴", "键盘")
    ):
        return "keys"
    if any(
        hint in name for hint in ("guitar", "gtr", "吉他", "distortion")
    ):
        return "guitar"
    return "generic"


def _normalized_family(value: str) -> str:
    return "generic" if value == "unknown" else value


def _score_export_layout(song) -> list:
    """Mirror GP5SongExporter's stable track ordering."""
    tracks = song.score.tracks
    return [
        *(track for track in tracks if track.family in {"guitar", "bass"}),
        *(track for track in tracks if track.family in {"keys", "generic"}),
        *(track for track in tracks if track.family == "drums"),
    ]


def _as_tab(
    corpus: ProfessionalScoreCorpus,
    track: GroundTruthTrack,
    *,
    file_path: str | None = None,
) -> GroundTruthTab:
    tempo = float(corpus.tempo_map[0]["bpm"]) if corpus.tempo_map else 120.0
    if corpus.time_signature_map:
        first_signature = corpus.time_signature_map[0]
        signature = (
            int(first_signature["numerator"]),
            int(first_signature["denominator"]),
        )
    else:
        signature = (4, 4)
    return GroundTruthTab(
        file_path=file_path or corpus.file_path,
        title=corpus.title,
        style_label=corpus.style_label,
        tempo_bpm=tempo,
        time_signature=signature,
        tuning_pitches=list(track.tuning_pitches),
        notes=[note for note in track.notes if not note.is_tie],
        track_name=track.name,
        techniques=list(track.techniques),
    )


def _merge_tracks(
    corpus: ProfessionalScoreCorpus,
    tracks: list[GroundTruthTrack],
    *,
    source_track: GroundTruthTrack,
) -> GroundTruthTab:
    merged = GroundTruthTrack(
        id="generated-merged",
        name=" + ".join(track.name for track in tracks) or "Not generated",
        program=tracks[0].program if tracks else source_track.program,
        is_percussion=(
            all(track.is_percussion for track in tracks)
            if tracks
            else source_track.is_percussion
        ),
        tuning_pitches=(
            list(tracks[0].tuning_pitches)
            if tracks
            else list(source_track.tuning_pitches)
        ),
        capo=tracks[0].capo if tracks else source_track.capo,
        notes=[note for track in tracks for note in track.notes],
        techniques=[technique for track in tracks for technique in track.techniques],
    )
    return _as_tab(corpus, merged)


def _weighted(items: list[tuple[dict[str, Any], int]], name: str) -> float:
    total = sum(weight for _metrics, weight in items)
    if not total:
        return 0.0
    return sum(float(metrics[name]) * weight for metrics, weight in items) / total


def _micro_technique_metrics(
    items: list[tuple[dict[str, Any], int]],
) -> dict[str, float | int]:
    source = sum(int(metrics["source_techniques"]) for metrics, _weight in items)
    generated = sum(
        int(metrics["generated_techniques"]) for metrics, _weight in items
    )
    aligned = sum(int(metrics["aligned_techniques"]) for metrics, _weight in items)
    precision = aligned / generated if generated else (1.0 if not source else 0.0)
    recall = aligned / source if source else 1.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return {
        "technique_precision": precision,
        "technique_recall": recall,
        "technique_f1": f1,
        "source_techniques": source,
        "generated_techniques": generated,
        "aligned_techniques": aligned,
    }


class FullSongRoundTripEvaluator:
    """Evaluate every source track through the canonical SongIR product path."""

    def __init__(self, knowledge_dir: str | None = None) -> None:
        assets = knowledge_dir or str(
            Path(__file__).resolve().parent.parent / "knowledge" / "assets"
        )
        self._reader = GPReader()
        self._converter = GPMidiConverter()
        self._repair = RepairService(
            ShadowRewriteAdvisor(),
            knowledge_dir=assets,
        )
        self._exporters = SongExporterRegistry.default()
        self._comparator = ProfessionalScoreComparator()

    def evaluate_file(
        self,
        gp_path: str | Path,
        *,
        generated_path: str | Path | None = None,
    ) -> dict[str, Any]:
        source_path = Path(gp_path)
        source = self._reader.parse_corpus(source_path)
        midi_fd, midi_name = tempfile.mkstemp(
            suffix=".mid", prefix="bandpilot-full-roundtrip-"
        )
        os.close(midi_fd)
        owns_generated = generated_path is None
        if generated_path is None:
            gp_fd, gp_name = tempfile.mkstemp(
                suffix=".gp5", prefix="bandpilot-full-roundtrip-"
            )
            os.close(gp_fd)
            generated = Path(gp_name)
        else:
            generated = Path(generated_path)
            generated.parent.mkdir(parents=True, exist_ok=True)

        try:
            self._converter.convert_corpus(source, midi_name)
            timeline = load_midi(midi_name)
            run = self._repair.run(
                timeline,
                title=source.title,
                midi_fidelity=0.5,
                arrangement_mode="faithful",
                source_path=Path(midi_name),
                source_filename=source_path.name,
            )
            if run.song is None:
                raise RuntimeError("Repair service did not produce canonical SongIR")
            export_result = self._exporters.export("gp5", run.song, generated)
            generated_corpus = self._reader.parse_corpus(
                generated,
                style_label=source.style_label,
            )
            return self._compare_song(
                source,
                generated_corpus,
                run,
                export_result,
                generated_file=(str(generated) if not owns_generated else "ephemeral"),
            )
        finally:
            Path(midi_name).unlink(missing_ok=True)
            if owns_generated:
                generated.unlink(missing_ok=True)

    def _compare_song(
        self,
        source: ProfessionalScoreCorpus,
        generated: ProfessionalScoreCorpus,
        run,
        export_result,
        *,
        generated_file: str,
    ) -> dict[str, Any]:
        song = run.song
        layout = _score_export_layout(song)
        layout_warning = None
        if len(layout) != len(generated.tracks):
            layout_warning = (
                f"Expected {len(layout)} exported tracks but GP5 parse-back has "
                f"{len(generated.tracks)}"
            )

        generated_by_source: dict[int, list[GroundTruthTrack]] = defaultdict(list)
        generated_families: dict[int, set[str]] = defaultdict(set)
        for score_track, parsed_track in zip(layout, generated.tracks):
            for source_index in score_track.source_track_indices:
                generated_by_source[source_index].append(parsed_track)
                generated_families[source_index].add(score_track.family)

        assignments = {
            assignment.source_track_index: assignment
            for assignment in song.analysis.track_assignments
        }
        routes = {report.track_index: report for report in run.result.track_reports}
        track_reports: list[dict[str, Any]] = []
        metric_items: list[tuple[dict[str, Any], int]] = []
        fretted_items: list[tuple[dict[str, Any], int]] = []
        mismatch_totals: Counter[str] = Counter()
        classification_correct = 0
        classification_total = 0

        for source_index, source_track in enumerate(source.tracks, start=1):
            source_tab = _as_tab(source, source_track)
            if not source_tab.notes:
                continue
            expected_family = _source_family(source_track)
            assignment = assignments.get(source_index)
            detected_family = assignment.family if assignment else "missing"
            classification_total += 1
            is_classification_correct = (
                _normalized_family(detected_family) == expected_family
            )
            classification_correct += is_classification_correct
            generated_tracks = generated_by_source.get(source_index, [])
            generated_tab = _merge_tracks(
                generated,
                generated_tracks,
                source_track=source_track,
            )
            comparison = self._comparator.compare(
                source_tab,
                generated_tab,
                generated_file=generated_file,
                instrument_family=expected_family,
                evaluate_fingering=expected_family in {"guitar", "bass"},
                warnings=([layout_warning] if layout_warning else []),
            )
            comparison_dict = comparison.to_dict()
            weight = comparison.metrics.source_notes
            metric_items.append((comparison.metrics.to_dict(), weight))
            if expected_family in {"guitar", "bass"}:
                fretted_items.append((comparison.metrics.to_dict(), weight))
            mismatch_totals.update(comparison.mismatch_counts)
            route = routes.get(source_index)
            track_reports.append(
                {
                    "source_track_number": source_index,
                    "source_track_name": source_track.name,
                    "source_program": source_track.program,
                    "expected_family": expected_family,
                    "detected_family": detected_family,
                    "classification_correct": is_classification_correct,
                    "classification_reason": assignment.reason if assignment else "missing",
                    "generated_families": sorted(generated_families.get(source_index, set())),
                    "generated_track_names": [track.name for track in generated_tracks],
                    "route_status": (
                        "failed"
                        if route and route.failed
                        else "skipped"
                        if route and route.skipped
                        else "processed"
                        if route
                        else "missing"
                    ),
                    "route_error": route.error if route else None,
                    "comparison": comparison_dict,
                }
            )

        source_notes = sum(metrics["source_notes"] for metrics, _weight in metric_items)
        generated_notes = sum(
            len([note for note in track.notes if not note.is_tie])
            for track in generated.tracks
        )
        aligned_notes = sum(metrics["aligned_notes"] for metrics, _weight in metric_items)
        overall = {
            "source_notes": source_notes,
            "generated_notes": generated_notes,
            "aligned_notes": aligned_notes,
            "note_recall": aligned_notes / source_notes if source_notes else 1.0,
            "note_precision": aligned_notes / generated_notes if generated_notes else 0.0,
            "onset_exact_rate": _weighted(metric_items, "onset_exact_rate"),
            "duration_exact_rate": _weighted(metric_items, "duration_exact_rate"),
            "exact_fingering_rate": _weighted(
                fretted_items, "exact_fingering_rate"
            ),
            "chord_shape_match_rate": _weighted(
                fretted_items, "chord_shape_match_rate"
            ),
            "professional_score_score": _weighted(
                metric_items, "professional_score_score"
            ),
            "classification_accuracy": (
                classification_correct / classification_total
                if classification_total
                else 1.0
            ),
        }
        overall.update(_micro_technique_metrics(metric_items))
        return {
            "schema_version": "1.0",
            "evaluation_scope": "full_song_actual_product_songir_gp5_parseback",
            "source_file": source.file_path,
            "generated_file": generated_file,
            "style_label": source.style_label,
            "source_track_count": len(source.tracks),
            "generated_track_count": len(generated.tracks),
            "export_note_count": export_result.note_count,
            "repair_status": run.result.status,
            "validation_status": song.validation.status,
            "validation_issues": [
                {
                    "code": issue.code,
                    "severity": issue.severity,
                    "track_id": issue.track_id,
                    "note_ids": list(issue.note_ids),
                    "message": issue.message,
                }
                for issue in song.validation.issues
            ],
            "overall": overall,
            "mismatch_totals": dict(mismatch_totals),
            "track_reports": track_reports,
            "warnings": [
                *([layout_warning] if layout_warning else []),
                *export_result.warnings,
                *run.result.warnings,
            ],
        }

    def scan_files(self, input_dir: str | Path) -> tuple[list[Path], int]:
        root = Path(input_dir)
        files = sorted(
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
        )
        unique: list[Path] = []
        seen: set[str] = set()
        duplicates = 0
        for path in files:
            digest = _digest(path)
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
        reports: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        for index, source_path in enumerate(selected, start=1):
            generated_path = None
            if generated_root is not None:
                relative = source_path.relative_to(root).with_suffix(".generated.gp5")
                generated_path = generated_root / relative
            try:
                report = self.evaluate_file(
                    source_path,
                    generated_path=generated_path,
                )
                reports.append(report)
                logger.info(
                    "[%d/%d] %.1f%% %s (%d tracks)",
                    index,
                    len(selected),
                    report["overall"]["professional_score_score"] * 100,
                    source_path.name,
                    report["source_track_count"],
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
            root,
            candidates=len(files),
            duplicate_files=duplicates,
            selected=len(selected),
            reports=reports,
            failures=failures,
        )
        if output_path is not None:
            destination = Path(output_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return result

    @staticmethod
    def _batch_result(
        root: Path,
        *,
        candidates: int,
        duplicate_files: int,
        selected: int,
        reports: list[dict[str, Any]],
        failures: list[dict[str, str]],
    ) -> dict[str, Any]:
        file_items = [
            (report["overall"], int(report["overall"]["source_notes"]))
            for report in reports
        ]
        metric_names = (
            "note_recall",
            "note_precision",
            "onset_exact_rate",
            "duration_exact_rate",
            "exact_fingering_rate",
            "chord_shape_match_rate",
            "professional_score_score",
            "classification_accuracy",
        )
        overall = {name: _weighted(file_items, name) for name in metric_names}
        overall.update(_micro_technique_metrics(file_items))
        overall.update(
            {
                "source_notes": sum(item["source_notes"] for item, _weight in file_items),
                "generated_notes": sum(
                    item["generated_notes"] for item, _weight in file_items
                ),
                "aligned_notes": sum(item["aligned_notes"] for item, _weight in file_items),
            }
        )
        family_items: dict[str, list[tuple[dict[str, Any], int]]] = defaultdict(list)
        mismatch_totals: Counter[str] = Counter()
        for report in reports:
            mismatch_totals.update(report["mismatch_totals"])
            for track_report in report["track_reports"]:
                metrics = track_report["comparison"]["metrics"]
                family_items[track_report["expected_family"]].append(
                    (metrics, int(metrics["source_notes"]))
                )
        per_family = {
            family: {
                "tracks": len(items),
                "source_notes": sum(weight for _metrics, weight in items),
                "note_recall": _weighted(items, "note_recall"),
                "onset_exact_rate": _weighted(items, "onset_exact_rate"),
                "duration_exact_rate": _weighted(items, "duration_exact_rate"),
                "exact_fingering_rate": (
                    _weighted(items, "exact_fingering_rate")
                    if family in {"guitar", "bass"}
                    else None
                ),
                **_micro_technique_metrics(items),
                "professional_score_score": _weighted(
                    items, "professional_score_score"
                ),
            }
            for family, items in sorted(family_items.items())
        }
        return {
            "schema_version": "1.0",
            "evaluation_scope": "full_song_actual_product_songir_gp5_parseback",
            "corpus_root": str(root),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "candidate_files": candidates,
            "duplicate_files_skipped": duplicate_files,
            "selected_files": selected,
            "successful_files": len(reports),
            "failed_files": len(failures),
            "overall": overall,
            "per_family": per_family,
            "mismatch_totals": dict(mismatch_totals),
            "worst_files": sorted(
                (
                    {
                        "file": report["source_file"],
                        "score": report["overall"]["professional_score_score"],
                        "repair_status": report["repair_status"],
                    }
                    for report in reports
                ),
                key=lambda item: item["score"],
            )[:20],
            "failures": failures,
            "reports": reports,
        }


__all__ = ["FullSongRoundTripEvaluator"]
