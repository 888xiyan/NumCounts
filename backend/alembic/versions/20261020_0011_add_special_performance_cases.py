"""Add material-backed special-performance and appeal cases.

Revision ID: 20261020_0011
Revises: 20261020_0010
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision: str = "20261020_0011"
down_revision: str | None = "20261020_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "rule_plugins",
        sa.Column(
            "purpose", sa.String(length=24), nullable=False, server_default="general"
        ),
    )
    op.create_table(
        "special_performance_cases",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("case_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("submitted_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("teacher_id", sa.String(length=64), nullable=False),
        sa.Column("teacher_name", sa.String(length=128), nullable=False),
        sa.Column("department_id", sa.String(length=64), nullable=False),
        sa.Column("period_id", sa.String(length=64), nullable=False),
        sa.Column("original_result_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("form_data", mysql.JSON(), nullable=False),
        sa.Column("submitted_snapshot", mysql.JSON(), nullable=True),
        sa.Column("submission_version", sa.Integer(), nullable=False),
        sa.Column("submitted_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("review_due_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("processed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("processing_comment", sa.Text(), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("plugin_id", sa.String(length=36), nullable=True),
        sa.Column("plugin_snapshot", mysql.JSON(), nullable=True),
        sa.Column("plugin_execution_status", sa.String(length=16), nullable=True),
        sa.Column("calculation_record_id", sa.String(length=36), nullable=True),
        sa.Column("achievement_id", sa.String(length=36), nullable=True),
        sa.Column("processing_error", mysql.JSON(), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["submitted_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["original_result_id"], ["formal_calculation_results.id"]
        ),
        sa.ForeignKeyConstraint(["processed_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["plugin_id"], ["rule_plugins.id"]),
        sa.ForeignKeyConstraint(
            ["calculation_record_id"], ["calculation_records.id"]
        ),
        sa.ForeignKeyConstraint(["achievement_id"], ["achievement_records.id"]),
    )
    op.create_index(
        "idx_special_cases_status_due",
        "special_performance_cases",
        ["status", "review_due_at"],
    )
    op.create_index(
        "idx_special_cases_owner_created",
        "special_performance_cases",
        ["submitted_by_user_id", "created_at"],
    )
    op.create_index(
        "idx_special_cases_teacher_period",
        "special_performance_cases",
        ["teacher_id", "period_id"],
    )

    op.create_table(
        "special_performance_case_materials",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("material_key", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content", mysql.MEDIUMBLOB(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["special_performance_cases.id"]),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"]),
        sa.UniqueConstraint(
            "case_id", "material_key", "version", name="uk_special_material_version"
        ),
    )
    op.create_index(
        "idx_special_materials_case_current",
        "special_performance_case_materials",
        ["case_id", "is_current"],
    )

    op.create_table(
        "special_performance_case_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("from_status", sa.String(length=16), nullable=True),
        sa.Column("to_status", sa.String(length=16), nullable=True),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("details", mysql.JSON(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["special_performance_cases.id"]),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
    )
    op.create_index(
        "idx_special_case_events_case_created",
        "special_performance_case_events",
        ["case_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_special_case_events_case_created",
        table_name="special_performance_case_events",
    )
    op.drop_table("special_performance_case_events")
    op.drop_index(
        "idx_special_materials_case_current",
        table_name="special_performance_case_materials",
    )
    op.drop_table("special_performance_case_materials")
    op.drop_index(
        "idx_special_cases_teacher_period", table_name="special_performance_cases"
    )
    op.drop_index(
        "idx_special_cases_owner_created", table_name="special_performance_cases"
    )
    op.drop_index(
        "idx_special_cases_status_due", table_name="special_performance_cases"
    )
    op.drop_table("special_performance_cases")
    op.drop_column("rule_plugins", "purpose")
