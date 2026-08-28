from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from backtest_engine.benchmark_economic_accounting import (
    apply_session_open_benchmark_economic_accounting,
    initialize_economic_benchmark,
    value_economic_benchmark,
)
from backtest_engine.benchmark_economic_models import (
    APPROVED_BENCHMARK_ECONOMIC_POLICY,
    BENCHMARK_ECONOMIC_POLICY_VERSION,
    BENCHMARK_UNIT_QUANT,
    EconomicBenchmarkState,
)
from backtest_engine.economic_models import EconomicAccountingError
from research_sdk.contracts.daily_market_data_economics import (
    DailyMarketDataCashDistribution,
    DailyMarketDataSplit,
    DailyMarketDataUnsupportedCorporateAction,
)

INSTRUMENT_ID = "instrument-us-etf-spy-arcx"
SESSIONS = (
    date(2026, 1, 2),
    date(2026, 1, 5),
    date(2026, 1, 6),
    date(2026, 1, 9),
)


def test_benchmark_policy_is_explicit_and_frozen() -> None:
    policy = APPROVED_BENCHMARK_ECONOMIC_POLICY

    assert BENCHMARK_ECONOMIC_POLICY_VERSION == (
        "daily-etf-gross-benchmark-economic-accounting-v1"
    )
    assert BENCHMARK_UNIT_QUANT == Decimal("0.000000000001")
    assert policy.unit_policy == "fractional_decimal_12"
    assert policy.price_policy == "raw"
    assert policy.cash_distribution_policy == "explicit_receivable_retain_cash"
    assert policy.dividend_reinvestment is False
    assert policy.commission_policy == "none"
    assert policy.slippage_policy == "none"


def test_initialization_normalizes_fractional_units_without_costs() -> None:
    state = initialize_economic_benchmark(
        instrument_id=INSTRUMENT_ID,
        currency="USD",
        initial_capital=Decimal("100000"),
        raw_execution_price=Decimal("503.123456"),
    )
    valuation = value_economic_benchmark(
        state=state,
        session_date=SESSIONS[0],
        raw_market_price=Decimal("503.123456"),
    )

    assert state.fractional_units == Decimal("198.758373928803")
    assert state.cash == Decimal("0.000000")
    assert valuation.total_equity == Decimal("100000.000000")
    assert not contains_float(state.model_dump(mode="python"))


def test_fractional_units_earn_exact_ex_date_receivable() -> None:
    state = benchmark_state(units=Decimal("10.500000000000"))

    new_state, records = apply_session_open_benchmark_economic_accounting(
        state=state,
        session_date=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
        corporate_action_events=(
            distribution_event(
                "dist-fractional",
                ex_date=date(2026, 1, 5),
                amount=Decimal("0.40"),
                payable_date=date(2026, 1, 5),
            ),
        ),
    )

    receivable = new_state.receivables[0]
    assert receivable.entitled_units == Decimal("10.500000000000")
    assert receivable.receivable_amount == Decimal("4.200000")
    assert receivable.cash_available_session == date(2026, 1, 6)
    assert records[0].entitlement_units == Decimal("10.500000000000")
    assert records[0].receivable_delta == Decimal("4.200000")


def test_receivable_immediately_offsets_raw_ex_date_price_drop() -> None:
    state = benchmark_state(units=Decimal("10.500000000000"))
    before = value_economic_benchmark(
        state=state,
        session_date=date(2026, 1, 2),
        raw_market_price=Decimal("100.40"),
    )
    entitled_state, _records = apply_session_open_benchmark_economic_accounting(
        state=state,
        session_date=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
        corporate_action_events=(
            distribution_event(
                "dist-offset",
                ex_date=date(2026, 1, 5),
                amount=Decimal("0.40"),
                payable_date=date(2026, 1, 5),
            ),
        ),
    )
    after = value_economic_benchmark(
        state=entitled_state,
        session_date=date(2026, 1, 5),
        raw_market_price=Decimal("100.00"),
    )

    assert before.total_equity == after.total_equity == Decimal("1054.200000")
    assert after.receivable_value == Decimal("4.200000")


def test_settlement_preserves_equity_and_retains_cash_without_reinvestment() -> None:
    entitled_state, _records = apply_session_open_benchmark_economic_accounting(
        state=benchmark_state(units=Decimal("10.500000000000")),
        session_date=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
        corporate_action_events=(
            distribution_event(
                "dist-settle",
                ex_date=date(2026, 1, 5),
                amount=Decimal("0.40"),
                payable_date=date(2026, 1, 5),
            ),
        ),
    )
    before = value_economic_benchmark(
        state=entitled_state,
        session_date=date(2026, 1, 5),
        raw_market_price=Decimal("100"),
    )

    settled_state, records = apply_session_open_benchmark_economic_accounting(
        state=entitled_state,
        session_date=date(2026, 1, 6),
        expected_session_dates=SESSIONS,
        corporate_action_events=(),
    )
    after = value_economic_benchmark(
        state=settled_state,
        session_date=date(2026, 1, 6),
        raw_market_price=Decimal("100"),
    )

    assert before.total_equity == after.total_equity == Decimal("1054.200000")
    assert settled_state.cash == Decimal("4.200000")
    assert settled_state.fractional_units == Decimal("10.500000000000")
    assert settled_state.receivables == ()
    assert records[0].accounting_action == "cash_distribution_settlement"
    assert records[0].cash_delta == Decimal("4.200000")


def test_receivable_after_horizon_remains_in_state_and_equity() -> None:
    new_state, _records = apply_session_open_benchmark_economic_accounting(
        state=benchmark_state(units=Decimal("7.250000000000")),
        session_date=date(2026, 1, 9),
        expected_session_dates=SESSIONS,
        corporate_action_events=(
            distribution_event(
                "dist-outstanding",
                ex_date=date(2026, 1, 9),
                amount=Decimal("0.25"),
                payable_date=date(2026, 1, 12),
            ),
        ),
    )
    valuation = value_economic_benchmark(
        state=new_state,
        session_date=date(2026, 1, 9),
        raw_market_price=Decimal("100"),
    )

    assert new_state.receivables[0].cash_available_session is None
    assert valuation.receivable_value == Decimal("1.812500")
    assert valuation.total_equity == Decimal("726.812500")


def test_entitled_distribution_without_payable_date_fails_atomically() -> None:
    state = benchmark_state(units=Decimal("10.5"))

    with pytest.raises(EconomicAccountingError, match="requires payable_date"):
        apply_session_open_benchmark_economic_accounting(
            state=state,
            session_date=date(2026, 1, 5),
            expected_session_dates=SESSIONS,
            corporate_action_events=(
                distribution_event(
                    "dist-no-payable",
                    ex_date=date(2026, 1, 5),
                    payable_date=None,
                ),
            ),
        )

    assert state.receivables == ()
    assert state.applied_corporate_action_event_ids == ()


def test_forward_split_preserves_fractional_economic_value() -> None:
    state = benchmark_state(units=Decimal("10.500000000000"))
    before = value_economic_benchmark(
        state=state,
        session_date=date(2026, 1, 2),
        raw_market_price=Decimal("100"),
    )

    split_state, records = apply_session_open_benchmark_economic_accounting(
        state=state,
        session_date=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
        corporate_action_events=(
            split_event("split-forward", effective_date=date(2026, 1, 5)),
        ),
    )
    after = value_economic_benchmark(
        state=split_state,
        session_date=date(2026, 1, 5),
        raw_market_price=Decimal("50"),
    )

    assert split_state.fractional_units == Decimal("21.000000000000")
    assert before.total_equity == after.total_equity == Decimal("1050.000000")
    assert records[0].cash_delta == Decimal("0.000000")


def test_reverse_split_preserves_fractional_units_and_economic_value() -> None:
    state = benchmark_state(units=Decimal("10.500000000000"))
    before = value_economic_benchmark(
        state=state,
        session_date=date(2026, 1, 2),
        raw_market_price=Decimal("100"),
    )

    split_state, _records = apply_session_open_benchmark_economic_accounting(
        state=state,
        session_date=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
        corporate_action_events=(
            split_event(
                "split-reverse",
                effective_date=date(2026, 1, 5),
                numerator=1,
                denominator=3,
            ),
        ),
    )
    after = value_economic_benchmark(
        state=split_state,
        session_date=date(2026, 1, 5),
        raw_market_price=Decimal("300"),
    )

    assert split_state.fractional_units == Decimal("3.500000000000")
    assert before.total_equity == after.total_equity == Decimal("1050.000000")


def test_malformed_split_factor_is_rejected_by_event_contract() -> None:
    with pytest.raises(ValidationError, match="greater than 0"):
        split_event(
            "split-malformed",
            effective_date=date(2026, 1, 5),
            denominator=0,
        )


def test_duplicate_event_in_same_call_fails_closed() -> None:
    event = distribution_event(
        "dist-duplicate-call",
        ex_date=date(2026, 1, 5),
        payable_date=date(2026, 1, 5),
    )

    with pytest.raises(EconomicAccountingError, match="duplicate IDs"):
        apply_session_open_benchmark_economic_accounting(
            state=benchmark_state(units=Decimal("10.5")),
            session_date=date(2026, 1, 5),
            expected_session_dates=SESSIONS,
            corporate_action_events=(event, event),
        )


def test_duplicate_applied_event_fails_closed() -> None:
    state = benchmark_state(
        units=Decimal("10.5"),
        applied_event_ids=("dist-applied",),
    )

    with pytest.raises(EconomicAccountingError, match="already applied"):
        apply_session_open_benchmark_economic_accounting(
            state=state,
            session_date=date(2026, 1, 5),
            expected_session_dates=SESSIONS,
            corporate_action_events=(
                distribution_event(
                    "dist-applied",
                    ex_date=date(2026, 1, 5),
                    payable_date=date(2026, 1, 5),
                ),
            ),
        )


def test_unsupported_event_fails_closed() -> None:
    with pytest.raises(EconomicAccountingError, match="unsupported"):
        apply_session_open_benchmark_economic_accounting(
            state=benchmark_state(units=Decimal("10.5")),
            session_date=date(2026, 1, 5),
            expected_session_dates=SESSIONS,
            corporate_action_events=(
                unsupported_event(
                    "unsupported",
                    effective_date=date(2026, 1, 5),
                ),
            ),
        )


def test_same_day_split_and_distribution_with_units_fails_atomically() -> None:
    state = benchmark_state(units=Decimal("10.5"))

    with pytest.raises(EconomicAccountingError, match="ambiguous"):
        apply_session_open_benchmark_economic_accounting(
            state=state,
            session_date=date(2026, 1, 5),
            expected_session_dates=SESSIONS,
            corporate_action_events=(
                split_event("split-ambiguous", effective_date=date(2026, 1, 5)),
                distribution_event(
                    "dist-ambiguous",
                    ex_date=date(2026, 1, 5),
                    payable_date=date(2026, 1, 5),
                ),
            ),
        )

    assert state.fractional_units == Decimal("10.500000000000")
    assert state.applied_corporate_action_event_ids == ()


def test_cash_distribution_event_order_is_deterministic() -> None:
    state = benchmark_state(units=Decimal("10.5"))
    event_a = distribution_event(
        "dist-a",
        ex_date=date(2026, 1, 5),
        payable_date=date(2026, 1, 5),
    )
    event_b = distribution_event(
        "dist-b",
        ex_date=date(2026, 1, 5),
        payable_date=date(2026, 1, 5),
    )

    state_ab, records_ab = apply_session_open_benchmark_economic_accounting(
        state=state,
        session_date=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
        corporate_action_events=(event_a, event_b),
    )
    state_ba, records_ba = apply_session_open_benchmark_economic_accounting(
        state=state,
        session_date=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
        corporate_action_events=(event_b, event_a),
    )

    assert state_ab == state_ba
    assert records_ab == records_ba
    assert tuple(record.event_id for record in records_ab) == ("dist-a", "dist-b")


def test_repeated_benchmark_inputs_produce_identical_state() -> None:
    kwargs = {
        "state": benchmark_state(units=Decimal("10.5")),
        "session_date": date(2026, 1, 5),
        "expected_session_dates": SESSIONS,
        "corporate_action_events": (
            distribution_event(
                "dist-replay",
                ex_date=date(2026, 1, 5),
                amount=Decimal("0.3333335"),
                payable_date=date(2026, 1, 5),
            ),
        ),
    }

    first = apply_session_open_benchmark_economic_accounting(**kwargs)
    second = apply_session_open_benchmark_economic_accounting(**kwargs)

    assert first == second
    assert first[0].receivables[0].receivable_amount == Decimal("3.500002")
    assert not contains_float(first[0].model_dump(mode="python"))


def benchmark_state(
    *,
    units: Decimal,
    cash: Decimal = Decimal("0"),
    applied_event_ids: tuple[str, ...] = (),
) -> EconomicBenchmarkState:
    return EconomicBenchmarkState(
        instrument_id=INSTRUMENT_ID,
        currency="USD",
        cash=cash,
        fractional_units=units,
        applied_corporate_action_event_ids=applied_event_ids,
    )


def split_event(
    event_id: str,
    *,
    effective_date: date,
    numerator: int = 2,
    denominator: int = 1,
) -> DailyMarketDataSplit:
    return DailyMarketDataSplit(
        schema_version="1.0.0",
        event_id=event_id,
        instrument_id=INSTRUMENT_ID,
        source_event_reference=f"synthetic://{event_id}",
        source_available_at=datetime(2026, 1, 2, tzinfo=UTC),
        effective_date=effective_date,
        numerator=numerator,
        denominator=denominator,
    )


def distribution_event(
    event_id: str,
    *,
    ex_date: date,
    payable_date: date | None,
    amount: Decimal = Decimal("0.50"),
) -> DailyMarketDataCashDistribution:
    return DailyMarketDataCashDistribution(
        schema_version="1.0.0",
        event_id=event_id,
        instrument_id=INSTRUMENT_ID,
        source_event_reference=f"synthetic://{event_id}",
        source_available_at=datetime(2026, 1, 2, tzinfo=UTC),
        ex_date=ex_date,
        amount=amount,
        currency="USD",
        payable_date=payable_date,
    )


def unsupported_event(
    event_id: str,
    *,
    effective_date: date,
) -> DailyMarketDataUnsupportedCorporateAction:
    return DailyMarketDataUnsupportedCorporateAction(
        schema_version="1.0.0",
        event_id=event_id,
        instrument_id=INSTRUMENT_ID,
        source_event_reference=f"synthetic://{event_id}",
        source_available_at=datetime(2026, 1, 2, tzinfo=UTC),
        effective_date=effective_date,
        provider_event_type="merger",
        description="unsupported synthetic event",
    )


def contains_float(value: Any) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(contains_float(inner) for inner in value.values())
    if isinstance(value, list | tuple):
        return any(contains_float(inner) for inner in value)
    return False
