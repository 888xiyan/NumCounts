"""add formal function body and execution context snapshots

Revision ID: 20261018_0007
Revises: 20261018_0006
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261018_0007"
down_revision = "20261018_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "calculation_records",
        sa.Column("requested_by_user_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "calculation_records",
        sa.Column("workflow_run_id", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        "fk_calculation_records_requested_by_user_id",
        "calculation_records",
        "users",
        ["requested_by_user_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_calculation_records_workflow_run_id",
        "calculation_records",
        "workflow_runs",
        ["workflow_run_id"],
        ["id"],
    )
    op.create_index(
        "idx_records_requester_created",
        "calculation_records",
        ["requested_by_user_id", "created_at"],
    )
    op.create_index(
        "idx_records_workflow_run", "calculation_records", ["workflow_run_id"]
    )

    op.add_column(
        "calculation_attempts",
        sa.Column("function_body_snapshot", mysql.JSON(), nullable=True),
    )
    op.add_column(
        "calculation_attempts",
        sa.Column("execution_context_snapshot", mysql.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("calculation_attempts", "execution_context_snapshot")
    op.drop_column("calculation_attempts", "function_body_snapshot")
    op.drop_index("idx_records_workflow_run", table_name="calculation_records")
    op.drop_index("idx_records_requester_created", table_name="calculation_records")
    op.drop_constraint(
        "fk_calculation_records_workflow_run_id",
        "calculation_records",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_calculation_records_requested_by_user_id",
        "calculation_records",
        type_="foreignkey",
    )
    op.drop_column("calculation_records", "workflow_run_id")
    op.drop_column("calculation_records", "requested_by_user_id")
