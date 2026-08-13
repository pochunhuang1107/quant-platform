"""Pure S3d1 daily ETF economic-accounting functions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from backtest_engine.economic_models import (
    CashDistributionReceivable,
    CorporateActionAccountingRecord,
    EconomicAccountingError,
    EconomicPortfolioState,
    EconomicPortfolioValuation,
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
    DailyMarketDataUnsupportedCorporateAction,
    corporate_action_event_economic_date,
    corporate_action_event_sort_key,
)


def apply_session_open_economic_accounting(
    *,
    state: EconomicPortfolioState,
    session_date: date,
    expected_session_dates: tuple[date, ...],
    corporate_action_events: tuple[DailyMarketDataCorporateActionEvent, ...],
) -> tuple[EconomicPortfolioState, tuple[CorporateActionAccountingRecord, ...]]:
    """Apply deterministic pre-trading corporate-action accounting for one session."""

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

    records: list[CorporateActionAccountingRecord] = []
    cash = state.cash
    retained_receivables: list[CashDistributionReceivable] = []

    for receivable in state.receivables:
        if receivable.cash_available_session == session_date:
            cash = quantize_economic_money(cash + receivable.receivable_amount)
            records.append(
                CorporateActionAccountingRecord(
                    session_date=session_date,
                    event_id=receivable.event_id,
                    instrument_id=receivable.instrument_id,
                    event_type="cash_distribution",
                    accounting_action="cash_distribution_settlement",
                    pre_quantity=state.quantity,
                    post_quantity=state.quantity,
                    entitlement_quantity=receivable.entitled_quantity,
                    receivable_delta=-receivable.receivable_amount,
                    cash_delta=receivable.receivable_amount,
                )
            )
        else:
            retained_receivables.append(receivable)

    quantity = state.quantity
    applied_event_ids = set(state.applied_corporate_action_event_ids)

    for event in ordered_events:
        if isinstance(event, DailyMarketDataSplit):
            pre_quantity = quantity
            quantity = _apply_split_quantity(quantity=quantity, split=event)
            applied_event_ids.add(event.event_id)
            records.append(
                CorporateActionAccountingRecord(
                    session_date=session_date,
                    event_id=event.event_id,
                    instrument_id=event.instrument_id,
                    event_type="split",
                    accounting_action="split_applied",
                    pre_quantity=pre_quantity,
                    post_quantity=quantity,
                    entitlement_quantity=0,
                    receivable_delta=Decimal("0"),
                    cash_delta=Decimal("0"),
                )
            )

    new_receivables = list(retained_receivables)
    for event in ordered_events:
        if isinstance(event, DailyMarketDataCashDistribution):
            entitlement_quantity = quantity
            receivable_amount = Decimal("0")
            if entitlement_quantity > 0:
                receivable_amount = quantize_economic_money(
                    Decimal(entitlement_quantity) * event.amount
                )
                if event.payable_date is None:
                    raise EconomicAccountingError(
                        "entitled cash distribution requires payable_date"
                    )
                new_receivables.append(
                    CashDistributionReceivable(
                        event_id=event.event_id,
                        instrument_id=event.instrument_id,
                        ex_date=event.ex_date,
                        entitled_quantity=entitlement_quantity,
                        amount_per_share=event.amount,
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
                CorporateActionAccountingRecord(
                    session_date=session_date,
                    event_id=event.event_id,
                    instrument_id=event.instrument_id,
                    event_type="cash_distribution",
                    accounting_action="cash_distribution_entitlement",
                    pre_quantity=quantity,
                    post_quantity=quantity,
                    entitlement_quantity=entitlement_quantity,
                    receivable_delta=receivable_amount,
                    cash_delta=Decimal("0"),
                )
            )

    return (
        EconomicPortfolioState(
            instrument_id=state.instrument_id,
            currency=state.currency,
            cash=cash,
            quantity=quantity,
            total_book_cost=state.total_book_cost,
            receivables=tuple(
                sorted(
                    new_receivables,
                    key=lambda receivable: (
                        receivable.cash_available_session is None,
                        receivable.cash_available_session or date.max,
                        receivable.ex_date,
                        receivable.event_id,
                    ),
                )
            ),
            applied_corporate_action_event_ids=tuple(sorted(applied_event_ids)),
        ),
        tuple(records),
    )


def value_economic_portfolio(
    *,
    state: EconomicPortfolioState,
    session_date: date,
    market_price: Decimal,
) -> EconomicPortfolioValuation:
    """Value a single-instrument economic portfolio from supplied market price."""

    _validate_session_date(session_date)
    parsed_market_price = _parse_market_price(market_price)
    if not parsed_market_price.is_finite():
        raise EconomicAccountingError("market_price must be a finite Decimal")
    if parsed_market_price <= 0:
        raise EconomicAccountingError("market_price must be positive")

    quantized_market_price = quantize_economic_money(parsed_market_price)
    market_value = quantize_economic_money(
        Decimal(state.quantity) * quantized_market_price
    )
    receivable_value = quantize_economic_money(
        sum(
            (receivable.receivable_amount for receivable in state.receivables),
            Decimal("0"),
        )
    )
    total_equity = quantize_economic_money(state.cash + market_value + receivable_value)
    return EconomicPortfolioValuation(
        session_date=session_date,
        cash=state.cash,
        quantity=state.quantity,
        market_price=quantized_market_price,
        market_value=market_value,
        receivable_value=receivable_value,
        total_book_cost=state.total_book_cost,
        total_equity=total_equity,
    )


def _validate_current_session_events(
    *,
    state: EconomicPortfolioState,
    session_date: date,
    expected_session_dates: tuple[date, ...],
    corporate_action_events: tuple[DailyMarketDataCorporateActionEvent, ...],
) -> tuple[DailyMarketDataCorporateActionEvent, ...]:
    event_ids = tuple(event.event_id for event in corporate_action_events)
    if len(set(event_ids)) != len(event_ids):
        raise EconomicAccountingError("corporate_action_events contain duplicate IDs")
    already_applied = set(state.applied_corporate_action_event_ids)
    if already_applied.intersection(event_ids):
        raise EconomicAccountingError("corporate action event was already applied")

    splits: list[DailyMarketDataSplit] = []
    distributions: list[DailyMarketDataCashDistribution] = []
    for event in corporate_action_events:
        if corporate_action_event_economic_date(event) != session_date:
            raise EconomicAccountingError("event economic date must match session_date")
        if event.instrument_id != state.instrument_id:
            raise EconomicAccountingError("event instrument_id must match portfolio")
        if isinstance(event, DailyMarketDataUnsupportedCorporateAction):
            raise EconomicAccountingError("unsupported corporate action event")
        if isinstance(event, DailyMarketDataSplit):
            splits.append(event)
        elif isinstance(event, DailyMarketDataCashDistribution):
            if event.currency != state.currency:
                raise EconomicAccountingError("cash distribution currency mismatch")
            distributions.append(event)
        else:
            raise EconomicAccountingError("unknown corporate action event")

    if state.quantity > 0 and splits and distributions:
        raise EconomicAccountingError(
            "same-day split and cash distribution are ambiguous for held positions"
        )
    if state.quantity > 0 and len(splits) > 1:
        raise EconomicAccountingError("multiple same-day splits are unsupported")

    if state.quantity > 0:
        for split in splits:
            _validate_split_quantity(quantity=state.quantity, split=split)
        for distribution in distributions:
            if distribution.payable_date is None:
                raise EconomicAccountingError(
                    "entitled cash distribution requires payable_date"
                )
            if distribution.payable_date < distribution.ex_date:
                raise EconomicAccountingError(
                    "payable_date must be on or after ex_date"
                )
            first_expected_session_after(
                distribution.payable_date, expected_session_dates
            )

    return tuple(sorted(corporate_action_events, key=corporate_action_event_sort_key))


def _apply_split_quantity(*, quantity: int, split: DailyMarketDataSplit) -> int:
    if quantity == 0:
        return 0
    _validate_split_quantity(quantity=quantity, split=split)
    return (quantity * split.numerator) // split.denominator


def _validate_split_quantity(*, quantity: int, split: DailyMarketDataSplit) -> None:
    candidate_numerator = quantity * split.numerator
    if candidate_numerator % split.denominator != 0:
        raise EconomicAccountingError("split would produce fractional strategy shares")


def _parse_market_price(value: object) -> Decimal:
    if isinstance(value, bool | float):
        raise EconomicAccountingError(
            "market_price must be Decimal, string, or integer"
        )
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | str):
        return Decimal(value)
    raise EconomicAccountingError("market_price must be Decimal, string, or integer")


def _validate_session_date(session_date: date) -> None:
    if type(session_date) is not date:
        raise EconomicAccountingError("session_date must contain a date value only")


__all__ = [
    "apply_session_open_economic_accounting",
    "value_economic_portfolio",
]
