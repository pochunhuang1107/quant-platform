"""Add research note and review event tables.

Revision ID: 0004_research_review_tables
Revises: 0003_artifact_tables
Create Date: 2026-07-10 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_research_review_tables"
down_revision: str | None = "0003_artifact_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create research note and generic review event metadata tables."""

    op.create_table(
        "research_notes",
        sa.Column("note_id", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("note_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("hypothesis_status", sa.Text(), nullable=False),
        sa.Column("evidence_strength", sa.Text(), nullable=False),
        sa.Column("decision_outcome", sa.Text(), nullable=False),
        sa.Column("parent_note_id", sa.Text(), nullable=True),
        sa.Column("supersedes_note_id", sa.Text(), nullable=True),
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
            "parent_note_id IS NULL OR parent_note_id <> note_id",
            name="parent_note_id_not_self",
        ),
        sa.CheckConstraint(
            "supersedes_note_id IS NULL OR supersedes_note_id <> note_id",
            name="supersedes_note_id_not_self",
        ),
        sa.CheckConstraint(
            "note_type IN ("
            "'hypothesis', 'experiment_result', 'failure_analysis', "
            "'review_note', 'other'"
            ")",
            name="note_type_values",
        ),
        sa.CheckConstraint(
            "status IN ("
            "'draft', 'ready_for_review', 'under_review', 'finalized', "
            "'superseded', 'archived'"
            ")",
            name="status_values",
        ),
        sa.CheckConstraint(
            "hypothesis_status IN ("
            "'proposed', 'testing', 'supported', 'partially_supported', "
            "'not_supported', 'inconclusive', 'superseded'"
            ")",
            name="hypothesis_status_values",
        ),
        sa.CheckConstraint(
            "evidence_strength IN ('none', 'weak', 'moderate', 'strong')",
            name="evidence_strength_values",
        ),
        sa.CheckConstraint(
            "decision_outcome IN ("
            "'no_decision', 'continue_research', 'accept_result', "
            "'reject_result', 'mark_invalid', 'supersede_prior', "
            "'needs_changes'"
            ")",
            name="decision_outcome_values",
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
        sa.PrimaryKeyConstraint("note_id", name="pk_research_notes"),
    )
    op.create_index(
        "ix_research_notes_status_updated_at",
        "research_notes",
        ["status", "updated_at"],
    )
    op.create_index(
        "ix_research_notes_note_type_created_at",
        "research_notes",
        ["note_type", "created_at"],
    )
    op.create_index(
        "ix_research_notes_review_status_updated_at",
        "research_notes",
        ["review_status", "updated_at"],
    )
    op.create_index(
        "ix_research_notes_decision_outcome_updated_at",
        "research_notes",
        ["decision_outcome", "updated_at"],
    )
    op.create_index(
        "ix_research_notes_parent_note_id",
        "research_notes",
        ["parent_note_id"],
    )
    op.create_index(
        "ix_research_notes_supersedes_note_id",
        "research_notes",
        ["supersedes_note_id"],
    )

    op.create_table(
        "review_events",
        sa.Column("review_event_id", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("review_status", sa.Text(), nullable=False),
        sa.Column("reviewer_id", sa.Text(), nullable=True),
        sa.Column("review_role", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision", sa.Text(), nullable=True),
        sa.Column("approval_scope", sa.Text(), nullable=True),
        sa.Column("approval_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("linked_pr", sa.Text(), nullable=True),
        sa.Column("review_notes_uri", sa.Text(), nullable=True),
        sa.Column("risk_approval_required", sa.Boolean(), nullable=False),
        sa.Column("raw_review", postgresql.JSONB(), nullable=False),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "subject_type IN ("
            "'experiment_run', 'research_note', 'data_snapshot_manifest', "
            "'run_artifact_manifest'"
            ")",
            name="subject_type_values",
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
        sa.PrimaryKeyConstraint("review_event_id", name="pk_review_events"),
    )
    op.create_index(
        "ix_review_events_subject_type_subject_id_inserted_at",
        "review_events",
        ["subject_type", "subject_id", "inserted_at"],
    )
    op.create_index(
        "ix_review_events_reviewer_id_inserted_at",
        "review_events",
        ["reviewer_id", "inserted_at"],
    )
    op.create_index(
        "ix_review_events_review_status_inserted_at",
        "review_events",
        ["review_status", "inserted_at"],
    )


def downgrade() -> None:
    """Drop research note and generic review event metadata tables."""

    op.drop_index(
        "ix_review_events_review_status_inserted_at",
        table_name="review_events",
    )
    op.drop_index(
        "ix_review_events_reviewer_id_inserted_at",
        table_name="review_events",
    )
    op.drop_index(
        "ix_review_events_subject_type_subject_id_inserted_at",
        table_name="review_events",
    )
    op.drop_table("review_events")

    op.drop_index(
        "ix_research_notes_supersedes_note_id",
        table_name="research_notes",
    )
    op.drop_index(
        "ix_research_notes_parent_note_id",
        table_name="research_notes",
    )
    op.drop_index(
        "ix_research_notes_decision_outcome_updated_at",
        table_name="research_notes",
    )
    op.drop_index(
        "ix_research_notes_review_status_updated_at",
        table_name="research_notes",
    )
    op.drop_index(
        "ix_research_notes_note_type_created_at",
        table_name="research_notes",
    )
    op.drop_index(
        "ix_research_notes_status_updated_at",
        table_name="research_notes",
    )
    op.drop_table("research_notes")
