"""Canonical semantic hashing for daily market-data corporate actions."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Any

from research_sdk.contracts.daily_market_data import DailyMarketDataInstrument
from research_sdk.contracts.daily_market_data_economics import (
    DailyMarketDataCashDistribution,
    DailyMarketDataCorporateActionEvent,
    DailyMarketDataCorporateActionEventType,
    DailyMarketDataCorporateActionEvidence,
    DailyMarketDataSplit,
    DailyMarketDataUnsupportedCorporateAction,
    corporate_action_event_economic_date,
)

DAILY_MARKET_DATA_CORPORATE_ACTIONS_HASH_VERSION = (
    "daily-market-data-corporate-actions-v1"
)


def derive_daily_market_data_corporate_action_content_hash(
    *,
    instrument: DailyMarketDataInstrument,
    coverage_start_date: date,
    coverage_end_date: date,
    events: tuple[DailyMarketDataCorporateActionEvent, ...],
    canonicalization_version: str = DAILY_MARKET_DATA_CORPORATE_ACTIONS_HASH_VERSION,
) -> str:
    """Return a semantic SHA-256 hash for provider-neutral action economics.

    The projection intentionally excludes source references, source timestamps,
    and event IDs. Those fields are lineage and audit evidence retained by the
    full evidence contract; S3c2 will decide how to bind that full contract into
    a versioned snapshot identity.
    """

    if not canonicalization_version.strip():
        raise ValueError("canonicalization_version must not be blank")
    if coverage_end_date < coverage_start_date:
        raise ValueError(
            "coverage_end_date must be greater than or equal to coverage_start_date"
        )

    validated_instrument = DailyMarketDataInstrument.model_validate(
        instrument.model_dump(mode="json")
    )
    validated_events = tuple(_revalidate_event(event) for event in events)
    payload = {
        "domain": "daily-market-data-corporate-actions",
        "canonicalization_version": canonicalization_version,
        "instrument": validated_instrument.model_dump(mode="json"),
        "coverage": {
            "start_date": coverage_start_date.isoformat(),
            "end_date": coverage_end_date.isoformat(),
        },
        "events": [
            _event_payload(event)
            for event in sorted(validated_events, key=_semantic_event_sort_key)
        ],
    }
    digest = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
    return f"sha256:{digest}"


def derive_daily_market_data_corporate_action_evidence_content_hash(
    evidence: DailyMarketDataCorporateActionEvidence,
) -> str:
    """Return the semantic economic hash for a complete evidence contract."""

    validated = DailyMarketDataCorporateActionEvidence.model_validate(
        evidence.model_dump(mode="json")
    )
    return derive_daily_market_data_corporate_action_content_hash(
        instrument=validated.instrument,
        coverage_start_date=validated.coverage_start_date,
        coverage_end_date=validated.coverage_end_date,
        events=validated.events,
        canonicalization_version=validated.canonicalization_version,
    )


def _revalidate_event(
    event: DailyMarketDataCorporateActionEvent,
) -> DailyMarketDataCorporateActionEvent:
    if isinstance(event, DailyMarketDataCashDistribution):
        return DailyMarketDataCashDistribution.model_validate(
            event.model_dump(mode="json")
        )
    if isinstance(event, DailyMarketDataSplit):
        return DailyMarketDataSplit.model_validate(event.model_dump(mode="json"))
    if isinstance(event, DailyMarketDataUnsupportedCorporateAction):
        return DailyMarketDataUnsupportedCorporateAction.model_validate(
            event.model_dump(mode="json")
        )
    raise TypeError("unsupported corporate-action event model")


def _semantic_event_sort_key(
    event: DailyMarketDataCorporateActionEvent,
) -> tuple[date, str, tuple[tuple[str, object], ...]]:
    payload = _event_payload(event)
    return (
        corporate_action_event_economic_date(event),
        event.event_type.value,
        tuple(sorted(payload.items())),
    )


def _event_payload(event: DailyMarketDataCorporateActionEvent) -> dict[str, object]:
    if isinstance(event, DailyMarketDataCashDistribution):
        return {
            "event_type": (
                DailyMarketDataCorporateActionEventType.CASH_DISTRIBUTION.value
            ),
            "instrument_id": event.instrument_id,
            "ex_date": event.ex_date.isoformat(),
            "amount": _canonical_decimal(event.amount),
            "currency": event.currency,
        }
    if isinstance(event, DailyMarketDataSplit):
        return {
            "event_type": DailyMarketDataCorporateActionEventType.SPLIT.value,
            "instrument_id": event.instrument_id,
            "effective_date": event.effective_date.isoformat(),
            "numerator": event.canonical_numerator,
            "denominator": event.canonical_denominator,
        }
    if isinstance(event, DailyMarketDataUnsupportedCorporateAction):
        return {
            "event_type": DailyMarketDataCorporateActionEventType.UNSUPPORTED.value,
            "instrument_id": event.instrument_id,
            "effective_date": event.effective_date.isoformat(),
            "provider_event_type": event.provider_event_type,
        }
    raise TypeError("unsupported corporate-action event model")


def _canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("decimal values must be finite")
    if value == value.to_integral_value():
        return format(value, "f").split(".", 1)[0]
    return format(value.normalize(), "f")


def _canonical_json_bytes(payload: Any) -> bytes:
    rendered = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return f"{rendered}\n".encode()


__all__ = [
    "DAILY_MARKET_DATA_CORPORATE_ACTIONS_HASH_VERSION",
    "derive_daily_market_data_corporate_action_content_hash",
    "derive_daily_market_data_corporate_action_evidence_content_hash",
]
