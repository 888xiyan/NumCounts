"""add record links and runtime governance

Revision ID: 20261018_0006
Revises: 20261018_0005
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261018_0006"
down_revision = "20261018_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "record_links",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source_record_id", sa.String(length=36), nullable=False),
        sa.Column("target_record_id", sa.String(length=36), nullable=False),
        sa.Column("link_type", sa.String(length=16), nullable=False),
        sa.Column("input_key", sa.String(length=64), nullable=False),
        sa.Column("target_path", sa.String(length=256), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["source_record_id"], ["calculation_records.id"]),
        sa.ForeignKeyConstraint(["target_record_id"], ["calculation_records.id"]),
        sa.UniqueConstraint("source_record_id", "input_key", name="uk_record_link_input"),
    )
    op.create_index("idx_record_links_target", "record_links", ["target_record_id"])

    op.add_column(
        "calculation_attempts",
        sa.Column("link_snapshot", mysql.JSON(), nullable=True),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=36), nullable=False),
        sa.Column("details", mysql.JSON(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
    )
    op.create_index(
        "idx_audit_resource_created", "audit_events", ["resource_type", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_audit_resource_created", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_column("calculation_attempts", "link_snapshot")
    op.drop_index("idx_record_links_target", table_name="record_links")
    op.drop_table("record_links")
