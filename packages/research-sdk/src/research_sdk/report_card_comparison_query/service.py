"""Read-only persisted report-card comparison query service."""

from __future__ import annotations

from typing import Literal

from research_sdk.contracts import ResearchNote, ResearchReportCard
from research_sdk.report_card_comparison import (
    ComparisonCompatibilityStatus,
    assess_research_report_card_compatibility,
    compare_research_report_cards,
)
from research_sdk.report_card_comparison_query.models import (
    LinkedResearchNoteReviewState,
    ResearchReportCardComparisonQueryResult,
)
from research_sdk.report_card_comparison_query.protocols import (
    ResearchComparisonReadRepository,
)

type ReportCardComparisonQueryRole = Literal["baseline", "candidate"]


class ResearchReportCardComparisonQueryError(ValueError):
    """Base error for deterministic C2b query input and integrity failures."""


class ResearchReportCardComparisonQueryNotFoundError(
    ResearchReportCardComparisonQueryError
):
    """Raised when a requested persisted report-card input does not exist."""

    role: ReportCardComparisonQueryRole
    report_card_id: str

    def __init__(
        self,
        *,
        role: ReportCardComparisonQueryRole,
        report_card_id: str,
    ) -> None:
        super().__init__(f"{role} report_card_id not found: {report_card_id}")
        self.role = role
        self.report_card_id = report_card_id


class ResearchReportCardComparisonQueryIntegrityError(
    ResearchReportCardComparisonQueryError
):
    """Raised when repository read output is internally contradictory."""


def query_research_report_card_comparison(
    *,
    baseline_report_card_id: str,
    candidate_report_card_id: str,
    repository: ResearchComparisonReadRepository,
) -> ResearchReportCardComparisonQueryResult:
    """Read persisted cards, run C2a, and expose linked ResearchNote review facts."""

    baseline, candidate = _load_report_cards(
        baseline_report_card_id=baseline_report_card_id,
        candidate_report_card_id=candidate_report_card_id,
        repository=repository,
    )
    compatibility = assess_research_report_card_compatibility(
        baseline=baseline,
        candidate=candidate,
    )
    if baseline_report_card_id == candidate_report_card_id:
        linked_states = _linked_review_states(
            report_card_id=baseline_report_card_id,
            repository=repository,
        )
        baseline_review_states = linked_states
        candidate_review_states = linked_states
    else:
        baseline_review_states = _linked_review_states(
            report_card_id=baseline_report_card_id,
            repository=repository,
        )
        candidate_review_states = _linked_review_states(
            report_card_id=candidate_report_card_id,
            repository=repository,
        )

    comparison = None
    if compatibility.status is not ComparisonCompatibilityStatus.INCOMPATIBLE:
        comparison = compare_research_report_cards(
            baseline=baseline, candidate=candidate
        )

    return ResearchReportCardComparisonQueryResult(
        baseline_report_card_id=baseline_report_card_id,
        candidate_report_card_id=candidate_report_card_id,
        compatibility=compatibility,
        comparison=comparison,
        baseline_review_states=baseline_review_states,
        candidate_review_states=candidate_review_states,
    )


def _load_report_cards(
    *,
    baseline_report_card_id: str,
    candidate_report_card_id: str,
    repository: ResearchComparisonReadRepository,
) -> tuple[ResearchReportCard, ResearchReportCard]:
    baseline = repository.get_research_report_card(baseline_report_card_id)
    if baseline is None:
        raise ResearchReportCardComparisonQueryNotFoundError(
            role="baseline",
            report_card_id=baseline_report_card_id,
        )
    _require_requested_report_card_id(
        role="baseline",
        requested_report_card_id=baseline_report_card_id,
        returned_report_card=baseline,
    )
    if baseline_report_card_id == candidate_report_card_id:
        return baseline, baseline

    candidate = repository.get_research_report_card(candidate_report_card_id)
    if candidate is None:
        raise ResearchReportCardComparisonQueryNotFoundError(
            role="candidate",
            report_card_id=candidate_report_card_id,
        )
    _require_requested_report_card_id(
        role="candidate",
        requested_report_card_id=candidate_report_card_id,
        returned_report_card=candidate,
    )
    return baseline, candidate


def _require_requested_report_card_id(
    *,
    role: ReportCardComparisonQueryRole,
    requested_report_card_id: str,
    returned_report_card: ResearchReportCard,
) -> None:
    if returned_report_card.report_card_id != requested_report_card_id:
        raise ResearchReportCardComparisonQueryIntegrityError(
            f"{role} report-card ID mismatch: requested report_card_id "
            f"{requested_report_card_id}; returned report_card_id "
            f"{returned_report_card.report_card_id}"
        )


def _linked_review_states(
    *,
    report_card_id: str,
    repository: ResearchComparisonReadRepository,
) -> tuple[LinkedResearchNoteReviewState, ...]:
    note_ids = repository.get_research_note_ids_for_report_card(report_card_id)
    _validate_repository_note_id_order(note_ids=note_ids, report_card_id=report_card_id)
    return tuple(
        _project_review_state(
            note=_load_linked_note(repository=repository, note_id=note_id),
        )
        for note_id in note_ids
    )


def _validate_repository_note_id_order(
    *,
    note_ids: tuple[str, ...],
    report_card_id: str,
) -> None:
    for note_id in note_ids:
        if not isinstance(note_id, str) or not note_id.strip():
            raise ResearchReportCardComparisonQueryIntegrityError(
                f"linked note IDs must be nonempty strings for report_card_id "
                f"{report_card_id}"
            )
    if len(set(note_ids)) != len(note_ids):
        raise ResearchReportCardComparisonQueryIntegrityError(
            f"linked note IDs must be unique for report_card_id {report_card_id}"
        )
    if note_ids != tuple(sorted(note_ids)):
        raise ResearchReportCardComparisonQueryIntegrityError(
            f"linked note IDs must be ascending for report_card_id {report_card_id}"
        )


def _load_linked_note(
    *,
    repository: ResearchComparisonReadRepository,
    note_id: str,
) -> ResearchNote:
    note = repository.get_research_note(note_id)
    if note is None:
        raise ResearchReportCardComparisonQueryIntegrityError(
            f"linked research note does not exist: {note_id}"
        )
    if note.note_id != note_id:
        raise ResearchReportCardComparisonQueryIntegrityError(
            f"linked research note ID mismatch: requested note_id {note_id}; "
            f"returned note_id {note.note_id}"
        )
    return note


def _project_review_state(
    *,
    note: ResearchNote,
) -> LinkedResearchNoteReviewState:
    review = note.review
    return LinkedResearchNoteReviewState(
        note_id=note.note_id,
        note_type=note.note_type,
        note_status=note.status,
        title=note.title,
        updated_at=note.updated_at,
        evidence_strength=note.evidence_strength,
        research_decision_outcome=note.decision.outcome,
        review_status=review.review_status,
        reviewer_id=review.reviewer_id,
        review_role=review.review_role,
        reviewed_at=review.reviewed_at,
        review_decision=review.decision,
        approval_scope=review.approval_scope,
        approval_expires_at=review.approval_expires_at,
        linked_pr=review.linked_pr,
        review_notes_uri=review.review_notes_uri,
        risk_approval_required=review.risk_approval_required,
        parent_note_id=note.parent_note_id,
        supersedes_note_id=note.supersedes_note_id,
    )


__all__ = [
    "ReportCardComparisonQueryRole",
    "ResearchReportCardComparisonQueryError",
    "ResearchReportCardComparisonQueryIntegrityError",
    "ResearchReportCardComparisonQueryNotFoundError",
    "query_research_report_card_comparison",
]
