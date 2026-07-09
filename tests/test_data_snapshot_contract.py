from copy import deepcopy
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from research_sdk.contracts import (
    DataAdjustmentPolicy,
    DataSnapshotKind,
    DataSnapshotManifest,
    DataSnapshotStatus,
    DataSourceType,
    TemporalCoverage,
)


def valid_snapshot_data() -> dict[str, Any]:
    return {
        "snapshot_id": "market-snapshot-20260709",
        "schema_version": "1.0.0",
        "snapshot_kind": "market_data",
        "status": "completed",
        "created_at": datetime(2026, 7, 9, 9, 0, 0, tzinfo=UTC),
        "created_by": "agent-codex",
        "asset_class": "equities",
        "asset_universe": {
            "universe_id": "sp500-point-in-time",
            "symbols": ("AAPL", "MSFT"),
            "as_of": datetime(2026, 7, 9, 8, 25, 0, tzinfo=UTC),
        },
        "time_range": {
            "start_date": date(2020, 1, 1),
            "end_date": date(2026, 7, 8),
        },
        "frequency": "1d",
        "data_root_uri": "data/snapshots/market-snapshot-20260709",
        "source_dataset": "example-equities-daily-bars",
        "source_version": "2026-07-09",
        "source_type": "vendor",
        "vendor_name": "example-vendor",
        "license_notes": "research-only fixture metadata",
        "temporal_coverage": "point_in_time",
        "as_of": datetime(2026, 7, 9, 8, 30, 0, tzinfo=UTC),
        "source_observed_at": datetime(2026, 7, 9, 8, 40, 0, tzinfo=UTC),
        "ingestion_completed_at": datetime(2026, 7, 9, 8, 50, 0, tzinfo=UTC),
        "available_at": datetime(2026, 7, 9, 8, 55, 0, tzinfo=UTC),
        "adjustment_policy": "split_adjusted",
        "calendar": "XNYS",
        "timezone": "America/New_York",
        "currency": "USD",
        "universe_membership_policy": "point-in-time membership",
        "corporate_action_policy": "split adjusted, dividends unadjusted",
        "survivorship_policy": "includes delisted names when available",
        "delisting_policy": "terminal delisting prices retained when available",
        "rollover_policy": "not applicable",
        "hash_algorithm": "sha256",
        "content_hash": "declared-content-hash-only",
        "row_count": 100,
        "file_count": 2,
        "size_bytes": 4096,
        "known_limitations": ("none known",),
    }


def test_data_snapshot_manifest_accepts_complete_valid_manifest() -> None:
    manifest = DataSnapshotManifest(**valid_snapshot_data())

    assert manifest.snapshot_id == "market-snapshot-20260709"
    assert manifest.snapshot_kind is DataSnapshotKind.MARKET_DATA
    assert manifest.status is DataSnapshotStatus.COMPLETED
    assert manifest.source_type is DataSourceType.VENDOR
    assert manifest.adjustment_policy is DataAdjustmentPolicy.SPLIT_ADJUSTED
    assert manifest.temporal_coverage is TemporalCoverage.POINT_IN_TIME
    assert manifest.known_limitations == ("none known",)


def test_data_snapshot_kind_contains_documented_values() -> None:
    assert {kind.value for kind in DataSnapshotKind} == {
        "market_data",
        "fundamental_data",
        "reference_data",
        "corporate_actions",
        "universe_membership",
        "benchmark_data",
        "mixed",
        "other",
    }


def test_data_source_type_contains_documented_values() -> None:
    assert {source_type.value for source_type in DataSourceType} == {
        "vendor",
        "exchange",
        "public_dataset",
        "internal",
        "research_generated",
        "manual",
        "other",
    }


def test_data_adjustment_policy_contains_documented_values() -> None:
    assert {policy.value for policy in DataAdjustmentPolicy} == {
        "raw",
        "split_adjusted",
        "total_return",
        "continuous",
        "other",
    }


def test_temporal_coverage_contains_documented_values() -> None:
    assert {coverage.value for coverage in TemporalCoverage} == {
        "point_in_time",
        "first_available",
        "latest_known",
        "mixed",
        "not_applicable",
    }


def test_data_snapshot_status_contains_documented_values() -> None:
    assert {status.value for status in DataSnapshotStatus} == {
        "created",
        "completed",
        "failed",
        "invalid",
        "superseded",
    }


def test_data_snapshot_manifest_normalizes_utc_datetimes() -> None:
    data = valid_snapshot_data()
    pacific = timezone(timedelta(hours=-7))
    data["created_at"] = datetime(2026, 7, 9, 2, 0, 0, tzinfo=pacific)
    data["as_of"] = datetime(2026, 7, 9, 1, 30, 0, tzinfo=pacific)
    data["source_observed_at"] = datetime(2026, 7, 9, 1, 40, 0, tzinfo=pacific)
    data["ingestion_completed_at"] = datetime(2026, 7, 9, 1, 50, 0, tzinfo=pacific)
    data["available_at"] = datetime(2026, 7, 9, 1, 55, 0, tzinfo=pacific)
    data["asset_universe"]["as_of"] = datetime(2026, 7, 9, 1, 25, 0, tzinfo=pacific)

    manifest = DataSnapshotManifest(**data)

    assert manifest.created_at == datetime(2026, 7, 9, 9, 0, 0, tzinfo=UTC)
    assert manifest.as_of == datetime(2026, 7, 9, 8, 30, 0, tzinfo=UTC)
    assert manifest.source_observed_at == datetime(2026, 7, 9, 8, 40, 0, tzinfo=UTC)
    assert manifest.ingestion_completed_at == datetime(2026, 7, 9, 8, 50, 0, tzinfo=UTC)
    assert manifest.available_at == datetime(2026, 7, 9, 8, 55, 0, tzinfo=UTC)
    assert manifest.asset_universe.as_of == datetime(2026, 7, 9, 8, 25, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "field_path",
    [
        ("created_at",),
        ("as_of",),
        ("available_at",),
        ("ingestion_completed_at",),
        ("source_observed_at",),
        ("asset_universe", "as_of"),
    ],
)
def test_data_snapshot_manifest_rejects_naive_datetimes(
    field_path: tuple[str, ...],
) -> None:
    data = valid_snapshot_data()
    target = data
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = datetime(2026, 7, 9, 9, 0, 0)

    with pytest.raises(ValidationError):
        DataSnapshotManifest(**data)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("snapshot_kind", "tick_level_alpha_signal"),
        ("status", "verified"),
        ("source_type", "broker"),
        ("temporal_coverage", "survivorship_biased"),
        ("adjustment_policy", "back_adjusted"),
        ("asset_class", "single_stock_futures"),
        ("hash_algorithm", "md5"),
    ],
)
def test_data_snapshot_manifest_rejects_invalid_enum_values(
    field_name: str,
    value: str,
) -> None:
    data = valid_snapshot_data()
    data[field_name] = value

    with pytest.raises(ValidationError):
        DataSnapshotManifest(**data)


def test_data_snapshot_manifest_rejects_unknown_extra_fields() -> None:
    data = valid_snapshot_data()
    data["storage_verified"] = True

    with pytest.raises(ValidationError):
        DataSnapshotManifest(**data)


@pytest.mark.parametrize(
    "field_name",
    [
        "snapshot_id",
        "data_root_uri",
        "source_dataset",
        "source_version",
        "as_of",
        "available_at",
        "ingestion_completed_at",
        "content_hash",
        "row_count",
        "known_limitations",
    ],
)
def test_data_snapshot_manifest_rejects_missing_required_fields(
    field_name: str,
) -> None:
    data = valid_snapshot_data()
    del data[field_name]

    with pytest.raises(ValidationError):
        DataSnapshotManifest(**data)


@pytest.mark.parametrize(
    "field_name",
    [
        "row_count",
        "file_count",
        "size_bytes",
    ],
)
def test_data_snapshot_manifest_rejects_negative_counts(field_name: str) -> None:
    data = valid_snapshot_data()
    data[field_name] = -1

    with pytest.raises(ValidationError):
        DataSnapshotManifest(**data)


def test_data_snapshot_manifest_rejects_source_observed_after_ingestion() -> None:
    data = valid_snapshot_data()
    data["source_observed_at"] = datetime(2026, 7, 9, 8, 51, 0, tzinfo=UTC)

    with pytest.raises(ValidationError, match="source_observed_at"):
        DataSnapshotManifest(**data)


def test_data_snapshot_manifest_rejects_ingestion_after_available() -> None:
    data = valid_snapshot_data()
    data["ingestion_completed_at"] = datetime(2026, 7, 9, 8, 56, 0, tzinfo=UTC)

    with pytest.raises(ValidationError, match="ingestion_completed_at"):
        DataSnapshotManifest(**data)


def test_data_snapshot_manifest_rejects_available_after_created() -> None:
    data = valid_snapshot_data()
    data["available_at"] = datetime(2026, 7, 9, 9, 1, 0, tzinfo=UTC)

    with pytest.raises(ValidationError, match="available_at"):
        DataSnapshotManifest(**data)


def test_data_snapshot_manifest_rejects_as_of_after_available() -> None:
    data = valid_snapshot_data()
    data["as_of"] = datetime(2026, 7, 9, 8, 56, 0, tzinfo=UTC)

    with pytest.raises(ValidationError, match="as_of"):
        DataSnapshotManifest(**data)


def test_data_snapshot_manifest_rejects_time_range_after_as_of_date() -> None:
    data = valid_snapshot_data()
    data["time_range"] = {
        "start_date": date(2020, 1, 1),
        "end_date": date(2026, 7, 10),
    }

    with pytest.raises(ValidationError, match="time_range.end_date"):
        DataSnapshotManifest(**data)


def test_data_snapshot_manifest_rejects_asset_universe_as_of_after_as_of() -> None:
    data = valid_snapshot_data()
    data["asset_universe"]["as_of"] = datetime(2026, 7, 9, 8, 31, 0, tzinfo=UTC)

    with pytest.raises(ValidationError, match="asset_universe.as_of"):
        DataSnapshotManifest(**data)


def test_data_snapshot_manifest_requires_vendor_name_for_vendor_source() -> None:
    data = valid_snapshot_data()
    data["vendor_name"] = None

    with pytest.raises(ValidationError, match="vendor_name"):
        DataSnapshotManifest(**data)


def test_data_snapshot_manifest_accepts_missing_vendor_name_for_non_vendor() -> None:
    data = valid_snapshot_data()
    data["source_type"] = "internal"
    data["vendor_name"] = None

    manifest = DataSnapshotManifest(**data)

    assert manifest.source_type is DataSourceType.INTERNAL
    assert manifest.vendor_name is None


def test_data_snapshot_manifest_requires_notes_for_other_adjustment_policy() -> None:
    data = valid_snapshot_data()
    data["adjustment_policy"] = "other"

    with pytest.raises(ValidationError, match="adjustment_policy_notes"):
        DataSnapshotManifest(**data)


def test_data_snapshot_manifest_requires_notes_for_mixed_temporal_coverage() -> None:
    data = valid_snapshot_data()
    data["temporal_coverage"] = "mixed"

    with pytest.raises(ValidationError, match="temporal_coverage_notes"):
        DataSnapshotManifest(**data)


def test_data_snapshot_manifest_rejects_empty_known_limitations() -> None:
    data = valid_snapshot_data()
    data["known_limitations"] = ()

    with pytest.raises(ValidationError):
        DataSnapshotManifest(**data)


def test_data_snapshot_manifest_accepts_none_known_limitation() -> None:
    data = valid_snapshot_data()
    data["known_limitations"] = ("none known",)

    manifest = DataSnapshotManifest(**data)

    assert manifest.known_limitations == ("none known",)


def test_data_snapshot_manifest_keeps_integrity_metadata_declarative() -> None:
    data = deepcopy(valid_snapshot_data())
    data["content_hash"] = "not-a-validated-hash"

    manifest = DataSnapshotManifest(**data)

    assert manifest.content_hash == "not-a-validated-hash"


def test_data_snapshot_manifest_has_no_ingestion_or_storage_behavior() -> None:
    manifest = DataSnapshotManifest(**valid_snapshot_data())

    for method_name in (
        "ingest",
        "fetch_vendor_data",
        "read_files",
        "verify_hashes",
        "validate_storage",
        "scan_quality",
        "write_snapshot",
    ):
        assert not hasattr(manifest, method_name)
