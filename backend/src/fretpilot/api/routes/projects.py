"""Project routes — create, list, detail, repair, status, report."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from fretpilot.ai.advisor import (
    ShadowRewriteAdvisor,
    apply_rewrite_decisions,
    build_note_summaries,
    build_policy,
    extract_features,
    validate_decisions,
)
from fretpilot.ai.models import RewriteRequest
from fretpilot.ai.crypto import KeyVault, get_key_vault
from fretpilot.ai.providers.openai_compatible import OpenAICompatibleAdvisor
from fretpilot.api.deps import get_current_user
from fretpilot.config import get_settings
from fretpilot.db.models import ByokConfig, Project, User
from fretpilot.db.session import get_db
from fretpilot.detection import classify_timeline, resolve_streams
from fretpilot.engine.cleanup import auto_detect_tuning, cleanup_streams
from fretpilot.engine.pipeline import create_pipeline
from fretpilot.engine.drum_pipeline import create_drum_pipeline
from fretpilot.engine.context import PipelineContext, NoteRewriteDecision
from fretpilot.ir.drum_models import DrumProjectIR
from fretpilot.knowledge.tunings import GuitarTuning, TuningRegistry
from fretpilot.ir.serde import ir_to_dict, load_ir, save_ir
from fretpilot.midi.models import NormalizedTimeline, NormalizedTrack
from fretpilot.midi.parser import load_midi
from fretpilot.orchestrator import BandPilotOrchestrator, classify_track_family

logger = logging.getLogger("fretpilot.api.projects")
router = APIRouter()


class ProjectResponse(BaseModel):
    id: int
    title: str
    source_filename: str
    status: str
    style_label: str
    degraded_mode: bool


class RepairRequest(BaseModel):
    midi_fidelity: float = 0.5
    tuning_id: str | None = None  # NEW: 用户覆盖定弦；None 则 auto_detect


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
    reasons: list[str] = []


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
    segments: list[SeparationSegmentInfo] = []
    warnings: list[str] = []


class RepairResponse(BaseModel):
    project_id: int
    status: str
    style_label: str
    degraded_mode: bool
    note_count: int
    change_count: int
    cleanup: CleanupInfo | None = None
    rewrite: RewriteInfo | None = None
    separation: SeparationInfo | None = None
    # BandPilot multi-track fields (optional — absent for guitar-only backward compat).
    tracks_repaired: list[dict[str, Any]] | None = None
    has_drums: bool = False


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
    provider = OpenAICompatibleAdvisor(api_key=api_key, model=model, base_url=base_url)
    return ShadowRewriteAdvisor(provider)


def _non_drum_streams(timeline: NormalizedTimeline) -> list:
    """Resolve logical streams, excluding percussion/drum streams.

    在 BandPilot 混合 MIDI（吉他 + 鼓）里，鼓轨常常承载最多音符（kick/
    snare/hat 律动）。吉他 cleanup 绝不能把鼓流选成"主吉他流"，否则吉他 IR
    会用鼓的音高、冠以鼓轨的名字（曾导致导出的 .gp5 两条轨都叫 "Drums"）。
    鼓轨由 BandPilot orchestrator 路由到 StickPilot 处理。
    """
    drum_indices = {
        t.index
        for t in timeline.tracks
        if t.notes and classify_track_family(t).is_drum
    }
    if not drum_indices:
        return resolve_streams(timeline)
    return [
        s
        for s in resolve_streams(timeline)
        if not s.source_track_indices
        or not any(i in drum_indices for i in s.source_track_indices)
    ]


def _build_cleaned_track(
    timeline: NormalizedTimeline,
    primary_track_index: int | None,
    fallback: NormalizedTrack,
    tuning: GuitarTuning | None = None,
) -> tuple[NormalizedTrack, CleanupInfo | None]:
    """resolve_streams → 定弦（auto-detect 或用户覆盖）→ cleanup_streams。

    执行 cleanup 全流程（带 timeline + 定弦，flag 模式不删音符），取
    note_count 最多的流作为主吉他流并构建 cleaned NormalizedTrack。当
    ``tuning`` 为 None 时走 auto_detect；否则使用用户传入的定弦（覆盖）。
    当无流可清理时回退到 ``fallback`` 并返回 ``None`` 摘要。返回
    ``(cleaned_track, cleanup_info)``。

    混合 MIDI（吉他 + 鼓）下先经 :func:`_non_drum_streams` 排除鼓流，
    确保主吉他流永远来自吉他/旋律轨。
    """
    streams = _non_drum_streams(timeline)
    # auto-detect + user override：显式传入定弦时覆盖自动检测结果。
    if tuning is None:
        tuning = auto_detect_tuning(streams) if streams else None
    clean_result = (
        cleanup_streams(
            streams,
            timeline=timeline,
            tuning=tuning,
            out_of_range_mode="flag",
        )
        if streams
        else None
    )

    if clean_result is not None and clean_result.streams:
        primary_stream = max(clean_result.streams, key=lambda s: s.note_count)
        cleaned_track = NormalizedTrack(
            index=primary_track_index or 0,
            name=primary_stream.track_name,
            notes=list(primary_stream.notes),
            instrument_name=primary_stream.instrument_name,
            program=primary_stream.program,
        )
    else:
        cleaned_track = fallback

    cleanup_info: CleanupInfo | None = None
    if clean_result is not None and tuning is not None:
        cleanup_info = CleanupInfo(
            tuning_id=tuning.id,
            tuning_display_name=tuning.display_name,
            tempo_dedup_count=clean_result.tempo_dedup_count,
            out_of_range_count=clean_result.out_of_range_count,
            velocity_remapped=clean_result.velocity_remapped,
            overlaps_truncated=clean_result.overlaps_truncated,
            total_actions=len(clean_result.actions),
        )
    return cleaned_track, cleanup_info


def _resolve_tuning(tuning_id: str | None) -> GuitarTuning | None:
    """解析用户覆盖定弦：None 回退 auto_detect，非法 ID 抛 400。

    遵循 "auto-detect + user override" 原则——用户在 API 里显式指定定弦时
    使用该定弦；未指定（None）时交由 ``_build_cleaned_track`` 自动检测。
    """
    if tuning_id is None:
        return None
    tuning = TuningRegistry.default().get(tuning_id)
    if tuning is None:
        raise HTTPException(400, f"Unknown tuning_id: {tuning_id}")
    return tuning


def _combine_drum_irs(
    drum_irs: list[DrumProjectIR], title: str
) -> DrumProjectIR | None:
    """Combine one or more drum IRs into a single project IR with all tracks.

    The repair route produces one ``DrumProjectIR`` per drum track; the merged
    export contract (``load_merged_irs`` / ``export_bandpilot``) consumes a
    single drum IR. This merges them preserving tempo/time-sig/knowledge from
    the first IR.
    """
    if not drum_irs:
        return None
    first = drum_irs[0]
    return DrumProjectIR(
        title=title,
        source=first.source,
        schema_version=first.schema_version,
        tempo_map=list(first.tempo_map),
        time_signatures=list(first.time_signatures),
        tracks=[t for ir in drum_irs for t in ir.tracks],
        knowledge=first.knowledge,
        style_label=first.style_label,
        changes=[c for ir in drum_irs for c in ir.changes],
        warnings=[w for ir in drum_irs for w in ir.warnings],
    )


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
    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(413, "File too large (max 20MB)")
    if not file.filename or not file.filename.lower().endswith((".mid", ".midi")):
        raise HTTPException(415, "Only .mid/.midi files are supported")

    project = Project(
        user_id=user.id,
        title=title or Path(file.filename).stem,
        source_filename=file.filename,
        status="imported",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    project_dir = _project_path(user, project.id)
    source_path = project_dir / "source.mid"
    source_path.write_bytes(content)

    timeline = load_midi(source_path)
    report = classify_timeline(timeline)

    # BandPilot: detect instrument families for all tracks.
    has_drums_on_import = False
    for track in timeline.tracks:
        if not track.notes:
            continue
        family_cls = classify_track_family(track)
        if family_cls.is_drum:
            has_drums_on_import = True
            break
    if has_drums_on_import:
        project.instrument_family = "mixed"

    project.track_summary = json.dumps(
        {
            "tracks": [
                {
                    "index": c.track_index,
                    "name": c.track_name,
                    "family": c.instrument_family,
                    "is_guitar": c.is_guitar,
                    "role": c.guitar_role,
                    "confidence": c.confidence,
                    "note_count": len(timeline.tracks[c.track_index].notes) if c.track_index < len(timeline.tracks) else 0,
                }
                for c in report.classifications
            ],
            "primary_guitar_track": report.primary_guitar_track_index,
        },
        ensure_ascii=False,
    )
    db.commit()

    return {"code": 0, "data": ProjectResponse(
        id=project.id, title=project.title, source_filename=project.source_filename,
        status=project.status, style_label=project.style_label, degraded_mode=project.degraded_mode,
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
    tracks_info: list[dict[str, Any]] = []
    for track in timeline.tracks:
        if not track.notes:
            continue
        cls = classify_track_family(track)
        info: dict[str, Any] = {
            "index": cls.track_index,
            "name": cls.track_name,
            "family": cls.family.value,
            "is_guitar": cls.is_guitar,
            "is_drum": cls.is_drum,
            "role": cls.guitar_role,
            "confidence": cls.confidence,
            "note_count": cls.note_count,
        }
        if cls.is_drum:
            info["kit_type"] = cls.kit_type
            info["detected_pieces"] = cls.detected_pieces
        tracks_info.append(info)

    return {"code": 0, "data": {"tracks": tracks_info, "total": len(tracks_info)}, "message": "ok"}


def _get_user_project(db: Session, user: User, project_id: int) -> Project:
    """Fetch a project owned by the user, or 404."""
    project = db.query(Project).filter(
        Project.id == project_id, Project.user_id == user.id
    ).first()
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


@router.post("/{project_id}/repair", response_model=dict)
def repair_project(
    project_id: int,
    req: RepairRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Run the repair pipeline (synchronous in MVP)."""
    project = _get_user_project(db, user, project_id)
    project_dir = _project_path(user, project.id)
    source_path = project_dir / "source.mid"

    timeline = load_midi(source_path)
    report = classify_timeline(timeline)
    if report.primary_guitar_track_index is None:
        raise HTTPException(400, "No guitar track detected in this MIDI file")

    track = timeline.tracks[report.primary_guitar_track_index]
    # cleanup 集成：resolve → detect（或用户覆盖定弦）→ cleanup → 构建 track。
    tuning = _resolve_tuning(req.tuning_id)
    cleaned_track, cleanup_info = _build_cleaned_track(
        timeline, report.primary_guitar_track_index, track, tuning
    )
    # When the user didn't specify a tuning, _build_cleaned_track auto-detects
    # one internally. Retrieve it from cleanup_info so the pipeline uses the
    # same tuning that cleanup used for out-of-range detection.
    if tuning is None and cleanup_info is not None:
        tuning = TuningRegistry.default().get(cleanup_info.tuning_id)

    advisor = _build_advisor(user, db)
    features = extract_features(cleaned_track)
    style_result = advisor.infer_style(features)

    # ─── Shadow Rewrite (LLM note-level decisions) ───
    # The LLM proposes note-level decisions (delete noise, transpose
    # out-of-range notes). Validated decisions are applied to the track
    # before it enters the pipeline. Degraded mode (no BYOK) skips this.
    policy = build_policy(req.midi_fidelity)
    note_summaries = build_note_summaries(cleaned_track, tuning)
    tuning_info: dict[str, Any] = {}
    if tuning is not None:
        tuning_info = {
            "id": tuning.id,
            "display_name": tuning.display_name,
            "string_count": tuning.string_count,
            "string_pitches": tuning.string_pitches,
            "min_pitch": tuning.min_pitch,
            "max_pitch": tuning.max_pitch,
        }

    rewrite_request = RewriteRequest(
        features=features,
        style_label=style_result.style_label,
        policy=policy,
        note_summaries=note_summaries,
        tuning_info=tuning_info,
    )
    rewrite_response, rewrite_degraded = advisor.propose_rewrite(rewrite_request)

    rewrite_info: RewriteInfo | None = None
    applied_log: list[dict[str, Any]] = []

    if not rewrite_degraded and rewrite_response.decisions:
        valid_decisions = validate_decisions(
            rewrite_response.decisions,
            len(cleaned_track.notes),
            policy,
        )
        if valid_decisions:
            cleaned_track, applied_log = apply_rewrite_decisions(
                cleaned_track, valid_decisions
            )
            deletions = sum(1 for a in applied_log if a["operation"] == "delete")
            transpositions = sum(
                1 for a in applied_log if a["operation"] == "transpose"
            )
            rewrite_info = RewriteInfo(
                degraded=False,
                deletions=deletions,
                transpositions=transpositions,
                total=len(applied_log),
                reasons=[a.get("reason", "") for a in applied_log[:10]],
            )
            # Re-extract features after rewrite so the pipeline sees the
            # post-rewrite state.
            features = extract_features(cleaned_track)
    elif rewrite_degraded:
        rewrite_info = RewriteInfo(
            degraded=True, deletions=0, transpositions=0, total=0, reasons=[],
        )

    pipeline = create_pipeline()
    ctx = PipelineContext(
        timeline=timeline,
        track=cleaned_track,
        knowledge=pipeline.registry,
        style_label=style_result.style_label,
        midi_fidelity=req.midi_fidelity,
        advisor=advisor._provider,
        track_role=report.primary_classification.guitar_role if report.primary_classification else "unknown",
        source_track_index=cleaned_track.index,
        degraded_mode=style_result.degraded_mode,
        tuning=tuning,
        rewrite_decisions=[
            NoteRewriteDecision(
                index=a["index"],
                operation=a["operation"],
                pitch=a.get("new_pitch"),
                reason=a.get("reason", ""),
            )
            for a in applied_log
        ],
    )

    # Record rewrite transformations (before pipeline stages add their own).
    for a in applied_log:
        if a["operation"] == "delete":
            ctx.add_transformation(
                stage="rewrite",
                source_note_index=a["index"],
                before={"pitch": a["pitch"], "present": True},
                after={"present": False},
                confidence=0.8,
                reason=f"LLM shadow rewrite: delete ({a.get('reason', '')})",
            )
        elif a["operation"] == "transpose":
            ctx.add_transformation(
                stage="rewrite",
                source_note_index=a["index"],
                before={"pitch": a["old_pitch"]},
                after={"pitch": a["new_pitch"]},
                confidence=0.8,
                reason=f"LLM shadow rewrite: transpose ({a.get('reason', '')})",
            )

    ir = pipeline.execute(ctx)

    separation_info: SeparationInfo | None = None
    if ctx.separation is not None:
        separation_info = SeparationInfo(
            detected=ctx.separation.detected,
            total_confidence=ctx.separation.total_confidence,
            segments=[
                SeparationSegmentInfo(
                    start_measure=seg.start_measure,
                    end_measure=seg.end_measure,
                    split_pitch=seg.split_pitch,
                    low_note_count=seg.low_note_count,
                    high_note_count=seg.high_note_count,
                    confidence=seg.confidence,
                    reason=seg.reason,
                )
                for seg in ctx.separation.segments
            ],
            warnings=list(ctx.separation.warnings),
        )

    # ─── BandPilot: detect drum tracks and route to StickPilot ───
    # Backward compatibility: if no drums are detected, the behavior is
    # identical to the previous guitar-only pipeline. The merged IR wraps
    # the single guitar IR and the response omits multi-track fields.
    guitar_irs = [ir]
    drum_irs: list = []
    tracks_repaired: list[dict[str, Any]] | None = None
    has_drums = False
    instrument_family = "guitar"

    from fretpilot.orchestrator.detector import InstrumentFamily

    for track in timeline.tracks:
        if not track.notes or track.index == cleaned_track.index:
            continue
        family_cls = classify_track_family(track)
        if family_cls.family == InstrumentFamily.DRUMS:
            has_drums = True
            instrument_family = "mixed"
            try:
                drum_pipeline = create_drum_pipeline()
                from fretpilot.engine.drum_context import DrumPipelineContext
                drum_ctx = DrumPipelineContext(
                    timeline=timeline,
                    track=track,
                    knowledge=drum_pipeline.registry,
                    style_label=style_result.style_label,
                    midi_fidelity=req.midi_fidelity,
                    source_track_index=track.index,
                )
                drum_ir = drum_pipeline.execute(drum_ctx)
                drum_irs.append(drum_ir)
                drum_stages = sum(1 for v in drum_ctx.stage_progress.values() if v)
                drum_report: dict[str, Any] = {
                    "kit_type": drum_ir.tracks[0].kit if drum_ir.tracks else "",
                    "style_detected": drum_ctx.detected_style,
                    "patterns": [m.pattern for t in drum_ir.tracks for m in t.measures],
                    "sticking_suggested": drum_stages >= 6,
                    "velocity_normalized": drum_stages >= 5,
                }
                if tracks_repaired is None:
                    tracks_repaired = []
                tracks_repaired.append({
                    "track_index": track.index,
                    "module": "stickpilot",
                    "stages_completed": drum_stages,
                    "note_count": len(track.notes),
                    "change_count": len(drum_ctx.transformations),
                    "drum_report": drum_report,
                })
            except Exception:
                logger.exception("BandPilot: error processing drum track %d", track.index)

    # Build the guitar track report for multi-track response.
    if has_drums and tracks_repaired is not None:
        tracks_repaired.insert(0, {
            "track_index": cleaned_track.index,
            "module": "fretpilot",
            "stages_completed": sum(1 for v in ctx.stage_progress.values() if v),
            "note_count": len(cleaned_track.notes),
            "change_count": len(ir.changes),
        })

    # Merge IRs (single guitar IR when no drums — backward compatible).
    from fretpilot.orchestrator.merge import merge_irs
    merged = merge_irs(guitar_irs, drum_irs, project.title)

    # Persist IRs. When no drums, save the guitar IR via save_ir() (backward
    # compatible with the /report endpoint which uses load_ir()). When drums
    # are present, also save the split IR pair as ir_merged.json — the
    # documented contract of load_merged_irs(): {"guitar": {...}|null,
    # "drum": {...}|null}.
    save_ir(ir, project_dir / "ir.json")
    if has_drums:
        import json as _json
        drum_ir_combined = _combine_drum_irs(drum_irs, project.title)
        (project_dir / "ir_merged.json").write_text(
            _json.dumps(
                {
                    "guitar": ir_to_dict(ir),
                    "drum": (
                        drum_ir_combined.to_dict()
                        if drum_ir_combined is not None
                        else None
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    project.status = "repaired"
    project.style_label = style_result.style_label
    project.degraded_mode = style_result.degraded_mode
    project.midi_fidelity = req.midi_fidelity
    project.instrument_family = instrument_family
    db.commit()

    # When no drums, the response is identical to the previous guitar-only
    # pipeline (tracks_repaired=None, has_drums=False).
    total_note_count = (
        merged.get("note_count", 0)
        if has_drums
        else sum(len(m.events) for t in ir.tracks for m in t.measures)
    )
    total_changes = len(ir.changes) + sum(len(d.changes) for d in drum_irs)

    return {"code": 0, "data": RepairResponse(
        project_id=project.id, status="repaired",
        style_label=style_result.style_label, degraded_mode=style_result.degraded_mode,
        note_count=total_note_count,
        change_count=total_changes,
        cleanup=cleanup_info,
        rewrite=rewrite_info,
        separation=separation_info,
        tracks_repaired=tracks_repaired,
        has_drums=has_drums,
    ).model_dump(), "message": "ok"}


@router.get("/{project_id}/report", response_model=dict)
def repair_report(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return the repair report (transformations + summary)."""
    project = _get_user_project(db, user, project_id)
    project_dir = _project_path(user, project.id)
    ir_path = project_dir / "ir.json"
    if not ir_path.exists():
        raise HTTPException(404, "No repair result found. Run repair first.")
    ir = load_ir(ir_path)
    from dataclasses import asdict
    return {"code": 0, "data": {
        "changes": [asdict(c) for c in ir.changes],
        "summary": {
            "total_changes": len(ir.changes),
            "warnings": ir.warnings,
            "style_label": ir.style_label,
            "degraded_mode": ir.degraded_mode,
            "note_count": sum(len(m.events) for t in ir.tracks for m in t.measures),
        },
    }, "message": "ok"}
