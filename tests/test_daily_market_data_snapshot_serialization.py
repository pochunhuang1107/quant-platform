from __future__ import annotations

import pytest
from pydantic import ValidationError

from helpers_daily_market_data_snapshots import (
    BARS_STORAGE_HASH,
    CANONICAL_BARS_BYTES,
    sample_expected_sessions,
    sample_plan,
    sample_policy,
    source_bytes,
)
from research_sdk.contracts.daily_market_data import DailyMarketDataPolicy
from research_sdk.contracts.daily_market_data_snapshots import (
    DailyMarketDataSnapshotProvenance,
)
from research_sdk.daily_market_data_storage.serialization import (
    DailyMarketDataSnapshotSerializationError,
    parse_canonical_daily_bars,
    parse_contract_json,
    render_canonical_daily_bars,
    render_contract_json,
    sha256_bytes,
)


def test_parse_source_jsonl_and_render_canonical_bars_golden_bytes() -> None:
    bars = parse_canonical_daily_bars(source_bytes())

    assert render_canonical_daily_bars(bars) == CANONICAL_BARS_BYTES
    assert sha256_bytes(CANONICAL_BARS_BYTES) == BARS_STORAGE_HASH


def test_source_order_does_not_affect_canonical_published_bars() -> None:
    bars = parse_canonical_daily_bars(source_bytes())

    assert render_canonical_daily_bars(tuple(reversed(bars))) == CANONICAL_BARS_BYTES


def test_decimal_textual_forms_normalize_in_published_bars() -> None:
    equivalent = (
        b'{"session_date":"2026-01-02","open":"100","high":"101.0000",'
        b'"low":"99.0","close":"100.500000","volume":1000}\n'
    )

    assert render_canonical_daily_bars(parse_canonical_daily_bars(equivalent)) == (
        b'{"close":"100.5","high":"101","low":"99","open":"100",'
        b'"session_date":"2026-01-02","volume":1000}\n'
    )


def test_parse_render_roundtrip_preserves_canonical_bars() -> None:
    first = parse_canonical_daily_bars(source_bytes())
    second = parse_canonical_daily_bars(render_canonical_daily_bars(first))

    assert render_canonical_daily_bars(second) == render_canonical_daily_bars(first)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\n",
        b'{"session_date":"2026-01-02","open":"100"}\n',
        b'{"session_date":"2026-01-02","open":"100","high":"101","low":"99","close":"100.5","volume":1000,"extra":true}\n',
        b'{"session_date":"2026-01-02","open":100,"high":"101","low":"99","close":"100.5","volume":1000}\n',
        b'{"session_date":"2026-01-02","open":"100","high":"101","low":"99","close":"100.5","volume":1000.0}\n',
        b'{"session_date":"2026-01-02","open":"100","high":"101","low":"99","close":"100.5","volume":1000}\n\n',
        b"not json\n",
    ],
)
def test_malformed_source_jsonl_fails_closed(data: bytes) -> None:
    with pytest.raises((DailyMarketDataSnapshotSerializationError, ValidationError)):
        parse_canonical_daily_bars(data)


@pytest.mark.parametrize(
    "data",
    [
        (
            b'{"session_date":"2026-01-02","session_date":"2026-01-03",'
            b'"open":"100","high":"101","low":"99","close":"100.5",'
            b'"volume":1000}\n'
        ),
        (
            b'{"session_date":"2026-01-02","open":"100","open":"101",'
            b'"high":"101","low":"99","close":"100.5","volume":1000}\n'
        ),
        (
            b'{"session_date":"2026-01-02","open":"100","high":"101",'
            b'"low":"99","close":"100.5","volume":1000,"volume":1001}\n'
        ),
    ],
)
def test_source_jsonl_rejects_duplicate_object_keys(data: bytes) -> None:
    with pytest.raises(DailyMarketDataSnapshotSerializationError, match="duplicate"):
        parse_canonical_daily_bars(data)


@pytest.mark.parametrize("constant", [b"NaN", b"Infinity", b"-Infinity"])
def test_source_jsonl_rejects_non_standard_json_constants(constant: bytes) -> None:
    data = (
        b'{"session_date":"2026-01-02","open":'
        + constant
        + b',"high":"101","low":"99","close":"100.5","volume":1000}\n'
    )

    with pytest.raises(DailyMarketDataSnapshotSerializationError, match="constant"):
        parse_canonical_daily_bars(data)


def test_contract_json_rejects_duplicate_top_level_keys() -> None:
    data = (
        b'{"schema_version":"1.0.0","policy_id":"first","policy_id":"second",'
        b'"asset_class":"etfs","frequency":"daily","calendar":"XNYS",'
        b'"timezone":"America/New_York","adjustment_policy":"raw",'
        b'"distribution_treatment":"explicit_cash",'
        b'"corporate_action_policy":"raw OHLCV plus explicit evidence",'
        b'"universe_membership_policy":"static explicit instrument universe",'
        b'"survivorship_policy":"static named instrument",'
        b'"delisting_policy":"unsupported","canonicalization_version":"v1",'
        b'"quality_policy_version":"v1"}\n'
    )

    with pytest.raises(DailyMarketDataSnapshotSerializationError, match="duplicate"):
        parse_contract_json(data, DailyMarketDataPolicy)


def test_contract_json_rejects_non_standard_json_constants() -> None:
    with pytest.raises(DailyMarketDataSnapshotSerializationError, match="constant"):
        parse_contract_json(b'{"schema_version":NaN}\n', DailyMarketDataPolicy)


def test_render_contract_json_revalidates_copied_invalid_contracts() -> None:
    invalid_expected_sessions = sample_expected_sessions().model_copy(
        update={"session_dates": ()}
    )
    provenance = parse_contract_json(
        sample_plan().as_file_map()["provenance.json"],
        DailyMarketDataSnapshotProvenance,
    )
    invalid_provenance = provenance.model_copy(
        update={"available_at": provenance.as_of}
    )
    invalid_bundle_manifest = sample_plan().bundle_manifest.model_copy(
        update={"snapshot_id": "bad"}
    )

    with pytest.raises(ValidationError):
        render_contract_json(invalid_expected_sessions)
    with pytest.raises(ValidationError):
        render_contract_json(invalid_provenance)
    with pytest.raises(ValidationError):
        render_contract_json(invalid_bundle_manifest)


def test_render_contract_json_valid_bytes_remain_canonical() -> None:
    assert render_contract_json(sample_policy()).endswith(b"\n")


def test_source_missing_final_newline_is_accepted_but_output_adds_one() -> None:
    source = (
        b'{"session_date":"2026-01-02","open":"100","high":"101",'
        b'"low":"99","close":"100.5","volume":1000}'
    )

    rendered = render_canonical_daily_bars(parse_canonical_daily_bars(source))

    assert rendered.endswith(b"\n")
    assert rendered.count(b"\n") == 1


def test_non_utf8_source_bytes_reject() -> None:
    with pytest.raises(DailyMarketDataSnapshotSerializationError, match="UTF-8"):
        parse_canonical_daily_bars(b"\xff")
