from __future__ import annotations

import json
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

import pytest

from research_sdk.contracts import ResearchNote, ResearchReportCard
from research_sdk.persistence import (
    PersistenceCorruptionError,
    PersistenceDisposition,
    PersistenceErrorContext,
)
from research_sdk.persistence.results import (
    PersistedRecordMetadata,
    PersistenceWriteResult,
)
from research_sdk.report_card_identity import derive_research_report_card_id_from_fields
from research_sdk.research_interpretation import (
    FinalizedResearchInterpretationBundle,
    FinalizedResearchInterpretationDispositionCoherenceError,
    FinalizedResearchInterpretationValidationError,
    record_finalized_research_interpretation,
)
from research_sdk.research_note_identity import derive_finalized_research_note_id

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "contracts"


@pytest.fixture
def report_card() -> ResearchReportCard:
    payload = _load_fixture("research_report_card.json")
    lineage = payload["lineage"]
    payload["report_card_id"] = derive_research_report_card_id_from_fields(
        source_run_id=payload["source_run_id"],
        schema_version=payload["schema_version"],
        derivation_policy_version=payload["derivation_policy_version"],
        data_snapshot_content_hash=lineage["data_snapshot_content_hash"],
        benchmark_snapshot_content_hash=lineage["benchmark_snapshot_content_hash"],
        config_hash=lineage["config_hash"],
        parameter_hash=lineage["parameter_hash"],
        artifact_manifest_hash=lineage["artifact_manifest_hash"],
    )
    return ResearchReportCard.model_validate(payload)


@pytest.fixture
def finalized_note(report_card: ResearchReportCard) -> ResearchNote:
    return _finalized_note_for_report_card(report_card)


def test_valid_finalized_human_owner_interpretation_is_recorded(
    report_card: ResearchReportCard,
    finalized_note: ResearchNote,
) -> None:
    repository = _FakeRepository(report_card=report_card)

    result = record_finalized_research_interpretation(
        bundle=FinalizedResearchInterpretationBundle(
            note=finalized_note,
            report_card_id=report_card.report_card_id,
        ),
        transaction_factory=_transaction_factory(),
        repository_factory=lambda _connection: repository,
    )

    assert result.research_note_result.disposition is PersistenceDisposition.CREATED
    assert result.report_card_link_result.disposition is PersistenceDisposition.CREATED
    assert result.report_card_id == report_card.report_card_id
    assert repository.notes[finalized_note.note_id] == finalized_note
    assert repository.links[finalized_note.note_id] == (report_card.report_card_id,)


@pytest.mark.parametrize(
    "status",
    ["draft", "ready_for_review", "under_review"],
)
def test_non_finalized_note_status_is_rejected(
    report_card: ResearchReportCard,
    finalized_note: ResearchNote,
    status: str,
) -> None:
    note = _with_payload_updates_without_identity(finalized_note, {"status": status})

    with pytest.raises(FinalizedResearchInterpretationValidationError):
        _record(note=note, report_card=report_card)


@pytest.mark.parametrize("review_status", ["pending", "rejected", "changes_requested"])
def test_non_approved_review_status_is_rejected(
    report_card: ResearchReportCard,
    finalized_note: ResearchNote,
    review_status: str,
) -> None:
    note = _with_payload_updates(
        finalized_note,
        report_card.report_card_id,
        {"review": {"review_status": review_status}},
    )

    with pytest.raises(FinalizedResearchInterpretationValidationError):
        _record(note=note, report_card=report_card)


@pytest.mark.parametrize("review_role", ["agent_reviewer", "risk_reviewer"])
def test_only_human_owner_review_role_authorizes_finalization(
    report_card: ResearchReportCard,
    finalized_note: ResearchNote,
    review_role: str,
) -> None:
    note = _with_payload_updates(
        finalized_note,
        report_card.report_card_id,
        {"review": {"review_role": review_role}},
    )

    with pytest.raises(FinalizedResearchInterpretationValidationError):
        _record(note=note, report_card=report_card)


@pytest.mark.parametrize(
    "review_update",
    [
        {"reviewer_id": None},
        {"reviewed_at": None},
    ],
)
def test_human_review_attribution_fields_are_required(
    report_card: ResearchReportCard,
    finalized_note: ResearchNote,
    review_update: dict[str, Any],
) -> None:
    note = _with_payload_updates(
        finalized_note,
        report_card.report_card_id,
        {"review": review_update},
    )

    with pytest.raises(FinalizedResearchInterpretationValidationError):
        _record(note=note, report_card=report_card)


@pytest.mark.parametrize(
    ("updated_at", "reviewed_at"),
    [
        ("2026-07-09T10:00:00Z", "2026-07-09T10:00:00Z"),
        ("2026-07-09T10:00:00Z", "2026-07-09T10:05:00Z"),
    ],
)
def test_reviewed_at_equal_to_or_after_updated_at_is_accepted(
    report_card: ResearchReportCard,
    finalized_note: ResearchNote,
    updated_at: str,
    reviewed_at: str,
) -> None:
    note = _with_payload_updates(
        finalized_note,
        report_card.report_card_id,
        {
            "updated_at": updated_at,
            "review": {"reviewed_at": reviewed_at},
        },
    )

    result = _record(note=note, report_card=report_card)

    assert result.research_note_result.disposition is PersistenceDisposition.CREATED


@pytest.mark.parametrize(
    ("updated_at", "reviewed_at"),
    [
        ("2026-07-09T10:00:00Z", "2026-07-09T09:59:59Z"),
        ("2026-07-09T09:30:00Z", "2026-07-09T08:59:59Z"),
    ],
)
def test_reviewed_at_before_updated_at_is_rejected(
    report_card: ResearchReportCard,
    finalized_note: ResearchNote,
    updated_at: str,
    reviewed_at: str,
) -> None:
    note = _with_payload_updates(
        finalized_note,
        report_card.report_card_id,
        {
            "updated_at": updated_at,
            "review": {"reviewed_at": reviewed_at},
        },
    )

    with pytest.raises(
        FinalizedResearchInterpretationValidationError,
        match="reviewed_at",
    ):
        _record(note=note, report_card=report_card)


@pytest.mark.parametrize("risk_approval_required", [True, False])
def test_risk_approval_required_does_not_grant_or_revoke_research_finalization(
    report_card: ResearchReportCard,
    finalized_note: ResearchNote,
    risk_approval_required: bool,
) -> None:
    note = _with_payload_updates(
        finalized_note,
        report_card.report_card_id,
        {"review": {"risk_approval_required": risk_approval_required}},
    )

    result = _record(note=note, report_card=report_card)

    assert result.research_note_result.disposition is PersistenceDisposition.CREATED


def test_review_decision_absent_is_allowed(
    report_card: ResearchReportCard,
    finalized_note: ResearchNote,
) -> None:
    note = _with_payload_updates(
        finalized_note,
        report_card.report_card_id,
        {"review": {"decision": None}},
    )

    result = _record(note=note, report_card=report_card)

    assert result.research_note_result.disposition is PersistenceDisposition.CREATED


@pytest.mark.parametrize(
    ("reference_update", "match_text"),
    [
        ({"run_ids": ("wrong-run",)}, "run_ids"),
        ({"experiment_ids": ("wrong-experiment",)}, "experiment_ids"),
        ({"data_snapshot_ids": ("wrong-data-snapshot",)}, "data_snapshot_ids"),
        (
            {"benchmark_snapshot_ids": ("wrong-benchmark-snapshot",)},
            "benchmark_snapshot_ids",
        ),
        ({"strategy_ids": ("wrong-strategy",)}, "strategy_ids"),
        ({"artifact_manifest_uris": ("wrong-manifest-uri",)}, "artifact_manifest"),
        ({"artifact_uris": ("wrong-artifact-uri",)}, "artifact_uris"),
        ({"feature_snapshot_ids": ("feature-snapshot-001",)}, "feature_snapshot"),
    ],
)
def test_structured_reference_mismatches_are_rejected(
    report_card: ResearchReportCard,
    finalized_note: ResearchNote,
    reference_update: dict[str, tuple[str, ...]],
    match_text: str,
) -> None:
    references = finalized_note.references.model_copy(update=reference_update)
    note = _with_note_identity(
        finalized_note.model_copy(update={"references": references}),
        report_card.report_card_id,
    )

    with pytest.raises(
        FinalizedResearchInterpretationValidationError, match=match_text
    ):
        _record(note=note, report_card=report_card)


@pytest.mark.parametrize(
    "reference_update",
    [
        {"run_ids": ("run-a", "run-a")},
        {"experiment_ids": ("exp-a", "exp-a")},
        {"artifact_manifest_uris": ("manifest-a", "manifest-a")},
        {"artifact_uris": ("artifact-a", "artifact-a")},
    ],
)
def test_duplicate_structured_references_are_rejected(
    report_card: ResearchReportCard,
    finalized_note: ResearchNote,
    reference_update: dict[str, tuple[str, ...]],
) -> None:
    references = finalized_note.references.model_copy(update=reference_update)
    note = _with_note_identity(
        finalized_note.model_copy(update={"references": references}),
        report_card.report_card_id,
    )

    with pytest.raises(FinalizedResearchInterpretationValidationError):
        _record(note=note, report_card=report_card)


def test_missing_report_card_is_rejected(finalized_note: ResearchNote) -> None:
    missing_report_card_id = "report-card-" + "0" * 64
    note = _with_note_identity(finalized_note, missing_report_card_id)
    repository = _FakeRepository(report_card=None)

    with pytest.raises(FinalizedResearchInterpretationValidationError):
        record_finalized_research_interpretation(
            bundle=FinalizedResearchInterpretationBundle(
                note=note,
                report_card_id=missing_report_card_id,
            ),
            transaction_factory=_transaction_factory(),
            repository_factory=lambda _connection: repository,
        )


def test_corrupt_report_card_readback_is_rejected(
    report_card: ResearchReportCard,
    finalized_note: ResearchNote,
) -> None:
    repository = _FakeRepository(report_card=report_card)
    repository.corrupt_report_card = True

    with pytest.raises(PersistenceCorruptionError):
        record_finalized_research_interpretation(
            bundle=FinalizedResearchInterpretationBundle(
                note=finalized_note,
                report_card_id=report_card.report_card_id,
            ),
            transaction_factory=_transaction_factory(),
            repository_factory=lambda _connection: repository,
        )


def test_incompatible_existing_link_is_rejected(
    report_card: ResearchReportCard,
    finalized_note: ResearchNote,
) -> None:
    repository = _FakeRepository(report_card=report_card)
    repository.links[finalized_note.note_id] = ("report-card-" + "f" * 64,)

    with pytest.raises(FinalizedResearchInterpretationValidationError):
        record_finalized_research_interpretation(
            bundle=FinalizedResearchInterpretationBundle(
                note=finalized_note,
                report_card_id=report_card.report_card_id,
            ),
            transaction_factory=_transaction_factory(),
            repository_factory=lambda _connection: repository,
        )


def test_missing_parent_is_rejected(
    report_card: ResearchReportCard,
    finalized_note: ResearchNote,
) -> None:
    note = _with_note_identity(
        finalized_note.model_copy(update={"parent_note_id": "missing-parent"}),
        report_card.report_card_id,
    )

    with pytest.raises(FinalizedResearchInterpretationValidationError):
        _record(note=note, report_card=report_card)


def test_missing_supersedes_target_is_rejected(
    report_card: ResearchReportCard,
    finalized_note: ResearchNote,
) -> None:
    note = _with_note_identity(
        finalized_note.model_copy(update={"supersedes_note_id": "missing-prior"}),
        report_card.report_card_id,
    )

    with pytest.raises(FinalizedResearchInterpretationValidationError):
        _record(note=note, report_card=report_card)


def test_valid_finalized_v1_prior_note_may_be_superseded(
    report_card: ResearchReportCard,
    finalized_note: ResearchNote,
) -> None:
    prior_note = _with_note_identity(
        finalized_note.model_copy(update={"title": "Prior interpretation"}),
        report_card.report_card_id,
    )
    repository = _FakeRepository(report_card=report_card)
    repository.notes[prior_note.note_id] = prior_note
    repository.links[prior_note.note_id] = (report_card.report_card_id,)
    successor = _with_note_identity(
        finalized_note.model_copy(update={"supersedes_note_id": prior_note.note_id}),
        report_card.report_card_id,
    )

    result = record_finalized_research_interpretation(
        bundle=FinalizedResearchInterpretationBundle(
            note=successor,
            report_card_id=report_card.report_card_id,
        ),
        transaction_factory=_transaction_factory(),
        repository_factory=lambda _connection: repository,
    )

    assert result.research_note_result.disposition is PersistenceDisposition.CREATED
    assert repository.notes[prior_note.note_id].status == prior_note.status


def test_arbitrary_id_prior_note_is_not_valid_supersession_authority(
    report_card: ResearchReportCard,
    finalized_note: ResearchNote,
) -> None:
    prior_note = finalized_note.model_copy(
        update={
            "note_id": "caller-owned-prior-note",
            "title": "Caller-owned prior interpretation",
        }
    )
    repository = _FakeRepository(report_card=report_card)
    repository.notes[prior_note.note_id] = prior_note
    repository.links[prior_note.note_id] = (report_card.report_card_id,)
    successor = _with_note_identity(
        finalized_note.model_copy(update={"supersedes_note_id": prior_note.note_id}),
        report_card.report_card_id,
    )

    with pytest.raises(FinalizedResearchInterpretationValidationError):
        record_finalized_research_interpretation(
            bundle=FinalizedResearchInterpretationBundle(
                note=successor,
                report_card_id=report_card.report_card_id,
            ),
            transaction_factory=_transaction_factory(),
            repository_factory=lambda _connection: repository,
        )


@pytest.mark.parametrize(
    "prior_note_id",
    [
        "research-note-finalized-v1-not-a-full-digest",
        "research-note-finalized-v1-" + "0" * 64,
    ],
)
def test_invalid_finalized_v1_prior_id_is_rejected_as_supersession_target(
    report_card: ResearchReportCard,
    finalized_note: ResearchNote,
    prior_note_id: str,
) -> None:
    prior_note = finalized_note.model_copy(update={"note_id": prior_note_id})
    repository = _FakeRepository(report_card=report_card)
    repository.notes[prior_note.note_id] = prior_note
    repository.links[prior_note.note_id] = (report_card.report_card_id,)
    successor = _with_note_identity(
        finalized_note.model_copy(update={"supersedes_note_id": prior_note.note_id}),
        report_card.report_card_id,
    )

    with pytest.raises(FinalizedResearchInterpretationValidationError):
        record_finalized_research_interpretation(
            bundle=FinalizedResearchInterpretationBundle(
                note=successor,
                report_card_id=report_card.report_card_id,
            ),
            transaction_factory=_transaction_factory(),
            repository_factory=lambda _connection: repository,
        )


def test_finalized_v1_prior_note_linked_to_different_card_is_rejected(
    report_card: ResearchReportCard,
    finalized_note: ResearchNote,
) -> None:
    prior_note = _with_note_identity(
        finalized_note.model_copy(update={"title": "Prior interpretation"}),
        report_card.report_card_id,
    )
    repository = _FakeRepository(report_card=report_card)
    repository.notes[prior_note.note_id] = prior_note
    repository.links[prior_note.note_id] = ("report-card-" + "f" * 64,)
    successor = _with_note_identity(
        finalized_note.model_copy(update={"supersedes_note_id": prior_note.note_id}),
        report_card.report_card_id,
    )

    with pytest.raises(FinalizedResearchInterpretationValidationError):
        record_finalized_research_interpretation(
            bundle=FinalizedResearchInterpretationBundle(
                note=successor,
                report_card_id=report_card.report_card_id,
            ),
            transaction_factory=_transaction_factory(),
            repository_factory=lambda _connection: repository,
        )


def test_prior_note_with_invalid_review_chronology_cannot_be_superseded(
    report_card: ResearchReportCard,
    finalized_note: ResearchNote,
) -> None:
    prior_note = _with_payload_updates(
        finalized_note,
        report_card.report_card_id,
        {
            "title": "Prior interpretation",
            "updated_at": "2026-07-09T10:05:00Z",
            "review": {"reviewed_at": "2026-07-09T10:00:00Z"},
        },
    )
    repository = _FakeRepository(report_card=report_card)
    repository.notes[prior_note.note_id] = prior_note
    repository.links[prior_note.note_id] = (report_card.report_card_id,)
    successor = _with_note_identity(
        finalized_note.model_copy(update={"supersedes_note_id": prior_note.note_id}),
        report_card.report_card_id,
    )

    with pytest.raises(FinalizedResearchInterpretationValidationError):
        record_finalized_research_interpretation(
            bundle=FinalizedResearchInterpretationBundle(
                note=successor,
                report_card_id=report_card.report_card_id,
            ),
            transaction_factory=_transaction_factory(),
            repository_factory=lambda _connection: repository,
        )


def test_generic_parent_note_without_finalized_v1_identity_remains_allowed(
    report_card: ResearchReportCard,
    finalized_note: ResearchNote,
) -> None:
    parent_note = _with_payload_updates_without_identity(
        finalized_note,
        {
            "note_id": "caller-owned-parent-note",
            "status": "draft",
        },
    )
    repository = _FakeRepository(report_card=report_card)
    repository.notes[parent_note.note_id] = parent_note
    successor = _with_note_identity(
        finalized_note.model_copy(update={"parent_note_id": parent_note.note_id}),
        report_card.report_card_id,
    )

    result = record_finalized_research_interpretation(
        bundle=FinalizedResearchInterpretationBundle(
            note=successor,
            report_card_id=report_card.report_card_id,
        ),
        transaction_factory=_transaction_factory(),
        repository_factory=lambda _connection: repository,
    )

    assert result.research_note_result.disposition is PersistenceDisposition.CREATED


def test_authoritative_finalized_v1_parent_linked_to_same_card_is_allowed(
    report_card: ResearchReportCard,
    finalized_note: ResearchNote,
) -> None:
    parent_note = _with_note_identity(
        finalized_note.model_copy(update={"title": "Parent interpretation"}),
        report_card.report_card_id,
    )
    repository = _FakeRepository(report_card=report_card)
    repository.notes[parent_note.note_id] = parent_note
    repository.links[parent_note.note_id] = (report_card.report_card_id,)
    successor = _with_note_identity(
        finalized_note.model_copy(update={"parent_note_id": parent_note.note_id}),
        report_card.report_card_id,
    )

    result = record_finalized_research_interpretation(
        bundle=FinalizedResearchInterpretationBundle(
            note=successor,
            report_card_id=report_card.report_card_id,
        ),
        transaction_factory=_transaction_factory(),
        repository_factory=lambda _connection: repository,
    )

    assert result.research_note_result.disposition is PersistenceDisposition.CREATED


def test_deterministic_id_mismatch_is_rejected(
    report_card: ResearchReportCard,
    finalized_note: ResearchNote,
) -> None:
    stale = finalized_note.model_copy(
        update={"note_id": "research-note-finalized-v1-" + "0" * 64}
    )

    with pytest.raises(FinalizedResearchInterpretationValidationError):
        _record(note=stale, report_card=report_card)


def test_replayed_note_can_create_missing_authority_link(
    report_card: ResearchReportCard,
    finalized_note: ResearchNote,
) -> None:
    repository = _FakeRepository(report_card=report_card)
    repository.notes[finalized_note.note_id] = finalized_note

    result = record_finalized_research_interpretation(
        bundle=FinalizedResearchInterpretationBundle(
            note=finalized_note,
            report_card_id=report_card.report_card_id,
        ),
        transaction_factory=_transaction_factory(),
        repository_factory=lambda _connection: repository,
    )

    assert result.research_note_result.disposition is PersistenceDisposition.REPLAYED
    assert result.report_card_link_result.disposition is PersistenceDisposition.CREATED


def test_replayed_note_and_link_are_accepted(
    report_card: ResearchReportCard,
    finalized_note: ResearchNote,
) -> None:
    repository = _FakeRepository(report_card=report_card)
    repository.notes[finalized_note.note_id] = finalized_note
    repository.links[finalized_note.note_id] = (report_card.report_card_id,)

    result = record_finalized_research_interpretation(
        bundle=FinalizedResearchInterpretationBundle(
            note=finalized_note,
            report_card_id=report_card.report_card_id,
        ),
        transaction_factory=_transaction_factory(),
        repository_factory=lambda _connection: repository,
    )

    assert result.research_note_result.disposition is PersistenceDisposition.REPLAYED
    assert result.report_card_link_result.disposition is PersistenceDisposition.REPLAYED


def test_created_note_with_replayed_link_is_rejected_as_incoherent(
    report_card: ResearchReportCard,
    finalized_note: ResearchNote,
) -> None:
    repository = _FakeRepository(report_card=report_card)
    repository.force_created_note_replayed_link = True

    with pytest.raises(FinalizedResearchInterpretationDispositionCoherenceError):
        record_finalized_research_interpretation(
            bundle=FinalizedResearchInterpretationBundle(
                note=finalized_note,
                report_card_id=report_card.report_card_id,
            ),
            transaction_factory=_transaction_factory(),
            repository_factory=lambda _connection: repository,
        )


def _record(
    *,
    note: ResearchNote,
    report_card: ResearchReportCard,
) -> Any:
    repository = _FakeRepository(report_card=report_card)
    return record_finalized_research_interpretation(
        bundle=FinalizedResearchInterpretationBundle(
            note=note,
            report_card_id=report_card.report_card_id,
        ),
        transaction_factory=_transaction_factory(),
        repository_factory=lambda _connection: repository,
    )


class _Transaction(AbstractContextManager[object]):
    def __enter__(self) -> object:
        return object()

    def __exit__(self, *exc_info: object) -> None:
        return None


def _transaction_factory() -> Any:
    return _Transaction


class _FakeRepository:
    def __init__(self, *, report_card: ResearchReportCard | None) -> None:
        self.report_card = report_card
        self.notes: dict[str, ResearchNote] = {}
        self.links: dict[str, tuple[str, ...]] = {}
        self.corrupt_report_card = False
        self.force_created_note_replayed_link = False

    def get_research_report_card(
        self,
        report_card_id: str,
    ) -> ResearchReportCard | None:
        if self.corrupt_report_card:
            raise PersistenceCorruptionError(
                PersistenceErrorContext(
                    table_name="research_report_cards",
                    operation="get_research_report_card",
                    logical_identity={"report_card_id": report_card_id},
                )
            )
        if (
            self.report_card is None
            or self.report_card.report_card_id != report_card_id
        ):
            return None
        return self.report_card

    def get_research_note(self, note_id: str) -> ResearchNote | None:
        return self.notes.get(note_id)

    def get_report_card_ids_for_note(self, note_id: str) -> tuple[str, ...]:
        return self.links.get(note_id, ())

    def record_research_note(self, note: ResearchNote) -> PersistenceWriteResult:
        disposition = (
            PersistenceDisposition.REPLAYED
            if note.note_id in self.notes
            else PersistenceDisposition.CREATED
        )
        self.notes.setdefault(note.note_id, note)
        return _write_result(
            disposition=disposition,
            table_name="research_notes",
            primary_key={"note_id": note.note_id},
        )

    def record_research_note_report_card_link(
        self,
        *,
        note_id: str,
        report_card_id: str,
    ) -> PersistenceWriteResult:
        existing = self.links.get(note_id, ())
        if self.force_created_note_replayed_link:
            disposition = PersistenceDisposition.REPLAYED
        elif report_card_id in existing:
            disposition = PersistenceDisposition.REPLAYED
        else:
            disposition = PersistenceDisposition.CREATED
            self.links[note_id] = tuple(sorted((*existing, report_card_id)))
        return _write_result(
            disposition=disposition,
            table_name="research_note_report_cards",
            primary_key={"note_id": note_id, "report_card_id": report_card_id},
        )


def _write_result(
    *,
    disposition: PersistenceDisposition,
    table_name: str,
    primary_key: dict[str, str],
) -> PersistenceWriteResult:
    return PersistenceWriteResult(
        disposition=disposition,
        record=PersistedRecordMetadata(table_name=table_name, primary_key=primary_key),
    )


def _finalized_note_for_report_card(report_card: ResearchReportCard) -> ResearchNote:
    payload = _load_fixture("research_note.json")
    payload.update(
        {
            "note_id": "temporary-note-id",
            "status": "finalized",
            "created_by": "human-owner-a",
            "updated_by": "human-owner-a",
            "title": "Synthetic ETF infrastructure validation interpretation",
            "interpretation": (
                "Human-owner interpretation of deterministic synthetic ETF "
                "infrastructure evidence."
            ),
            "limitations": [
                "Generated synthetic data only.",
                "Infrastructure validation only.",
                "No investment-performance claim.",
                "Not production-data strategy research.",
                "Not paper-trading evidence.",
                "Not live-trading evidence.",
            ],
            "review": {
                "review_status": "approved",
                "reviewer_id": "human-owner-a",
                "review_role": "human_owner",
                "reviewed_at": "2026-07-09T10:00:00Z",
                "risk_approval_required": True,
            },
            "references": {
                "experiment_ids": [report_card.experiment_id],
                "run_ids": [report_card.source_run_id],
                "artifact_uris": [report_card.evidence.artifacts[0].uri],
                "artifact_manifest_uris": [report_card.evidence.artifact_manifest_uri],
                "data_snapshot_ids": [report_card.lineage.data_snapshot_id],
                "feature_snapshot_ids": [],
                "benchmark_snapshot_ids": [report_card.lineage.benchmark_snapshot_id],
                "strategy_ids": [report_card.lineage.strategy_id],
            },
        }
    )
    return _with_note_identity(
        ResearchNote.model_validate(payload),
        report_card.report_card_id,
    )


def _with_note_identity(note: ResearchNote, report_card_id: str) -> ResearchNote:
    note_id = derive_finalized_research_note_id(
        note=note,
        report_card_ids=(report_card_id,),
    )
    return note.model_copy(update={"note_id": note_id})


def _with_payload_updates(
    note: ResearchNote,
    report_card_id: str,
    updates: dict[str, Any],
) -> ResearchNote:
    payload = note.model_dump(mode="json")
    for field_name, value in updates.items():
        if isinstance(value, dict) and isinstance(payload.get(field_name), dict):
            payload[field_name].update(value)
        else:
            payload[field_name] = value
    return _with_note_identity(ResearchNote.model_validate(payload), report_card_id)


def _with_payload_updates_without_identity(
    note: ResearchNote,
    updates: dict[str, Any],
) -> ResearchNote:
    payload = note.model_dump(mode="json")
    for field_name, value in updates.items():
        if isinstance(value, dict) and isinstance(payload.get(field_name), dict):
            payload[field_name].update(value)
        else:
            payload[field_name] = value
    return ResearchNote.model_validate(payload)


def _load_fixture(filename: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / filename).read_text(encoding="utf-8"))
