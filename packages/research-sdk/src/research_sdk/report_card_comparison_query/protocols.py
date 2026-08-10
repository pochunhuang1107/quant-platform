"""Read-only repository protocol for persisted report-card comparison queries."""

from __future__ import annotations

from typing import Protocol

from research_sdk.contracts import ResearchNote, ResearchReportCard


class ResearchComparisonReadRepository(Protocol):
    """Minimal durable read boundary required by C2b query service."""

    def get_research_report_card(
        self,
        report_card_id: str,
    ) -> ResearchReportCard | None:
        """Return None or a card whose report_card_id equals the requested ID."""
        ...

    def get_research_note(
        self,
        note_id: str,
    ) -> ResearchNote | None:
        """Return None or a note whose note_id equals the requested ID."""
        ...

    def get_research_note_ids_for_report_card(
        self,
        report_card_id: str,
    ) -> tuple[str, ...]:
        """Return unique nonempty note IDs in ascending order."""
        ...


__all__ = ["ResearchComparisonReadRepository"]
