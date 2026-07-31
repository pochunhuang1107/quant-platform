from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Never

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import NullPool

from live_postgres_safety import (
    QUANT_RUN_LIVE_DB_TESTS_ENV_VAR,
    QUANT_TEST_DATABASE_URL_ENV_VAR,
    UnsafePostgresTestUrl,
    get_quant_test_database_url,
    should_run_live_db_tests,
    validate_safe_postgres_test_url,
)
from research_sdk.contracts import (
    DataSnapshotManifest,
    ExperimentRunRecord,
    ResearchNote,
    ReviewMetadata,
    RunArtifactManifest,
)
from research_sdk.persistence.errors import ContractHashConflictError
from research_sdk.persistence.hashing import contract_sha256
from research_sdk.persistence.mappers import ReviewSubjectType
from research_sdk.persistence.results import (
    PersistenceDisposition,
    PersistenceWriteResult,
)
from research_sdk.persistence.sqlalchemy_repository import (
    SqlAlchemyExperimentLedgerRepository,
)
from research_sdk.persistence.tables import experiment_runs

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "contracts"
TRANSACTION_REQUIRED_MESSAGE = (
    "repository write requires an active caller-owned transaction"
)
SCOPE_MESSAGE = "repository execution is outside PR 33 experiment-run scope"


class _ExperimentRunOnlyRepository(SqlAlchemyExperimentLedgerRepository):
    __slots__ = ()

    def record_data_snapshot_manifest(
        self,
        snapshot: DataSnapshotManifest,
    ) -> PersistenceWriteResult:
        raise AssertionError(SCOPE_MESSAGE)

    def record_run_artifact_manifest(
        self,
        *,
        manifest_id: str,
        manifest: RunArtifactManifest,
    ) -> PersistenceWriteResult:
        raise AssertionError(SCOPE_MESSAGE)

    def record_research_note(
        self,
        note: ResearchNote,
    ) -> PersistenceWriteResult:
        raise AssertionError(SCOPE_MESSAGE)

    def append_review_event(
        self,
        *,
        review_event_id: str,
        subject_type: ReviewSubjectType | str,
        subject_id: str,
        review: ReviewMetadata,
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
def experiment_run() -> ExperimentRunRecord:
    return _experiment_run_with(run_id="run-pr33-live-vertical-slice")


@pytest.mark.live_db
def test_record_experiment_run_requires_active_transaction(
    migrated_engine: Engine,
) -> None:
    run = _experiment_run_with(run_id="run-pr33-live-transaction-required")

    with migrated_engine.connect() as connection:
        repository = _ExperimentRunOnlyRepository(connection)

        assert connection.in_transaction() is False
        with pytest.raises(RuntimeError, match=TRANSACTION_REQUIRED_MESSAGE):
            repository.record_experiment_run(run)
        assert connection.in_transaction() is False

    assert _count_experiment_runs(migrated_engine, run.run_id) == 0


@pytest.mark.live_db
def test_record_experiment_run_created_replayed_conflict_and_caller_rollback(
    migrated_engine: Engine,
    experiment_run: ExperimentRunRecord,
) -> None:
    conflicting_run = experiment_run.model_copy(update={"strategy_version": "0.1.1"})
    original_hash = contract_sha256(experiment_run)
    conflicting_hash = contract_sha256(conflicting_run)

    assert conflicting_run.run_id == experiment_run.run_id
    assert conflicting_hash != original_hash

    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            repository = _ExperimentRunOnlyRepository(connection)

            created = repository.record_experiment_run(experiment_run)
            assert created.disposition is PersistenceDisposition.CREATED
            assert created.record.table_name == "experiment_runs"
            assert created.record.primary_key == {"run_id": experiment_run.run_id}
            assert created.record.contract_hash == original_hash
            assert created.record.inserted_at is not None
            assert created.record.inserted_at.tzinfo is not None
            assert created.record.inserted_at.utcoffset() is not None
            assert created.aggregate_entry_count is None
            assert (
                _count_experiment_runs_in_connection(
                    connection,
                    experiment_run.run_id,
                )
                == 1
            )

            original_inserted_at = created.record.inserted_at
            original_raw_contract = _stored_raw_contract(
                connection,
                experiment_run.run_id,
            )

            replayed = repository.record_experiment_run(experiment_run)
            assert replayed.disposition is PersistenceDisposition.REPLAYED
            assert replayed.record.primary_key == {"run_id": experiment_run.run_id}
            assert replayed.record.contract_hash == original_hash
            assert replayed.record.inserted_at == original_inserted_at
            assert replayed.aggregate_entry_count is None
            assert (
                _count_experiment_runs_in_connection(
                    connection,
                    experiment_run.run_id,
                )
                == 1
            )
            assert _stored_raw_contract(connection, experiment_run.run_id) == (
                original_raw_contract
            )

            with pytest.raises(ContractHashConflictError) as exc_info:
                repository.record_experiment_run(conflicting_run)

            error = exc_info.value
            assert error.context.table_name == "experiment_runs"
            assert error.context.operation == "record_experiment_run"
            assert error.context.logical_identity == {"run_id": experiment_run.run_id}
            assert error.context.constraint_name == "pk_experiment_runs"
            assert error.context.existing_hash_prefix == original_hash[:12]
            assert error.context.attempted_hash_prefix == conflicting_hash[:12]
            assert original_hash not in str(error)
            assert conflicting_hash not in str(error)
            assert "raw_contract" not in str(error)
            assert connection.in_transaction() is True
            assert (
                _count_experiment_runs_in_connection(
                    connection,
                    experiment_run.run_id,
                )
                == 1
            )
            assert _stored_contract_hash(connection, experiment_run.run_id) == (
                original_hash
            )
            assert _stored_raw_contract(connection, experiment_run.run_id) == (
                original_raw_contract
            )
            assert _stored_inserted_at(connection, experiment_run.run_id) == (
                original_inserted_at
            )
        finally:
            transaction.rollback()

    assert _count_experiment_runs(migrated_engine, experiment_run.run_id) == 0


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


def _load_experiment_run_payload() -> dict[str, Any]:
    return json.loads(
        (FIXTURE_DIR / "experiment_run_record.json").read_text(encoding="utf-8")
    )


def _experiment_run_with(*, run_id: str) -> ExperimentRunRecord:
    run = ExperimentRunRecord.model_validate(_load_experiment_run_payload())
    return run.model_copy(update={"run_id": run_id})


def _count_experiment_runs(engine: Engine, run_id: str) -> int:
    with engine.connect() as connection:
        with connection.begin():
            return _count_experiment_runs_in_connection(connection, run_id)


def _count_experiment_runs_in_connection(
    connection: Connection,
    run_id: str,
) -> int:
    statement = (
        select(func.count())
        .select_from(experiment_runs)
        .where(experiment_runs.c.run_id == run_id)
    )
    return connection.execute(statement).scalar_one()


def _stored_contract_hash(connection: Connection, run_id: str) -> str:
    statement = select(experiment_runs.c.contract_hash).where(
        experiment_runs.c.run_id == run_id
    )
    return connection.execute(statement).scalar_one()


def _stored_raw_contract(connection: Connection, run_id: str) -> dict[str, Any]:
    statement = select(experiment_runs.c.raw_contract).where(
        experiment_runs.c.run_id == run_id
    )
    return connection.execute(statement).scalar_one()


def _stored_inserted_at(connection: Connection, run_id: str) -> object:
    statement = select(experiment_runs.c.inserted_at).where(
        experiment_runs.c.run_id == run_id
    )
    return connection.execute(statement).scalar_one()
