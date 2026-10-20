"""Add member-to-teacher mapping and isolated trial workflow runs.

Revision ID: 20261020_0010
Revises: 20261020_0009
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261020_0010"
down_revision: str | None = "20261020_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("teacher_id", sa.String(length=64), nullable=True))
    op.create_index("uk_users_teacher_id", "users", ["teacher_id"], unique=True)

    op.add_column(
        "workflow_runs",
        sa.Column(
            "run_mode",
            sa.String(length=16),
            nullable=False,
            server_default="operator",
        ),
    )
    op.create_index(
        "idx_workflow_runs_requester_mode_started",
        "workflow_runs",
        ["requested_by_user_id", "run_mode", "started_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_workflow_runs_requester_mode_started", table_name="workflow_runs"
    )
    op.drop_column("workflow_runs", "run_mode")
    op.drop_index("uk_users_teacher_id", table_name="users")
    op.drop_column("users", "teacher_id")
