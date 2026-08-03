from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from backtest_engine import (
    ENGINE_VERSION,
    BasisPointAssumption,
    ExecutionMetadata,
    ResolvedBacktestConfig,
    load_daily_bar_snapshot,
    run_buy_and_hold_backtest,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "backtest_engine"
    / "synthetic_daily_etf_bars.json"
)


def test_unconditional_first_session_open_execution() -> None:
    result = completed_result()
    trade = result.trades[0]

    assert trade.trading_date == date(2026, 1, 29)
    assert trade.symbol == "QQQ"
    assert trade.side == "buy"
    assert trade.raw_price == Decimal("100.000000")
    assert trade.fill_price == Decimal("100.020000")
    assert trade.quantity == 999


def test_no_same_day_close_used_in_quantity_or_fill_calculation() -> None:
    result = completed_result()
    trade = result.trades[0]

    assert result.daily_equity[0].qqq_close == Decimal("102.000000")
    assert trade.fill_price != Decimal("102.020400")
    assert trade.quantity == 999


def test_exact_slippage_commission_and_cash_remainder() -> None:
    result = completed_result()
    trade = result.trades[0]

    assert trade.executed_notional == Decimal("99919.980000")
    assert trade.slippage == Decimal("19.980000")
    assert trade.commission == Decimal("9.991998")
    assert trade.total_cash_spent == Decimal("99929.971998")
    assert result.ending_cash == Decimal("70.028002")


def test_first_day_close_valuation_and_no_liquidation() -> None:
    result = completed_result()

    assert result.daily_equity[0].strategy_equity == Decimal("101968.028002")
    assert result.ending_quantity == 999
    assert result.ending_cash == Decimal("70.028002")
    assert len(result.trades) == 1


def test_one_unconditional_signal() -> None:
    result = completed_result()
    signal = result.signals[0]

    assert len(result.signals) == 1
    assert signal.signal_name == "unconditional_initial_allocation"
    assert signal.target_allocation == "buy_and_hold"
    assert signal.no_lookahead is True


def test_exact_benchmark_normalization() -> None:
    result = completed_result()

    assert result.daily_equity[0].benchmark_equity == Decimal("100500.000000")
    assert result.daily_equity[-1].benchmark_equity == Decimal("102500.000000")


def test_exact_aligned_equity_rows() -> None:
    result = completed_result()

    assert [(row.trading_date, row.strategy_equity) for row in result.daily_equity] == [
        (date(2026, 1, 29), Decimal("101968.028002")),
        (date(2026, 1, 30), Decimal("100969.028002")),
        (date(2026, 1, 31), Decimal("103966.028002")),
        (date(2026, 2, 3), Decimal("102967.028002")),
        (date(2026, 2, 4), Decimal("105964.028002")),
        (date(2026, 2, 5), Decimal("104965.028002")),
    ]


def test_deterministic_repeated_result() -> None:
    assert completed_result() == completed_result()


def test_no_float_values_in_core_result() -> None:
    assert not contains_float(completed_result().model_dump(mode="python"))


def test_no_random_behavior() -> None:
    result = completed_result()

    assert result.resolved_config.random_seed is None
    assert result.resolved_config.no_randomness_reason


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


def contains_float(value: Any) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(contains_float(inner_value) for inner_value in value.values())
    if isinstance(value, list | tuple):
        return any(contains_float(inner_value) for inner_value in value)
    return False
