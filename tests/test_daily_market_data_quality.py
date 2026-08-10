from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from research_sdk.contracts import (
    AssetClass,
    AssetUniverseReference,
    DataAdjustmentPolicy,
    DataSnapshotKind,
    DataSnapshotManifest,
    DataSnapshotStatus,
    DataSourceType,
    HashAlgorithm,
    TemporalCoverage,
    TimeRange,
)
from research_sdk.contracts.daily_market_data import (
    CanonicalDailyBar,
    DailyMarketDataInstrument,
    DailyMarketDataPolicy,
    DailyMarketDataQualityCode,
    DailyMarketDataQualityReport,
    DailyMarketDataQualityStatus,
    DistributionTreatment,
)
from research_sdk.daily_market_data import (
    DailyMarketDataManifestCompatibilityError,
    DailyMarketDataQualityInputError,
    derive_daily_market_data_content_hash,
    evaluate_daily_market_data_quality,
    validate_daily_market_data_snapshot_manifest,
)


def test_perfect_expected_coverage_passes_quality() -> None:
    report = evaluate_quality()

    assert report.status is DailyMarketDataQualityStatus.PASS
    assert report.fatal_violations == ()
    assert report.expected_start_date == date(2026, 1, 2)
    assert report.expected_end_date == date(2026, 1, 5)
    assert report.expected_session_count == 2
    assert report.observed_session_count == 2
    assert report.duplicate_row_count == 0


def test_quality_evaluation_is_bar_order_independent() -> None:
    assert evaluate_quality(bars=tuple(reversed(sample_bars()))) == evaluate_quality()


def test_quality_evaluation_is_expected_session_order_independent() -> None:
    assert (
        evaluate_quality(expected_session_dates=(date(2026, 1, 5), date(2026, 1, 2)))
        == evaluate_quality()
    )


def test_missing_session_fails_quality() -> None:
    report = evaluate_quality(bars=(sample_bars()[0],))

    assert report.status is DailyMarketDataQualityStatus.FAIL
    assert report.missing_session_dates == (date(2026, 1, 5),)
    assert report.fatal_violations == (DailyMarketDataQualityCode.MISSING_SESSION,)


def test_unexpected_session_fails_quality() -> None:
    unexpected_bar = sample_bars()[0].model_copy(
        update={"session_date": date(2026, 1, 6)}
    )
    report = evaluate_quality(bars=sample_bars() + (unexpected_bar,))

    assert report.status is DailyMarketDataQualityStatus.FAIL
    assert report.unexpected_session_dates == (date(2026, 1, 6),)
    assert DailyMarketDataQualityCode.UNEXPECTED_SESSION in report.fatal_violations


def test_duplicate_session_fails_quality() -> None:
    duplicate_bar = sample_bars()[0].model_copy(update={"close": Decimal("100.6")})
    report = evaluate_quality(bars=sample_bars() + (duplicate_bar,))

    assert report.status is DailyMarketDataQualityStatus.FAIL
    assert report.duplicate_session_dates == (date(2026, 1, 2),)
    assert report.duplicate_row_count == 1
    assert report.observed_session_count == 3
    assert DailyMarketDataQualityCode.DUPLICATE_SESSION in report.fatal_violations


def test_zero_volume_fails_quality_under_etf_v1() -> None:
    zero_volume_bar = sample_bars()[0].model_copy(update={"volume": 0})
    report = evaluate_quality(bars=(zero_volume_bar, sample_bars()[1]))

    assert report.status is DailyMarketDataQualityStatus.FAIL
    assert report.zero_volume_dates == (date(2026, 1, 2),)
    assert DailyMarketDataQualityCode.ZERO_VOLUME in report.fatal_violations


def test_multiple_fatal_codes_have_canonical_order() -> None:
    duplicate_zero = sample_bars()[0].model_copy(update={"volume": 0})
    report = evaluate_quality(
        bars=(duplicate_zero, sample_bars()[0]),
        expected_session_dates=(date(2026, 1, 2), date(2026, 1, 5)),
    )

    assert report.fatal_violations == (
        DailyMarketDataQualityCode.DUPLICATE_SESSION,
        DailyMarketDataQualityCode.MISSING_SESSION,
        DailyMarketDataQualityCode.ZERO_VOLUME,
    )


def test_duplicate_session_triplicate_counts_extra_rows() -> None:
    first_duplicate = sample_bars()[0].model_copy(update={"close": Decimal("100.6")})
    second_duplicate = sample_bars()[0].model_copy(update={"close": Decimal("100.7")})
    report = evaluate_quality(bars=sample_bars() + (first_duplicate, second_duplicate))

    assert report.duplicate_session_dates == (date(2026, 1, 2),)
    assert report.duplicate_row_count == 2
    assert report.observed_session_count == 4


def test_duplicate_sessions_on_two_dates_count_all_extra_rows() -> None:
    first_duplicate = sample_bars()[0].model_copy(update={"close": Decimal("100.6")})
    second_duplicate = sample_bars()[1].model_copy(update={"close": Decimal("101.6")})
    report = evaluate_quality(bars=sample_bars() + (first_duplicate, second_duplicate))

    assert report.duplicate_session_dates == (date(2026, 1, 2), date(2026, 1, 5))
    assert report.duplicate_row_count == 2
    assert report.observed_session_count == 4


def test_duplicate_rows_remain_part_of_failed_quality_content_hash() -> None:
    duplicate_bar = sample_bars()[0].model_copy(update={"close": Decimal("100.6")})
    bars = sample_bars() + (duplicate_bar,)
    report = evaluate_quality(bars=bars)

    assert report.status is DailyMarketDataQualityStatus.FAIL
    assert report.content_hash == derive_daily_market_data_content_hash(
        instrument=sample_instrument(),
        bars=bars,
        canonicalization_version=sample_policy().canonicalization_version,
    )
    assert report.content_hash != evaluate_quality().content_hash


def test_quality_content_hash_matches_direct_canonical_helper() -> None:
    report = evaluate_quality()

    assert report.content_hash == derive_daily_market_data_content_hash(
        instrument=sample_instrument(),
        bars=sample_bars(),
        canonicalization_version=sample_policy().canonicalization_version,
    )


def test_quality_evaluation_does_not_mutate_caller_input() -> None:
    bars = sample_bars()
    expected_sessions = (date(2026, 1, 5), date(2026, 1, 2))
    before_bars = deepcopy(bars)
    before_sessions = tuple(expected_sessions)

    evaluate_quality(bars=bars, expected_session_dates=expected_sessions)

    assert bars == before_bars
    assert expected_sessions == before_sessions


def test_quality_evaluation_has_no_current_time_dependency() -> None:
    assert evaluate_quality() == evaluate_quality()


def test_quality_revalidates_copied_invalid_instrument() -> None:
    invalid = sample_instrument().model_copy(update={"venue": " "})

    with pytest.raises(ValidationError):
        evaluate_daily_market_data_quality(
            instrument=invalid,
            bars=sample_bars(),
            expected_session_dates=(date(2026, 1, 2), date(2026, 1, 5)),
            policy=sample_policy(),
        )


def test_quality_revalidates_copied_invalid_bar_volume() -> None:
    invalid = sample_bars()[0].model_copy(update={"volume": -1})

    with pytest.raises(ValidationError):
        evaluate_quality(bars=(invalid, sample_bars()[1]))


def test_quality_revalidates_copied_invalid_bar_ohlc() -> None:
    invalid = sample_bars()[0].model_copy(update={"open": Decimal("0")})

    with pytest.raises(ValidationError):
        evaluate_quality(bars=(invalid, sample_bars()[1]))


def test_quality_revalidates_copied_invalid_policy() -> None:
    invalid = sample_policy().model_copy(update={"asset_class": AssetClass.EQUITIES})

    with pytest.raises(ValidationError):
        evaluate_daily_market_data_quality(
            instrument=sample_instrument(),
            bars=sample_bars(),
            expected_session_dates=(date(2026, 1, 2), date(2026, 1, 5)),
            policy=invalid,
        )


def test_quality_accepts_unsorted_expected_sessions() -> None:
    report = evaluate_quality(
        expected_session_dates=(date(2026, 1, 5), date(2026, 1, 2))
    )

    assert report.expected_start_date == date(2026, 1, 2)
    assert report.expected_end_date == date(2026, 1, 5)
    assert report.status is DailyMarketDataQualityStatus.PASS


def test_quality_rejects_duplicate_expected_session_dates() -> None:
    with pytest.raises(DailyMarketDataQualityInputError, match="duplicates"):
        evaluate_quality(expected_session_dates=(date(2026, 1, 2), date(2026, 1, 2)))


def test_quality_rejects_empty_expected_sessions() -> None:
    with pytest.raises(DailyMarketDataQualityInputError, match="at least one"):
        evaluate_quality(expected_session_dates=())


@pytest.mark.parametrize(
    "expected_session_dates",
    [
        (datetime(2026, 1, 2, tzinfo=UTC),),
        (True,),
        (object(),),
    ],
)
def test_quality_rejects_malformed_expected_sessions(
    expected_session_dates: tuple[object, ...],
) -> None:
    with pytest.raises(DailyMarketDataQualityInputError, match="date values"):
        evaluate_daily_market_data_quality(
            instrument=sample_instrument(),
            bars=sample_bars(),
            expected_session_dates=expected_session_dates,  # type: ignore[arg-type]
            policy=sample_policy(),
        )


@pytest.mark.parametrize(
    ("update", "message"),
    [
        ({"snapshot_kind": DataSnapshotKind.BENCHMARK_DATA}, "snapshot_kind"),
        ({"status": DataSnapshotStatus.CREATED}, "status"),
        ({"asset_class": AssetClass.EQUITIES}, "asset_class"),
        ({"frequency": "1d"}, "frequency"),
        ({"calendar": "XNAS"}, "calendar"),
        ({"timezone": "UTC"}, "timezone"),
        ({"adjustment_policy": DataAdjustmentPolicy.SPLIT_ADJUSTED}, "adjustment"),
        ({"universe_membership_policy": "other membership"}, "universe"),
        ({"corporate_action_policy": "other corporate actions"}, "corporate"),
        ({"survivorship_policy": "other survivorship"}, "survivorship"),
        ({"delisting_policy": "other delisting"}, "delisting"),
        ({"content_hash": f"sha256:{'2' * 64}"}, "content_hash"),
        ({"row_count": 1}, "row_count"),
    ],
)
def test_manifest_compatibility_rejects_incoherent_manifest_fields(
    update: dict[str, object],
    message: str,
) -> None:
    manifest = coherent_manifest().model_copy(update=update)

    with pytest.raises(DailyMarketDataManifestCompatibilityError, match=message):
        validate_daily_market_data_snapshot_manifest(
            manifest=manifest,
            policy=sample_policy(),
            quality_report=evaluate_quality(),
        )


def test_manifest_compatibility_rejects_wrong_policy_id_linkage() -> None:
    report = evaluate_quality().model_copy(update={"policy_id": "other-policy"})

    with pytest.raises(DailyMarketDataManifestCompatibilityError, match="policy_id"):
        validate_daily_market_data_snapshot_manifest(
            manifest=coherent_manifest(),
            policy=sample_policy(),
            quality_report=report,
        )


def test_manifest_compatibility_revalidates_copied_invalid_manifest_contract() -> None:
    manifest = coherent_manifest().model_copy(
        update={"source_type": DataSourceType.VENDOR, "vendor_name": None}
    )

    with pytest.raises(ValidationError):
        validate_daily_market_data_snapshot_manifest(
            manifest=manifest,
            policy=sample_policy(),
            quality_report=evaluate_quality(),
        )


def test_manifest_compatibility_revalidates_copied_invalid_quality_report() -> None:
    report = evaluate_quality().model_copy(update={"observed_session_count": -1})

    with pytest.raises(ValidationError):
        validate_daily_market_data_snapshot_manifest(
            manifest=coherent_manifest(),
            policy=sample_policy(),
            quality_report=report,
        )


def test_manifest_compatibility_revalidates_copied_invalid_policy() -> None:
    policy = sample_policy().model_copy(
        update={"adjustment_policy": DataAdjustmentPolicy.TOTAL_RETURN}
    )

    with pytest.raises(ValidationError):
        validate_daily_market_data_snapshot_manifest(
            manifest=coherent_manifest(),
            policy=policy,
            quality_report=evaluate_quality(),
        )


def test_manifest_compatibility_rejects_fail_quality_report() -> None:
    report = evaluate_quality(bars=(sample_bars()[0],))

    with pytest.raises(DailyMarketDataManifestCompatibilityError, match="status"):
        validate_daily_market_data_snapshot_manifest(
            manifest=coherent_manifest(
                content_hash=report.content_hash,
                row_count=report.observed_session_count,
            ),
            policy=sample_policy(),
            quality_report=report,
        )


def test_manifest_compatibility_rejects_wrong_manifest_start_date() -> None:
    manifest = coherent_manifest(
        time_range=TimeRange(start_date=date(2026, 1, 1), end_date=date(2026, 1, 5))
    )

    with pytest.raises(DailyMarketDataManifestCompatibilityError, match="start"):
        validate_daily_market_data_snapshot_manifest(
            manifest=manifest,
            policy=sample_policy(),
            quality_report=evaluate_quality(),
        )


def test_manifest_compatibility_rejects_wrong_manifest_end_date() -> None:
    manifest = coherent_manifest(
        time_range=TimeRange(start_date=date(2026, 1, 2), end_date=date(2026, 1, 3))
    )

    with pytest.raises(DailyMarketDataManifestCompatibilityError, match="end"):
        validate_daily_market_data_snapshot_manifest(
            manifest=manifest,
            policy=sample_policy(),
            quality_report=evaluate_quality(),
        )


def test_manifest_compatibility_rejects_missing_asset_universe_symbols() -> None:
    manifest = coherent_manifest(
        asset_universe=AssetUniverseReference(
            universe_id="static-us-etf-qqq-v1",
            symbols=None,
        )
    )

    with pytest.raises(DailyMarketDataManifestCompatibilityError, match="symbols"):
        validate_daily_market_data_snapshot_manifest(
            manifest=manifest,
            policy=sample_policy(),
            quality_report=evaluate_quality(),
        )


def test_manifest_compatibility_rejects_extra_asset_universe_symbol() -> None:
    manifest = coherent_manifest(
        asset_universe=AssetUniverseReference(symbols=("QQQ", "SPY"))
    )

    with pytest.raises(DailyMarketDataManifestCompatibilityError, match="symbols"):
        validate_daily_market_data_snapshot_manifest(
            manifest=manifest,
            policy=sample_policy(),
            quality_report=evaluate_quality(),
        )


def test_manifest_compatibility_rejects_wrong_asset_universe_symbol() -> None:
    manifest = coherent_manifest(
        asset_universe=AssetUniverseReference(symbols=("SPY",))
    )

    with pytest.raises(DailyMarketDataManifestCompatibilityError, match="symbols"):
        validate_daily_market_data_snapshot_manifest(
            manifest=manifest,
            policy=sample_policy(),
            quality_report=evaluate_quality(),
        )


def test_manifest_compatibility_accepts_fully_coherent_manifest() -> None:
    validate_daily_market_data_snapshot_manifest(
        manifest=coherent_manifest(),
        policy=sample_policy(),
        quality_report=evaluate_quality(),
    )


def test_daily_market_data_import_does_not_load_operational_dependencies() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [
                str(repo_root / "packages" / "research-sdk" / "src"),
                str(repo_root / "packages" / "backtest-engine" / "src"),
            ]
        ),
    }
    command = [
        sys.executable,
        "-c",
        (
            "import json, sys; import research_sdk.daily_market_data; "
            "print(json.dumps(sorted(sys.modules)))"
        ),
    ]
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    imported_modules = set(json.loads(result.stdout))

    assert {
        "sqlalchemy",
        "psycopg",
        "research_sdk.persistence",
        "backtest_engine",
        "boto3",
        "requests",
        "httpx",
    }.isdisjoint(imported_modules)


def evaluate_quality(
    *,
    bars: tuple[CanonicalDailyBar, ...] | None = None,
    expected_session_dates: tuple[date, ...] | None = None,
) -> DailyMarketDataQualityReport:
    return evaluate_daily_market_data_quality(
        instrument=sample_instrument(),
        bars=sample_bars() if bars is None else bars,
        expected_session_dates=expected_session_dates
        if expected_session_dates is not None
        else (date(2026, 1, 2), date(2026, 1, 5)),
        policy=sample_policy(),
    )


def coherent_manifest(**overrides: object) -> DataSnapshotManifest:
    report = evaluate_quality()
    policy = sample_policy()
    data = {
        "schema_version": "1.0.0",
        "snapshot_id": "market-snapshot-qqq-20260105",
        "snapshot_kind": DataSnapshotKind.MARKET_DATA,
        "status": DataSnapshotStatus.COMPLETED,
        "created_at": datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
        "created_by": "agent-codex",
        "asset_class": policy.asset_class,
        "asset_universe": AssetUniverseReference(
            universe_id="static-us-etf-qqq-v1",
            symbols=("QQQ",),
            as_of=datetime(2026, 1, 5, 0, 0, tzinfo=UTC),
        ),
        "time_range": TimeRange(
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 5),
        ),
        "frequency": policy.frequency,
        "data_root_uri": "file:///tmp/curated/market-snapshot-qqq-20260105",
        "source_dataset": "curated-daily-market-data",
        "source_version": "2026-01-06",
        "source_type": DataSourceType.INTERNAL,
        "temporal_coverage": TemporalCoverage.POINT_IN_TIME,
        "as_of": datetime(2026, 1, 5, 0, 0, tzinfo=UTC),
        "available_at": datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
        "ingestion_completed_at": datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
        "adjustment_policy": policy.adjustment_policy,
        "calendar": policy.calendar,
        "timezone": policy.timezone,
        "universe_membership_policy": policy.universe_membership_policy,
        "corporate_action_policy": policy.corporate_action_policy,
        "survivorship_policy": policy.survivorship_policy,
        "delisting_policy": policy.delisting_policy,
        "hash_algorithm": HashAlgorithm.SHA256,
        "content_hash": report.content_hash,
        "row_count": report.observed_session_count,
        "known_limitations": ("provider provenance deferred to S3b",),
    }
    data.update(overrides)
    return DataSnapshotManifest(**data)


def sample_policy() -> DailyMarketDataPolicy:
    return DailyMarketDataPolicy(
        schema_version="1.0.0",
        policy_id="daily-market-data-etf-execution-v1",
        asset_class=AssetClass.ETFS,
        frequency="daily",
        calendar="XNYS",
        timezone="America/New_York",
        adjustment_policy=DataAdjustmentPolicy.RAW,
        distribution_treatment=DistributionTreatment.EXPLICIT_CASH,
        corporate_action_policy="raw OHLCV plus explicit corporate-action evidence",
        universe_membership_policy="static explicit instrument universe",
        survivorship_policy="static named instrument; no survivorship-free claim",
        delisting_policy="unsupported for ETF S3a; fail closed if encountered",
        canonicalization_version="daily-market-data-canonical-v1",
        quality_policy_version="daily-market-data-quality-v1",
    )


def sample_instrument() -> DailyMarketDataInstrument:
    return DailyMarketDataInstrument(
        instrument_id="instrument-us-etf-qqq-xnas",
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
