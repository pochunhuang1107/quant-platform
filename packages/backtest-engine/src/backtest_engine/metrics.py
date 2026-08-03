"""Deterministic metrics for the ETF backtest engine."""

from __future__ import annotations

from decimal import Decimal

from backtest_engine.models import (
    BacktestMetrics,
    DailyEquityRecord,
    DrawdownRecord,
    MonthlyReturnRecord,
    TradeRecord,
    quantize_money,
    quantize_ratio,
)


def build_drawdown_series(
    daily_equity: tuple[DailyEquityRecord, ...],
) -> tuple[DrawdownRecord, ...]:
    """Compute drawdown as equity / running peak - 1."""

    running_peak = Decimal("0")
    rows: list[DrawdownRecord] = []
    for row in daily_equity:
        running_peak = max(running_peak, row.strategy_equity)
        drawdown = quantize_ratio(row.strategy_equity / running_peak - Decimal("1"))
        rows.append(
            DrawdownRecord(
                trading_date=row.trading_date,
                running_peak=quantize_money(running_peak),
                drawdown=drawdown,
            )
        )
    return tuple(rows)


def build_monthly_returns(
    *,
    initial_capital: Decimal,
    daily_equity: tuple[DailyEquityRecord, ...],
) -> tuple[MonthlyReturnRecord, ...]:
    """Compute month-end returns from supplied observations only."""

    rows: list[MonthlyReturnRecord] = []
    month_ends: list[DailyEquityRecord] = []
    previous = daily_equity[0]
    for row in daily_equity[1:]:
        if row.trading_date.strftime("%Y-%m") != previous.trading_date.strftime(
            "%Y-%m"
        ):
            month_ends.append(previous)
        previous = row
    month_ends.append(previous)

    prior_boundary_equity = quantize_money(initial_capital)
    for month_end in month_ends:
        rows.append(_monthly_return(prior_boundary_equity, month_end))
        prior_boundary_equity = month_end.strategy_equity
    return tuple(rows)


def calculate_metrics(
    *,
    initial_capital: Decimal,
    daily_equity: tuple[DailyEquityRecord, ...],
    drawdown_series: tuple[DrawdownRecord, ...],
    trades: tuple[TradeRecord, ...],
) -> BacktestMetrics:
    """Calculate the approved deterministic metric set."""

    ending = daily_equity[-1]
    total_commission = sum((trade.commission for trade in trades), Decimal("0"))
    total_slippage = sum((trade.slippage for trade in trades), Decimal("0"))
    total_return = quantize_ratio(
        ending.strategy_equity / initial_capital - Decimal("1")
    )
    benchmark_total_return = quantize_ratio(
        ending.benchmark_equity / initial_capital - Decimal("1")
    )
    return BacktestMetrics(
        total_return=total_return,
        benchmark_total_return=benchmark_total_return,
        excess_return=quantize_ratio(total_return - benchmark_total_return),
        maximum_drawdown=min(row.drawdown for row in drawdown_series),
        realized_commission=quantize_money(total_commission),
        realized_slippage=quantize_money(total_slippage),
        ending_equity=ending.strategy_equity,
        number_of_trades=len(trades),
        observation_count=len(daily_equity),
    )


def _monthly_return(
    start_equity: Decimal,
    end: DailyEquityRecord,
) -> MonthlyReturnRecord:
    return MonthlyReturnRecord(
        month=end.trading_date.strftime("%Y-%m"),
        start_equity=start_equity,
        end_equity=end.strategy_equity,
        return_value=quantize_ratio(end.strategy_equity / start_equity - Decimal("1")),
    )


__all__ = [
    "build_drawdown_series",
    "build_monthly_returns",
    "calculate_metrics",
]
