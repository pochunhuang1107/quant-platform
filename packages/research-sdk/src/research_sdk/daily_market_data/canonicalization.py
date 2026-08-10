"""Canonical semantic content hashing for daily market data."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

from research_sdk.contracts.daily_market_data import (
    CanonicalDailyBar,
    DailyMarketDataInstrument,
)


def derive_daily_market_data_content_hash(
    *,
    instrument: DailyMarketDataInstrument,
    bars: tuple[CanonicalDailyBar, ...],
    canonicalization_version: str,
) -> str:
    """Return a semantic sha256 content hash for canonical daily bars.

    Equivalent Decimal numeric values canonicalize identically. For example,
    ``100``, ``100.0``, and ``100.000000`` all hash as ``"100"``.
    """

    if not canonicalization_version.strip():
        raise ValueError("canonicalization_version must not be blank")
    validated_instrument = _revalidate_instrument(instrument)
    validated_bars = tuple(_revalidate_bar(bar) for bar in bars)
    payload = {
        "domain": "daily-market-data-content",
        "canonicalization_version": canonicalization_version,
        "instrument": validated_instrument.model_dump(mode="json"),
        "bars": [
            _bar_payload(bar)
            for bar in sorted(
                validated_bars,
                key=lambda bar: (
                    bar.session_date,
                    _canonical_decimal(bar.open),
                    _canonical_decimal(bar.high),
                    _canonical_decimal(bar.low),
                    _canonical_decimal(bar.close),
                    bar.volume,
                ),
            )
        ],
    }
    digest = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
    return f"sha256:{digest}"


def _revalidate_instrument(
    instrument: DailyMarketDataInstrument,
) -> DailyMarketDataInstrument:
    return DailyMarketDataInstrument.model_validate(instrument.model_dump(mode="json"))


def _revalidate_bar(bar: CanonicalDailyBar) -> CanonicalDailyBar:
    return CanonicalDailyBar.model_validate(bar.model_dump(mode="json"))


def _bar_payload(bar: CanonicalDailyBar) -> dict[str, str | int]:
    return {
        "session_date": bar.session_date.isoformat(),
        "open": _canonical_decimal(bar.open),
        "high": _canonical_decimal(bar.high),
        "low": _canonical_decimal(bar.low),
        "close": _canonical_decimal(bar.close),
        "volume": bar.volume,
    }


def _canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("decimal values must be finite")
    if value == value.to_integral_value():
        return format(value, "f").split(".", 1)[0]
    normalized = value.normalize()
    return format(normalized, "f")


def _canonical_json_bytes(payload: Any) -> bytes:
    rendered = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return f"{rendered}\n".encode()


__all__ = ["derive_daily_market_data_content_hash"]
