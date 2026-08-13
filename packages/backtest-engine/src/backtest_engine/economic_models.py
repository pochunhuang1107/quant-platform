"""Engine-side economic accounting models for daily ETF positions."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal, Self

from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, field_validator, model_validator

ECONOMIC_ACCOUNTING_POLICY_VERSION = "daily-etf-economic-accounting-v1"
ECONOMIC_MONEY_QUANT = Decimal("0.000001")

CorporateActionAccountingAction = Literal[
    "split_applied",
    "cash_distribution_entitlement",
    "cash_distribution_settlement",
]
CorporateActionEventTypeValue = Literal[
    "cash_distribution",
    "split",
    "unsupported",
]


class EconomicAccountingError(ValueError):
    """Raised when economic accounting input cannot be applied deterministically."""


class EconomicAccountingModel(PydanticBaseModel):
    """Frozen operational model base for S3d1 accounting state."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class CashDistributionReceivable(EconomicAccountingModel):
    """Outstanding cash distribution economically earned but not spendable yet."""

    event_id: str
    instrument_id: str
    ex_date: date
    entitled_quantity: int
    amount_per_share: Decimal
    receivable_amount: Decimal
    currency: str
    payable_date: date
    cash_available_session: date | None

    @field_validator("event_id", "instrument_id", "currency")
    @classmethod
    def validate_nonblank_string(cls, value: str) -> str:
        return _validate_nonblank_string(value)

    @field_validator("amount_per_share", "receivable_amount", mode="before")
    @classmethod
    def parse_money(cls, value: object) -> Decimal:
        return _parse_decimal(value)

    @field_validator("amount_per_share")
    @classmethod
    def validate_positive_amount_per_share(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("amount_per_share must be positive")
        return value

    @field_validator("receivable_amount")
    @classmethod
    def validate_positive_receivable_amount(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("receivable_amount must be positive")
        return quantize_economic_money(value)

    @field_validator("entitled_quantity")
    @classmethod
    def validate_entitled_quantity(cls, value: int) -> int:
        if isinstance(value, bool) or value <= 0:
            raise ValueError("entitled_quantity must be a positive integer")
        return value

    @model_validator(mode="after")
    def validate_receivable_dates(self) -> Self:
        if self.payable_date < self.ex_date:
            raise ValueError("payable_date must be on or after ex_date")
        if (
            self.cash_available_session is not None
            and self.cash_available_session <= self.payable_date
        ):
            raise ValueError(
                "cash_available_session must be strictly after payable_date"
            )
        expected_receivable_amount = quantize_economic_money(
            Decimal(self.entitled_quantity) * self.amount_per_share
        )
        if self.receivable_amount != expected_receivable_amount:
            raise ValueError(
                "receivable_amount must equal entitled_quantity times amount_per_share"
            )
        return self


class EconomicPortfolioState(EconomicAccountingModel):
    """Single-instrument long-only strategy portfolio state."""

    instrument_id: str
    currency: str
    cash: Decimal
    quantity: int
    total_book_cost: Decimal
    receivables: tuple[CashDistributionReceivable, ...] = ()
    applied_corporate_action_event_ids: tuple[str, ...] = ()

    @field_validator("instrument_id", "currency")
    @classmethod
    def validate_nonblank_string(cls, value: str) -> str:
        return _validate_nonblank_string(value)

    @field_validator("cash", "total_book_cost", mode="before")
    @classmethod
    def parse_money(cls, value: object) -> Decimal:
        return _parse_decimal(value)

    @field_validator("cash", "total_book_cost")
    @classmethod
    def validate_nonnegative_money(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("portfolio money values must be nonnegative")
        return quantize_economic_money(value)

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, value: int) -> int:
        if isinstance(value, bool) or value < 0:
            raise ValueError("quantity must be a nonnegative integer")
        return value

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
        if self.quantity == 0 and self.total_book_cost != 0:
            raise ValueError("quantity zero requires zero total_book_cost")

        receivable_event_ids = tuple(
            receivable.event_id for receivable in self.receivables
        )
        if len(set(receivable_event_ids)) != len(receivable_event_ids):
            raise ValueError("receivable event IDs must be unique")
        for receivable in self.receivables:
            if receivable.instrument_id != self.instrument_id:
                raise ValueError("receivable instrument_id must match portfolio")
            if receivable.currency != self.currency:
                raise ValueError("receivable currency must match portfolio")
            if receivable.event_id not in self.applied_corporate_action_event_ids:
                raise ValueError("receivable event ID must be applied")
        object.__setattr__(
            self,
            "receivables",
            tuple(sorted(self.receivables, key=_receivable_sort_key)),
        )
        return self


class CorporateActionAccountingRecord(EconomicAccountingModel):
    """Operational audit record for mechanical corporate-action accounting."""

    session_date: date
    event_id: str
    instrument_id: str
    event_type: CorporateActionEventTypeValue
    accounting_action: CorporateActionAccountingAction
    pre_quantity: int
    post_quantity: int
    entitlement_quantity: int
    receivable_delta: Decimal
    cash_delta: Decimal

    @field_validator("event_id", "instrument_id")
    @classmethod
    def validate_nonblank_string(cls, value: str) -> str:
        return _validate_nonblank_string(value)

    @field_validator("receivable_delta", "cash_delta", mode="before")
    @classmethod
    def parse_money(cls, value: object) -> Decimal:
        return _parse_decimal(value)

    @field_validator("receivable_delta", "cash_delta")
    @classmethod
    def quantize_money(cls, value: Decimal) -> Decimal:
        return quantize_economic_money(value)

    @field_validator("pre_quantity", "post_quantity", "entitlement_quantity")
    @classmethod
    def validate_quantity(cls, value: int) -> int:
        if isinstance(value, bool) or value < 0:
            raise ValueError("record quantities must be nonnegative integers")
        return value


class EconomicPortfolioValuation(EconomicAccountingModel):
    """Additive daily economic valuation including outstanding receivables."""

    session_date: date
    cash: Decimal
    quantity: int
    market_price: Decimal
    market_value: Decimal
    receivable_value: Decimal
    total_book_cost: Decimal
    total_equity: Decimal

    @field_validator(
        "cash",
        "market_price",
        "market_value",
        "receivable_value",
        "total_book_cost",
        "total_equity",
        mode="before",
    )
    @classmethod
    def parse_money(cls, value: object) -> Decimal:
        return _parse_decimal(value)

    @field_validator(
        "cash",
        "market_value",
        "receivable_value",
        "total_book_cost",
        "total_equity",
    )
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

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, value: int) -> int:
        if isinstance(value, bool) or value < 0:
            raise ValueError("quantity must be a nonnegative integer")
        return value

    @model_validator(mode="after")
    def validate_total_equity(self) -> Self:
        expected_total = quantize_economic_money(
            self.cash + self.market_value + self.receivable_value
        )
        if self.total_equity != expected_total:
            raise ValueError("total_equity must equal cash plus market and receivables")
        return self


def quantize_economic_money(value: Decimal) -> Decimal:
    """Quantize S3d1 monetary values without reading global Decimal context."""

    return value.quantize(ECONOMIC_MONEY_QUANT, rounding=ROUND_HALF_EVEN)


def _parse_decimal(value: object) -> Decimal:
    if isinstance(value, bool | float):
        raise ValueError("money values must be Decimal, string, or integer")
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, int | str):
        parsed = Decimal(value)
    else:
        raise ValueError("money values must be Decimal, string, or integer")
    if not parsed.is_finite():
        raise ValueError("money values must be finite")
    return parsed


def _validate_nonblank_string(value: str) -> str:
    if not value.strip():
        raise ValueError("string fields must not be blank")
    return value


def _receivable_sort_key(
    receivable: CashDistributionReceivable,
) -> tuple[bool, date, date, str]:
    return (
        receivable.cash_available_session is None,
        receivable.cash_available_session or date.max,
        receivable.ex_date,
        receivable.event_id,
    )


__all__ = [
    "ECONOMIC_ACCOUNTING_POLICY_VERSION",
    "ECONOMIC_MONEY_QUANT",
    "CashDistributionReceivable",
    "CorporateActionAccountingAction",
    "CorporateActionAccountingRecord",
    "CorporateActionEventTypeValue",
    "EconomicAccountingError",
    "EconomicPortfolioState",
    "EconomicPortfolioValuation",
    "quantize_economic_money",
]
