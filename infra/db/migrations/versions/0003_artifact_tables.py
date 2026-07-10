"""Add artifact manifest and entry tables.

Revision ID: 0003_artifact_tables
Revises: 0002_ledger_anchor_tables
Create Date: 2026-07-10 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_artifact_tables"
down_revision: str | None = "0002_ledger_anchor_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create run artifact manifest and entry projection tables."""

    op.create_table(
        "run_artifact_manifests",
        sa.Column("manifest_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("experiment_id", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("artifact_root_uri", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("required_artifacts_complete", sa.Boolean(), nullable=False),
        sa.Column("contract_hash", sa.Text(), nullable=False),
        sa.Column("raw_contract", postgresql.JSONB(), nullable=False),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("manifest_id", name="pk_run_artifact_manifests"),
        sa.UniqueConstraint(
            "run_id",
            "contract_hash",
            name="uq_run_artifact_manifests_run_id_contract_hash",
        ),
    )
    op.create_index(
        "ix_run_artifact_manifests_run_id",
        "run_artifact_manifests",
        ["run_id"],
    )
    op.create_index(
        "ix_run_artifact_manifests_experiment_id_created_at",
        "run_artifact_manifests",
        ["experiment_id", "created_at"],
    )

    op.create_table(
        "run_artifact_entries",
        sa.Column("manifest_id", sa.Text(), nullable=False),
        sa.Column("artifact_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("artifact_kind", sa.Text(), nullable=False),
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("hash_algorithm", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("row_count", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("validator_version", sa.Text(), nullable=True),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["manifest_id"],
            ["run_artifact_manifests.manifest_id"],
            name="fk_run_artifact_entries_manifest_id_run_artifact_manifests",
        ),
        sa.CheckConstraint(
            "artifact_kind IN ("
            "'config', 'metrics', 'trade_log', 'signal_log', 'daily_equity', "
            "'drawdown_series', 'monthly_returns', 'regime_breakdown', "
            "'failure_analysis', 'research_note', 'chart', 'log', "
            "'diagnostic', 'other'"
            ")",
            name="artifact_kind_values",
        ),
        sa.CheckConstraint(
            "format IN ("
            "'json', 'parquet', 'markdown', 'png', 'svg', 'html', 'csv', 'text'"
            ")",
            name="format_values",
        ),
        sa.CheckConstraint(
            "status IN ('produced', 'missing', 'failed', 'skipped')",
            name="status_values",
        ),
        sa.CheckConstraint(
            "hash_algorithm IS NULL OR hash_algorithm IN ('sha256')",
            name="hash_algorithm_values",
        ),
        sa.CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0",
            name="size_bytes_nonnegative",
        ),
        sa.CheckConstraint(
            "row_count IS NULL OR row_count >= 0",
            name="row_count_nonnegative",
        ),
        sa.PrimaryKeyConstraint(
            "manifest_id",
            "artifact_id",
            name="pk_run_artifact_entries",
        ),
    )
    op.create_index(
        "ix_run_artifact_entries_run_id_artifact_kind",
        "run_artifact_entries",
        ["run_id", "artifact_kind"],
    )
    op.create_index(
        "ix_run_artifact_entries_status",
        "run_artifact_entries",
        ["status"],
    )
    op.create_index(
        "ix_run_artifact_entries_manifest_id",
        "run_artifact_entries",
        ["manifest_id"],
    )


def downgrade() -> None:
    """Drop run artifact manifest and entry projection tables."""

    op.drop_index(
        "ix_run_artifact_entries_manifest_id",
        table_name="run_artifact_entries",
    )
    op.drop_index(
        "ix_run_artifact_entries_status",
        table_name="run_artifact_entries",
    )
    op.drop_index(
        "ix_run_artifact_entries_run_id_artifact_kind",
        table_name="run_artifact_entries",
    )
    op.drop_table("run_artifact_entries")

    op.drop_index(
        "ix_run_artifact_manifests_experiment_id_created_at",
        table_name="run_artifact_manifests",
    )
    op.drop_index(
        "ix_run_artifact_manifests_run_id",
        table_name="run_artifact_manifests",
    )
    op.drop_table("run_artifact_manifests")
