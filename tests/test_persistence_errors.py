from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError, fields

import pytest

import research_sdk.persistence as persistence
import research_sdk.persistence.errors as errors
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
from research_sdk.persistence.errors import (
    AggregateIntegrityError,
    ContractHashConflictError,
    DuplicateReviewEventError,
    NaturalKeyConflictError,
    PersistenceConflictError,
    PersistenceError,
    PersistenceErrorContext,
    ReplayLookupError,
    UnsupportedVersioningConflictError,
)
from research_sdk.persistence.protocols import ExperimentLedgerRepository
from research_sdk.persistence.results import (
    PersistedRecordMetadata,
    PersistenceDisposition,
    PersistenceWriteResult,
)

CONCRETE_ERROR_TYPES = (
    ContractHashConflictError,
    NaturalKeyConflictError,
    UnsupportedVersioningConflictError,
    DuplicateReviewEventError,
    AggregateIntegrityError,
    ReplayLookupError,
)

CONFLICT_ERROR_TYPES = (
    ContractHashConflictError,
    NaturalKeyConflictError,
    UnsupportedVersioningConflictError,
    DuplicateReviewEventError,
)


def valid_context() -> PersistenceErrorContext:
    return PersistenceErrorContext(
        table_name="experiment_runs",
        operation="record_experiment_run",
        logical_identity={"run_id": "run-001"},
        constraint_name="experiment_runs_pkey",
        existing_hash_prefix="0abc",
        attempted_hash_prefix="1def",
    )


def test_context_is_frozen_and_structurally_equal() -> None:
    first = valid_context()
    second = valid_context()

    assert first == second

    with pytest.raises(FrozenInstanceError):
        first.table_name = "data_snapshot_manifests"


def test_context_retains_safe_fields() -> None:
    context = valid_context()

    assert context.table_name == "experiment_runs"
    assert context.operation == "record_experiment_run"
    assert context.logical_identity == {"run_id": "run-001"}
    assert context.constraint_name == "experiment_runs_pkey"
    assert context.existing_hash_prefix == "0abc"
    assert context.attempted_hash_prefix == "1def"


def test_context_optional_fields_default_to_none() -> None:
    context = PersistenceErrorContext(
        table_name="review_events",
        operation="append_review_event",
        logical_identity={"review_event_id": "review-event-001"},
    )

    assert context.constraint_name is None
    assert context.existing_hash_prefix is None
    assert context.attempted_hash_prefix is None


@pytest.mark.parametrize("table_name", ["", "   "])
def test_context_rejects_blank_table_name(table_name: str) -> None:
    with pytest.raises(ValueError, match="table_name must not be blank"):
        PersistenceErrorContext(
            table_name=table_name,
            operation="record",
            logical_identity={"id": "value"},
        )


@pytest.mark.parametrize("operation", ["", "   "])
def test_context_rejects_blank_operation(operation: str) -> None:
    with pytest.raises(ValueError, match="operation must not be blank"):
        PersistenceErrorContext(
            table_name="experiment_runs",
            operation=operation,
            logical_identity={"id": "value"},
        )


def test_context_rejects_empty_logical_identity() -> None:
    with pytest.raises(ValueError, match="logical_identity must not be empty"):
        PersistenceErrorContext(
            table_name="experiment_runs",
            operation="record",
            logical_identity={},
        )


@pytest.mark.parametrize("prefix", ["a", "012345abcdef"])
def test_context_accepts_valid_hash_prefixes(prefix: str) -> None:
    context = PersistenceErrorContext(
        table_name="experiment_runs",
        operation="record",
        logical_identity={"run_id": "run-001"},
        existing_hash_prefix=prefix,
        attempted_hash_prefix=prefix,
    )

    assert context.existing_hash_prefix == prefix
    assert context.attempted_hash_prefix == prefix


@pytest.mark.parametrize(
    ("field_name", "prefix"),
    [
        ("existing_hash_prefix", "ABC"),
        ("existing_hash_prefix", "not-hex"),
        ("existing_hash_prefix", ""),
        ("existing_hash_prefix", "012345abcdef0"),
        ("existing_hash_prefix", "0" * 64),
        ("attempted_hash_prefix", "ABC"),
        ("attempted_hash_prefix", "not-hex"),
        ("attempted_hash_prefix", ""),
        ("attempted_hash_prefix", "012345abcdef0"),
        ("attempted_hash_prefix", "0" * 64),
    ],
)
def test_context_rejects_invalid_hash_prefixes(
    field_name: str,
    prefix: str,
) -> None:
    kwargs = {
        "table_name": "experiment_runs",
        "operation": "record",
        "logical_identity": {"run_id": "run-001"},
        field_name: prefix,
    }

    with pytest.raises(
        ValueError,
        match=f"{field_name} must be 1 to 12 lowercase hexadecimal characters",
    ):
        PersistenceErrorContext(**kwargs)


def test_context_validates_hash_prefix_fields_independently() -> None:
    with pytest.raises(ValueError, match="attempted_hash_prefix must be"):
        PersistenceErrorContext(
            table_name="experiment_runs",
            operation="record",
            logical_identity={"run_id": "run-001"},
            existing_hash_prefix="abc123",
            attempted_hash_prefix="ABC123",
        )


def test_context_exposes_no_payload_secret_execution_retry_or_logging_fields() -> None:
    field_names = {field.name for field in fields(PersistenceErrorContext)}

    for unsafe_name in (
        "raw_payload",
        "raw_contract",
        "raw_review",
        "payload",
        "details",
        "credentials",
        "credential",
        "password",
        "secret",
        "sql",
        "statement",
        "database_url",
        "db_url",
        "exception",
        "driver_exception",
        "retryable",
        "retry_after",
        "retry_count",
        "logger",
        "log_context",
    ):
        assert unsafe_name not in field_names


def test_error_hierarchy_matches_domain_taxonomy() -> None:
    assert issubclass(PersistenceError, Exception)
    assert issubclass(PersistenceConflictError, PersistenceError)
    assert issubclass(ContractHashConflictError, PersistenceConflictError)
    assert issubclass(NaturalKeyConflictError, PersistenceConflictError)
    assert issubclass(UnsupportedVersioningConflictError, NaturalKeyConflictError)
    assert issubclass(DuplicateReviewEventError, PersistenceConflictError)
    assert not issubclass(DuplicateReviewEventError, NaturalKeyConflictError)
    assert not issubclass(DuplicateReviewEventError, ContractHashConflictError)
    assert issubclass(ReplayLookupError, PersistenceError)
    assert not issubclass(ReplayLookupError, PersistenceConflictError)
    assert not issubclass(ReplayLookupError, ContractHashConflictError)
    assert not issubclass(ReplayLookupError, NaturalKeyConflictError)
    assert not issubclass(ReplayLookupError, AggregateIntegrityError)
    assert issubclass(AggregateIntegrityError, PersistenceError)
    assert not issubclass(AggregateIntegrityError, PersistenceConflictError)


def test_concrete_errors_instantiate_with_valid_context() -> None:
    context = valid_context()

    for error_type in CONCRETE_ERROR_TYPES:
        error = error_type(context)

        assert isinstance(error, Exception)
        assert isinstance(error, PersistenceError)
        assert error.context is context


def test_persistence_error_catches_every_concrete_domain_error() -> None:
    context = valid_context()

    for error_type in CONCRETE_ERROR_TYPES:
        try:
            raise error_type(context)
        except PersistenceError as error:
            assert type(error) is error_type


def test_persistence_conflict_error_catches_conflict_types() -> None:
    context = valid_context()

    for error_type in CONFLICT_ERROR_TYPES:
        try:
            raise error_type(context)
        except PersistenceConflictError as error:
            assert type(error) is error_type


def test_persistence_conflict_error_does_not_catch_aggregate_integrity() -> None:
    context = valid_context()

    try:
        raise AggregateIntegrityError(context)
    except PersistenceConflictError:
        pytest.fail("AggregateIntegrityError must not be a conflict error")
    except AggregateIntegrityError:
        pass


def test_errors_expose_read_only_context_property() -> None:
    context = valid_context()
    error = ContractHashConflictError(context)

    assert error.context is context

    with pytest.raises(AttributeError):
        error.context = context


def test_errors_use_base_constructor_signature() -> None:
    for error_type in CONCRETE_ERROR_TYPES:
        signature = inspect.signature(error_type)

        assert tuple(signature.parameters) == ("context",)


def test_errors_reject_arbitrary_messages_and_details() -> None:
    context = valid_context()

    for error_type in CONCRETE_ERROR_TYPES:
        with pytest.raises(TypeError):
            error_type(context, "raw message")
        with pytest.raises(TypeError):
            error_type(context, details={"raw_payload": "unsafe"})


def test_error_messages_are_deterministic_for_identity_order() -> None:
    first_context = PersistenceErrorContext(
        table_name="run_artifact_manifests",
        operation="record_run_artifact_manifest",
        logical_identity={"run_id": "run-001", "manifest_id": "manifest-001"},
    )
    second_context = PersistenceErrorContext(
        table_name="run_artifact_manifests",
        operation="record_run_artifact_manifest",
        logical_identity={"manifest_id": "manifest-001", "run_id": "run-001"},
    )

    assert str(NaturalKeyConflictError(first_context)) == str(
        NaturalKeyConflictError(second_context)
    )


def test_error_messages_contain_safe_classification_and_context() -> None:
    context = PersistenceErrorContext(
        table_name="experiment_runs",
        operation="record_experiment_run",
        logical_identity={"run_id": "run-001"},
        constraint_name="experiment_runs_pkey",
        existing_hash_prefix="012345abcdef",
        attempted_hash_prefix="abcdef012345",
    )

    message = str(ContractHashConflictError(context))

    assert "ContractHashConflictError" in message
    assert "experiment_runs" in message
    assert "record_experiment_run" in message
    assert "run_id" in message
    assert "run-001" in message
    assert "experiment_runs_pkey" in message
    assert "012345abcdef" in message
    assert "abcdef012345" in message


def test_error_messages_omit_absent_optional_context() -> None:
    context = PersistenceErrorContext(
        table_name="review_events",
        operation="append_review_event",
        logical_identity={"review_event_id": "review-event-001"},
    )

    message = str(DuplicateReviewEventError(context))

    assert "constraint_name=" not in message
    assert "existing_hash_prefix=" not in message
    assert "attempted_hash_prefix=" not in message


def test_replay_lookup_error_uses_safe_deterministic_context() -> None:
    context = PersistenceErrorContext(
        table_name="experiment_runs",
        operation="record_experiment_run",
        logical_identity={"run_id": "run-001"},
        constraint_name="pk_experiment_runs",
        attempted_hash_prefix="0123456789ab",
    )

    error = ReplayLookupError(context)
    message = str(error)

    assert error.context is context
    assert "ReplayLookupError" in message
    assert "table_name=experiment_runs" in message
    assert "operation=record_experiment_run" in message
    assert "logical_identity={run_id=run-001}" in message
    assert "constraint_name=pk_experiment_runs" in message
    assert "attempted_hash_prefix=0123456789ab" in message
    assert "existing_hash_prefix=" not in message


def test_error_messages_exclude_unsafe_sentinel_values() -> None:
    full_hash = "0" * 64
    context = PersistenceErrorContext(
        table_name="research_notes",
        operation="record_research_note",
        logical_identity={"note_id": "note-001"},
        existing_hash_prefix=full_hash[:12],
        attempted_hash_prefix="1" * 12,
    )

    message = str(ContractHashConflictError(context))

    for unsafe_value in (
        full_hash,
        "RAW_PAYLOAD_SENTINEL",
        "raw_contract",
        "raw_review",
        "password=secret-password",
        "credential=api-key",
        "secret-token",
        "SELECT * FROM experiment_runs",
        "postgresql://user:password@db.example.com/prod",
        "driver sentinel",
    ):
        assert unsafe_value not in message


def test_exception_chaining_remains_normal_python_behavior() -> None:
    context = valid_context()

    try:
        raise RuntimeError("driver sentinel")
    except RuntimeError as cause:
        try:
            raise ContractHashConflictError(context) from cause
        except ContractHashConflictError as error:
            assert error.__cause__ is cause
            assert "driver sentinel" not in str(error)


def test_error_types_export_from_errors_module() -> None:
    expected_exports = {
        "AggregateIntegrityError": AggregateIntegrityError,
        "ContractHashConflictError": ContractHashConflictError,
        "DuplicateReviewEventError": DuplicateReviewEventError,
        "NaturalKeyConflictError": NaturalKeyConflictError,
        "PersistenceConflictError": PersistenceConflictError,
        "PersistenceError": PersistenceError,
        "PersistenceErrorContext": PersistenceErrorContext,
        "ReplayLookupError": ReplayLookupError,
        "UnsupportedVersioningConflictError": UnsupportedVersioningConflictError,
    }

    assert set(errors.__all__) == set(expected_exports)
    for name, exported_type in expected_exports.items():
        assert getattr(errors, name) is exported_type


def test_error_types_export_from_persistence_package_as_canonical_classes() -> None:
    for name in errors.__all__:
        assert getattr(persistence, name) is getattr(errors, name)


def test_existing_result_and_protocol_exports_remain_unchanged() -> None:
    assert ExportedPersistedRecordMetadata is PersistedRecordMetadata
    assert ExportedPersistenceDisposition is PersistenceDisposition
    assert ExportedPersistenceWriteResult is PersistenceWriteResult
    assert ExportedExperimentLedgerRepository is ExperimentLedgerRepository


def test_errors_module_excludes_execution_driver_and_trading_scope() -> None:
    source = inspect.getsource(errors)
    source_without_domain_names = source.replace("AggregateIntegrityError", "")

    for prohibited_term in (
        "sqlalchemy",
        "alembic",
        "psycopg",
        "asyncpg",
        "create_engine",
        "Engine",
        "Session",
        "Connection",
        "IntegrityError",
        "OperationalError",
        "execute(",
        "on_conflict",
        "get_database_url",
        "repository implementation",
        "boto3",
        "requests",
        "Path(",
        "open(",
        "broker",
        "paper trading",
        "live trading",
    ):
        source_to_check = (
            source_without_domain_names
            if prohibited_term == "IntegrityError"
            else source
        )

        assert prohibited_term not in source_to_check
