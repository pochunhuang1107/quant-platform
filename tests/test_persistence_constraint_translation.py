from __future__ import annotations

import inspect

import pytest
from sqlalchemy import UniqueConstraint

import research_sdk.persistence as persistence
import research_sdk.persistence.constraint_translation as constraint_translation
from research_sdk.persistence import (
    translate_constraint_violation as package_translate_constraint_violation,
)
from research_sdk.persistence.constraint_translation import (
    translate_constraint_violation,
)
from research_sdk.persistence.errors import (
    AggregateIntegrityError,
    ContractHashConflictError,
    DuplicateReviewEventError,
    NaturalKeyConflictError,
    PersistenceConflictError,
    PersistenceErrorContext,
    UnsupportedVersioningConflictError,
)
from research_sdk.persistence.results import (
    PersistedRecordMetadata,
    PersistenceDisposition,
    PersistenceWriteResult,
)
from research_sdk.persistence.tables import review_events, run_artifact_manifests


def safe_context(
    *,
    constraint_name: str | None = None,
) -> PersistenceErrorContext:
    return PersistenceErrorContext(
        table_name="run_artifact_manifests",
        operation="record_run_artifact_manifest",
        logical_identity={"manifest_id": "manifest-001", "run_id": "run-001"},
        constraint_name=constraint_name,
        existing_hash_prefix="0abc",
        attempted_hash_prefix="1def",
    )


@pytest.mark.parametrize(
    ("constraint_name", "expected_error_type"),
    [
        (
            "uq_run_artifact_manifests_run_id",
            UnsupportedVersioningConflictError,
        ),
        ("pk_review_events", DuplicateReviewEventError),
    ],
)
def test_known_constraint_mappings_return_conflict_errors(
    constraint_name: str,
    expected_error_type: type[PersistenceConflictError],
) -> None:
    context = safe_context()

    error = translate_constraint_violation(
        constraint_name=constraint_name,
        context=context,
    )

    assert isinstance(error, expected_error_type)
    assert isinstance(error, PersistenceConflictError)
    assert error.context.constraint_name == constraint_name
    assert error.context.table_name == context.table_name
    assert error.context.operation == context.operation
    assert error.context.logical_identity == context.logical_identity
    assert error.context.existing_hash_prefix == context.existing_hash_prefix
    assert error.context.attempted_hash_prefix == context.attempted_hash_prefix


def test_context_without_constraint_name_is_copied_and_enriched() -> None:
    context = safe_context()

    error = translate_constraint_violation(
        constraint_name="uq_run_artifact_manifests_run_id",
        context=context,
    )

    assert error is not None
    assert error.context is not context
    assert context.constraint_name is None
    assert error.context.constraint_name == "uq_run_artifact_manifests_run_id"
    assert error.context.table_name == context.table_name
    assert error.context.operation == context.operation
    assert error.context.logical_identity == context.logical_identity
    assert error.context.existing_hash_prefix == context.existing_hash_prefix
    assert error.context.attempted_hash_prefix == context.attempted_hash_prefix


def test_matching_context_constraint_name_reuses_supplied_context() -> None:
    context = safe_context(constraint_name="pk_review_events")

    error = translate_constraint_violation(
        constraint_name="pk_review_events",
        context=context,
    )

    assert error is not None
    assert error.context is context


@pytest.mark.parametrize(
    "constraint_name",
    [
        "pk_review_events",
        "uq_unknown",
    ],
)
def test_mismatched_context_constraint_name_rejects_before_mapping(
    constraint_name: str,
) -> None:
    context = safe_context(constraint_name="different_constraint")

    with pytest.raises(
        ValueError,
        match="context constraint_name must match constraint_name",
    ):
        translate_constraint_violation(
            constraint_name=constraint_name,
            context=context,
        )


@pytest.mark.parametrize("constraint_name", ["", "   "])
def test_blank_constraint_name_rejects(constraint_name: str) -> None:
    with pytest.raises(ValueError, match="constraint_name must not be blank"):
        translate_constraint_violation(
            constraint_name=constraint_name,
            context=safe_context(),
        )


@pytest.mark.parametrize(
    "constraint_name",
    [
        "pk_experiment_runs",
        "pk_data_snapshot_manifests",
        "pk_research_notes",
        "pk_run_artifact_manifests",
        "pk_run_artifact_entries",
        "pk_unknown",
        "uq_unknown",
        "fk_unknown",
        "ck_unknown",
        "not_null_unknown",
    ],
)
def test_unknown_constraints_remain_untranslated(constraint_name: str) -> None:
    assert (
        translate_constraint_violation(
            constraint_name=constraint_name,
            context=safe_context(),
        )
        is None
    )


def test_unknown_unique_constraint_does_not_create_natural_key_conflict() -> None:
    error = translate_constraint_violation(
        constraint_name="uq_unknown",
        context=safe_context(),
    )

    assert error is None
    assert not isinstance(error, NaturalKeyConflictError)


def test_contract_hash_conflict_requires_replay_select_and_hash_comparison() -> None:
    for constraint_name in (
        "uq_run_artifact_manifests_run_id",
        "pk_review_events",
    ):
        error = translate_constraint_violation(
            constraint_name=constraint_name,
            context=safe_context(),
        )

        assert not isinstance(error, ContractHashConflictError)


def test_aggregate_integrity_error_requires_complete_aggregate_verification() -> None:
    for constraint_name in (
        "uq_run_artifact_manifests_run_id",
        "pk_review_events",
    ):
        error = translate_constraint_violation(
            constraint_name=constraint_name,
            context=safe_context(),
        )

        assert not isinstance(error, AggregateIntegrityError)


def test_translator_never_returns_success_result_vocabulary() -> None:
    for constraint_name in (
        "uq_run_artifact_manifests_run_id",
        "pk_review_events",
        "uq_unknown",
    ):
        error = translate_constraint_violation(
            constraint_name=constraint_name,
            context=safe_context(),
        )

        assert not isinstance(error, PersistenceWriteResult)
        assert not isinstance(error, PersistenceDisposition)
        assert not isinstance(error, PersistedRecordMetadata)
        assert error is not PersistenceDisposition.CREATED
        assert error is not PersistenceDisposition.REPLAYED


def test_metadata_constraint_names_match_translation_mapping() -> None:
    assert review_events.primary_key.name == "pk_review_events"

    unique_constraints = [
        constraint
        for constraint in run_artifact_manifests.constraints
        if isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_run_artifact_manifests_run_id"
    ]

    assert len(unique_constraints) == 1
    assert tuple(column.name for column in unique_constraints[0].columns) == ("run_id",)


def test_direct_module_and_package_exports_are_canonical() -> None:
    assert constraint_translation.translate_constraint_violation is (
        translate_constraint_violation
    )
    assert package_translate_constraint_violation is translate_constraint_violation
    assert persistence.translate_constraint_violation is translate_constraint_violation
    assert constraint_translation.__all__ == ["translate_constraint_violation"]
    assert not hasattr(persistence, "_CONSTRAINT_ERROR_TYPES")


def test_translation_module_excludes_driver_execution_and_trading_scope() -> None:
    source = inspect.getsource(constraint_translation)

    for prohibited_term in (
        "sqlalchemy",
        "alembic",
        "psycopg",
        "asyncpg",
        "IntegrityError",
        "UniqueViolation",
        "SQLSTATE",
        ".diag",
        ".orig",
        "create_engine",
        "Engine",
        "Session",
        "Connection",
        "execute(",
        "select(",
        "begin(",
        "commit(",
        "rollback(",
        "repository implementation",
        "retry",
        "logging",
        "boto3",
        "requests",
        "Path(",
        "open(",
        "broker",
        "paper trading",
        "live trading",
    ):
        assert prohibited_term not in source
