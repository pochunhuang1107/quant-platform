from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError
from typing import get_type_hints

import pytest

import research_sdk.persistence.protocols as protocols
from research_sdk.contracts import (
    DataSnapshotManifest,
    ExperimentRunRecord,
    ResearchNote,
    ReviewMetadata,
    RunArtifactManifest,
)
from research_sdk.persistence import (
    ExperimentLedgerRepository as ExportedExperimentLedgerRepository,
)
from research_sdk.persistence import (
    PersistedRecordMetadata as ExportedPersistedRecordMetadata,
)
from research_sdk.persistence import (
    PersistenceDisposition as ExportedPersistenceDisposition,
)
from research_sdk.persistence import (
    PersistenceWriteResult as ExportedPersistenceWriteResult,
)
from research_sdk.persistence.mappers import ReviewSubjectType
from research_sdk.persistence.protocols import ExperimentLedgerRepository
from research_sdk.persistence.results import (
    PersistedRecordMetadata,
    PersistenceDisposition,
    PersistenceWriteResult,
)

EXPECTED_PROTOCOL_METHODS = {
    "record_experiment_run",
    "record_data_snapshot_manifest",
    "record_run_artifact_manifest",
    "record_research_note",
    "append_review_event",
}


class FakeExperimentLedgerRepository:
    def record_experiment_run(
        self,
        run: ExperimentRunRecord,
    ) -> PersistenceWriteResult:
        return PersistenceWriteResult(
            disposition=PersistenceDisposition.CREATED,
            record=PersistedRecordMetadata(
                table_name="experiment_runs",
                primary_key={"run_id": run.run_id},
                contract_hash="0" * 64,
            ),
        )

    def record_data_snapshot_manifest(
        self,
        snapshot: DataSnapshotManifest,
    ) -> PersistenceWriteResult:
        return PersistenceWriteResult(
            disposition=PersistenceDisposition.CREATED,
            record=PersistedRecordMetadata(
                table_name="data_snapshot_manifests",
                primary_key={"snapshot_id": snapshot.snapshot_id},
                contract_hash="1" * 64,
            ),
        )

    def record_run_artifact_manifest(
        self,
        *,
        manifest_id: str,
        manifest: RunArtifactManifest,
    ) -> PersistenceWriteResult:
        return PersistenceWriteResult(
            disposition=PersistenceDisposition.CREATED,
            record=PersistedRecordMetadata(
                table_name="run_artifact_manifests",
                primary_key={"manifest_id": manifest_id},
                contract_hash="2" * 64,
            ),
            aggregate_entry_count=len(manifest.artifacts),
        )

    def record_research_note(
        self,
        note: ResearchNote,
    ) -> PersistenceWriteResult:
        return PersistenceWriteResult(
            disposition=PersistenceDisposition.CREATED,
            record=PersistedRecordMetadata(
                table_name="research_notes",
                primary_key={"note_id": note.note_id},
                contract_hash="3" * 64,
            ),
        )

    def append_review_event(
        self,
        *,
        review_event_id: str,
        subject_type: ReviewSubjectType | str,
        subject_id: str,
        review: ReviewMetadata,
    ) -> PersistenceWriteResult:
        return PersistenceWriteResult(
            disposition=PersistenceDisposition.CREATED,
            record=PersistedRecordMetadata(
                table_name="review_events",
                primary_key={"review_event_id": review_event_id},
            ),
        )


def test_protocols_import_from_protocol_module() -> None:
    assert protocols.PersistedRecordMetadata is PersistedRecordMetadata
    assert protocols.PersistenceWriteResult is PersistenceWriteResult
    assert protocols.ExperimentLedgerRepository is ExperimentLedgerRepository


def test_protocols_export_from_persistence_package() -> None:
    assert ExportedPersistedRecordMetadata is PersistedRecordMetadata
    assert ExportedPersistenceDisposition is PersistenceDisposition
    assert ExportedPersistenceWriteResult is PersistenceWriteResult
    assert ExportedExperimentLedgerRepository is ExperimentLedgerRepository


def test_persisted_record_metadata_is_frozen() -> None:
    metadata = PersistedRecordMetadata(
        table_name="experiment_runs",
        primary_key={"run_id": "run-001"},
        contract_hash="0" * 64,
    )

    with pytest.raises(FrozenInstanceError):
        metadata.table_name = "data_snapshot_manifests"


def test_persisted_record_metadata_accepts_minimal_fields() -> None:
    metadata = PersistedRecordMetadata(
        table_name="experiment_runs",
        primary_key={"run_id": "run-001"},
        contract_hash="0" * 64,
    )

    assert metadata.table_name == "experiment_runs"
    assert metadata.primary_key == {"run_id": "run-001"}
    assert metadata.contract_hash == "0" * 64
    assert metadata.inserted_at is None


def test_persisted_record_metadata_can_represent_review_events_without_hash() -> None:
    metadata = PersistedRecordMetadata(
        table_name="review_events",
        primary_key={"review_event_id": "review-event-001"},
    )

    assert metadata.contract_hash is None


def test_experiment_ledger_repository_exposes_expected_methods_only() -> None:
    method_names = {
        name
        for name, value in vars(ExperimentLedgerRepository).items()
        if inspect.isfunction(value) and not name.startswith("_")
    }

    assert method_names == EXPECTED_PROTOCOL_METHODS


def test_protocol_method_signatures_use_validated_contract_types() -> None:
    assert _type_hints("record_experiment_run")["run"] is ExperimentRunRecord
    assert (
        _type_hints("record_data_snapshot_manifest")["snapshot"] is DataSnapshotManifest
    )
    assert _type_hints("record_run_artifact_manifest")["manifest"] is (
        RunArtifactManifest
    )
    assert _type_hints("record_research_note")["note"] is ResearchNote
    assert _type_hints("append_review_event")["review"] is ReviewMetadata


def test_protocol_method_return_types_use_persistence_write_result() -> None:
    for method_name in EXPECTED_PROTOCOL_METHODS:
        assert _type_hints(method_name)["return"] is PersistenceWriteResult


def test_artifact_manifest_signature_requires_keyword_only_fields() -> None:
    signature = inspect.signature(
        ExperimentLedgerRepository.record_run_artifact_manifest
    )

    assert signature.parameters["manifest_id"].kind is (inspect.Parameter.KEYWORD_ONLY)
    assert signature.parameters["manifest"].kind is inspect.Parameter.KEYWORD_ONLY


def test_review_event_signature_requires_keyword_only_fields() -> None:
    signature = inspect.signature(ExperimentLedgerRepository.append_review_event)

    for parameter_name in (
        "review_event_id",
        "subject_type",
        "subject_id",
        "review",
    ):
        assert signature.parameters[parameter_name].kind is (
            inspect.Parameter.KEYWORD_ONLY
        )


def test_protocol_methods_do_not_accept_contract_hash_parameter() -> None:
    for method_name in EXPECTED_PROTOCOL_METHODS:
        signature = inspect.signature(getattr(ExperimentLedgerRepository, method_name))

        assert "contract_hash" not in signature.parameters


def test_protocol_methods_are_synchronous() -> None:
    for method_name in EXPECTED_PROTOCOL_METHODS:
        method = getattr(ExperimentLedgerRepository, method_name)

        assert not inspect.iscoroutinefunction(method)
        assert not inspect.isasyncgenfunction(method)


def test_protocol_module_excludes_db_driver_session_engine_and_io_hooks() -> None:
    source = inspect.getsource(protocols)

    for prohibited_term in (
        "sqlalchemy",
        "alembic",
        "create_engine",
        "Session",
        "connect(",
        "execute(",
        "get_database_url",
        "metadata",
        "Table",
        "Path(",
        "open(",
        "read_text(",
        "requests",
        "boto3",
        "psycopg",
        "asyncpg",
    ):
        assert prohibited_term not in source


def test_protocol_module_does_not_import_row_mapper_functions() -> None:
    module_names = set(vars(protocols))

    for prohibited_name in (
        "experiment_run_to_row",
        "data_snapshot_manifest_to_row",
        "run_artifact_manifest_to_rows",
        "research_note_to_row",
        "review_metadata_to_row",
    ):
        assert prohibited_name not in module_names


def test_fake_class_structurally_satisfies_repository_protocol() -> None:
    repository: ExperimentLedgerRepository = FakeExperimentLedgerRepository()

    assert isinstance(repository, ExperimentLedgerRepository)


def _type_hints(method_name: str) -> dict[str, object]:
    return get_type_hints(
        getattr(ExperimentLedgerRepository, method_name),
        globalns=vars(protocols),
    )
