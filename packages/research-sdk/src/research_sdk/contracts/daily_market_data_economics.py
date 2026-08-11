"""Economic evidence contracts for daily ETF market-data research."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from math import gcd
from typing import Annotated, Literal, Self
from urllib.parse import parse_qsl, urlsplit

from pydantic import ConfigDict, Field, field_validator, model_validator

from research_sdk.contracts.daily_market_data import (
    DAILY_MARKET_DATA_FREQUENCY,
    SHA256_CONTENT_HASH_PATTERN,
    DailyMarketDataInstrument,
    DistributionTreatment,
)
from research_sdk.contracts.enums import (
    AssetClass,
    DataAdjustmentPolicy,
    DataSourceType,
    TemporalCoverage,
)
from research_sdk.contracts.schema import VersionedContract
from research_sdk.contracts.time import UtcDatetime
from research_sdk.contracts.types import NonEmptyString

_SENSITIVE_REFERENCE_QUERY_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "signature",
        "sig",
        "token",
        "x-amz-credential",
        "x-amz-security-token",
        "x-amz-signature",
    }
)


class DailyMarketDataCorporateActionEventType(StrEnum):
    """Provider-neutral event vocabulary for S3c1 economic evidence."""

    CASH_DISTRIBUTION = "cash_distribution"
    SPLIT = "split"
    UNSUPPORTED = "unsupported"


class DailyMarketDataCorporateActionEvidenceCompleteness(StrEnum):
    """Whether checked corporate-action source evidence is complete."""

    CHECKED_NO_EVENTS = "checked_no_events"
    CHECKED_EVENTS_CAPTURED = "checked_events_captured"


class DailyMarketDataBarAvailabilityPolicy(StrEnum):
    """Daily-bar information availability policy for research data profiles."""

    NEXT_EXPECTED_SESSION = "next_expected_session"


class _DailyMarketDataCorporateActionEventBase(VersionedContract):
    """Common source authority for one corporate-action event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: NonEmptyString
    instrument_id: NonEmptyString
    source_event_reference: NonEmptyString
    source_available_at: UtcDatetime

    @field_validator("source_event_reference")
    @classmethod
    def reject_sensitive_source_reference(cls, value: str) -> str:
        """Reject obvious credential-bearing source references."""

        parsed = urlsplit(value)
        if parsed.scheme and parsed.netloc and (parsed.username or parsed.password):
            raise ValueError("source event references must not contain URI userinfo")
        sensitive_keys = {
            key.lower()
            for key, _value in parse_qsl(parsed.query, keep_blank_values=True)
        }
        if sensitive_keys & _SENSITIVE_REFERENCE_QUERY_KEYS:
            raise ValueError(
                "source event references must not contain obvious access tokens"
            )
        return value


class DailyMarketDataCashDistribution(_DailyMarketDataCorporateActionEventBase):
    """Provider-neutral cash distribution event for daily ETF evidence."""

    event_type: Literal[DailyMarketDataCorporateActionEventType.CASH_DISTRIBUTION] = (
        DailyMarketDataCorporateActionEventType.CASH_DISTRIBUTION
    )
    ex_date: date
    amount: Decimal
    currency: NonEmptyString
    record_date: date | None = None
    payable_date: date | None = None
    announced_at: UtcDatetime | None = None
    distribution_classification: NonEmptyString | None = None

    @field_validator("ex_date", "record_date", "payable_date", mode="before")
    @classmethod
    def reject_non_date_values(cls, value: object) -> object:
        return _reject_non_date_value(value)

    @field_validator("amount", mode="before")
    @classmethod
    def parse_amount(cls, value: object) -> Decimal:
        return _parse_positive_decimal(value, field_name="amount")


class DailyMarketDataSplit(_DailyMarketDataCorporateActionEventBase):
    """Provider-neutral split event for daily ETF evidence."""

    event_type: Literal[DailyMarketDataCorporateActionEventType.SPLIT] = (
        DailyMarketDataCorporateActionEventType.SPLIT
    )
    effective_date: date
    numerator: int = Field(gt=0)
    denominator: int = Field(gt=0)

    @field_validator("effective_date", mode="before")
    @classmethod
    def reject_non_date_values(cls, value: object) -> object:
        return _reject_non_date_value(value)

    @field_validator("numerator", "denominator", mode="before")
    @classmethod
    def reject_bool_ratio_values(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("split ratio values must be positive integers")
        return value

    @property
    def canonical_numerator(self) -> int:
        """Reduced split numerator used by semantic hashing."""

        divisor = gcd(self.numerator, self.denominator)
        return self.numerator // divisor

    @property
    def canonical_denominator(self) -> int:
        """Reduced split denominator used by semantic hashing."""

        divisor = gcd(self.numerator, self.denominator)
        return self.denominator // divisor

    @model_validator(mode="after")
    def reject_economically_empty_ratio(self) -> Self:
        if self.canonical_numerator == self.canonical_denominator:
            raise ValueError("1:1 split ratio is not an economic split event")
        return self


class DailyMarketDataUnsupportedCorporateAction(
    _DailyMarketDataCorporateActionEventBase
):
    """Provider-neutral unsupported event evidence for fail-closed behavior."""

    event_type: Literal[DailyMarketDataCorporateActionEventType.UNSUPPORTED] = (
        DailyMarketDataCorporateActionEventType.UNSUPPORTED
    )
    provider_event_type: NonEmptyString
    effective_date: date
    description: NonEmptyString | None = None

    @field_validator("effective_date", mode="before")
    @classmethod
    def reject_non_date_values(cls, value: object) -> object:
        return _reject_non_date_value(value)


type DailyMarketDataCorporateActionEvent = Annotated[
    DailyMarketDataCashDistribution
    | DailyMarketDataSplit
    | DailyMarketDataUnsupportedCorporateAction,
    Field(discriminator="event_type"),
]


class DailyMarketDataCorporateActionEvidence(VersionedContract):
    """Complete checked corporate-action evidence for one daily instrument."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_policy_version: NonEmptyString
    completeness: DailyMarketDataCorporateActionEvidenceCompleteness
    instrument: DailyMarketDataInstrument
    coverage_start_date: date
    coverage_end_date: date
    source_dataset: NonEmptyString
    source_version: NonEmptyString
    source_type: DataSourceType
    source_reference: NonEmptyString
    source_content_hash: NonEmptyString
    source_size_bytes: int = Field(ge=0)
    source_observed_at: UtcDatetime
    ingestion_completed_at: UtcDatetime
    available_at: UtcDatetime
    created_at: UtcDatetime
    created_by: NonEmptyString
    canonicalization_version: NonEmptyString
    events: tuple[DailyMarketDataCorporateActionEvent, ...] = ()
    known_limitations: tuple[NonEmptyString, ...] = Field(min_length=1)
    vendor_name: NonEmptyString | None = None
    license_notes: NonEmptyString | None = None

    @field_validator("coverage_start_date", "coverage_end_date", mode="before")
    @classmethod
    def reject_non_date_values(cls, value: object) -> object:
        return _reject_non_date_value(value)

    @field_validator("source_reference")
    @classmethod
    def reject_sensitive_source_reference(cls, value: str) -> str:
        return _reject_sensitive_reference(value, context="source references")

    @field_validator("source_content_hash")
    @classmethod
    def validate_source_hash(cls, value: str) -> str:
        if SHA256_CONTENT_HASH_PATTERN.fullmatch(value) is None:
            raise ValueError("source_content_hash must use sha256:<64 lowercase hex>")
        return value

    @field_validator("events")
    @classmethod
    def validate_canonical_event_order(
        cls,
        value: tuple[DailyMarketDataCorporateActionEvent, ...],
    ) -> tuple[DailyMarketDataCorporateActionEvent, ...]:
        if value != tuple(sorted(value, key=corporate_action_event_sort_key)):
            raise ValueError("events must use canonical economic-date/type/event order")
        return value

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if self.coverage_end_date < self.coverage_start_date:
            raise ValueError(
                "coverage_end_date must be greater than or equal to coverage_start_date"
            )
        if self.source_observed_at > self.ingestion_completed_at:
            raise ValueError(
                "source_observed_at must be less than or equal to "
                "ingestion_completed_at"
            )
        if self.ingestion_completed_at > self.available_at:
            raise ValueError(
                "ingestion_completed_at must be less than or equal to available_at"
            )
        if self.available_at > self.created_at:
            raise ValueError("available_at must be less than or equal to created_at")
        if self.source_type is DataSourceType.VENDOR and self.vendor_name is None:
            raise ValueError("vendor_name is required when source_type is vendor")

        event_ids = [event.event_id for event in self.events]
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("event_id values must be unique within evidence")

        for event in self.events:
            if event.instrument_id != self.instrument.instrument_id:
                raise ValueError("event instrument_id must match evidence instrument")
            event_date = corporate_action_event_economic_date(event)
            if not self.coverage_start_date <= event_date <= self.coverage_end_date:
                raise ValueError("event economic date must lie within coverage")
            if event.source_available_at > self.created_at:
                raise ValueError(
                    "event source_available_at must be less than or equal to "
                    "evidence created_at"
                )

        if (
            self.completeness
            is DailyMarketDataCorporateActionEvidenceCompleteness.CHECKED_NO_EVENTS
            and self.events
        ):
            raise ValueError("checked_no_events requires an empty event set")
        if (
            self.completeness
            is (
                DailyMarketDataCorporateActionEvidenceCompleteness.CHECKED_EVENTS_CAPTURED
            )
            and not self.events
        ):
            raise ValueError("checked_events_captured requires at least one event")
        return self


class DailyMarketDataResearchProfile(VersionedContract):
    """Versioned deterministic requirements for daily ETF research data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_id: NonEmptyString
    profile_policy_version: NonEmptyString
    asset_class: AssetClass
    frequency: NonEmptyString
    required_currency: NonEmptyString
    permitted_temporal_coverage: tuple[TemporalCoverage, ...] = Field(min_length=1)
    adjustment_policy: DataAdjustmentPolicy
    distribution_treatment: DistributionTreatment
    daily_bar_availability_policy: DailyMarketDataBarAvailabilityPolicy
    allowed_corporate_action_completeness: tuple[
        DailyMarketDataCorporateActionEvidenceCompleteness, ...
    ] = Field(min_length=1)
    supported_corporate_action_event_types: tuple[
        DailyMarketDataCorporateActionEventType, ...
    ] = Field(min_length=1)
    unsupported_events_allowed: bool
    corporate_action_coverage_requirement: NonEmptyString
    calendar: NonEmptyString
    timezone: NonEmptyString
    session_source_id: NonEmptyString
    session_source_version: NonEmptyString
    universe_membership_policy: NonEmptyString
    survivorship_policy: NonEmptyString
    delisting_policy: NonEmptyString

    @field_validator(
        "permitted_temporal_coverage",
        "allowed_corporate_action_completeness",
        "supported_corporate_action_event_types",
    )
    @classmethod
    def validate_canonical_tuple_order(
        cls,
        value: tuple[StrEnum, ...],
    ) -> tuple[StrEnum, ...]:
        if len(set(value)) != len(value):
            raise ValueError("profile enum tuples must not contain duplicates")
        expected = tuple(sorted(value, key=lambda item: item.value))
        if value != expected:
            raise ValueError("profile enum tuples must use canonical order")
        return value

    @model_validator(mode="after")
    def validate_profile(self) -> Self:
        if self.asset_class is not AssetClass.ETFS:
            raise ValueError("S3c1 research profiles support ETFs only")
        if self.frequency != DAILY_MARKET_DATA_FREQUENCY:
            raise ValueError("S3c1 research profiles require daily frequency")
        if self.adjustment_policy is not DataAdjustmentPolicy.RAW:
            raise ValueError("S3c1 complete-economic ETF profile requires raw OHLCV")
        if self.distribution_treatment is not DistributionTreatment.EXPLICIT_CASH:
            raise ValueError(
                "S3c1 complete-economic ETF profile requires explicit cash "
                "distributions"
            )
        if (
            self.daily_bar_availability_policy
            is not DailyMarketDataBarAvailabilityPolicy.NEXT_EXPECTED_SESSION
        ):
            raise ValueError("S3c1 supports only next-expected-session availability")
        required_completeness = {
            DailyMarketDataCorporateActionEvidenceCompleteness.CHECKED_EVENTS_CAPTURED,
            DailyMarketDataCorporateActionEvidenceCompleteness.CHECKED_NO_EVENTS,
        }
        if set(self.allowed_corporate_action_completeness) != required_completeness:
            raise ValueError(
                "complete-economic profile must allow both checked no-event and "
                "checked captured-event evidence"
            )
        required_event_types = {
            DailyMarketDataCorporateActionEventType.CASH_DISTRIBUTION,
            DailyMarketDataCorporateActionEventType.SPLIT,
        }
        if set(self.supported_corporate_action_event_types) != required_event_types:
            raise ValueError(
                "complete-economic profile supports only cash distributions and splits"
            )
        if self.unsupported_events_allowed:
            raise ValueError(
                "complete-economic profile must disallow unsupported events"
            )
        return self


def corporate_action_event_economic_date(
    event: DailyMarketDataCorporateActionEvent,
) -> date:
    """Return the economic/effective date used for canonical event ordering."""

    if isinstance(event, DailyMarketDataCashDistribution):
        return event.ex_date
    return event.effective_date


def corporate_action_event_sort_key(
    event: DailyMarketDataCorporateActionEvent,
) -> tuple[date, str, str]:
    """Return canonical ordering by date, event type, and event ID."""

    return (
        corporate_action_event_economic_date(event),
        event.event_type.value,
        event.event_id,
    )


def _reject_non_date_value(value: object) -> object:
    if value is None:
        return value
    if isinstance(value, datetime | bool):
        raise ValueError("date fields must contain date values only")
    return value


def _parse_positive_decimal(value: object, *, field_name: str) -> Decimal:
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
    if parsed <= 0:
        raise ValueError(f"{field_name} must be strictly positive")
    return parsed


def _reject_sensitive_reference(value: str, *, context: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme and parsed.netloc and (parsed.username or parsed.password):
        raise ValueError(f"{context} must not contain URI userinfo")
    sensitive_keys = {
        key.lower() for key, _value in parse_qsl(parsed.query, keep_blank_values=True)
    }
    if sensitive_keys & _SENSITIVE_REFERENCE_QUERY_KEYS:
        raise ValueError(f"{context} must not contain obvious access tokens")
    return value


__all__ = [
    "DailyMarketDataBarAvailabilityPolicy",
    "DailyMarketDataCashDistribution",
    "DailyMarketDataCorporateActionEvent",
    "DailyMarketDataCorporateActionEventType",
    "DailyMarketDataCorporateActionEvidence",
    "DailyMarketDataCorporateActionEvidenceCompleteness",
    "DailyMarketDataResearchProfile",
    "DailyMarketDataSplit",
    "DailyMarketDataUnsupportedCorporateAction",
    "corporate_action_event_economic_date",
    "corporate_action_event_sort_key",
]
