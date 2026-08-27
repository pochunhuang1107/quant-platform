"""Pure accounting for the gross fractional-unit ETF benchmark."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_FLOOR, Context, Decimal, localcontext

from backtest_engine.benchmark_economic_models import (
    APPROVED_BENCHMARK_ECONOMIC_POLICY,
    BENCHMARK_UNIT_QUANT,
    BenchmarkCorporateActionAccountingRecord,
    BenchmarkEconomicPolicy,
    EconomicBenchmarkReceivable,
    EconomicBenchmarkState,
    EconomicBenchmarkValuation,
    quantize_benchmark_units,
)
from backtest_engine.corporate_action_accounting import (
    validate_and_order_session_corporate_action_events,
)
from backtest_engine.economic_models import (
    EconomicAccountingError,
    quantize_economic_money,
)
from backtest_engine.timing import (
    first_expected_session_after,
    validate_expected_session_dates,
)
from research_sdk.contracts.daily_market_data_economics import (
    DailyMarketDataCashDistribution,
    DailyMarketDataCorporateActionEvent,
    DailyMarketDataSplit,
)

_BENCHMARK_DECIMAL_CONTEXT = Context(prec=50)


def initialize_economic_benchmark(
    *,
    instrument_id: str,
    currency: str,
    initial_capital: Decimal,
    raw_execution_price: Decimal,
    policy: BenchmarkEconomicPolicy = APPROVED_BENCHMARK_ECONOMIC_POLICY,
) -> EconomicBenchmarkState:
    """Normalize capital into fractional units with explicit residual cash."""

    approved_policy = BenchmarkEconomicPolicy.model_validate(
        policy.model_dump(mode="python")
    )
    capital = _parse_positive_money(initial_capital, field_name="initial_capital")
    raw_price = _parse_positive_money(
        raw_execution_price, field_name="raw_execution_price"
    )
    capital = quantize_economic_money(capital)
    raw_price = quantize_economic_money(raw_price)

    with localcontext(_BENCHMARK_DECIMAL_CONTEXT):
        unquantized_units = capital / raw_price
        units = unquantized_units.quantize(
            BENCHMARK_UNIT_QUANT,
            rounding=ROUND_FLOOR,
        )
    if units <= 0:
        raise EconomicAccountingError(
            "initial capital cannot buy positive benchmark units"
        )

    normalized_market_value = quantize_economic_money(units * raw_price)
    residual_cash = quantize_economic_money(capital - normalized_market_value)
    if residual_cash < 0:
        raise EconomicAccountingError("benchmark normalization overspent capital")

    return EconomicBenchmarkState(
        policy_version=approved_policy.policy_version,
        instrument_id=instrument_id,
        currency=currency,
        cash=residual_cash,
        fractional_units=units,
    )


def apply_session_open_benchmark_economic_accounting(
    *,
    state: EconomicBenchmarkState,
    session_date: date,
    expected_session_dates: tuple[date, ...],
    corporate_action_events: tuple[DailyMarketDataCorporateActionEvent, ...],
) -> tuple[
    EconomicBenchmarkState,
    tuple[BenchmarkCorporateActionAccountingRecord, ...],
]:
    """Apply deterministic pre-valuation benchmark corporate-action accounting."""

    _validate_session_date(session_date)
    sessions = validate_expected_session_dates(expected_session_dates)
    if session_date not in sessions:
        raise EconomicAccountingError("session_date must be an expected session")

    ordered_events = _validate_current_session_events(
        state=state,
        session_date=session_date,
        expected_session_dates=sessions,
        corporate_action_events=corporate_action_events,
    )

    records: list[BenchmarkCorporateActionAccountingRecord] = []
    cash = state.cash
    retained_receivables: list[EconomicBenchmarkReceivable] = []
    for receivable in state.receivables:
        if receivable.cash_available_session == session_date:
            cash = quantize_economic_money(cash + receivable.receivable_amount)
            records.append(
                BenchmarkCorporateActionAccountingRecord(
                    session_date=session_date,
                    event_id=receivable.event_id,
                    instrument_id=receivable.instrument_id,
                    event_type="cash_distribution",
                    accounting_action="cash_distribution_settlement",
                    pre_units=state.fractional_units,
                    post_units=state.fractional_units,
                    entitlement_units=receivable.entitled_units,
                    receivable_delta=-receivable.receivable_amount,
                    cash_delta=receivable.receivable_amount,
                )
            )
        else:
            retained_receivables.append(receivable)

    units = state.fractional_units
    applied_event_ids = set(state.applied_corporate_action_event_ids)
    for event in ordered_events:
        if isinstance(event, DailyMarketDataSplit):
            pre_units = units
            units = _apply_split_units(units=units, split=event)
            applied_event_ids.add(event.event_id)
            records.append(
                BenchmarkCorporateActionAccountingRecord(
                    session_date=session_date,
                    event_id=event.event_id,
                    instrument_id=event.instrument_id,
                    event_type="split",
                    accounting_action="split_applied",
                    pre_units=pre_units,
                    post_units=units,
                    entitlement_units=Decimal("0"),
                    receivable_delta=Decimal("0"),
                    cash_delta=Decimal("0"),
                )
            )

    new_receivables = list(retained_receivables)
    for event in ordered_events:
        if isinstance(event, DailyMarketDataCashDistribution):
            entitlement_units = units
            receivable_amount = Decimal("0")
            if entitlement_units > 0:
                receivable_amount = quantize_economic_money(
                    entitlement_units * event.amount
                )
                if event.payable_date is None:
                    raise EconomicAccountingError(
                        "entitled cash distribution requires payable_date"
                    )
                new_receivables.append(
                    EconomicBenchmarkReceivable(
                        event_id=event.event_id,
                        instrument_id=event.instrument_id,
                        ex_date=event.ex_date,
                        entitled_units=entitlement_units,
                        amount_per_unit=event.amount,
                        receivable_amount=receivable_amount,
                        currency=event.currency,
                        payable_date=event.payable_date,
                        cash_available_session=first_expected_session_after(
                            event.payable_date,
                            sessions,
                        ),
                    )
                )
            applied_event_ids.add(event.event_id)
            records.append(
                BenchmarkCorporateActionAccountingRecord(
                    session_date=session_date,
                    event_id=event.event_id,
                    instrument_id=event.instrument_id,
                    event_type="cash_distribution",
                    accounting_action="cash_distribution_entitlement",
                    pre_units=units,
                    post_units=units,
                    entitlement_units=entitlement_units,
                    receivable_delta=receivable_amount,
                    cash_delta=Decimal("0"),
                )
            )

    return (
        EconomicBenchmarkState(
            policy_version=state.policy_version,
            instrument_id=state.instrument_id,
            currency=state.currency,
            cash=cash,
            fractional_units=units,
            receivables=tuple(new_receivables),
            applied_corporate_action_event_ids=tuple(sorted(applied_event_ids)),
        ),
        tuple(records),
    )


def value_economic_benchmark(
    *,
    state: EconomicBenchmarkState,
    session_date: date,
    raw_market_price: Decimal,
) -> EconomicBenchmarkValuation:
    """Value the benchmark from cash, fractional units, and receivables."""

    _validate_session_date(session_date)
    market_price = quantize_economic_money(
        _parse_positive_money(raw_market_price, field_name="raw_market_price")
    )
    market_value = quantize_economic_money(state.fractional_units * market_price)
    receivable_value = quantize_economic_money(
        sum(
            (receivable.receivable_amount for receivable in state.receivables),
            Decimal("0"),
        )
    )
    total_equity = quantize_economic_money(state.cash + market_value + receivable_value)
    return EconomicBenchmarkValuation(
        session_date=session_date,
        cash=state.cash,
        fractional_units=state.fractional_units,
        market_price=market_price,
        market_value=market_value,
        receivable_value=receivable_value,
        total_equity=total_equity,
    )


def _validate_current_session_events(
    *,
    state: EconomicBenchmarkState,
    session_date: date,
    expected_session_dates: tuple[date, ...],
    corporate_action_events: tuple[DailyMarketDataCorporateActionEvent, ...],
) -> tuple[DailyMarketDataCorporateActionEvent, ...]:
    ordered_events = validate_and_order_session_corporate_action_events(
        session_date=session_date,
        instrument_id=state.instrument_id,
        currency=state.currency,
        has_held_position=state.fractional_units > 0,
        applied_event_ids=state.applied_corporate_action_event_ids,
        corporate_action_events=corporate_action_events,
    )

    if state.fractional_units > 0:
        for event in ordered_events:
            if isinstance(event, DailyMarketDataSplit):
                _calculate_split_units(units=state.fractional_units, split=event)
            elif isinstance(event, DailyMarketDataCashDistribution):
                if event.payable_date is None:
                    raise EconomicAccountingError(
                        "entitled cash distribution requires payable_date"
                    )
                if event.payable_date < event.ex_date:
                    raise EconomicAccountingError(
                        "payable_date must be on or after ex_date"
                    )
                first_expected_session_after(
                    event.payable_date,
                    expected_session_dates,
                )
    return ordered_events


def _apply_split_units(*, units: Decimal, split: DailyMarketDataSplit) -> Decimal:
    if units == 0:
        return Decimal("0")
    return _calculate_split_units(units=units, split=split)


def _calculate_split_units(*, units: Decimal, split: DailyMarketDataSplit) -> Decimal:
    if split.numerator <= 0 or split.denominator <= 0:
        raise EconomicAccountingError("split ratio values must be positive")
    with localcontext(_BENCHMARK_DECIMAL_CONTEXT):
        candidate = (
            units * Decimal(split.numerator) / Decimal(split.denominator)
        ).quantize(BENCHMARK_UNIT_QUANT)
    if candidate <= 0:
        raise EconomicAccountingError(
            "split cannot be represented by benchmark unit precision"
        )
    return quantize_benchmark_units(candidate)


def _parse_positive_money(value: object, *, field_name: str) -> Decimal:
    if isinstance(value, bool | float):
        raise EconomicAccountingError(
            f"{field_name} must be Decimal, string, or integer"
        )
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, int | str):
        parsed = Decimal(value)
    else:
        raise EconomicAccountingError(
            f"{field_name} must be Decimal, string, or integer"
        )
    if not parsed.is_finite() or parsed <= 0:
        raise EconomicAccountingError(f"{field_name} must be positive and finite")
    return parsed


def _validate_session_date(session_date: date) -> None:
    if type(session_date) is not date:
        raise EconomicAccountingError("session_date must contain a date value only")


__all__ = [
    "apply_session_open_benchmark_economic_accounting",
    "initialize_economic_benchmark",
    "value_economic_benchmark",
]
