"""Export routes — generate and download gp5 / Ample MIDI files."""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from fretpilot.api.deps import get_current_user
from fretpilot.config import get_settings
from fretpilot.db.models import ExportRecord, Project, ScoreDocumentRecord, User
from fretpilot.db.session import get_db
from fretpilot.exporters.ample_midi.profile import load_profile
from fretpilot.exporters.ample_midi.renderer import AmpleMidiExporter
from fretpilot.exporters.gp5 import GP5Exporter, export_bandpilot
from fretpilot.exporters.registry import SongExporterRegistry
from fretpilot.ir.score_document_adapter import score_document_to_song_ir
from fretpilot.ir.serde import load_ir, load_merged_irs
from fretpilot.ir.song import SongIR
from fretpilot.ir.song_serde import load_song_ir
from fretpilot.services.score_documents import (
    ScoreDocumentIntegrityError,
    ScoreDocumentNotFoundError,
    load_score_document_revision,
)
from fretpilot.validation import ScoreValidationError

logger = logging.getLogger("fretpilot.api.exports")
router = APIRouter()


class ExportRequest(BaseModel):
    format: str
    revision: int | None = Field(default=None, ge=0)


class ExportResponse(BaseModel):
    download_url: str
    format_id: str
    note_count: int
    revision_id: str | None = None
    revision_hash: str | None = None


def _get_user_project(db: Session, user: User, project_id: int) -> Project:
    """Fetch a project owned by the user, or 404."""
    project = db.query(Project).filter(
        Project.id == project_id, Project.user_id == user.id
    ).first()
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


def _project_dir(user: User, project_id: int) -> Path:
    return get_settings().job_root_path / str(user.id) / str(project_id)


def _export_gp5(project_dir: Path, out_dir: Path) -> tuple[Path, int, int]:
    """Export the IR to a .gp5 file.

    Checks for ir_merged.json (BandPilot multi-track) first, then
    falls back to ir.json (guitar-only) for backward compatibility.
    """
    merged_path = project_dir / "ir_merged.json"
    ir_path = project_dir / "ir.json"

    if merged_path.exists():
        guitar_ir, drum_ir = load_merged_irs(merged_path)
        out_path = out_dir / "output.gp5"
        result = export_bandpilot(guitar_ir, drum_ir, out_path)
        return out_path, result.note_count, result.measure_count

    # Guitar-only backward-compatible path
    ir = load_ir(ir_path)
    exporter = GP5Exporter()
    out_path = out_dir / "output.gp5"
    result = exporter.export(ir, out_path)
    return out_path, result.note_count, result.measure_count


def _export_ample(project_dir: Path, out_dir: Path) -> tuple[Path, int, int]:
    """Export the IR to an Ample MIDI file."""
    merged_path = project_dir / "ir_merged.json"
    ir_path = project_dir / "ir.json"

    if merged_path.exists():
        guitar_ir, _ = load_merged_irs(merged_path)
        ir = guitar_ir
        if ir is None:
            raise HTTPException(400, "No guitar IR found in merged result for Ample MIDI export.")
    else:
        ir = load_ir(ir_path)
    profile = load_profile("ample_eclipse")
    exporter = AmpleMidiExporter(profile)
    out_path = out_dir / "output_ample.mid"
    result = exporter.export(ir, out_path)
    return out_path, result.note_count, result.measure_count


def _export_song(
    song: SongIR,
    requested_format: str,
    exports_dir: Path,
) -> tuple[Path, int, int]:
    aliases = {"ample_midi": "ample_eclipse_midi"}
    canonical_format = aliases.get(requested_format, requested_format)
    file_shapes = {
        "gp5": ("score", ".gp5"),
        "musicxml": ("score", ".musicxml"),
        "humanized_midi": ("humanized-band", ".mid"),
        "ample_eclipse_midi": ("ample-eclipse", ".mid"),
        "humanized_ample_eclipse_midi": ("humanized-ample-eclipse", ".mid"),
    }
    file_shape = file_shapes.get(canonical_format)
    if file_shape is None:
        raise HTTPException(400, f"Unsupported format: {requested_format}")
    stem, suffix = file_shape
    out_path = exports_dir / f"{stem}-{uuid4().hex[:12]}{suffix}"
    try:
        result = SongExporterRegistry.default().export(canonical_format, song, out_path)
    except ScoreValidationError as exc:
        raise HTTPException(
            422,
            {
                "message": "Score failed professional playability validation",
                "issues": [
                    {
                        "code": issue.code,
                        "message": issue.message,
                        "track_id": issue.track_id,
                        "note_ids": issue.note_ids,
                    }
                    for issue in exc.issues
                ],
            },
        ) from exc
    return out_path, result.note_count, result.measure_count


@router.post("/{project_id}/export", response_model=dict)
def export_project(
    project_id: int,
    req: ExportRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Export the repaired project to the requested format."""
    project = _get_user_project(db, user, project_id)
    project_dir = _project_dir(user, project_id)
    exports_dir = project_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)

    revision_id: str | None = None
    revision_hash: str | None = None
    if req.revision is not None:
        record = db.query(ScoreDocumentRecord).filter(
            ScoreDocumentRecord.project_id == project.id
        ).first()
        if record is None:
            raise HTTPException(404, "Project has no ScoreDocument")
        try:
            stored = load_score_document_revision(db, record.id, revision=req.revision)
        except ScoreDocumentNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ScoreDocumentIntegrityError as exc:
            raise HTTPException(500, str(exc)) from exc
        out_path, note_count, measure_count = _export_song(
            score_document_to_song_ir(stored.document), req.format, exports_dir
        )
        revision_id = stored.revision_id
        revision_hash = stored.content_hash
    else:
        song_path = project_dir / "song_ir.json"
        ir_path = project_dir / "ir.json"
        merged_path = project_dir / "ir_merged.json"
        if not song_path.exists() and not ir_path.exists() and not merged_path.exists():
            raise HTTPException(
                400,
                "No repair result found. Export a ScoreDocument revision or run repair first.",
            )
        if song_path.exists():
            out_path, note_count, measure_count = _export_song(
                load_song_ir(song_path), req.format, exports_dir
            )
        else:
            legacy_exporters = {"gp5": _export_gp5, "ample_midi": _export_ample}
            exporter = legacy_exporters.get(req.format)
            if exporter is None:
                raise HTTPException(400, f"Unsupported format: {req.format}")
            out_path, note_count, measure_count = exporter(project_dir, exports_dir)

    record = ExportRecord(
        project_id=project.id,
        format_id=req.format,
        file_path=str(out_path),
        note_count=note_count,
        revision_id=revision_id,
        revision_hash=revision_hash,
    )
    db.add(record)
    db.commit()

    download_url = f"/api/projects/{project_id}/exports/{record.id}/download"
    return {"code": 0, "data": ExportResponse(
        download_url=download_url,
        format_id=req.format,
        note_count=note_count,
        revision_id=record.revision_id,
        revision_hash=record.revision_hash,
    ).model_dump(), "message": "ok"}


@router.get("/{project_id}/exports", response_model=dict)
def list_exports(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """List export records for a project."""
    _get_user_project(db, user, project_id)
    records = db.query(ExportRecord).filter(
        ExportRecord.project_id == project_id
    ).order_by(ExportRecord.created_at.desc()).all()
    items = [
        {
            "id": r.id,
            "format_id": r.format_id,
            "note_count": r.note_count,
            "revision_id": r.revision_id,
            "revision_hash": r.revision_hash,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]
    return {"code": 0, "data": {"items": items}, "message": "ok"}


@router.get("/{project_id}/exports/{export_id}/download")
def download_export(
    project_id: int,
    export_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    """Download an exported file."""
    _get_user_project(db, user, project_id)
    record = db.query(ExportRecord).filter(
        ExportRecord.id == export_id, ExportRecord.project_id == project_id
    ).first()
    if record is None:
        raise HTTPException(404, "Export not found")
    path = Path(record.file_path)
    if not path.exists():
        raise HTTPException(404, "Export file not found on disk")
    media_type = "application/octet-stream"
    if record.format_id == "gp5":
        media_type = "application/octet-stream"
    elif record.format_id in {
        "ample_midi",
        "ample_eclipse_midi",
        "humanized_midi",
        "humanized_ample_eclipse_midi",
    }:
        media_type = "audio/midi"
    elif record.format_id == "musicxml":
        media_type = "application/vnd.recordare.musicxml+xml"
    return FileResponse(path, media_type=media_type, filename=path.name)
