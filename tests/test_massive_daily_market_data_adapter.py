from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext

import pytest

import research_sdk.daily_market_data_adapters.massive as adapter_module
from research_sdk.contracts.daily_market_data import (
    CanonicalDailyBar,
    DailyMarketDataInstrument,
)
from research_sdk.contracts.daily_market_data_economics import (
    DailyMarketDataCashDistribution,
    DailyMarketDataCorporateActionEventType,
    DailyMarketDataCorporateActionEvidenceCompleteness,
    DailyMarketDataSplit,
    DailyMarketDataUnsupportedCorporateAction,
)
from research_sdk.contracts.enums import TemporalCoverage
from research_sdk.daily_market_data_adapters.massive import (
    MASSIVE_BAR_ENDPOINT_FAMILY,
    MASSIVE_BAR_ENDPOINT_VERSION,
    MASSIVE_DAILY_MARKET_DATA_ADAPTER_VERSION,
    MASSIVE_DIVIDEND_ENDPOINT_FAMILY,
    MASSIVE_DIVIDEND_ENDPOINT_VERSION,
    MASSIVE_PROVIDER,
    MASSIVE_SOURCE_FAMILY,
    MASSIVE_SPLIT_ENDPOINT_FAMILY,
    MASSIVE_SPLIT_ENDPOINT_VERSION,
    AdaptedMassiveDailyMarketData,
    MassiveDailyMarketDataAdapterContext,
    MassiveDailyMarketDataAdapterDiagnostic,
    MassiveResponseParsingError,
    MassiveResponseValidationError,
    MassiveUnsupportedSemanticError,
    adapt_massive_daily_market_data_source_capture,
    adapt_massive_daily_market_data_source_capture_with_diagnostics,
)
from research_sdk.daily_market_data_source_capture.models import (
    DailyMarketDataSourceCaptureMemberInput,
    DailyMarketDataSourceCaptureRequestParameter,
    DailyMarketDataSourceCaptureRole,
)
from research_sdk.daily_market_data_source_capture.planning import (
    plan_daily_market_data_source_capture,
)
from research_sdk.daily_market_data_source_capture.verification import (
    VerifiedDailyMarketDataSourceCapture,
    verify_daily_market_data_source_capture,
)

CAPTURE_OBSERVED_AT = datetime(2026, 8, 14, 16, 0, tzinfo=UTC)
UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
HIGH_PRECISION_SPLIT_TO = "1.000000000000000000000000000001"
HIGH_PRECISION_NUMERATOR = 1000000000000000000000000000001
HIGH_PRECISION_DENOMINATOR = 1000000000000000000000000000000
INSTRUMENT = DailyMarketDataInstrument(
    instrument_id="us-equity:QQQ",
    symbol="QQQ",
    venue="XNAS",
)
PROVIDER_SENTINEL = "PROVIDER_CONTROLLED_SENTINEL_7d3a"


def test_adapts_valid_source_capture_and_retains_lineage() -> None:
    verified = sample_verified_capture()

    adapted = adapt_massive_daily_market_data_source_capture(
        source_capture=verified,
        context=MassiveDailyMarketDataAdapterContext(
            instrument=INSTRUMENT,
            currency="USD",
        ),
    )

    assert isinstance(adapted, AdaptedMassiveDailyMarketData)
    assert adapted.source_capture is verified
    assert adapted.capture_id == verified.capture_id
    assert adapted.instrument == INSTRUMENT
    assert adapted.currency == "USD"
    assert adapted.parser_version == MASSIVE_DAILY_MARKET_DATA_ADAPTER_VERSION
    assert adapted.temporal_coverage is TemporalCoverage.LATEST_KNOWN
    assert adapted.bar_requested_start_date == date(2026, 1, 5)
    assert adapted.bar_requested_end_date == date(2026, 7, 6)
    assert adapted.corporate_action_coverage_start_date == date(2026, 1, 1)
    assert adapted.corporate_action_coverage_end_date == date(2026, 12, 31)
    assert adapted.bars == (
        CanonicalDailyBar(
            session_date=date(2026, 1, 5),
            open=Decimal("100.123456789123456789"),
            high=Decimal("101.25"),
            low=Decimal("99.75"),
            close=Decimal("100.5"),
            volume=1000,
        ),
        CanonicalDailyBar(
            session_date=date(2026, 7, 6),
            open=Decimal("200.1"),
            high=Decimal("202.2"),
            low=Decimal("199.9"),
            close=Decimal("201.01"),
            volume=2000,
        ),
    )
    assert adapted.corporate_action_completeness is (
        DailyMarketDataCorporateActionEvidenceCompleteness.CHECKED_EVENTS_CAPTURED
    )
    assert len(adapted.corporate_action_events) == 2
    cash_event = adapted.corporate_action_events[0]
    assert isinstance(cash_event, DailyMarketDataCashDistribution)
    assert cash_event.event_id == "synthetic-dividend-1"
    assert cash_event.source_event_reference == "synthetic-dividend-1"
    assert cash_event.source_available_at == CAPTURE_OBSERVED_AT
    assert cash_event.ex_date == date(2026, 3, 15)
    assert cash_event.amount == Decimal("0.123456789123456789")
    assert cash_event.currency == "USD"
    assert cash_event.payable_date == date(2026, 3, 30)
    assert cash_event.record_date == date(2026, 3, 16)
    assert cash_event.announced_at is None
    assert cash_event.distribution_classification == "recurring"
    split_event = adapted.corporate_action_events[1]
    assert isinstance(split_event, DailyMarketDataSplit)
    assert split_event.event_id == "synthetic-split-1"
    assert split_event.effective_date == date(2026, 6, 1)
    assert split_event.numerator == 2
    assert split_event.denominator == 1
    assert verified.member_bytes[DailyMarketDataSourceCaptureRole.BAR_RESPONSE] == (
        sample_bar_response()
    )
    assert (
        adapted.source_capture.ca_source_content_hash == verified.ca_source_content_hash
    )
    assert adapted.source_capture.ca_source_size_bytes == verified.ca_source_size_bytes


def test_descending_provider_bars_are_sorted_by_session_date() -> None:
    verified = sample_verified_capture(
        bar_bytes=bar_response_bytes(
            [
                bar_row(
                    "2026-07-06T04:00:00+00:00",
                    o="200.1",
                    h="202.2",
                    low="199.9",
                    c="201.01",
                    v="2000",
                ),
                bar_row(
                    "2026-01-05T05:00:00+00:00",
                    o="100.1",
                    h="101.2",
                    low="99.9",
                    c="100.8",
                    v="1000",
                ),
            ]
        )
    )

    adapted = adapt_valid(verified)

    assert tuple(bar.session_date for bar in adapted.bars) == (
        date(2026, 1, 5),
        date(2026, 7, 6),
    )


def test_empty_bar_response_is_valid_observed_empty_data() -> None:
    verified = sample_verified_capture(bar_bytes=bar_response_bytes([]))

    adapted = adapt_valid(verified)

    assert adapted.bars == ()


@pytest.mark.parametrize(
    "distribution_type",
    ("recurring", "special", "supplemental", "irregular", "unknown"),
)
def test_documented_dividend_distribution_types_are_cash_distributions(
    distribution_type: str,
) -> None:
    verified = sample_verified_capture(
        dividend_bytes=dividend_response_bytes(
            [dividend_row(distribution_type=distribution_type)]
        )
    )

    event = adapt_valid(verified).corporate_action_events[0]

    assert isinstance(event, DailyMarketDataCashDistribution)
    assert event.distribution_classification == distribution_type


def test_optional_dividend_dates_are_not_invented() -> None:
    verified = sample_verified_capture(
        dividend_bytes=dividend_response_bytes(
            [
                dividend_row(
                    declaration_date=None,
                    pay_date=None,
                    record_date=None,
                )
            ]
        )
    )

    event = adapt_valid(verified).corporate_action_events[0]

    assert isinstance(event, DailyMarketDataCashDistribution)
    assert event.announced_at is None
    assert event.payable_date is None
    assert event.record_date is None


def test_empty_dividends_and_splits_are_checked_no_events() -> None:
    verified = sample_verified_capture(
        dividend_bytes=dividend_response_bytes([]),
        split_bytes=split_response_bytes([]),
    )

    adapted = adapt_valid(verified)

    assert adapted.corporate_action_events == ()
    assert adapted.corporate_action_completeness is (
        DailyMarketDataCorporateActionEvidenceCompleteness.CHECKED_NO_EVENTS
    )


def test_dividend_present_and_splits_empty_is_checked_events_captured() -> None:
    verified = sample_verified_capture(split_bytes=split_response_bytes([]))

    adapted = adapt_valid(verified)

    assert len(adapted.corporate_action_events) == 1
    assert adapted.corporate_action_completeness is (
        DailyMarketDataCorporateActionEvidenceCompleteness.CHECKED_EVENTS_CAPTURED
    )


def test_forward_reverse_and_fractional_splits_preserve_exact_ratio_direction() -> None:
    verified = sample_verified_capture(
        dividend_bytes=dividend_response_bytes([]),
        split_bytes=split_response_bytes(
            [
                split_row(
                    event_id="forward",
                    execution_date="2026-02-01",
                    adjustment_type="forward_split",
                    split_from="1",
                    split_to="2",
                ),
                split_row(
                    event_id="reverse",
                    execution_date="2026-03-01",
                    adjustment_type="reverse_split",
                    split_from="10",
                    split_to="1",
                ),
                split_row(
                    event_id="fractional",
                    execution_date="2026-04-01",
                    adjustment_type="forward_split",
                    split_from="1",
                    split_to="1.5",
                ),
                split_row(
                    event_id="decimal-denominator",
                    execution_date="2026-05-01",
                    adjustment_type="reverse_split",
                    split_from="2.5",
                    split_to="1",
                ),
            ]
        ),
    )

    events = adapt_valid(verified).corporate_action_events

    assert [
        (event.event_id, event.numerator, event.denominator) for event in events
    ] == [
        ("forward", 2, 1),
        ("reverse", 1, 10),
        ("fractional", 3, 2),
        ("decimal-denominator", 2, 5),
    ]


def test_high_precision_split_ratio_exceeds_default_decimal_context() -> None:
    verified = sample_verified_capture(
        dividend_bytes=dividend_response_bytes([]),
        split_bytes=split_response_bytes(
            [
                split_row(
                    event_id="high-precision",
                    execution_date="2026-04-01",
                    adjustment_type="forward_split",
                    split_from="1",
                    split_to=HIGH_PRECISION_SPLIT_TO,
                )
            ]
        ),
    )

    event = adapt_valid(verified).corporate_action_events[0]

    assert isinstance(event, DailyMarketDataSplit)
    assert event.numerator == HIGH_PRECISION_NUMERATOR
    assert event.denominator == HIGH_PRECISION_DENOMINATOR


def test_high_precision_split_ratio_is_decimal_context_invariant() -> None:
    verified = sample_verified_capture(
        dividend_bytes=dividend_response_bytes([]),
        split_bytes=split_response_bytes(
            [
                split_row(
                    event_id="high-precision",
                    execution_date="2026-04-01",
                    adjustment_type="forward_split",
                    split_from="1",
                    split_to=HIGH_PRECISION_SPLIT_TO,
                )
            ]
        ),
    )

    with localcontext() as context:
        context.prec = 6
        low_precision_event = adapt_valid(verified).corporate_action_events[0]
    with localcontext() as context:
        context.prec = 50
        high_precision_event = adapt_valid(verified).corporate_action_events[0]

    assert low_precision_event == high_precision_event
    assert isinstance(low_precision_event, DailyMarketDataSplit)
    assert low_precision_event.numerator == HIGH_PRECISION_NUMERATOR
    assert low_precision_event.denominator == HIGH_PRECISION_DENOMINATOR


def test_stock_dividend_and_unknown_split_type_are_unsupported_events() -> None:
    verified = sample_verified_capture(
        dividend_bytes=dividend_response_bytes([]),
        split_bytes=split_response_bytes(
            [
                split_row(
                    event_id="stock-dividend",
                    execution_date="2026-02-01",
                    adjustment_type="stock_dividend",
                    include_ratio=False,
                ),
                split_row(
                    event_id="future-event",
                    execution_date="2026-03-01",
                    adjustment_type="invented_future_adjustment",
                    include_ratio=False,
                ),
            ]
        ),
    )

    events = adapt_valid(verified).corporate_action_events

    assert all(
        event.event_type is DailyMarketDataCorporateActionEventType.UNSUPPORTED
        for event in events
    )
    assert all(
        isinstance(event, DailyMarketDataUnsupportedCorporateAction) for event in events
    )
    assert [event.provider_event_type for event in events] == [
        "stock_dividend",
        "invented_future_adjustment",
    ]


@pytest.mark.parametrize(
    ("member", "payload"),
    (
        (DailyMarketDataSourceCaptureRole.BAR_RESPONSE, b"\xff"),
        (DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE, b'{"status":"OK",}\n'),
        (
            DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
            b'{"status":"OK","status":"OK"}\n',
        ),
        (
            DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
            b'{"status":"OK","results":[{"id":"first","id":"second"}]}\n',
        ),
        (DailyMarketDataSourceCaptureRole.BAR_RESPONSE, b'{"status":NaN}\n'),
        (DailyMarketDataSourceCaptureRole.BAR_RESPONSE, b'{"status":Infinity}\n'),
        (DailyMarketDataSourceCaptureRole.BAR_RESPONSE, b"[]\n"),
    ),
)
def test_strict_json_parser_rejects_invalid_provider_bytes(
    member: DailyMarketDataSourceCaptureRole,
    payload: bytes,
) -> None:
    verified = sample_verified_capture(
        bar_bytes=payload
        if member is DailyMarketDataSourceCaptureRole.BAR_RESPONSE
        else None,
        dividend_bytes=payload
        if member is DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE
        else None,
        split_bytes=payload
        if member is DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE
        else None,
    )

    with pytest.raises(MassiveResponseParsingError):
        adapt_valid(verified)


def test_safe_adapter_diagnostic_set_is_exact_and_finite() -> None:
    assert tuple(
        diagnostic.value for diagnostic in MassiveDailyMarketDataAdapterDiagnostic
    ) == (
        "capture/context authority",
        "BAR_RESPONSE member authority",
        "DIVIDEND_RESPONSE member authority",
        "SPLIT_RESPONSE member authority",
        "BAR_RESPONSE request authority",
        "DIVIDEND_RESPONSE request authority",
        "SPLIT_RESPONSE request authority",
        "corporate-action request compatibility",
        "BAR_RESPONSE parsing",
        "DIVIDEND_RESPONSE parsing",
        "SPLIT_RESPONSE parsing",
        "BAR_RESPONSE semantic adaptation",
        "DIVIDEND_RESPONSE semantic adaptation",
        "SPLIT_RESPONSE semantic adaptation",
        "corporate-action canonicalization",
        "adapted-result construction",
        "unknown adapter failure",
    )


def test_safe_adapter_success_is_exactly_equal_to_ordinary_adapter_output() -> None:
    verified = sample_verified_capture()

    ordinary = adapt_valid(verified)
    safe = adapt_massive_daily_market_data_source_capture_with_diagnostics(
        source_capture=verified,
        context=MassiveDailyMarketDataAdapterContext(
            instrument=INSTRUMENT,
            currency="USD",
        ),
    )

    assert safe.diagnostic is None
    assert safe.adapted == ordinary


@pytest.mark.parametrize(
    ("role", "diagnostic"),
    (
        (
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
            MassiveDailyMarketDataAdapterDiagnostic.BAR_RESPONSE_MEMBER_AUTHORITY,
        ),
        (
            DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
            MassiveDailyMarketDataAdapterDiagnostic.DIVIDEND_RESPONSE_MEMBER_AUTHORITY,
        ),
        (
            DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
            MassiveDailyMarketDataAdapterDiagnostic.SPLIT_RESPONSE_MEMBER_AUTHORITY,
        ),
    ),
)
def test_safe_adapter_categorizes_each_member_authority_failure(
    role: DailyMarketDataSourceCaptureRole,
    diagnostic: MassiveDailyMarketDataAdapterDiagnostic,
) -> None:
    verified = sample_verified_capture(
        member_overrides={role: {"endpoint_family": PROVIDER_SENTINEL}}
    )

    assert_safe_diagnostic(verified, diagnostic)


@pytest.mark.parametrize(
    ("role", "diagnostic"),
    (
        (
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
            MassiveDailyMarketDataAdapterDiagnostic.BAR_RESPONSE_REQUEST_AUTHORITY,
        ),
        (
            DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
            MassiveDailyMarketDataAdapterDiagnostic.DIVIDEND_RESPONSE_REQUEST_AUTHORITY,
        ),
        (
            DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
            MassiveDailyMarketDataAdapterDiagnostic.SPLIT_RESPONSE_REQUEST_AUTHORITY,
        ),
    ),
)
def test_safe_adapter_categorizes_each_request_authority_failure(
    role: DailyMarketDataSourceCaptureRole,
    diagnostic: MassiveDailyMarketDataAdapterDiagnostic,
) -> None:
    verified = sample_verified_capture(
        request_overrides={role: {PROVIDER_SENTINEL: "provider-value"}}
    )

    assert_safe_diagnostic(verified, diagnostic)


@pytest.mark.parametrize(
    ("role", "diagnostic"),
    (
        (
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
            MassiveDailyMarketDataAdapterDiagnostic.BAR_RESPONSE_PARSING,
        ),
        (
            DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
            MassiveDailyMarketDataAdapterDiagnostic.DIVIDEND_RESPONSE_PARSING,
        ),
        (
            DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
            MassiveDailyMarketDataAdapterDiagnostic.SPLIT_RESPONSE_PARSING,
        ),
    ),
)
def test_safe_adapter_categorizes_each_response_parsing_failure(
    role: DailyMarketDataSourceCaptureRole,
    diagnostic: MassiveDailyMarketDataAdapterDiagnostic,
) -> None:
    payload = (
        b'{"status":"OK","'
        + PROVIDER_SENTINEL.encode()
        + b'":1,"'
        + PROVIDER_SENTINEL.encode()
        + b'":2}\n'
    )
    verified = sample_verified_capture(
        bar_bytes=payload
        if role is DailyMarketDataSourceCaptureRole.BAR_RESPONSE
        else None,
        dividend_bytes=payload
        if role is DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE
        else None,
        split_bytes=payload
        if role is DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE
        else None,
    )

    assert_safe_diagnostic(verified, diagnostic)


@pytest.mark.parametrize(
    ("role", "diagnostic"),
    (
        (
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
            MassiveDailyMarketDataAdapterDiagnostic.BAR_RESPONSE_SEMANTIC_ADAPTATION,
        ),
        (
            DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
            MassiveDailyMarketDataAdapterDiagnostic.DIVIDEND_RESPONSE_SEMANTIC_ADAPTATION,
        ),
        (
            DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
            MassiveDailyMarketDataAdapterDiagnostic.SPLIT_RESPONSE_SEMANTIC_ADAPTATION,
        ),
    ),
)
def test_safe_adapter_categorizes_each_semantic_adaptation_failure(
    role: DailyMarketDataSourceCaptureRole,
    diagnostic: MassiveDailyMarketDataAdapterDiagnostic,
) -> None:
    payload = add_json_key(sample_response_for_role(role), PROVIDER_SENTINEL, 1)
    verified = sample_verified_capture(
        bar_bytes=payload
        if role is DailyMarketDataSourceCaptureRole.BAR_RESPONSE
        else None,
        dividend_bytes=payload
        if role is DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE
        else None,
        split_bytes=payload
        if role is DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE
        else None,
    )

    assert_safe_diagnostic(verified, diagnostic)


def test_safe_adapter_categorizes_capture_and_context_authority_failure() -> None:
    verified = sample_verified_capture(provider=PROVIDER_SENTINEL)

    assert_safe_diagnostic(
        verified,
        MassiveDailyMarketDataAdapterDiagnostic.CAPTURE_CONTEXT_AUTHORITY,
    )


def test_safe_adapter_categorizes_cross_endpoint_request_compatibility() -> None:
    verified = sample_verified_capture(
        request_overrides={
            DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE: {
                "execution_date.lte": "2026-06-30"
            }
        }
    )

    assert_safe_diagnostic(
        verified,
        MassiveDailyMarketDataAdapterDiagnostic.CORPORATE_ACTION_REQUEST_COMPATIBILITY,
    )


def test_safe_adapter_categorizes_corporate_action_canonicalization() -> None:
    verified = sample_verified_capture(
        dividend_bytes=dividend_response_bytes(
            [dividend_row(event_id=PROVIDER_SENTINEL)]
        ),
        split_bytes=split_response_bytes([split_row(event_id=PROVIDER_SENTINEL)]),
    )

    assert_safe_diagnostic(
        verified,
        MassiveDailyMarketDataAdapterDiagnostic.CORPORATE_ACTION_CANONICALIZATION,
    )


def test_safe_adapter_categorizes_adapted_result_construction(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        adapter_module,
        "_build_adapted_result",
        lambda **_kwargs: (_ for _ in ()).throw(
            MassiveResponseValidationError(PROVIDER_SENTINEL)
        ),
    )

    assert_safe_diagnostic(
        sample_verified_capture(),
        MassiveDailyMarketDataAdapterDiagnostic.ADAPTED_RESULT_CONSTRUCTION,
    )


@pytest.mark.parametrize("error_type", (ValueError, RuntimeError, KeyError))
def test_safe_adapter_unexpected_internal_exception_fails_closed(
    monkeypatch,
    error_type,
) -> None:
    monkeypatch.setattr(
        adapter_module,
        "_adapt_bars",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error_type(PROVIDER_SENTINEL)),
    )

    assert_safe_diagnostic(
        sample_verified_capture(),
        MassiveDailyMarketDataAdapterDiagnostic.UNKNOWN_ADAPTER_FAILURE,
    )


def test_ordinary_adapter_keeps_detailed_developer_facing_error() -> None:
    verified = sample_verified_capture(
        bar_bytes=add_json_key(sample_bar_response(), PROVIDER_SENTINEL, 1)
    )

    with pytest.raises(MassiveResponseValidationError) as caught:
        adapt_valid(verified)

    assert PROVIDER_SENTINEL in str(caught.value)


@pytest.mark.parametrize(
    ("override", "match"),
    (
        ({"provider": "tiingo"}, "provider"),
        ({"source_family": "other-family"}, "source family"),
        ({"symbol": "SPY"}, "symbol"),
    ),
)
def test_capture_and_context_mismatches_fail(
    override: dict[str, str],
    match: str,
) -> None:
    verified = sample_verified_capture(**override)

    with pytest.raises(MassiveResponseValidationError, match=match):
        adapt_valid(verified)


@pytest.mark.parametrize(
    ("role", "metadata_override", "match"),
    (
        (
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
            {"endpoint_family": "wrong"},
            "endpoint_family",
        ),
        (
            DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
            {"endpoint_version": "v9"},
            "endpoint_version",
        ),
        (
            DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
            {"endpoint_family": "wrong"},
            "endpoint_family",
        ),
    ),
)
def test_endpoint_metadata_mismatch_fails(
    role: DailyMarketDataSourceCaptureRole,
    metadata_override: dict[str, str],
    match: str,
) -> None:
    verified = sample_verified_capture(member_overrides={role: metadata_override})

    with pytest.raises(MassiveResponseValidationError, match=match):
        adapt_valid(verified)


@pytest.mark.parametrize(
    ("role", "request_override", "match"),
    (
        (
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
            {"adjusted": "true"},
            "adjusted",
        ),
        (
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
            {"timespan": "minute"},
            "timespan",
        ),
        (
            DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
            {"ex_dividend_date.lte": "2025-12-31"},
            "coverage",
        ),
        (
            DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
            {"ticker": "SPY"},
            "ticker",
        ),
    ),
)
def test_structured_request_authority_mismatch_fails(
    role: DailyMarketDataSourceCaptureRole,
    request_override: dict[str, str],
    match: str,
) -> None:
    verified = sample_verified_capture(request_overrides={role: request_override})

    with pytest.raises(MassiveResponseValidationError, match=match):
        adapt_valid(verified)


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        ("adjusted_true", "adjusted"),
        ("missing_adjusted", "adjusted"),
        ("wrong_ticker", "ticker"),
        ("error_status", "status"),
        ("request_id_mismatch", "request_id"),
        ("unknown_field", "unknown"),
        ("pagination", "next_url"),
    ),
)
def test_bar_top_level_validation_fails(mutation: str, match: str) -> None:
    bar_payload = {
        "adjusted_true": replace_json_value(sample_bar_response(), "adjusted", True),
        "missing_adjusted": drop_json_key(sample_bar_response(), "adjusted"),
        "wrong_ticker": replace_json_value(sample_bar_response(), "ticker", "SPY"),
        "error_status": replace_json_value(sample_bar_response(), "status", "ERROR"),
        "request_id_mismatch": replace_json_value(
            sample_bar_response(),
            "request_id",
            "other",
        ),
        "unknown_field": add_json_key(sample_bar_response(), "unexpected", 1),
        "pagination": replace_json_value(
            sample_bar_response(),
            "next_url",
            "https://example.test/page2",
        ),
    }[mutation]
    verified = sample_verified_capture(bar_bytes=bar_payload)

    with pytest.raises(MassiveResponseValidationError, match=match):
        adapt_valid(verified)


@pytest.mark.parametrize(
    "role",
    (
        DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
        DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
        DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
    ),
)
def test_stocks_responses_reject_undocumented_top_level_count(
    role: DailyMarketDataSourceCaptureRole,
) -> None:
    payload = add_json_key(sample_response_for_role(role), "count", 1)
    verified = sample_verified_capture(
        bar_bytes=payload
        if role is DailyMarketDataSourceCaptureRole.BAR_RESPONSE
        else None,
        dividend_bytes=payload
        if role is DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE
        else None,
        split_bytes=payload
        if role is DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE
        else None,
    )

    with pytest.raises(MassiveResponseValidationError, match="unknown"):
        adapt_valid(verified)


@pytest.mark.parametrize(
    "role",
    (
        DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
        DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
        DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
    ),
)
@pytest.mark.parametrize(
    ("next_url", "match"),
    (
        ("https://example.test/page2", "pagination"),
        ("", "absent"),
        (None, "absent"),
        (123, "absent"),
        ({"url": "https://example.test/page2"}, "absent"),
        (["https://example.test/page2"], "absent"),
    ),
)
def test_next_url_indicator_is_strict_and_never_followed(
    role: DailyMarketDataSourceCaptureRole,
    next_url: object,
    match: str,
) -> None:
    payload = add_json_key(sample_response_for_role(role), "next_url", next_url)
    verified = sample_verified_capture(
        bar_bytes=payload
        if role is DailyMarketDataSourceCaptureRole.BAR_RESPONSE
        else None,
        dividend_bytes=payload
        if role is DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE
        else None,
        split_bytes=payload
        if role is DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE
        else None,
    )

    with pytest.raises(MassiveResponseValidationError, match=match):
        adapt_valid(verified)


@pytest.mark.parametrize(
    ("response_request_id", "capture_request_id"),
    (("123", "123"), (123, "123")),
)
def test_request_id_accepts_string_or_integer_evidence_coherence(
    response_request_id: object,
    capture_request_id: str,
) -> None:
    verified = sample_verified_capture(
        bar_bytes=replace_json_value(
            sample_bar_response(),
            "request_id",
            response_request_id,
        ),
        member_overrides={
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE: {
                "api_request_id": capture_request_id
            }
        },
    )

    assert adapt_valid(verified).capture_id == verified.capture_id


@pytest.mark.parametrize("request_id", (True, Decimal("123.5"), "", " 123"))
def test_request_id_rejects_invalid_or_whitespace_values(request_id: object) -> None:
    verified = sample_verified_capture(
        bar_bytes=replace_json_value(sample_bar_response(), "request_id", request_id),
        member_overrides={
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE: {"api_request_id": None}
        },
    )

    with pytest.raises(MassiveResponseValidationError, match="request_id"):
        adapt_valid(verified)


@pytest.mark.parametrize(
    ("row_override", "match"),
    (
        ({"o": "100.1"}, "exact JSON number"),
        ({"h": False}, "exact JSON number"),
        ({"l": None}, "required"),
        ({"c": -1}, "canonical OHLCV"),
        ({"h": "98", "l": "99"}, "exact JSON number"),
        ({"v": "100"}, "integer"),
        ({"v": "100.5"}, "integer"),
        ({"v": "-1"}, "nonnegative"),
        ({"n": "1.25"}, "integer"),
        ({"otc": "false"}, "otc"),
        ({"t": "1760000000000"}, "timestamp"),
        ({"extra": 1}, "unknown"),
    ),
)
def test_bar_row_validation_fails(row_override: dict[str, object], match: str) -> None:
    row = bar_row("2026-01-05T05:00:00+00:00")
    row.update(row_override)
    verified = sample_verified_capture(bar_bytes=bar_response_bytes([row]))

    with pytest.raises(MassiveResponseValidationError, match=match):
        adapt_valid(verified)


def test_bar_row_missing_required_field_fails() -> None:
    row = bar_row("2026-01-05T05:00:00+00:00")
    del row["o"]
    verified = sample_verified_capture(bar_bytes=bar_response_bytes([row]))

    with pytest.raises(MassiveResponseValidationError, match="required"):
        adapt_valid(verified)


def test_duplicate_normalized_bar_session_fails() -> None:
    row = bar_row("2026-01-05T05:00:00+00:00")
    verified = sample_verified_capture(bar_bytes=bar_response_bytes([row, row]))

    with pytest.raises(MassiveResponseValidationError, match="duplicate"):
        adapt_valid(verified)


def test_out_of_range_bar_session_fails() -> None:
    verified = sample_verified_capture(
        bar_bytes=bar_response_bytes([bar_row("2025-12-31T05:00:00+00:00")])
    )

    with pytest.raises(MassiveResponseValidationError, match="outside requested"):
        adapt_valid(verified)


@pytest.mark.parametrize(
    ("milliseconds", "expected_session_date"),
    (
        (1767589200000, date(2026, 1, 5)),
        (1767589199999, date(2026, 1, 4)),
    ),
)
def test_epoch_millisecond_boundary_uses_exact_new_york_date(
    milliseconds: int,
    expected_session_date: date,
) -> None:
    verified = sample_verified_capture(
        bar_bytes=bar_response_bytes([bar_row_from_millis(milliseconds)]),
        request_overrides={
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE: {
                "from": "2026-01-04",
                "to": "2026-01-05",
            }
        },
    )

    assert adapt_valid(verified).bars[0].session_date == expected_session_date


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        ("error_status", "status"),
        ("request_id_mismatch", "request_id"),
        ("pagination", "next_url"),
        ("unknown_field", "unknown"),
    ),
)
def test_dividend_top_level_validation_fails(mutation: str, match: str) -> None:
    dividend_payload = {
        "error_status": replace_json_value(
            sample_dividend_response(),
            "status",
            "ERROR",
        ),
        "request_id_mismatch": replace_json_value(
            sample_dividend_response(),
            "request_id",
            "other",
        ),
        "pagination": add_json_key(
            sample_dividend_response(),
            "next_url",
            "https://example.test/page2",
        ),
        "unknown_field": add_json_key(sample_dividend_response(), "unexpected", 1),
    }[mutation]
    verified = sample_verified_capture(dividend_bytes=dividend_payload)

    with pytest.raises(MassiveResponseValidationError, match=match):
        adapt_valid(verified)


@pytest.mark.parametrize(
    ("row_override", "error_type", "match"),
    (
        ({"ticker": "SPY"}, MassiveResponseValidationError, "ticker"),
        ({"id": ""}, MassiveResponseValidationError, "non-empty"),
        ({"cash_amount": 0}, MassiveResponseValidationError, "positive"),
        ({"cash_amount": -1}, MassiveResponseValidationError, "positive"),
        ({"cash_amount": "0.1"}, MassiveResponseValidationError, "exact JSON number"),
        ({"currency": "CAD"}, MassiveResponseValidationError, "currency"),
        ({"ex_dividend_date": "2026-13-01"}, MassiveResponseValidationError, "date"),
        ({"ex_dividend_date": "2027-01-01"}, MassiveResponseValidationError, "outside"),
        ({"frequency": "4"}, MassiveResponseValidationError, "integer"),
        (
            {"historical_adjustment_factor": "1.0"},
            MassiveResponseValidationError,
            "exact JSON number",
        ),
        (
            {"distribution_type": "invented"},
            MassiveUnsupportedSemanticError,
            "unsupported",
        ),
        ({"extra": 1}, MassiveResponseValidationError, "unknown"),
    ),
)
def test_dividend_row_validation_fails(
    row_override: dict[str, object],
    error_type: type[Exception],
    match: str,
) -> None:
    row = dividend_row()
    row.update(row_override)
    verified = sample_verified_capture(dividend_bytes=dividend_response_bytes([row]))

    with pytest.raises(error_type, match=match):
        adapt_valid(verified)


@pytest.mark.parametrize("field", ("id", "ex_dividend_date", "cash_amount"))
def test_dividend_missing_required_field_fails(field: str) -> None:
    row = dividend_row()
    del row[field]
    verified = sample_verified_capture(dividend_bytes=dividend_response_bytes([row]))

    with pytest.raises(MassiveResponseValidationError, match="required"):
        adapt_valid(verified)


def test_duplicate_dividend_id_fails() -> None:
    verified = sample_verified_capture(
        dividend_bytes=dividend_response_bytes([dividend_row(), dividend_row()])
    )

    with pytest.raises(MassiveResponseValidationError, match="duplicate"):
        adapt_valid(verified)


def test_context_currency_rejects_blank_or_whitespace() -> None:
    verified = sample_verified_capture()

    with pytest.raises(MassiveResponseValidationError, match="context.currency"):
        adapt_massive_daily_market_data_source_capture(
            source_capture=verified,
            context=MassiveDailyMarketDataAdapterContext(
                instrument=INSTRUMENT,
                currency="   ",
            ),
        )


def test_cash_distribution_contract_errors_are_wrapped_as_adapter_errors() -> None:
    unsafe_id = "https://example.test/dividend?api_key=synthetic"
    verified = sample_verified_capture(
        dividend_bytes=dividend_response_bytes([dividend_row(event_id=unsafe_id)])
    )

    with pytest.raises(MassiveResponseValidationError, match="cash-distribution"):
        adapt_valid(verified)


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        ("error_status", "status"),
        ("request_id_mismatch", "request_id"),
        ("pagination", "next_url"),
        ("unknown_field", "unknown"),
    ),
)
def test_split_top_level_validation_fails(mutation: str, match: str) -> None:
    split_payload = {
        "error_status": replace_json_value(sample_split_response(), "status", "ERROR"),
        "request_id_mismatch": replace_json_value(
            sample_split_response(),
            "request_id",
            "other",
        ),
        "pagination": add_json_key(
            sample_split_response(),
            "next_url",
            "https://example.test/page2",
        ),
        "unknown_field": add_json_key(sample_split_response(), "unexpected", 1),
    }[mutation]
    verified = sample_verified_capture(
        dividend_bytes=dividend_response_bytes([]),
        split_bytes=split_payload,
    )

    with pytest.raises(MassiveResponseValidationError, match=match):
        adapt_valid(verified)


@pytest.mark.parametrize(
    ("split_override", "match"),
    (
        ({"ticker": "SPY"}, "ticker"),
        ({"id": ""}, "non-empty"),
        ({"execution_date": "2026-99-01"}, "date"),
        ({"execution_date": "2027-01-01"}, "outside"),
        ({"split_to": 1, "split_from": 1}, "1:1"),
        ({"split_to": 0}, "positive"),
        ({"split_from": -1}, "positive"),
        ({"split_to": "2"}, "exact JSON number"),
        (
            {"adjustment_type": "forward_split", "split_to": 1, "split_from": 2},
            "forward_split",
        ),
        (
            {"adjustment_type": "reverse_split", "split_to": 2, "split_from": 1},
            "reverse_split",
        ),
        ({"historical_adjustment_factor": "1.0"}, "exact JSON number"),
        ({"extra": 1}, "unknown"),
    ),
)
def test_split_row_validation_fails(
    split_override: dict[str, object],
    match: str,
) -> None:
    row = split_row()
    row.update(split_override)
    verified = sample_verified_capture(
        dividend_bytes=dividend_response_bytes([]),
        split_bytes=split_response_bytes([row]),
    )

    with pytest.raises(MassiveResponseValidationError, match=match):
        adapt_valid(verified)


def test_ordinary_split_missing_ratio_field_fails() -> None:
    verified = sample_verified_capture(
        dividend_bytes=dividend_response_bytes([]),
        split_bytes=split_response_bytes(
            [split_row(adjustment_type="forward_split", include_ratio=False)]
        ),
    )

    with pytest.raises(MassiveResponseValidationError, match="split_"):
        adapt_valid(verified)


def test_unsupported_event_contract_errors_are_wrapped_as_adapter_errors() -> None:
    unsafe_id = "https://example.test/split?api_key=synthetic"
    verified = sample_verified_capture(
        dividend_bytes=dividend_response_bytes([]),
        split_bytes=split_response_bytes(
            [
                split_row(
                    event_id=unsafe_id,
                    adjustment_type="stock_dividend",
                    include_ratio=False,
                )
            ]
        ),
    )

    with pytest.raises(MassiveResponseValidationError, match="unsupported-event"):
        adapt_valid(verified)


def test_event_id_collision_across_dividend_and_split_fails() -> None:
    verified = sample_verified_capture(
        dividend_bytes=dividend_response_bytes(
            [dividend_row(event_id="same-provider-id")]
        ),
        split_bytes=split_response_bytes([split_row(event_id="same-provider-id")]),
    )

    with pytest.raises(MassiveResponseValidationError, match="unique"):
        adapt_valid(verified)


def test_dividend_split_coverage_mismatch_fails() -> None:
    verified = sample_verified_capture(
        request_overrides={
            DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE: {
                "execution_date.lte": "2026-06-30"
            }
        }
    )

    with pytest.raises(MassiveResponseValidationError, match="identical"):
        adapt_valid(verified)


@pytest.mark.parametrize(
    ("role", "missing_key", "scope_key", "scope_value"),
    (
        (
            DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
            "ex_dividend_date.gte",
            "ex_dividend_date.gte",
            "2026-01-01",
        ),
        (
            DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
            "execution_date.gte",
            "execution_date.gte",
            "2026-01-01",
        ),
    ),
)
def test_missing_actual_ca_bound_cannot_be_supplied_by_requested_scope(
    role: DailyMarketDataSourceCaptureRole,
    missing_key: str,
    scope_key: str,
    scope_value: str,
) -> None:
    verified = sample_verified_capture(
        request_overrides={role: {missing_key: None}},
        member_overrides={role: {"requested_scope": ((scope_key, scope_value),)}},
    )

    with pytest.raises(MassiveResponseValidationError, match="requested_scope"):
        adapt_valid(verified)


@pytest.mark.parametrize(
    "role",
    (
        DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
        DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
    ),
)
def test_missing_actual_ca_ticker_cannot_be_supplied_by_requested_scope(
    role: DailyMarketDataSourceCaptureRole,
) -> None:
    verified = sample_verified_capture(
        request_overrides={role: {"ticker": None}},
        member_overrides={role: {"requested_scope": (("ticker", "QQQ"),)}},
    )

    with pytest.raises(MassiveResponseValidationError, match="requested_scope"):
        adapt_valid(verified)


def test_missing_actual_bar_scope_cannot_be_supplied_by_requested_scope() -> None:
    verified = sample_verified_capture(
        request_overrides={
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE: {"from": None}
        },
        member_overrides={
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE: {
                "requested_scope": (("from", "2026-01-05"),)
            }
        },
    )

    with pytest.raises(MassiveResponseValidationError, match="requested_scope"):
        adapt_valid(verified)


def test_conflicting_request_parameter_and_requested_scope_fails() -> None:
    verified = sample_verified_capture(
        member_overrides={
            DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE: {
                "requested_scope": (("ex_dividend_date.gte", "2025-01-01"),)
            },
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE: {
                "requested_scope": (("from", "2025-01-01"),)
            },
        }
    )

    with pytest.raises(MassiveResponseValidationError, match="contradict"):
        adapt_valid(verified)


def test_coherent_redundant_request_parameter_and_requested_scope_is_allowed() -> None:
    verified = sample_verified_capture(
        member_overrides={
            DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE: {
                "requested_scope": (("ex_dividend_date.gte", "2026-01-01"),)
            },
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE: {
                "requested_scope": (("from", "2026-01-05"),)
            },
        }
    )

    assert adapt_valid(verified).capture_id == verified.capture_id


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("distribution_type", "recurring"),
        ("frequency", "4"),
        ("cash_amount.gt", "0.5"),
        ("declaration_date.gte", "2026-01-01"),
        ("pay_date.lte", "2026-12-31"),
        ("record_date", "2026-03-16"),
    ),
)
def test_dividend_semantic_narrowing_request_filters_fail(
    field: str,
    value: str,
) -> None:
    verified = sample_verified_capture(
        request_overrides={
            DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE: {field: value}
        }
    )

    with pytest.raises(MassiveResponseValidationError, match="unsupported"):
        adapt_valid(verified)


def test_split_semantic_narrowing_request_filter_fails() -> None:
    verified = sample_verified_capture(
        request_overrides={
            DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE: {
                "adjustment_type": "forward_split"
            }
        }
    )

    with pytest.raises(MassiveResponseValidationError, match="unsupported"):
        adapt_valid(verified)


@pytest.mark.parametrize(
    "role",
    (
        DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
        DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
        DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
    ),
)
def test_unknown_request_parameter_fails(
    role: DailyMarketDataSourceCaptureRole,
) -> None:
    verified = sample_verified_capture(
        request_overrides={role: {"invented_future_filter": "value"}}
    )

    with pytest.raises(MassiveResponseValidationError, match="unsupported"):
        adapt_valid(verified)


def test_requested_scope_rejects_transport_parameters() -> None:
    verified = sample_verified_capture(
        member_overrides={
            DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE: {
                "requested_scope": (("limit", "5000"),)
            }
        }
    )

    with pytest.raises(MassiveResponseValidationError, match="requested_scope"):
        adapt_valid(verified)


def test_valid_operational_sort_and_limit_parameters_are_allowed() -> None:
    verified = sample_verified_capture(
        request_overrides={
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE: {
                "limit": "50000",
                "sort": "desc",
            },
            DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE: {
                "limit": "5000",
                "sort": "ex_dividend_date.asc",
            },
            DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE: {
                "limit": "5000",
                "sort": "execution_date.asc",
            },
        }
    )

    assert adapt_valid(verified).capture_id == verified.capture_id


@pytest.mark.parametrize(
    ("role", "field", "value"),
    (
        (DailyMarketDataSourceCaptureRole.BAR_RESPONSE, "limit", "0"),
        (DailyMarketDataSourceCaptureRole.BAR_RESPONSE, "limit", "-1"),
        (DailyMarketDataSourceCaptureRole.BAR_RESPONSE, "limit", "50001"),
        (DailyMarketDataSourceCaptureRole.BAR_RESPONSE, "limit", "1.5"),
        (DailyMarketDataSourceCaptureRole.BAR_RESPONSE, "limit", " 100"),
        (DailyMarketDataSourceCaptureRole.BAR_RESPONSE, "limit", "abc"),
        (DailyMarketDataSourceCaptureRole.BAR_RESPONSE, "sort", "ticker.asc"),
        (DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE, "limit", "0"),
        (DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE, "limit", "-1"),
        (DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE, "limit", "5001"),
        (DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE, "limit", "1.5"),
        (DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE, "limit", " 100"),
        (DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE, "limit", "abc"),
        (DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE, "sort", "asc"),
        (DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE, "limit", "0"),
        (DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE, "limit", "-1"),
        (DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE, "limit", "5001"),
        (DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE, "limit", "1.5"),
        (DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE, "limit", " 100"),
        (DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE, "limit", "abc"),
        (DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE, "sort", "asc"),
    ),
)
def test_invalid_operational_sort_and_limit_parameters_fail(
    role: DailyMarketDataSourceCaptureRole,
    field: str,
    value: str,
) -> None:
    verified = sample_verified_capture(request_overrides={role: {field: value}})
    if value != value.strip():
        verified = verified_with_unvalidated_request_parameter(
            verified,
            role=role,
            field=field,
            value=value,
        )

    with pytest.raises(MassiveResponseValidationError):
        adapt_valid(verified)


@pytest.mark.parametrize(
    "role",
    (
        DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
        DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
        DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
    ),
)
def test_pagination_fails_even_with_maximum_allowed_limit(
    role: DailyMarketDataSourceCaptureRole,
) -> None:
    limit = "50000" if role is DailyMarketDataSourceCaptureRole.BAR_RESPONSE else "5000"
    payload = add_json_key(
        sample_response_for_role(role),
        "next_url",
        "https://example.test/page2",
    )
    verified = sample_verified_capture(
        bar_bytes=payload
        if role is DailyMarketDataSourceCaptureRole.BAR_RESPONSE
        else None,
        dividend_bytes=payload
        if role is DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE
        else None,
        split_bytes=payload
        if role is DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE
        else None,
        request_overrides={role: {"limit": limit}},
    )

    with pytest.raises(MassiveResponseValidationError, match="next_url"):
        adapt_valid(verified)


def test_unsupported_split_valid_optional_ratio_fields_are_shape_validated() -> None:
    verified = sample_verified_capture(
        dividend_bytes=dividend_response_bytes([]),
        split_bytes=split_response_bytes(
            [
                split_row(
                    event_id="stock-dividend",
                    adjustment_type="stock_dividend",
                    split_from="1",
                    split_to="1.25",
                )
            ]
        ),
    )

    event = adapt_valid(verified).corporate_action_events[0]

    assert isinstance(event, DailyMarketDataUnsupportedCorporateAction)
    assert event.provider_event_type == "stock_dividend"


@pytest.mark.parametrize(
    ("adjustment_type", "field_name", "field_value"),
    (
        ("stock_dividend", "split_from", "bad"),
        ("invented_future_adjustment", "split_to", False),
    ),
)
def test_unsupported_split_optional_ratio_fields_must_be_valid_when_present(
    adjustment_type: str,
    field_name: str,
    field_value: object,
) -> None:
    row = split_row(adjustment_type=adjustment_type, include_ratio=False)
    row[field_name] = field_value
    verified = sample_verified_capture(
        dividend_bytes=dividend_response_bytes([]),
        split_bytes=split_response_bytes([row]),
    )

    with pytest.raises(MassiveResponseValidationError):
        adapt_valid(verified)


def test_no_filesystem_or_local_loader_api_is_exposed() -> None:
    assert "source_capture_root" not in (
        adapt_massive_daily_market_data_source_capture.__annotations__
    )
    assert (
        "capture_id"
        not in adapt_massive_daily_market_data_source_capture.__annotations__
    )


def adapt_valid(
    verified: VerifiedDailyMarketDataSourceCapture,
) -> AdaptedMassiveDailyMarketData:
    return adapt_massive_daily_market_data_source_capture(
        source_capture=verified,
        context=MassiveDailyMarketDataAdapterContext(
            instrument=INSTRUMENT,
            currency="USD",
        ),
    )


def assert_safe_diagnostic(
    verified: VerifiedDailyMarketDataSourceCapture,
    expected: MassiveDailyMarketDataAdapterDiagnostic,
) -> None:
    result = adapt_massive_daily_market_data_source_capture_with_diagnostics(
        source_capture=verified,
        context=MassiveDailyMarketDataAdapterContext(
            instrument=INSTRUMENT,
            currency="USD",
        ),
    )

    assert result.adapted is None
    assert result.diagnostic is expected
    assert PROVIDER_SENTINEL not in str(result)
    assert PROVIDER_SENTINEL not in repr(result)
    assert not any(isinstance(value, BaseException) for value in vars(result).values())


def sample_verified_capture(
    *,
    provider: str = MASSIVE_PROVIDER,
    source_family: str = MASSIVE_SOURCE_FAMILY,
    instrument_id: str = "us-equity:QQQ",
    symbol: str = "QQQ",
    bar_bytes: bytes | None = None,
    dividend_bytes: bytes | None = None,
    split_bytes: bytes | None = None,
    member_overrides: dict[DailyMarketDataSourceCaptureRole, dict[str, object]]
    | None = None,
    request_overrides: dict[DailyMarketDataSourceCaptureRole, dict[str, str | None]]
    | None = None,
) -> VerifiedDailyMarketDataSourceCapture:
    plan = plan_daily_market_data_source_capture(
        provider=provider,
        source_family=source_family,
        instrument_id=instrument_id,
        symbol=symbol,
        capture_observed_at=CAPTURE_OBSERVED_AT,
        members=(
            member_input(
                DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
                content=bar_bytes if bar_bytes is not None else sample_bar_response(),
                overrides=(member_overrides or {}).get(
                    DailyMarketDataSourceCaptureRole.BAR_RESPONSE, {}
                ),
                request_override=(request_overrides or {}).get(
                    DailyMarketDataSourceCaptureRole.BAR_RESPONSE, {}
                ),
            ),
            member_input(
                DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
                content=(
                    dividend_bytes
                    if dividend_bytes is not None
                    else sample_dividend_response()
                ),
                overrides=(member_overrides or {}).get(
                    DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE, {}
                ),
                request_override=(request_overrides or {}).get(
                    DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE, {}
                ),
            ),
            member_input(
                DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
                content=split_bytes
                if split_bytes is not None
                else sample_split_response(),
                overrides=(member_overrides or {}).get(
                    DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE, {}
                ),
                request_override=(request_overrides or {}).get(
                    DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE, {}
                ),
            ),
        ),
        acquisition_batch_id="synthetic-s3c3b3-batch",
    )
    return verify_daily_market_data_source_capture(plan.as_file_map())


def verified_with_unvalidated_request_parameter(
    verified: VerifiedDailyMarketDataSourceCapture,
    *,
    role: DailyMarketDataSourceCaptureRole,
    field: str,
    value: str,
) -> VerifiedDailyMarketDataSourceCapture:
    members = []
    for member in verified.capture_manifest.members:
        if member.role is not role:
            members.append(member)
            continue
        parameters = {
            parameter.key: parameter.value for parameter in member.request_parameters
        }
        parameters[field] = value
        request_parameters = tuple(
            DailyMarketDataSourceCaptureRequestParameter.model_construct(
                key=key,
                value=parameter_value,
            )
            for key, parameter_value in sorted(parameters.items())
        )
        members.append(
            member.model_copy(update={"request_parameters": request_parameters})
        )
    return replace(
        verified,
        capture_manifest=verified.capture_manifest.model_copy(
            update={"members": tuple(members)}
        ),
    )


def member_input(
    role: DailyMarketDataSourceCaptureRole,
    *,
    content: bytes,
    overrides: dict[str, object],
    request_override: dict[str, str | None],
) -> DailyMarketDataSourceCaptureMemberInput:
    endpoint_family = {
        DailyMarketDataSourceCaptureRole.BAR_RESPONSE: MASSIVE_BAR_ENDPOINT_FAMILY,
        DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE: (
            MASSIVE_DIVIDEND_ENDPOINT_FAMILY
        ),
        DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE: MASSIVE_SPLIT_ENDPOINT_FAMILY,
    }[role]
    endpoint_version = {
        DailyMarketDataSourceCaptureRole.BAR_RESPONSE: MASSIVE_BAR_ENDPOINT_VERSION,
        DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE: (
            MASSIVE_DIVIDEND_ENDPOINT_VERSION
        ),
        DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE: MASSIVE_SPLIT_ENDPOINT_VERSION,
    }[role]
    request_parameters = {
        DailyMarketDataSourceCaptureRole.BAR_RESPONSE: {
            "adjusted": "false",
            "from": "2026-01-05",
            "multiplier": "1",
            "ticker": "QQQ",
            "timespan": "day",
            "to": "2026-07-06",
        },
        DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE: {
            "ex_dividend_date.gte": "2026-01-01",
            "ex_dividend_date.lte": "2026-12-31",
            "ticker": "QQQ",
        },
        DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE: {
            "execution_date.gte": "2026-01-01",
            "execution_date.lte": "2026-12-31",
            "ticker": "QQQ",
        },
    }[role]
    for key, value in request_override.items():
        if value is None:
            request_parameters.pop(key, None)
        else:
            request_parameters[key] = value
    data = {
        "role": role,
        "endpoint_family": endpoint_family,
        "endpoint_version": endpoint_version,
        "request_parameters": tuple(sorted(request_parameters.items())),
        "sanitized_source_reference": f"synthetic:massive:{role.value}",
        "content": content,
        "http_status": 200,
        "media_type": "application/json",
        "api_request_id": f"synthetic-{role.value.lower()}-request",
    }
    data.update(overrides)
    return DailyMarketDataSourceCaptureMemberInput(**data)


def sample_bar_response() -> bytes:
    return bar_response_bytes(
        [
            bar_row(
                "2026-01-05T05:00:00+00:00",
                o="100.123456789123456789",
                h="101.25",
                low="99.75",
                c="100.5",
                v="1000",
            ),
            bar_row(
                "2026-07-06T04:00:00+00:00",
                o="200.1",
                h="202.2",
                low="199.9",
                c="201.01",
                v="2000",
            ),
        ]
    )


def sample_dividend_response() -> bytes:
    return dividend_response_bytes([dividend_row()])


def sample_split_response() -> bytes:
    return split_response_bytes([split_row()])


def sample_response_for_role(role: DailyMarketDataSourceCaptureRole) -> bytes:
    return {
        DailyMarketDataSourceCaptureRole.BAR_RESPONSE: sample_bar_response,
        DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE: sample_dividend_response,
        DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE: sample_split_response,
    }[role]()


def bar_response_bytes(rows: list[dict[str, object]]) -> bytes:
    return (
        b'{"adjusted":false,"queryCount":'
        + str(len(rows)).encode()
        + b',"request_id":"synthetic-bar_response-request","results":['
        + b",".join(json_object_bytes(row).rstrip(b"\n") for row in rows)
        + b'],"resultsCount":'
        + str(len(rows)).encode()
        + b',"status":"OK","ticker":"QQQ"}\n'
    )


def bar_row(
    timestamp: str,
    *,
    o: str = "100.1",
    h: str = "101.2",
    low: str = "99.9",
    c: str = "100.8",
    v: str = "1000",
) -> dict[str, object]:
    milliseconds = epoch_millis_from_iso(timestamp)
    return bar_row_from_millis(milliseconds, o=o, h=h, low=low, c=c, v=v)


def bar_row_from_millis(
    milliseconds: int,
    *,
    o: str = "100.1",
    h: str = "101.2",
    low: str = "99.9",
    c: str = "100.8",
    v: str = "1000",
) -> dict[str, object]:
    return {
        "c": Decimal(c),
        "h": Decimal(h),
        "l": Decimal(low),
        "n": 12,
        "o": Decimal(o),
        "otc": False,
        "t": milliseconds,
        "v": Decimal(v),
        "vw": Decimal("100.333333333333333333"),
    }


def epoch_millis_from_iso(timestamp: str) -> int:
    instant = datetime.fromisoformat(timestamp).astimezone(UTC)
    delta = instant - UNIX_EPOCH
    return delta.days * 86_400_000 + delta.seconds * 1_000 + delta.microseconds // 1_000


def dividend_response_bytes(rows: list[dict[str, object]]) -> bytes:
    return json_response_bytes(
        {
            "request_id": "synthetic-dividend_response-request",
            "results": rows,
            "status": "OK",
        }
    )


def dividend_row(
    *,
    event_id: str = "synthetic-dividend-1",
    distribution_type: str = "recurring",
    declaration_date: str | None = "2026-03-01",
    pay_date: str | None = "2026-03-30",
    record_date: str | None = "2026-03-16",
) -> dict[str, object]:
    row: dict[str, object] = {
        "cash_amount": Decimal("0.123456789123456789"),
        "currency": "USD",
        "distribution_type": distribution_type,
        "ex_dividend_date": "2026-03-15",
        "frequency": 4,
        "historical_adjustment_factor": Decimal("1"),
        "id": event_id,
        "split_adjusted_cash_amount": Decimal("0.123456789123456789"),
        "ticker": "QQQ",
    }
    if declaration_date is not None:
        row["declaration_date"] = declaration_date
    if pay_date is not None:
        row["pay_date"] = pay_date
    if record_date is not None:
        row["record_date"] = record_date
    return row


def split_response_bytes(rows: list[dict[str, object]]) -> bytes:
    return json_response_bytes(
        {
            "request_id": "synthetic-split_response-request",
            "results": rows,
            "status": "OK",
        }
    )


def split_row(
    *,
    event_id: str = "synthetic-split-1",
    execution_date: str = "2026-06-01",
    adjustment_type: str = "forward_split",
    split_from: str | int = "1",
    split_to: str | int = "2",
    include_ratio: bool = True,
) -> dict[str, object]:
    row: dict[str, object] = {
        "adjustment_type": adjustment_type,
        "execution_date": execution_date,
        "historical_adjustment_factor": Decimal("1"),
        "id": event_id,
        "ticker": "QQQ",
    }
    if include_ratio:
        row["split_from"] = Decimal(str(split_from))
        row["split_to"] = Decimal(str(split_to))
    return row


def json_response_bytes(payload: dict[str, object]) -> bytes:
    return json_object_bytes(payload)


def json_object_bytes(payload: object) -> bytes:
    return (_render_json(payload) + "\n").encode()


def _render_json(value: object) -> str:
    if isinstance(value, dict):
        return (
            "{"
            + ",".join(
                json.dumps(str(key), separators=(",", ":"))
                + ":"
                + _render_json(value[key])
                for key in sorted(value)
            )
            + "}"
        )
    if isinstance(value, list):
        return "[" + ",".join(_render_json(item) for item in value) + "]"
    if isinstance(value, Decimal):
        return format(value, "f")
    return json.dumps(value, separators=(",", ":"))


def replace_json_value(data: bytes, key: str, value: object) -> bytes:
    payload = json.loads(data, parse_float=Decimal, parse_int=int)
    payload[key] = value
    return json_response_bytes(payload)


def drop_json_key(data: bytes, key: str) -> bytes:
    payload = json.loads(data, parse_float=Decimal, parse_int=int)
    del payload[key]
    return json_response_bytes(payload)


def add_json_key(data: bytes, key: str, value: object) -> bytes:
    payload = json.loads(data, parse_float=Decimal, parse_int=int)
    payload[key] = value
    return json_response_bytes(payload)
