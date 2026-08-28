"""Canonical reconciliation for completed snapshot-v2 economic results."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from backtest_engine.benchmark_economic_accounting import value_economic_benchmark
from backtest_engine.economic_accounting import value_economic_portfolio
from backtest_engine.economic_execution_models import (
    CompletedEconomicBacktestResult,
    EconomicCorporateActionAuditRecord,
    EconomicTradeRecord,
)
from backtest_engine.economic_models import (
    EconomicPortfolioState,
    quantize_economic_money,
)
from backtest_engine.metrics import (
    build_drawdown_series,
    build_monthly_returns,
    calculate_metrics,
)
from backtest_engine.models import DailyEquityRecord, TradeRecord
from backtest_engine.strategy_execution import apply_initial_integer_buy


class CompletedEconomicResultValidationError(ValueError):
    """Raised when a completed economic result is stale or irreconcilable."""


def canonicalize_completed_economic_backtest_result(
    result: CompletedEconomicBacktestResult,
) -> CompletedEconomicBacktestResult:
    """Revalidate and exactly reconcile every result-derived economic output."""

    try:
        canonical = CompletedEconomicBacktestResult.model_validate(
            result.model_dump(mode="python")
        )
        _validate_instruments_and_currencies(canonical)
        _validate_initial_fill(canonical)
        _validate_terminal_states(canonical)
        _validate_costs(canonical)
        _validate_derived_outputs(canonical)
        _validate_corporate_action_audit(canonical)
    except CompletedEconomicResultValidationError:
        raise
    except Exception as exc:
        raise CompletedEconomicResultValidationError(
            "completed economic result failed canonical validation"
        ) from exc
    return canonical


def _validate_instruments_and_currencies(
    result: CompletedEconomicBacktestResult,
) -> None:
    lineage = result.market_data_lineage
    strategy = result.ending_strategy_state
    benchmark = result.ending_benchmark_state
    asset_currency = lineage.asset.data_snapshot_manifest.currency
    benchmark_currency = lineage.benchmark.data_snapshot_manifest.currency
    _require(asset_currency is not None, "asset snapshot currency must be present")
    _require(
        benchmark_currency is not None,
        "benchmark snapshot currency must be present",
    )
    _require(
        strategy.instrument_id == lineage.asset.instrument_id,
        "ending strategy instrument must match asset lineage",
    )
    _require(
        benchmark.instrument_id == lineage.benchmark.instrument_id,
        "ending benchmark instrument must match benchmark lineage",
    )
    _require(
        strategy.currency == asset_currency,
        "ending strategy currency must match asset lineage",
    )
    _require(
        benchmark.currency == benchmark_currency,
        "ending benchmark currency must match benchmark lineage",
    )


def _validate_initial_fill(result: CompletedEconomicBacktestResult) -> None:
    config = result.resolved_config
    first_daily = result.daily_records[0]
    trade = result.trade_records[0]
    initial_state = EconomicPortfolioState(
        instrument_id=result.market_data_lineage.asset.instrument_id,
        currency=result.ending_strategy_state.currency,
        cash=config.initial_capital,
        quantity=0,
        total_book_cost=Decimal("0"),
    )
    expected_state, expected_fill = apply_initial_integer_buy(
        state=initial_state,
        raw_execution_price=trade.raw_open,
        commission=config.commission,
        slippage=config.slippage,
    )
    expected_trade = EconomicTradeRecord(
        execution_session=result.market_data_lineage.run_session_dates[0],
        symbol="QQQ",
        side="buy",
        quantity=expected_fill.quantity,
        raw_open=expected_fill.raw_price,
        fill_price=expected_fill.fill_price,
        executed_notional=expected_fill.executed_notional,
        commission=expected_fill.commission,
        slippage=expected_fill.slippage,
        total_cash_spent=expected_fill.total_cash_spent,
        decision_authority="pre_run_unconditional",
        timing_policy_version=config.timing_policy_version,
    )
    _require(trade == expected_trade, "initial strategy trade must match resolved fill")
    _require(
        first_daily.strategy_cash == expected_state.cash,
        "first daily strategy cash must match initial fill",
    )
    _require(
        first_daily.strategy_quantity == expected_state.quantity,
        "first daily strategy quantity must match initial fill",
    )
    _require(
        first_daily.strategy_total_book_cost == expected_state.total_book_cost,
        "first daily strategy book cost must match initial fill",
    )
    _require(
        first_daily.strategy_outstanding_receivable_value == 0,
        "first-session zero-position actions cannot create strategy receivables",
    )
    _require(
        first_daily.benchmark_outstanding_receivable_value == 0,
        "first-session zero-position actions cannot create benchmark receivables",
    )
    _require(
        first_daily.cumulative_strategy_commission == expected_fill.commission,
        "first daily commission must match initial fill",
    )
    _require(
        first_daily.cumulative_strategy_slippage == expected_fill.slippage,
        "first daily slippage must match initial fill",
    )


def _validate_terminal_states(result: CompletedEconomicBacktestResult) -> None:
    ending = result.daily_records[-1]
    strategy_state = result.ending_strategy_state
    benchmark_state = result.ending_benchmark_state
    strategy_receivables = quantize_economic_money(
        sum(
            (item.receivable_amount for item in strategy_state.receivables),
            Decimal("0"),
        )
    )
    benchmark_receivables = quantize_economic_money(
        sum(
            (item.receivable_amount for item in benchmark_state.receivables),
            Decimal("0"),
        )
    )
    _require(
        ending.strategy_total_book_cost == strategy_state.total_book_cost,
        "ending strategy book cost must reconcile",
    )
    _require(
        ending.strategy_outstanding_receivable_value == strategy_receivables,
        "ending strategy receivables must reconcile",
    )
    _require(
        ending.benchmark_outstanding_receivable_value == benchmark_receivables,
        "ending benchmark receivables must reconcile",
    )
    strategy_valuation = value_economic_portfolio(
        state=strategy_state,
        session_date=ending.session,
        market_price=ending.strategy_raw_close,
    )
    benchmark_valuation = value_economic_benchmark(
        state=benchmark_state,
        session_date=ending.session,
        raw_market_price=ending.benchmark_raw_close,
    )
    _require(
        (
            ending.strategy_cash,
            ending.strategy_quantity,
            ending.strategy_market_value,
            ending.strategy_outstanding_receivable_value,
            ending.strategy_total_book_cost,
            ending.strategy_total_economic_equity,
        )
        == (
            strategy_valuation.cash,
            strategy_valuation.quantity,
            strategy_valuation.market_value,
            strategy_valuation.receivable_value,
            strategy_valuation.total_book_cost,
            strategy_valuation.total_equity,
        ),
        "ending strategy valuation must reconcile with ending state",
    )
    _require(
        (
            ending.benchmark_cash,
            ending.benchmark_fractional_units,
            ending.benchmark_market_value,
            ending.benchmark_outstanding_receivable_value,
            ending.benchmark_total_economic_equity,
        )
        == (
            benchmark_valuation.cash,
            benchmark_valuation.fractional_units,
            benchmark_valuation.market_value,
            benchmark_valuation.receivable_value,
            benchmark_valuation.total_equity,
        ),
        "ending benchmark valuation must reconcile with ending state",
    )


def _validate_costs(result: CompletedEconomicBacktestResult) -> None:
    trade = result.trade_records[0]
    totals = result.transaction_cost_totals
    _require(
        totals.strategy_commission == trade.commission,
        "strategy commission total must match initial fill",
    )
    _require(
        totals.strategy_slippage == trade.slippage,
        "strategy slippage total must match initial fill",
    )
    _require(
        totals.benchmark_commission == 0 and totals.benchmark_slippage == 0,
        "benchmark transaction costs must remain zero",
    )
    for row in result.daily_records:
        _require(
            row.cumulative_strategy_commission == totals.strategy_commission,
            "every daily commission total must match the sole initial fill",
        )
        _require(
            row.cumulative_strategy_slippage == totals.strategy_slippage,
            "every daily slippage total must match the sole initial fill",
        )


def _validate_derived_outputs(result: CompletedEconomicBacktestResult) -> None:
    legacy_daily = tuple(
        DailyEquityRecord(
            trading_date=row.session,
            strategy_equity=row.strategy_total_economic_equity,
            cash=row.strategy_cash,
            quantity=row.strategy_quantity,
            qqq_close=row.strategy_raw_close,
            benchmark_equity=row.benchmark_total_economic_equity,
            spy_close=row.benchmark_raw_close,
        )
        for row in result.daily_records
    )
    legacy_trades = tuple(
        TradeRecord(
            trading_date=row.execution_session,
            symbol=row.symbol,
            side=row.side,
            quantity=row.quantity,
            raw_price=row.raw_open,
            fill_price=row.fill_price,
            executed_notional=row.executed_notional,
            commission=row.commission,
            slippage=row.slippage,
            total_cash_spent=row.total_cash_spent,
        )
        for row in result.trade_records
    )
    expected_drawdown = build_drawdown_series(legacy_daily)
    expected_monthly_returns = build_monthly_returns(
        initial_capital=result.resolved_config.initial_capital,
        daily_equity=legacy_daily,
    )
    expected_metrics = calculate_metrics(
        initial_capital=result.resolved_config.initial_capital,
        daily_equity=legacy_daily,
        drawdown_series=expected_drawdown,
        trades=legacy_trades,
    )
    _require(result.metrics == expected_metrics, "economic metrics must be canonical")
    _require(
        result.drawdown_series == expected_drawdown,
        "drawdown series must be canonical",
    )
    _require(
        result.monthly_returns == expected_monthly_returns,
        "monthly returns must be canonical",
    )


def _validate_corporate_action_audit(
    result: CompletedEconomicBacktestResult,
) -> None:
    sessions = set(result.market_data_lineage.run_session_dates)
    _validate_role_audit(
        records=tuple(
            row
            for row in result.corporate_action_audit
            if row.portfolio_role == "strategy"
        ),
        role="strategy",
        instrument_id=result.ending_strategy_state.instrument_id,
        position_unit_policy="integer_shares",
        state_event_ids=(
            result.ending_strategy_state.applied_corporate_action_event_ids
        ),
        sessions=sessions,
        first_session=result.market_data_lineage.run_session_dates[0],
    )
    _validate_role_audit(
        records=tuple(
            row
            for row in result.corporate_action_audit
            if row.portfolio_role == "benchmark"
        ),
        role="benchmark",
        instrument_id=result.ending_benchmark_state.instrument_id,
        position_unit_policy="fractional_decimal_12_units",
        state_event_ids=(
            result.ending_benchmark_state.applied_corporate_action_event_ids
        ),
        sessions=sessions,
        first_session=result.market_data_lineage.run_session_dates[0],
    )


def _validate_role_audit(
    *,
    records: tuple[EconomicCorporateActionAuditRecord, ...],
    role: str,
    instrument_id: str,
    position_unit_policy: str,
    state_event_ids: tuple[str, ...],
    sessions: set[date],
    first_session: date,
) -> None:
    application_ids: list[str] = []
    settlement_ids: list[str] = []
    application_types: dict[str, str] = {}
    for row in records:
        _require(row.session in sessions, f"{role} audit session must be in-run")
        _require(
            row.instrument_id == instrument_id,
            f"{role} audit instrument must match ending state",
        )
        _require(
            row.position_unit_policy == position_unit_policy,
            f"{role} audit position policy must match role",
        )
        if row.accounting_action in {
            "split_applied",
            "cash_distribution_entitlement",
        }:
            application_ids.append(row.event_id)
            application_types[row.event_id] = row.accounting_action
            if row.accounting_action == "split_applied":
                _require(row.event_type == "split", "split audit type must be split")
            else:
                _require(
                    row.event_type == "cash_distribution",
                    "distribution entitlement audit type must be cash_distribution",
                )
            if row.session == first_session:
                _require(
                    row.pre_position == 0
                    and row.post_position == 0
                    and row.entitlement_position == 0,
                    f"first-session {role} action must use zero carried holdings",
                )
        else:
            settlement_ids.append(row.event_id)
            _require(
                row.event_type == "cash_distribution",
                "distribution settlement audit type must be cash_distribution",
            )
    _require(
        len(application_ids) == len(set(application_ids)),
        f"{role} audit must contain one application row per event",
    )
    _require(
        len(settlement_ids) == len(set(settlement_ids)),
        f"{role} audit must contain at most one settlement row per event",
    )
    _require(
        tuple(sorted(application_ids)) == state_event_ids,
        f"{role} audit application IDs must match ending state",
    )
    for event_id in settlement_ids:
        _require(
            application_types.get(event_id) == "cash_distribution_entitlement",
            f"{role} settlement must refer to an applied distribution",
        )


def _require(condition: object, message: str) -> None:
    if not condition:
        raise CompletedEconomicResultValidationError(message)


__all__ = [
    "CompletedEconomicResultValidationError",
    "canonicalize_completed_economic_backtest_result",
]
