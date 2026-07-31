"""Enforce one artifact manifest per run.

Revision ID: 0005_artifact_run_identity
Revises: 0004_research_review_tables
Create Date: 2026-07-29 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005_artifact_run_identity"
down_revision: str | None = "0004_research_review_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Promote run_id to the artifact manifest natural aggregate identity."""

    op.create_unique_constraint(
        "uq_run_artifact_manifests_run_id",
        "run_artifact_manifests",
        ["run_id"],
    )
    op.drop_constraint(
        "uq_run_artifact_manifests_run_id_contract_hash",
        "run_artifact_manifests",
        type_="unique",
    )
    op.drop_index(
        "ix_run_artifact_manifests_run_id",
        table_name="run_artifact_manifests",
    )


def downgrade() -> None:
    """Restore the artifact manifest identity schema from revision 0004."""

    op.create_unique_constraint(
        "uq_run_artifact_manifests_run_id_contract_hash",
        "run_artifact_manifests",
        ["run_id", "contract_hash"],
    )
    op.create_index(
        "ix_run_artifact_manifests_run_id",
        "run_artifact_manifests",
        ["run_id"],
    )
    op.drop_constraint(
        "uq_run_artifact_manifests_run_id",
        "run_artifact_manifests",
        type_="unique",
    )
