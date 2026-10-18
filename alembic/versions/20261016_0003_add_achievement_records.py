"""add achievement records data MVP

Revision ID: 20261016_0003
Revises: 20261016_0002
Create Date: 2026-10-16
"""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261016_0003"
down_revision = "20261016_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "achievement_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("teacher_id", sa.String(length=64), nullable=False),
        sa.Column("teacher_name", sa.String(length=128), nullable=False),
        sa.Column("department_id", sa.String(length=64), nullable=False),
        sa.Column("achievement_type", sa.String(length=32), nullable=False),
        sa.Column("level", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_record_id", sa.String(length=128), nullable=True),
        sa.Column("payload", mysql.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("submitted_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["submitted_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"]),
        sa.UniqueConstraint(
            "source", "source_record_id", name="uk_achievement_source_record"
        ),
    )
    op.create_index(
        "idx_achievement_status_occurred",
        "achievement_records",
        ["status", "occurred_at"],
    )
    op.create_index(
        "idx_achievement_teacher_status",
        "achievement_records",
        ["teacher_id", "status"],
    )
    op.create_index(
        "idx_achievement_department_status",
        "achievement_records",
        ["department_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("idx_achievement_department_status", table_name="achievement_records")
    op.drop_index("idx_achievement_teacher_status", table_name="achievement_records")
    op.drop_index("idx_achievement_status_occurred", table_name="achievement_records")
    op.drop_table("achievement_records")
