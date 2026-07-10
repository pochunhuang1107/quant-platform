"""Persistence baseline.

Revision ID: 0001_persistence_baseline
Revises:
Create Date: 2026-07-10 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0001_persistence_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the empty persistence baseline."""
    # PR 11 intentionally creates no tables.


def downgrade() -> None:
    """Revert the empty persistence baseline."""
    # Baseline removal has no table effects.
