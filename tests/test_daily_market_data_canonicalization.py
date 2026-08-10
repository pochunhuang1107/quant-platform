from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from research_sdk.contracts.daily_market_data import (
    CanonicalDailyBar,
    DailyMarketDataInstrument,
)
from research_sdk.daily_market_data import derive_daily_market_data_content_hash

CANONICALIZATION_VERSION = "daily-market-data-canonical-v1"
GOLDEN_CONTENT_HASH = (
    "sha256:93ec3e3e9fb514519e1131b27f04032c2737bdae0bc5ca7d2f57cf570e3b9e85"
)


def test_daily_market_data_content_hash_matches_golden_value() -> None:
    assert content_hash(sample_bars()) == GOLDEN_CONTENT_HASH


def test_daily_market_data_content_hash_is_deterministic() -> None:
    assert content_hash(sample_bars()) == content_hash(sample_bars())


def test_daily_market_data_content_hash_is_bar_order_independent() -> None:
    assert content_hash(tuple(reversed(sample_bars()))) == content_hash(sample_bars())


def test_expected_sessions_are_not_content_hash_input() -> None:
    assert content_hash(sample_bars()) == content_hash(sample_bars())


def test_equivalent_decimal_textual_forms_hash_identically() -> None:
    first = (
        CanonicalDailyBar(
            session_date=date(2026, 1, 2),
            open="100",
            high="101.0",
            low="99.000000",
            close="100.5000",
            volume=1000,
        ),
    )
    second = (
        CanonicalDailyBar(
            session_date=date(2026, 1, 2),
            open="100.000000",
            high="101",
            low="99.0",
            close="100.5",
            volume=1000,
        ),
    )

    assert content_hash(first) == content_hash(second)


def test_changed_ohlc_changes_content_hash() -> None:
    changed = (sample_bars()[0].model_copy(update={"close": Decimal("100.6")}),)

    assert content_hash(changed) != content_hash((sample_bars()[0],))


def test_changed_volume_changes_content_hash() -> None:
    changed = (sample_bars()[0].model_copy(update={"volume": 1001}),)

    assert content_hash(changed) != content_hash((sample_bars()[0],))


def test_changed_session_date_changes_content_hash() -> None:
    changed = (sample_bars()[0].model_copy(update={"session_date": date(2026, 1, 5)}),)

    assert content_hash(changed) != content_hash((sample_bars()[0],))


def test_changed_instrument_id_changes_content_hash() -> None:
    assert content_hash(sample_bars(), instrument=instrument("other")) != content_hash(
        sample_bars()
    )


def test_changed_symbol_changes_content_hash() -> None:
    changed = DailyMarketDataInstrument(
        instrument_id="instrument-us-etf-qqq-xnas",
        symbol="QQQ.A",
        venue="XNAS",
    )

    assert content_hash(sample_bars(), instrument=changed) != content_hash(
        sample_bars()
    )


def test_changed_venue_changes_content_hash() -> None:
    changed = DailyMarketDataInstrument(
        instrument_id="instrument-us-etf-qqq-xnas",
        symbol="QQQ",
        venue="ARCX",
    )

    assert content_hash(sample_bars(), instrument=changed) != content_hash(
        sample_bars()
    )


def test_provider_metadata_uri_policy_and_file_serialization_are_not_inputs() -> None:
    first = content_hash(sample_bars())
    provider_name = "example-provider"
    data_root_uri = "s3://bucket/curated"
    policy_id = "daily-market-data-etf-execution-v1"
    file_bytes = b"not canonical data"

    assert provider_name
    assert data_root_uri
    assert policy_id
    assert file_bytes
    assert content_hash(sample_bars()) == first


def test_daily_market_data_content_hash_shape() -> None:
    digest = content_hash(sample_bars())

    assert digest.startswith("sha256:")
    assert len(digest) == len("sha256:") + 64
    assert digest.removeprefix("sha256:").lower() == digest.removeprefix("sha256:")


def test_content_hash_revalidates_copied_invalid_instrument() -> None:
    invalid = sample_instrument().model_copy(update={"symbol": " "})

    with pytest.raises(ValidationError):
        content_hash(sample_bars(), instrument=invalid)


def test_content_hash_revalidates_copied_invalid_bar_volume() -> None:
    invalid = sample_bars()[0].model_copy(update={"volume": -1})

    with pytest.raises(ValidationError):
        content_hash((invalid,))


def test_content_hash_revalidates_copied_invalid_bar_ohlc() -> None:
    invalid = sample_bars()[0].model_copy(update={"close": Decimal("0")})

    with pytest.raises(ValidationError):
        content_hash((invalid,))


def content_hash(
    bars: tuple[CanonicalDailyBar, ...],
    *,
    instrument: DailyMarketDataInstrument | None = None,
) -> str:
    return derive_daily_market_data_content_hash(
        instrument=instrument or sample_instrument(),
        bars=bars,
        canonicalization_version=CANONICALIZATION_VERSION,
    )


def sample_instrument() -> DailyMarketDataInstrument:
    return instrument("instrument-us-etf-qqq-xnas")


def instrument(instrument_id: str) -> DailyMarketDataInstrument:
    return DailyMarketDataInstrument(
        instrument_id=instrument_id,
        symbol="QQQ",
        venue="XNAS",
    )


def sample_bars() -> tuple[CanonicalDailyBar, ...]:
    return (
        CanonicalDailyBar(
            session_date=date(2026, 1, 2),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100.5"),
            volume=1000,
        ),
        CanonicalDailyBar(
            session_date=date(2026, 1, 5),
            open=Decimal("101"),
            high=Decimal("102"),
            low=Decimal("100"),
            close=Decimal("101.5"),
            volume=1100,
        ),
    )
