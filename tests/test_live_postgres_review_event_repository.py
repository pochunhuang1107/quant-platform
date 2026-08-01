from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Never

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from live_postgres_safety import (
    QUANT_RUN_LIVE_DB_TESTS_ENV_VAR,
    QUANT_TEST_DATABASE_URL_ENV_VAR,
    UnsafePostgresTestUrl,
    get_quant_test_database_url,
    should_run_live_db_tests,
    validate_safe_postgres_test_url,
)
from research_sdk.contracts import ReviewMetadata, RunArtifactManifest
from research_sdk.persistence.errors import DuplicateReviewEventError
from research_sdk.persistence.mappers import ReviewSubjectType
from research_sdk.persistence.results import (
    PersistenceDisposition,
    PersistenceWriteResult,
)
from research_sdk.persistence.sqlalchemy_repository import (
    SqlAlchemyExperimentLedgerRepository,
)
from research_sdk.persistence.tables import review_events

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "contracts"
TRANSACTION_REQUIRED_MESSAGE = (
    "repository write requires an active caller-owned transaction"
)
SCOPE_MESSAGE = "artifact repository execution is outside PR 36 review-event scope"


class _ReviewEventRepository(SqlAlchemyExperimentLedgerRepository):
    __slots__ = ()

    def record_run_artifact_manifest(
        self,
        *,
        manifest_id: str,
        manifest: RunArtifactManifest,
    ) -> PersistenceWriteResult:
        raise AssertionError(SCOPE_MESSAGE)


@pytest.fixture(scope="module")
def database_url() -> str:
    return _require_live_database_url()


@pytest.fixture(scope="module")
def migrated_engine(database_url: str) -> Engine:
    alembic_config = Config(str(ALEMBIC_INI))
    alembic_config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(alembic_config, "head")

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def review_metadata() -> ReviewMetadata:
    return ReviewMetadata.model_validate(_load_review_metadata_payload())


@pytest.mark.live_db
def test_append_review_event_requires_active_transaction(
    migrated_engine: Engine,
    review_metadata: ReviewMetadata,
) -> None:
    review_event_id = "review-event-pr36-transaction-required"

    with migrated_engine.connect() as connection:
        repository = _ReviewEventRepository(connection)

        assert connection.in_transaction() is False
        with pytest.raises(RuntimeError, match=TRANSACTION_REQUIRED_MESSAGE):
            repository.append_review_event(
                review_event_id=review_event_id,
                subject_type=ReviewSubjectType.EXPERIMENT_RUN,
                subject_id="run-pr36-transaction-required",
                review=review_metadata,
            )
        assert connection.in_transaction() is False

    assert _count_review_events(migrated_engine, review_event_id) == 0


@pytest.mark.live_db
def test_append_review_event_created_and_caller_rollback(
    migrated_engine: Engine,
    review_metadata: ReviewMetadata,
) -> None:
    review_event_id = "review-event-pr36-created"
    subject_id = "run-pr36-created"

    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            repository = _ReviewEventRepository(connection)

            created = repository.append_review_event(
                review_event_id=review_event_id,
                subject_type=ReviewSubjectType.EXPERIMENT_RUN,
                subject_id=subject_id,
                review=review_metadata,
            )

            assert created.disposition is PersistenceDisposition.CREATED
            assert created.record.table_name == "review_events"
            assert created.record.primary_key == {"review_event_id": review_event_id}
            assert created.record.contract_hash is None
            assert created.record.inserted_at is not None
            assert created.record.inserted_at.tzinfo is not None
            assert created.record.inserted_at.utcoffset() is not None
            assert created.aggregate_entry_count is None
            assert _count_review_events_in_connection(connection, review_event_id) == 1

            row = _stored_review_event_row(connection, review_event_id)
            assert row["inserted_at"] == created.record.inserted_at
            assert row["subject_type"] == ReviewSubjectType.EXPERIMENT_RUN.value
            assert row["subject_id"] == subject_id
            assert row["raw_review"] == review_metadata.model_dump(mode="json")
            assert row["review_status"] == review_metadata.review_status.value
            assert row["reviewer_id"] == review_metadata.reviewer_id
            assert row["review_role"] == review_metadata.review_role.value
            assert row["reviewed_at"] == review_metadata.reviewed_at
            assert row["decision"] == review_metadata.decision
            assert row["linked_pr"] == review_metadata.linked_pr
            assert row["review_notes_uri"] == review_metadata.review_notes_uri
        finally:
            transaction.rollback()

    assert _count_review_events(migrated_engine, review_event_id) == 0


@pytest.mark.live_db
def test_append_review_event_identical_duplicate_rejects_and_savepoint_recovers(
    migrated_engine: Engine,
    review_metadata: ReviewMetadata,
) -> None:
    review_event_id = "review-event-pr36-identical-duplicate"
    subject_id = "run-pr36-identical-duplicate"

    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            repository = _ReviewEventRepository(connection)
            repository.append_review_event(
                review_event_id=review_event_id,
                subject_type=ReviewSubjectType.EXPERIMENT_RUN,
                subject_id=subject_id,
                review=review_metadata,
            )
            original_row = _stored_review_event_row(connection, review_event_id)

            with pytest.raises(DuplicateReviewEventError) as exc_info:
                with connection.begin_nested():
                    repository.append_review_event(
                        review_event_id=review_event_id,
                        subject_type=ReviewSubjectType.EXPERIMENT_RUN,
                        subject_id=subject_id,
                        review=review_metadata,
                    )

            error = exc_info.value
            assert error.context.table_name == "review_events"
            assert error.context.operation == "append_review_event"
            assert error.context.logical_identity == {
                "review_event_id": review_event_id
            }
            assert error.context.constraint_name == "pk_review_events"
            assert error.context.existing_hash_prefix is None
            assert error.context.attempted_hash_prefix is None
            assert isinstance(error.__cause__, IntegrityError)
            assert subject_id not in str(error)
            assert review_metadata.review_notes_uri not in str(error)
            assert review_metadata.linked_pr not in str(error)
            assert connection.in_transaction() is True
            assert _count_review_events_in_connection(connection, review_event_id) == 1
            assert _stored_review_event_row(connection, review_event_id) == original_row
        finally:
            transaction.rollback()

    assert _count_review_events(migrated_engine, review_event_id) == 0


@pytest.mark.live_db
def test_append_review_event_changed_payload_duplicate_rejects_without_replay(
    migrated_engine: Engine,
    review_metadata: ReviewMetadata,
) -> None:
    review_event_id = "review-event-pr36-changed-duplicate"
    subject_id = "run-pr36-changed-duplicate"
    changed_subject_id = f"{subject_id}-changed"
    changed_review = ReviewMetadata.model_validate(
        {
            **review_metadata.model_dump(mode="json"),
            "decision": "Changed duplicate payload.",
        }
    )

    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            repository = _ReviewEventRepository(connection)
            repository.append_review_event(
                review_event_id=review_event_id,
                subject_type=ReviewSubjectType.EXPERIMENT_RUN,
                subject_id=subject_id,
                review=review_metadata,
            )
            original_row = _stored_review_event_row(connection, review_event_id)

            with pytest.raises(DuplicateReviewEventError) as exc_info:
                with connection.begin_nested():
                    repository.append_review_event(
                        review_event_id=review_event_id,
                        subject_type=ReviewSubjectType.RESEARCH_NOTE,
                        subject_id=changed_subject_id,
                        review=changed_review,
                    )

            error = exc_info.value
            assert type(error) is DuplicateReviewEventError
            assert "REPLAYED" not in str(error)
            assert connection.in_transaction() is True
            assert _count_review_events_in_connection(connection, review_event_id) == 1
            assert _stored_review_event_row(connection, review_event_id) == original_row
        finally:
            transaction.rollback()

    assert _count_review_events(migrated_engine, review_event_id) == 0


def _require_live_database_url() -> str:
    if not should_run_live_db_tests():
        pytest.skip(f"set {QUANT_RUN_LIVE_DB_TESTS_ENV_VAR}=1 to run live DB tests")

    database_url = get_quant_test_database_url()
    if database_url is None:
        pytest.skip(f"{QUANT_TEST_DATABASE_URL_ENV_VAR} is not set")

    try:
        return validate_safe_postgres_test_url(database_url)
    except UnsafePostgresTestUrl as exc:
        _fail_without_traceback(str(exc))


def _fail_without_traceback(message: str) -> Never:
    pytest.fail(message, pytrace=False)


def _load_review_metadata_payload() -> dict[str, Any]:
    return json.loads(
        (FIXTURE_DIR / "review_metadata.json").read_text(encoding="utf-8")
    )


def _count_review_events(engine: Engine, review_event_id: str) -> int:
    with engine.connect() as connection:
        with connection.begin():
            return _count_review_events_in_connection(connection, review_event_id)


def _count_review_events_in_connection(
    connection: Connection,
    review_event_id: str,
) -> int:
    statement = (
        select(func.count())
        .select_from(review_events)
        .where(review_events.c.review_event_id == review_event_id)
    )
    return connection.execute(statement).scalar_one()


def _stored_review_event_row(
    connection: Connection,
    review_event_id: str,
) -> dict[str, Any]:
    statement = select(review_events).where(
        review_events.c.review_event_id == review_event_id
    )
    return dict(connection.execute(statement).mappings().one())
