"""Data snapshot manifest contracts for reproducible research inputs."""

from typing import Self

from pydantic import Field, model_validator

from research_sdk.contracts.enums import (
    AssetClass,
    DataAdjustmentPolicy,
    DataSnapshotKind,
    DataSnapshotStatus,
    DataSourceType,
    HashAlgorithm,
    TemporalCoverage,
)
from research_sdk.contracts.ledger import AssetUniverseReference, TimeRange
from research_sdk.contracts.schema import VersionedContract
from research_sdk.contracts.time import UtcDatetime
from research_sdk.contracts.types import NonEmptyString


class DataSnapshotManifest(VersionedContract):
    """Manifest describing a full point-in-time dataset snapshot."""

    snapshot_id: NonEmptyString
    snapshot_kind: DataSnapshotKind
    status: DataSnapshotStatus
    created_at: UtcDatetime
    created_by: NonEmptyString
    asset_class: AssetClass
    asset_universe: AssetUniverseReference
    time_range: TimeRange
    frequency: NonEmptyString
    data_root_uri: NonEmptyString
    source_dataset: NonEmptyString
    source_version: NonEmptyString
    source_type: DataSourceType
    temporal_coverage: TemporalCoverage
    as_of: UtcDatetime
    available_at: UtcDatetime
    ingestion_completed_at: UtcDatetime
    adjustment_policy: DataAdjustmentPolicy
    calendar: NonEmptyString
    timezone: NonEmptyString
    universe_membership_policy: NonEmptyString
    corporate_action_policy: NonEmptyString
    survivorship_policy: NonEmptyString
    delisting_policy: NonEmptyString
    hash_algorithm: HashAlgorithm
    content_hash: NonEmptyString
    row_count: int = Field(ge=0)
    known_limitations: tuple[NonEmptyString, ...] = Field(min_length=1)
    vendor_name: NonEmptyString | None = None
    license_notes: NonEmptyString | None = None
    source_observed_at: UtcDatetime | None = None
    currency: NonEmptyString | None = None
    rollover_policy: NonEmptyString | None = None
    file_count: int | None = Field(default=None, ge=0)
    size_bytes: int | None = Field(default=None, ge=0)
    adjustment_policy_notes: NonEmptyString | None = None
    temporal_coverage_notes: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_snapshot_manifest_consistency(self) -> Self:
        """Validate manifest relationships without inspecting external data."""

        if (
            self.source_observed_at is not None
            and self.source_observed_at > self.ingestion_completed_at
        ):
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

        if self.as_of > self.available_at:
            raise ValueError("as_of must be less than or equal to available_at")

        if self.time_range.end_date > self.as_of.date():
            raise ValueError("time_range.end_date must be on or before as_of date")

        if (
            self.asset_universe.as_of is not None
            and self.asset_universe.as_of > self.as_of
        ):
            raise ValueError("asset_universe.as_of must be less than or equal to as_of")

        if self.source_type is DataSourceType.VENDOR and self.vendor_name is None:
            raise ValueError("vendor_name is required when source_type is vendor")

        if (
            self.adjustment_policy is DataAdjustmentPolicy.OTHER
            and self.adjustment_policy_notes is None
        ):
            raise ValueError(
                "adjustment_policy_notes is required when adjustment_policy is other"
            )

        if (
            self.temporal_coverage is TemporalCoverage.MIXED
            and self.temporal_coverage_notes is None
        ):
            raise ValueError(
                "temporal_coverage_notes is required when temporal_coverage is mixed"
            )

        return self
