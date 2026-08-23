"""Project routes — create, list, detail, repair, status, report."""

from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from fretpilot.ai.advisor import ShadowRewriteAdvisor
from fretpilot.ai.crypto import get_key_vault
from fretpilot.ai.providers.openai_compatible import OpenAICompatibleAdvisor
from fretpilot.api.deps import get_current_user
from fretpilot.config import get_settings
from fretpilot.db.models import ByokConfig, Project, RepairJob, User
from fretpilot.db.session import get_db, session_scope
from fretpilot.ir.serde import load_ir, load_merged_irs
from fretpilot.ir.song_serde import load_song_ir
from fretpilot.knowledge.tunings import GuitarTuning, TuningRegistry
from fretpilot.midi.parser import load_midi
from fretpilot.orchestrator import classify_track_family
from fretpilot.services.repair import RepairService

logger = logging.getLogger("fretpilot.api.projects")
router = APIRouter()


class ProjectResponse(BaseModel):
    id: int
    title: str
    source_filename: str
    status: str
    style_label: str
    degraded_mode: bool
    instrument_family: str


class RepairRequest(BaseModel):
    midi_fidelity: float = Field(default=0.5, ge=0.0, le=1.0)
    tuning_id: str | None = None  # NEW: 用户覆盖定弦；None 则 auto_detect
    arrangement_mode: Literal["faithful", "playable_arrangement", "creative_rewrite"] = (
        "faithful"
    )
    family_overrides: dict[int, Literal["guitar", "drums", "bass", "keys", "unknown"]] = (
        Field(default_factory=dict)
    )


class TrackFamilyOverrideRequest(BaseModel):
    family: Literal["guitar", "drums", "bass", "keys", "unknown"]


class CleanupInfo(BaseModel):
    """Cleanup 阶段的可追溯摘要（定弦、tempo 去重、超范围音高等）。"""

    tuning_id: str
    tuning_display_name: str
    tempo_dedup_count: int
    out_of_range_count: int
    velocity_remapped: bool
    overlaps_truncated: int
    total_actions: int


class RewriteInfo(BaseModel):
    """Shadow rewrite summary."""

    degraded: bool
    deletions: int
    transpositions: int
    total: int
    reasons: list[str] = Field(default_factory=list)


class SeparationSegmentInfo(BaseModel):
    """A single riff/melody separation segment summary."""

    start_measure: int
    end_measure: int
    split_pitch: int
    low_note_count: int
    high_note_count: int
    confidence: float
    reason: str


class SeparationInfo(BaseModel):
    """Stream separation summary (riff → Rhythm, melody → Lead)."""

    detected: bool
    total_confidence: float
    segments: list[SeparationSegmentInfo] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TrackRepairInfo(BaseModel):
    """Stable API contract for one physical source track outcome."""

    track_index: int
    track_name: str
    family: str
    module: str
    stages_completed: int
    note_count: int
    change_count: int
    drum_report: dict[str, Any] = Field(default_factory=dict)
    skipped: bool = False
    failed: bool = False
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)


class RepairResponse(BaseModel):
    project_id: int
    job_id: int = 0
    status: str
    style_label: str
    degraded_mode: bool
    note_count: int
    change_count: int
    cleanup: CleanupInfo | None = None
    rewrite: RewriteInfo | None = None
    separation: SeparationInfo | None = None
    tracks_repaired: list[TrackRepairInfo] = Field(default_factory=list)
    has_drums: bool = False
    arrangement_mode: str = "faithful"
    validation_status: str = "not_validated"
    validation_issues: list[dict[str, Any]] = Field(default_factory=list)


class RepairJobResponse(BaseModel):
    id: int
    run_id: str | None
    status: str
    progress: float
    arrangement_mode: str
    settings: dict[str, Any]
    result: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


def _repair_job_response(job: RepairJob) -> dict[str, Any]:
    return RepairJobResponse(
        id=job.id,
        run_id=job.run_id,
        status=job.status,
        progress=job.progress,
        arrangement_mode=job.arrangement_mode,
        settings=json.loads(job.settings_json),
        result=json.loads(job.result_json) if job.result_json else None,
        error_message=job.error_message,
        created_at=job.created_at,
        completed_at=job.completed_at,
    ).model_dump(mode="json")


def _project_path(user: User, project_id: int) -> Path:
    """Return the storage directory for a project."""
    path = get_settings().job_root_path / str(user.id) / str(project_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _build_advisor(user: User, db: Session) -> ShadowRewriteAdvisor:
    """Build a ShadowRewriteAdvisor from the user's BYOK config (or None)."""
    config = db.query(ByokConfig).filter(ByokConfig.user_id == user.id).first()
    if config is None:
        return ShadowRewriteAdvisor(None)
    vault = get_key_vault()
    try:
        api_key = vault.decrypt(config.encrypted_key)
    except Exception:
        logger.warning("Failed to decrypt BYOK key for user %s", user.id)
        return ShadowRewriteAdvisor(None)
    base_url = config.base_url or "https://api.openai.com/v1"
    model = config.model or "gpt-4o-mini"
    provider = OpenAICompatibleAdvisor(
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout=get_settings().llm_request_timeout,
    )
    return ShadowRewriteAdvisor(provider)


def _resolve_tuning(tuning_id: str | None) -> GuitarTuning | None:
    """解析用户覆盖定弦：None 回退 auto_detect，非法 ID 抛 400。

    遵循 "auto-detect + user override" 原则——用户显式指定时使用该定弦；
    未指定（None）时由 ``RepairService`` 按吉他轨独立自动检测。
    """
    if tuning_id is None:
        return None
    tuning = TuningRegistry.default().get(tuning_id)
    if tuning is None:
        raise HTTPException(400, f"Unknown tuning_id: {tuning_id}")
    return tuning


@router.get("", response_model=dict)
def list_projects(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """List the current user's projects."""
    projects = (
        db.query(Project)
        .filter(Project.user_id == user.id)
        .order_by(Project.created_at.desc())
        .all()
    )
    items = [
        ProjectResponse(
            id=p.id, title=p.title, source_filename=p.source_filename,
            status=p.status, style_label=p.style_label, degraded_mode=p.degraded_mode,
            instrument_family=p.instrument_family,
        ).model_dump()
        for p in projects
    ]
    return {"code": 0, "data": {"items": items, "total": len(items)}, "message": "ok"}


@router.post("", response_model=dict)
async def create_project(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Create a project by uploading a MIDI file."""
    settings = get_settings()
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(413, f"File too large (max {settings.max_upload_bytes} bytes)")
    if not file.filename or not file.filename.lower().endswith((".mid", ".midi")):
        raise HTTPException(415, "Only .mid/.midi files are supported")

    try:
        with tempfile.NamedTemporaryFile(suffix=".mid") as temporary:
            temporary.write(content)
            temporary.flush()
            timeline = load_midi(Path(temporary.name))
    except Exception as exc:
        raise HTTPException(422, "The uploaded file is not a valid MIDI file") from exc

    project = Project(
        user_id=user.id,
        title=title or Path(file.filename).stem,
        source_filename=file.filename,
        status="imported",
    )
    db.add(project)
    db.flush()

    project_dir = _project_path(user, project.id)
    source_path = project_dir / "source.mid"
    source_path.write_bytes(content)

    family_classifications = [
        classify_track_family(track) for track in timeline.tracks if track.notes
    ]
    families = {classification.family.value for classification in family_classifications}
    if families:
        project.instrument_family = next(iter(families)) if len(families) == 1 else "mixed"

    project.track_summary = json.dumps(
        {
            "tracks": [
                {
                    "index": classification.track_index,
                    "name": classification.track_name,
                    "family": classification.family.value,
                    "is_guitar": classification.is_guitar,
                    "is_drum": classification.is_drum,
                    "role": classification.guitar_role,
                    "confidence": classification.confidence,
                    "reason": classification.reason,
                    "user_overridden": classification.user_overridden,
                    "note_count": classification.note_count,
                }
                for classification in family_classifications
            ],
            "primary_guitar_track": next(
                (
                    classification.track_index
                    for classification in family_classifications
                    if classification.is_guitar
                ),
                None,
            ),
        },
        ensure_ascii=False,
    )
    db.commit()

    return {"code": 0, "data": ProjectResponse(
        id=project.id, title=project.title, source_filename=project.source_filename,
        status=project.status, style_label=project.style_label, degraded_mode=project.degraded_mode,
        instrument_family=project.instrument_family,
    ).model_dump(), "message": "ok"}


@router.get("/{project_id}", response_model=dict)
def get_project(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return project details including track summary."""
    project = _get_user_project(db, user, project_id)
    tracks = json.loads(project.track_summary) if project.track_summary else {"tracks": []}
    return {"code": 0, "data": {
        "id": project.id, "title": project.title,
        "source_filename": project.source_filename, "status": project.status,
        "style_label": project.style_label, "degraded_mode": project.degraded_mode,
        "instrument_family": project.instrument_family,
        "tracks": tracks.get("tracks", []),
    }, "message": "ok"}


@router.get("/{project_id}/tracks", response_model=dict)
def get_project_tracks(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return track list with instrument family info.

    Uses the BandPilot family classifier to detect each track's instrument
    family (guitar, drums, bass, keys, unknown) and includes drum-specific
    metadata (kit type, detected pieces) when applicable.
    """
    project = _get_user_project(db, user, project_id)
    project_dir = _project_path(user, project.id)
    source_path = project_dir / "source.mid"
    if not source_path.exists():
        raise HTTPException(404, "Source MIDI file not found")

    timeline = load_midi(source_path)
    summary = json.loads(project.track_summary) if project.track_summary else {"tracks": []}
    stored_overrides = {
        int(item["index"]): str(item["family"])
        for item in summary.get("tracks", [])
        if item.get("user_overridden")
    }
    tracks_info: list[dict[str, Any]] = []
    for track in timeline.tracks:
        if not track.notes:
            continue
        cls = classify_track_family(track, stored_overrides.get(track.index))
        info: dict[str, Any] = {
            "index": cls.track_index,
            "name": cls.track_name,
            "family": cls.family.value,
            "is_guitar": cls.is_guitar,
            "is_drum": cls.is_drum,
            "role": cls.guitar_role,
            "confidence": cls.confidence,
            "reason": cls.reason,
            "user_overridden": cls.user_overridden,
            "note_count": cls.note_count,
        }
        if cls.is_drum:
            info["kit_type"] = cls.kit_type
            info["detected_pieces"] = cls.detected_pieces
        tracks_info.append(info)

    return {"code": 0, "data": {"tracks": tracks_info, "total": len(tracks_info)}, "message": "ok"}


@router.put("/{project_id}/tracks/{track_index}", response_model=dict)
def override_project_track_family(
    project_id: int,
    track_index: int,
    req: TrackFamilyOverrideRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Persist an explicit user correction for an uncertain track family."""

    project = _get_user_project(db, user, project_id)
    source_path = _project_path(user, project.id) / "source.mid"
    if not source_path.is_file():
        raise HTTPException(404, "Source MIDI file not found")
    timeline = load_midi(source_path)
    track = next(
        (item for item in timeline.tracks if item.index == track_index and item.notes),
        None,
    )
    if track is None:
        raise HTTPException(404, "Note-bearing track not found")

    corrected = classify_track_family(track, req.family)
    summary = json.loads(project.track_summary) if project.track_summary else {"tracks": []}
    entries = {
        int(item["index"]): dict(item)
        for item in summary.get("tracks", [])
    }
    entries[track_index] = {
        "index": corrected.track_index,
        "name": corrected.track_name,
        "family": corrected.family.value,
        "is_guitar": corrected.is_guitar,
        "is_drum": corrected.is_drum,
        "role": corrected.guitar_role,
        "confidence": corrected.confidence,
        "reason": corrected.reason,
        "user_overridden": True,
        "note_count": corrected.note_count,
    }
    summary["tracks"] = [entries[index] for index in sorted(entries)]
    project.track_summary = json.dumps(summary, ensure_ascii=False)
    families = {str(item["family"]) for item in summary["tracks"]}
    project.instrument_family = next(iter(families)) if len(families) == 1 else "mixed"
    db.commit()
    return {"code": 0, "data": entries[track_index], "message": "ok"}


def _get_user_project(db: Session, user: User, project_id: int) -> Project:
    """Fetch a project owned by the user, or 404."""
    project = db.query(Project).filter(
        Project.id == project_id, Project.user_id == user.id
    ).first()
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


def _execute_repair(
    project_id: int,
    req: RepairRequest,
    user: User,
    db: Session,
    repair_job: RepairJob | None = None,
) -> dict:
    """Run one repair using either a new or pre-created durable job."""
    project = _get_user_project(db, user, project_id)
    project_dir = _project_path(user, project.id)
    source_path = project_dir / "source.mid"
    if not source_path.is_file():
        raise HTTPException(404, "Source MIDI file not found")

    tuning_override = _resolve_tuning(req.tuning_id)
    summary = json.loads(project.track_summary) if project.track_summary else {"tracks": []}
    persisted_overrides = {
        int(item["index"]): str(item["family"])
        for item in summary.get("tracks", [])
        if item.get("user_overridden")
    }
    family_overrides = {**persisted_overrides, **req.family_overrides}
    if repair_job is None:
        project.status = "processing"
        repair_job = RepairJob(
            project_id=project.id,
            status="processing",
            progress=0.0,
            arrangement_mode=req.arrangement_mode,
            settings_json=json.dumps(
                {
                    "midi_fidelity": req.midi_fidelity,
                    "tuning_id": req.tuning_id,
                    "family_overrides": family_overrides,
                },
                ensure_ascii=False,
            ),
        )
        db.add(repair_job)
        db.commit()
    else:
        if repair_job.project_id != project.id:
            raise RuntimeError("Repair job does not belong to the requested project")
        repair_job.status = "processing"
        repair_job.progress = 0.05
        db.commit()

    try:
        RepairService.clear_persisted_results(project_dir)
        timeline = load_midi(source_path)
        if not any(track.notes for track in timeline.tracks):
            raise HTTPException(400, "No note-bearing tracks found in this MIDI file")

        service = RepairService(_build_advisor(user, db))
        run = service.run(
            timeline,
            title=project.title,
            midi_fidelity=req.midi_fidelity,
            tuning_override=tuning_override,
            family_overrides=family_overrides,
            arrangement_mode=req.arrangement_mode,
            source_path=source_path,
            source_filename=project.source_filename,
        )
        service.persist(run, project_dir, project.title)
    except HTTPException as exc:
        project.status = "failed"
        repair_job.status = "failed"
        repair_job.error_message = str(exc.detail)[:500]
        repair_job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        raise
    except Exception as exc:
        logger.exception("BandPilot repair failed for project %s", project.id)
        project.status = "failed"
        repair_job.status = "failed"
        repair_job.error_message = "Repair pipeline failed"
        repair_job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        raise HTTPException(500, "Repair pipeline failed") from exc

    result = run.result
    families = {classification.family.value for classification in result.classifications}
    project.status = result.status
    project.style_label = result.style_label
    project.degraded_mode = result.degraded_mode
    project.midi_fidelity = req.midi_fidelity
    project.instrument_family = next(iter(families)) if len(families) == 1 else "mixed"
    repair_job.status = result.status
    repair_job.progress = 1.0
    repair_job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    artifact_manifest = json.loads(
        (project_dir / "artifact_manifest.json").read_text(encoding="utf-8")
    )
    repair_job.run_id = str(artifact_manifest["run_id"])

    entries = {
        int(item["index"]): dict(item) for item in summary.get("tracks", [])
    }
    for classification in result.classifications:
        current = entries.get(classification.track_index, {})
        current.update(
            {
                "index": classification.track_index,
                "name": classification.track_name,
                "family": classification.family.value,
                "is_guitar": classification.is_guitar,
                "is_drum": classification.is_drum,
                "role": classification.guitar_role,
                "confidence": classification.confidence,
                "reason": classification.reason,
                "user_overridden": classification.user_overridden,
                "note_count": classification.note_count,
            }
        )
        entries[classification.track_index] = current
    summary["tracks"] = [entries[index] for index in sorted(entries)]
    project.track_summary = json.dumps(summary, ensure_ascii=False)
    db.commit()

    primary = run.primary_preparation
    cleanup_info = None
    rewrite_info = None
    if primary is not None:
        cleanup = primary.cleanup
        tuning = cleanup.tuning
        if tuning is not None:
            cleanup_info = CleanupInfo(
                tuning_id=tuning.id,
                tuning_display_name=tuning.display_name,
                tempo_dedup_count=cleanup.tempo_dedup_count,
                out_of_range_count=cleanup.out_of_range_count,
                velocity_remapped=cleanup.velocity_remapped,
                overlaps_truncated=cleanup.overlaps_truncated,
                total_actions=len(cleanup.actions),
            )
        rewrite_info = RewriteInfo(**primary.rewrite)

    separation_info = None
    separation = next(
        (route.separation for route in result.route_results if route.separation is not None),
        None,
    )
    if separation is not None:
        separation_info = SeparationInfo(
            detected=separation.detected,
            total_confidence=separation.total_confidence,
            segments=[
                SeparationSegmentInfo(
                    start_measure=segment.start_measure,
                    end_measure=segment.end_measure,
                    split_pitch=segment.split_pitch,
                    low_note_count=segment.low_note_count,
                    high_note_count=segment.high_note_count,
                    confidence=segment.confidence,
                    reason=segment.reason,
                )
                for segment in separation.segments
            ],
            warnings=list(separation.warnings),
        )

    response = RepairResponse(
        project_id=project.id,
        job_id=repair_job.id,
        status=result.status,
        style_label=result.style_label,
        degraded_mode=result.degraded_mode,
        note_count=(
            sum(
                len(measure.events)
                for track in run.song.score.tracks
                for measure in track.measures
            )
            if run.song
            else int(result.merged_ir.get("note_count", 0))
        ),
        change_count=result.total_changes,
        cleanup=cleanup_info,
        rewrite=rewrite_info,
        separation=separation_info,
        tracks_repaired=[report.to_dict() for report in result.track_reports],
        has_drums=result.has_drums,
        arrangement_mode=req.arrangement_mode,
        validation_status=run.song.validation.status if run.song else "not_validated",
        validation_issues=(
            [
                {
                    "code": issue.code,
                    "severity": issue.severity,
                    "message": issue.message,
                    "track_id": issue.track_id,
                    "note_ids": issue.note_ids,
                }
                for issue in run.song.validation.issues
            ]
            if run.song
            else []
        ),
    )
    repair_job.result_json = response.model_dump_json()
    db.commit()
    return {"code": 0, "data": response.model_dump(), "message": "ok"}


@router.post("/{project_id}/repair", response_model=dict)
def repair_project(
    project_id: int,
    req: RepairRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Run repair synchronously for backwards-compatible API clients."""

    return _execute_repair(project_id, req, user, db)


def _run_repair_background(
    user_id: int,
    project_id: int,
    job_id: int,
    request_data: dict[str, Any],
) -> None:
    """Finish a detached repair with a fresh, thread-local DB session."""

    with session_scope() as db:
        user = db.get(User, user_id)
        project = db.get(Project, project_id)
        repair_job = db.get(RepairJob, job_id)
        if user is None or project is None or repair_job is None:
            logger.error("Async repair %s lost its user, project, or job", job_id)
            return
        try:
            _execute_repair(
                project_id,
                RepairRequest.model_validate(request_data),
                user,
                db,
                repair_job=repair_job,
            )
        except HTTPException as exc:
            logger.warning("Async repair job %s failed: %s", job_id, exc.detail)
        except Exception:
            logger.exception("Async repair job %s failed unexpectedly", job_id)
            project.status = "failed"
            repair_job.status = "failed"
            repair_job.error_message = "Repair pipeline failed"
            repair_job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)


@router.post("/{project_id}/repair-async", response_model=dict, status_code=202)
def start_repair_project(
    project_id: int,
    req: RepairRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Start a durable repair and return immediately for client polling."""

    project = _get_user_project(db, user, project_id)
    source_path = _project_path(user, project.id) / "source.mid"
    if not source_path.is_file():
        raise HTTPException(404, "Source MIDI file not found")
    _resolve_tuning(req.tuning_id)

    active_job = (
        db.query(RepairJob)
        .filter(RepairJob.project_id == project.id, RepairJob.status == "processing")
        .order_by(RepairJob.id.desc())
        .first()
    )
    if active_job is not None:
        raise HTTPException(409, f"Repair job {active_job.id} is already processing")

    summary = json.loads(project.track_summary) if project.track_summary else {"tracks": []}
    persisted_overrides = {
        int(item["index"]): str(item["family"])
        for item in summary.get("tracks", [])
        if item.get("user_overridden")
    }
    family_overrides = {**persisted_overrides, **req.family_overrides}
    repair_job = RepairJob(
        project_id=project.id,
        status="processing",
        progress=0.0,
        arrangement_mode=req.arrangement_mode,
        settings_json=json.dumps(
            {
                "midi_fidelity": req.midi_fidelity,
                "tuning_id": req.tuning_id,
                "family_overrides": family_overrides,
            },
            ensure_ascii=False,
        ),
    )
    project.status = "processing"
    db.add(repair_job)
    db.commit()
    db.refresh(repair_job)
    background_tasks.add_task(
        _run_repair_background,
        user.id,
        project.id,
        repair_job.id,
        req.model_dump(),
    )
    return {
        "code": 0,
        "data": {
            "project_id": project.id,
            "job": _repair_job_response(repair_job),
            "status_url": f"/api/projects/{project.id}/repair-jobs/{repair_job.id}",
        },
        "message": "repair started",
    }


@router.get("/{project_id}/repair-jobs", response_model=dict)
def list_repair_jobs(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return immutable execution history, newest run first."""

    project = _get_user_project(db, user, project_id)
    jobs = (
        db.query(RepairJob)
        .filter(RepairJob.project_id == project.id)
        .order_by(RepairJob.id.desc())
        .all()
    )
    return {
        "code": 0,
        "data": {
            "items": [_repair_job_response(job) for job in jobs],
            "total": len(jobs),
        },
        "message": "ok",
    }


@router.get("/{project_id}/repair-jobs/{job_id}", response_model=dict)
def get_repair_job(
    project_id: int,
    job_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return one durable repair execution owned by this project."""

    project = _get_user_project(db, user, project_id)
    job = (
        db.query(RepairJob)
        .filter(RepairJob.id == job_id, RepairJob.project_id == project.id)
        .first()
    )
    if job is None:
        raise HTTPException(404, "Repair job not found")
    return {"code": 0, "data": _repair_job_response(job), "message": "ok"}


@router.get("/{project_id}/report", response_model=dict)
def repair_report(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return the repair report (transformations + summary)."""
    project = _get_user_project(db, user, project_id)
    project_dir = _project_path(user, project.id)
    song_path = project_dir / "song_ir.json"
    merged_path = project_dir / "ir_merged.json"
    ir_path = project_dir / "ir.json"
    if not song_path.exists() and not merged_path.exists() and not ir_path.exists():
        raise HTTPException(404, "No repair result found. Run repair first.")
    from dataclasses import asdict

    if song_path.exists():
        song = load_song_ir(song_path)
        note_count = sum(
            len(measure.events)
            for track in song.score.tracks
            for measure in track.measures
        )
        return {
            "code": 0,
            "data": {
                "changes": [asdict(change) for change in song.changes],
                "summary": {
                    "total_changes": len(song.changes),
                    "warnings": song.warnings,
                    "style_label": song.analysis.style_label,
                    "degraded_mode": project.degraded_mode,
                    "note_count": note_count,
                    "unresolved_note_count": len(song.analysis.unresolved_events),
                    "validation_status": song.validation.status,
                    "validation_issues": [asdict(issue) for issue in song.validation.issues],
                    "schema_version": song.schema_version,
                    "arrangement_mode": song.arrangement_mode,
                },
            },
            "message": "ok",
        }

    if merged_path.exists():
        guitar_ir, drum_ir = load_merged_irs(merged_path)
    else:
        guitar_ir, drum_ir = load_ir(ir_path), None

    guitar_changes = list(guitar_ir.changes) if guitar_ir is not None else []
    drum_changes = list(drum_ir.changes) if drum_ir is not None else []
    warnings = []
    note_count = 0
    if guitar_ir is not None:
        warnings.extend(guitar_ir.warnings)
        note_count += sum(
            len(measure.events) for track in guitar_ir.tracks for measure in track.measures
        )
    if drum_ir is not None:
        warnings.extend(drum_ir.warnings)
        note_count += sum(
            len(measure.events) for track in drum_ir.tracks for measure in track.measures
        )

    return {"code": 0, "data": {
        "changes": [asdict(change) for change in guitar_changes + drum_changes],
        "summary": {
            "total_changes": len(guitar_changes) + len(drum_changes),
            "warnings": warnings,
            "style_label": project.style_label,
            "degraded_mode": project.degraded_mode,
            "note_count": note_count,
        },
    }, "message": "ok"}


@router.get("/{project_id}/song-ir", response_model=dict)
def get_song_ir(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return the canonical score contract used by every v2 exporter."""

    project = _get_user_project(db, user, project_id)
    song_path = _project_path(user, project.id) / "song_ir.json"
    if not song_path.is_file():
        raise HTTPException(404, "No canonical SongIR found. Run repair first.")
    return {"code": 0, "data": load_song_ir(song_path).to_dict(), "message": "ok"}


@router.get("/{project_id}/artifacts", response_model=dict)
def get_artifact_manifest(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return reproducibility pins and hashes for the latest repair run."""

    project = _get_user_project(db, user, project_id)
    manifest_path = _project_path(user, project.id) / "artifact_manifest.json"
    if not manifest_path.is_file():
        raise HTTPException(404, "No artifact manifest found. Run repair first.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {"code": 0, "data": manifest, "message": "ok"}
