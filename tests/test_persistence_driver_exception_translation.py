from __future__ import annotations

import inspect
from dataclasses import fields
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

import research_sdk.persistence as persistence
import research_sdk.persistence.driver_exception_translation as driver_translation
from research_sdk.persistence import (
    translate_sqlalchemy_integrity_error as package_translate,
)
from research_sdk.persistence.driver_exception_translation import (
    translate_sqlalchemy_integrity_error,
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

SQL_SENTINEL = "SQL_SENTINEL_pk_review_events"
PARAM_SENTINEL = "PARAM_SENTINEL_uq_run_artifact_manifests_run_id"
DRIVER_SENTINEL = "DRIVER_SENTINEL_pk_review_events"
_DEFAULT_DIAG = object()


class FakeDiagnostic:
    def __init__(
        self,
        *,
        constraint_name: object = "pk_review_events",
        include_constraint_name: bool = True,
    ) -> None:
        if include_constraint_name:
            self.constraint_name = constraint_name


class FakeOrig(Exception):
    def __init__(
        self,
        message: str = DRIVER_SENTINEL,
        *,
        sqlstate: object = "23505",
        diag: object = None,
        include_sqlstate: bool = True,
        include_diag: bool = True,
    ) -> None:
        super().__init__(message)
        if include_sqlstate:
            self.sqlstate = sqlstate
        if include_diag:
            self.diag = diag


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


def integrity_error(
    *,
    sqlstate: object = "23505",
    constraint_name: object = "pk_review_events",
    include_sqlstate: bool = True,
    include_diag: bool = True,
    include_constraint_name: bool = True,
    diag: object = _DEFAULT_DIAG,
    message: str = DRIVER_SENTINEL,
) -> IntegrityError:
    if diag is _DEFAULT_DIAG and include_diag:
        diag = FakeDiagnostic(
            constraint_name=constraint_name,
            include_constraint_name=include_constraint_name,
        )

    orig = FakeOrig(
        message,
        sqlstate=sqlstate,
        diag=diag,
        include_sqlstate=include_sqlstate,
        include_diag=include_diag,
    )
    return IntegrityError(SQL_SENTINEL, {"secret": PARAM_SENTINEL}, orig)


@pytest.mark.parametrize(
    ("constraint_name", "expected_error_type"),
    [
        ("pk_review_events", DuplicateReviewEventError),
        (
            "uq_run_artifact_manifests_run_id",
            UnsupportedVersioningConflictError,
        ),
    ],
)
def test_known_unique_constraint_mappings_return_conflict_errors(
    constraint_name: str,
    expected_error_type: type[PersistenceConflictError],
) -> None:
    context = safe_context()
    database_error = integrity_error(constraint_name=constraint_name)

    result = translate_sqlalchemy_integrity_error(
        error=database_error,
        context=context,
    )

    assert isinstance(result, expected_error_type)
    assert isinstance(result, PersistenceConflictError)
    assert result.context.constraint_name == constraint_name
    assert result.context.table_name == context.table_name
    assert result.context.operation == context.operation
    assert result.context.logical_identity == context.logical_identity
    assert result.context.existing_hash_prefix == context.existing_hash_prefix
    assert result.context.attempted_hash_prefix == context.attempted_hash_prefix
    assert all(value is not database_error for value in vars(result).values())
    assert result.__cause__ is None
    assert result.__context__ is None


def test_translated_error_excludes_sql_params_and_driver_message_sentinels() -> None:
    result = translate_sqlalchemy_integrity_error(
        error=integrity_error(constraint_name="pk_review_events"),
        context=safe_context(),
    )

    assert result is not None
    context = result.context
    context_values = [
        getattr(context, field.name) for field in fields(PersistenceErrorContext)
    ]
    context_identity_values = list(context.logical_identity.values())

    for sentinel in (SQL_SENTINEL, PARAM_SENTINEL, DRIVER_SENTINEL):
        assert sentinel not in str(result)
        assert sentinel not in repr(context)
        assert sentinel not in context.logical_identity
        assert sentinel not in context_identity_values
        assert all(value != sentinel for value in context_values)


@pytest.mark.parametrize(
    "constraint_name",
    [
        "uq_unknown",
        "pk_unknown",
        "fk_unknown",
        "ck_unknown",
    ],
)
def test_unknown_unique_constraints_remain_untranslated(
    constraint_name: str,
) -> None:
    result = translate_sqlalchemy_integrity_error(
        error=integrity_error(constraint_name=constraint_name),
        context=safe_context(),
    )

    assert result is None
    assert not isinstance(result, NaturalKeyConflictError)


@pytest.mark.parametrize(
    "sqlstate",
    [
        "23502",
        "23503",
        "23514",
        "40001",
        "40P01",
        "99999",
        "",
        None,
        23505,
        object(),
    ],
)
def test_non_unique_or_malformed_sqlstate_returns_none(sqlstate: object) -> None:
    assert (
        translate_sqlalchemy_integrity_error(
            error=integrity_error(
                sqlstate=sqlstate,
                constraint_name="pk_review_events",
            ),
            context=safe_context(),
        )
        is None
    )


@pytest.mark.parametrize(
    "database_error",
    [
        integrity_error(include_sqlstate=False),
        integrity_error(sqlstate=None),
        integrity_error(sqlstate=23505),
        integrity_error(include_diag=False),
        integrity_error(diag=None),
        integrity_error(include_constraint_name=False),
        integrity_error(constraint_name=None),
        integrity_error(constraint_name=object()),
        integrity_error(constraint_name=""),
        integrity_error(constraint_name="   "),
    ],
)
def test_missing_or_malformed_diagnostics_return_none(
    database_error: IntegrityError,
) -> None:
    assert (
        translate_sqlalchemy_integrity_error(
            error=database_error,
            context=safe_context(),
        )
        is None
    )


@pytest.mark.parametrize(
    "database_error",
    [
        IntegrityError(
            "SELECT 1 /* pk_review_events */",
            {"constraint": "uq_run_artifact_manifests_run_id"},
            FakeOrig("driver text pk_review_events", include_diag=False),
        ),
        IntegrityError(
            "SELECT 1 /* pk_review_events */",
            {"constraint": "uq_run_artifact_manifests_run_id"},
            FakeOrig(
                "driver text pk_review_events",
                sqlstate="23503",
                diag=FakeDiagnostic(constraint_name="uq_run_artifact_manifests_run_id"),
            ),
        ),
        IntegrityError(
            "SELECT 1 /* pk_review_events */",
            {"constraint": "uq_run_artifact_manifests_run_id"},
            FakeOrig(
                "driver text pk_review_events",
                sqlstate="23505",
                diag=FakeDiagnostic(constraint_name="uq_unknown"),
            ),
        ),
    ],
)
def test_adapter_does_not_parse_statement_params_or_driver_messages(
    database_error: IntegrityError,
) -> None:
    assert (
        translate_sqlalchemy_integrity_error(
            error=database_error,
            context=safe_context(),
        )
        is None
    )


def test_nonblank_constraint_name_is_not_normalized() -> None:
    assert (
        translate_sqlalchemy_integrity_error(
            error=integrity_error(constraint_name=" pk_review_events "),
            context=safe_context(),
        )
        is None
    )


def test_context_without_constraint_name_is_copied_and_enriched() -> None:
    context = safe_context()

    result = translate_sqlalchemy_integrity_error(
        error=integrity_error(constraint_name="pk_review_events"),
        context=context,
    )

    assert result is not None
    assert result.context is not context
    assert context.constraint_name is None
    assert result.context.constraint_name == "pk_review_events"


def test_matching_context_constraint_name_reuses_supplied_context() -> None:
    context = safe_context(constraint_name="pk_review_events")

    result = translate_sqlalchemy_integrity_error(
        error=integrity_error(constraint_name="pk_review_events"),
        context=context,
    )

    assert result is not None
    assert result.context is context


def test_mismatched_context_constraint_name_propagates_translator_value_error() -> None:
    with pytest.raises(
        ValueError,
        match="context constraint_name must match constraint_name",
    ):
        translate_sqlalchemy_integrity_error(
            error=integrity_error(constraint_name="pk_review_events"),
            context=safe_context(constraint_name="different_constraint"),
        )


def test_non_unique_sqlstate_does_not_validate_mismatched_context() -> None:
    assert (
        translate_sqlalchemy_integrity_error(
            error=integrity_error(
                sqlstate="23503",
                constraint_name="pk_review_events",
            ),
            context=safe_context(constraint_name="different_constraint"),
        )
        is None
    )


def test_successful_translations_stay_separate_from_other_error_and_result_types() -> (
    None
):
    for constraint_name in (
        "pk_review_events",
        "uq_run_artifact_manifests_run_id",
    ):
        result = translate_sqlalchemy_integrity_error(
            error=integrity_error(constraint_name=constraint_name),
            context=safe_context(),
        )

        assert not isinstance(result, ContractHashConflictError)
        assert not isinstance(result, AggregateIntegrityError)
        assert not isinstance(result, PersistenceWriteResult)
        assert not isinstance(result, PersistedRecordMetadata)
        assert not isinstance(result, PersistenceDisposition)
        assert result is not PersistenceDisposition.CREATED
        assert result is not PersistenceDisposition.REPLAYED


def test_direct_module_and_package_exports_are_canonical() -> None:
    assert driver_translation.translate_sqlalchemy_integrity_error is (
        translate_sqlalchemy_integrity_error
    )
    assert package_translate is translate_sqlalchemy_integrity_error
    assert persistence.translate_sqlalchemy_integrity_error is (
        translate_sqlalchemy_integrity_error
    )
    assert driver_translation.__all__ == ["translate_sqlalchemy_integrity_error"]
    assert not hasattr(persistence, "_UNIQUE_VIOLATION_SQLSTATE")
    assert not hasattr(persistence, "_extract_psycopg_unique_constraint_name")


def test_driver_translation_module_excludes_execution_driver_and_trading_scope() -> (
    None
):
    source = inspect.getsource(driver_translation)

    for prohibited_term in (
        "import psycopg",
        "from psycopg",
        "asyncpg",
        "alembic",
        "create_engine",
        "Engine",
        "Session",
        "Connection",
        "execute(",
        "select(",
        "cursor",
        "begin(",
        "commit(",
        "rollback(",
        "pgcode",
        "diag.sqlstate",
        "error.code",
        "__cause__",
        "__context__",
        "regex",
        "re.compile",
        "repository implementation",
        "ExperimentLedgerRepository",
        "PersistenceWriteResult(",
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


def test_fake_diagnostics_do_not_import_real_database_driver_types() -> None:
    module_names: dict[str, Any] = vars(driver_translation)

    assert "psycopg" not in module_names
    assert "asyncpg" not in module_names
