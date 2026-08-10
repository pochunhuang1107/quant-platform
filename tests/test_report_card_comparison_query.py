from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from research_sdk.contracts import (
    DecisionOutcome,
    EvidenceStrength,
    ResearchNote,
    ResearchNoteStatus,
    ResearchNoteType,
    ReviewRole,
    ReviewStatus,
)
from research_sdk.persistence import PersistenceCorruptionError, PersistenceErrorContext
from research_sdk.report_card_comparison import (
    REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION,
    ComparisonCompatibilityStatus,
    ComparisonDifference,
    ComparisonDifferenceCode,
    ReportCardCompatibilityAssessment,
    compare_research_report_cards,
)
from research_sdk.report_card_comparison.models import (
    COMPARISON_DIFFERENCE_FIELD_PATH_BY_CODE,
)
from research_sdk.report_card_comparison_query import (
    LinkedResearchNoteReviewState,
    ResearchReportCardComparisonQueryIntegrityError,
    ResearchReportCardComparisonQueryNotFoundError,
    ResearchReportCardComparisonQueryResult,
    query_research_report_card_comparison,
)
from research_sdk.report_card_identity import derive_research_report_card_id_from_fields
from test_deterministic_etf_report_card import mapped_records, report_card_from_records


def test_query_result_accepts_incompatible_without_comparison() -> None:
    result = ResearchReportCardComparisonQueryResult(
        baseline_report_card_id=_report_card_id("1"),
        candidate_report_card_id=_report_card_id("2"),
        compatibility=_incompatible_assessment(),
        comparison=None,
    )

    assert result.comparison is None


def test_query_result_rejects_incompatible_with_comparison(tmp_path: Path) -> None:
    comparison = _strict_comparison(tmp_path)

    with pytest.raises(ValidationError):
        ResearchReportCardComparisonQueryResult(
            baseline_report_card_id=comparison.baseline_report_card_id,
            candidate_report_card_id=comparison.candidate_report_card_id,
            compatibility=_incompatible_assessment(),
            comparison=comparison,
        )


@pytest.mark.parametrize(
    "compatibility",
    [
        lambda: ReportCardCompatibilityAssessment(
            compatibility_policy_version=(
                REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION
            ),
            status=ComparisonCompatibilityStatus.STRICT_COMPATIBLE,
        ),
        lambda: _context_assessment(),
    ],
)
def test_query_result_rejects_compatible_without_comparison(
    compatibility: object,
) -> None:
    with pytest.raises(ValidationError):
        ResearchReportCardComparisonQueryResult(
            baseline_report_card_id=_report_card_id("1"),
            candidate_report_card_id=_report_card_id("2"),
            compatibility=compatibility(),
            comparison=None,
        )


def test_query_result_rejects_comparison_baseline_id_mismatch(
    tmp_path: Path,
) -> None:
    comparison = _strict_comparison(tmp_path)

    with pytest.raises(ValidationError):
        ResearchReportCardComparisonQueryResult(
            baseline_report_card_id=_report_card_id("9"),
            candidate_report_card_id=comparison.candidate_report_card_id,
            compatibility=comparison.compatibility,
            comparison=comparison,
        )


def test_query_result_rejects_comparison_candidate_id_mismatch(
    tmp_path: Path,
) -> None:
    comparison = _strict_comparison(tmp_path)

    with pytest.raises(ValidationError):
        ResearchReportCardComparisonQueryResult(
            baseline_report_card_id=comparison.baseline_report_card_id,
            candidate_report_card_id=_report_card_id("9"),
            compatibility=comparison.compatibility,
            comparison=comparison,
        )


def test_query_result_rejects_comparison_compatibility_mismatch(
    tmp_path: Path,
) -> None:
    comparison = _strict_comparison(tmp_path)

    with pytest.raises(ValidationError):
        ResearchReportCardComparisonQueryResult(
            baseline_report_card_id=comparison.baseline_report_card_id,
            candidate_report_card_id=comparison.candidate_report_card_id,
            compatibility=_context_assessment(),
            comparison=comparison,
        )


@pytest.mark.parametrize(
    "field_name",
    ["baseline_review_states", "candidate_review_states"],
)
def test_query_result_rejects_duplicate_review_state_note_ids(
    tmp_path: Path,
    field_name: str,
) -> None:
    comparison = _strict_comparison(tmp_path)
    review_state = _review_state("note-a")

    with pytest.raises(ValidationError):
        ResearchReportCardComparisonQueryResult(
            baseline_report_card_id=comparison.baseline_report_card_id,
            candidate_report_card_id=comparison.candidate_report_card_id,
            compatibility=comparison.compatibility,
            comparison=comparison,
            **{field_name: (review_state, review_state)},
        )


@pytest.mark.parametrize(
    "field_name",
    ["baseline_review_states", "candidate_review_states"],
)
def test_query_result_rejects_nonascending_review_state_note_ids(
    tmp_path: Path,
    field_name: str,
) -> None:
    comparison = _strict_comparison(tmp_path)

    with pytest.raises(ValidationError):
        ResearchReportCardComparisonQueryResult(
            baseline_report_card_id=comparison.baseline_report_card_id,
            candidate_report_card_id=comparison.candidate_report_card_id,
            compatibility=comparison.compatibility,
            comparison=comparison,
            **{field_name: (_review_state("note-b"), _review_state("note-a"))},
        )


def test_linked_review_state_exposes_direct_facts_without_authority_fields() -> None:
    review_state = _review_state("note-a")
    dumped = review_state.model_dump(mode="json")

    assert dumped["risk_approval_required"] is True
    assert "authoritative" not in dumped
    assert "approved_interpretation" not in dumped
    assert "human_approved" not in dumped
    assert "valid_research_conclusion" not in dumped
    assert "current_note" not in dumped
    assert "preferred_note" not in dumped


def test_service_returns_strict_compatible_query_result(tmp_path: Path) -> None:
    report_card = report_card_from_records(mapped_records(tmp_path))
    repository = _FakeReadRepository(
        report_cards={report_card.report_card_id: report_card},
    )

    result = query_research_report_card_comparison(
        baseline_report_card_id=report_card.report_card_id,
        candidate_report_card_id=report_card.report_card_id,
        repository=repository,
    )

    assert (
        result.compatibility.status is ComparisonCompatibilityStatus.STRICT_COMPATIBLE
    )
    assert result.comparison is not None
    assert result.baseline_review_states == ()
    assert result.candidate_review_states == ()


def test_service_returns_context_compatible_query_result(tmp_path: Path) -> None:
    baseline = report_card_from_records(mapped_records(tmp_path))
    candidate = _with_recomputed_report_card_id(
        _with_lineage_update(baseline, parameter_hash=_hash("9"))
    )
    repository = _FakeReadRepository(
        report_cards={
            baseline.report_card_id: baseline,
            candidate.report_card_id: candidate,
        },
    )

    result = query_research_report_card_comparison(
        baseline_report_card_id=baseline.report_card_id,
        candidate_report_card_id=candidate.report_card_id,
        repository=repository,
    )

    assert result.compatibility.status is (
        ComparisonCompatibilityStatus.CONTEXT_COMPATIBLE
    )
    assert result.comparison is not None


def test_service_returns_incompatible_assessment_without_numeric_comparison(
    tmp_path: Path,
) -> None:
    baseline = report_card_from_records(mapped_records(tmp_path))
    candidate = _with_distinct_source_identity(
        _with_scope_update(baseline, frequency="weekly")
    )
    baseline_note = _note("note-baseline")
    candidate_note = _note("note-candidate")
    repository = _FakeReadRepository(
        report_cards={
            baseline.report_card_id: baseline,
            candidate.report_card_id: candidate,
        },
        notes={
            baseline_note.note_id: baseline_note,
            candidate_note.note_id: candidate_note,
        },
        links={
            baseline.report_card_id: (baseline_note.note_id,),
            candidate.report_card_id: (candidate_note.note_id,),
        },
    )

    result = query_research_report_card_comparison(
        baseline_report_card_id=baseline.report_card_id,
        candidate_report_card_id=candidate.report_card_id,
        repository=repository,
    )

    assert result.compatibility.status is ComparisonCompatibilityStatus.INCOMPATIBLE
    assert result.comparison is None
    assert [state.note_id for state in result.baseline_review_states] == [
        baseline_note.note_id
    ]
    assert [state.note_id for state in result.candidate_review_states] == [
        candidate_note.note_id
    ]


def test_service_same_card_deduplicates_card_and_note_reads(tmp_path: Path) -> None:
    report_card = report_card_from_records(mapped_records(tmp_path))
    note = _note("note-a")
    repository = _FakeReadRepository(
        report_cards={report_card.report_card_id: report_card},
        notes={note.note_id: note},
        links={report_card.report_card_id: (note.note_id,)},
    )

    result = query_research_report_card_comparison(
        baseline_report_card_id=report_card.report_card_id,
        candidate_report_card_id=report_card.report_card_id,
        repository=repository,
    )

    assert repository.report_card_reads == [report_card.report_card_id]
    assert repository.reverse_reads == [report_card.report_card_id]
    assert repository.note_reads == [note.note_id]
    assert result.baseline_review_states == result.candidate_review_states
    assert result.comparison is not None
    assert {
        metric.metric_name.value: metric.delta
        for metric in result.comparison.metric_comparisons
    } == {
        "total_return": "0.000000000000",
        "excess_return": "0.000000000000",
        "maximum_drawdown": "0.000000000000",
        "number_of_trades": 0,
    }


def test_service_raises_missing_baseline(tmp_path: Path) -> None:
    report_card = report_card_from_records(mapped_records(tmp_path))
    repository = _FakeReadRepository(report_cards={})

    with pytest.raises(ResearchReportCardComparisonQueryNotFoundError) as exc_info:
        query_research_report_card_comparison(
            baseline_report_card_id=report_card.report_card_id,
            candidate_report_card_id=report_card.report_card_id,
            repository=repository,
        )

    assert exc_info.value.role == "baseline"
    assert exc_info.value.report_card_id == report_card.report_card_id


def test_service_raises_missing_candidate(tmp_path: Path) -> None:
    baseline = report_card_from_records(mapped_records(tmp_path))
    candidate_id = _report_card_id("9")
    repository = _FakeReadRepository(report_cards={baseline.report_card_id: baseline})

    with pytest.raises(ResearchReportCardComparisonQueryNotFoundError) as exc_info:
        query_research_report_card_comparison(
            baseline_report_card_id=baseline.report_card_id,
            candidate_report_card_id=candidate_id,
            repository=repository,
        )

    assert exc_info.value.role == "candidate"
    assert exc_info.value.report_card_id == candidate_id


def test_service_rejects_baseline_report_card_id_mismatch(tmp_path: Path) -> None:
    requested = report_card_from_records(mapped_records(tmp_path))
    returned = _with_recomputed_report_card_id(
        _with_lineage_update(requested, parameter_hash=_hash("8"))
    )
    repository = _FakeReadRepository(
        report_cards={requested.report_card_id: returned},
    )

    with pytest.raises(ResearchReportCardComparisonQueryIntegrityError) as exc_info:
        query_research_report_card_comparison(
            baseline_report_card_id=requested.report_card_id,
            candidate_report_card_id=requested.report_card_id,
            repository=repository,
        )

    message = str(exc_info.value)
    assert "baseline" in message
    assert requested.report_card_id in message
    assert returned.report_card_id in message
    assert repository.report_card_reads == [requested.report_card_id]
    assert repository.reverse_reads == []


def test_service_rejects_candidate_report_card_id_mismatch(tmp_path: Path) -> None:
    baseline = report_card_from_records(mapped_records(tmp_path))
    requested_candidate = _with_recomputed_report_card_id(
        _with_lineage_update(baseline, parameter_hash=_hash("7"))
    )
    returned_candidate = _with_recomputed_report_card_id(
        _with_lineage_update(baseline, parameter_hash=_hash("8"))
    )
    repository = _FakeReadRepository(
        report_cards={
            baseline.report_card_id: baseline,
            requested_candidate.report_card_id: returned_candidate,
        },
    )

    with pytest.raises(ResearchReportCardComparisonQueryIntegrityError) as exc_info:
        query_research_report_card_comparison(
            baseline_report_card_id=baseline.report_card_id,
            candidate_report_card_id=requested_candidate.report_card_id,
            repository=repository,
        )

    message = str(exc_info.value)
    assert "candidate" in message
    assert requested_candidate.report_card_id in message
    assert returned_candidate.report_card_id in message
    assert repository.report_card_reads == [
        baseline.report_card_id,
        requested_candidate.report_card_id,
    ]
    assert repository.reverse_reads == []


def test_service_rejects_same_card_report_card_id_mismatch(tmp_path: Path) -> None:
    requested = report_card_from_records(mapped_records(tmp_path))
    returned = _with_recomputed_report_card_id(
        _with_lineage_update(requested, parameter_hash=_hash("8"))
    )
    repository = _FakeReadRepository(
        report_cards={requested.report_card_id: returned},
    )

    with pytest.raises(ResearchReportCardComparisonQueryIntegrityError):
        query_research_report_card_comparison(
            baseline_report_card_id=requested.report_card_id,
            candidate_report_card_id=requested.report_card_id,
            repository=repository,
        )

    assert repository.report_card_reads == [requested.report_card_id]
    assert repository.reverse_reads == []


def test_service_projects_zero_notes_both_sides(tmp_path: Path) -> None:
    baseline = report_card_from_records(mapped_records(tmp_path))
    candidate = _with_recomputed_report_card_id(
        _with_lineage_update(baseline, parameter_hash=_hash("8"))
    )
    repository = _FakeReadRepository(
        report_cards={
            baseline.report_card_id: baseline,
            candidate.report_card_id: candidate,
        },
    )

    result = query_research_report_card_comparison(
        baseline_report_card_id=baseline.report_card_id,
        candidate_report_card_id=candidate.report_card_id,
        repository=repository,
    )

    assert result.baseline_review_states == ()
    assert result.candidate_review_states == ()


def test_service_projects_notes_on_baseline_only(tmp_path: Path) -> None:
    baseline, candidate = _compatible_pair(tmp_path)
    note = _note("note-baseline")
    result = _query_pair_with_notes(
        baseline=baseline,
        candidate=candidate,
        notes={note.note_id: note},
        links={baseline.report_card_id: (note.note_id,)},
    )

    assert [state.note_id for state in result.baseline_review_states] == [note.note_id]
    assert result.candidate_review_states == ()


def test_service_projects_notes_on_candidate_only(tmp_path: Path) -> None:
    baseline, candidate = _compatible_pair(tmp_path)
    note = _note("note-candidate")
    result = _query_pair_with_notes(
        baseline=baseline,
        candidate=candidate,
        notes={note.note_id: note},
        links={candidate.report_card_id: (note.note_id,)},
    )

    assert result.baseline_review_states == ()
    assert [state.note_id for state in result.candidate_review_states] == [note.note_id]


def test_service_projects_note_linked_to_both_cards(tmp_path: Path) -> None:
    baseline, candidate = _compatible_pair(tmp_path)
    note = _note("note-shared")
    result = _query_pair_with_notes(
        baseline=baseline,
        candidate=candidate,
        notes={note.note_id: note},
        links={
            baseline.report_card_id: (note.note_id,),
            candidate.report_card_id: (note.note_id,),
        },
    )

    assert [state.note_id for state in result.baseline_review_states] == [note.note_id]
    assert [state.note_id for state in result.candidate_review_states] == [note.note_id]


def test_service_projects_multiple_notes_in_note_id_order(tmp_path: Path) -> None:
    baseline, candidate = _compatible_pair(tmp_path)
    notes = {
        "note-a": _note("note-a"),
        "note-b": _note("note-b"),
        "note-c": _note("note-c"),
    }
    result = _query_pair_with_notes(
        baseline=baseline,
        candidate=candidate,
        notes=notes,
        links={
            baseline.report_card_id: ("note-a", "note-c"),
            candidate.report_card_id: ("note-b",),
        },
    )

    assert [state.note_id for state in result.baseline_review_states] == [
        "note-a",
        "note-c",
    ]
    assert [state.note_id for state in result.candidate_review_states] == ["note-b"]


@pytest.mark.parametrize(
    "note_status",
    [
        ResearchNoteStatus.DRAFT,
        ResearchNoteStatus.READY_FOR_REVIEW,
        ResearchNoteStatus.UNDER_REVIEW,
        ResearchNoteStatus.FINALIZED,
    ],
)
def test_service_shows_generic_note_status_visibility(
    tmp_path: Path,
    note_status: ResearchNoteStatus,
) -> None:
    baseline, candidate = _compatible_pair(tmp_path)
    note = _note("note-status", status=note_status)
    result = _query_pair_with_notes(
        baseline=baseline,
        candidate=candidate,
        notes={note.note_id: note},
        links={baseline.report_card_id: (note.note_id,)},
    )

    assert result.baseline_review_states[0].note_status is note_status


@pytest.mark.parametrize(
    "review_status",
    [
        ReviewStatus.PENDING,
        ReviewStatus.APPROVED,
        ReviewStatus.CHANGES_REQUESTED,
        ReviewStatus.REJECTED,
    ],
)
def test_service_shows_generic_review_status_visibility(
    tmp_path: Path,
    review_status: ReviewStatus,
) -> None:
    baseline, candidate = _compatible_pair(tmp_path)
    note = _note("note-review-status", review_status=review_status)
    result = _query_pair_with_notes(
        baseline=baseline,
        candidate=candidate,
        notes={note.note_id: note},
        links={baseline.report_card_id: (note.note_id,)},
    )

    assert result.baseline_review_states[0].review_status is review_status


def test_service_projects_review_state_fields_exactly(tmp_path: Path) -> None:
    baseline, candidate = _compatible_pair(tmp_path)
    note = _note(
        "note-a",
        evidence_strength=EvidenceStrength.STRONG,
        decision_outcome=DecisionOutcome.ACCEPT_RESULT,
        review_status=ReviewStatus.CHANGES_REQUESTED,
        review_decision="needs a narrower limitation note",
        parent_note_id="note-parent",
        supersedes_note_id="note-prior",
        risk_approval_required=False,
    )
    result = _query_pair_with_notes(
        baseline=baseline,
        candidate=candidate,
        notes={note.note_id: note},
        links={baseline.report_card_id: (note.note_id,)},
    )

    state = result.baseline_review_states[0]
    assert state.note_id == note.note_id
    assert state.note_type is note.note_type
    assert state.note_status is note.status
    assert state.title == note.title
    assert state.updated_at == note.updated_at
    assert state.evidence_strength is EvidenceStrength.STRONG
    assert state.research_decision_outcome is DecisionOutcome.ACCEPT_RESULT
    assert state.review_status is ReviewStatus.CHANGES_REQUESTED
    assert state.reviewer_id == note.review.reviewer_id
    assert state.review_role is ReviewRole.AGENT_REVIEWER
    assert state.reviewed_at == note.review.reviewed_at
    assert state.review_decision == "needs a narrower limitation note"
    assert state.approval_scope == note.review.approval_scope
    assert state.approval_expires_at == note.review.approval_expires_at
    assert state.linked_pr == note.review.linked_pr
    assert state.review_notes_uri == note.review.review_notes_uri
    assert state.risk_approval_required is False
    assert state.parent_note_id == "note-parent"
    assert state.supersedes_note_id == "note-prior"


def test_service_keeps_research_decision_and_review_decision_distinct(
    tmp_path: Path,
) -> None:
    baseline, candidate = _compatible_pair(tmp_path)
    note = _note(
        "note-a",
        decision_outcome=DecisionOutcome.CONTINUE_RESEARCH,
        review_decision="review metadata decision text",
    )
    result = _query_pair_with_notes(
        baseline=baseline,
        candidate=candidate,
        notes={note.note_id: note},
        links={baseline.report_card_id: (note.note_id,)},
    )
    state = result.baseline_review_states[0]

    assert state.research_decision_outcome is DecisionOutcome.CONTINUE_RESEARCH
    assert state.review_decision == "review metadata decision text"


def test_service_raises_for_missing_linked_note(tmp_path: Path) -> None:
    baseline, candidate = _compatible_pair(tmp_path)
    repository = _FakeReadRepository(
        report_cards={
            baseline.report_card_id: baseline,
            candidate.report_card_id: candidate,
        },
        links={baseline.report_card_id: ("missing-note",)},
    )

    with pytest.raises(ResearchReportCardComparisonQueryIntegrityError):
        query_research_report_card_comparison(
            baseline_report_card_id=baseline.report_card_id,
            candidate_report_card_id=candidate.report_card_id,
            repository=repository,
        )


def test_service_rejects_linked_note_id_mismatch(tmp_path: Path) -> None:
    baseline, candidate = _compatible_pair(tmp_path)
    requested_note_id = "note-a"
    returned_note = _note("note-b")
    repository = _FakeReadRepository(
        report_cards={
            baseline.report_card_id: baseline,
            candidate.report_card_id: candidate,
        },
        notes={requested_note_id: returned_note},
        links={baseline.report_card_id: (requested_note_id,)},
    )

    with pytest.raises(ResearchReportCardComparisonQueryIntegrityError) as exc_info:
        query_research_report_card_comparison(
            baseline_report_card_id=baseline.report_card_id,
            candidate_report_card_id=candidate.report_card_id,
            repository=repository,
        )

    message = str(exc_info.value)
    assert requested_note_id in message
    assert returned_note.note_id in message


@pytest.mark.parametrize(
    "note_ids",
    [
        ("",),
        ("   ",),
        (object(),),
    ],
)
def test_service_rejects_malformed_reverse_note_ids(
    tmp_path: Path,
    note_ids: tuple[object, ...],
) -> None:
    baseline, candidate = _compatible_pair(tmp_path)
    repository = _FakeReadRepository(
        report_cards={
            baseline.report_card_id: baseline,
            candidate.report_card_id: candidate,
        },
        links={baseline.report_card_id: note_ids},
    )

    with pytest.raises(ResearchReportCardComparisonQueryIntegrityError):
        query_research_report_card_comparison(
            baseline_report_card_id=baseline.report_card_id,
            candidate_report_card_id=candidate.report_card_id,
            repository=repository,
        )

    assert repository.note_reads == []


@pytest.mark.parametrize(
    "note_ids",
    [
        ("note-a", "note-a"),
        ("note-b", "note-a"),
    ],
)
def test_service_rejects_duplicate_or_noncanonical_reverse_note_ids(
    tmp_path: Path,
    note_ids: tuple[str, ...],
) -> None:
    baseline, candidate = _compatible_pair(tmp_path)
    repository = _FakeReadRepository(
        report_cards={
            baseline.report_card_id: baseline,
            candidate.report_card_id: candidate,
        },
        notes={"note-a": _note("note-a"), "note-b": _note("note-b")},
        links={baseline.report_card_id: note_ids},
    )

    with pytest.raises(ResearchReportCardComparisonQueryIntegrityError):
        query_research_report_card_comparison(
            baseline_report_card_id=baseline.report_card_id,
            candidate_report_card_id=candidate.report_card_id,
            repository=repository,
        )


def test_service_propagates_report_card_corruption(tmp_path: Path) -> None:
    report_card = report_card_from_records(mapped_records(tmp_path))
    corruption = _corruption("research_report_cards", "get_research_report_card")
    repository = _FakeReadRepository(report_card_error=corruption)

    with pytest.raises(PersistenceCorruptionError) as exc_info:
        query_research_report_card_comparison(
            baseline_report_card_id=report_card.report_card_id,
            candidate_report_card_id=report_card.report_card_id,
            repository=repository,
        )

    assert exc_info.value is corruption


def test_service_propagates_note_corruption(tmp_path: Path) -> None:
    baseline, candidate = _compatible_pair(tmp_path)
    corruption = _corruption("research_notes", "get_research_note")
    repository = _FakeReadRepository(
        report_cards={
            baseline.report_card_id: baseline,
            candidate.report_card_id: candidate,
        },
        links={baseline.report_card_id: ("note-a",)},
        note_error=corruption,
    )

    with pytest.raises(PersistenceCorruptionError) as exc_info:
        query_research_report_card_comparison(
            baseline_report_card_id=baseline.report_card_id,
            candidate_report_card_id=candidate.report_card_id,
            repository=repository,
        )

    assert exc_info.value is corruption


class _FakeReadRepository:
    def __init__(
        self,
        *,
        report_cards=None,
        notes=None,
        links=None,
        report_card_error: Exception | None = None,
        note_error: Exception | None = None,
    ) -> None:
        self.report_cards = dict(report_cards or {})
        self.notes = dict(notes or {})
        self.links = dict(links or {})
        self.report_card_error = report_card_error
        self.note_error = note_error
        self.report_card_reads: list[str] = []
        self.note_reads: list[str] = []
        self.reverse_reads: list[str] = []

    def get_research_report_card(self, report_card_id: str):
        self.report_card_reads.append(report_card_id)
        if self.report_card_error is not None:
            raise self.report_card_error
        return self.report_cards.get(report_card_id)

    def get_research_note(self, note_id: str):
        self.note_reads.append(note_id)
        if self.note_error is not None:
            raise self.note_error
        return self.notes.get(note_id)

    def get_research_note_ids_for_report_card(self, report_card_id: str):
        self.reverse_reads.append(report_card_id)
        return self.links.get(report_card_id, ())


def _query_pair_with_notes(
    *,
    baseline,
    candidate,
    notes,
    links,
) -> ResearchReportCardComparisonQueryResult:
    repository = _FakeReadRepository(
        report_cards={
            baseline.report_card_id: baseline,
            candidate.report_card_id: candidate,
        },
        notes=notes,
        links=links,
    )
    return query_research_report_card_comparison(
        baseline_report_card_id=baseline.report_card_id,
        candidate_report_card_id=candidate.report_card_id,
        repository=repository,
    )


def _compatible_pair(tmp_path: Path):
    baseline = report_card_from_records(mapped_records(tmp_path))
    candidate = _with_recomputed_report_card_id(
        _with_lineage_update(baseline, parameter_hash=_hash("7"))
    )
    return baseline, candidate


def _strict_comparison(tmp_path: Path):
    report_card = report_card_from_records(mapped_records(tmp_path))
    return compare_research_report_cards(baseline=report_card, candidate=report_card)


def _review_state(note_id: str) -> LinkedResearchNoteReviewState:
    return LinkedResearchNoteReviewState(
        note_id=note_id,
        note_type=ResearchNoteType.REVIEW_NOTE,
        note_status=ResearchNoteStatus.UNDER_REVIEW,
        title="Review visibility",
        updated_at=datetime(2026, 7, 9, 10, 0, tzinfo=UTC),
        evidence_strength=EvidenceStrength.MODERATE,
        research_decision_outcome=DecisionOutcome.CONTINUE_RESEARCH,
        review_status=ReviewStatus.APPROVED,
        reviewer_id="reviewer-a",
        review_role=ReviewRole.AGENT_REVIEWER,
        reviewed_at=datetime(2026, 7, 9, 11, 0, tzinfo=UTC),
        review_decision="visible persisted review metadata",
        approval_scope="metadata visibility only",
        approval_expires_at=datetime(2026, 8, 9, 11, 0, tzinfo=UTC),
        linked_pr="PR-1",
        review_notes_uri="notes://review-a",
        risk_approval_required=True,
        parent_note_id=None,
        supersedes_note_id=None,
    )


def _note(
    note_id: str,
    *,
    status: ResearchNoteStatus = ResearchNoteStatus.UNDER_REVIEW,
    evidence_strength: EvidenceStrength = EvidenceStrength.MODERATE,
    decision_outcome: DecisionOutcome = DecisionOutcome.CONTINUE_RESEARCH,
    review_status: ReviewStatus = ReviewStatus.APPROVED,
    review_decision: str | None = "persisted review decision",
    parent_note_id: str | None = None,
    supersedes_note_id: str | None = None,
    risk_approval_required: bool = True,
) -> ResearchNote:
    return ResearchNote.model_validate(
        {
            "note_id": note_id,
            "schema_version": "1.0.0",
            "note_type": "review_note",
            "status": status.value,
            "created_at": "2026-07-09T10:00:00Z",
            "created_by": "agent-a",
            "updated_at": "2026-07-09T11:00:00Z",
            "updated_by": "agent-a",
            "title": f"Review state {note_id}",
            "hypothesis": {
                "statement": "Review visibility should be factual.",
                "status": "inconclusive",
            },
            "motivation": "Exercise persisted review-state visibility.",
            "methodology": "Project direct note and review metadata.",
            "benchmark_summary": "Benchmark facts remain in report cards.",
            "cost_assumptions": "Costs remain in report cards.",
            "slippage_assumptions": "Slippage remains in report cards.",
            "lookback": "Lookback remains in report cards.",
            "lag_assumptions": "Lag assumptions remain in report cards.",
            "leakage_review": "Leakage review remains in report cards.",
            "results_summary": "Do not project free-form results text in C2b.",
            "interpretation": "Do not project interpretation prose in C2b.",
            "risks": ["Misreading metadata as authority."],
            "failure_modes": ["Linked note corruption."],
            "validation_plan": "Use durable readback before projection.",
            "limitations": ["Factual visibility only."],
            "next_steps": ["Human review decides interpretation authority."],
            "evidence_strength": evidence_strength.value,
            "decision": {
                "outcome": decision_outcome.value,
                "rationale": "Research decision is distinct from review metadata.",
            },
            "review": {
                "review_status": review_status.value,
                "reviewer_id": "reviewer-a",
                "review_role": "agent_reviewer",
                "reviewed_at": "2026-07-09T11:30:00Z",
                "decision": review_decision,
                "approval_scope": "metadata visibility only",
                "approval_expires_at": "2026-08-09T11:30:00Z",
                "linked_pr": "PR-visibility",
                "review_notes_uri": "notes://visibility",
                "risk_approval_required": risk_approval_required,
            },
            "references": {},
            "tags": ["visibility"],
            "body_markdown": "# Not projected\n",
            "parent_note_id": parent_note_id,
            "supersedes_note_id": supersedes_note_id,
        }
    )


def _difference(code: ComparisonDifferenceCode) -> ComparisonDifference:
    return ComparisonDifference(
        code=code,
        field_path=COMPARISON_DIFFERENCE_FIELD_PATH_BY_CODE[code],
        baseline_value="baseline",
        candidate_value="candidate",
    )


def _incompatible_assessment() -> ReportCardCompatibilityAssessment:
    return ReportCardCompatibilityAssessment(
        compatibility_policy_version=REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION,
        status=ComparisonCompatibilityStatus.INCOMPATIBLE,
        required_context_differences=(
            _difference(ComparisonDifferenceCode.FREQUENCY_MISMATCH),
        ),
    )


def _context_assessment() -> ReportCardCompatibilityAssessment:
    return ReportCardCompatibilityAssessment(
        compatibility_policy_version=REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION,
        status=ComparisonCompatibilityStatus.CONTEXT_COMPATIBLE,
        observed_lineage_differences=(
            _difference(ComparisonDifferenceCode.PARAMETER_HASH_DIFFERENCE),
        ),
    )


def _with_lineage_update(card, **updates):
    return card.model_copy(update={"lineage": card.lineage.model_copy(update=updates)})


def _with_scope_update(card, **updates):
    return card.model_copy(
        update={"research_scope": card.research_scope.model_copy(update=updates)}
    )


def _with_recomputed_report_card_id(card):
    return card.model_copy(
        update={
            "report_card_id": derive_research_report_card_id_from_fields(
                source_run_id=card.source_run_id,
                schema_version=card.schema_version,
                derivation_policy_version=card.derivation_policy_version,
                data_snapshot_content_hash=card.lineage.data_snapshot_content_hash,
                benchmark_snapshot_content_hash=(
                    card.lineage.benchmark_snapshot_content_hash
                ),
                config_hash=card.lineage.config_hash,
                parameter_hash=card.lineage.parameter_hash,
                artifact_manifest_hash=card.lineage.artifact_manifest_hash,
            )
        }
    )


def _with_distinct_source_identity(card):
    distinct_source = card.model_copy(
        update={
            "source_run_id": "run-" + ("5" * 64),
            "experiment_id": "exp-distinct-c2b-source",
            "lineage": card.lineage.model_copy(
                update={
                    "artifact_manifest_id": "manifest-" + ("5" * 64),
                    "artifact_manifest_hash": _hash("5"),
                }
            ),
        }
    )
    return _with_recomputed_report_card_id(distinct_source)


def _hash(digit: str) -> str:
    return f"sha256:{digit * 64}"


def _report_card_id(digit: str) -> str:
    return f"report-card-{digit * 64}"


def _corruption(table_name: str, operation: str) -> PersistenceCorruptionError:
    return PersistenceCorruptionError(
        PersistenceErrorContext(
            table_name=table_name,
            operation=operation,
            logical_identity={"id": "corrupt"},
        )
    )
