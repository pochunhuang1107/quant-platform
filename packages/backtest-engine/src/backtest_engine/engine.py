"""Deterministic QQQ buy-and-hold baseline engine."""

from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal

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

_BPS_DENOMINATOR = Decimal("10000")


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
    slippage_rate = config.slippage.bps / _BPS_DENOMINATOR
    commission_rate = config.commission.bps / _BPS_DENOMINATOR
    fill_price = quantize_money(first_qqq.open * (Decimal("1") + slippage_rate))
    per_share_cash_required = fill_price * (Decimal("1") + commission_rate)
    quantity = int(
        (config.initial_capital / per_share_cash_required).to_integral_value(
            rounding=ROUND_FLOOR
        )
    )
    if quantity <= 0:
        raise ValueError("initial capital cannot buy one QQQ share")

    executed_notional = quantize_money(Decimal(quantity) * fill_price)
    commission = quantize_money(executed_notional * commission_rate)
    slippage = quantize_money(Decimal(quantity) * (fill_price - first_qqq.open))
    total_cash_spent = quantize_money(executed_notional + commission)
    cash = quantize_money(config.initial_capital - total_cash_spent)

    trade = TradeRecord(
        trading_date=first_qqq.trading_date,
        symbol=config.asset_symbol,
        side="buy",
        quantity=quantity,
        raw_price=quantize_money(first_qqq.open),
        fill_price=fill_price,
        executed_notional=executed_notional,
        commission=commission,
        slippage=slippage,
        total_cash_spent=total_cash_spent,
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
        total_realized_commission=commission,
        total_realized_slippage=slippage,
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
