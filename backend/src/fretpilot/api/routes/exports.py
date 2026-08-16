"""Export routes — generate and download gp5 / Ample MIDI files."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from fretpilot.api.deps import get_current_user
from fretpilot.config import get_settings
from fretpilot.db.models import ExportRecord, Project, User
from fretpilot.db.session import get_db
from fretpilot.exporters.ample_midi.profile import load_profile
from fretpilot.exporters.ample_midi.renderer import AmpleMidiExporter
from fretpilot.exporters.gp5 import GP5Exporter
from fretpilot.ir.serde import load_ir

logger = logging.getLogger("fretpilot.api.exports")
router = APIRouter()


class ExportRequest(BaseModel):
    format: str  # "gp5" or "ample_midi"


class ExportResponse(BaseModel):
    download_url: str
    format_id: str
    note_count: int


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


def _export_gp5(ir_path: Path, out_dir: Path) -> tuple[Path, int, int]:
    """Export the IR to a .gp5 file."""
    ir = load_ir(ir_path)
    exporter = GP5Exporter()
    out_path = out_dir / "output.gp5"
    result = exporter.export(ir, out_path)
    return out_path, result.note_count, result.measure_count


def _export_ample(ir_path: Path, out_dir: Path) -> tuple[Path, int, int]:
    """Export the IR to an Ample MIDI file."""
    ir = load_ir(ir_path)
    profile = load_profile("ample_eclipse")
    exporter = AmpleMidiExporter(profile)
    out_path = out_dir / "output_ample.mid"
    result = exporter.export(ir, out_path)
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
    ir_path = project_dir / "ir.json"
    if not ir_path.exists():
        raise HTTPException(400, "No repair result found. Run repair first.")

    exports_dir = project_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)

    if req.format == "gp5":
        out_path, note_count, measure_count = _export_gp5(ir_path, exports_dir)
    elif req.format == "ample_midi":
        out_path, note_count, measure_count = _export_ample(ir_path, exports_dir)
    else:
        raise HTTPException(400, f"Unsupported format: {req.format}")

    record = ExportRecord(
        project_id=project.id,
        format_id=req.format,
        file_path=str(out_path),
        note_count=note_count,
    )
    db.add(record)
    db.commit()

    download_url = f"/api/projects/{project_id}/exports/{record.id}/download"
    return {"code": 0, "data": ExportResponse(
        download_url=download_url, format_id=req.format, note_count=note_count,
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
    elif record.format_id == "ample_midi":
        media_type = "audio/midi"
    return FileResponse(path, media_type=media_type, filename=path.name)
