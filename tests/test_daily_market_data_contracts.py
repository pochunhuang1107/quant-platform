from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from research_sdk.contracts import AssetClass, DataAdjustmentPolicy
from research_sdk.contracts.daily_market_data import (
    CanonicalDailyBar,
    DailyMarketDataInstrument,
    DailyMarketDataPolicy,
    DailyMarketDataQualityCode,
    DailyMarketDataQualityReport,
    DailyMarketDataQualityStatus,
    DistributionTreatment,
)


def test_daily_market_data_instrument_accepts_provider_neutral_identity() -> None:
    instrument = DailyMarketDataInstrument(
        instrument_id="instrument-us-etf-qqq-xnas",
        symbol="QQQ",
        venue="XNAS",
    )

    assert instrument.instrument_id == "instrument-us-etf-qqq-xnas"
    assert instrument.symbol == "QQQ"
    assert instrument.venue == "XNAS"


@pytest.mark.parametrize("field_name", ["instrument_id", "symbol", "venue"])
def test_daily_market_data_instrument_rejects_blank_fields(field_name: str) -> None:
    data = {
        "instrument_id": "instrument-us-etf-qqq-xnas",
        "symbol": "QQQ",
        "venue": "XNAS",
    }
    data[field_name] = " "

    with pytest.raises(ValidationError):
        DailyMarketDataInstrument(**data)


def test_canonical_daily_bar_accepts_decimal_ohlcv() -> None:
    bar = canonical_bar()

    assert bar.open == Decimal("100")
    assert bar.high == Decimal("101")
    assert bar.low == Decimal("99")
    assert bar.close == Decimal("100.5")
    assert bar.volume == 1000


def test_canonical_daily_bar_accepts_string_decimal_input() -> None:
    bar = CanonicalDailyBar(
        session_date=date(2026, 1, 2),
        open="100.000000",
        high="101.0",
        low="99",
        close="100.5000",
        volume=1000,
    )

    assert bar.open == Decimal("100.000000")
    assert bar.close == Decimal("100.5000")


def test_canonical_daily_bar_rejects_float_prices() -> None:
    with pytest.raises(ValidationError):
        CanonicalDailyBar(
            session_date=date(2026, 1, 2),
            open=100.0,
            high="101",
            low="99",
            close="100.5",
            volume=1000,
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("open", "0"),
        ("high", "-1"),
        ("low", "0"),
        ("close", "-1"),
    ],
)
def test_canonical_daily_bar_rejects_nonpositive_ohlc(
    field_name: str,
    value: str,
) -> None:
    data = canonical_bar_data()
    data[field_name] = value

    with pytest.raises(ValidationError, match="positive"):
        CanonicalDailyBar(**data)


def test_canonical_daily_bar_rejects_negative_volume() -> None:
    data = canonical_bar_data()
    data["volume"] = -1

    with pytest.raises(ValidationError):
        CanonicalDailyBar(**data)


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("high", "99.5", "high must be greater than or equal to open"),
        ("high", "100.25", "high must be greater than or equal to close"),
        ("low", "100.25", "low must be less than or equal to open"),
        ("low", "100.75", "low must be less than or equal to close"),
    ],
)
def test_canonical_daily_bar_rejects_ohlc_inconsistency(
    field_name: str,
    value: str,
    message: str,
) -> None:
    data = canonical_bar_data()
    data[field_name] = value
    if field_name == "low" and "close" in message:
        data["open"] = "101"

    with pytest.raises(ValidationError, match=message):
        CanonicalDailyBar(**data)


def test_canonical_daily_bar_rejects_high_less_than_low() -> None:
    data = canonical_bar_data()
    data["high"] = "98"
    data["low"] = "99"

    with pytest.raises(ValidationError, match="high must be greater"):
        CanonicalDailyBar(**data)


def test_daily_market_data_policy_accepts_etf_daily_v1_policy() -> None:
    policy = daily_policy()

    assert policy.asset_class is AssetClass.ETFS
    assert policy.frequency == "daily"
    assert policy.distribution_treatment is DistributionTreatment.EXPLICIT_CASH


def test_daily_market_data_policy_rejects_unsupported_asset_class() -> None:
    with pytest.raises(ValidationError, match="ETFs only"):
        daily_policy(asset_class=AssetClass.EQUITIES)


def test_daily_market_data_policy_rejects_non_daily_frequency() -> None:
    with pytest.raises(ValidationError, match="daily frequency"):
        daily_policy(frequency="hourly")


@pytest.mark.parametrize(
    "adjustment_policy",
    [DataAdjustmentPolicy.TOTAL_RETURN, DataAdjustmentPolicy.CONTINUOUS],
)
def test_daily_market_data_policy_rejects_total_return_execution_ohlc(
    adjustment_policy: DataAdjustmentPolicy,
) -> None:
    with pytest.raises(ValidationError, match="not tradable execution OHLC"):
        daily_policy(adjustment_policy=adjustment_policy)


def test_daily_market_data_policy_rejects_other_adjustment_policy() -> None:
    with pytest.raises(ValidationError, match="other adjustment policy"):
        daily_policy(adjustment_policy=DataAdjustmentPolicy.OTHER)


def test_daily_market_data_policy_requires_explicit_distribution_treatment() -> None:
    data = daily_policy().model_dump(mode="python")
    del data["distribution_treatment"]

    with pytest.raises(ValidationError):
        DailyMarketDataPolicy(**data)


def test_daily_market_data_quality_report_accepts_valid_pass() -> None:
    report = quality_report(status=DailyMarketDataQualityStatus.PASS)

    assert report.status is DailyMarketDataQualityStatus.PASS
    assert report.fatal_violations == ()


def test_daily_market_data_quality_report_accepts_valid_fail() -> None:
    report = quality_report(
        status=DailyMarketDataQualityStatus.FAIL,
        fatal_violations=(DailyMarketDataQualityCode.MISSING_SESSION,),
        missing_session_dates=(date(2026, 1, 5),),
        observed_session_count=1,
    )

    assert report.status is DailyMarketDataQualityStatus.FAIL


def test_daily_market_data_quality_report_rejects_pass_with_fatal_violation() -> None:
    with pytest.raises(ValidationError):
        quality_report(
            status=DailyMarketDataQualityStatus.PASS,
            fatal_violations=(DailyMarketDataQualityCode.MISSING_SESSION,),
        )


def test_daily_market_data_quality_report_rejects_fail_without_fatal() -> None:
    with pytest.raises(ValidationError):
        quality_report(status=DailyMarketDataQualityStatus.FAIL)


def test_daily_market_data_quality_report_rejects_malformed_content_hash() -> None:
    with pytest.raises(ValidationError, match="content_hash"):
        quality_report(content_hash="sha256:short")


@pytest.mark.parametrize(
    "field_name",
    [
        "missing_session_dates",
        "unexpected_session_dates",
        "duplicate_session_dates",
        "zero_volume_dates",
    ],
)
def test_daily_market_data_quality_report_rejects_duplicate_date_tuples(
    field_name: str,
) -> None:
    with pytest.raises(ValidationError, match="duplicates"):
        quality_report(**{field_name: (date(2026, 1, 5), date(2026, 1, 5))})


@pytest.mark.parametrize(
    "field_name",
    [
        "missing_session_dates",
        "unexpected_session_dates",
        "duplicate_session_dates",
        "zero_volume_dates",
    ],
)
def test_daily_market_data_quality_report_rejects_nonascending_date_tuples(
    field_name: str,
) -> None:
    with pytest.raises(ValidationError, match="strictly ascending"):
        quality_report(**{field_name: (date(2026, 1, 6), date(2026, 1, 5))})


@pytest.mark.parametrize("field_name", ["fatal_violations", "warnings"])
def test_daily_market_data_quality_report_rejects_duplicate_codes(
    field_name: str,
) -> None:
    with pytest.raises(ValidationError, match="duplicates"):
        quality_report(
            status=DailyMarketDataQualityStatus.FAIL
            if field_name == "fatal_violations"
            else DailyMarketDataQualityStatus.PASS,
            **{
                field_name: (
                    DailyMarketDataQualityCode.MISSING_SESSION,
                    DailyMarketDataQualityCode.MISSING_SESSION,
                )
            },
        )


@pytest.mark.parametrize("field_name", ["fatal_violations", "warnings"])
def test_daily_market_data_quality_report_rejects_noncanonical_code_order(
    field_name: str,
) -> None:
    with pytest.raises(ValidationError, match="canonical order"):
        quality_report(
            status=DailyMarketDataQualityStatus.FAIL
            if field_name == "fatal_violations"
            else DailyMarketDataQualityStatus.PASS,
            **{
                field_name: (
                    DailyMarketDataQualityCode.ZERO_VOLUME,
                    DailyMarketDataQualityCode.MISSING_SESSION,
                )
            },
        )


def test_daily_market_data_quality_report_rejects_missing_fact_without_code() -> None:
    with pytest.raises(ValidationError, match="fatal_violations"):
        quality_report(
            missing_session_dates=(date(2026, 1, 5),),
            observed_session_count=1,
        )


def test_daily_market_data_quality_report_rejects_missing_code_without_fact() -> None:
    with pytest.raises(ValidationError, match="fatal_violations"):
        quality_report(
            status=DailyMarketDataQualityStatus.FAIL,
            fatal_violations=(DailyMarketDataQualityCode.MISSING_SESSION,),
        )


def test_daily_market_data_quality_report_rejects_duplicate_fact_without_code() -> None:
    with pytest.raises(ValidationError, match="fatal_violations"):
        quality_report(
            duplicate_session_dates=(date(2026, 1, 2),),
            observed_session_count=3,
            duplicate_row_count=1,
        )


def test_daily_market_data_quality_report_rejects_unexpected_fact_without_code() -> (
    None
):
    with pytest.raises(ValidationError, match="fatal_violations"):
        quality_report(
            unexpected_session_dates=(date(2026, 1, 6),),
            observed_session_count=3,
        )


def test_daily_market_data_quality_report_rejects_zero_volume_fact_without_code() -> (
    None
):
    with pytest.raises(ValidationError, match="fatal_violations"):
        quality_report(zero_volume_dates=(date(2026, 1, 2),))


@pytest.mark.parametrize(
    "fatal_violations",
    [
        (DailyMarketDataQualityCode.DUPLICATE_SESSION,),
        (DailyMarketDataQualityCode.UNEXPECTED_SESSION,),
        (DailyMarketDataQualityCode.ZERO_VOLUME,),
    ],
)
def test_daily_market_data_quality_report_rejects_fatal_code_without_fact(
    fatal_violations: tuple[DailyMarketDataQualityCode, ...],
) -> None:
    with pytest.raises(ValidationError, match="fatal_violations"):
        quality_report(
            status=DailyMarketDataQualityStatus.FAIL,
            fatal_violations=fatal_violations,
        )


def test_daily_market_data_quality_report_rejects_warning_observations() -> None:
    with pytest.raises(ValidationError, match="warning"):
        quality_report(warnings=(DailyMarketDataQualityCode.ZERO_VOLUME,))


def test_daily_market_data_quality_report_rejects_pass_with_implied_fatal_fact() -> (
    None
):
    with pytest.raises(ValidationError, match="status"):
        quality_report(
            status=DailyMarketDataQualityStatus.PASS,
            fatal_violations=(DailyMarketDataQualityCode.ZERO_VOLUME,),
            zero_volume_dates=(date(2026, 1, 2),),
        )


def test_daily_market_data_quality_report_rejects_fail_without_implied_fatal_fact() -> (
    None
):
    with pytest.raises(ValidationError, match="status"):
        quality_report(status=DailyMarketDataQualityStatus.FAIL)


def test_daily_market_data_quality_report_rejects_wrong_expected_session_count() -> (
    None
):
    with pytest.raises(ValidationError):
        quality_report(expected_session_count=0)


def test_daily_market_data_quality_report_rejects_wrong_observed_session_count() -> (
    None
):
    with pytest.raises(ValidationError, match="observed_session_count"):
        quality_report(observed_session_count=1)


def test_daily_market_data_quality_report_rejects_wrong_duplicate_row_count() -> None:
    with pytest.raises(ValidationError, match="observed_session_count"):
        quality_report(
            status=DailyMarketDataQualityStatus.FAIL,
            fatal_violations=(DailyMarketDataQualityCode.DUPLICATE_SESSION,),
            duplicate_session_dates=(date(2026, 1, 2),),
            duplicate_row_count=0,
            observed_session_count=3,
        )


def test_daily_market_data_quality_report_rejects_invalid_expected_date_order() -> None:
    with pytest.raises(ValidationError, match="expected_end_date"):
        quality_report(
            expected_start_date=date(2026, 1, 5),
            expected_end_date=date(2026, 1, 2),
        )


def canonical_bar() -> CanonicalDailyBar:
    return CanonicalDailyBar(**canonical_bar_data())


def canonical_bar_data() -> dict[str, object]:
    return {
        "session_date": date(2026, 1, 2),
        "open": Decimal("100"),
        "high": Decimal("101"),
        "low": Decimal("99"),
        "close": Decimal("100.5"),
        "volume": 1000,
    }


def daily_policy(**overrides: object) -> DailyMarketDataPolicy:
    data = {
        "schema_version": "1.0.0",
        "policy_id": "daily-market-data-etf-execution-v1",
        "asset_class": AssetClass.ETFS,
        "frequency": "daily",
        "calendar": "XNYS",
        "timezone": "America/New_York",
        "adjustment_policy": DataAdjustmentPolicy.RAW,
        "distribution_treatment": DistributionTreatment.EXPLICIT_CASH,
        "corporate_action_policy": "raw OHLCV plus explicit corporate-action evidence",
        "universe_membership_policy": "static explicit instrument universe",
        "survivorship_policy": "static named instrument; no survivorship-free claim",
        "delisting_policy": "unsupported for ETF S3a; fail closed if encountered",
        "canonicalization_version": "daily-market-data-canonical-v1",
        "quality_policy_version": "daily-market-data-quality-v1",
    }
    data.update(overrides)
    return DailyMarketDataPolicy(**data)


def quality_report(**overrides: object) -> DailyMarketDataQualityReport:
    data = {
        "schema_version": "1.0.0",
        "policy_id": "daily-market-data-etf-execution-v1",
        "quality_policy_version": "daily-market-data-quality-v1",
        "canonicalization_version": "daily-market-data-canonical-v1",
        "instrument": {
            "instrument_id": "instrument-us-etf-qqq-xnas",
            "symbol": "QQQ",
            "venue": "XNAS",
        },
        "content_hash": f"sha256:{'1' * 64}",
        "expected_start_date": date(2026, 1, 2),
        "expected_end_date": date(2026, 1, 5),
        "expected_session_count": 2,
        "observed_session_count": 2,
        "duplicate_row_count": 0,
        "missing_session_dates": (),
        "unexpected_session_dates": (),
        "duplicate_session_dates": (),
        "zero_volume_dates": (),
        "fatal_violations": (),
        "warnings": (),
        "status": DailyMarketDataQualityStatus.PASS,
    }
    data.update(overrides)
    return DailyMarketDataQualityReport(**data)
