"""Typed application service for the complete BandPilot repair workflow.

The HTTP layer owns authentication and database transactions. This service
owns track preparation, orchestration, result aggregation, and IR persistence,
so there is exactly one repair path for guitar-only, drum-only, and mixed MIDI.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from fretpilot.ai.advisor import (
    ShadowRewriteAdvisor,
    apply_rewrite_decisions,
    build_note_summaries,
    build_policy,
    extract_features,
    validate_decisions,
)
from fretpilot.ai.models import RewriteRequest
from fretpilot.artifacts import ArtifactManifest
from fretpilot.detection.streams import stream_from_track
from fretpilot.engine.cleanup import CleanupResult, auto_detect_tuning, cleanup_streams
from fretpilot.engine.context import NoteRewriteDecision
from fretpilot.engine.drum_pipeline import create_drum_pipeline
from fretpilot.engine.pipeline import create_pipeline
from fretpilot.ir.drum_models import DrumProjectIR
from fretpilot.ir.models import GuitarProjectIR, Transformation
from fretpilot.ir.serde import ir_to_dict
from fretpilot.ir.song import SongIR
from fretpilot.ir.song_adapter import build_song_ir
from fretpilot.knowledge.tunings import GuitarTuning
from fretpilot.midi.models import NormalizedTimeline, NormalizedTrack
from fretpilot.orchestrator.bandpilot import BandPilotOrchestrator, BandPilotResult
from fretpilot.orchestrator.detector import InstrumentFamily, classify_track_family
from fretpilot.validation import validate_song


@dataclass(slots=True)
class TrackPreparation:
    """Traceable preprocessing information for one guitar track."""

    cleanup: CleanupResult
    rewrite: dict[str, Any]


@dataclass(slots=True)
class RepairRun:
    """Complete service result, including per-track preprocessing details."""

    result: BandPilotResult
    preparations: dict[int, TrackPreparation] = field(default_factory=dict)
    song: SongIR | None = None
    guitar: GuitarProjectIR | None = None
    drums: DrumProjectIR | None = None
    midi_fidelity: float = 0.5

    @property
    def primary_preparation(self) -> TrackPreparation | None:
        return next(iter(self.preparations.values()), None)


def _rewrite_transformations(track_index: int, applied: list[dict[str, Any]]) -> list[Transformation]:
    transformations: list[Transformation] = []
    for sequence, action in enumerate(applied, start=1):
        operation = action["operation"]
        if operation == "delete":
            before = {"pitch": action["pitch"], "present": True}
            after = {"present": False}
        else:
            before = {"pitch": action["old_pitch"]}
            after = {"pitch": action["new_pitch"]}
        transformations.append(
            Transformation(
                id=f"rewrite-{track_index}-{sequence:05d}",
                stage="rewrite",
                source_note_index=action["index"],
                before=before,
                after=after,
                confidence=0.8,
                reason=f"LLM shadow rewrite: {operation} ({action.get('reason', '')})",
            )
        )
    return transformations


def _prepare_guitar_track(
    track: NormalizedTrack,
    timeline: NormalizedTimeline,
    advisor: ShadowRewriteAdvisor,
    midi_fidelity: float,
    tuning_override: GuitarTuning | None,
    arrangement_mode: str,
) -> tuple[NormalizedTrack, dict[str, Any], TrackPreparation]:
    stream = stream_from_track(track)
    tuning = tuning_override or auto_detect_tuning([stream])
    cleanup = cleanup_streams(
        [stream], timeline=timeline, tuning=tuning, out_of_range_mode="flag"
    )
    cleaned_stream = cleanup.streams[0] if cleanup.streams else stream
    cleaned_track = NormalizedTrack(
        index=track.index,
        name=cleaned_stream.track_name or track.name,
        notes=list(cleaned_stream.notes),
        instrument_name=cleaned_stream.instrument_name,
        program=cleaned_stream.program,
    )

    features = extract_features(cleaned_track)
    style = advisor.infer_style(features)
    policy = build_policy(midi_fidelity)
    applied: list[dict[str, Any]] = []
    rewrite_degraded = False
    if arrangement_mode != "faithful":
        rewrite_request = RewriteRequest(
            features=features,
            style_label=style.style_label,
            policy=policy,
            note_summaries=build_note_summaries(cleaned_track, tuning),
            tuning_info={
                "id": tuning.id,
                "display_name": tuning.display_name,
                "string_count": tuning.string_count,
                "string_pitches": tuning.string_pitches,
                "min_pitch": tuning.min_pitch,
                "max_pitch": tuning.max_pitch,
            },
        )
        rewrite_response, rewrite_degraded = advisor.propose_rewrite(rewrite_request)
        decisions = validate_decisions(
            rewrite_response.decisions, len(cleaned_track.notes), policy
        )
        if not rewrite_degraded and decisions:
            cleaned_track, applied = apply_rewrite_decisions(cleaned_track, decisions)

    rewrite_summary = {
        "degraded": rewrite_degraded,
        "deletions": sum(action["operation"] == "delete" for action in applied),
        "transpositions": sum(action["operation"] == "transpose" for action in applied),
        "total": len(applied),
        "reasons": [str(action.get("reason", "")) for action in applied[:10]],
    }
    settings = {
        "style_label": style.style_label,
        "tuning": tuning,
        "advisor": advisor.provider,
        "degraded_mode": style.degraded_mode or rewrite_degraded,
        "rewrite_decisions": [
            NoteRewriteDecision(
                index=action["index"],
                operation=action["operation"],
                pitch=action.get("new_pitch"),
                reason=action.get("reason", ""),
            )
            for action in applied
        ],
        "initial_transformations": _rewrite_transformations(track.index, applied),
        "track_id": f"guitar-{track.index}",
        "arrangement_mode": arrangement_mode,
    }
    return cleaned_track, settings, TrackPreparation(cleanup=cleanup, rewrite=rewrite_summary)


def _combine_guitar_irs(irs: list[GuitarProjectIR], title: str) -> GuitarProjectIR | None:
    if not irs:
        return None
    first = irs[0]
    return GuitarProjectIR(
        title=title,
        source=first.source,
        schema_version=first.schema_version,
        tempo_map=list(first.tempo_map),
        time_signatures=list(first.time_signatures),
        tracks=[track for ir in irs for track in ir.tracks],
        knowledge=first.knowledge,
        style_label=first.style_label,
        midi_fidelity=first.midi_fidelity,
        degraded_mode=any(ir.degraded_mode for ir in irs),
        changes=[
            replace(change, id=f"guitar-{ir_index}-{change.id}")
            for ir_index, ir in enumerate(irs, start=1)
            for change in ir.changes
        ],
        warnings=[warning for ir in irs for warning in ir.warnings],
    )


def _combine_drum_irs(irs: list[DrumProjectIR], title: str) -> DrumProjectIR | None:
    if not irs:
        return None
    first = irs[0]
    return DrumProjectIR(
        title=title,
        source=first.source,
        schema_version=first.schema_version,
        tempo_map=list(first.tempo_map),
        time_signatures=list(first.time_signatures),
        tracks=[
            replace(
                track,
                id=(
                    f"drum-{track.source_track_index}"
                    if track.source_track_index is not None
                    else f"drum-{ir_index}-{track_index}"
                ),
            )
            for ir_index, ir in enumerate(irs, start=1)
            for track_index, track in enumerate(ir.tracks, start=1)
        ],
        knowledge=first.knowledge,
        style_label=first.style_label,
        changes=[
            replace(change, id=f"drum-{ir_index}-{change.id}")
            for ir_index, ir in enumerate(irs, start=1)
            for change in ir.changes
        ],
        warnings=[warning for ir in irs for warning in ir.warnings],
    )


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            json.dump(value, temporary, ensure_ascii=False, indent=2)
            temporary.flush()
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


class RepairService:
    """Prepare every supported track and invoke the BandPilot orchestrator."""

    def __init__(
        self,
        advisor: ShadowRewriteAdvisor,
        *,
        knowledge_dir: str | None = None,
    ) -> None:
        self._advisor = advisor
        self._knowledge_dir = knowledge_dir

    @staticmethod
    def clear_persisted_results(project_dir: Path) -> None:
        """Invalidate derived repair artifacts before a new run starts."""
        for filename in (
            "song_ir.json",
            "ir.json",
            "ir_merged.json",
            "repair_manifest.json",
            "artifact_manifest.json",
        ):
            (project_dir / filename).unlink(missing_ok=True)

    def run(
        self,
        timeline: NormalizedTimeline,
        *,
        title: str,
        midi_fidelity: float,
        tuning_override: GuitarTuning | None = None,
        family_overrides: dict[int, str] | None = None,
        arrangement_mode: str = "faithful",
        source_path: Path | None = None,
        source_filename: str = "source.mid",
    ) -> RepairRun:
        track_overrides: dict[int, NormalizedTrack] = {}
        track_settings: dict[int, dict[str, Any]] = {}
        preparations: dict[int, TrackPreparation] = {}
        primary_style = "unknown"

        for track in timeline.tracks:
            if not track.notes:
                continue
            classification = classify_track_family(
                track, (family_overrides or {}).get(track.index)
            )
            if classification.family != InstrumentFamily.GUITAR:
                continue
            cleaned, settings, preparation = _prepare_guitar_track(
                track,
                timeline,
                self._advisor,
                midi_fidelity,
                tuning_override,
                arrangement_mode,
            )
            settings["guitar_role"] = classification.guitar_role
            track_overrides[track.index] = cleaned
            track_settings[track.index] = settings
            preparations[track.index] = preparation
            if primary_style == "unknown":
                primary_style = settings["style_label"]

        orchestrator = BandPilotOrchestrator(
            create_pipeline(self._knowledge_dir),
            create_drum_pipeline(self._knowledge_dir),
        )
        result = orchestrator.run(
            timeline,
            {
                "title": title,
                "midi_fidelity": midi_fidelity,
                "style_label": primary_style,
                "track_overrides": track_overrides,
                "track_settings": track_settings,
                "family_overrides": family_overrides or {},
                "arrangement_mode": arrangement_mode,
            },
        )
        guitar = _combine_guitar_irs(result.guitar_irs, title)
        drums = _combine_drum_irs(result.drum_irs, title)
        provider = self._advisor.provider
        identity = getattr(provider, "identity", None)
        song = build_song_ir(
            title=title,
            source_path=source_path,
            source_filename=source_filename,
            timeline=timeline,
            classifications=result.classifications,
            guitar=guitar,
            drums=drums,
            pitched=result.pitched_irs,
            arrangement_mode=arrangement_mode,
            model_provider=getattr(identity, "provider", "none"),
            model_name=getattr(identity, "model", "none"),
            prompt_version="music-intelligence-v1",
        )
        validation = validate_song(song)
        invalid_track_ids = {
            issue.track_id
            for issue in validation.issues
            if issue.severity == "error" and issue.track_id is not None
        }
        if invalid_track_ids:
            for routed in result.route_results:
                produced_ids = {
                    track.id
                    for ir in (routed.guitar_ir, routed.drum_ir)
                    if ir is not None
                    for track in ir.tracks
                }
                if produced_ids & invalid_track_ids:
                    routed.failed = True
                    routed.error = "Score failed professional playability validation"
                    routed.warnings.append(routed.error)
            for report in result.track_reports:
                routed = next(
                    (item for item in result.route_results if item.track_index == report.track_index),
                    None,
                )
                if routed is not None and routed.failed:
                    report.failed = True
                    report.error = routed.error
                    report.warnings = list(routed.warnings)
        return RepairRun(
            result=result,
            preparations=preparations,
            song=song,
            guitar=guitar,
            drums=drums,
            midi_fidelity=midi_fidelity,
        )

    @staticmethod
    def persist(run: RepairRun, project_dir: Path, title: str) -> None:
        """Atomically persist combined instrument IRs for report and export."""
        project_dir.mkdir(parents=True, exist_ok=True)
        guitar = run.guitar
        drums = run.drums
        if run.song is None:
            raise ValueError("Repair run has no canonical SongIR")
        _write_json_atomic(project_dir / "song_ir.json", run.song.to_dict())
        guitar_path = project_dir / "ir.json"
        if guitar is not None:
            _write_json_atomic(guitar_path, ir_to_dict(guitar))
        elif guitar_path.exists():
            guitar_path.unlink()

        _write_json_atomic(
            project_dir / "ir_merged.json",
            {
                "guitar": ir_to_dict(guitar) if guitar is not None else None,
                "drum": drums.to_dict() if drums is not None else None,
            },
        )
        _write_json_atomic(
            project_dir / "repair_manifest.json",
            {
                "status": run.result.status,
                "tracks": [report.to_dict() for report in run.result.track_reports],
                "warnings": run.result.warnings,
                "passthrough_tracks": [
                    report.to_dict()
                    for report in run.result.track_reports
                    if report.skipped
                ],
                "failed_tracks": [
                    report.to_dict()
                    for report in run.result.track_reports
                    if report.failed
                ],
                "validation": {
                    "status": run.song.validation.status,
                    "issues": [
                        {
                            "code": issue.code,
                            "severity": issue.severity,
                            "message": issue.message,
                            "track_id": issue.track_id,
                            "note_ids": issue.note_ids,
                        }
                        for issue in run.song.validation.issues
                    ],
                },
            },
        )
        manifest = ArtifactManifest.create(
            source_sha256=run.song.source.sha256,
            song_schema_version=run.song.schema_version,
            application_version=run.song.pins.application_version,
            knowledge_snapshot=run.song.pins.knowledge_snapshot,
            model_provider=run.song.pins.model_provider,
            model_name=run.song.pins.model_name,
            prompt_version=run.song.pins.prompt_version,
            arrangement_mode=run.song.arrangement_mode,
            settings={"midi_fidelity": run.midi_fidelity},
            validation_status=run.song.validation.status,
        )
        manifest.capture(
            project_dir,
            ["source.mid", "song_ir.json", "ir.json", "ir_merged.json", "repair_manifest.json"],
        )
        _write_json_atomic(project_dir / "artifact_manifest.json", manifest.to_dict())


__all__ = ["RepairRun", "RepairService", "TrackPreparation"]
