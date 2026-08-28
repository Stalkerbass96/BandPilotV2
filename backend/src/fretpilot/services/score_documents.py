"""Atomic persistence boundary for ScoreDocument revisions and typed commands.

The service deliberately accepts an existing SQLAlchemy session and never
commits it.  API/workflow callers own the transaction boundary, so the command,
revision, snapshot and document head become visible together or not at all.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from fretpilot.db.models import (
    Project,
    ScoreCommand,
    ScoreDocumentRecord,
    ScoreRevision,
    ScoreSnapshot,
)
from fretpilot.editor.document import ScoreDocument
from fretpilot.editor.operations import (
    CommandApplyResult,
    FieldTouch,
    ScoreCommandError,
    ScoreConflictError,
    ScoreEditor,
    ScoreTransaction,
    operation_from_dict,
    operation_to_dict,
    touches_conflict,
    transaction_fingerprint,
    transaction_from_dict,
    transaction_to_dict,
)
from fretpilot.ir.score_document_serde import (
    canonical_document_json,
    document_from_dict,
    document_hash,
)


class ScoreDocumentStoreError(RuntimeError):
    """Base error for durable score document access."""


class ScoreDocumentNotFoundError(ScoreDocumentStoreError):
    """The requested document or revision does not exist."""


class ScoreDocumentIntegrityError(ScoreDocumentStoreError):
    """Persisted snapshot content does not match its immutable metadata."""


@dataclass(frozen=True, slots=True)
class StoredScoreRevision:
    document: ScoreDocument
    revision_id: str
    revision: int
    content_hash: str
    canonical_payload: str


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _snapshot(document: ScoreDocument) -> tuple[str, str]:
    payload = canonical_document_json(document)
    return payload, document_hash(document)


def _new_revision_id() -> str:
    return f"revision:{uuid4().hex}"


def _load_revision_row(
    db: Session,
    record: ScoreDocumentRecord,
    revision: int | None,
) -> ScoreRevision:
    target = record.current_revision if revision is None else revision
    row = db.execute(
        select(ScoreRevision).where(
            ScoreRevision.document_id == record.id,
            ScoreRevision.revision_number == target,
        )
    ).scalar_one_or_none()
    if row is None:
        raise ScoreDocumentNotFoundError(
            f"ScoreDocument {record.id!r} has no revision {target}"
        )
    return row


def _decode_revision(record: ScoreDocumentRecord, revision: ScoreRevision) -> StoredScoreRevision:
    snapshot = revision.snapshot
    if snapshot is None:
        raise ScoreDocumentIntegrityError(f"Revision {revision.id!r} has no snapshot")
    encoded_size = len(snapshot.document_json.encode("utf-8"))
    if encoded_size != snapshot.byte_count:
        raise ScoreDocumentIntegrityError(
            f"Revision {revision.id!r} snapshot byte count does not match"
        )
    try:
        document = document_from_dict(json.loads(snapshot.document_json))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ScoreDocumentIntegrityError(
            f"Revision {revision.id!r} snapshot cannot be decoded"
        ) from exc
    if document.id != record.id:
        raise ScoreDocumentIntegrityError(
            f"Revision {revision.id!r} contains a different document ID"
        )
    actual_hash = hashlib.sha256(snapshot.document_json.encode("utf-8")).hexdigest()
    if actual_hash != revision.content_hash:
        raise ScoreDocumentIntegrityError(
            f"Revision {revision.id!r} content hash does not match"
        )
    if (
        revision.revision_number == record.current_revision
        and revision.content_hash != record.current_revision_hash
    ):
        raise ScoreDocumentIntegrityError("Document head hash does not match its revision")
    return StoredScoreRevision(
        document=document,
        revision_id=revision.id,
        revision=revision.revision_number,
        content_hash=revision.content_hash,
        canonical_payload=snapshot.document_json,
    )


def create_score_document(
    db: Session,
    *,
    project_id: int,
    document: ScoreDocument,
    actor_user_id: int | None,
) -> StoredScoreRevision:
    """Create immutable revision zero for a project.

    Existing documents are never overwritten.  Repair reruns must become a
    proposal/new revision once that workflow is enabled.
    """

    if db.get(Project, project_id) is None:
        raise ScoreDocumentNotFoundError(f"Project {project_id} does not exist")
    existing = db.execute(
        select(ScoreDocumentRecord).where(ScoreDocumentRecord.project_id == project_id)
    ).scalar_one_or_none()
    if existing is not None:
        raise ScoreConflictError(f"Project {project_id} already has a score document")

    editor = ScoreEditor(document)
    normalized = editor.document
    payload, content_hash = _snapshot(normalized)
    record = ScoreDocumentRecord(
        id=normalized.id,
        project_id=project_id,
        schema_version=normalized.schema_version,
        current_revision=0,
        current_revision_hash=content_hash,
    )
    revision = ScoreRevision(
        id=_new_revision_id(),
        document_id=normalized.id,
        revision_number=0,
        parent_revision_id=None,
        command_id=None,
        author_user_id=actor_user_id,
        content_hash=content_hash,
        validation_status=normalized.validation.status,
    )
    revision.snapshot = ScoreSnapshot(
        schema_version=normalized.schema_version,
        document_json=payload,
        byte_count=len(payload.encode("utf-8")),
    )
    record.revisions.append(revision)
    db.add(record)
    db.flush()
    return StoredScoreRevision(
        document=normalized,
        revision_id=revision.id,
        revision=0,
        content_hash=content_hash,
        canonical_payload=payload,
    )


def load_score_document_revision(
    db: Session,
    document_id: str,
    *,
    revision: int | None = None,
) -> StoredScoreRevision:
    """Load and verify the current or requested immutable revision."""

    record = db.get(ScoreDocumentRecord, document_id)
    if record is None:
        raise ScoreDocumentNotFoundError(f"ScoreDocument {document_id!r} does not exist")
    return _decode_revision(record, _load_revision_row(db, record, revision))


def _decode_touches(command: ScoreCommand) -> tuple[FieldTouch, ...]:
    try:
        values = json.loads(command.touched_fields_json)
        touches = tuple(tuple(str(part) for part in value) for value in values)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ScoreDocumentIntegrityError(
            f"Command {command.command_id!r} has invalid touch metadata"
        ) from exc
    if any(len(value) != 3 for value in touches):
        raise ScoreDocumentIntegrityError(
            f"Command {command.command_id!r} has invalid touch metadata"
        )
    return touches  # type: ignore[return-value]


def apply_score_transaction(
    db: Session,
    transaction: ScoreTransaction,
    *,
    actor_user_id: int | None,
) -> CommandApplyResult:
    """Validate and durably append one idempotent score transaction."""

    record = db.execute(
        select(ScoreDocumentRecord)
        .where(ScoreDocumentRecord.id == transaction.document_id)
        .with_for_update()
    ).scalar_one_or_none()
    if record is None:
        raise ScoreDocumentNotFoundError(
            f"ScoreDocument {transaction.document_id!r} does not exist"
        )
    if actor_user_id is not None and transaction.actor_id != f"user:{actor_user_id}":
        raise ScoreCommandError("Transaction actor does not match the authenticated user")

    fingerprint = transaction_fingerprint(transaction)
    existing = db.execute(
        select(ScoreCommand).where(
            ScoreCommand.document_id == record.id,
            ScoreCommand.command_id == transaction.command_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.fingerprint != fingerprint:
            raise ScoreConflictError("Command ID was already used for a different payload")
        revision = db.get(ScoreRevision, existing.accepted_revision_id)
        if revision is None:
            raise ScoreDocumentIntegrityError(
                f"Command {existing.command_id!r} lost its accepted revision"
            )
        return CommandApplyResult(
            command_id=existing.command_id,
            revision=existing.accepted_revision,
            document_hash=revision.content_hash,
            rebased=existing.rebased,
            idempotent_replay=True,
        )

    if transaction.base_revision < 0 or transaction.base_revision > record.current_revision:
        raise ScoreConflictError("Transaction base revision is not available")

    requested_touches = frozenset(
        touch for operation in transaction.operations for touch in operation.touches()
    )
    intervening = db.execute(
        select(ScoreCommand).where(
            ScoreCommand.document_id == record.id,
            ScoreCommand.accepted_revision > transaction.base_revision,
        )
    ).scalars()
    if any(
        touches_conflict(requested, accepted)
        for command in intervening
        for accepted in _decode_touches(command)
        for requested in requested_touches
    ):
        raise ScoreConflictError(
            "Transaction conflicts with accepted changes after its base revision"
        )

    current_revision = _load_revision_row(db, record, record.current_revision)
    current = _decode_revision(record, current_revision)
    editor = ScoreEditor.from_verified_snapshot(
        current.document,
        revision=current.revision,
        canonical_payload=current.canonical_payload,
        content_hash=current.content_hash,
    )
    result = editor.apply(transaction)
    accepted = editor.accepted_command(transaction.command_id)
    if accepted is None:  # pragma: no cover - guarded by successful apply
        raise ScoreDocumentIntegrityError("Accepted command metadata was not retained")

    snapshot = editor.canonical_snapshot()
    if result.document_hash != snapshot.content_hash:
        raise ScoreDocumentIntegrityError("Command result hash is not deterministic")
    revision = ScoreRevision(
        id=_new_revision_id(),
        document_id=record.id,
        revision_number=result.revision,
        parent_revision_id=current.revision_id,
        command_id=transaction.command_id,
        author_user_id=actor_user_id,
        content_hash=snapshot.content_hash,
        validation_status=snapshot.validation_status,
    )
    revision.snapshot = ScoreSnapshot(
        schema_version=snapshot.schema_version,
        document_json=snapshot.payload,
        byte_count=len(snapshot.payload.encode("utf-8")),
    )
    db.add(revision)
    db.flush()

    command = ScoreCommand(
        document_id=record.id,
        command_id=transaction.command_id,
        actor_user_id=actor_user_id,
        base_revision=transaction.base_revision,
        accepted_revision_id=revision.id,
        accepted_revision=result.revision,
        origin=transaction.origin,
        intent=transaction.intent,
        transaction_json=_json(transaction_to_dict(transaction)),
        inverse_operations_json=_json(
            [operation_to_dict(value) for value in accepted.inverse_operations]
        ),
        touched_fields_json=_json(sorted(accepted.touched_fields)),
        fingerprint=accepted.fingerprint,
        rebased=result.rebased,
        status="accepted",
    )
    db.add(command)
    record.current_revision = result.revision
    record.current_revision_hash = snapshot.content_hash
    db.flush()
    return result


def append_system_snapshot(
    db: Session,
    *,
    document_id: str,
    document: ScoreDocument,
    command_id: str,
    origin: str,
    intent: str,
    author_user_id: int | None,
) -> CommandApplyResult:
    """Append a trusted whole-document transition with a global conflict fence.

    This is deliberately not a generic client operation. It promotes workflow
    output such as raw MIDI -> prepared score without creating an untracked
    second mutation path.
    """

    record = db.execute(
        select(ScoreDocumentRecord)
        .where(ScoreDocumentRecord.id == document_id)
        .with_for_update()
    ).scalar_one_or_none()
    if record is None:
        raise ScoreDocumentNotFoundError(f"ScoreDocument {document_id!r} does not exist")
    existing = db.execute(
        select(ScoreCommand).where(
            ScoreCommand.document_id == document_id,
            ScoreCommand.command_id == command_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        revision = db.get(ScoreRevision, existing.accepted_revision_id)
        if revision is None:
            raise ScoreDocumentIntegrityError(
                f"Command {command_id!r} lost its accepted revision"
            )
        return CommandApplyResult(
            command_id=command_id,
            revision=existing.accepted_revision,
            document_hash=revision.content_hash,
            rebased=existing.rebased,
            idempotent_replay=True,
        )
    if document.id != document_id:
        raise ScoreCommandError("System snapshot targets a different document")

    normalized = ScoreEditor(document).document
    payload, content_hash = _snapshot(normalized)
    if content_hash == record.current_revision_hash:
        return CommandApplyResult(
            command_id=command_id,
            revision=record.current_revision,
            document_hash=content_hash,
            rebased=False,
            idempotent_replay=True,
        )

    parent = _load_revision_row(db, record, record.current_revision)
    next_revision = record.current_revision + 1
    transaction_payload = {
        "schema_version": "1.0",
        "command_id": command_id,
        "document_id": document_id,
        "actor_id": f"system:{origin}",
        "base_revision": record.current_revision,
        "origin": origin,
        "intent": intent,
        "selection": None,
        "operations": [],
        "created_at": datetime.now(UTC).isoformat(),
        "snapshot_hash": content_hash,
    }
    fingerprint = hashlib.sha256(_json(transaction_payload).encode("utf-8")).hexdigest()
    revision = ScoreRevision(
        id=_new_revision_id(),
        document_id=document_id,
        revision_number=next_revision,
        parent_revision_id=parent.id,
        command_id=command_id,
        author_user_id=author_user_id,
        content_hash=content_hash,
        validation_status=normalized.validation.status,
    )
    revision.snapshot = ScoreSnapshot(
        schema_version=normalized.schema_version,
        document_json=payload,
        byte_count=len(payload.encode("utf-8")),
    )
    db.add(revision)
    db.flush()
    db.add(
        ScoreCommand(
            document_id=document_id,
            command_id=command_id,
            actor_user_id=None,
            base_revision=record.current_revision,
            accepted_revision_id=revision.id,
            accepted_revision=next_revision,
            origin=origin,
            intent=intent,
            transaction_json=_json(transaction_payload),
            inverse_operations_json="[]",
            touched_fields_json=_json([("document", document_id, "*")]),
            fingerprint=fingerprint,
            rebased=False,
            status="accepted",
        )
    )
    record.current_revision = next_revision
    record.current_revision_hash = content_hash
    db.flush()
    return CommandApplyResult(
        command_id=command_id,
        revision=next_revision,
        document_hash=content_hash,
        rebased=False,
    )


def undo_score_transaction(
    db: Session,
    *,
    document_id: str,
    target_command_id: str,
    undo_command_id: str,
    actor_user_id: int,
    created_at: str | None = None,
) -> CommandApplyResult:
    """Append a compensating transaction for one command owned by the actor."""

    target = db.execute(
        select(ScoreCommand).where(
            ScoreCommand.document_id == document_id,
            ScoreCommand.command_id == target_command_id,
        )
    ).scalar_one_or_none()
    if target is None:
        raise ScoreDocumentNotFoundError(
            f"Command {target_command_id!r} does not exist in {document_id!r}"
        )
    if target.actor_user_id != actor_user_id:
        raise ScoreCommandError("An actor may undo only their own command")
    record = db.get(ScoreDocumentRecord, document_id)
    if record is None:
        raise ScoreDocumentNotFoundError(f"ScoreDocument {document_id!r} does not exist")

    existing_undo = db.execute(
        select(ScoreCommand).where(
            ScoreCommand.document_id == document_id,
            ScoreCommand.command_id == undo_command_id,
        )
    ).scalar_one_or_none()
    if existing_undo is not None:
        return apply_score_transaction(
            db,
            transaction_from_dict(json.loads(existing_undo.transaction_json)),
            actor_user_id=actor_user_id,
        )
    original = transaction_from_dict(json.loads(target.transaction_json))
    transaction = ScoreTransaction(
        command_id=undo_command_id,
        document_id=document_id,
        actor_id=f"user:{actor_user_id}",
        base_revision=record.current_revision,
        origin="manual",
        intent=f"Undo {target.intent}",
        operations=tuple(
            operation_from_dict(value)
            for value in json.loads(target.inverse_operations_json)
        ),
        selection=original.selection,
        created_at=created_at or datetime.now(UTC).isoformat(),
    )
    return apply_score_transaction(db, transaction, actor_user_id=actor_user_id)


__all__ = [
    "ScoreDocumentIntegrityError",
    "ScoreDocumentNotFoundError",
    "ScoreDocumentStoreError",
    "StoredScoreRevision",
    "append_system_snapshot",
    "apply_score_transaction",
    "create_score_document",
    "load_score_document_revision",
    "undo_score_transaction",
]
