"""Pure in-memory verification for daily market-data snapshot-v2 bundles."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from research_sdk.contracts import BaseContractModel, DataSnapshotManifest
from research_sdk.contracts.daily_market_data import (
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
from research_sdk.contracts.schema import RESEARCH_SDK_CONTRACT_SCHEMA_VERSION
from research_sdk.daily_market_data import (
    derive_daily_market_data_content_hash,
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
    parse_contract_json,
    render_canonical_daily_bars,
    render_contract_json,
    sha256_bytes,
)


class DailyMarketDataSnapshotVerificationV2Error(ValueError):
    """Raised when an in-memory snapshot-v2 bundle is incoherent."""


@dataclass(frozen=True)
class VerifiedDailyMarketDataSnapshotV2:
    """Verified immutable daily market-data snapshot-v2 facts."""

    snapshot_id: str
    manifest: DataSnapshotManifest
    instrument_id: str
    policy: DailyMarketDataPolicy
    expected_sessions: DailyMarketDataExpectedSessions
    bar_provenance: DailyMarketDataBarSourceProvenanceV2
    quality_report: DailyMarketDataQualityReport
    corporate_action_evidence: DailyMarketDataCorporateActionEvidence
    semantic_content_hash: str
    policy_hash: str
    expected_sessions_hash: str
    bar_provenance_hash: str
    corporate_action_semantic_hash: str
    corporate_action_evidence_authority_hash: str
    bundle_manifest: DailyMarketDataSnapshotBundleManifestV2


def verify_daily_market_data_snapshot_bundle_v2(
    files: Mapping[str, bytes],
) -> VerifiedDailyMarketDataSnapshotV2:
    """Verify an S3c2a snapshot-v2 bundle from in-memory bytes."""

    _require_exact_file_set(files)
    bundle_manifest = _parse_canonical_contract(
        files[DAILY_MARKET_DATA_BUNDLE_MANIFEST_PATH],
        DailyMarketDataSnapshotBundleManifestV2,
        DAILY_MARKET_DATA_BUNDLE_MANIFEST_PATH,
    )
    _verify_bundle_payload_file_entries(files, bundle_manifest)

    policy = _parse_canonical_contract(
        files["policy.json"],
        DailyMarketDataPolicy,
        "policy.json",
    )
    expected_sessions = _parse_canonical_contract(
        files["expected-sessions.json"],
        DailyMarketDataExpectedSessions,
        "expected-sessions.json",
    )
    bar_provenance = _parse_canonical_contract(
        files["bar-provenance.json"],
        DailyMarketDataBarSourceProvenanceV2,
        "bar-provenance.json",
    )
    bars = parse_canonical_daily_bars(files["bars.jsonl"])
    _require(
        render_canonical_daily_bars(bars) == files["bars.jsonl"],
        "bars.jsonl must use canonical published JSONL bytes",
    )
    quality_report = _parse_canonical_contract(
        files["quality-report.json"],
        DailyMarketDataQualityReport,
        "quality-report.json",
    )
    corporate_action_evidence = _parse_canonical_contract(
        files["corporate-action-evidence.json"],
        DailyMarketDataCorporateActionEvidence,
        "corporate-action-evidence.json",
    )
    manifest = _parse_canonical_contract(
        files["snapshot-manifest.json"],
        DataSnapshotManifest,
        "snapshot-manifest.json",
    )

    _verify_policy_session_coherence(policy=policy, expected_sessions=expected_sessions)
    semantic_content_hash = derive_daily_market_data_content_hash(
        instrument=quality_report.instrument,
        bars=bars,
        canonicalization_version=policy.canonicalization_version,
    )
    rederived_quality_report = evaluate_daily_market_data_quality(
        instrument=quality_report.instrument,
        bars=bars,
        expected_session_dates=expected_sessions.session_dates,
        policy=policy,
    )
    _require(
        rederived_quality_report.model_dump(mode="json")
        == quality_report.model_dump(mode="json"),
        "quality-report.json must match rederived quality evidence",
    )
    _require(
        quality_report.status is DailyMarketDataQualityStatus.PASS,
        "quality-report.json must have pass status",
    )
    _verify_corporate_action_evidence_coherence(
        quality_report=quality_report,
        corporate_action_evidence=corporate_action_evidence,
    )
    validate_daily_market_data_snapshot_manifest(
        manifest=manifest,
        policy=policy,
        quality_report=quality_report,
    )
    _verify_v2_manifest_boundary(
        manifest=manifest,
        quality_report=quality_report,
        bar_provenance=bar_provenance,
        corporate_action_evidence=corporate_action_evidence,
        bars_size_bytes=len(files["bars.jsonl"]),
    )

    policy_hash = derive_daily_market_data_policy_hash(policy)
    expected_sessions_hash = derive_daily_market_data_expected_sessions_hash(
        expected_sessions
    )
    bar_provenance_hash = derive_daily_market_data_bar_source_provenance_hash_v2(
        bar_provenance
    )
    corporate_action_semantic_hash = (
        derive_daily_market_data_corporate_action_evidence_content_hash(
            corporate_action_evidence
        )
    )
    corporate_action_evidence_authority_hash = (
        derive_daily_market_data_corporate_action_evidence_authority_hash(
            corporate_action_evidence
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

    _require(bundle_manifest.snapshot_id == snapshot_id, "bundle snapshot_id mismatch")
    _require(manifest.snapshot_id == snapshot_id, "manifest snapshot_id mismatch")
    _require(
        bundle_manifest.semantic_content_hash == semantic_content_hash,
        "bundle semantic content hash mismatch",
    )
    _require(bundle_manifest.policy_hash == policy_hash, "bundle policy hash mismatch")
    _require(
        bundle_manifest.expected_sessions_hash == expected_sessions_hash,
        "bundle expected-sessions hash mismatch",
    )
    _require(
        bundle_manifest.bar_provenance_hash == bar_provenance_hash,
        "bundle bar provenance hash mismatch",
    )
    _require(
        bundle_manifest.corporate_action_semantic_hash
        == corporate_action_semantic_hash,
        "bundle corporate-action semantic hash mismatch",
    )
    _require(
        bundle_manifest.corporate_action_evidence_authority_hash
        == corporate_action_evidence_authority_hash,
        "bundle corporate-action evidence authority hash mismatch",
    )
    expected_bundle_manifest = _build_expected_bundle_manifest_v2(
        files=files,
        snapshot_id=snapshot_id,
        semantic_content_hash=semantic_content_hash,
        policy_hash=policy_hash,
        expected_sessions_hash=expected_sessions_hash,
        bar_provenance_hash=bar_provenance_hash,
        corporate_action_semantic_hash=corporate_action_semantic_hash,
        corporate_action_evidence_authority_hash=(
            corporate_action_evidence_authority_hash
        ),
        row_count=len(bars),
    )
    _require(
        expected_bundle_manifest.model_dump(mode="json")
        == bundle_manifest.model_dump(mode="json"),
        "bundle-manifest.json must match payload file bytes",
    )

    return VerifiedDailyMarketDataSnapshotV2(
        snapshot_id=snapshot_id,
        manifest=manifest,
        instrument_id=quality_report.instrument.instrument_id,
        policy=policy,
        expected_sessions=expected_sessions,
        bar_provenance=bar_provenance,
        quality_report=quality_report,
        corporate_action_evidence=corporate_action_evidence,
        semantic_content_hash=semantic_content_hash,
        policy_hash=policy_hash,
        expected_sessions_hash=expected_sessions_hash,
        bar_provenance_hash=bar_provenance_hash,
        corporate_action_semantic_hash=corporate_action_semantic_hash,
        corporate_action_evidence_authority_hash=(
            corporate_action_evidence_authority_hash
        ),
        bundle_manifest=bundle_manifest,
    )


def _require_exact_file_set(files: Mapping[str, bytes]) -> None:
    expected = {
        *(path for _, path, _ in REQUIRED_DAILY_MARKET_DATA_SNAPSHOT_FILES_V2),
        DAILY_MARKET_DATA_BUNDLE_MANIFEST_PATH,
    }
    actual = set(files)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise DailyMarketDataSnapshotVerificationV2Error(
            f"snapshot-v2 bundle file set mismatch; missing={missing}; "
            f"unexpected={unexpected}"
        )
    for path, content in files.items():
        if type(path) is not str or type(content) is not bytes:
            raise DailyMarketDataSnapshotVerificationV2Error(
                "bundle files must map string paths to bytes"
            )


def _verify_bundle_payload_file_entries(
    files: Mapping[str, bytes],
    bundle_manifest: DailyMarketDataSnapshotBundleManifestV2,
) -> None:
    _require(
        bundle_manifest.bundle_format_version == BUNDLE_FORMAT_VERSION_V2,
        "bundle format version must be snapshot-v2",
    )
    for entry in bundle_manifest.files:
        content = files[entry.relative_path]
        _require(
            entry.sha256 == sha256_bytes(content),
            f"{entry.relative_path} hash mismatch",
        )
        _require(
            entry.size_bytes == len(content),
            f"{entry.relative_path} size mismatch",
        )


def _parse_canonical_contract[ContractT: BaseContractModel](
    data: bytes,
    model: type[ContractT],
    relative_path: str,
) -> ContractT:
    parsed = parse_contract_json(data, model)
    _require(
        render_contract_json(parsed) == data,
        f"{relative_path} must use canonical JSON bytes",
    )
    return parsed


def _verify_policy_session_coherence(
    *,
    policy: DailyMarketDataPolicy,
    expected_sessions: DailyMarketDataExpectedSessions,
) -> None:
    _require(
        expected_sessions.calendar == policy.calendar,
        "expected sessions calendar must match policy",
    )
    _require(
        expected_sessions.timezone == policy.timezone,
        "expected sessions timezone must match policy",
    )


def _verify_corporate_action_evidence_coherence(
    *,
    quality_report: DailyMarketDataQualityReport,
    corporate_action_evidence: DailyMarketDataCorporateActionEvidence,
) -> None:
    _require(
        corporate_action_evidence.instrument.model_dump(mode="json")
        == quality_report.instrument.model_dump(mode="json"),
        "corporate-action evidence instrument must match bar instrument",
    )
    _require(
        corporate_action_evidence.coverage_start_date
        <= quality_report.expected_start_date
        and corporate_action_evidence.coverage_end_date
        >= quality_report.expected_end_date,
        "corporate-action evidence coverage must cover bar expected-session range",
    )


def _verify_v2_manifest_boundary(
    *,
    manifest: DataSnapshotManifest,
    quality_report: DailyMarketDataQualityReport,
    bar_provenance: DailyMarketDataBarSourceProvenanceV2,
    corporate_action_evidence: DailyMarketDataCorporateActionEvidence,
    bars_size_bytes: int,
) -> None:
    instrument = quality_report.instrument
    expected_ingestion_completed_at = max(
        bar_provenance.ingestion_completed_at,
        corporate_action_evidence.ingestion_completed_at,
    )
    expected_available_at = max(
        bar_provenance.available_at,
        corporate_action_evidence.available_at,
    )
    expected_created_at = max(
        bar_provenance.created_at,
        corporate_action_evidence.created_at,
    )
    expected_as_of = max(
        bar_provenance.as_of,
        corporate_action_evidence.source_observed_at,
    )
    expected_known_limitations = _merge_known_limitations(
        bar_provenance.known_limitations,
        corporate_action_evidence.known_limitations,
    )
    _require(
        manifest.asset_universe.universe_id
        == f"daily-market-data-single-instrument-v2:{instrument.instrument_id}",
        "manifest universe_id must use S3c2a single-instrument rule",
    )
    _require(
        manifest.asset_universe.as_of == expected_as_of,
        "manifest universe as_of must match combined snapshot-v2 as_of",
    )
    _require(
        manifest.ingestion_completed_at == expected_ingestion_completed_at,
        "manifest ingestion_completed_at must be combined component maximum",
    )
    _require(
        manifest.available_at == expected_available_at,
        "manifest available_at must be combined component maximum",
    )
    _require(
        manifest.created_at == expected_created_at,
        "manifest created_at must be combined component maximum",
    )
    _require(
        manifest.as_of == expected_as_of,
        "manifest as_of must be combined source-vintage cutoff",
    )
    _require(
        manifest.created_by == bar_provenance.created_by,
        "manifest created_by must remain bar-primary",
    )
    _require(
        manifest.source_dataset == bar_provenance.source_dataset,
        "manifest source_dataset must remain bar-primary",
    )
    _require(
        manifest.source_version == bar_provenance.source_version,
        "manifest source_version must remain bar-primary",
    )
    _require(
        manifest.source_type is bar_provenance.source_type,
        "manifest source_type must remain bar-primary",
    )
    _require(
        manifest.source_observed_at == bar_provenance.source_observed_at,
        "manifest source_observed_at must remain bar-primary",
    )
    _require(
        manifest.vendor_name == bar_provenance.vendor_name,
        "manifest vendor_name must remain bar-primary",
    )
    _require(
        manifest.license_notes == bar_provenance.license_notes,
        "manifest license_notes must remain bar-primary",
    )
    _require(
        manifest.currency == bar_provenance.currency,
        "manifest currency must match bar provenance currency",
    )
    _require(
        manifest.temporal_coverage is bar_provenance.temporal_coverage,
        "manifest temporal_coverage must remain bar-primary",
    )
    _require(manifest.file_count == 1, "manifest file_count must describe bars only")
    _require(
        manifest.size_bytes == bars_size_bytes,
        "manifest size_bytes must describe bars.jsonl only",
    )
    _require(
        manifest.data_root_uri == f"{DATA_ROOT_URI_PREFIX}{manifest.snapshot_id}",
        "manifest data_root_uri must be deterministic relative snapshot path",
    )
    _require(
        manifest.known_limitations == expected_known_limitations,
        "manifest limitations must be deterministic bar+corporate-action merge",
    )
    _require(
        quality_report.expected_end_date <= bar_provenance.as_of.date(),
        "quality expected_end_date must be on or before bar provenance as_of date",
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


def _build_expected_bundle_manifest_v2(
    *,
    files: Mapping[str, bytes],
    snapshot_id: str,
    semantic_content_hash: str,
    policy_hash: str,
    expected_sessions_hash: str,
    bar_provenance_hash: str,
    corporate_action_semantic_hash: str,
    corporate_action_evidence_authority_hash: str,
    row_count: int,
) -> DailyMarketDataSnapshotBundleManifestV2:
    file_entries: list[DailyMarketDataSnapshotFileEntryV2] = []
    for role, relative_path, media_type in REQUIRED_DAILY_MARKET_DATA_SNAPSHOT_FILES_V2:
        content = files[relative_path]
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


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DailyMarketDataSnapshotVerificationV2Error(message)


__all__ = [
    "DailyMarketDataSnapshotVerificationV2Error",
    "VerifiedDailyMarketDataSnapshotV2",
    "verify_daily_market_data_snapshot_bundle_v2",
]
