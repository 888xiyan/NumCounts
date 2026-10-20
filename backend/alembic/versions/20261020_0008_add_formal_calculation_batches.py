"""add formal calculation batches and versioned results

Revision ID: 20261020_0008
Revises: 20261018_0007
Create Date: 2026-10-20
"""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261020_0008"
down_revision = "20261018_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "formal_calculation_batches",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("period_id", sa.String(length=64), nullable=False),
        sa.Column("occurred_from", sa.Date(), nullable=False),
        sa.Column("occurred_to", sa.Date(), nullable=False),
        sa.Column("department_id", sa.String(length=64), nullable=True),
        sa.Column("teacher_ids", mysql.JSON(), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_snapshot", mysql.JSON(), nullable=False),
        sa.Column("input_mappings", mysql.JSON(), nullable=False),
        sa.Column("result_node_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("reviewed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_details", mysql.JSON(), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("finished_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow_definitions.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"]),
    )
    op.create_index(
        "idx_formal_batches_period_created",
        "formal_calculation_batches",
        ["period_id", "created_at"],
    )
    op.create_index(
        "idx_formal_batches_status_created",
        "formal_calculation_batches",
        ["status", "created_at"],
    )

    op.create_table(
        "formal_calculation_results",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("teacher_id", sa.String(length=64), nullable=False),
        sa.Column("teacher_name", sa.String(length=128), nullable=False),
        sa.Column("department_id", sa.String(length=64), nullable=False),
        sa.Column("period_id", sa.String(length=64), nullable=False),
        sa.Column("result_version", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("total_amount", sa.Float(), nullable=True),
        sa.Column("result_data", mysql.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_details", mysql.JSON(), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("finished_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["formal_calculation_batches.id"]),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"]),
        sa.UniqueConstraint("batch_id", "teacher_id", name="uk_formal_result_batch_teacher"),
        sa.UniqueConstraint(
            "period_id", "teacher_id", "result_version", name="uk_formal_result_version"
        ),
    )
    op.create_index(
        "idx_formal_results_period_teacher",
        "formal_calculation_results",
        ["period_id", "teacher_id"],
    )
    op.create_index(
        "idx_formal_results_batch", "formal_calculation_results", ["batch_id"]
    )

    op.create_table(
        "formal_calculation_result_sources",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("result_id", sa.String(length=36), nullable=False),
        sa.Column("achievement_id", sa.String(length=36), nullable=False),
        sa.Column("achievement_snapshot", mysql.JSON(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["result_id"], ["formal_calculation_results.id"]),
        sa.ForeignKeyConstraint(["achievement_id"], ["achievement_records.id"]),
        sa.UniqueConstraint("result_id", "achievement_id", name="uk_formal_result_source"),
    )
    op.create_index(
        "idx_formal_sources_achievement",
        "formal_calculation_result_sources",
        ["achievement_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_formal_sources_achievement", table_name="formal_calculation_result_sources"
    )
    op.drop_table("formal_calculation_result_sources")
    op.drop_index("idx_formal_results_batch", table_name="formal_calculation_results")
    op.drop_index(
        "idx_formal_results_period_teacher", table_name="formal_calculation_results"
    )
    op.drop_table("formal_calculation_results")
    op.drop_index(
        "idx_formal_batches_status_created", table_name="formal_calculation_batches"
    )
    op.drop_index(
        "idx_formal_batches_period_created", table_name="formal_calculation_batches"
    )
    op.drop_table("formal_calculation_batches")
