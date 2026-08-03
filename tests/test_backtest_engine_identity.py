from __future__ import annotations

import ast
import inspect
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from backtest_engine import (
    ENGINE_VERSION,
    BacktestMetrics,
    BasisPointAssumption,
    ExecutionMetadata,
    ResolvedBacktestConfig,
    canonical_json_bytes,
    derive_execution_identity,
    identity_from_completed_result,
    load_daily_bar_snapshot,
    run_buy_and_hold_backtest,
    validate_run_id_contract_compatibility,
)
from backtest_engine.models import quantize_ratio

FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "backtest_engine"
    / "synthetic_daily_etf_bars.json"
)


def test_same_inputs_produce_same_full_digest_and_run_id() -> None:
    result = completed_result()

    first = identity_from_completed_result(result)
    second = identity_from_completed_result(result)

    assert first == second
    assert first == (
        result.full_execution_identity_digest,
        result.run_id,
    )


def test_run_id_uses_full_64_lowercase_hex_digest() -> None:
    run_id = completed_result().run_id
    digest = run_id.removeprefix("run-")

    assert len(digest) == 64
    assert digest == digest.lower()
    assert all(character in "0123456789abcdef" for character in digest)
    validate_run_id_contract_compatibility(run_id)


def test_changed_config_changes_run_id() -> None:
    result = completed_result()
    changed_config = result.resolved_config.model_copy(
        update={"initial_capital": Decimal("100001")}
    )

    assert derive_execution_identity(
        config=changed_config,
        execution_metadata=result.execution_metadata,
        fixture_content_hash=result.fixture_content_hash,
    ) != identity_from_completed_result(result)


def test_changed_fixture_hash_changes_run_id() -> None:
    result = completed_result()

    assert derive_execution_identity(
        config=result.resolved_config,
        execution_metadata=result.execution_metadata,
        fixture_content_hash="0" * 64,
    ) != identity_from_completed_result(result)


def test_changed_lineage_changes_run_id() -> None:
    result = completed_result()
    changed_metadata = result.execution_metadata.model_copy(
        update={"dependency_lock_hash": "sha256:changed-lock"}
    )

    assert derive_execution_identity(
        config=result.resolved_config,
        execution_metadata=changed_metadata,
        fixture_content_hash=result.fixture_content_hash,
    ) != identity_from_completed_result(result)


def test_changed_output_metrics_do_not_change_run_id() -> None:
    result = completed_result()
    changed_metrics = BacktestMetrics(
        total_return=quantize_ratio(Decimal("0")),
        benchmark_total_return=result.metrics.benchmark_total_return,
        excess_return=result.metrics.excess_return,
        maximum_drawdown=result.metrics.maximum_drawdown,
        realized_commission=result.metrics.realized_commission,
        realized_slippage=result.metrics.realized_slippage,
        ending_equity=result.metrics.ending_equity,
        number_of_trades=result.metrics.number_of_trades,
        observation_count=result.metrics.observation_count,
    )
    changed_result = result.model_copy(update={"metrics": changed_metrics})

    assert identity_from_completed_result(
        changed_result
    ) == identity_from_completed_result(result)


def test_changed_artifact_root_does_not_change_run_id() -> None:
    result = completed_result()

    assert identity_from_completed_result(result) == derive_execution_identity(
        config=result.resolved_config,
        execution_metadata=result.execution_metadata,
        fixture_content_hash=result.fixture_content_hash,
    )


def test_identity_source_does_not_call_python_builtin_hash() -> None:
    import backtest_engine.identity as identity

    tree = ast.parse(inspect.getsource(identity))

    for node in ast.walk(tree):
        assert not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "hash"
        )


@pytest.mark.parametrize(
    "value",
    [
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_canonical_json_rejects_nan_and_infinity(value: object) -> None:
    with pytest.raises(ValueError):
        canonical_json_bytes({"value": value})


def test_canonical_json_rejects_timezone_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        canonical_json_bytes({"created_at": datetime(2026, 1, 1)})


def test_identity_and_engine_sources_do_not_use_wall_clock() -> None:
    import backtest_engine.artifacts as artifacts
    import backtest_engine.engine as engine
    import backtest_engine.identity as identity

    combined_source = "\n".join(
        inspect.getsource(module) for module in (artifacts, engine, identity)
    )

    for prohibited in ("datetime.now", "datetime.utcnow", "date.today", "time.time"):
        assert prohibited not in combined_source


def test_config_model_records_no_randomness_marker() -> None:
    config = resolved_config()
    metadata = execution_metadata()

    _digest, run_id = derive_execution_identity(
        config=config,
        execution_metadata=metadata,
        fixture_content_hash="1" * 64,
    )

    assert config.random_seed is None
    assert config.no_randomness_reason == "deterministic no-randomness baseline"
    assert run_id.startswith("run-")


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
        benchmark_snapshot_id="synthetic-spy-benchmark-snapshot-20260206",
        random_seed=None,
        no_randomness_reason="deterministic no-randomness baseline",
        logical_execution_at=datetime(2026, 2, 6, tzinfo=UTC),
    )


def completed_result():
    snapshot, fixture_hash = load_daily_bar_snapshot(FIXTURE_PATH)
    return run_buy_and_hold_backtest(
        config=resolved_config(),
        snapshot=snapshot,
        fixture_content_hash=fixture_hash,
        execution_metadata=execution_metadata(),
    )


def execution_metadata() -> ExecutionMetadata:
    return ExecutionMetadata(
        git_commit_sha="8f09472f18e7be1895f716b9c4a259ec1a5c4050",
        repo_dirty=False,
        python_version="3.13.14",
        platform="test-platform",
        dependency_lock_hash="sha256:test-lock",
        execution_command="python -m backtest_engine",
    )
