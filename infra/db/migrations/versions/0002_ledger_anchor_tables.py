"""Add ledger anchor tables.

Revision ID: 0002_ledger_anchor_tables
Revises: 0001_persistence_baseline
Create Date: 2026-07-10 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_ledger_anchor_tables"
down_revision: str | None = "0001_persistence_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the first experiment ledger anchor tables."""

    op.create_table(
        "experiment_runs",
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("experiment_id", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("status_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status_updated_by", sa.Text(), nullable=False),
        sa.Column("strategy_id", sa.Text(), nullable=False),
        sa.Column("strategy_version", sa.Text(), nullable=False),
        sa.Column("git_commit_sha", sa.Text(), nullable=False),
        sa.Column("repo_dirty", sa.Boolean(), nullable=False),
        sa.Column("asset_class", sa.Text(), nullable=False),
        sa.Column("frequency", sa.Text(), nullable=False),
        sa.Column("data_snapshot_id", sa.Text(), nullable=False),
        sa.Column("feature_snapshot_id", sa.Text(), nullable=True),
        sa.Column("artifact_uri", sa.Text(), nullable=False),
        sa.Column("artifact_manifest_uri", sa.Text(), nullable=False),
        sa.Column("artifact_manifest_hash", sa.Text(), nullable=False),
        sa.Column("parent_run_id", sa.Text(), nullable=True),
        sa.Column("supersedes_run_id", sa.Text(), nullable=True),
        sa.Column("review_status", sa.Text(), nullable=False),
        sa.Column("reviewer_id", sa.Text(), nullable=True),
        sa.Column("review_role", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("risk_approval_required", sa.Boolean(), nullable=False),
        sa.Column("contract_hash", sa.Text(), nullable=False),
        sa.Column("raw_contract", postgresql.JSONB(), nullable=False),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "parent_run_id IS NULL OR parent_run_id <> run_id",
            name="parent_run_id_not_self",
        ),
        sa.CheckConstraint(
            "supersedes_run_id IS NULL OR supersedes_run_id <> run_id",
            name="supersedes_run_id_not_self",
        ),
        sa.CheckConstraint(
            "status IN ("
            "'created', 'running', 'completed', 'under_review', 'accepted', "
            "'rejected', 'failed', 'invalid', 'superseded', 'cancelled'"
            ")",
            name="status_values",
        ),
        sa.CheckConstraint(
            "asset_class IN ("
            "'equities', 'etfs', 'futures', 'fx', 'crypto', 'indices', "
            "'options', 'mixed'"
            ")",
            name="asset_class_values",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending', 'approved', 'rejected', 'changes_requested')",
            name="review_status_values",
        ),
        sa.CheckConstraint(
            "review_role IS NULL OR review_role IN ("
            "'human_owner', 'risk_reviewer', 'agent_reviewer'"
            ")",
            name="review_role_values",
        ),
        sa.PrimaryKeyConstraint("run_id", name="pk_experiment_runs"),
    )
    op.create_index(
        "ix_experiment_runs_status_created_at",
        "experiment_runs",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_experiment_runs_strategy_id_created_at",
        "experiment_runs",
        ["strategy_id", "created_at"],
    )
    op.create_index(
        "ix_experiment_runs_experiment_id_created_at",
        "experiment_runs",
        ["experiment_id", "created_at"],
    )
    op.create_index(
        "ix_experiment_runs_data_snapshot_id",
        "experiment_runs",
        ["data_snapshot_id"],
    )
    op.create_index(
        "ix_experiment_runs_parent_run_id",
        "experiment_runs",
        ["parent_run_id"],
    )
    op.create_index(
        "ix_experiment_runs_supersedes_run_id",
        "experiment_runs",
        ["supersedes_run_id"],
    )

    op.create_table(
        "data_snapshot_manifests",
        sa.Column("snapshot_id", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("snapshot_kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("asset_class", sa.Text(), nullable=False),
        sa.Column("frequency", sa.Text(), nullable=False),
        sa.Column("data_root_uri", sa.Text(), nullable=False),
        sa.Column("source_dataset", sa.Text(), nullable=False),
        sa.Column("source_version", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("vendor_name", sa.Text(), nullable=True),
        sa.Column("temporal_coverage", sa.Text(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingestion_completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("adjustment_policy", sa.Text(), nullable=False),
        sa.Column("calendar", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("row_count", sa.BigInteger(), nullable=False),
        sa.Column("file_count", sa.BigInteger(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("contract_hash", sa.Text(), nullable=False),
        sa.Column("raw_contract", postgresql.JSONB(), nullable=False),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "row_count >= 0",
            name="row_count_nonnegative",
        ),
        sa.CheckConstraint(
            "file_count IS NULL OR file_count >= 0",
            name="file_count_nonnegative",
        ),
        sa.CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0",
            name="size_bytes_nonnegative",
        ),
        sa.CheckConstraint(
            "snapshot_kind IN ("
            "'market_data', 'fundamental_data', 'reference_data', "
            "'corporate_actions', 'universe_membership', 'benchmark_data', "
            "'mixed', 'other'"
            ")",
            name="snapshot_kind_values",
        ),
        sa.CheckConstraint(
            "status IN ('created', 'completed', 'failed', 'invalid', 'superseded')",
            name="status_values",
        ),
        sa.CheckConstraint(
            "asset_class IN ("
            "'equities', 'etfs', 'futures', 'fx', 'crypto', 'indices', "
            "'options', 'mixed'"
            ")",
            name="asset_class_values",
        ),
        sa.CheckConstraint(
            "source_type IN ("
            "'vendor', 'exchange', 'public_dataset', 'internal', "
            "'research_generated', 'manual', 'other'"
            ")",
            name="source_type_values",
        ),
        sa.CheckConstraint(
            "temporal_coverage IN ("
            "'point_in_time', 'first_available', 'latest_known', 'mixed', "
            "'not_applicable'"
            ")",
            name="temporal_coverage_values",
        ),
        sa.CheckConstraint(
            "adjustment_policy IN ("
            "'raw', 'split_adjusted', 'total_return', 'continuous', 'other'"
            ")",
            name="adjustment_policy_values",
        ),
        sa.PrimaryKeyConstraint("snapshot_id", name="pk_data_snapshot_manifests"),
    )
    op.create_index(
        "ix_data_snapshot_manifests_snapshot_kind_status_created_at",
        "data_snapshot_manifests",
        ["snapshot_kind", "status", "created_at"],
    )
    op.create_index(
        "ix_data_snapshot_manifests_asset_source_created_at",
        "data_snapshot_manifests",
        ["asset_class", "source_dataset", "created_at"],
    )


def downgrade() -> None:
    """Drop the first experiment ledger anchor tables."""

    op.drop_index(
        "ix_data_snapshot_manifests_asset_source_created_at",
        table_name="data_snapshot_manifests",
    )
    op.drop_index(
        "ix_data_snapshot_manifests_snapshot_kind_status_created_at",
        table_name="data_snapshot_manifests",
    )
    op.drop_table("data_snapshot_manifests")

    op.drop_index(
        "ix_experiment_runs_supersedes_run_id",
        table_name="experiment_runs",
    )
    op.drop_index(
        "ix_experiment_runs_parent_run_id",
        table_name="experiment_runs",
    )
    op.drop_index(
        "ix_experiment_runs_data_snapshot_id",
        table_name="experiment_runs",
    )
    op.drop_index(
        "ix_experiment_runs_experiment_id_created_at",
        table_name="experiment_runs",
    )
    op.drop_index(
        "ix_experiment_runs_strategy_id_created_at",
        table_name="experiment_runs",
    )
    op.drop_index(
        "ix_experiment_runs_status_created_at",
        table_name="experiment_runs",
    )
    op.drop_table("experiment_runs")
