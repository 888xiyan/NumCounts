"""Align formal result amount type with the ORM model.

Revision ID: 20261020_0009
Revises: 20261020_0008
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261020_0009"
down_revision: str | None = "20261020_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "formal_calculation_results",
        "total_amount",
        existing_type=sa.Float(),
        type_=sa.Double(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "formal_calculation_results",
        "total_amount",
        existing_type=sa.Double(),
        type_=sa.Float(),
        existing_nullable=True,
    )
