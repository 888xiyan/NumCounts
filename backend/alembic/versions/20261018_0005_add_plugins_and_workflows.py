"""add rule plugins and operator workflows

Revision ID: 20261018_0005
Revises: 20261016_0004
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261018_0005"
down_revision = "20261016_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rule_plugins",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("plugin_key", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("function_spec", mysql.JSON(), nullable=False),
        sa.Column("input_defaults", mysql.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint("plugin_key", "version", name="uk_rule_plugin_key_version"),
    )
    op.create_index("idx_rule_plugins_status", "rule_plugins", ["status"])

    op.add_column(
        "calculation_records",
        sa.Column("plugin_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "calculation_records",
        sa.Column("plugin_snapshot", mysql.JSON(), nullable=True),
    )
    op.create_foreign_key(
        "fk_calculation_records_plugin_id",
        "calculation_records",
        "rule_plugins",
        ["plugin_id"],
        ["id"],
    )

    op.create_table(
        "workflow_definitions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workflow_key", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint("workflow_key", "version", name="uk_workflow_key_version"),
    )
    op.create_index("idx_workflows_status", "workflow_definitions", ["status"])

    op.create_table(
        "workflow_nodes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("node_key", sa.String(length=64), nullable=False),
        sa.Column("node_type", sa.String(length=32), nullable=False),
        sa.Column("position", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("config", mysql.JSON(), nullable=False),
        sa.Column("plugin_snapshot", mysql.JSON(), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow_definitions.id"]),
        sa.UniqueConstraint("workflow_id", "node_key", name="uk_workflow_node_key"),
        sa.UniqueConstraint("workflow_id", "position", name="uk_workflow_node_position"),
    )

    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_key", sa.String(length=64), nullable=False),
        sa.Column("workflow_version", sa.String(length=64), nullable=False),
        sa.Column("period_id", sa.String(length=64), nullable=True),
        sa.Column("context", mysql.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("result_data", mysql.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_details", mysql.JSON(), nullable=True),
        sa.Column("requested_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("started_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("finished_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow_definitions.id"]),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"]),
    )
    op.create_index(
        "idx_workflow_runs_workflow_started",
        "workflow_runs",
        ["workflow_id", "started_at"],
    )

    op.create_table(
        "workflow_run_nodes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_node_id", sa.String(length=36), nullable=False),
        sa.Column("node_key", sa.String(length=64), nullable=False),
        sa.Column("node_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("calculation_record_id", sa.String(length=36), nullable=True),
        sa.Column("input_snapshot", mysql.JSON(), nullable=True),
        sa.Column("output_snapshot", mysql.JSON(), nullable=True),
        sa.Column("error_snapshot", mysql.JSON(), nullable=True),
        sa.Column("started_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("finished_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"]),
        sa.ForeignKeyConstraint(["workflow_node_id"], ["workflow_nodes.id"]),
        sa.ForeignKeyConstraint(["calculation_record_id"], ["calculation_records.id"]),
        sa.UniqueConstraint("workflow_run_id", "node_key", name="uk_workflow_run_node"),
    )
    op.create_index(
        "idx_workflow_run_nodes_run",
        "workflow_run_nodes",
        ["workflow_run_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_workflow_run_nodes_run", table_name="workflow_run_nodes")
    op.drop_table("workflow_run_nodes")
    op.drop_index("idx_workflow_runs_workflow_started", table_name="workflow_runs")
    op.drop_table("workflow_runs")
    op.drop_table("workflow_nodes")
    op.drop_index("idx_workflows_status", table_name="workflow_definitions")
    op.drop_table("workflow_definitions")
    op.drop_constraint(
        "fk_calculation_records_plugin_id",
        "calculation_records",
        type_="foreignkey",
    )
    op.drop_column("calculation_records", "plugin_snapshot")
    op.drop_column("calculation_records", "plugin_id")
    op.drop_index("idx_rule_plugins_status", table_name="rule_plugins")
    op.drop_table("rule_plugins")
