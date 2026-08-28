"""Fractional-unit economic models for the gross ETF benchmark."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal, Self

from pydantic import field_validator, model_validator

from backtest_engine.economic_models import (
    CorporateActionAccountingAction,
    CorporateActionEventTypeValue,
    EconomicAccountingModel,
    quantize_economic_money,
)

BENCHMARK_ECONOMIC_POLICY_VERSION = "daily-etf-gross-benchmark-economic-accounting-v1"
BENCHMARK_UNIT_QUANT = Decimal("0.000000000001")


class BenchmarkEconomicPolicy(EconomicAccountingModel):
    """Frozen policy for the first gross fractional ETF benchmark."""

    policy_version: Literal["daily-etf-gross-benchmark-economic-accounting-v1"] = (
        "daily-etf-gross-benchmark-economic-accounting-v1"
    )
    unit_policy: Literal["fractional_decimal_12"] = "fractional_decimal_12"
    price_policy: Literal["raw"] = "raw"
    cash_distribution_policy: Literal["explicit_receivable_retain_cash"] = (
        "explicit_receivable_retain_cash"
    )
    dividend_reinvestment: Literal[False] = False
    commission_policy: Literal["none"] = "none"
    slippage_policy: Literal["none"] = "none"


APPROVED_BENCHMARK_ECONOMIC_POLICY = BenchmarkEconomicPolicy()


class EconomicBenchmarkReceivable(EconomicAccountingModel):
    """Outstanding cash distribution earned by fractional benchmark units."""

    event_id: str
    instrument_id: str
    ex_date: date
    entitled_units: Decimal
    amount_per_unit: Decimal
    receivable_amount: Decimal
    currency: str
    payable_date: date
    cash_available_session: date | None

    @field_validator("event_id", "instrument_id", "currency")
    @classmethod
    def validate_nonblank_string(cls, value: str) -> str:
        return _validate_nonblank_string(value)

    @field_validator("entitled_units", mode="before")
    @classmethod
    def parse_units(cls, value: object) -> Decimal:
        return _parse_decimal(value, field_name="units")

    @field_validator("entitled_units")
    @classmethod
    def validate_positive_units(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("entitled_units must be positive")
        return quantize_benchmark_units(value)

    @field_validator("amount_per_unit", "receivable_amount", mode="before")
    @classmethod
    def parse_money(cls, value: object) -> Decimal:
        return _parse_decimal(value, field_name="money")

    @field_validator("amount_per_unit")
    @classmethod
    def validate_positive_amount_per_unit(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("amount_per_unit must be positive")
        return value

    @field_validator("receivable_amount")
    @classmethod
    def validate_positive_receivable_amount(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("receivable_amount must be positive")
        return quantize_economic_money(value)

    @model_validator(mode="after")
    def validate_receivable(self) -> Self:
        if self.payable_date < self.ex_date:
            raise ValueError("payable_date must be on or after ex_date")
        if (
            self.cash_available_session is not None
            and self.cash_available_session <= self.payable_date
        ):
            raise ValueError(
                "cash_available_session must be strictly after payable_date"
            )
        expected_amount = quantize_economic_money(
            self.entitled_units * self.amount_per_unit
        )
        if self.receivable_amount != expected_amount:
            raise ValueError(
                "receivable_amount must equal entitled_units times amount_per_unit"
            )
        return self


class EconomicBenchmarkState(EconomicAccountingModel):
    """Single-instrument gross benchmark state with fractional units."""

    policy_version: Literal["daily-etf-gross-benchmark-economic-accounting-v1"] = (
        "daily-etf-gross-benchmark-economic-accounting-v1"
    )
    instrument_id: str
    currency: str
    cash: Decimal
    fractional_units: Decimal
    receivables: tuple[EconomicBenchmarkReceivable, ...] = ()
    applied_corporate_action_event_ids: tuple[str, ...] = ()

    @field_validator("instrument_id", "currency")
    @classmethod
    def validate_nonblank_string(cls, value: str) -> str:
        return _validate_nonblank_string(value)

    @field_validator("cash", mode="before")
    @classmethod
    def parse_cash(cls, value: object) -> Decimal:
        return _parse_decimal(value, field_name="cash")

    @field_validator("cash")
    @classmethod
    def validate_nonnegative_cash(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("benchmark cash must be nonnegative")
        return quantize_economic_money(value)

    @field_validator("fractional_units", mode="before")
    @classmethod
    def parse_units(cls, value: object) -> Decimal:
        return _parse_decimal(value, field_name="units")

    @field_validator("fractional_units")
    @classmethod
    def validate_nonnegative_units(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("benchmark units must be nonnegative")
        return quantize_benchmark_units(value)

    @field_validator("applied_corporate_action_event_ids")
    @classmethod
    def validate_applied_event_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for event_id in value:
            _validate_nonblank_string(event_id)
        if len(set(value)) != len(value):
            raise ValueError("applied event IDs must be unique")
        if value != tuple(sorted(value)):
            raise ValueError("applied event IDs must use canonical order")
        return value

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        receivable_event_ids = tuple(
            receivable.event_id for receivable in self.receivables
        )
        if len(set(receivable_event_ids)) != len(receivable_event_ids):
            raise ValueError("receivable event IDs must be unique")
        for receivable in self.receivables:
            if receivable.instrument_id != self.instrument_id:
                raise ValueError("receivable instrument_id must match benchmark")
            if receivable.currency != self.currency:
                raise ValueError("receivable currency must match benchmark")
            if receivable.event_id not in self.applied_corporate_action_event_ids:
                raise ValueError("receivable event ID must be applied")
        object.__setattr__(
            self,
            "receivables",
            tuple(sorted(self.receivables, key=_receivable_sort_key)),
        )
        return self


class BenchmarkCorporateActionAccountingRecord(EconomicAccountingModel):
    """Audit record for one fractional benchmark accounting action."""

    session_date: date
    event_id: str
    instrument_id: str
    event_type: CorporateActionEventTypeValue
    accounting_action: CorporateActionAccountingAction
    pre_units: Decimal
    post_units: Decimal
    entitlement_units: Decimal
    receivable_delta: Decimal
    cash_delta: Decimal

    @field_validator("event_id", "instrument_id")
    @classmethod
    def validate_nonblank_string(cls, value: str) -> str:
        return _validate_nonblank_string(value)

    @field_validator("pre_units", "post_units", "entitlement_units", mode="before")
    @classmethod
    def parse_units(cls, value: object) -> Decimal:
        return _parse_decimal(value, field_name="units")

    @field_validator("pre_units", "post_units", "entitlement_units")
    @classmethod
    def validate_nonnegative_units(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("record units must be nonnegative")
        return quantize_benchmark_units(value)

    @field_validator("receivable_delta", "cash_delta", mode="before")
    @classmethod
    def parse_money(cls, value: object) -> Decimal:
        return _parse_decimal(value, field_name="money")

    @field_validator("receivable_delta", "cash_delta")
    @classmethod
    def quantize_money(cls, value: Decimal) -> Decimal:
        return quantize_economic_money(value)


class EconomicBenchmarkValuation(EconomicAccountingModel):
    """Gross benchmark valuation from raw price and explicit economics."""

    session_date: date
    cash: Decimal
    fractional_units: Decimal
    market_price: Decimal
    market_value: Decimal
    receivable_value: Decimal
    total_equity: Decimal

    @field_validator("fractional_units", mode="before")
    @classmethod
    def parse_units(cls, value: object) -> Decimal:
        return _parse_decimal(value, field_name="units")

    @field_validator("fractional_units")
    @classmethod
    def validate_nonnegative_units(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("benchmark units must be nonnegative")
        return quantize_benchmark_units(value)

    @field_validator(
        "cash",
        "market_price",
        "market_value",
        "receivable_value",
        "total_equity",
        mode="before",
    )
    @classmethod
    def parse_money(cls, value: object) -> Decimal:
        return _parse_decimal(value, field_name="money")

    @field_validator("cash", "market_value", "receivable_value", "total_equity")
    @classmethod
    def validate_nonnegative_money(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("valuation money values must be nonnegative")
        return quantize_economic_money(value)

    @field_validator("market_price")
    @classmethod
    def validate_market_price(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("market_price must be positive")
        return quantize_economic_money(value)

    @model_validator(mode="after")
    def validate_total_equity(self) -> Self:
        expected_total = quantize_economic_money(
            self.cash + self.market_value + self.receivable_value
        )
        if self.total_equity != expected_total:
            raise ValueError("total_equity must equal cash plus market and receivables")
        return self


def quantize_benchmark_units(value: Decimal) -> Decimal:
    """Quantize fractional units to the versioned twelve-decimal policy."""

    return value.quantize(BENCHMARK_UNIT_QUANT, rounding=ROUND_HALF_EVEN)


def _parse_decimal(value: object, *, field_name: str) -> Decimal:
    if isinstance(value, bool | float):
        raise ValueError(f"{field_name} must be Decimal, string, or integer")
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, int | str):
        parsed = Decimal(value)
    else:
        raise ValueError(f"{field_name} must be Decimal, string, or integer")
    if not parsed.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return parsed


def _validate_nonblank_string(value: str) -> str:
    if not value.strip():
        raise ValueError("string fields must not be blank")
    return value


def _receivable_sort_key(
    receivable: EconomicBenchmarkReceivable,
) -> tuple[bool, date, date, str]:
    return (
        receivable.cash_available_session is None,
        receivable.cash_available_session or date.max,
        receivable.ex_date,
        receivable.event_id,
    )


__all__ = [
    "APPROVED_BENCHMARK_ECONOMIC_POLICY",
    "BENCHMARK_ECONOMIC_POLICY_VERSION",
    "BENCHMARK_UNIT_QUANT",
    "BenchmarkCorporateActionAccountingRecord",
    "BenchmarkEconomicPolicy",
    "EconomicBenchmarkReceivable",
    "EconomicBenchmarkState",
    "EconomicBenchmarkValuation",
    "quantize_benchmark_units",
]
