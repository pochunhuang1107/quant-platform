"""Pure in-memory verification for daily market-data snapshot bundles."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from research_sdk.contracts import BaseContractModel, DataSnapshotManifest
from research_sdk.contracts.daily_market_data import (
    DailyMarketDataPolicy,
    DailyMarketDataQualityReport,
)
from research_sdk.contracts.daily_market_data_snapshots import (
    DAILY_MARKET_DATA_BUNDLE_MANIFEST_PATH,
    DATA_ROOT_URI_PREFIX,
    REQUIRED_DAILY_MARKET_DATA_SNAPSHOT_FILES,
    DailyMarketDataExpectedSessions,
    DailyMarketDataSnapshotBundleManifest,
    DailyMarketDataSnapshotFileEntry,
    DailyMarketDataSnapshotFileRole,
    DailyMarketDataSnapshotProvenance,
)
from research_sdk.contracts.schema import RESEARCH_SDK_CONTRACT_SCHEMA_VERSION
from research_sdk.daily_market_data import (
    derive_daily_market_data_content_hash,
    evaluate_daily_market_data_quality,
    validate_daily_market_data_snapshot_manifest,
)
from research_sdk.daily_market_data.snapshot_identity import (
    derive_daily_market_data_expected_sessions_hash,
    derive_daily_market_data_policy_hash,
    derive_daily_market_data_provenance_hash,
    derive_daily_market_data_snapshot_id,
)
from research_sdk.daily_market_data_storage.planning import BUNDLE_FORMAT_VERSION
from research_sdk.daily_market_data_storage.serialization import (
    parse_canonical_daily_bars,
    parse_contract_json,
    render_canonical_daily_bars,
    render_contract_json,
    sha256_bytes,
)


class DailyMarketDataSnapshotVerificationError(ValueError):
    """Raised when an in-memory daily market-data bundle is incoherent."""


@dataclass(frozen=True)
class VerifiedDailyMarketDataSnapshot:
    """Verified immutable daily market-data snapshot facts."""

    snapshot_id: str
    manifest: DataSnapshotManifest
    quality_report: DailyMarketDataQualityReport
    policy: DailyMarketDataPolicy
    expected_sessions: DailyMarketDataExpectedSessions
    provenance: DailyMarketDataSnapshotProvenance
    bundle_manifest: DailyMarketDataSnapshotBundleManifest


def verify_daily_market_data_snapshot_bundle(
    files: Mapping[str, bytes],
) -> VerifiedDailyMarketDataSnapshot:
    """Verify an S3b1 daily market-data snapshot from in-memory bytes."""

    _require_exact_file_set(files)
    bundle_manifest = _parse_canonical_contract(
        files[DAILY_MARKET_DATA_BUNDLE_MANIFEST_PATH],
        DailyMarketDataSnapshotBundleManifest,
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
    provenance = _parse_canonical_contract(
        files["provenance.json"],
        DailyMarketDataSnapshotProvenance,
        "provenance.json",
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
    manifest = _parse_canonical_contract(
        files["snapshot-manifest.json"],
        DataSnapshotManifest,
        "snapshot-manifest.json",
    )

    policy_hash = derive_daily_market_data_policy_hash(policy)
    expected_sessions_hash = derive_daily_market_data_expected_sessions_hash(
        expected_sessions
    )
    provenance_hash = derive_daily_market_data_provenance_hash(provenance)
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
    validate_daily_market_data_snapshot_manifest(
        manifest=manifest,
        policy=policy,
        quality_report=quality_report,
    )
    _verify_s3b_manifest_boundary(
        manifest=manifest,
        quality_report=quality_report,
        provenance=provenance,
        bars_size_bytes=len(files["bars.jsonl"]),
    )

    snapshot_id = derive_daily_market_data_snapshot_id(
        semantic_content_hash=semantic_content_hash,
        policy_hash=policy_hash,
        expected_sessions_hash=expected_sessions_hash,
        provenance_hash=provenance_hash,
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
        bundle_manifest.provenance_hash == provenance_hash,
        "bundle provenance hash mismatch",
    )
    expected_bundle_manifest = _build_expected_bundle_manifest(
        files=files,
        snapshot_id=snapshot_id,
        semantic_content_hash=semantic_content_hash,
        policy_hash=policy_hash,
        expected_sessions_hash=expected_sessions_hash,
        provenance_hash=provenance_hash,
        row_count=len(bars),
    )
    _require(
        expected_bundle_manifest.model_dump(mode="json")
        == bundle_manifest.model_dump(mode="json"),
        "bundle-manifest.json must match payload file bytes",
    )

    return VerifiedDailyMarketDataSnapshot(
        snapshot_id=snapshot_id,
        manifest=manifest,
        quality_report=quality_report,
        policy=policy,
        expected_sessions=expected_sessions,
        provenance=provenance,
        bundle_manifest=bundle_manifest,
    )


def _require_exact_file_set(files: Mapping[str, bytes]) -> None:
    expected = {
        *(path for _, path, _ in REQUIRED_DAILY_MARKET_DATA_SNAPSHOT_FILES),
        DAILY_MARKET_DATA_BUNDLE_MANIFEST_PATH,
    }
    actual = set(files)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise DailyMarketDataSnapshotVerificationError(
            f"bundle file set mismatch; missing={missing}; unexpected={unexpected}"
        )
    for path, content in files.items():
        if type(path) is not str or type(content) is not bytes:
            raise DailyMarketDataSnapshotVerificationError(
                "bundle files must map string paths to bytes"
            )


def _verify_bundle_payload_file_entries(
    files: Mapping[str, bytes],
    bundle_manifest: DailyMarketDataSnapshotBundleManifest,
) -> None:
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


def _verify_s3b_manifest_boundary(
    *,
    manifest: DataSnapshotManifest,
    quality_report: DailyMarketDataQualityReport,
    provenance: DailyMarketDataSnapshotProvenance,
    bars_size_bytes: int,
) -> None:
    instrument = quality_report.instrument
    _require(
        manifest.asset_universe.universe_id
        == f"daily-market-data-single-instrument-v1:{instrument.instrument_id}",
        "manifest universe_id must use S3b1 single-instrument rule",
    )
    _require(
        manifest.asset_universe.as_of == provenance.as_of,
        "manifest universe as_of must match provenance as_of",
    )
    _require(
        manifest.currency == provenance.currency,
        "manifest currency must match provenance currency",
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
        manifest.known_limitations == provenance.known_limitations,
        "manifest limitations must match provenance limitations",
    )


def _build_expected_bundle_manifest(
    *,
    files: Mapping[str, bytes],
    snapshot_id: str,
    semantic_content_hash: str,
    policy_hash: str,
    expected_sessions_hash: str,
    provenance_hash: str,
    row_count: int,
) -> DailyMarketDataSnapshotBundleManifest:
    file_entries: list[DailyMarketDataSnapshotFileEntry] = []
    for role, relative_path, media_type in REQUIRED_DAILY_MARKET_DATA_SNAPSHOT_FILES:
        content = files[relative_path]
        file_entries.append(
            DailyMarketDataSnapshotFileEntry(
                relative_path=relative_path,
                role=role,
                media_type=media_type,
                sha256=sha256_bytes(content),
                size_bytes=len(content),
                row_count=(
                    row_count if role is DailyMarketDataSnapshotFileRole.BARS else None
                ),
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


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DailyMarketDataSnapshotVerificationError(message)


__all__ = [
    "DailyMarketDataSnapshotVerificationError",
    "VerifiedDailyMarketDataSnapshot",
    "verify_daily_market_data_snapshot_bundle",
]
