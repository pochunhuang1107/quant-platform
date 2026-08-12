"""Versioned daily market-data snapshot v2 bundle contracts."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Final, Self
from urllib.parse import parse_qsl, urlsplit

from pydantic import ConfigDict, Field, field_validator, model_validator

from research_sdk.contracts.base import BaseContractModel
from research_sdk.contracts.daily_market_data import SHA256_CONTENT_HASH_PATTERN
from research_sdk.contracts.daily_market_data_snapshots import (
    CORPORATE_ACTION_NOT_INTEGRATED_LIMITATION,
    DAILY_MARKET_DATA_BUNDLE_MANIFEST_PATH,
)
from research_sdk.contracts.enums import DataSourceType, TemporalCoverage
from research_sdk.contracts.schema import VersionedContract
from research_sdk.contracts.time import UtcDatetime
from research_sdk.contracts.types import NonEmptyString

SNAPSHOT_ID_V2_PREFIX: Final[str] = "daily-market-data-snapshot-v2-"
SNAPSHOT_ID_V2_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"^{SNAPSHOT_ID_V2_PREFIX}[0-9a-f]{{64}}$"
)
BUNDLE_FORMAT_VERSION_V2: Final[str] = "daily-market-data-snapshot-bundle-v2"

_SENSITIVE_REFERENCE_QUERY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "signature",
        "sig",
        "token",
        "x-amz-credential",
        "x-amz-security-token",
        "x-amz-signature",
    }
)


class DailyMarketDataSnapshotFileRoleV2(StrEnum):
    """Authoritative file roles in an S3c2a snapshot-v2 bundle."""

    BARS = "bars"
    EXPECTED_SESSIONS = "expected_sessions"
    POLICY = "policy"
    BAR_PROVENANCE = "bar_provenance"
    QUALITY_REPORT = "quality_report"
    CORPORATE_ACTION_EVIDENCE = "corporate_action_evidence"
    SNAPSHOT_MANIFEST = "snapshot_manifest"


REQUIRED_DAILY_MARKET_DATA_SNAPSHOT_FILES_V2: Final[
    tuple[tuple[DailyMarketDataSnapshotFileRoleV2, str, str], ...]
] = (
    (
        DailyMarketDataSnapshotFileRoleV2.BARS,
        "bars.jsonl",
        "application/x-ndjson",
    ),
    (
        DailyMarketDataSnapshotFileRoleV2.EXPECTED_SESSIONS,
        "expected-sessions.json",
        "application/json",
    ),
    (DailyMarketDataSnapshotFileRoleV2.POLICY, "policy.json", "application/json"),
    (
        DailyMarketDataSnapshotFileRoleV2.BAR_PROVENANCE,
        "bar-provenance.json",
        "application/json",
    ),
    (
        DailyMarketDataSnapshotFileRoleV2.QUALITY_REPORT,
        "quality-report.json",
        "application/json",
    ),
    (
        DailyMarketDataSnapshotFileRoleV2.CORPORATE_ACTION_EVIDENCE,
        "corporate-action-evidence.json",
        "application/json",
    ),
    (
        DailyMarketDataSnapshotFileRoleV2.SNAPSHOT_MANIFEST,
        "snapshot-manifest.json",
        "application/json",
    ),
)
REQUIRED_DAILY_MARKET_DATA_SNAPSHOT_PATHS_V2: Final[tuple[str, ...]] = tuple(
    path for _, path, _ in REQUIRED_DAILY_MARKET_DATA_SNAPSHOT_FILES_V2
)


class DailyMarketDataBarSourceProvenanceV2(VersionedContract):
    """Bar-only source and capture authority for a snapshot-v2 bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provenance_policy_version: NonEmptyString
    created_at: UtcDatetime
    created_by: NonEmptyString
    source_dataset: NonEmptyString
    source_version: NonEmptyString
    source_type: DataSourceType
    source_reference: NonEmptyString
    source_content_hash: NonEmptyString
    source_size_bytes: int = Field(ge=0)
    parser_version: NonEmptyString
    temporal_coverage: TemporalCoverage
    as_of: UtcDatetime
    source_observed_at: UtcDatetime | None = None
    ingestion_completed_at: UtcDatetime
    available_at: UtcDatetime
    vendor_name: NonEmptyString | None = None
    license_notes: NonEmptyString | None = None
    source_instrument_reference: NonEmptyString
    currency: NonEmptyString
    known_limitations: tuple[NonEmptyString, ...] = Field(min_length=1)

    @field_validator("source_content_hash")
    @classmethod
    def validate_source_hash(cls, value: str) -> str:
        if SHA256_CONTENT_HASH_PATTERN.fullmatch(value) is None:
            raise ValueError("source_content_hash must use sha256:<64 lowercase hex>")
        return value

    @field_validator("source_reference")
    @classmethod
    def reject_sensitive_source_reference(cls, value: str) -> str:
        return _reject_sensitive_reference(value, context="source references")

    @field_validator("known_limitations")
    @classmethod
    def reject_legacy_not_integrated_limitation(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        if CORPORATE_ACTION_NOT_INTEGRATED_LIMITATION in set(value):
            raise ValueError(
                "snapshot-v2 bar provenance must not carry the legacy "
                "not-integrated corporate-action limitation"
            )
        return value

    @model_validator(mode="after")
    def validate_bar_provenance(self) -> Self:
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
        if self.temporal_coverage is TemporalCoverage.MIXED:
            raise ValueError(
                "mixed temporal coverage requires explanatory authority deferred "
                "beyond S3c2a"
            )
        if self.source_type is DataSourceType.VENDOR and self.vendor_name is None:
            raise ValueError("vendor_name is required when source_type is vendor")
        return self


class DailyMarketDataSnapshotFileEntryV2(BaseContractModel):
    """Storage-byte integrity facts for one snapshot-v2 payload file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    relative_path: NonEmptyString
    role: DailyMarketDataSnapshotFileRoleV2
    media_type: NonEmptyString
    sha256: NonEmptyString
    size_bytes: int = Field(ge=0)
    row_count: int | None = Field(default=None, ge=0)

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if SHA256_CONTENT_HASH_PATTERN.fullmatch(value) is None:
            raise ValueError("sha256 must use sha256:<64 lowercase hex>")
        return value

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        if value.startswith("/") or "\\" in value:
            raise ValueError("relative_path must be a relative POSIX path")
        parts = value.split("/")
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("relative_path must not contain empty, ., or .. segments")
        if len(parts) != 1:
            raise ValueError("S3c2a bundle files must be top-level filenames")
        if value == DAILY_MARKET_DATA_BUNDLE_MANIFEST_PATH:
            raise ValueError("bundle-manifest.json must not be a payload entry")
        return value


class DailyMarketDataSnapshotBundleManifestV2(VersionedContract):
    """Dataset-specific file manifest for a snapshot-v2 bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bundle_format_version: NonEmptyString
    snapshot_id: NonEmptyString
    semantic_content_hash: NonEmptyString
    policy_hash: NonEmptyString
    expected_sessions_hash: NonEmptyString
    bar_provenance_hash: NonEmptyString
    corporate_action_semantic_hash: NonEmptyString
    corporate_action_evidence_authority_hash: NonEmptyString
    files: tuple[DailyMarketDataSnapshotFileEntryV2, ...]

    @field_validator(
        "semantic_content_hash",
        "policy_hash",
        "expected_sessions_hash",
        "bar_provenance_hash",
        "corporate_action_semantic_hash",
        "corporate_action_evidence_authority_hash",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        if SHA256_CONTENT_HASH_PATTERN.fullmatch(value) is None:
            raise ValueError("hash fields must use sha256:<64 lowercase hex>")
        return value

    @field_validator("snapshot_id")
    @classmethod
    def validate_snapshot_id(cls, value: str) -> str:
        if SNAPSHOT_ID_V2_PATTERN.fullmatch(value) is None:
            raise ValueError("snapshot_id must use daily-market-data-snapshot-v2-*")
        return value

    @model_validator(mode="after")
    def validate_bundle_manifest(self) -> Self:
        if self.bundle_format_version != BUNDLE_FORMAT_VERSION_V2:
            raise ValueError(
                "bundle_format_version must be daily-market-data-snapshot-bundle-v2"
            )
        expected = REQUIRED_DAILY_MARKET_DATA_SNAPSHOT_FILES_V2
        expected_roles = tuple(role for role, _, _ in expected)
        expected_paths = tuple(path for _, path, _ in expected)
        expected_media_types = tuple(media_type for _, _, media_type in expected)
        actual_roles = tuple(entry.role for entry in self.files)
        actual_paths = tuple(entry.relative_path for entry in self.files)
        actual_media_types = tuple(entry.media_type for entry in self.files)
        if actual_roles != expected_roles:
            raise ValueError("bundle files must use canonical required role order")
        if actual_paths != expected_paths:
            raise ValueError("bundle files must use canonical required paths")
        if actual_media_types != expected_media_types:
            raise ValueError("bundle file media types must match required roles")
        if len(set(actual_roles)) != len(actual_roles):
            raise ValueError("bundle file roles must be unique")
        if len(set(actual_paths)) != len(actual_paths):
            raise ValueError("bundle file paths must be unique")
        for entry in self.files:
            if entry.role is DailyMarketDataSnapshotFileRoleV2.BARS:
                if entry.row_count is None:
                    raise ValueError("bars file entry requires row_count")
            elif entry.row_count is not None:
                raise ValueError("sidecar file entries must not carry row_count")
        return self


def _reject_sensitive_reference(value: str, *, context: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme and parsed.netloc and (parsed.username or parsed.password):
        raise ValueError(f"{context} must not contain URI userinfo")
    sensitive_keys = {
        key.lower() for key, _value in parse_qsl(parsed.query, keep_blank_values=True)
    }
    if sensitive_keys & _SENSITIVE_REFERENCE_QUERY_KEYS:
        raise ValueError(f"{context} must not contain obvious access tokens")
    return value


__all__ = [
    "BUNDLE_FORMAT_VERSION_V2",
    "REQUIRED_DAILY_MARKET_DATA_SNAPSHOT_FILES_V2",
    "REQUIRED_DAILY_MARKET_DATA_SNAPSHOT_PATHS_V2",
    "SNAPSHOT_ID_V2_PATTERN",
    "SNAPSHOT_ID_V2_PREFIX",
    "DailyMarketDataBarSourceProvenanceV2",
    "DailyMarketDataSnapshotBundleManifestV2",
    "DailyMarketDataSnapshotFileEntryV2",
    "DailyMarketDataSnapshotFileRoleV2",
]
