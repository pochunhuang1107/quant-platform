"""Pure in-memory planning for immutable daily market-data snapshot bundles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from research_sdk.contracts import (
    AssetUniverseReference,
    DataSnapshotKind,
    DataSnapshotManifest,
    DataSnapshotStatus,
    HashAlgorithm,
    TimeRange,
)
from research_sdk.contracts.daily_market_data import (
    DailyMarketDataInstrument,
    DailyMarketDataPolicy,
    DailyMarketDataQualityReport,
    DailyMarketDataQualityStatus,
)
from research_sdk.contracts.daily_market_data_snapshots import (
    DAILY_MARKET_DATA_BUNDLE_MANIFEST_PATH,
    DATA_ROOT_URI_PREFIX,
    REQUIRED_DAILY_MARKET_DATA_SNAPSHOT_FILES,
    CorporateActionEvidenceStatus,
    DailyMarketDataExpectedSessions,
    DailyMarketDataSnapshotBundleManifest,
    DailyMarketDataSnapshotFileEntry,
    DailyMarketDataSnapshotProvenance,
)
from research_sdk.contracts.enums import DataSourceType, TemporalCoverage
from research_sdk.contracts.schema import RESEARCH_SDK_CONTRACT_SCHEMA_VERSION
from research_sdk.daily_market_data import (
    evaluate_daily_market_data_quality,
    validate_daily_market_data_snapshot_manifest,
)
from research_sdk.daily_market_data.snapshot_identity import (
    derive_daily_market_data_expected_sessions_hash,
    derive_daily_market_data_policy_hash,
    derive_daily_market_data_provenance_hash,
    derive_daily_market_data_snapshot_id,
)
from research_sdk.daily_market_data_storage.serialization import (
    parse_canonical_daily_bars,
    render_canonical_daily_bars,
    render_contract_json,
    sha256_bytes,
)

BUNDLE_FORMAT_VERSION = "daily-market-data-snapshot-bundle-v1"
PROVENANCE_POLICY_VERSION = "daily-market-data-snapshot-provenance-v1"
PARSER_VERSION = "daily-market-data-jsonl-parser-v1"


class DailyMarketDataSnapshotPlanningError(ValueError):
    """Raised when a daily market-data snapshot cannot be planned."""


@dataclass(frozen=True)
class DailyMarketDataSnapshotProvenanceInput:
    """Caller-supplied provenance facts whose source hash/size are derived."""

    created_at: datetime
    created_by: str
    source_dataset: str
    source_version: str
    source_type: DataSourceType
    source_reference: str
    temporal_coverage: TemporalCoverage
    as_of: datetime
    ingestion_completed_at: datetime
    available_at: datetime
    source_instrument_reference: str
    currency: str
    known_limitations: tuple[str, ...]
    source_observed_at: datetime | None = None
    vendor_name: str | None = None
    license_notes: str | None = None
    corporate_action_evidence_status: CorporateActionEvidenceStatus = (
        CorporateActionEvidenceStatus.NOT_INTEGRATED
    )
    corporate_action_source_reference: str | None = None
    corporate_action_source_content_hash: str | None = None
    corporate_action_source_size_bytes: int | None = None
    corporate_action_event_count: int | None = None


@dataclass(frozen=True)
class PlannedDailyMarketDataSnapshotFile:
    """Immutable planned file bytes for an S3b1 in-memory bundle."""

    relative_path: str
    content: bytes


@dataclass(frozen=True)
class DailyMarketDataSnapshotPlan:
    """Pure in-memory snapshot plan with all final deterministic bytes."""

    snapshot_id: str
    manifest: DataSnapshotManifest
    quality_report: DailyMarketDataQualityReport
    policy_hash: str
    expected_sessions_hash: str
    provenance_hash: str
    bundle_manifest: DailyMarketDataSnapshotBundleManifest
    files: tuple[PlannedDailyMarketDataSnapshotFile, ...]

    def as_file_map(self) -> dict[str, bytes]:
        """Return a detached filename-to-bytes mapping for verification tests."""

        return {
            planned_file.relative_path: planned_file.content
            for planned_file in self.files
        }


def plan_daily_market_data_snapshot(
    *,
    source_bytes: bytes,
    instrument: DailyMarketDataInstrument,
    policy: DailyMarketDataPolicy,
    expected_sessions: DailyMarketDataExpectedSessions,
    provenance_input: DailyMarketDataSnapshotProvenanceInput,
) -> DailyMarketDataSnapshotPlan:
    """Build a deterministic in-memory immutable daily market-data snapshot plan."""

    if type(source_bytes) is not bytes:
        raise DailyMarketDataSnapshotPlanningError("source_bytes must be bytes")

    validated_instrument = DailyMarketDataInstrument.model_validate(
        instrument.model_dump(mode="json")
    )
    validated_policy = DailyMarketDataPolicy.model_validate(
        policy.model_dump(mode="json")
    )
    validated_expected_sessions = DailyMarketDataExpectedSessions.model_validate(
        expected_sessions.model_dump(mode="json")
    )
    if validated_expected_sessions.calendar != validated_policy.calendar:
        raise DailyMarketDataSnapshotPlanningError(
            "expected sessions calendar must match policy"
        )
    if validated_expected_sessions.timezone != validated_policy.timezone:
        raise DailyMarketDataSnapshotPlanningError(
            "expected sessions timezone must match policy"
        )

    source_content_hash = sha256_bytes(source_bytes)
    bars = parse_canonical_daily_bars(source_bytes)
    provenance = _build_provenance(
        provenance_input=provenance_input,
        source_content_hash=source_content_hash,
        source_size_bytes=len(source_bytes),
    )

    quality_report = evaluate_daily_market_data_quality(
        instrument=validated_instrument,
        bars=bars,
        expected_session_dates=validated_expected_sessions.session_dates,
        policy=validated_policy,
    )
    if quality_report.status is not DailyMarketDataQualityStatus.PASS:
        raise DailyMarketDataSnapshotPlanningError(
            "daily market-data quality must pass before snapshot planning"
        )
    if quality_report.expected_end_date > provenance.as_of.date():
        raise DailyMarketDataSnapshotPlanningError(
            "quality expected_end_date must be on or before provenance as_of date"
        )

    semantic_content_hash = quality_report.content_hash
    policy_hash = derive_daily_market_data_policy_hash(validated_policy)
    expected_sessions_hash = derive_daily_market_data_expected_sessions_hash(
        validated_expected_sessions
    )
    provenance_hash = derive_daily_market_data_provenance_hash(provenance)
    snapshot_id = derive_daily_market_data_snapshot_id(
        semantic_content_hash=semantic_content_hash,
        policy_hash=policy_hash,
        expected_sessions_hash=expected_sessions_hash,
        provenance_hash=provenance_hash,
    )

    bars_bytes = render_canonical_daily_bars(bars)
    manifest = _build_manifest(
        snapshot_id=snapshot_id,
        instrument=validated_instrument,
        policy=validated_policy,
        quality_report=quality_report,
        provenance=provenance,
        bars_size_bytes=len(bars_bytes),
    )
    validate_daily_market_data_snapshot_manifest(
        manifest=manifest,
        policy=validated_policy,
        quality_report=quality_report,
    )

    payload_files = _render_payload_files(
        bars_bytes=bars_bytes,
        expected_sessions=validated_expected_sessions,
        policy=validated_policy,
        provenance=provenance,
        quality_report=quality_report,
        manifest=manifest,
    )
    bundle_manifest = _build_bundle_manifest(
        snapshot_id=snapshot_id,
        semantic_content_hash=semantic_content_hash,
        policy_hash=policy_hash,
        expected_sessions_hash=expected_sessions_hash,
        provenance_hash=provenance_hash,
        payload_files=payload_files,
        row_count=len(bars),
    )
    bundle_manifest_bytes = render_contract_json(bundle_manifest)
    files = tuple(
        PlannedDailyMarketDataSnapshotFile(path, content)
        for path, content in (
            *payload_files,
            (DAILY_MARKET_DATA_BUNDLE_MANIFEST_PATH, bundle_manifest_bytes),
        )
    )

    return DailyMarketDataSnapshotPlan(
        snapshot_id=snapshot_id,
        manifest=manifest,
        quality_report=quality_report,
        policy_hash=policy_hash,
        expected_sessions_hash=expected_sessions_hash,
        provenance_hash=provenance_hash,
        bundle_manifest=bundle_manifest,
        files=files,
    )


def _build_provenance(
    *,
    provenance_input: DailyMarketDataSnapshotProvenanceInput,
    source_content_hash: str,
    source_size_bytes: int,
) -> DailyMarketDataSnapshotProvenance:
    if (
        provenance_input.corporate_action_evidence_status
        is not CorporateActionEvidenceStatus.NOT_INTEGRATED
    ):
        raise DailyMarketDataSnapshotPlanningError(
            "checked corporate-action evidence requires a future dedicated "
            "evidence input/contract and cannot be asserted by S3b1"
        )
    return DailyMarketDataSnapshotProvenance(
        schema_version=RESEARCH_SDK_CONTRACT_SCHEMA_VERSION,
        provenance_policy_version=PROVENANCE_POLICY_VERSION,
        created_at=provenance_input.created_at,
        created_by=provenance_input.created_by,
        source_dataset=provenance_input.source_dataset,
        source_version=provenance_input.source_version,
        source_type=provenance_input.source_type,
        source_reference=provenance_input.source_reference,
        source_content_hash=source_content_hash,
        source_size_bytes=source_size_bytes,
        parser_version=PARSER_VERSION,
        temporal_coverage=provenance_input.temporal_coverage,
        as_of=provenance_input.as_of,
        source_observed_at=provenance_input.source_observed_at,
        ingestion_completed_at=provenance_input.ingestion_completed_at,
        available_at=provenance_input.available_at,
        vendor_name=provenance_input.vendor_name,
        license_notes=provenance_input.license_notes,
        source_instrument_reference=provenance_input.source_instrument_reference,
        currency=provenance_input.currency,
        known_limitations=provenance_input.known_limitations,
        corporate_action_evidence_status=(
            provenance_input.corporate_action_evidence_status
        ),
        corporate_action_source_reference=(
            provenance_input.corporate_action_source_reference
        ),
        corporate_action_source_content_hash=(
            provenance_input.corporate_action_source_content_hash
        ),
        corporate_action_source_size_bytes=(
            provenance_input.corporate_action_source_size_bytes
        ),
        corporate_action_event_count=provenance_input.corporate_action_event_count,
    )


def _build_manifest(
    *,
    snapshot_id: str,
    instrument: DailyMarketDataInstrument,
    policy: DailyMarketDataPolicy,
    quality_report: DailyMarketDataQualityReport,
    provenance: DailyMarketDataSnapshotProvenance,
    bars_size_bytes: int,
) -> DataSnapshotManifest:
    return DataSnapshotManifest(
        schema_version=RESEARCH_SDK_CONTRACT_SCHEMA_VERSION,
        snapshot_id=snapshot_id,
        snapshot_kind=DataSnapshotKind.MARKET_DATA,
        status=DataSnapshotStatus.COMPLETED,
        created_at=provenance.created_at,
        created_by=provenance.created_by,
        asset_class=policy.asset_class,
        asset_universe=AssetUniverseReference(
            universe_id=f"daily-market-data-single-instrument-v1:{instrument.instrument_id}",
            symbols=(instrument.symbol,),
            as_of=provenance.as_of,
        ),
        time_range=TimeRange(
            start_date=quality_report.expected_start_date,
            end_date=quality_report.expected_end_date,
        ),
        frequency=policy.frequency,
        data_root_uri=f"{DATA_ROOT_URI_PREFIX}{snapshot_id}",
        source_dataset=provenance.source_dataset,
        source_version=provenance.source_version,
        source_type=provenance.source_type,
        temporal_coverage=provenance.temporal_coverage,
        as_of=provenance.as_of,
        available_at=provenance.available_at,
        ingestion_completed_at=provenance.ingestion_completed_at,
        adjustment_policy=policy.adjustment_policy,
        calendar=policy.calendar,
        timezone=policy.timezone,
        universe_membership_policy=policy.universe_membership_policy,
        corporate_action_policy=policy.corporate_action_policy,
        survivorship_policy=policy.survivorship_policy,
        delisting_policy=policy.delisting_policy,
        hash_algorithm=HashAlgorithm.SHA256,
        content_hash=quality_report.content_hash,
        row_count=quality_report.observed_session_count,
        known_limitations=provenance.known_limitations,
        vendor_name=provenance.vendor_name,
        license_notes=provenance.license_notes,
        source_observed_at=provenance.source_observed_at,
        currency=provenance.currency,
        rollover_policy=None,
        file_count=1,
        size_bytes=bars_size_bytes,
        adjustment_policy_notes=None,
        temporal_coverage_notes=None,
    )


def _render_payload_files(
    *,
    bars_bytes: bytes,
    expected_sessions: DailyMarketDataExpectedSessions,
    policy: DailyMarketDataPolicy,
    provenance: DailyMarketDataSnapshotProvenance,
    quality_report: DailyMarketDataQualityReport,
    manifest: DataSnapshotManifest,
) -> tuple[tuple[str, bytes], ...]:
    return (
        ("bars.jsonl", bars_bytes),
        ("expected-sessions.json", render_contract_json(expected_sessions)),
        ("policy.json", render_contract_json(policy)),
        ("provenance.json", render_contract_json(provenance)),
        ("quality-report.json", render_contract_json(quality_report)),
        ("snapshot-manifest.json", render_contract_json(manifest)),
    )


def _build_bundle_manifest(
    *,
    snapshot_id: str,
    semantic_content_hash: str,
    policy_hash: str,
    expected_sessions_hash: str,
    provenance_hash: str,
    payload_files: tuple[tuple[str, bytes], ...],
    row_count: int,
) -> DailyMarketDataSnapshotBundleManifest:
    file_entries: list[DailyMarketDataSnapshotFileEntry] = []
    payload_by_path = dict(payload_files)
    for role, relative_path, media_type in REQUIRED_DAILY_MARKET_DATA_SNAPSHOT_FILES:
        content = payload_by_path[relative_path]
        file_entries.append(
            DailyMarketDataSnapshotFileEntry(
                relative_path=relative_path,
                role=role,
                media_type=media_type,
                sha256=sha256_bytes(content),
                size_bytes=len(content),
                row_count=row_count if relative_path == "bars.jsonl" else None,
            )
        )
    return DailyMarketDataSnapshotBundleManifest(
        schema_version=RESEARCH_SDK_CONTRACT_SCHEMA_VERSION,
        bundle_format_version=BUNDLE_FORMAT_VERSION,
        snapshot_id=snapshot_id,
        semantic_content_hash=semantic_content_hash,
        policy_hash=policy_hash,
        expected_sessions_hash=expected_sessions_hash,
        provenance_hash=provenance_hash,
        files=tuple(file_entries),
    )


__all__ = [
    "BUNDLE_FORMAT_VERSION",
    "PARSER_VERSION",
    "PROVENANCE_POLICY_VERSION",
    "DailyMarketDataSnapshotPlan",
    "DailyMarketDataSnapshotPlanningError",
    "DailyMarketDataSnapshotProvenanceInput",
    "PlannedDailyMarketDataSnapshotFile",
    "plan_daily_market_data_snapshot",
]
