"""Deterministic QQQ buy-and-hold baseline engine."""

from __future__ import annotations

from decimal import Decimal

from backtest_engine.economic_models import EconomicPortfolioState
from backtest_engine.identity import (
    derive_execution_identity,
    validate_run_id_contract_compatibility,
)
from backtest_engine.market_data import align_daily_bars
from backtest_engine.metrics import (
    build_drawdown_series,
    build_monthly_returns,
    calculate_metrics,
)
from backtest_engine.models import (
    CompletedBacktestResult,
    DailyBarSnapshot,
    DailyEquityRecord,
    ExecutionMetadata,
    ResolvedBacktestConfig,
    SignalRecord,
    TradeRecord,
    quantize_money,
)
from backtest_engine.strategy_execution import apply_initial_integer_buy


def run_buy_and_hold_backtest(
    *,
    config: ResolvedBacktestConfig,
    snapshot: DailyBarSnapshot,
    fixture_content_hash: str,
    execution_metadata: ExecutionMetadata,
) -> CompletedBacktestResult:
    """Run the unconditional one-trade QQQ buy-and-hold baseline."""

    aligned = align_daily_bars(snapshot=snapshot, config=config)
    identity_digest, run_id = derive_execution_identity(
        config=config,
        execution_metadata=execution_metadata,
        fixture_content_hash=fixture_content_hash,
    )
    validate_run_id_contract_compatibility(run_id)

    first_qqq = aligned.qqq_bars[0]
    first_spy = aligned.spy_bars[0]
    strategy_state, buy_fill = apply_initial_integer_buy(
        state=EconomicPortfolioState(
            instrument_id=config.asset_symbol,
            currency=snapshot.currency,
            cash=config.initial_capital,
            quantity=0,
            total_book_cost=Decimal("0"),
        ),
        raw_execution_price=first_qqq.open,
        commission=config.commission,
        slippage=config.slippage,
    )
    quantity = strategy_state.quantity
    cash = strategy_state.cash

    trade = TradeRecord(
        trading_date=first_qqq.trading_date,
        symbol=config.asset_symbol,
        side="buy",
        quantity=quantity,
        raw_price=buy_fill.raw_price,
        fill_price=buy_fill.fill_price,
        executed_notional=buy_fill.executed_notional,
        commission=buy_fill.commission,
        slippage=buy_fill.slippage,
        total_cash_spent=buy_fill.total_cash_spent,
    )
    signal = SignalRecord(
        trading_date=first_qqq.trading_date,
        symbol=config.asset_symbol,
        signal_name="unconditional_initial_allocation",
        target_allocation="buy_and_hold",
        order_type_assumption="market_on_open",
        execution_price_field="open",
        no_lookahead=True,
    )

    benchmark_units = config.initial_capital / first_spy.open
    daily_equity = tuple(
        DailyEquityRecord(
            trading_date=qqq_bar.trading_date,
            strategy_equity=quantize_money(cash + Decimal(quantity) * qqq_bar.close),
            cash=cash,
            quantity=quantity,
            qqq_close=quantize_money(qqq_bar.close),
            benchmark_equity=quantize_money(benchmark_units * spy_bar.close),
            spy_close=quantize_money(spy_bar.close),
        )
        for qqq_bar, spy_bar in zip(aligned.qqq_bars, aligned.spy_bars, strict=True)
    )
    drawdown_series = build_drawdown_series(daily_equity)
    monthly_returns = build_monthly_returns(
        initial_capital=config.initial_capital,
        daily_equity=daily_equity,
    )
    trades = (trade,)
    metrics = calculate_metrics(
        initial_capital=config.initial_capital,
        daily_equity=daily_equity,
        drawdown_series=drawdown_series,
        trades=trades,
    )

    return CompletedBacktestResult(
        run_id=run_id,
        full_execution_identity_digest=identity_digest,
        resolved_config=config,
        execution_metadata=execution_metadata,
        input_snapshot_id=snapshot.snapshot_id,
        fixture_content_hash=fixture_content_hash,
        aligned_dates=aligned.trading_dates,
        daily_equity=daily_equity,
        drawdown_series=drawdown_series,
        monthly_returns=monthly_returns,
        trades=trades,
        signals=(signal,),
        metrics=metrics,
        total_realized_commission=buy_fill.commission,
        total_realized_slippage=buy_fill.slippage,
        ending_cash=cash,
        ending_quantity=quantity,
        ending_equity=daily_equity[-1].strategy_equity,
        deterministic_warnings=(
            "synthetic fixture-only data; not historical market data",
        ),
        leakage_assumptions=(
            "unconditional allocation uses no same-day close, future prices, "
            "indicators, or prior performance",
            "execution occurs at first aligned session open and valuation uses "
            "session close after execution",
        ),
    )


__all__ = ["run_buy_and_hold_backtest"]
