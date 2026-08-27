"""Pure deterministic execution transitions for the QQQ baseline."""

from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal
from typing import Self

from pydantic import field_validator, model_validator

from backtest_engine.economic_models import (
    EconomicAccountingError,
    EconomicAccountingModel,
    EconomicPortfolioState,
    quantize_economic_money,
)
from backtest_engine.models import BasisPointAssumption

_BPS_DENOMINATOR = Decimal("10000")


class EconomicBuyFill(EconomicAccountingModel):
    """Resolved economics for one integer-share strategy buy."""

    quantity: int
    raw_price: Decimal
    fill_price: Decimal
    commission_bps: Decimal
    slippage_bps: Decimal
    executed_notional: Decimal
    commission: Decimal
    slippage: Decimal
    total_cash_spent: Decimal

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, value: int) -> int:
        if isinstance(value, bool) or value <= 0:
            raise ValueError("quantity must be a positive integer")
        return value

    @field_validator(
        "raw_price",
        "fill_price",
        "commission_bps",
        "slippage_bps",
        "executed_notional",
        "commission",
        "slippage",
        "total_cash_spent",
        mode="before",
    )
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return _parse_decimal(value)

    @field_validator("raw_price", "fill_price")
    @classmethod
    def validate_positive_price(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("prices must be positive")
        return quantize_economic_money(value)

    @field_validator("commission_bps", "slippage_bps")
    @classmethod
    def validate_nonnegative_bps(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("basis points must be nonnegative")
        return value

    @field_validator("executed_notional", "commission", "slippage", "total_cash_spent")
    @classmethod
    def validate_nonnegative_money(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("fill money values must be nonnegative")
        return quantize_economic_money(value)

    @model_validator(mode="after")
    def validate_fill_consistency(self) -> Self:
        expected_notional = quantize_economic_money(
            Decimal(self.quantity) * self.fill_price
        )
        expected_commission = quantize_economic_money(
            expected_notional * self.commission_bps / _BPS_DENOMINATOR
        )
        expected_slippage = quantize_economic_money(
            Decimal(self.quantity) * (self.fill_price - self.raw_price)
        )
        expected_cash_spent = quantize_economic_money(
            expected_notional + expected_commission
        )
        if self.executed_notional != expected_notional:
            raise ValueError("executed_notional must equal quantity times fill_price")
        if self.commission != expected_commission:
            raise ValueError("commission must match commission basis points")
        if self.slippage != expected_slippage:
            raise ValueError("slippage must match raw-to-fill price difference")
        if self.total_cash_spent != expected_cash_spent:
            raise ValueError(
                "total_cash_spent must equal executed_notional plus commission"
            )
        return self


def apply_initial_integer_buy(
    *,
    state: EconomicPortfolioState,
    raw_execution_price: Decimal,
    commission: BasisPointAssumption,
    slippage: BasisPointAssumption,
) -> tuple[EconomicPortfolioState, EconomicBuyFill]:
    """Invest available strategy cash in one deterministic integer-share buy."""

    if state.quantity != 0 or state.total_book_cost != 0:
        raise EconomicAccountingError(
            "initial buy requires zero quantity and zero total_book_cost"
        )
    if state.receivables:
        raise EconomicAccountingError("initial buy state must not have receivables")

    raw_price = quantize_economic_money(
        _parse_positive_decimal(
            raw_execution_price,
            field_name="raw_execution_price",
        )
    )
    slippage_rate = slippage.bps / _BPS_DENOMINATOR
    commission_rate = commission.bps / _BPS_DENOMINATOR
    fill_price = quantize_economic_money(raw_price * (Decimal("1") + slippage_rate))
    per_share_cash_required = fill_price * (Decimal("1") + commission_rate)
    quantity = int(
        (state.cash / per_share_cash_required).to_integral_value(rounding=ROUND_FLOOR)
    )
    if quantity <= 0:
        raise EconomicAccountingError("initial capital cannot buy one QQQ share")

    executed_notional = quantize_economic_money(Decimal(quantity) * fill_price)
    realized_commission = quantize_economic_money(executed_notional * commission_rate)
    realized_slippage = quantize_economic_money(
        Decimal(quantity) * (fill_price - raw_price)
    )
    total_cash_spent = quantize_economic_money(executed_notional + realized_commission)
    ending_cash = quantize_economic_money(state.cash - total_cash_spent)
    if ending_cash < 0:
        raise EconomicAccountingError("buy transition cannot create negative cash")

    fill = EconomicBuyFill(
        quantity=quantity,
        raw_price=raw_price,
        fill_price=fill_price,
        commission_bps=commission.bps,
        slippage_bps=slippage.bps,
        executed_notional=executed_notional,
        commission=realized_commission,
        slippage=realized_slippage,
        total_cash_spent=total_cash_spent,
    )
    new_state = EconomicPortfolioState(
        instrument_id=state.instrument_id,
        currency=state.currency,
        cash=ending_cash,
        quantity=quantity,
        total_book_cost=total_cash_spent,
        receivables=state.receivables,
        applied_corporate_action_event_ids=(state.applied_corporate_action_event_ids),
    )
    return new_state, fill


def _parse_decimal(value: object) -> Decimal:
    if isinstance(value, bool | float):
        raise ValueError("decimal values must be Decimal, string, or integer")
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, int | str):
        parsed = Decimal(value)
    else:
        raise ValueError("decimal values must be Decimal, string, or integer")
    if not parsed.is_finite():
        raise ValueError("decimal values must be finite")
    return parsed


def _parse_positive_decimal(value: object, *, field_name: str) -> Decimal:
    try:
        parsed = _parse_decimal(value)
    except ValueError as exc:
        raise EconomicAccountingError(f"{field_name} must be finite Decimal") from exc
    if parsed <= 0:
        raise EconomicAccountingError(f"{field_name} must be positive")
    return parsed


__all__ = [
    "EconomicBuyFill",
    "apply_initial_integer_buy",
]
