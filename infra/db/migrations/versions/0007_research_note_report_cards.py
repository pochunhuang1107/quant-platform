"""Add durable research note to report-card links.

Revision ID: 0007_research_note_report_cards
Revises: 0006_research_report_cards
Create Date: 2026-08-08 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_research_note_report_cards"
down_revision: str | None = "0006_research_report_cards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create normalized research-note to report-card association table."""

    op.create_table(
        "research_note_report_cards",
        sa.Column("note_id", sa.Text(), nullable=False),
        sa.Column("report_card_id", sa.Text(), nullable=False),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["note_id"],
            ["research_notes.note_id"],
            name="fk_note_report_cards_note_id",
        ),
        sa.ForeignKeyConstraint(
            ["report_card_id"],
            ["research_report_cards.report_card_id"],
            name="fk_note_report_cards_report_card_id",
        ),
        sa.PrimaryKeyConstraint(
            "note_id",
            "report_card_id",
            name="pk_research_note_report_cards",
        ),
    )
    op.create_index(
        "ix_research_note_report_cards_report_card_id",
        "research_note_report_cards",
        ["report_card_id"],
    )


def downgrade() -> None:
    """Drop normalized research-note to report-card association table."""

    op.drop_index(
        "ix_research_note_report_cards_report_card_id",
        table_name="research_note_report_cards",
    )
    op.drop_table("research_note_report_cards")
