"""Immutable daily market-data snapshot bundle contracts."""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import StrEnum
from typing import Final, Self
from urllib.parse import urlsplit

from pydantic import ConfigDict, Field, field_validator, model_validator

from research_sdk.contracts.base import BaseContractModel
from research_sdk.contracts.daily_market_data import SHA256_CONTENT_HASH_PATTERN
from research_sdk.contracts.enums import DataSourceType, TemporalCoverage
from research_sdk.contracts.schema import VersionedContract
from research_sdk.contracts.time import UtcDatetime
from research_sdk.contracts.types import NonEmptyString

SNAPSHOT_ID_PREFIX: Final[str] = "daily-market-data-snapshot-v1-"
SNAPSHOT_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"^{SNAPSHOT_ID_PREFIX}[0-9a-f]{{64}}$"
)
DATA_ROOT_URI_PREFIX: Final[str] = "daily-market-data/"
CORPORATE_ACTION_NOT_INTEGRATED_LIMITATION: Final[str] = (
    "corporate-action/distribution evidence is not integrated"
)


class CorporateActionEvidenceStatus(StrEnum):
    """Recorded status for corporate-action/distribution evidence."""

    NOT_INTEGRATED = "not_integrated"
    CHECKED_NO_EVENTS = "checked_no_events"
    EVENTS_PRESENT_UNSUPPORTED = "events_present_unsupported"


class DailyMarketDataSnapshotFileRole(StrEnum):
    """Authoritative file roles in an S3b daily market-data snapshot bundle."""

    BARS = "bars"
    EXPECTED_SESSIONS = "expected_sessions"
    POLICY = "policy"
    PROVENANCE = "provenance"
    QUALITY_REPORT = "quality_report"
    SNAPSHOT_MANIFEST = "snapshot_manifest"


REQUIRED_DAILY_MARKET_DATA_SNAPSHOT_FILES: Final[
    tuple[tuple[DailyMarketDataSnapshotFileRole, str, str], ...]
] = (
    (
        DailyMarketDataSnapshotFileRole.BARS,
        "bars.jsonl",
        "application/x-ndjson",
    ),
    (
        DailyMarketDataSnapshotFileRole.EXPECTED_SESSIONS,
        "expected-sessions.json",
        "application/json",
    ),
    (DailyMarketDataSnapshotFileRole.POLICY, "policy.json", "application/json"),
    (
        DailyMarketDataSnapshotFileRole.PROVENANCE,
        "provenance.json",
        "application/json",
    ),
    (
        DailyMarketDataSnapshotFileRole.QUALITY_REPORT,
        "quality-report.json",
        "application/json",
    ),
    (
        DailyMarketDataSnapshotFileRole.SNAPSHOT_MANIFEST,
        "snapshot-manifest.json",
        "application/json",
    ),
)
REQUIRED_DAILY_MARKET_DATA_SNAPSHOT_PATHS: Final[tuple[str, ...]] = tuple(
    path for _, path, _ in REQUIRED_DAILY_MARKET_DATA_SNAPSHOT_FILES
)
DAILY_MARKET_DATA_BUNDLE_MANIFEST_PATH: Final[str] = "bundle-manifest.json"


class DailyMarketDataExpectedSessions(VersionedContract):
    """Exact expected-session authority used for daily data quality validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_source_id: NonEmptyString
    session_source_version: NonEmptyString
    calendar: NonEmptyString
    timezone: NonEmptyString
    session_dates: tuple[date, ...] = Field(min_length=1)

    @field_validator("session_dates", mode="before")
    @classmethod
    def reject_non_date_session_values(cls, value: object) -> object:
        """Reject datetime/bool/object values before date coercion."""

        if isinstance(value, list | tuple):
            for session_date in value:
                if isinstance(session_date, datetime | bool):
                    raise ValueError("session_dates must contain date values only")
        return value

    @field_validator("session_dates")
    @classmethod
    def validate_session_dates(cls, value: tuple[date, ...]) -> tuple[date, ...]:
        """Require unique strictly ascending dates."""

        if len(set(value)) != len(value):
            raise ValueError("session_dates must not contain duplicates")
        if value != tuple(sorted(value)):
            raise ValueError("session_dates must be strictly ascending")
        return value


class DailyMarketDataSnapshotProvenance(VersionedContract):
    """Persisted source and capture authority for an immutable snapshot plan."""

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
    corporate_action_evidence_status: CorporateActionEvidenceStatus
    corporate_action_source_reference: NonEmptyString | None = None
    corporate_action_source_content_hash: NonEmptyString | None = None
    corporate_action_source_size_bytes: int | None = Field(default=None, ge=0)
    corporate_action_event_count: int | None = Field(default=None, ge=0)

    @field_validator("source_content_hash", "corporate_action_source_content_hash")
    @classmethod
    def validate_hash(cls, value: str | None) -> str | None:
        """Require repository-standard SHA-256 content-hash formatting."""

        if value is not None and SHA256_CONTENT_HASH_PATTERN.fullmatch(value) is None:
            raise ValueError("hash values must use sha256:<64 lowercase hex>")
        return value

    @field_validator("source_reference", "corporate_action_source_reference")
    @classmethod
    def reject_uri_userinfo(cls, value: str | None) -> str | None:
        """Reject credential-bearing URI userinfo in persisted references."""

        if value is None:
            return value
        parsed = urlsplit(value)
        if parsed.scheme and parsed.netloc and (parsed.username or parsed.password):
            raise ValueError("source references must not contain URI userinfo")
        return value

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        """Validate provenance chronology and evidence-state coherence."""

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
                "beyond S3b1"
            )
        if self.source_type is DataSourceType.VENDOR and self.vendor_name is None:
            raise ValueError("vendor_name is required when source_type is vendor")

        has_action_source = any(
            value is not None
            for value in (
                self.corporate_action_source_reference,
                self.corporate_action_source_content_hash,
                self.corporate_action_source_size_bytes,
                self.corporate_action_event_count,
            )
        )
        if (
            self.corporate_action_evidence_status
            is CorporateActionEvidenceStatus.NOT_INTEGRATED
        ):
            if has_action_source:
                raise ValueError(
                    "not_integrated corporate-action evidence must not include "
                    "source fields"
                )
            if CORPORATE_ACTION_NOT_INTEGRATED_LIMITATION not in set(
                self.known_limitations
            ):
                raise ValueError(
                    "not_integrated corporate-action evidence requires an explicit "
                    "known limitation"
                )
            return self

        required_action_fields = {
            "corporate_action_source_reference": self.corporate_action_source_reference,
            "corporate_action_source_content_hash": (
                self.corporate_action_source_content_hash
            ),
            "corporate_action_source_size_bytes": (
                self.corporate_action_source_size_bytes
            ),
            "corporate_action_event_count": self.corporate_action_event_count,
        }
        missing = [
            field_name
            for field_name, value in required_action_fields.items()
            if value is None
        ]
        if missing:
            raise ValueError(
                "checked corporate-action evidence requires "
                + ", ".join(sorted(missing))
            )
        if (
            self.corporate_action_evidence_status
            is CorporateActionEvidenceStatus.CHECKED_NO_EVENTS
            and self.corporate_action_event_count != 0
        ):
            raise ValueError("checked_no_events requires event count 0")
        if (
            self.corporate_action_evidence_status
            is CorporateActionEvidenceStatus.EVENTS_PRESENT_UNSUPPORTED
            and (self.corporate_action_event_count or 0) <= 0
        ):
            raise ValueError("events_present_unsupported requires event count > 0")
        return self


class DailyMarketDataSnapshotFileEntry(BaseContractModel):
    """Storage-byte integrity facts for one authoritative bundle payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    relative_path: NonEmptyString
    role: DailyMarketDataSnapshotFileRole
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
            raise ValueError("S3b1 bundle files must be top-level filenames")
        if value == DAILY_MARKET_DATA_BUNDLE_MANIFEST_PATH:
            raise ValueError("bundle-manifest.json must not be a payload entry")
        return value


class DailyMarketDataSnapshotBundleManifest(VersionedContract):
    """Dataset-specific manifest for an immutable daily market-data bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bundle_format_version: NonEmptyString
    snapshot_id: NonEmptyString
    semantic_content_hash: NonEmptyString
    policy_hash: NonEmptyString
    expected_sessions_hash: NonEmptyString
    provenance_hash: NonEmptyString
    files: tuple[DailyMarketDataSnapshotFileEntry, ...]

    @field_validator(
        "semantic_content_hash",
        "policy_hash",
        "expected_sessions_hash",
        "provenance_hash",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        if SHA256_CONTENT_HASH_PATTERN.fullmatch(value) is None:
            raise ValueError("hash fields must use sha256:<64 lowercase hex>")
        return value

    @field_validator("snapshot_id")
    @classmethod
    def validate_snapshot_id(cls, value: str) -> str:
        if SNAPSHOT_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("snapshot_id must use daily-market-data-snapshot-v1-*")
        return value

    @model_validator(mode="after")
    def validate_bundle_manifest(self) -> Self:
        """Require the exact S3b1 payload file set and canonical order."""

        expected = REQUIRED_DAILY_MARKET_DATA_SNAPSHOT_FILES
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
            if entry.role is DailyMarketDataSnapshotFileRole.BARS:
                if entry.row_count is None:
                    raise ValueError("bars file entry requires row_count")
            elif entry.row_count is not None:
                raise ValueError("sidecar file entries must not carry row_count")
        return self


__all__ = [
    "CORPORATE_ACTION_NOT_INTEGRATED_LIMITATION",
    "DAILY_MARKET_DATA_BUNDLE_MANIFEST_PATH",
    "DATA_ROOT_URI_PREFIX",
    "REQUIRED_DAILY_MARKET_DATA_SNAPSHOT_FILES",
    "REQUIRED_DAILY_MARKET_DATA_SNAPSHOT_PATHS",
    "SNAPSHOT_ID_PATTERN",
    "SNAPSHOT_ID_PREFIX",
    "CorporateActionEvidenceStatus",
    "DailyMarketDataExpectedSessions",
    "DailyMarketDataSnapshotBundleManifest",
    "DailyMarketDataSnapshotFileEntry",
    "DailyMarketDataSnapshotFileRole",
    "DailyMarketDataSnapshotProvenance",
]
