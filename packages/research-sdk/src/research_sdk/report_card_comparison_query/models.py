"""Read-only persisted report-card comparison query models."""

from __future__ import annotations

from typing import Self

from pydantic import model_validator

from research_sdk.contracts import (
    BaseContractModel,
    DecisionOutcome,
    EvidenceStrength,
    ResearchNoteStatus,
    ResearchNoteType,
    ReviewRole,
    ReviewStatus,
    UtcDatetime,
)
from research_sdk.contracts.types import NonEmptyString
from research_sdk.report_card_comparison import (
    ComparisonCompatibilityStatus,
    ReportCardCompatibilityAssessment,
    ResearchReportCardComparison,
)


class LinkedResearchNoteReviewState(BaseContractModel):
    """Direct persisted ResearchNote review-state facts linked to a report card."""

    note_id: NonEmptyString
    note_type: ResearchNoteType
    note_status: ResearchNoteStatus
    title: NonEmptyString
    updated_at: UtcDatetime
    evidence_strength: EvidenceStrength
    research_decision_outcome: DecisionOutcome
    review_status: ReviewStatus
    reviewer_id: NonEmptyString | None = None
    review_role: ReviewRole | None = None
    reviewed_at: UtcDatetime | None = None
    review_decision: str | None = None
    approval_scope: str | None = None
    approval_expires_at: UtcDatetime | None = None
    linked_pr: str | None = None
    review_notes_uri: str | None = None
    risk_approval_required: bool
    parent_note_id: NonEmptyString | None = None
    supersedes_note_id: NonEmptyString | None = None


class ResearchReportCardComparisonQueryResult(BaseContractModel):
    """Read-time C2b projection for one ordered persisted report-card pair."""

    baseline_report_card_id: NonEmptyString
    candidate_report_card_id: NonEmptyString
    compatibility: ReportCardCompatibilityAssessment
    comparison: ResearchReportCardComparison | None
    baseline_review_states: tuple[LinkedResearchNoteReviewState, ...] = ()
    candidate_review_states: tuple[LinkedResearchNoteReviewState, ...] = ()

    @model_validator(mode="after")
    def validate_query_result_invariants(self) -> Self:
        """Reject contradictory comparison and linked-note state."""

        if self.compatibility.status is ComparisonCompatibilityStatus.INCOMPATIBLE:
            if self.comparison is not None:
                raise ValueError(
                    "incompatible query result must not include comparison"
                )
        elif self.comparison is None:
            raise ValueError("compatible query result requires comparison")

        if self.comparison is not None:
            if self.comparison.baseline_report_card_id != self.baseline_report_card_id:
                raise ValueError("comparison baseline_report_card_id mismatch")
            if (
                self.comparison.candidate_report_card_id
                != self.candidate_report_card_id
            ):
                raise ValueError("comparison candidate_report_card_id mismatch")
            if self.comparison.compatibility != self.compatibility:
                raise ValueError("comparison compatibility mismatch")

        _validate_review_state_order(
            self.baseline_review_states,
            "baseline_review_states",
        )
        _validate_review_state_order(
            self.candidate_review_states,
            "candidate_review_states",
        )
        return self


def _validate_review_state_order(
    review_states: tuple[LinkedResearchNoteReviewState, ...],
    field_name: str,
) -> None:
    note_ids = tuple(review_state.note_id for review_state in review_states)
    if len(set(note_ids)) != len(note_ids):
        raise ValueError(f"{field_name} must not contain duplicate note_ids")
    if note_ids != tuple(sorted(note_ids)):
        raise ValueError(f"{field_name} must use ascending note_id order")


__all__ = [
    "LinkedResearchNoteReviewState",
    "ResearchReportCardComparisonQueryResult",
]
