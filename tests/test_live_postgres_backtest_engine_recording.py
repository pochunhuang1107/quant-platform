from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Never

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from backtest_engine import (
    ENGINE_VERSION,
    BasisPointAssumption,
    CompletedBacktestLedgerMappingInput,
    CompletedEconomicBacktestLedgerMappingInput,
    ExecutionMetadata,
    ResolvedBacktestConfig,
    generate_artifact_bundle,
    generate_economic_artifact_bundle,
    load_daily_bar_snapshot,
    map_completed_backtest_to_ledger_records,
    map_completed_economic_backtest_to_ledger_records,
    run_buy_and_hold_backtest,
    run_snapshot_v2_buy_and_hold_backtest,
)
from helpers_backtest_engine_economic import (
    compatible_profile as economic_compatible_profile,
)
from helpers_backtest_engine_economic import (
    execution_metadata as economic_execution_metadata,
)
from helpers_backtest_engine_economic import qqq_bundle_files, spy_bundle_files
from helpers_backtest_engine_economic import (
    resolved_config as economic_resolved_config,
)
from live_postgres_safety import (
    QUANT_RUN_LIVE_DB_TESTS_ENV_VAR,
    QUANT_TEST_DATABASE_URL_ENV_VAR,
    UnsafePostgresTestUrl,
    get_quant_test_database_url,
    should_run_live_db_tests,
    validate_safe_postgres_test_url,
)
from research_sdk.contracts import (
    ReviewMetadata,
    ReviewStatus,
)
from research_sdk.experiment_recording import (
    CompletedExperimentPairRecordBundle,
    CompletedExperimentRecordBundle,
    record_completed_experiment,
    record_completed_experiment_pair,
)
from research_sdk.persistence.errors import ContractHashConflictError
from research_sdk.persistence.results import PersistenceDisposition
from research_sdk.persistence.sqlalchemy_repository import (
    SqlAlchemyExperimentLedgerRepository,
)
from research_sdk.persistence.tables import (
    data_snapshot_manifests,
    experiment_runs,
    run_artifact_entries,
    run_artifact_manifests,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
FIXTURE_PATH = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "backtest_engine"
    / ("synthetic_daily_etf_bars.json")
)


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
def test_completed_backtest_recording_all_created_is_durable(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path, artifact_label="all-created")
    cleanup_bundles(migrated_engine, bundle)
    try:
        result = record_completed_experiment(
            bundle=bundle,
            transaction_factory=migrated_engine.begin,
        )

        assert result.snapshot_result.disposition is PersistenceDisposition.CREATED
        assert (
            result.experiment_run_result.disposition is PersistenceDisposition.CREATED
        )
        assert (
            result.artifact_manifest_result.disposition
            is PersistenceDisposition.CREATED
        )
        assert result.artifact_manifest_result.aggregate_entry_count == 10
        assert durable_counts(migrated_engine, bundle) == (1, 1, 1, 10)
    finally:
        cleanup_bundles(migrated_engine, bundle)


@pytest.mark.live_db
def test_completed_backtest_exact_replay_does_not_rewrite_artifacts(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path, artifact_label="replay")
    root = Path(bundle.artifact_manifest.artifact_root_uri.removeprefix("file://"))
    artifact_bytes_before = {
        path.name: path.read_bytes() for path in sorted(root.iterdir())
    }
    cleanup_bundles(migrated_engine, bundle)
    try:
        created = record_completed_experiment(
            bundle=bundle,
            transaction_factory=migrated_engine.begin,
        )
        replayed = record_completed_experiment(
            bundle=bundle,
            transaction_factory=migrated_engine.begin,
        )

        assert created.snapshot_result.disposition is PersistenceDisposition.CREATED
        assert replayed.snapshot_result.disposition is PersistenceDisposition.REPLAYED
        assert (
            replayed.experiment_run_result.disposition
            is PersistenceDisposition.REPLAYED
        )
        assert (
            replayed.artifact_manifest_result.disposition
            is PersistenceDisposition.REPLAYED
        )
        assert {path.name: path.read_bytes() for path in sorted(root.iterdir())} == (
            artifact_bytes_before
        )
        assert durable_counts(migrated_engine, bundle) == (1, 1, 1, 10)
    finally:
        cleanup_bundles(migrated_engine, bundle)


@pytest.mark.live_db
def test_same_snapshot_with_changed_execution_lineage_records_new_run(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    first = build_bundle(tmp_path, artifact_label="lineage-one")
    second = build_bundle(
        tmp_path,
        artifact_label="lineage-two",
        metadata=execution_metadata(dependency_lock_hash="sha256:changed-lock"),
    )
    assert first.snapshot.snapshot_id == second.snapshot.snapshot_id
    assert first.run.run_id != second.run.run_id
    cleanup_bundles(migrated_engine, first, second)
    try:
        record_completed_experiment(
            bundle=first,
            transaction_factory=migrated_engine.begin,
        )
        result = record_completed_experiment(
            bundle=second,
            transaction_factory=migrated_engine.begin,
        )

        assert result.snapshot_result.disposition is PersistenceDisposition.REPLAYED
        assert (
            result.experiment_run_result.disposition is PersistenceDisposition.CREATED
        )
        assert (
            result.artifact_manifest_result.disposition
            is PersistenceDisposition.CREATED
        )
        assert durable_counts(migrated_engine, first) == (1, 1, 1, 10)
        assert durable_counts(migrated_engine, second) == (1, 1, 1, 10)
    finally:
        cleanup_bundles(migrated_engine, first, second)


@pytest.mark.live_db
def test_snapshot_contract_conflict_stops_before_run_or_artifact_durability(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path, artifact_label="snapshot-conflict")
    conflicting_snapshot = bundle.snapshot.model_copy(
        update={"source_version": "conflicting-source-version"}
    )
    cleanup_bundles(migrated_engine, bundle)
    try:
        with migrated_engine.begin() as connection:
            repository = SqlAlchemyExperimentLedgerRepository(connection)
            repository.record_data_snapshot_manifest(conflicting_snapshot)

        with pytest.raises(ContractHashConflictError) as exc_info:
            record_completed_experiment(
                bundle=bundle,
                transaction_factory=migrated_engine.begin,
            )

        assert exc_info.value.context.table_name == "data_snapshot_manifests"
        assert durable_counts(migrated_engine, bundle) == (1, 0, 0, 0)
    finally:
        cleanup_bundles(migrated_engine, bundle)


@pytest.mark.live_db
def test_same_run_id_changed_run_contract_conflicts_at_run_stage(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path, artifact_label="run-conflict")
    conflicting = bundle_with_run_update(
        bundle,
        {"leakage_review": f"{bundle.run.leakage_review}; changed"},
    )
    cleanup_bundles(migrated_engine, bundle)
    try:
        record_completed_experiment(
            bundle=bundle,
            transaction_factory=migrated_engine.begin,
        )

        with pytest.raises(ContractHashConflictError) as exc_info:
            record_completed_experiment(
                bundle=conflicting,
                transaction_factory=migrated_engine.begin,
            )

        assert exc_info.value.context.table_name == "experiment_runs"
        assert durable_counts(migrated_engine, bundle) == (1, 1, 1, 10)
    finally:
        cleanup_bundles(migrated_engine, bundle)


@pytest.mark.live_db
def test_changed_artifact_root_for_same_run_id_conflicts_at_run_stage(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    first = build_bundle(tmp_path, artifact_label="root-one")
    same_run_other_root = build_bundle(tmp_path, artifact_label="root-two")
    assert first.run.run_id == same_run_other_root.run.run_id
    assert first.run.artifact_uri != same_run_other_root.run.artifact_uri
    cleanup_bundles(migrated_engine, first)
    try:
        record_completed_experiment(
            bundle=first,
            transaction_factory=migrated_engine.begin,
        )

        with pytest.raises(ContractHashConflictError) as exc_info:
            record_completed_experiment(
                bundle=same_run_other_root,
                transaction_factory=migrated_engine.begin,
            )

        assert exc_info.value.context.table_name == "experiment_runs"
        assert durable_counts(migrated_engine, first) == (1, 1, 1, 10)
    finally:
        cleanup_bundles(migrated_engine, first)


@pytest.mark.live_db
def test_artifact_manifest_conflict_rolls_back_snapshot_and_run_writes(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path, artifact_label="artifact-conflict")
    conflicting_manifest = bundle.artifact_manifest.model_copy(
        update={"created_at": datetime(2026, 2, 7, tzinfo=UTC)}
    )
    cleanup_bundles(migrated_engine, bundle)
    try:
        with migrated_engine.begin() as connection:
            repository = SqlAlchemyExperimentLedgerRepository(connection)
            repository.record_run_artifact_manifest(
                manifest_id=bundle.manifest_id,
                manifest=conflicting_manifest,
            )

        with pytest.raises(ContractHashConflictError) as exc_info:
            record_completed_experiment(
                bundle=bundle,
                transaction_factory=migrated_engine.begin,
            )

        assert exc_info.value.context.table_name == "run_artifact_manifests"
        assert durable_counts(migrated_engine, bundle) == (0, 0, 1, 10)
    finally:
        cleanup_bundles(migrated_engine, bundle)


@pytest.mark.live_db
def test_pair_aware_economic_recording_created_and_exact_replay(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    bundle = build_economic_pair_bundle(tmp_path)
    cleanup_pair_bundle(migrated_engine, bundle)
    try:
        created = record_completed_experiment_pair(
            bundle=bundle,
            transaction_factory=migrated_engine.begin,
        )
        replayed = record_completed_experiment_pair(
            bundle=bundle,
            transaction_factory=migrated_engine.begin,
        )

        assert (
            created.asset_snapshot_result.disposition is PersistenceDisposition.CREATED
        )
        assert (
            created.benchmark_snapshot_result.disposition
            is PersistenceDisposition.CREATED
        )
        assert (
            created.experiment_run_result.disposition is PersistenceDisposition.CREATED
        )
        assert (
            created.artifact_manifest_result.disposition
            is PersistenceDisposition.CREATED
        )
        assert (
            replayed.asset_snapshot_result.disposition
            is PersistenceDisposition.REPLAYED
        )
        assert (
            replayed.benchmark_snapshot_result.disposition
            is PersistenceDisposition.REPLAYED
        )
        assert (
            replayed.experiment_run_result.disposition
            is PersistenceDisposition.REPLAYED
        )
        assert (
            replayed.artifact_manifest_result.disposition
            is PersistenceDisposition.REPLAYED
        )
        assert durable_pair_counts(migrated_engine, bundle) == (2, 1, 1, 11)
    finally:
        cleanup_pair_bundle(migrated_engine, bundle)


@pytest.mark.live_db
def test_pair_artifact_conflict_rolls_back_both_snapshots_and_run(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    bundle = build_economic_pair_bundle(tmp_path)
    conflicting_manifest = bundle.artifact_manifest.model_copy(
        update={"created_at": datetime(2026, 2, 7, tzinfo=UTC)}
    )
    cleanup_pair_bundle(migrated_engine, bundle)
    try:
        with migrated_engine.begin() as connection:
            repository = SqlAlchemyExperimentLedgerRepository(connection)
            repository.record_run_artifact_manifest(
                manifest_id=bundle.manifest_id,
                manifest=conflicting_manifest,
            )

        with pytest.raises(ContractHashConflictError) as exc_info:
            record_completed_experiment_pair(
                bundle=bundle,
                transaction_factory=migrated_engine.begin,
            )

        assert exc_info.value.context.table_name == "run_artifact_manifests"
        assert durable_pair_counts(migrated_engine, bundle) == (0, 0, 1, 11)
    finally:
        cleanup_pair_bundle(migrated_engine, bundle)


def build_bundle(
    tmp_path: Path,
    *,
    artifact_label: str,
    metadata: ExecutionMetadata | None = None,
) -> CompletedExperimentRecordBundle:
    snapshot, fixture_hash = load_daily_bar_snapshot(FIXTURE_PATH)
    result = run_buy_and_hold_backtest(
        config=resolved_config(),
        snapshot=snapshot,
        fixture_content_hash=fixture_hash,
        execution_metadata=metadata or execution_metadata(),
    )
    artifacts = generate_artifact_bundle(
        result=result,
        artifact_base_dir=tmp_path / artifact_label,
    )
    records = map_completed_backtest_to_ledger_records(
        CompletedBacktestLedgerMappingInput(
            result=result,
            artifacts=artifacts,
            fixture_path=FIXTURE_PATH,
            created_by="agent-codex",
            review=review_metadata(),
        )
    )
    return CompletedExperimentRecordBundle(
        snapshot=records.snapshot,
        run=records.run,
        manifest_id=records.manifest_id,
        artifact_manifest=records.artifact_manifest,
    )


def build_economic_pair_bundle(tmp_path: Path) -> CompletedExperimentPairRecordBundle:
    qqq = qqq_bundle_files()
    result = run_snapshot_v2_buy_and_hold_backtest(
        asset_files=qqq,
        benchmark_files=spy_bundle_files(),
        research_profile=economic_compatible_profile(qqq),
        resolved_config=economic_resolved_config(),
        execution_metadata=economic_execution_metadata(),
    )
    artifacts = generate_economic_artifact_bundle(
        result=result,
        artifact_base_dir=tmp_path / "economic-pair",
    )
    records = map_completed_economic_backtest_to_ledger_records(
        CompletedEconomicBacktestLedgerMappingInput(
            result=result,
            artifacts=artifacts,
            created_by="agent-codex",
            review=review_metadata(),
        )
    )
    return CompletedExperimentPairRecordBundle(
        asset_snapshot=records.asset_snapshot,
        benchmark_snapshot=records.benchmark_snapshot,
        run=records.run,
        manifest_id=records.manifest_id,
        artifact_manifest=records.artifact_manifest,
    )


def resolved_config() -> ResolvedBacktestConfig:
    return ResolvedBacktestConfig(
        experiment_id="exp-fixture-qqq-buy-hold",
        strategy_id="strategies/etfs/qqq_buy_and_hold",
        strategy_version="0.1.0",
        engine_version=ENGINE_VERSION,
        asset_symbol="QQQ",
        benchmark_symbol="SPY",
        start_date=date(2026, 1, 29),
        end_date=date(2026, 2, 5),
        frequency="daily",
        initial_capital=Decimal("100000"),
        commission=BasisPointAssumption(
            bps=Decimal("1"),
            description="1 basis point commission on executed notional",
        ),
        slippage=BasisPointAssumption(
            bps=Decimal("2"),
            description="2 basis points buy slippage",
        ),
        execution_price_field="open",
        valuation_price_field="close",
        share_policy="integer",
        data_snapshot_id="synthetic-etf-snapshot-20260206",
        benchmark_snapshot_id="synthetic-etf-snapshot-20260206",
        random_seed=None,
        no_randomness_reason="deterministic no-randomness baseline",
        logical_execution_at=datetime(2026, 2, 6, tzinfo=UTC),
    )


def execution_metadata(
    *,
    dependency_lock_hash: str = "sha256:test-lock",
) -> ExecutionMetadata:
    return ExecutionMetadata(
        git_commit_sha="fe79572125f36088218e346451f4d7986cbec562",
        repo_dirty=False,
        python_version="3.13.14",
        platform="test-platform",
        dependency_lock_hash=dependency_lock_hash,
        execution_command="python -m backtest_engine",
    )


def review_metadata() -> ReviewMetadata:
    return ReviewMetadata(
        review_status=ReviewStatus.PENDING,
        reviewer_id=None,
        review_role=None,
        reviewed_at=None,
        decision=None,
        approval_scope=None,
        approval_expires_at=None,
        linked_pr=None,
        review_notes_uri=None,
        risk_approval_required=True,
    )


def bundle_with_run_update(
    bundle: CompletedExperimentRecordBundle,
    updates: dict[str, object],
) -> CompletedExperimentRecordBundle:
    return CompletedExperimentRecordBundle(
        snapshot=bundle.snapshot,
        run=bundle.run.model_copy(update=updates),
        manifest_id=bundle.manifest_id,
        artifact_manifest=bundle.artifact_manifest,
    )


def durable_counts(
    engine: Engine,
    bundle: CompletedExperimentRecordBundle,
) -> tuple[int, int, int, int]:
    with engine.connect() as connection:
        with connection.begin():
            snapshot_count = connection.execute(
                select(func.count())
                .select_from(data_snapshot_manifests)
                .where(
                    data_snapshot_manifests.c.snapshot_id == bundle.snapshot.snapshot_id
                )
            ).scalar_one()
            run_count = connection.execute(
                select(func.count())
                .select_from(experiment_runs)
                .where(experiment_runs.c.run_id == bundle.run.run_id)
            ).scalar_one()
            manifest_count = connection.execute(
                select(func.count())
                .select_from(run_artifact_manifests)
                .where(run_artifact_manifests.c.manifest_id == bundle.manifest_id)
            ).scalar_one()
            entry_count = connection.execute(
                select(func.count())
                .select_from(run_artifact_entries)
                .where(run_artifact_entries.c.manifest_id == bundle.manifest_id)
            ).scalar_one()
    return snapshot_count, run_count, manifest_count, entry_count


def durable_pair_counts(
    engine: Engine,
    bundle: CompletedExperimentPairRecordBundle,
) -> tuple[int, int, int, int]:
    with engine.connect() as connection:
        with connection.begin():
            snapshot_count = connection.execute(
                select(func.count())
                .select_from(data_snapshot_manifests)
                .where(
                    data_snapshot_manifests.c.snapshot_id.in_(
                        (
                            bundle.asset_snapshot.snapshot_id,
                            bundle.benchmark_snapshot.snapshot_id,
                        )
                    )
                )
            ).scalar_one()
            run_count = connection.execute(
                select(func.count())
                .select_from(experiment_runs)
                .where(experiment_runs.c.run_id == bundle.run.run_id)
            ).scalar_one()
            manifest_count = connection.execute(
                select(func.count())
                .select_from(run_artifact_manifests)
                .where(run_artifact_manifests.c.manifest_id == bundle.manifest_id)
            ).scalar_one()
            entry_count = connection.execute(
                select(func.count())
                .select_from(run_artifact_entries)
                .where(run_artifact_entries.c.manifest_id == bundle.manifest_id)
            ).scalar_one()
    return snapshot_count, run_count, manifest_count, entry_count


def cleanup_bundles(
    engine: Engine,
    *bundles: CompletedExperimentRecordBundle,
) -> None:
    manifest_ids = sorted({bundle.manifest_id for bundle in bundles})
    run_ids = sorted({bundle.run.run_id for bundle in bundles})
    snapshot_ids = sorted({bundle.snapshot.snapshot_id for bundle in bundles})
    with engine.begin() as connection:
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


def cleanup_pair_bundle(
    engine: Engine,
    bundle: CompletedExperimentPairRecordBundle,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            delete(run_artifact_entries).where(
                run_artifact_entries.c.manifest_id == bundle.manifest_id
            )
        )
        connection.execute(
            delete(run_artifact_manifests).where(
                run_artifact_manifests.c.manifest_id == bundle.manifest_id
            )
        )
        connection.execute(
            delete(experiment_runs).where(experiment_runs.c.run_id == bundle.run.run_id)
        )
        connection.execute(
            delete(data_snapshot_manifests).where(
                data_snapshot_manifests.c.snapshot_id.in_(
                    (
                        bundle.asset_snapshot.snapshot_id,
                        bundle.benchmark_snapshot.snapshot_id,
                    )
                )
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
