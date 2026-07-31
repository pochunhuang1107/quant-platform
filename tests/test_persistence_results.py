from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime
from enum import StrEnum

import pytest

from research_sdk.persistence.results import (
    PersistedRecordMetadata,
    PersistenceDisposition,
    PersistenceWriteResult,
)


def test_persistence_disposition_members_are_successful_outcomes_only() -> None:
    assert tuple(PersistenceDisposition) == (
        PersistenceDisposition.CREATED,
        PersistenceDisposition.REPLAYED,
    )
    assert PersistenceDisposition.CREATED.value == "created"
    assert PersistenceDisposition.REPLAYED.value == "replayed"
    assert isinstance(PersistenceDisposition.CREATED, StrEnum)
    assert PersistenceDisposition.CREATED == "created"

    prohibited_members = {
        "REJECTED",
        "CONFLICTED",
        "FAILED",
        "SKIPPED",
        "UPDATED",
        "DELETED",
    }

    assert prohibited_members.isdisjoint(PersistenceDisposition.__members__)


def test_persisted_record_metadata_is_frozen_and_structurally_equal() -> None:
    first = PersistedRecordMetadata(
        table_name="experiment_runs",
        primary_key={"run_id": "run-001"},
        contract_hash="0" * 64,
    )
    second = PersistedRecordMetadata(
        table_name="experiment_runs",
        primary_key={"run_id": "run-001"},
        contract_hash="0" * 64,
    )

    assert first == second

    with pytest.raises(FrozenInstanceError):
        first.table_name = "data_snapshot_manifests"


def test_persisted_record_metadata_retains_safe_record_identity() -> None:
    inserted_at = datetime(2026, 7, 31, 12, 30, tzinfo=UTC)
    metadata = PersistedRecordMetadata(
        table_name="experiment_runs",
        primary_key={"run_id": "run-001"},
        contract_hash="0" * 64,
        inserted_at=inserted_at,
    )

    assert metadata.table_name == "experiment_runs"
    assert metadata.primary_key == {"run_id": "run-001"}
    assert metadata.contract_hash == "0" * 64
    assert metadata.inserted_at is inserted_at


def test_persisted_record_metadata_defaults_are_safe_for_review_events() -> None:
    before = datetime.now(tz=UTC)
    metadata = PersistedRecordMetadata(
        table_name="review_events",
        primary_key={"review_event_id": "review-event-001"},
    )
    after = datetime.now(tz=UTC)

    assert metadata.contract_hash is None
    assert metadata.inserted_at is None
    assert metadata.inserted_at not in (before, after)


def test_persisted_record_metadata_exposes_no_payload_or_db_config_fields() -> None:
    field_names = {field.name for field in fields(PersistedRecordMetadata)}

    for unsafe_name in (
        "raw_contract",
        "raw_review",
        "credential",
        "credentials",
        "secret",
        "database_url",
        "db_url",
    ):
        assert unsafe_name not in field_names


def test_persistence_write_result_is_frozen_and_structurally_equal() -> None:
    metadata = PersistedRecordMetadata(
        table_name="experiment_runs",
        primary_key={"run_id": "run-001"},
        contract_hash="0" * 64,
    )
    first = PersistenceWriteResult(
        disposition=PersistenceDisposition.CREATED,
        record=metadata,
    )
    second = PersistenceWriteResult(
        disposition=PersistenceDisposition.CREATED,
        record=metadata,
    )

    assert first == second

    with pytest.raises(FrozenInstanceError):
        first.disposition = PersistenceDisposition.REPLAYED


def test_persistence_write_result_accepts_created_and_replayed() -> None:
    metadata = PersistedRecordMetadata(
        table_name="experiment_runs",
        primary_key={"run_id": "run-001"},
        contract_hash="0" * 64,
    )

    created = PersistenceWriteResult(
        disposition=PersistenceDisposition.CREATED,
        record=metadata,
    )
    replayed = PersistenceWriteResult(
        disposition=PersistenceDisposition.REPLAYED,
        record=metadata,
    )

    assert created.disposition is PersistenceDisposition.CREATED
    assert replayed.disposition is PersistenceDisposition.REPLAYED
    assert created.record is metadata


def test_persistence_write_result_aggregate_entry_count_semantics() -> None:
    metadata = PersistedRecordMetadata(
        table_name="run_artifact_manifests",
        primary_key={"manifest_id": "manifest-001"},
        contract_hash="0" * 64,
    )

    default_result = PersistenceWriteResult(
        disposition=PersistenceDisposition.CREATED,
        record=metadata,
    )
    zero_result = PersistenceWriteResult(
        disposition=PersistenceDisposition.CREATED,
        record=metadata,
        aggregate_entry_count=0,
    )
    positive_result = PersistenceWriteResult(
        disposition=PersistenceDisposition.REPLAYED,
        record=metadata,
        aggregate_entry_count=9,
    )

    assert default_result.aggregate_entry_count is None
    assert zero_result.aggregate_entry_count == 0
    assert positive_result.aggregate_entry_count == 9


def test_persistence_write_result_rejects_negative_aggregate_count() -> None:
    metadata = PersistedRecordMetadata(
        table_name="run_artifact_manifests",
        primary_key={"manifest_id": "manifest-001"},
        contract_hash="0" * 64,
    )

    with pytest.raises(ValueError, match="aggregate_entry_count must be non-negative"):
        PersistenceWriteResult(
            disposition=PersistenceDisposition.CREATED,
            record=metadata,
            aggregate_entry_count=-1,
        )


def test_persistence_write_result_exposes_no_execution_or_payload_fields() -> None:
    field_names = {field.name for field in fields(PersistenceWriteResult)}

    for unsafe_name in (
        "raw_payload",
        "raw_contract",
        "raw_review",
        "credential",
        "credentials",
        "database_url",
        "db_url",
        "sql",
        "statement",
        "exception",
        "retry",
        "row_count",
    ):
        assert unsafe_name not in field_names
