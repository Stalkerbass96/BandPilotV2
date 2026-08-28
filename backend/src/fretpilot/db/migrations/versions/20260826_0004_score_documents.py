"""Add canonical score document, revision, snapshot and command persistence.

Revision ID: 20260826_0004
Revises: 20260823_0003
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0004"
down_revision: str | None = "20260823_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "score_documents",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("current_revision_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id"),
    )
    op.create_index(
        "ix_score_documents_project_id",
        "score_documents",
        ["project_id"],
        unique=True,
    )

    op.create_table(
        "score_revisions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("parent_revision_id", sa.String(length=64), nullable=True),
        sa.Column("command_id", sa.String(length=128), nullable=True),
        sa.Column("author_user_id", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("validation_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["document_id"], ["score_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parent_revision_id"], ["score_revisions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id", "revision_number", name="uq_score_revision_number"
        ),
    )
    op.create_index(
        "ix_score_revisions_document_id",
        "score_revisions",
        ["document_id"],
        unique=False,
    )

    op.create_table(
        "score_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("revision_id", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("document_json", sa.Text(), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["revision_id"], ["score_revisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("revision_id"),
    )

    op.create_table(
        "score_commands",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("command_id", sa.String(length=128), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("base_revision", sa.Integer(), nullable=False),
        sa.Column("accepted_revision_id", sa.String(length=64), nullable=False),
        sa.Column("accepted_revision", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("intent", sa.String(length=255), nullable=False),
        sa.Column("transaction_json", sa.Text(), nullable=False),
        sa.Column("inverse_operations_json", sa.Text(), nullable=False),
        sa.Column("touched_fields_json", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("rebased", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["accepted_revision_id"], ["score_revisions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["document_id"], ["score_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("accepted_revision_id"),
        sa.UniqueConstraint("document_id", "command_id", name="uq_score_command_id"),
    )
    op.create_index(
        "ix_score_commands_document_id", "score_commands", ["document_id"], unique=False
    )

    with op.batch_alter_table("export_records") as batch_op:
        batch_op.add_column(sa.Column("revision_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("revision_hash", sa.String(length=64), nullable=True))
        batch_op.create_foreign_key(
            "fk_export_records_revision_id",
            "score_revisions",
            ["revision_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_export_records_revision_id", ["revision_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("export_records") as batch_op:
        batch_op.drop_index("ix_export_records_revision_id")
        batch_op.drop_constraint("fk_export_records_revision_id", type_="foreignkey")
        batch_op.drop_column("revision_hash")
        batch_op.drop_column("revision_id")

    op.drop_index("ix_score_commands_document_id", table_name="score_commands")
    op.drop_table("score_commands")
    op.drop_table("score_snapshots")
    op.drop_index("ix_score_revisions_document_id", table_name="score_revisions")
    op.drop_table("score_revisions")
    op.drop_index("ix_score_documents_project_id", table_name="score_documents")
    op.drop_table("score_documents")
