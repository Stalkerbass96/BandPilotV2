"""Authenticated ScoreDocument snapshot and typed-command transport."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from fretpilot.api.deps import get_current_user
from fretpilot.config import get_settings
from fretpilot.db.models import (
    Project,
    ScoreCommand,
    ScoreDocumentRecord,
    ScoreRevision,
    User,
)
from fretpilot.db.session import get_db
from fretpilot.editor.operations import (
    ScoreCommandError,
    ScoreConflictError,
    ScoreOperationError,
    transaction_from_dict,
)
from fretpilot.ir.score_document_adapter import song_ir_to_score_document
from fretpilot.ir.score_document_serde import document_hash, document_to_api_dict
from fretpilot.ir.song_serde import load_song_ir
from fretpilot.services.score_documents import (
    ScoreDocumentIntegrityError,
    ScoreDocumentNotFoundError,
    append_system_snapshot,
    apply_score_transaction,
    create_score_document,
    load_score_document_revision,
    undo_score_transaction,
)

router = APIRouter()


class ScoreCommandRequest(BaseModel):
    """Client-safe transaction body; document and actor come from the route/auth."""

    schema_version: str = "1.0"
    command_id: str = Field(min_length=1, max_length=128)
    base_revision: int = Field(ge=0)
    origin: Literal["manual"] = "manual"
    intent: str = Field(min_length=1, max_length=255)
    operations: list[dict[str, Any]] = Field(min_length=1)
    selection: dict[str, Any] | None = None
    created_at: str | None = None


class UndoScoreCommandRequest(BaseModel):
    command_id: str = Field(min_length=1, max_length=128)
    created_at: str | None = None


def _project_for_owner(db: Session, user: User, project_id: int) -> Project:
    project = db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user.id)
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


def _document_record(db: Session, project_id: int) -> ScoreDocumentRecord:
    record = db.execute(
        select(ScoreDocumentRecord).where(ScoreDocumentRecord.project_id == project_id)
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(
            404,
            {
                "code": "document_not_ready",
                "message": "Project has no ScoreDocument. Bootstrap a repaired SongIR first.",
            },
        )
    return record


def _revision_response(stored, *, current_revision: int) -> dict[str, Any]:
    return {
        "document": document_to_api_dict(stored.document),
        "revision": {
            "id": stored.revision_id,
            "number": stored.revision,
            "hash": stored.content_hash,
            "is_current": stored.revision == current_revision,
        },
    }


def _accepted_revision_id(db: Session, document_id: str, revision: int) -> str:
    revision_id = db.execute(
        select(ScoreRevision.id).where(
            ScoreRevision.document_id == document_id,
            ScoreRevision.revision_number == revision,
        )
    ).scalar_one_or_none()
    if revision_id is None:
        raise ScoreDocumentIntegrityError(
            f"Accepted revision {revision} for {document_id!r} is missing"
        )
    return revision_id


@router.post("/{project_id}/document/bootstrap", response_model=dict)
def bootstrap_score_document(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Create revision zero from the latest immutable SongIR compatibility artifact."""

    project = _project_for_owner(db, user, project_id)
    existing = db.execute(
        select(ScoreDocumentRecord).where(ScoreDocumentRecord.project_id == project.id)
    ).scalar_one_or_none()
    if existing is not None:
        stored = load_score_document_revision(db, existing.id)
        return {
            "code": 0,
            "data": _revision_response(stored, current_revision=existing.current_revision),
            "message": "document already exists",
        }

    song_path = get_settings().job_root_path / str(user.id) / str(project.id) / "song_ir.json"
    if not song_path.is_file():
        raise HTTPException(
            409,
            {
                "code": "document_source_not_ready",
                "message": "Run the existing MIDI preparation flow before migration bootstrap.",
            },
        )
    try:
        document = song_ir_to_score_document(
            load_song_ir(song_path), document_id=f"project:{project.id}:document"
        )
        stored = create_score_document(
            db,
            project_id=project.id,
            document=document,
            actor_user_id=user.id,
        )
        db.commit()
    except (ScoreCommandError, ScoreDocumentIntegrityError) as exc:
        db.rollback()
        raise HTTPException(
            422,
            {"code": "document_invalid", "message": str(exc)},
        ) from exc
    return {
        "code": 0,
        "data": _revision_response(stored, current_revision=0),
        "message": "document created",
    }


@router.post("/{project_id}/document/promote-prepared", response_model=dict)
def promote_prepared_score_document(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Promote the first prepared SongIR into canonical revision history.

    Only an untouched raw revision zero can be replaced. Repair reruns over an
    edited score require the later proposal/review workflow and are never
    allowed to silently discard manual work.
    """

    project = _project_for_owner(db, user, project_id)
    if project.status not in {"repaired", "partial"}:
        raise HTTPException(
            409,
            {
                "code": "preparation_not_ready",
                "message": "Finish score preparation before opening the professional editor.",
            },
        )
    song_path = get_settings().job_root_path / str(user.id) / str(project.id) / "song_ir.json"
    if not song_path.is_file():
        raise HTTPException(
            409,
            {"code": "prepared_artifact_missing", "message": "Prepared SongIR is missing."},
        )
    record = db.execute(
        select(ScoreDocumentRecord).where(ScoreDocumentRecord.project_id == project.id)
    ).scalar_one_or_none()
    try:
        prepared = song_ir_to_score_document(
            load_song_ir(song_path), document_id=f"project:{project.id}:document"
        )
        if record is None:
            stored = create_score_document(
                db,
                project_id=project.id,
                document=prepared,
                actor_user_id=user.id,
            )
        else:
            current = load_score_document_revision(db, record.id)
            is_raw = any(
                track.instrument.get("realization_status") == "unprepared"
                for track in current.document.tracks
            )
            if not is_raw:
                stored = current
            else:
                if record.current_revision != 0:
                    raise ScoreConflictError(
                        "The raw score already has manual edits; preparation must be reviewed as a proposal."
                    )
                prepared_hash = document_hash(prepared)
                result = append_system_snapshot(
                    db,
                    document_id=record.id,
                    document=prepared,
                    command_id=f"prepare:{prepared_hash[:32]}",
                    origin="repair",
                    intent="Promote prepared score",
                    author_user_id=user.id,
                )
                stored = load_score_document_revision(
                    db, record.id, revision=result.revision
                )
        db.commit()
    except ScoreConflictError as exc:
        db.rollback()
        raise HTTPException(
            409, {"code": "preparation_conflict", "message": str(exc)}
        ) from exc
    except (ScoreCommandError, ScoreDocumentIntegrityError) as exc:
        db.rollback()
        raise HTTPException(
            422, {"code": "prepared_document_invalid", "message": str(exc)}
        ) from exc
    current_revision = db.get(ScoreDocumentRecord, stored.document.id).current_revision
    return {
        "code": 0,
        "data": _revision_response(stored, current_revision=current_revision),
        "message": "prepared document ready",
    }


@router.get("/{project_id}/document", response_model=dict)
def get_score_document(
    project_id: int,
    revision: int | None = Query(default=None, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Load a verified immutable snapshot; omit revision for the current head."""

    _project_for_owner(db, user, project_id)
    record = _document_record(db, project_id)
    try:
        stored = load_score_document_revision(db, record.id, revision=revision)
    except ScoreDocumentNotFoundError as exc:
        raise HTTPException(
            404, {"code": "revision_not_found", "message": str(exc)}
        ) from exc
    except ScoreDocumentIntegrityError as exc:
        raise HTTPException(
            500, {"code": "document_integrity_failed", "message": str(exc)}
        ) from exc
    return {
        "code": 0,
        "data": _revision_response(stored, current_revision=record.current_revision),
        "message": "ok",
    }


@router.post("/{project_id}/commands", response_model=dict)
def submit_score_command(
    project_id: int,
    request: ScoreCommandRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Submit one server-authoritative, idempotent typed score transaction."""

    _project_for_owner(db, user, project_id)
    record = _document_record(db, project_id)
    raw = request.model_dump()
    raw["document_id"] = record.id
    raw["actor_id"] = f"user:{user.id}"
    existing = db.execute(
        select(ScoreCommand).where(
            ScoreCommand.document_id == record.id,
            ScoreCommand.command_id == request.command_id,
        )
    ).scalar_one_or_none()
    if request.created_at is not None:
        raw["created_at"] = request.created_at
    elif existing is not None:
        raw["created_at"] = json.loads(existing.transaction_json)["created_at"]
    else:
        raw["created_at"] = datetime.now(UTC).isoformat()
    try:
        transaction = transaction_from_dict(raw)
        result = apply_score_transaction(db, transaction, actor_user_id=user.id)
        revision_id = _accepted_revision_id(db, record.id, result.revision)
        db.commit()
    except ScoreConflictError as exc:
        db.rollback()
        raise HTTPException(
            409, {"code": "revision_conflict", "message": str(exc)}
        ) from exc
    except ScoreOperationError as exc:
        db.rollback()
        raise HTTPException(
            422, {"code": "validation_failed", "message": str(exc)}
        ) from exc
    except (ScoreCommandError, KeyError, TypeError, ValueError) as exc:
        db.rollback()
        raise HTTPException(
            400, {"code": "unsupported_operation", "message": str(exc)}
        ) from exc
    except ScoreDocumentIntegrityError as exc:
        db.rollback()
        raise HTTPException(
            500, {"code": "document_integrity_failed", "message": str(exc)}
        ) from exc
    return {
        "code": 0,
        "data": {
            "command_id": result.command_id,
            "revision_id": revision_id,
            "revision": result.revision,
            "document_hash": result.document_hash,
            "rebased": result.rebased,
            "idempotent_replay": result.idempotent_replay,
        },
        "message": "command accepted",
    }


@router.get("/{project_id}/commands", response_model=dict)
def list_score_commands(
    project_id: int,
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Catch up accepted transactions after a known revision."""

    _project_for_owner(db, user, project_id)
    record = _document_record(db, project_id)
    commands = db.execute(
        select(ScoreCommand)
        .where(
            ScoreCommand.document_id == record.id,
            ScoreCommand.accepted_revision > after,
        )
        .order_by(ScoreCommand.accepted_revision)
        .limit(limit)
    ).scalars()
    items = [
        {
            "command_id": command.command_id,
            "base_revision": command.base_revision,
            "accepted_revision": command.accepted_revision,
            "rebased": command.rebased,
            "status": command.status,
            "transaction": json.loads(command.transaction_json),
        }
        for command in commands
    ]
    return {
        "code": 0,
        "data": {
            "items": items,
            "after": after,
            "current_revision": record.current_revision,
            "has_more": bool(items and items[-1]["accepted_revision"] < record.current_revision),
        },
        "message": "ok",
    }


@router.post("/{project_id}/commands/{target_command_id}/undo", response_model=dict)
def undo_score_command(
    project_id: int,
    target_command_id: str,
    request: UndoScoreCommandRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Undo one actor-owned command through the same validated append path."""

    _project_for_owner(db, user, project_id)
    record = _document_record(db, project_id)
    try:
        result = undo_score_transaction(
            db,
            document_id=record.id,
            target_command_id=target_command_id,
            undo_command_id=request.command_id,
            actor_user_id=user.id,
            created_at=request.created_at,
        )
        revision_id = _accepted_revision_id(db, record.id, result.revision)
        db.commit()
    except ScoreDocumentNotFoundError as exc:
        db.rollback()
        raise HTTPException(
            404, {"code": "command_not_found", "message": str(exc)}
        ) from exc
    except ScoreConflictError as exc:
        db.rollback()
        raise HTTPException(
            409, {"code": "revision_conflict", "message": str(exc)}
        ) from exc
    except ScoreOperationError as exc:
        db.rollback()
        raise HTTPException(
            422, {"code": "validation_failed", "message": str(exc)}
        ) from exc
    except ScoreCommandError as exc:
        db.rollback()
        raise HTTPException(
            403, {"code": "permission_denied", "message": str(exc)}
        ) from exc
    except ScoreDocumentIntegrityError as exc:
        db.rollback()
        raise HTTPException(
            500, {"code": "document_integrity_failed", "message": str(exc)}
        ) from exc
    return {
        "code": 0,
        "data": {
            "command_id": result.command_id,
            "revision_id": revision_id,
            "revision": result.revision,
            "document_hash": result.document_hash,
            "rebased": result.rebased,
            "idempotent_replay": result.idempotent_replay,
        },
        "message": "command undone",
    }


__all__ = ["router"]
