from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from backtest_engine import (
    ENGINE_VERSION,
    BasisPointAssumption,
    DailyEquityRecord,
    ExecutionMetadata,
    ResolvedBacktestConfig,
    load_daily_bar_snapshot,
    run_buy_and_hold_backtest,
)
from backtest_engine.metrics import build_monthly_returns

FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "backtest_engine"
    / "synthetic_daily_etf_bars.json"
)


def test_exact_total_return() -> None:
    assert completed_result().metrics.total_return == Decimal("0.049650280020")


def test_exact_benchmark_return() -> None:
    assert completed_result().metrics.benchmark_total_return == Decimal(
        "0.025000000000"
    )


def test_exact_excess_return() -> None:
    assert completed_result().metrics.excess_return == Decimal("0.024650280020")


def test_exact_non_positive_max_drawdown() -> None:
    maximum_drawdown = completed_result().metrics.maximum_drawdown

    assert maximum_drawdown == Decimal("-0.009797188585")
    assert maximum_drawdown <= 0


def test_exact_ending_equity() -> None:
    assert completed_result().metrics.ending_equity == Decimal("104965.028002")


def test_exact_cost_and_slippage_totals() -> None:
    result = completed_result()

    assert result.metrics.realized_commission == Decimal("9.991998")
    assert result.metrics.realized_slippage == Decimal("19.980000")
    assert result.total_realized_commission == Decimal("9.991998")
    assert result.total_realized_slippage == Decimal("19.980000")


def test_observation_and_trade_counts() -> None:
    metrics = completed_result().metrics

    assert metrics.number_of_trades == 1
    assert metrics.observation_count == 6


def test_monthly_returns_use_month_end_boundaries_and_initial_capital() -> None:
    monthly_returns = build_monthly_returns(
        initial_capital=Decimal("100.000000"),
        daily_equity=(
            daily_equity_row(date(2025, 12, 30), Decimal("100.000000")),
            daily_equity_row(date(2025, 12, 31), Decimal("110.000000")),
            daily_equity_row(date(2026, 1, 2), Decimal("121.000000")),
            daily_equity_row(date(2026, 2, 2), Decimal("108.900000")),
        ),
    )

    assert [
        (row.month, row.start_equity, row.end_equity, row.return_value)
        for row in monthly_returns
    ] == [
        (
            "2025-12",
            Decimal("100.000000"),
            Decimal("110.000000"),
            Decimal("0.100000000000"),
        ),
        (
            "2026-01",
            Decimal("110.000000"),
            Decimal("121.000000"),
            Decimal("0.100000000000"),
        ),
        (
            "2026-02",
            Decimal("121.000000"),
            Decimal("108.900000"),
            Decimal("-0.100000000000"),
        ),
    ]


def test_no_annualized_metrics() -> None:
    metrics = completed_result().metrics

    assert not hasattr(metrics, "cagr")
    assert not hasattr(metrics, "annualized_return")
    assert not hasattr(metrics, "volatility")
    assert not hasattr(metrics, "sharpe")
    assert not hasattr(metrics, "sortino")
    assert not hasattr(metrics, "alpha")
    assert not hasattr(metrics, "beta")


def completed_result():
    snapshot, fixture_hash = load_daily_bar_snapshot(FIXTURE_PATH)
    return run_buy_and_hold_backtest(
        config=resolved_config(),
        snapshot=snapshot,
        fixture_content_hash=fixture_hash,
        execution_metadata=execution_metadata(),
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
        benchmark_snapshot_id="synthetic-spy-benchmark-snapshot-20260206",
        random_seed=None,
        no_randomness_reason="deterministic no-randomness baseline",
        logical_execution_at=datetime(2026, 2, 6, tzinfo=UTC),
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


def daily_equity_row(
    trading_date: date,
    strategy_equity: Decimal,
) -> DailyEquityRecord:
    return DailyEquityRecord(
        trading_date=trading_date,
        strategy_equity=strategy_equity,
        cash=Decimal("0.000000"),
        quantity=1,
        qqq_close=strategy_equity,
        benchmark_equity=strategy_equity,
        spy_close=strategy_equity,
    )
