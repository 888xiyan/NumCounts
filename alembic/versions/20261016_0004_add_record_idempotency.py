"""add calculation record idempotency key

Revision ID: 20261016_0004
Revises: 20261016_0003
Create Date: 2026-10-16
"""

import sqlalchemy as sa

from alembic import op

revision = "20261016_0004"
down_revision = "20261016_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "calculation_records",
        sa.Column("idempotency_key", sa.String(length=36), nullable=True),
    )
    op.create_unique_constraint(
        "uk_records_idempotency_key", "calculation_records", ["idempotency_key"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uk_records_idempotency_key", "calculation_records", type_="unique"
    )
    op.drop_column("calculation_records", "idempotency_key")
