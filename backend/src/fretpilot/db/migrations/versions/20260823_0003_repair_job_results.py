"""Persist completed repair responses for asynchronous polling.

Revision ID: 20260823_0003
Revises: 20260823_0002
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260823_0003"
down_revision: str | None = "20260823_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("repair_jobs", sa.Column("result_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("repair_jobs", "result_json")
