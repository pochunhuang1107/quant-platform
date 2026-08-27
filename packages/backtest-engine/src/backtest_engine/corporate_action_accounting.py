"""Shared fail-closed validation for daily corporate-action accounting."""

from __future__ import annotations

from datetime import date

from backtest_engine.economic_models import EconomicAccountingError
from research_sdk.contracts.daily_market_data_economics import (
    DailyMarketDataCashDistribution,
    DailyMarketDataCorporateActionEvent,
    DailyMarketDataSplit,
    DailyMarketDataUnsupportedCorporateAction,
    corporate_action_event_economic_date,
    corporate_action_event_sort_key,
)


def validate_and_order_session_corporate_action_events(
    *,
    session_date: date,
    instrument_id: str,
    currency: str,
    has_held_position: bool,
    applied_event_ids: tuple[str, ...],
    corporate_action_events: tuple[DailyMarketDataCorporateActionEvent, ...],
) -> tuple[DailyMarketDataCorporateActionEvent, ...]:
    """Validate shared event authority before any portfolio state mutation."""

    event_ids = tuple(event.event_id for event in corporate_action_events)
    if len(set(event_ids)) != len(event_ids):
        raise EconomicAccountingError("corporate_action_events contain duplicate IDs")
    if set(applied_event_ids).intersection(event_ids):
        raise EconomicAccountingError("corporate action event was already applied")

    splits: list[DailyMarketDataSplit] = []
    distributions: list[DailyMarketDataCashDistribution] = []
    for event in corporate_action_events:
        if corporate_action_event_economic_date(event) != session_date:
            raise EconomicAccountingError("event economic date must match session_date")
        if event.instrument_id != instrument_id:
            raise EconomicAccountingError("event instrument_id must match portfolio")
        if isinstance(event, DailyMarketDataUnsupportedCorporateAction):
            raise EconomicAccountingError("unsupported corporate action event")
        if isinstance(event, DailyMarketDataSplit):
            splits.append(event)
        elif isinstance(event, DailyMarketDataCashDistribution):
            if event.currency != currency:
                raise EconomicAccountingError("cash distribution currency mismatch")
            distributions.append(event)
        else:
            raise EconomicAccountingError("unknown corporate action event")

    if has_held_position and splits and distributions:
        raise EconomicAccountingError(
            "same-day split and cash distribution are ambiguous for held positions"
        )
    if has_held_position and len(splits) > 1:
        raise EconomicAccountingError("multiple same-day splits are unsupported")

    return tuple(sorted(corporate_action_events, key=corporate_action_event_sort_key))


__all__ = ["validate_and_order_session_corporate_action_events"]
