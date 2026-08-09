"""Atomic service boundary for finalized research interpretation recording."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager

from sqlalchemy.engine import Connection

from research_sdk.contracts import (
    ResearchNote,
    ResearchNoteStatus,
    ResearchNoteType,
    ResearchReportCard,
    ReviewRole,
    ReviewStatus,
)
from research_sdk.persistence import (
    ExperimentLedgerRepository,
    PersistenceDisposition,
    SqlAlchemyExperimentLedgerRepository,
)
from research_sdk.research_interpretation.models import (
    FinalizedResearchInterpretationBundle,
    FinalizedResearchInterpretationRecordingResult,
)
from research_sdk.research_note_identity import verify_finalized_research_note_identity

type TransactionFactory = Callable[[], AbstractContextManager[Connection]]
type RepositoryFactory = Callable[[Connection], ExperimentLedgerRepository]

_SUPPORTED_DISPOSITION_COMBINATIONS = frozenset(
    {
        (PersistenceDisposition.CREATED, PersistenceDisposition.CREATED),
        (PersistenceDisposition.REPLAYED, PersistenceDisposition.CREATED),
        (PersistenceDisposition.REPLAYED, PersistenceDisposition.REPLAYED),
    }
)


class FinalizedResearchInterpretationValidationError(ValueError):
    """Raised when a note cannot become an authoritative interpretation."""


class FinalizedResearchInterpretationDispositionCoherenceError(ValueError):
    """Raised when component write outcomes imply incoherent partial state."""


def record_finalized_research_interpretation(
    *,
    bundle: FinalizedResearchInterpretationBundle,
    transaction_factory: TransactionFactory,
    repository_factory: RepositoryFactory = SqlAlchemyExperimentLedgerRepository,
) -> FinalizedResearchInterpretationRecordingResult:
    """Record one finalized human-owner interpretation and durable card link."""

    _validate_identity(bundle=bundle)

    recording_result: FinalizedResearchInterpretationRecordingResult | None = None
    with transaction_factory() as connection:
        repository = repository_factory(connection)
        report_card = repository.get_research_report_card(bundle.report_card_id)
        if report_card is None:
            raise FinalizedResearchInterpretationValidationError(
                "linked report_card_id must already be persisted"
            )

        _validate_human_owner_finalization(bundle.note)
        _validate_structured_references(note=bundle.note, report_card=report_card)
        _validate_parent_and_supersession(
            repository=repository,
            note=bundle.note,
            report_card=report_card,
        )
        _validate_existing_links(
            repository=repository,
            note_id=bundle.note.note_id,
            report_card_id=bundle.report_card_id,
        )

        research_note_result = repository.record_research_note(bundle.note)
        report_card_link_result = repository.record_research_note_report_card_link(
            note_id=bundle.note.note_id,
            report_card_id=bundle.report_card_id,
        )
        recording_result = FinalizedResearchInterpretationRecordingResult(
            research_note_result=research_note_result,
            report_card_link_result=report_card_link_result,
            report_card_id=bundle.report_card_id,
        )
        _validate_disposition_coherence(recording_result)

    if recording_result is None:
        raise RuntimeError("finalized interpretation recording produced no result")
    return recording_result


def _validate_identity(*, bundle: FinalizedResearchInterpretationBundle) -> None:
    try:
        verify_finalized_research_note_identity(
            note=bundle.note,
            report_card_ids=(bundle.report_card_id,),
        )
    except ValueError as exc:
        raise FinalizedResearchInterpretationValidationError(
            "finalized note_id must match finalized-v1 natural identity"
        ) from exc


def _validate_human_owner_finalization(note: ResearchNote) -> None:
    _require(
        note.note_type is ResearchNoteType.EXPERIMENT_RESULT,
        "finalized interpretation note_type must be experiment_result",
    )
    _require(
        note.status is ResearchNoteStatus.FINALIZED,
        "finalized interpretation note status must be finalized",
    )
    _require(
        note.review.review_status is ReviewStatus.APPROVED,
        "finalized interpretation review_status must be approved",
    )
    _require(
        note.review.reviewer_id is not None and bool(note.review.reviewer_id.strip()),
        "finalized interpretation requires reviewer_id",
    )
    _require(
        note.review.review_role is ReviewRole.HUMAN_OWNER,
        "finalized interpretation requires HUMAN_OWNER review role",
    )
    reviewed_at = note.review.reviewed_at
    _require(reviewed_at is not None, "finalized interpretation requires reviewed_at")
    if reviewed_at is None:
        raise FinalizedResearchInterpretationValidationError(
            "finalized interpretation requires reviewed_at"
        )
    _require(
        reviewed_at >= note.updated_at,
        "finalized interpretation reviewed_at must be greater than or equal to "
        "updated_at",
    )


def _validate_structured_references(
    *,
    note: ResearchNote,
    report_card: ResearchReportCard,
) -> None:
    references = note.references
    _require_unique("references.run_ids", references.run_ids)
    _require(
        references.run_ids == (report_card.source_run_id,),
        "note run_ids must exactly match report-card source_run_id",
    )
    _require_optional_exact(
        field_name="references.experiment_ids",
        values=references.experiment_ids,
        expected=report_card.experiment_id,
    )
    _require_optional_exact(
        field_name="references.data_snapshot_ids",
        values=references.data_snapshot_ids,
        expected=report_card.lineage.data_snapshot_id,
    )
    _require_optional_exact(
        field_name="references.benchmark_snapshot_ids",
        values=references.benchmark_snapshot_ids,
        expected=report_card.lineage.benchmark_snapshot_id,
    )
    _require_optional_exact(
        field_name="references.strategy_ids",
        values=references.strategy_ids,
        expected=report_card.lineage.strategy_id,
    )
    _require_optional_exact(
        field_name="references.artifact_manifest_uris",
        values=references.artifact_manifest_uris,
        expected=report_card.evidence.artifact_manifest_uri,
    )
    _require_unique("references.artifact_uris", references.artifact_uris)
    artifact_uris = {artifact.uri for artifact in report_card.evidence.artifacts}
    for artifact_uri in references.artifact_uris:
        _require(
            artifact_uri in artifact_uris,
            "note artifact_uris must be drawn from report-card evidence",
        )
    _require(
        references.feature_snapshot_ids == (),
        "feature_snapshot_ids are not supported by the B1b2 finalized workflow",
    )


def _validate_parent_and_supersession(
    *,
    repository: ExperimentLedgerRepository,
    note: ResearchNote,
    report_card: ResearchReportCard,
) -> None:
    report_card_id = report_card.report_card_id
    if note.parent_note_id is not None:
        parent_note = repository.get_research_note(note.parent_note_id)
        if parent_note is None:
            raise FinalizedResearchInterpretationValidationError(
                "parent_note_id must reference an existing research note"
            )

    if note.supersedes_note_id is not None:
        superseded_note = repository.get_research_note(note.supersedes_note_id)
        if superseded_note is None:
            raise FinalizedResearchInterpretationValidationError(
                "supersedes_note_id must reference an existing research note"
            )
        _validate_human_owner_finalization(superseded_note)
        superseded_links = repository.get_report_card_ids_for_note(
            superseded_note.note_id
        )
        _require(
            superseded_links == (report_card_id,),
            "superseded note must link to the same report card",
        )
        try:
            verify_finalized_research_note_identity(
                note=superseded_note,
                report_card_ids=(report_card_id,),
            )
        except ValueError as exc:
            raise FinalizedResearchInterpretationValidationError(
                "superseded note must be an authoritative finalized-v1 interpretation"
            ) from exc
        _validate_structured_references(
            note=superseded_note,
            report_card=report_card,
        )


def _validate_existing_links(
    *,
    repository: ExperimentLedgerRepository,
    note_id: str,
    report_card_id: str,
) -> None:
    existing_report_card_ids = repository.get_report_card_ids_for_note(note_id)
    if existing_report_card_ids not in ((), (report_card_id,)):
        raise FinalizedResearchInterpretationValidationError(
            "existing note links are incompatible with the single-card workflow"
        )


def _validate_disposition_coherence(
    result: FinalizedResearchInterpretationRecordingResult,
) -> None:
    dispositions = (
        result.research_note_result.disposition,
        result.report_card_link_result.disposition,
    )
    if dispositions not in _SUPPORTED_DISPOSITION_COMBINATIONS:
        joined = ", ".join(disposition.value for disposition in dispositions)
        raise FinalizedResearchInterpretationDispositionCoherenceError(
            "finalized interpretation write disposition combination is not "
            f"supported: {joined}"
        )


def _require_optional_exact(
    *,
    field_name: str,
    values: tuple[str, ...],
    expected: str,
) -> None:
    _require_unique(field_name, values)
    if values:
        _require(values == (expected,), f"{field_name} must exactly match {expected}")


def _require_unique(field_name: str, values: Iterable[str]) -> None:
    values_tuple = tuple(values)
    _require(len(set(values_tuple)) == len(values_tuple), f"{field_name} is duplicated")


def _require(condition: object, message: str) -> None:
    if not condition:
        raise FinalizedResearchInterpretationValidationError(message)


__all__ = [
    "FinalizedResearchInterpretationDispositionCoherenceError",
    "FinalizedResearchInterpretationRecordingResult",
    "FinalizedResearchInterpretationValidationError",
    "RepositoryFactory",
    "TransactionFactory",
    "record_finalized_research_interpretation",
]
