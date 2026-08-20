"""Pure in-memory planning for immutable daily market-data snapshot-v2 bundles."""

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
from research_sdk.contracts.daily_market_data_economics import (
    DailyMarketDataCorporateActionEvidence,
)
from research_sdk.contracts.daily_market_data_snapshots import (
    DAILY_MARKET_DATA_BUNDLE_MANIFEST_PATH,
    DATA_ROOT_URI_PREFIX,
    DailyMarketDataExpectedSessions,
)
from research_sdk.contracts.daily_market_data_snapshots_v2 import (
    BUNDLE_FORMAT_VERSION_V2,
    REQUIRED_DAILY_MARKET_DATA_SNAPSHOT_FILES_V2,
    DailyMarketDataBarSourceProvenanceV2,
    DailyMarketDataSnapshotBundleManifestV2,
    DailyMarketDataSnapshotFileEntryV2,
    DailyMarketDataSnapshotFileRoleV2,
)
from research_sdk.contracts.enums import DataSourceType, TemporalCoverage
from research_sdk.contracts.schema import RESEARCH_SDK_CONTRACT_SCHEMA_VERSION
from research_sdk.daily_market_data import (
    derive_daily_market_data_corporate_action_evidence_content_hash,
    evaluate_daily_market_data_quality,
    validate_daily_market_data_snapshot_manifest,
)
from research_sdk.daily_market_data.snapshot_identity import (
    derive_daily_market_data_expected_sessions_hash,
    derive_daily_market_data_policy_hash,
)
from research_sdk.daily_market_data.snapshot_identity_v2 import (
    derive_daily_market_data_bar_source_provenance_hash_v2,
    derive_daily_market_data_corporate_action_evidence_authority_hash,
    derive_daily_market_data_snapshot_id_v2,
)
from research_sdk.daily_market_data_storage.serialization import (
    parse_canonical_daily_bars,
    render_canonical_daily_bars,
    render_contract_json,
    sha256_bytes,
)

BAR_PROVENANCE_POLICY_VERSION = "daily-market-data-bar-source-provenance-v1"
BAR_PARSER_VERSION = "daily-market-data-jsonl-parser-v1"


class DailyMarketDataSnapshotPlanningV2Error(ValueError):
    """Raised when a daily market-data snapshot-v2 cannot be planned."""


@dataclass(frozen=True)
class DailyMarketDataBarSourceAuthorityInputV2:
    """Exact upstream bar-source bytes and their parser authority."""

    content: bytes
    parser_version: str


@dataclass(frozen=True)
class DailyMarketDataBarSourceProvenanceInputV2:
    """Caller-supplied bar-source facts whose byte hash/size are derived."""

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


@dataclass(frozen=True)
class PlannedDailyMarketDataSnapshotFileV2:
    """Immutable planned file bytes for an S3c2a in-memory bundle."""

    relative_path: str
    content: bytes


@dataclass(frozen=True)
class DailyMarketDataSnapshotPlanV2:
    """Pure in-memory snapshot-v2 plan with final deterministic bytes."""

    snapshot_id: str
    manifest: DataSnapshotManifest
    quality_report: DailyMarketDataQualityReport
    policy_hash: str
    expected_sessions_hash: str
    bar_provenance_hash: str
    corporate_action_semantic_hash: str
    corporate_action_evidence_authority_hash: str
    bar_provenance: DailyMarketDataBarSourceProvenanceV2
    corporate_action_evidence: DailyMarketDataCorporateActionEvidence
    bundle_manifest: DailyMarketDataSnapshotBundleManifestV2
    files: tuple[PlannedDailyMarketDataSnapshotFileV2, ...]

    def as_file_map(self) -> dict[str, bytes]:
        """Return a detached filename-to-bytes mapping for verification tests."""

        return {
            planned_file.relative_path: planned_file.content
            for planned_file in self.files
        }


def plan_daily_market_data_snapshot_v2(
    *,
    source_bytes: bytes,
    bar_source_authority: DailyMarketDataBarSourceAuthorityInputV2 | None = None,
    instrument: DailyMarketDataInstrument,
    policy: DailyMarketDataPolicy,
    expected_sessions: DailyMarketDataExpectedSessions,
    bar_provenance_input: DailyMarketDataBarSourceProvenanceInputV2,
    corporate_action_evidence: DailyMarketDataCorporateActionEvidence,
) -> DailyMarketDataSnapshotPlanV2:
    """Build a deterministic in-memory immutable snapshot-v2 plan."""

    if type(source_bytes) is not bytes:
        raise DailyMarketDataSnapshotPlanningV2Error("source_bytes must be bytes")
    source_authority_content, source_parser_version = _resolve_bar_source_authority(
        source_bytes=source_bytes,
        bar_source_authority=bar_source_authority,
    )

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
        raise DailyMarketDataSnapshotPlanningV2Error(
            "expected sessions calendar must match policy"
        )
    if validated_expected_sessions.timezone != validated_policy.timezone:
        raise DailyMarketDataSnapshotPlanningV2Error(
            "expected sessions timezone must match policy"
        )

    bars = parse_canonical_daily_bars(source_bytes)
    bar_provenance = _build_bar_provenance(
        bar_provenance_input=bar_provenance_input,
        source_content_hash=sha256_bytes(source_authority_content),
        source_size_bytes=len(source_authority_content),
        parser_version=source_parser_version,
    )
    validated_corporate_action_evidence = (
        DailyMarketDataCorporateActionEvidence.model_validate(
            corporate_action_evidence.model_dump(mode="json")
        )
    )

    quality_report = evaluate_daily_market_data_quality(
        instrument=validated_instrument,
        bars=bars,
        expected_session_dates=validated_expected_sessions.session_dates,
        policy=validated_policy,
    )
    if quality_report.status is not DailyMarketDataQualityStatus.PASS:
        raise DailyMarketDataSnapshotPlanningV2Error(
            "daily market-data quality must pass before snapshot-v2 planning"
        )
    if quality_report.expected_end_date > bar_provenance.as_of.date():
        raise DailyMarketDataSnapshotPlanningV2Error(
            "quality expected_end_date must be on or before bar provenance as_of date"
        )
    _validate_corporate_action_evidence_coherence(
        quality_report=quality_report,
        corporate_action_evidence=validated_corporate_action_evidence,
    )

    semantic_content_hash = quality_report.content_hash
    policy_hash = derive_daily_market_data_policy_hash(validated_policy)
    expected_sessions_hash = derive_daily_market_data_expected_sessions_hash(
        validated_expected_sessions
    )
    bar_provenance_hash = derive_daily_market_data_bar_source_provenance_hash_v2(
        bar_provenance
    )
    corporate_action_semantic_hash = (
        derive_daily_market_data_corporate_action_evidence_content_hash(
            validated_corporate_action_evidence
        )
    )
    corporate_action_evidence_authority_hash = (
        derive_daily_market_data_corporate_action_evidence_authority_hash(
            validated_corporate_action_evidence
        )
    )
    snapshot_id = derive_daily_market_data_snapshot_id_v2(
        semantic_content_hash=semantic_content_hash,
        policy_hash=policy_hash,
        expected_sessions_hash=expected_sessions_hash,
        bar_provenance_hash=bar_provenance_hash,
        corporate_action_semantic_hash=corporate_action_semantic_hash,
        corporate_action_evidence_authority_hash=(
            corporate_action_evidence_authority_hash
        ),
    )

    bars_bytes = render_canonical_daily_bars(bars)
    manifest = _build_manifest_v2(
        snapshot_id=snapshot_id,
        instrument=validated_instrument,
        policy=validated_policy,
        quality_report=quality_report,
        bar_provenance=bar_provenance,
        corporate_action_evidence=validated_corporate_action_evidence,
        bars_size_bytes=len(bars_bytes),
    )
    validate_daily_market_data_snapshot_manifest(
        manifest=manifest,
        policy=validated_policy,
        quality_report=quality_report,
    )

    payload_files = _render_payload_files_v2(
        bars_bytes=bars_bytes,
        expected_sessions=validated_expected_sessions,
        policy=validated_policy,
        bar_provenance=bar_provenance,
        quality_report=quality_report,
        corporate_action_evidence=validated_corporate_action_evidence,
        manifest=manifest,
    )
    bundle_manifest = _build_bundle_manifest_v2(
        snapshot_id=snapshot_id,
        semantic_content_hash=semantic_content_hash,
        policy_hash=policy_hash,
        expected_sessions_hash=expected_sessions_hash,
        bar_provenance_hash=bar_provenance_hash,
        corporate_action_semantic_hash=corporate_action_semantic_hash,
        corporate_action_evidence_authority_hash=(
            corporate_action_evidence_authority_hash
        ),
        payload_files=payload_files,
        row_count=len(bars),
    )
    bundle_manifest_bytes = render_contract_json(bundle_manifest)
    files = tuple(
        PlannedDailyMarketDataSnapshotFileV2(path, content)
        for path, content in (
            *payload_files,
            (DAILY_MARKET_DATA_BUNDLE_MANIFEST_PATH, bundle_manifest_bytes),
        )
    )

    return DailyMarketDataSnapshotPlanV2(
        snapshot_id=snapshot_id,
        manifest=manifest,
        quality_report=quality_report,
        policy_hash=policy_hash,
        expected_sessions_hash=expected_sessions_hash,
        bar_provenance_hash=bar_provenance_hash,
        corporate_action_semantic_hash=corporate_action_semantic_hash,
        corporate_action_evidence_authority_hash=(
            corporate_action_evidence_authority_hash
        ),
        bar_provenance=bar_provenance,
        corporate_action_evidence=validated_corporate_action_evidence,
        bundle_manifest=bundle_manifest,
        files=files,
    )


def _resolve_bar_source_authority(
    *,
    source_bytes: bytes,
    bar_source_authority: DailyMarketDataBarSourceAuthorityInputV2 | None,
) -> tuple[bytes, str]:
    if bar_source_authority is None:
        return source_bytes, BAR_PARSER_VERSION
    if not isinstance(bar_source_authority, DailyMarketDataBarSourceAuthorityInputV2):
        raise DailyMarketDataSnapshotPlanningV2Error(
            "bar_source_authority must be "
            "DailyMarketDataBarSourceAuthorityInputV2 or None"
        )
    content = bar_source_authority.content
    if type(content) is not bytes:
        raise DailyMarketDataSnapshotPlanningV2Error(
            "bar_source_authority content must be bytes"
        )
    parser_version = bar_source_authority.parser_version
    if (
        type(parser_version) is not str
        or not parser_version.strip()
        or parser_version != parser_version.strip()
    ):
        raise DailyMarketDataSnapshotPlanningV2Error(
            "bar_source_authority parser_version must be a non-empty string "
            "without surrounding whitespace"
        )
    return content, parser_version


def _build_bar_provenance(
    *,
    bar_provenance_input: DailyMarketDataBarSourceProvenanceInputV2,
    source_content_hash: str,
    source_size_bytes: int,
    parser_version: str,
) -> DailyMarketDataBarSourceProvenanceV2:
    return DailyMarketDataBarSourceProvenanceV2(
        schema_version=RESEARCH_SDK_CONTRACT_SCHEMA_VERSION,
        provenance_policy_version=BAR_PROVENANCE_POLICY_VERSION,
        created_at=bar_provenance_input.created_at,
        created_by=bar_provenance_input.created_by,
        source_dataset=bar_provenance_input.source_dataset,
        source_version=bar_provenance_input.source_version,
        source_type=bar_provenance_input.source_type,
        source_reference=bar_provenance_input.source_reference,
        source_content_hash=source_content_hash,
        source_size_bytes=source_size_bytes,
        parser_version=parser_version,
        temporal_coverage=bar_provenance_input.temporal_coverage,
        as_of=bar_provenance_input.as_of,
        source_observed_at=bar_provenance_input.source_observed_at,
        ingestion_completed_at=bar_provenance_input.ingestion_completed_at,
        available_at=bar_provenance_input.available_at,
        vendor_name=bar_provenance_input.vendor_name,
        license_notes=bar_provenance_input.license_notes,
        source_instrument_reference=(bar_provenance_input.source_instrument_reference),
        currency=bar_provenance_input.currency,
        known_limitations=bar_provenance_input.known_limitations,
    )


def _validate_corporate_action_evidence_coherence(
    *,
    quality_report: DailyMarketDataQualityReport,
    corporate_action_evidence: DailyMarketDataCorporateActionEvidence,
) -> None:
    if corporate_action_evidence.instrument.model_dump(
        mode="json"
    ) != quality_report.instrument.model_dump(mode="json"):
        raise DailyMarketDataSnapshotPlanningV2Error(
            "corporate-action evidence instrument must match bar instrument"
        )
    if (
        corporate_action_evidence.coverage_start_date
        > quality_report.expected_start_date
        or corporate_action_evidence.coverage_end_date
        < quality_report.expected_end_date
    ):
        raise DailyMarketDataSnapshotPlanningV2Error(
            "corporate-action evidence coverage must cover bar expected-session range"
        )


def _build_manifest_v2(
    *,
    snapshot_id: str,
    instrument: DailyMarketDataInstrument,
    policy: DailyMarketDataPolicy,
    quality_report: DailyMarketDataQualityReport,
    bar_provenance: DailyMarketDataBarSourceProvenanceV2,
    corporate_action_evidence: DailyMarketDataCorporateActionEvidence,
    bars_size_bytes: int,
) -> DataSnapshotManifest:
    ingestion_completed_at = max(
        bar_provenance.ingestion_completed_at,
        corporate_action_evidence.ingestion_completed_at,
    )
    available_at = max(
        bar_provenance.available_at, corporate_action_evidence.available_at
    )
    created_at = max(bar_provenance.created_at, corporate_action_evidence.created_at)
    as_of = max(bar_provenance.as_of, corporate_action_evidence.source_observed_at)
    known_limitations = _merge_known_limitations(
        bar_provenance.known_limitations,
        corporate_action_evidence.known_limitations,
    )
    return DataSnapshotManifest(
        schema_version=RESEARCH_SDK_CONTRACT_SCHEMA_VERSION,
        snapshot_id=snapshot_id,
        snapshot_kind=DataSnapshotKind.MARKET_DATA,
        status=DataSnapshotStatus.COMPLETED,
        created_at=created_at,
        created_by=bar_provenance.created_by,
        asset_class=policy.asset_class,
        asset_universe=AssetUniverseReference(
            universe_id=(
                f"daily-market-data-single-instrument-v2:{instrument.instrument_id}"
            ),
            symbols=(instrument.symbol,),
            as_of=as_of,
        ),
        time_range=TimeRange(
            start_date=quality_report.expected_start_date,
            end_date=quality_report.expected_end_date,
        ),
        frequency=policy.frequency,
        data_root_uri=f"{DATA_ROOT_URI_PREFIX}{snapshot_id}",
        source_dataset=bar_provenance.source_dataset,
        source_version=bar_provenance.source_version,
        source_type=bar_provenance.source_type,
        temporal_coverage=bar_provenance.temporal_coverage,
        as_of=as_of,
        available_at=available_at,
        ingestion_completed_at=ingestion_completed_at,
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
        known_limitations=known_limitations,
        vendor_name=bar_provenance.vendor_name,
        license_notes=bar_provenance.license_notes,
        source_observed_at=bar_provenance.source_observed_at,
        currency=bar_provenance.currency,
        rollover_policy=None,
        file_count=1,
        size_bytes=bars_size_bytes,
        adjustment_policy_notes=None,
        temporal_coverage_notes=None,
    )


def _merge_known_limitations(
    bar_limitations: tuple[str, ...],
    corporate_action_limitations: tuple[str, ...],
) -> tuple[str, ...]:
    merged: list[str] = []
    seen: set[str] = set()
    for limitation in (*bar_limitations, *corporate_action_limitations):
        if limitation not in seen:
            merged.append(limitation)
            seen.add(limitation)
    return tuple(merged)


def _render_payload_files_v2(
    *,
    bars_bytes: bytes,
    expected_sessions: DailyMarketDataExpectedSessions,
    policy: DailyMarketDataPolicy,
    bar_provenance: DailyMarketDataBarSourceProvenanceV2,
    quality_report: DailyMarketDataQualityReport,
    corporate_action_evidence: DailyMarketDataCorporateActionEvidence,
    manifest: DataSnapshotManifest,
) -> tuple[tuple[str, bytes], ...]:
    return (
        ("bars.jsonl", bars_bytes),
        ("expected-sessions.json", render_contract_json(expected_sessions)),
        ("policy.json", render_contract_json(policy)),
        ("bar-provenance.json", render_contract_json(bar_provenance)),
        ("quality-report.json", render_contract_json(quality_report)),
        (
            "corporate-action-evidence.json",
            render_contract_json(corporate_action_evidence),
        ),
        ("snapshot-manifest.json", render_contract_json(manifest)),
    )


def _build_bundle_manifest_v2(
    *,
    snapshot_id: str,
    semantic_content_hash: str,
    policy_hash: str,
    expected_sessions_hash: str,
    bar_provenance_hash: str,
    corporate_action_semantic_hash: str,
    corporate_action_evidence_authority_hash: str,
    payload_files: tuple[tuple[str, bytes], ...],
    row_count: int,
) -> DailyMarketDataSnapshotBundleManifestV2:
    file_entries: list[DailyMarketDataSnapshotFileEntryV2] = []
    payload_by_path = dict(payload_files)
    for role, relative_path, media_type in REQUIRED_DAILY_MARKET_DATA_SNAPSHOT_FILES_V2:
        content = payload_by_path[relative_path]
        file_entries.append(
            DailyMarketDataSnapshotFileEntryV2(
                relative_path=relative_path,
                role=role,
                media_type=media_type,
                sha256=sha256_bytes(content),
                size_bytes=len(content),
                row_count=(
                    row_count
                    if role is DailyMarketDataSnapshotFileRoleV2.BARS
                    else None
                ),
            )
        )
    return DailyMarketDataSnapshotBundleManifestV2(
        schema_version=RESEARCH_SDK_CONTRACT_SCHEMA_VERSION,
        bundle_format_version=BUNDLE_FORMAT_VERSION_V2,
        snapshot_id=snapshot_id,
        semantic_content_hash=semantic_content_hash,
        policy_hash=policy_hash,
        expected_sessions_hash=expected_sessions_hash,
        bar_provenance_hash=bar_provenance_hash,
        corporate_action_semantic_hash=corporate_action_semantic_hash,
        corporate_action_evidence_authority_hash=(
            corporate_action_evidence_authority_hash
        ),
        files=tuple(file_entries),
    )


__all__ = [
    "BAR_PARSER_VERSION",
    "BAR_PROVENANCE_POLICY_VERSION",
    "DailyMarketDataBarSourceAuthorityInputV2",
    "DailyMarketDataBarSourceProvenanceInputV2",
    "DailyMarketDataSnapshotPlanV2",
    "DailyMarketDataSnapshotPlanningV2Error",
    "PlannedDailyMarketDataSnapshotFileV2",
    "plan_daily_market_data_snapshot_v2",
]
