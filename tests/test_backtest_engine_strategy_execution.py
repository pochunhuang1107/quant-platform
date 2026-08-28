from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from backtest_engine.economic_models import (
    EconomicAccountingError,
    EconomicPortfolioState,
)
from backtest_engine.models import BasisPointAssumption
from backtest_engine.strategy_execution import apply_initial_integer_buy

INSTRUMENT_ID = "instrument-us-etf-qqq-xnas"
COMMISSION = BasisPointAssumption(
    bps=Decimal("1"),
    description="1 basis point commission on executed notional",
)
SLIPPAGE = BasisPointAssumption(
    bps=Decimal("2"),
    description="2 basis points buy slippage",
)


def test_initial_buy_matches_raw_open_slippage_commission_and_integer_quantity() -> (
    None
):
    new_state, fill = apply_initial_integer_buy(
        state=empty_state(cash=Decimal("100000")),
        raw_execution_price=Decimal("100"),
        commission=COMMISSION,
        slippage=SLIPPAGE,
    )

    assert fill.raw_price == Decimal("100.000000")
    assert fill.fill_price == Decimal("100.020000")
    assert fill.quantity == 999
    assert fill.executed_notional == Decimal("99919.980000")
    assert fill.slippage == Decimal("19.980000")
    assert fill.commission == Decimal("9.991998")
    assert fill.total_cash_spent == Decimal("99929.971998")
    assert new_state.quantity == 999
    assert new_state.cash == Decimal("70.028002")
    assert new_state.total_book_cost == Decimal("99929.971998")


def test_initial_buy_preserves_prior_zero_holding_event_authority() -> None:
    state = EconomicPortfolioState(
        instrument_id=INSTRUMENT_ID,
        currency="USD",
        cash=Decimal("100000"),
        quantity=0,
        total_book_cost=Decimal("0"),
        applied_corporate_action_event_ids=("split-before-buy",),
    )

    new_state, _fill = apply_initial_integer_buy(
        state=state,
        raw_execution_price=Decimal("100"),
        commission=COMMISSION,
        slippage=SLIPPAGE,
    )

    assert new_state.applied_corporate_action_event_ids == ("split-before-buy",)


def test_initial_buy_with_insufficient_cash_matches_legacy_failure() -> None:
    with pytest.raises(
        EconomicAccountingError,
        match="initial capital cannot buy one QQQ share",
    ):
        apply_initial_integer_buy(
            state=empty_state(cash=Decimal("100")),
            raw_execution_price=Decimal("100"),
            commission=COMMISSION,
            slippage=SLIPPAGE,
        )


def test_initial_buy_rejects_existing_position() -> None:
    state = EconomicPortfolioState(
        instrument_id=INSTRUMENT_ID,
        currency="USD",
        cash=Decimal("1000"),
        quantity=1,
        total_book_cost=Decimal("100"),
    )

    with pytest.raises(EconomicAccountingError, match="requires zero quantity"):
        apply_initial_integer_buy(
            state=state,
            raw_execution_price=Decimal("100"),
            commission=COMMISSION,
            slippage=SLIPPAGE,
        )


def test_initial_buy_rejects_binary_float_price() -> None:
    with pytest.raises(EconomicAccountingError, match="finite Decimal"):
        apply_initial_integer_buy(
            state=empty_state(cash=Decimal("100000")),
            raw_execution_price=100.0,  # type: ignore[arg-type]
            commission=COMMISSION,
            slippage=SLIPPAGE,
        )


def test_initial_buy_replay_is_deterministic_and_contains_no_float() -> None:
    kwargs = {
        "state": empty_state(cash=Decimal("100000")),
        "raw_execution_price": Decimal("100"),
        "commission": COMMISSION,
        "slippage": SLIPPAGE,
    }

    first = apply_initial_integer_buy(**kwargs)
    second = apply_initial_integer_buy(**kwargs)

    assert first == second
    assert not contains_float(first[0].model_dump(mode="python"))
    assert not contains_float(first[1].model_dump(mode="python"))


def empty_state(*, cash: Decimal) -> EconomicPortfolioState:
    return EconomicPortfolioState(
        instrument_id=INSTRUMENT_ID,
        currency="USD",
        cash=cash,
        quantity=0,
        total_book_cost=Decimal("0"),
    )


def contains_float(value: Any) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(contains_float(inner) for inner in value.values())
    if isinstance(value, list | tuple):
        return any(contains_float(inner) for inner in value)
    return False
