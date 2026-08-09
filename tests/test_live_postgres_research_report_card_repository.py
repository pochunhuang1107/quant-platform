from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Barrier
from typing import Never

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, event, func, select, text, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import NullPool

from backtest_engine import build_deterministic_etf_report_card
from live_postgres_safety import (
    QUANT_RUN_LIVE_DB_TESTS_ENV_VAR,
    QUANT_TEST_DATABASE_URL_ENV_VAR,
    UnsafePostgresTestUrl,
    get_quant_test_database_url,
    should_run_live_db_tests,
    validate_safe_postgres_test_url,
)
from research_sdk.contracts import ResearchReportCard
from research_sdk.experiment_recording import (
    CompletedExperimentRecordBundle,
    record_completed_experiment,
)
from research_sdk.persistence.errors import (
    ContractHashConflictError,
    PersistenceCorruptionError,
)
from research_sdk.persistence.hashing import contract_sha256
from research_sdk.persistence.results import (
    PersistenceDisposition,
    PersistenceWriteResult,
)
from research_sdk.persistence.sqlalchemy_repository import (
    SqlAlchemyExperimentLedgerRepository,
)
from research_sdk.persistence.tables import (
    data_snapshot_manifests,
    experiment_runs,
    research_report_cards,
    run_artifact_entries,
    run_artifact_manifests,
)
from research_sdk.report_card_identity import verify_research_report_card_identity
from test_live_postgres_backtest_engine_recording import build_bundle

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
BARRIER_TIMEOUT_SECONDS = 5.0
POSTGRES_STATEMENT_TIMEOUT_MS = 15_000
FUTURE_RESULT_TIMEOUT_SECONDS = 25.0


@dataclass(frozen=True)
class _WorkerSpec:
    label: str
    report_card: ResearchReportCard
    operation: Callable[
        [SqlAlchemyExperimentLedgerRepository],
        PersistenceWriteResult,
    ]


@dataclass(frozen=True)
class _WorkerOutcome:
    label: str
    report_card: ResearchReportCard
    result: PersistenceWriteResult | None = None
    error: Exception | None = None


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


@pytest.mark.live_db
def test_record_research_report_card_requires_active_transaction(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path, artifact_label="report-card-no-tx")
    report_card = _report_card_from_bundle(bundle)
    cleanup_bundles(migrated_engine, bundle)
    try:
        record_completed_experiment(
            bundle=bundle,
            transaction_factory=migrated_engine.begin,
        )
        with migrated_engine.connect() as connection:
            repository = SqlAlchemyExperimentLedgerRepository(connection)
            with pytest.raises(RuntimeError, match="active caller-owned transaction"):
                repository.record_research_report_card(report_card)
    finally:
        cleanup_bundles(migrated_engine, bundle)


@pytest.mark.live_db
def test_research_report_card_create_replay_conflict_and_readback(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path, artifact_label="report-card-crud")
    report_card = _report_card_from_bundle(bundle)
    conflicting = _report_card_with_non_source_content_change(report_card)
    cleanup_bundles(migrated_engine, bundle)
    try:
        record_completed_experiment(
            bundle=bundle,
            transaction_factory=migrated_engine.begin,
        )
        with migrated_engine.begin() as connection:
            repository = SqlAlchemyExperimentLedgerRepository(connection)
            created = repository.record_research_report_card(report_card)

        assert created.disposition is PersistenceDisposition.CREATED
        assert created.record.primary_key == {
            "report_card_id": report_card.report_card_id
        }
        assert created.record.contract_hash == contract_sha256(report_card)

        with migrated_engine.connect() as connection:
            repository = SqlAlchemyExperimentLedgerRepository(connection)
            loaded = repository.get_research_report_card(report_card.report_card_id)

        assert loaded == report_card
        verify_research_report_card_identity(loaded)

        with migrated_engine.begin() as connection:
            repository = SqlAlchemyExperimentLedgerRepository(connection)
            replayed = repository.record_research_report_card(report_card)

        assert replayed.disposition is PersistenceDisposition.REPLAYED
        assert replayed.record.primary_key == created.record.primary_key
        assert replayed.record.contract_hash == created.record.contract_hash
        assert _report_card_count(migrated_engine, report_card.report_card_id) == 1

        with pytest.raises(ContractHashConflictError) as exc_info:
            with migrated_engine.begin() as connection:
                repository = SqlAlchemyExperimentLedgerRepository(connection)
                repository.record_research_report_card(conflicting)

        error = exc_info.value
        assert error.context.table_name == "research_report_cards"
        assert error.context.operation == "record_research_report_card"
        assert error.context.logical_identity == {
            "report_card_id": report_card.report_card_id
        }
        assert error.context.constraint_name == "pk_research_report_cards"
        assert _stored_contract_hash(migrated_engine, report_card.report_card_id) == (
            contract_sha256(report_card)
        )
    finally:
        cleanup_bundles(migrated_engine, bundle)


@pytest.mark.live_db
def test_get_research_report_card_rejects_corrupt_durable_state(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path, artifact_label="report-card-corrupt")
    report_card = _report_card_from_bundle(bundle)
    cleanup_bundles(migrated_engine, bundle)
    try:
        record_completed_experiment(
            bundle=bundle,
            transaction_factory=migrated_engine.begin,
        )
        with migrated_engine.begin() as connection:
            repository = SqlAlchemyExperimentLedgerRepository(connection)
            repository.record_research_report_card(report_card)

        with migrated_engine.begin() as connection:
            connection.execute(
                update(research_report_cards)
                .where(
                    research_report_cards.c.report_card_id == report_card.report_card_id
                )
                .values(contract_hash="0" * 64)
            )
        with pytest.raises(PersistenceCorruptionError):
            with migrated_engine.connect() as connection:
                repository = SqlAlchemyExperimentLedgerRepository(connection)
                repository.get_research_report_card(report_card.report_card_id)
    finally:
        cleanup_bundles(migrated_engine, bundle)


@pytest.mark.live_db
def test_get_research_report_card_rejects_normalized_column_mismatch(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path, artifact_label="report-card-mismatch")
    report_card = _report_card_from_bundle(bundle)
    cleanup_bundles(migrated_engine, bundle)
    try:
        record_completed_experiment(
            bundle=bundle,
            transaction_factory=migrated_engine.begin,
        )
        with migrated_engine.begin() as connection:
            repository = SqlAlchemyExperimentLedgerRepository(connection)
            repository.record_research_report_card(report_card)
            connection.execute(
                update(research_report_cards)
                .where(
                    research_report_cards.c.report_card_id == report_card.report_card_id
                )
                .values(strategy_id="changed-strategy")
            )

        with pytest.raises(PersistenceCorruptionError):
            with migrated_engine.connect() as connection:
                repository = SqlAlchemyExperimentLedgerRepository(connection)
                repository.get_research_report_card(report_card.report_card_id)
    finally:
        cleanup_bundles(migrated_engine, bundle)


@pytest.mark.live_db
def test_concurrent_identical_research_report_card_replays(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path, artifact_label="report-card-race-identical")
    report_card = _report_card_from_bundle(bundle)
    cleanup_bundles(migrated_engine, bundle)
    try:
        record_completed_experiment(
            bundle=bundle,
            transaction_factory=migrated_engine.begin,
        )
        outcomes = _run_two_worker_race(
            engine=migrated_engine,
            left=_report_card_spec(label="left", report_card=report_card),
            right=_report_card_spec(label="right", report_card=report_card),
            expected_error_types=(),
        )

        created = _single_created(outcomes)
        replayed = _single_replayed(outcomes)
        assert _errors(outcomes) == []
        assert created.result is not None
        assert replayed.result is not None
        assert replayed.result.record.primary_key == created.result.record.primary_key
        assert (
            replayed.result.record.contract_hash == created.result.record.contract_hash
        )
        assert _report_card_count(migrated_engine, report_card.report_card_id) == 1
    finally:
        cleanup_bundles(migrated_engine, bundle)


@pytest.mark.live_db
def test_concurrent_conflicting_research_report_card_rejects_loser(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path, artifact_label="report-card-race-conflict")
    report_card = _report_card_from_bundle(bundle)
    conflicting = _report_card_with_non_source_content_change(report_card)
    cleanup_bundles(migrated_engine, bundle)
    try:
        record_completed_experiment(
            bundle=bundle,
            transaction_factory=migrated_engine.begin,
        )
        outcomes = _run_two_worker_race(
            engine=migrated_engine,
            left=_report_card_spec(label="original", report_card=report_card),
            right=_report_card_spec(label="conflicting", report_card=conflicting),
            expected_error_types=(ContractHashConflictError,),
        )

        created = _single_created(outcomes)
        conflict = _single_error(outcomes, ContractHashConflictError)
        assert isinstance(conflict.error, ContractHashConflictError)
        assert conflict.error.context.table_name == "research_report_cards"
        assert conflict.error.context.operation == "record_research_report_card"
        assert conflict.error.context.logical_identity == {
            "report_card_id": report_card.report_card_id
        }
        assert conflict.error.context.constraint_name == "pk_research_report_cards"
        assert created.result is not None
        assert _report_card_count(migrated_engine, report_card.report_card_id) == 1
        assert _stored_contract_hash(migrated_engine, report_card.report_card_id) in {
            contract_sha256(report_card),
            contract_sha256(conflicting),
        }
    finally:
        cleanup_bundles(migrated_engine, bundle)


@pytest.mark.live_db
def test_fixture_to_durable_research_report_card_vertical_integration(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path, artifact_label="report-card-vertical")
    cleanup_bundles(migrated_engine, bundle)
    try:
        record_completed_experiment(
            bundle=bundle,
            transaction_factory=migrated_engine.begin,
        )
        report_card = _report_card_from_bundle(bundle)
        verify_research_report_card_identity(report_card)

        with migrated_engine.begin() as connection:
            repository = SqlAlchemyExperimentLedgerRepository(connection)
            result = repository.record_research_report_card(report_card)

        assert result.disposition is PersistenceDisposition.CREATED

        with migrated_engine.connect() as connection:
            repository = SqlAlchemyExperimentLedgerRepository(connection)
            loaded = repository.get_research_report_card(report_card.report_card_id)

        assert loaded == report_card
        verify_research_report_card_identity(loaded)

        with migrated_engine.begin() as connection:
            repository = SqlAlchemyExperimentLedgerRepository(connection)
            replayed = repository.record_research_report_card(report_card)

        assert replayed.disposition is PersistenceDisposition.REPLAYED
        assert _report_card_count(migrated_engine, report_card.report_card_id) == 1

        conflicting = _report_card_with_non_source_content_change(report_card)
        with pytest.raises(ContractHashConflictError):
            with migrated_engine.begin() as connection:
                repository = SqlAlchemyExperimentLedgerRepository(connection)
                repository.record_research_report_card(conflicting)

        assert _stored_contract_hash(migrated_engine, report_card.report_card_id) == (
            contract_sha256(report_card)
        )
    finally:
        cleanup_bundles(migrated_engine, bundle)


def _report_card_from_bundle(
    bundle: CompletedExperimentRecordBundle,
) -> ResearchReportCard:
    return build_deterministic_etf_report_card(
        run=bundle.run,
        data_snapshot=bundle.snapshot,
        benchmark_snapshot=bundle.snapshot,
        artifact_manifest_id=bundle.manifest_id,
        artifact_manifest=bundle.artifact_manifest,
    )


def _report_card_with_non_source_content_change(
    report_card: ResearchReportCard,
) -> ResearchReportCard:
    return report_card.model_copy(
        update={"use_restrictions": report_card.use_restrictions[:-1]}
    )


def _run_two_worker_race(
    *,
    engine: Engine,
    left: _WorkerSpec,
    right: _WorkerSpec,
    expected_error_types: tuple[type[Exception], ...],
) -> tuple[_WorkerOutcome, _WorkerOutcome]:
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(_run_worker, engine, barrier, left, expected_error_types),
            executor.submit(_run_worker, engine, barrier, right, expected_error_types),
        )
        return tuple(
            future.result(timeout=FUTURE_RESULT_TIMEOUT_SECONDS) for future in futures
        )


def _run_worker(
    engine: Engine,
    barrier: Barrier,
    spec: _WorkerSpec,
    expected_error_types: tuple[type[Exception], ...],
) -> _WorkerOutcome:
    with engine.connect() as base_connection:
        connection = base_connection.execution_options(isolation_level="READ COMMITTED")
        transaction = connection.begin()
        connection.execute(
            text(f"SET LOCAL statement_timeout = {POSTGRES_STATEMENT_TIMEOUT_MS}")
        )
        listener = _install_first_repository_sql_barrier(connection, barrier)
        try:
            repository = SqlAlchemyExperimentLedgerRepository(connection)
            result = spec.operation(repository)
        except Exception as error:
            if transaction.is_active:
                transaction.rollback()
            if expected_error_types and isinstance(error, expected_error_types):
                return _WorkerOutcome(
                    label=spec.label,
                    report_card=spec.report_card,
                    error=error,
                )
            raise
        else:
            if result.disposition is PersistenceDisposition.CREATED:
                transaction.commit()
            else:
                transaction.rollback()
            return _WorkerOutcome(
                label=spec.label,
                report_card=spec.report_card,
                result=result,
            )
        finally:
            event.remove(connection, "before_cursor_execute", listener)


def _install_first_repository_sql_barrier(
    connection: Connection,
    barrier: Barrier,
) -> Callable[..., None]:
    has_waited = False

    def _before_cursor_execute(*_: object) -> None:
        nonlocal has_waited
        if has_waited:
            return
        has_waited = True
        barrier.wait(timeout=BARRIER_TIMEOUT_SECONDS)

    event.listen(connection, "before_cursor_execute", _before_cursor_execute)
    return _before_cursor_execute


def _report_card_spec(
    *,
    label: str,
    report_card: ResearchReportCard,
) -> _WorkerSpec:
    return _WorkerSpec(
        label=label,
        report_card=report_card,
        operation=lambda repository: repository.record_research_report_card(
            report_card
        ),
    )


def _single_created(
    outcomes: tuple[_WorkerOutcome, _WorkerOutcome],
) -> _WorkerOutcome:
    created = [
        outcome
        for outcome in outcomes
        if outcome.result is not None
        and outcome.result.disposition is PersistenceDisposition.CREATED
    ]
    assert len(created) == 1
    return created[0]


def _single_replayed(
    outcomes: tuple[_WorkerOutcome, _WorkerOutcome],
) -> _WorkerOutcome:
    replayed = [
        outcome
        for outcome in outcomes
        if outcome.result is not None
        and outcome.result.disposition is PersistenceDisposition.REPLAYED
    ]
    assert len(replayed) == 1
    return replayed[0]


def _single_error(
    outcomes: tuple[_WorkerOutcome, _WorkerOutcome],
    error_type: type[Exception],
) -> _WorkerOutcome:
    errors = [
        outcome
        for outcome in outcomes
        if outcome.error is not None and type(outcome.error) is error_type
    ]
    assert len(errors) == 1
    return errors[0]


def _errors(outcomes: tuple[_WorkerOutcome, _WorkerOutcome]) -> list[Exception]:
    return [outcome.error for outcome in outcomes if outcome.error is not None]


def _report_card_count(engine: Engine, report_card_id: str) -> int:
    with engine.connect() as connection:
        with connection.begin():
            return connection.execute(
                select(func.count())
                .select_from(research_report_cards)
                .where(research_report_cards.c.report_card_id == report_card_id)
            ).scalar_one()


def _stored_contract_hash(engine: Engine, report_card_id: str) -> str:
    with engine.connect() as connection:
        with connection.begin():
            return connection.execute(
                select(research_report_cards.c.contract_hash).where(
                    research_report_cards.c.report_card_id == report_card_id
                )
            ).scalar_one()


def cleanup_bundles(
    engine: Engine,
    *bundles: CompletedExperimentRecordBundle,
) -> None:
    report_card_ids = sorted(
        {_report_card_from_bundle(bundle).report_card_id for bundle in bundles}
    )
    manifest_ids = sorted({bundle.manifest_id for bundle in bundles})
    run_ids = sorted({bundle.run.run_id for bundle in bundles})
    snapshot_ids = sorted({bundle.snapshot.snapshot_id for bundle in bundles})
    with engine.begin() as connection:
        if report_card_ids:
            connection.execute(
                delete(research_report_cards).where(
                    research_report_cards.c.report_card_id.in_(report_card_ids)
                )
            )
        if manifest_ids:
            connection.execute(
                delete(run_artifact_entries).where(
                    run_artifact_entries.c.manifest_id.in_(manifest_ids)
                )
            )
            connection.execute(
                delete(run_artifact_manifests).where(
                    run_artifact_manifests.c.manifest_id.in_(manifest_ids)
                )
            )
        if run_ids:
            connection.execute(
                delete(experiment_runs).where(experiment_runs.c.run_id.in_(run_ids))
            )
        if snapshot_ids:
            connection.execute(
                delete(data_snapshot_manifests).where(
                    data_snapshot_manifests.c.snapshot_id.in_(snapshot_ids)
                )
            )


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
