"""Deterministic daily market-data quality and manifest compatibility checks."""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import NoReturn

from research_sdk.contracts import (
    DataSnapshotKind,
    DataSnapshotManifest,
    DataSnapshotStatus,
)
from research_sdk.contracts.daily_market_data import (
    CanonicalDailyBar,
    DailyMarketDataInstrument,
    DailyMarketDataPolicy,
    DailyMarketDataQualityCode,
    DailyMarketDataQualityReport,
    DailyMarketDataQualityStatus,
)
from research_sdk.contracts.schema import RESEARCH_SDK_CONTRACT_SCHEMA_VERSION
from research_sdk.daily_market_data.canonicalization import (
    derive_daily_market_data_content_hash,
)


class DailyMarketDataManifestCompatibilityError(ValueError):
    """Raised when a manifest does not match daily market-data quality evidence."""


class DailyMarketDataQualityInputError(ValueError):
    """Raised when caller-provided quality inputs are not canonical contracts."""


def evaluate_daily_market_data_quality(
    *,
    instrument: DailyMarketDataInstrument,
    bars: tuple[CanonicalDailyBar, ...],
    expected_session_dates: tuple[date, ...],
    policy: DailyMarketDataPolicy,
) -> DailyMarketDataQualityReport:
    """Evaluate deterministic dataset-level quality without I/O or clocks."""

    validated_instrument = _revalidate_instrument(instrument)
    validated_policy = _revalidate_policy(policy)
    validated_bars = tuple(_revalidate_bar(bar) for bar in bars)
    expected_dates = _canonical_expected_session_dates(expected_session_dates)
    expected_date_set = set(expected_dates)
    observed_dates = [bar.session_date for bar in validated_bars]
    observed_date_set = set(observed_dates)
    observed_date_counts = Counter(observed_dates)
    duplicate_dates = tuple(
        sorted(
            session_date
            for session_date, count in observed_date_counts.items()
            if count > 1
        )
    )
    duplicate_row_count = sum(
        count - 1 for count in observed_date_counts.values() if count > 1
    )
    missing_dates = tuple(sorted(expected_date_set - observed_date_set))
    unexpected_dates = tuple(sorted(observed_date_set - expected_date_set))
    zero_volume_dates = tuple(
        sorted({bar.session_date for bar in validated_bars if bar.volume == 0})
    )

    fatal_codes: list[DailyMarketDataQualityCode] = []
    if duplicate_dates:
        fatal_codes.append(DailyMarketDataQualityCode.DUPLICATE_SESSION)
    if missing_dates:
        fatal_codes.append(DailyMarketDataQualityCode.MISSING_SESSION)
    if unexpected_dates:
        fatal_codes.append(DailyMarketDataQualityCode.UNEXPECTED_SESSION)
    if zero_volume_dates:
        fatal_codes.append(DailyMarketDataQualityCode.ZERO_VOLUME)

    fatal_violations = tuple(fatal_codes)
    status = (
        DailyMarketDataQualityStatus.FAIL
        if fatal_violations
        else DailyMarketDataQualityStatus.PASS
    )

    return DailyMarketDataQualityReport(
        schema_version=RESEARCH_SDK_CONTRACT_SCHEMA_VERSION,
        policy_id=validated_policy.policy_id,
        quality_policy_version=validated_policy.quality_policy_version,
        canonicalization_version=validated_policy.canonicalization_version,
        instrument=validated_instrument,
        content_hash=derive_daily_market_data_content_hash(
            instrument=validated_instrument,
            bars=validated_bars,
            canonicalization_version=validated_policy.canonicalization_version,
        ),
        expected_start_date=expected_dates[0],
        expected_end_date=expected_dates[-1],
        expected_session_count=len(expected_dates),
        observed_session_count=len(validated_bars),
        duplicate_row_count=duplicate_row_count,
        missing_session_dates=missing_dates,
        unexpected_session_dates=unexpected_dates,
        duplicate_session_dates=duplicate_dates,
        zero_volume_dates=zero_volume_dates,
        fatal_violations=fatal_violations,
        warnings=(),
        status=status,
    )


def validate_daily_market_data_snapshot_manifest(
    *,
    manifest: DataSnapshotManifest,
    policy: DailyMarketDataPolicy,
    quality_report: DailyMarketDataQualityReport,
) -> None:
    """Validate manifest/policy/quality coherence without storage inspection."""

    validated_manifest = _revalidate_manifest(manifest)
    validated_policy = _revalidate_policy(policy)
    validated_quality_report = _revalidate_quality_report(quality_report)

    _require(
        validated_manifest.snapshot_kind is DataSnapshotKind.MARKET_DATA,
        "manifest snapshot_kind must be market_data",
    )
    _require(
        validated_manifest.status is DataSnapshotStatus.COMPLETED,
        "manifest status must be completed",
    )
    _require(
        validated_manifest.asset_class is validated_policy.asset_class,
        "manifest asset_class must match policy",
    )
    _require(
        validated_manifest.frequency == validated_policy.frequency,
        "manifest frequency must match policy",
    )
    _require(
        validated_manifest.calendar == validated_policy.calendar,
        "manifest calendar must match policy",
    )
    _require(
        validated_manifest.timezone == validated_policy.timezone,
        "manifest timezone must match policy",
    )
    _require(
        validated_manifest.adjustment_policy is validated_policy.adjustment_policy,
        "manifest adjustment_policy must match policy",
    )
    _require(
        validated_manifest.universe_membership_policy
        == validated_policy.universe_membership_policy,
        "manifest universe_membership_policy must match policy",
    )
    _require(
        validated_manifest.corporate_action_policy
        == validated_policy.corporate_action_policy,
        "manifest corporate_action_policy must match policy",
    )
    _require(
        validated_manifest.survivorship_policy == validated_policy.survivorship_policy,
        "manifest survivorship_policy must match policy",
    )
    _require(
        validated_manifest.delisting_policy == validated_policy.delisting_policy,
        "manifest delisting_policy must match policy",
    )
    _require(
        validated_manifest.content_hash == validated_quality_report.content_hash,
        "manifest content_hash must match quality report",
    )
    _require(
        validated_manifest.row_count == validated_quality_report.observed_session_count,
        "manifest row_count must match observed sessions",
    )
    _require(
        validated_manifest.time_range.start_date
        == validated_quality_report.expected_start_date,
        "manifest time_range.start_date must match quality coverage start",
    )
    _require(
        validated_manifest.time_range.end_date
        == validated_quality_report.expected_end_date,
        "manifest time_range.end_date must match quality coverage end",
    )
    _require(
        validated_quality_report.policy_id == validated_policy.policy_id,
        "quality report policy_id must match policy",
    )
    _require(
        validated_quality_report.quality_policy_version
        == validated_policy.quality_policy_version,
        "quality report quality_policy_version must match policy",
    )
    _require(
        validated_quality_report.canonicalization_version
        == validated_policy.canonicalization_version,
        "quality report canonicalization_version must match policy",
    )
    _require(
        validated_quality_report.status is DailyMarketDataQualityStatus.PASS,
        "quality report status must be pass",
    )

    _require(
        validated_manifest.asset_universe.symbols
        == (validated_quality_report.instrument.symbol,),
        "manifest asset_universe symbols must exactly match quality report symbol",
    )


def _revalidate_instrument(
    instrument: DailyMarketDataInstrument,
) -> DailyMarketDataInstrument:
    return DailyMarketDataInstrument.model_validate(instrument.model_dump(mode="json"))


def _revalidate_bar(bar: CanonicalDailyBar) -> CanonicalDailyBar:
    return CanonicalDailyBar.model_validate(bar.model_dump(mode="json"))


def _revalidate_policy(policy: DailyMarketDataPolicy) -> DailyMarketDataPolicy:
    return DailyMarketDataPolicy.model_validate(policy.model_dump(mode="json"))


def _revalidate_quality_report(
    quality_report: DailyMarketDataQualityReport,
) -> DailyMarketDataQualityReport:
    return DailyMarketDataQualityReport.model_validate(
        quality_report.model_dump(mode="json")
    )


def _revalidate_manifest(manifest: DataSnapshotManifest) -> DataSnapshotManifest:
    return DataSnapshotManifest.model_validate(manifest.model_dump(mode="json"))


def _canonical_expected_session_dates(
    expected_session_dates: tuple[date, ...],
) -> tuple[date, ...]:
    if not expected_session_dates:
        raise DailyMarketDataQualityInputError(
            "expected_session_dates must contain at least one date"
        )
    for session_date in expected_session_dates:
        if type(session_date) is not date:
            raise DailyMarketDataQualityInputError(
                "expected_session_dates must contain date values only"
            )
    if len(set(expected_session_dates)) != len(expected_session_dates):
        raise DailyMarketDataQualityInputError(
            "expected_session_dates must not contain duplicates"
        )
    return tuple(sorted(expected_session_dates))


def _require(condition: bool, message: str) -> None:
    if not condition:
        _compatibility_error(message)


def _compatibility_error(message: str) -> NoReturn:
    raise DailyMarketDataManifestCompatibilityError(message)


__all__ = [
    "DailyMarketDataManifestCompatibilityError",
    "DailyMarketDataQualityInputError",
    "evaluate_daily_market_data_quality",
    "validate_daily_market_data_snapshot_manifest",
]
