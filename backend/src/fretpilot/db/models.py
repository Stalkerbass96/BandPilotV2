"""SQLAlchemy ORM models for FretPilot persistence."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    byok_config: Mapped["ByokConfig | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    projects: Mapped[list["Project"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class ByokConfig(Base):
    __tablename__ = "byok_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="byok_config")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="imported", nullable=False)
    style_label: Mapped[str] = mapped_column(String(64), default="unknown", nullable=False)
    degraded_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    midi_fidelity: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    instrument_family: Mapped[str] = mapped_column(
        String(32), default="guitar", nullable=False
    )
    track_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="projects")
    exports: Mapped[list["ExportRecord"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    repair_jobs: Mapped[list["RepairJob"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    score_document: Mapped["ScoreDocumentRecord | None"] = relationship(
        back_populates="project",
        uselist=False,
        cascade="all, delete-orphan",
    )


class RepairJob(Base):
    """Durable execution history for a project repair request."""

    __tablename__ = "repair_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(32), default="processing", nullable=False)
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    arrangement_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    settings_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="repair_jobs")


class ExportRecord(Base):
    __tablename__ = "export_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    format_id: Mapped[str] = mapped_column(String(32), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    note_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("score_revisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    revision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="exports")
    revision: Mapped["ScoreRevision | None"] = relationship()


class ScoreDocumentRecord(Base):
    """One canonical editable score document owned by a project."""

    __tablename__ = "score_documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    current_revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_revision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="score_document")
    revisions: Mapped[list["ScoreRevision"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        foreign_keys="ScoreRevision.document_id",
    )
    commands: Mapped[list["ScoreCommand"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class ScoreRevision(Base):
    """Immutable revision metadata with a content-addressed snapshot."""

    __tablename__ = "score_revisions"
    __table_args__ = (
        UniqueConstraint("document_id", "revision_number", name="uq_score_revision_number"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("score_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("score_revisions.id", ondelete="RESTRICT"), nullable=True
    )
    command_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    author_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    document: Mapped["ScoreDocumentRecord"] = relationship(
        back_populates="revisions", foreign_keys=[document_id]
    )
    parent: Mapped["ScoreRevision | None"] = relationship(
        remote_side=[id], foreign_keys=[parent_revision_id]
    )
    snapshot: Mapped["ScoreSnapshot"] = relationship(
        back_populates="revision", uselist=False, cascade="all, delete-orphan"
    )


class ScoreSnapshot(Base):
    """Canonical JSON snapshot for one immutable score revision."""

    __tablename__ = "score_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("score_revisions.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    document_json: Mapped[str] = mapped_column(Text, nullable=False)
    byte_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    revision: Mapped["ScoreRevision"] = relationship(back_populates="snapshot")


class ScoreCommand(Base):
    """Accepted typed transaction and its deterministic inverse metadata."""

    __tablename__ = "score_commands"
    __table_args__ = (
        UniqueConstraint("document_id", "command_id", name="uq_score_command_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("score_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    command_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    base_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_revision_id: Mapped[str] = mapped_column(
        ForeignKey("score_revisions.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    accepted_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    intent: Mapped[str] = mapped_column(String(255), nullable=False)
    transaction_json: Mapped[str] = mapped_column(Text, nullable=False)
    inverse_operations_json: Mapped[str] = mapped_column(Text, nullable=False)
    touched_fields_json: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    rebased: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="accepted", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    document: Mapped["ScoreDocumentRecord"] = relationship(back_populates="commands")
    revision: Mapped["ScoreRevision"] = relationship(foreign_keys=[accepted_revision_id])


__all__ = [
    "Base",
    "User",
    "ByokConfig",
    "Project",
    "RepairJob",
    "ExportRecord",
    "ScoreDocumentRecord",
    "ScoreRevision",
    "ScoreSnapshot",
    "ScoreCommand",
]
