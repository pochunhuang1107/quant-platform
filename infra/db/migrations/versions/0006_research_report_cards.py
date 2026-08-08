"""Add durable research report-card table.

Revision ID: 0006_research_report_cards
Revises: 0005_artifact_run_identity
Create Date: 2026-08-08 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_research_report_cards"
down_revision: str | None = "0005_artifact_run_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create durable deterministic report-card persistence table."""

    op.create_table(
        "research_report_cards",
        sa.Column("report_card_id", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("derivation_policy_version", sa.Text(), nullable=False),
        sa.Column("source_run_id", sa.Text(), nullable=False),
        sa.Column("experiment_id", sa.Text(), nullable=False),
        sa.Column("strategy_id", sa.Text(), nullable=False),
        sa.Column("strategy_version", sa.Text(), nullable=False),
        sa.Column("data_snapshot_id", sa.Text(), nullable=False),
        sa.Column("benchmark_snapshot_id", sa.Text(), nullable=False),
        sa.Column("artifact_manifest_id", sa.Text(), nullable=False),
        sa.Column("contract_hash", sa.Text(), nullable=False),
        sa.Column("raw_contract", postgresql.JSONB(), nullable=False),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_run_id"],
            ["experiment_runs.run_id"],
            name="fk_research_report_cards_source_run_id_experiment_runs",
        ),
        sa.ForeignKeyConstraint(
            ["data_snapshot_id"],
            ["data_snapshot_manifests.snapshot_id"],
            name=("fk_research_report_cards_data_snapshot_id_data_snapshot_manifests"),
        ),
        sa.ForeignKeyConstraint(
            ["benchmark_snapshot_id"],
            ["data_snapshot_manifests.snapshot_id"],
            name=(
                "fk_research_report_cards_benchmark_snapshot_id_data_snapshot_manifests"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["artifact_manifest_id"],
            ["run_artifact_manifests.manifest_id"],
            name=(
                "fk_research_report_cards_artifact_manifest_id_run_artifact_manifests"
            ),
        ),
        sa.PrimaryKeyConstraint("report_card_id", name="pk_research_report_cards"),
    )
    op.create_index(
        "ix_research_report_cards_source_run_id",
        "research_report_cards",
        ["source_run_id"],
    )
    op.create_index(
        "ix_research_report_cards_experiment_id",
        "research_report_cards",
        ["experiment_id"],
    )
    op.create_index(
        "ix_research_report_cards_strategy_id_strategy_version",
        "research_report_cards",
        ["strategy_id", "strategy_version"],
    )


def downgrade() -> None:
    """Drop durable deterministic report-card persistence table."""

    op.drop_index(
        "ix_research_report_cards_strategy_id_strategy_version",
        table_name="research_report_cards",
    )
    op.drop_index(
        "ix_research_report_cards_experiment_id",
        table_name="research_report_cards",
    )
    op.drop_index(
        "ix_research_report_cards_source_run_id",
        table_name="research_report_cards",
    )
    op.drop_table("research_report_cards")
