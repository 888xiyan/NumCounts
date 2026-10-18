"""create calculation tables

Revision ID: 20261016_0001
Revises:
Create Date: 2026-10-16
"""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261016_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "calculation_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("table_name", sa.String(length=64), nullable=False),
        sa.Column("period_id", sa.String(length=64), nullable=True),
        sa.Column("input_data", mysql.JSON(), nullable=False),
        sa.Column("function_spec", mysql.JSON(), nullable=False),
        sa.Column("output_data", mysql.JSON(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_details", mysql.JSON(), nullable=True),
        sa.Column(
            "attempt_count",
            mysql.INTEGER(unsigned=True),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "lock_version",
            mysql.INTEGER(unsigned=True),
            nullable=False,
            server_default="1",
        ),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
    )
    op.create_index(
        "idx_records_status_created", "calculation_records", ["status", "created_at"]
    )
    op.create_index(
        "idx_records_table_period", "calculation_records", ["table_name", "period_id"]
    )
    op.create_index(
        "idx_records_status_period", "calculation_records", ["status", "period_id"]
    )

    op.create_table(
        "calculation_attempts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("record_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_no", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("execution_id", sa.String(length=36), nullable=False),
        sa.Column("executor_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("input_snapshot", mysql.JSON(), nullable=False),
        sa.Column("function_snapshot", mysql.JSON(), nullable=False),
        sa.Column("output_snapshot", mysql.JSON(), nullable=True),
        sa.Column("error_snapshot", mysql.JSON(), nullable=True),
        sa.Column("started_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("finished_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("duration_ms", mysql.INTEGER(unsigned=True), nullable=True),
        sa.ForeignKeyConstraint(["record_id"], ["calculation_records.id"]),
        sa.UniqueConstraint("record_id", "attempt_no", name="uk_attempt_record_no"),
        sa.UniqueConstraint("execution_id", name="uk_attempt_execution_id"),
    )
    op.create_index(
        "idx_attempt_record_started",
        "calculation_attempts",
        ["record_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_attempt_record_started", table_name="calculation_attempts")
    op.drop_table("calculation_attempts")
    op.drop_index("idx_records_status_period", table_name="calculation_records")
    op.drop_index("idx_records_table_period", table_name="calculation_records")
    op.drop_index("idx_records_status_created", table_name="calculation_records")
    op.drop_table("calculation_records")
