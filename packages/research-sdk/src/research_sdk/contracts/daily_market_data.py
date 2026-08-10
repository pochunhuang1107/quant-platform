"""Provider-neutral daily market-data policy and quality contracts."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from research_sdk.contracts.base import BaseContractModel
from research_sdk.contracts.enums import AssetClass, DataAdjustmentPolicy
from research_sdk.contracts.schema import VersionedContract
from research_sdk.contracts.types import NonEmptyString

DAILY_MARKET_DATA_FREQUENCY = "daily"
SHA256_CONTENT_HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class DistributionTreatment(StrEnum):
    """Explicit distribution handling for daily market-data research policy."""

    EXPLICIT_CASH = "explicit_cash"
    EXCLUDED_PRICE_RETURN_ONLY = "excluded_price_return_only"


class DailyMarketDataQualityStatus(StrEnum):
    """Deterministic quality report status."""

    PASS = "pass"
    FAIL = "fail"


class DailyMarketDataQualityCode(StrEnum):
    """Stable machine-readable daily market-data quality codes."""

    DUPLICATE_SESSION = "duplicate_session"
    MISSING_SESSION = "missing_session"
    UNEXPECTED_SESSION = "unexpected_session"
    ZERO_VOLUME = "zero_volume"


class DailyMarketDataInstrument(BaseContractModel):
    """Platform-facing provider-neutral instrument reference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: NonEmptyString
    symbol: NonEmptyString
    venue: NonEmptyString


class CanonicalDailyBar(BaseContractModel):
    """Provider-neutral canonical daily OHLCV bar."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int = Field(ge=0)

    @field_validator("open", "high", "low", "close", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        """Parse Decimal values without accepting binary floating point."""

        if isinstance(value, bool | float):
            raise ValueError("daily bar prices must be Decimal, string, or integer")
        if isinstance(value, Decimal):
            parsed = value
        elif isinstance(value, int | str):
            parsed = Decimal(value)
        else:
            raise ValueError("daily bar prices must be Decimal, string, or integer")
        if not parsed.is_finite():
            raise ValueError("daily bar prices must be finite")
        return parsed

    @model_validator(mode="after")
    def validate_ohlcv(self) -> Self:
        """Validate structural OHLCV facts only."""

        for field_name in ("open", "high", "low", "close"):
            if getattr(self, field_name) <= 0:
                raise ValueError(f"{field_name} must be positive")
        if self.high < self.low:
            raise ValueError("high must be greater than or equal to low")
        if self.high < self.open:
            raise ValueError("high must be greater than or equal to open")
        if self.high < self.close:
            raise ValueError("high must be greater than or equal to close")
        if self.low > self.open:
            raise ValueError("low must be less than or equal to open")
        if self.low > self.close:
            raise ValueError("low must be less than or equal to close")
        return self


class DailyMarketDataPolicy(VersionedContract):
    """Versioned provider-neutral daily market-data policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: NonEmptyString
    asset_class: AssetClass
    frequency: NonEmptyString
    calendar: NonEmptyString
    timezone: NonEmptyString
    adjustment_policy: DataAdjustmentPolicy
    distribution_treatment: DistributionTreatment
    corporate_action_policy: NonEmptyString
    universe_membership_policy: NonEmptyString
    survivorship_policy: NonEmptyString
    delisting_policy: NonEmptyString
    canonicalization_version: NonEmptyString
    quality_policy_version: NonEmptyString

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        """Constrain S3a v1 to ETF daily tradable execution bars."""

        if self.asset_class is not AssetClass.ETFS:
            raise ValueError("S3a daily market-data policy supports ETFs only")
        if self.frequency != DAILY_MARKET_DATA_FREQUENCY:
            raise ValueError("S3a daily market-data policy requires daily frequency")
        if self.adjustment_policy in {
            DataAdjustmentPolicy.TOTAL_RETURN,
            DataAdjustmentPolicy.CONTINUOUS,
        }:
            raise ValueError(
                "total-return and continuous series are not tradable execution OHLC"
            )
        if self.adjustment_policy is DataAdjustmentPolicy.OTHER:
            raise ValueError("other adjustment policy is not supported in S3a")
        return self


class DailyMarketDataQualityReport(VersionedContract):
    """Deterministic dataset-level quality facts for one daily instrument."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: NonEmptyString
    quality_policy_version: NonEmptyString
    canonicalization_version: NonEmptyString
    instrument: DailyMarketDataInstrument
    content_hash: NonEmptyString
    expected_start_date: date
    expected_end_date: date
    expected_session_count: int = Field(gt=0)
    observed_session_count: int = Field(ge=0)
    duplicate_row_count: int = Field(ge=0)
    missing_session_dates: tuple[date, ...] = ()
    unexpected_session_dates: tuple[date, ...] = ()
    duplicate_session_dates: tuple[date, ...] = ()
    zero_volume_dates: tuple[date, ...] = ()
    fatal_violations: tuple[DailyMarketDataQualityCode, ...] = ()
    warnings: tuple[DailyMarketDataQualityCode, ...] = ()
    status: DailyMarketDataQualityStatus

    @field_validator(
        "missing_session_dates",
        "unexpected_session_dates",
        "duplicate_session_dates",
        "zero_volume_dates",
    )
    @classmethod
    def validate_canonical_dates(cls, value: tuple[date, ...]) -> tuple[date, ...]:
        """Require deterministic date tuple ordering."""

        if len(set(value)) != len(value):
            raise ValueError("date tuples must not contain duplicates")
        if value != tuple(sorted(value)):
            raise ValueError("date tuples must be strictly ascending")
        return value

    @field_validator("fatal_violations", "warnings")
    @classmethod
    def validate_canonical_codes(
        cls,
        value: tuple[DailyMarketDataQualityCode, ...],
    ) -> tuple[DailyMarketDataQualityCode, ...]:
        """Require deterministic code tuple ordering."""

        if len(set(value)) != len(value):
            raise ValueError("quality code tuples must not contain duplicates")
        expected = tuple(sorted(value, key=lambda code: code.value))
        if value != expected:
            raise ValueError("quality code tuples must use canonical order")
        return value

    @model_validator(mode="after")
    def validate_quality_report(self) -> Self:
        """Reject contradictory status and quality evidence."""

        if SHA256_CONTENT_HASH_PATTERN.fullmatch(self.content_hash) is None:
            raise ValueError("content_hash must use sha256:<64 lowercase hex>")
        if self.expected_end_date < self.expected_start_date:
            raise ValueError(
                "expected_end_date must be greater than or equal to expected_start_date"
            )
        if self.warnings:
            raise ValueError("S3a quality reports do not define warning observations")

        expected_fatal_violations: tuple[DailyMarketDataQualityCode, ...] = tuple(
            code
            for code, evidence in (
                (
                    DailyMarketDataQualityCode.DUPLICATE_SESSION,
                    self.duplicate_session_dates,
                ),
                (
                    DailyMarketDataQualityCode.MISSING_SESSION,
                    self.missing_session_dates,
                ),
                (
                    DailyMarketDataQualityCode.UNEXPECTED_SESSION,
                    self.unexpected_session_dates,
                ),
                (DailyMarketDataQualityCode.ZERO_VOLUME, self.zero_volume_dates),
            )
            if evidence
        )
        if self.fatal_violations != expected_fatal_violations:
            raise ValueError(
                "fatal_violations must exactly match derived quality evidence"
            )

        expected_status = (
            DailyMarketDataQualityStatus.FAIL
            if expected_fatal_violations
            else DailyMarketDataQualityStatus.PASS
        )
        if self.status is not expected_status:
            raise ValueError("status must match derived quality evidence")

        expected_observed_session_count = (
            self.expected_session_count
            - len(self.missing_session_dates)
            + len(self.unexpected_session_dates)
            + self.duplicate_row_count
        )
        if self.observed_session_count != expected_observed_session_count:
            raise ValueError(
                "observed_session_count must match expected-session arithmetic"
            )
        return self


__all__ = [
    "DAILY_MARKET_DATA_FREQUENCY",
    "SHA256_CONTENT_HASH_PATTERN",
    "CanonicalDailyBar",
    "DailyMarketDataInstrument",
    "DailyMarketDataPolicy",
    "DailyMarketDataQualityCode",
    "DailyMarketDataQualityReport",
    "DailyMarketDataQualityStatus",
    "DistributionTreatment",
]
