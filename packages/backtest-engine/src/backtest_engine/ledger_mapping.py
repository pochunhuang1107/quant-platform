"""Map deterministic backtest outputs into completed experiment ledger contracts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from backtest_engine.artifacts import serialize_artifact_manifest
from backtest_engine.identity import (
    RUN_ID_PREFIX,
    canonical_json_bytes,
    canonical_json_sha256,
    file_sha256_bytes,
    identity_from_completed_result,
    validate_run_id_contract_compatibility,
)
from backtest_engine.market_data import snapshot_from_payload
from backtest_engine.models import (
    CompletedBacktestResult,
    DailyBarSnapshot,
    GeneratedArtifactBundle,
)
from research_sdk.contracts import (
    ArtifactKind,
    ArtifactStatus,
    AssetClass,
    AssetUniverseReference,
    BenchmarkReference,
    DataAdjustmentPolicy,
    DataSnapshotKind,
    DataSnapshotManifest,
    DataSnapshotStatus,
    DataSourceType,
    ExperimentRunRecord,
    ExperimentRunStatus,
    HashAlgorithm,
    RandomSeedMetadata,
    ReviewMetadata,
    RunArtifactEntry,
    RunArtifactManifest,
    RunEnvironment,
    TemporalCoverage,
    TimeRange,
)
from research_sdk.contracts.artifacts import REQUIRED_ARTIFACT_SPECS
from research_sdk.contracts.schema import RESEARCH_SDK_CONTRACT_SCHEMA_VERSION

SHA256_CONTENT_HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
COST_MODEL_DESCRIPTION = (
    "QQQ commission is {commission_bps} basis points on executed notional; "
    "SPY benchmark is gross with no commission"
)
SLIPPAGE_MODEL_DESCRIPTION = (
    "QQQ buy slippage is {slippage_bps} basis points on the first aligned open; "
    "SPY benchmark is gross with no slippage"
)
LOOKBACK_DESCRIPTION = "no lookback; unconditional initial allocation"
LAG_ASSUMPTIONS_DESCRIPTION = (
    "order sizing uses only the first aligned QQQ open; same-session close is "
    "used only for valuation; no future observation is used"
)
LEAKAGE_REVIEW_DESCRIPTION = (
    "synthetic fixture-only data; unconditional initial purchase; first aligned "
    "session open execution; no same-day close used for sizing; same-day close "
    "used only for valuation; no future bars; no indicators; no training data; "
    "no parameter fitting; no survivorship claim; no corporate actions; exact "
    "QQQ/SPY aligned-session requirement; SPY gross benchmark"
)
DATA_SNAPSHOT_TEMPORAL_COVERAGE_NOTES = (
    "point-in-time refers only to the synthetic fixture's logical availability "
    "timestamp and is not a historical vendor PIT claim"
)
DATA_SNAPSHOT_ADJUSTMENT_POLICY_NOTES = (
    "fixture declares adjustment_policy none; prices are unadjusted synthetic "
    "raw fixture values with no splits or dividends"
)
DATA_SNAPSHOT_KNOWN_LIMITATIONS = (
    "synthetic fixture-only data",
    "not historical market data",
    "not vendor or production data",
    "no corporate actions",
    "supplied sessions only",
    "no performance claim",
)


class BacktestLedgerMappingError(ValueError):
    """Raised when deterministic backtest output cannot be mapped."""


class DirtyBacktestLineageError(BacktestLedgerMappingError):
    """Raised when injected execution metadata marks the repository dirty."""


class GeneratedArtifactBundleVerificationError(BacktestLedgerMappingError):
    """Raised when generated artifact files do not match their manifest metadata."""


@dataclass(frozen=True)
class CompletedBacktestLedgerMappingInput:
    """Inputs needed to map one completed deterministic backtest to ledger contracts."""

    result: CompletedBacktestResult
    artifacts: GeneratedArtifactBundle
    fixture_path: Path
    created_by: str
    review: ReviewMetadata


@dataclass(frozen=True)
class CompletedBacktestLedgerRecords:
    """Pure mapped ledger records for one completed deterministic backtest."""

    snapshot: DataSnapshotManifest
    run: ExperimentRunRecord
    manifest_id: str
    artifact_manifest: RunArtifactManifest


@dataclass(frozen=True)
class _VerifiedArtifacts:
    manifest: RunArtifactManifest
    config_entry: RunArtifactEntry
    metrics_entry: RunArtifactEntry


def map_completed_backtest_to_ledger_records(
    mapping_input: CompletedBacktestLedgerMappingInput,
) -> CompletedBacktestLedgerRecords:
    """Build pure ledger records from deterministic backtest outputs."""

    result = mapping_input.result
    if result.execution_metadata.repo_dirty:
        raise DirtyBacktestLineageError(
            "dirty repository state cannot be recorded as a completed backtest"
        )
    _verify_completed_result_identity(result)

    try:
        fixture, fixture_hash, fixture_path, fixture_size_bytes = (
            _load_and_verify_fixture(mapping_input)
        )
        verified_artifacts = _verify_generated_artifact_bundle(
            result=result,
            artifacts=mapping_input.artifacts,
        )
        snapshot = _build_data_snapshot_manifest(
            mapping_input=mapping_input,
            fixture=fixture,
            fixture_hash=fixture_hash,
            fixture_path=fixture_path,
            fixture_size_bytes=fixture_size_bytes,
        )
        run = _build_experiment_run_record(
            mapping_input=mapping_input,
            artifacts=mapping_input.artifacts,
            verified_artifacts=verified_artifacts,
        )
        return CompletedBacktestLedgerRecords(
            snapshot=snapshot,
            run=run,
            manifest_id=mapping_input.artifacts.manifest_id,
            artifact_manifest=verified_artifacts.manifest,
        )
    except BacktestLedgerMappingError:
        raise
    except Exception as exc:
        raise BacktestLedgerMappingError(
            "completed backtest could not be mapped to ledger contracts"
        ) from exc


def verify_generated_artifact_bundle(
    *,
    result: CompletedBacktestResult,
    artifacts: GeneratedArtifactBundle,
) -> RunArtifactManifest:
    """Read and verify generated artifact metadata, returning the parsed manifest."""

    _verify_completed_result_identity(result)
    return _verify_generated_artifact_bundle(
        result=result,
        artifacts=artifacts,
    ).manifest


def _load_and_verify_fixture(
    mapping_input: CompletedBacktestLedgerMappingInput,
) -> tuple[DailyBarSnapshot, str, Path, int]:
    fixture_path = mapping_input.fixture_path
    result = mapping_input.result
    config = result.resolved_config

    if not fixture_path.is_file():
        raise BacktestLedgerMappingError("fixture_path must be a regular file")

    resolved_fixture_path = fixture_path.resolve()
    try:
        fixture_bytes = resolved_fixture_path.read_bytes()
        fixture_payload = json.loads(fixture_bytes.decode("utf-8"))
        fixture = snapshot_from_payload(fixture_payload)
    except Exception as exc:
        raise BacktestLedgerMappingError("fixture could not be loaded") from exc

    fixture_hash = file_sha256_bytes(fixture_bytes)
    fixture_size_bytes = len(fixture_bytes)
    expected_id = fixture.snapshot_id
    identity_values = {
        "fixture.snapshot_id": fixture.snapshot_id,
        "result.input_snapshot_id": result.input_snapshot_id,
        "config.data_snapshot_id": config.data_snapshot_id,
        "config.benchmark_snapshot_id": config.benchmark_snapshot_id,
    }
    if len(set(identity_values.values())) != 1:
        details = ", ".join(
            f"{name}={value}" for name, value in identity_values.items()
        )
        raise BacktestLedgerMappingError(
            f"fixture, result, data, and benchmark snapshot identities must match: "
            f"{details}"
        )

    if fixture_hash != result.fixture_content_hash:
        raise BacktestLedgerMappingError(
            "fixture byte SHA-256 must match result.fixture_content_hash"
        )
    if config.asset_symbol != "QQQ":
        raise BacktestLedgerMappingError("config asset_symbol must be QQQ")
    if config.benchmark_symbol != "SPY":
        raise BacktestLedgerMappingError("config benchmark_symbol must be SPY")
    if {bar.symbol for bar in fixture.bars} != {"QQQ", "SPY"}:
        raise BacktestLedgerMappingError("fixture must contain exactly QQQ and SPY")
    if result.input_snapshot_id != expected_id:
        raise BacktestLedgerMappingError("result input snapshot does not match fixture")

    return fixture, fixture_hash, resolved_fixture_path, fixture_size_bytes


def _verify_generated_artifact_bundle(
    *,
    result: CompletedBacktestResult,
    artifacts: GeneratedArtifactBundle,
) -> _VerifiedArtifacts:
    try:
        return _verify_generated_artifact_bundle_inner(
            result=result,
            artifacts=artifacts,
        )
    except GeneratedArtifactBundleVerificationError:
        raise
    except Exception as exc:
        raise GeneratedArtifactBundleVerificationError(
            "generated artifact bundle could not be verified"
        ) from exc


def _verify_generated_artifact_bundle_inner(
    *,
    result: CompletedBacktestResult,
    artifacts: GeneratedArtifactBundle,
) -> _VerifiedArtifacts:
    config = result.resolved_config

    root_path = Path(artifacts.artifact_root_path)
    if root_path.is_symlink():
        _artifact_error("artifact root must not be a symlink")
    root = root_path.resolve()
    if not root.is_dir():
        _artifact_error("artifact_root_path must resolve to an existing directory")
    if root.name != result.run_id:
        _artifact_error("artifact root directory name must equal run_id")
    if artifacts.artifact_root_uri != root.as_uri():
        _artifact_error("artifact_root_uri must match resolved artifact root")

    manifest_path = Path(artifacts.artifact_manifest_path)
    if manifest_path.is_symlink():
        _artifact_error("artifact_manifest_path must not be a symlink")
    manifest_resolved = manifest_path.resolve()
    expected_manifest_path = root / "artifact_manifest.json"
    if manifest_resolved != expected_manifest_path:
        _artifact_error("artifact_manifest_path must be under artifact root")
    if artifacts.artifact_manifest_uri != manifest_resolved.as_uri():
        _artifact_error("artifact_manifest_uri must match resolved manifest path")
    if not manifest_resolved.is_file():
        _artifact_error("artifact_manifest.json must exist as a regular file")

    _verify_write_order(artifacts)
    _verify_manifest_id(result=result, artifacts=artifacts)

    manifest_bytes = manifest_resolved.read_bytes()
    _require_sha256_content_hash(
        artifacts.artifact_manifest_hash,
        "artifact_manifest_hash",
    )
    expected_manifest_hash = f"sha256:{file_sha256_bytes(manifest_bytes)}"
    if artifacts.artifact_manifest_hash != expected_manifest_hash:
        _artifact_error(
            "artifact_manifest_hash must match artifact_manifest.json bytes"
        )

    try:
        parsed_manifest = RunArtifactManifest.model_validate(
            json.loads(manifest_bytes.decode("utf-8"))
        )
    except Exception as exc:
        raise GeneratedArtifactBundleVerificationError(
            "artifact_manifest.json must parse as RunArtifactManifest"
        ) from exc

    if serialize_artifact_manifest(parsed_manifest) != manifest_bytes:
        _artifact_error("artifact_manifest.json must use canonical manifest bytes")
    if not isinstance(artifacts.run_artifact_manifest, RunArtifactManifest):
        _artifact_error("run_artifact_manifest must be a RunArtifactManifest")
    if parsed_manifest != artifacts.run_artifact_manifest:
        _artifact_error("parsed manifest must match in-memory artifact manifest")
    if parsed_manifest.run_id != result.run_id:
        _artifact_error("manifest run_id must match result run_id")
    if parsed_manifest.experiment_id != config.experiment_id:
        _artifact_error("manifest experiment_id must match config experiment_id")
    if parsed_manifest.artifact_root_uri != artifacts.artifact_root_uri:
        _artifact_error("manifest artifact_root_uri must match artifact bundle root")
    if not parsed_manifest.required_artifacts_complete:
        _artifact_error("artifact manifest must declare complete required artifacts")
    if any(
        entry.filename == "artifact_manifest.json"
        for entry in parsed_manifest.artifacts
    ):
        _artifact_error("artifact_manifest.json must not be an artifact entry")

    config_entry, metrics_entry = _verify_payloads(
        result=result,
        root=root,
        artifacts=artifacts,
        manifest=parsed_manifest,
    )
    return _VerifiedArtifacts(
        manifest=parsed_manifest,
        config_entry=config_entry,
        metrics_entry=metrics_entry,
    )


def _verify_completed_result_identity(result: CompletedBacktestResult) -> None:
    try:
        validate_run_id_contract_compatibility(result.run_id)
    except Exception as exc:
        raise BacktestLedgerMappingError(
            "completed backtest result identity could not be verified"
        ) from exc

    expected_run_id = f"{RUN_ID_PREFIX}{result.full_execution_identity_digest}"
    if result.run_id != expected_run_id:
        raise BacktestLedgerMappingError(
            "completed backtest result identity is stale or inconsistent"
        )

    try:
        recomputed_digest, recomputed_run_id = identity_from_completed_result(result)
    except Exception as exc:
        raise BacktestLedgerMappingError(
            "completed backtest result identity could not be verified"
        ) from exc

    if (
        recomputed_digest != result.full_execution_identity_digest
        or recomputed_run_id != result.run_id
    ):
        raise BacktestLedgerMappingError(
            "completed backtest result identity is stale or inconsistent"
        )


def _verify_write_order(artifacts: GeneratedArtifactBundle) -> None:
    required_payload_filenames = _required_payload_filenames()
    expected_members = set(required_payload_filenames) | {"artifact_manifest.json"}
    if artifacts.write_order[-1:] != ("artifact_manifest.json",):
        _artifact_error("artifact_manifest.json must be final write_order item")
    if set(artifacts.write_order) != expected_members:
        _artifact_error(
            "write_order must contain exactly required payloads and manifest"
        )
    for filename in expected_members:
        if artifacts.write_order.count(filename) != 1:
            _artifact_error("write_order filenames must be unique")


def _verify_manifest_id(
    *,
    result: CompletedBacktestResult,
    artifacts: GeneratedArtifactBundle,
) -> None:
    digest = result.full_execution_identity_digest
    expected_manifest_id = f"manifest-{digest}"
    if artifacts.manifest_id != expected_manifest_id:
        _artifact_error("manifest_id must be derived from full execution digest")
    if artifacts.manifest_id != f"manifest-{result.run_id.removeprefix(RUN_ID_PREFIX)}":
        _artifact_error("manifest_id must be derived from run_id suffix")


def _verify_payloads(
    *,
    result: CompletedBacktestResult,
    root: Path,
    artifacts: GeneratedArtifactBundle,
    manifest: RunArtifactManifest,
) -> tuple[RunArtifactEntry, RunArtifactEntry]:
    required_kinds = set(REQUIRED_ARTIFACT_SPECS)
    manifest_entries_by_id = {entry.artifact_id: entry for entry in manifest.artifacts}
    metadata_by_id = {
        metadata.artifact_id: metadata for metadata in artifacts.payload_artifacts
    }
    if len(manifest_entries_by_id) != len(manifest.artifacts):
        _artifact_error("artifact IDs in manifest must be unique")
    if len(metadata_by_id) != len(artifacts.payload_artifacts):
        _artifact_error("payload artifact metadata IDs must be unique")
    if set(manifest_entries_by_id) != set(metadata_by_id):
        _artifact_error("payload metadata and manifest entries must match one-to-one")
    if len(manifest.artifacts) != len(required_kinds):
        _artifact_error("artifact manifest must contain exactly required artifacts")
    if {entry.artifact_kind for entry in manifest.artifacts} != required_kinds:
        _artifact_error(
            "artifact manifest must contain each required kind exactly once"
        )

    config_entry: RunArtifactEntry | None = None
    metrics_entry: RunArtifactEntry | None = None
    for artifact_id, entry in manifest_entries_by_id.items():
        metadata = metadata_by_id[artifact_id]
        if entry.artifact_kind is ArtifactKind.CONFIG:
            config_entry = entry
        if entry.artifact_kind is ArtifactKind.METRICS:
            metrics_entry = entry
        _verify_payload_entry(root=root, metadata=metadata, entry=entry)

    if config_entry is None:
        _artifact_error("config artifact entry is required")
    if metrics_entry is None:
        _artifact_error("metrics artifact entry is required")
    _verify_config_json_semantics(root=root, result=result, entry=config_entry)
    _verify_metrics_json_semantics(root=root, result=result, entry=metrics_entry)
    return config_entry, metrics_entry


def _verify_payload_entry(
    *,
    root: Path,
    metadata: object,
    entry: RunArtifactEntry,
) -> None:
    path = Path(getattr(metadata, "path"))
    if path.is_symlink():
        _artifact_error("payload artifact path must not be a symlink")
    resolved = path.resolve()
    if resolved.parent != root:
        _artifact_error("payload artifact path must resolve directly under root")
    if not resolved.is_file():
        _artifact_error("payload artifact must exist as a regular file")
    if getattr(metadata, "uri") != resolved.as_uri():
        _artifact_error("payload metadata URI must match resolved file URI")
    if entry.uri != resolved.as_uri():
        _artifact_error("manifest entry URI must match resolved file URI")
    if (
        entry.filename != resolved.name
        or getattr(metadata, "filename") != resolved.name
    ):
        _artifact_error("payload filename must agree across metadata and manifest")
    if entry.artifact_id != getattr(metadata, "artifact_id"):
        _artifact_error("payload artifact ID must agree across metadata and manifest")
    if entry.artifact_kind.value != getattr(metadata, "artifact_kind"):
        _artifact_error("payload artifact kind must agree across metadata and manifest")
    if entry.format.value != getattr(metadata, "format"):
        _artifact_error(
            "payload artifact format must agree across metadata and manifest"
        )
    if entry.status is not ArtifactStatus.PRODUCED:
        _artifact_error("payload artifact status must be produced")
    if entry.hash_algorithm is not HashAlgorithm.SHA256:
        _artifact_error("payload artifact hash algorithm must be SHA256")

    content = resolved.read_bytes()
    expected_hash = f"sha256:{file_sha256_bytes(content)}"
    _require_sha256_content_hash(expected_hash, "payload content hash")
    if (
        entry.content_hash != expected_hash
        or getattr(metadata, "content_hash") != expected_hash
    ):
        _artifact_error("payload artifact content hash must match file bytes")
    if entry.size_bytes != len(content) or getattr(metadata, "size_bytes") != len(
        content
    ):
        _artifact_error("payload artifact size must match file bytes")
    if entry.row_count != getattr(metadata, "row_count"):
        _artifact_error("payload row_count must agree across metadata and manifest")
    if entry.created_at != getattr(metadata, "created_at"):
        _artifact_error("payload created_at must agree across metadata and manifest")
    if entry.validator_version != getattr(metadata, "validator_version"):
        _artifact_error(
            "payload validator_version must agree across metadata and manifest"
        )


def _verify_config_json_semantics(
    *,
    root: Path,
    result: CompletedBacktestResult,
    entry: RunArtifactEntry,
) -> None:
    config_bytes = (root / entry.filename).read_bytes()
    expected_bytes = canonical_json_bytes(
        {
            "run_id": result.run_id,
            "full_execution_identity_digest": result.full_execution_identity_digest,
            "resolved_config": result.resolved_config,
            "execution_metadata": result.execution_metadata,
            "input_fixture_content_hash": result.fixture_content_hash,
            "execution_assumptions": {
                "strategy": "unconditional QQQ buy-and-hold",
                "execution_price_field": "open",
                "valuation_price_field": "close",
                "share_policy": "integer",
                "benchmark": "gross SPY normalized from first aligned open",
            },
            "leakage_assumptions": result.leakage_assumptions,
        }
    )
    if config_bytes != expected_bytes:
        _artifact_error("config.json must semantically match completed result")


def _verify_metrics_json_semantics(
    *,
    root: Path,
    result: CompletedBacktestResult,
    entry: RunArtifactEntry,
) -> None:
    metrics_bytes = (root / entry.filename).read_bytes()
    if metrics_bytes != canonical_json_bytes(result.metrics):
        _artifact_error("metrics.json must semantically match completed result")


def _build_data_snapshot_manifest(
    *,
    mapping_input: CompletedBacktestLedgerMappingInput,
    fixture: DailyBarSnapshot,
    fixture_hash: str,
    fixture_path: Path,
    fixture_size_bytes: int,
) -> DataSnapshotManifest:
    bars = fixture.bars
    dates = [bar.trading_date for bar in bars]
    return DataSnapshotManifest(
        schema_version=RESEARCH_SDK_CONTRACT_SCHEMA_VERSION,
        snapshot_id=fixture.snapshot_id,
        snapshot_kind=DataSnapshotKind.MARKET_DATA,
        status=DataSnapshotStatus.COMPLETED,
        created_at=fixture.logical_available_at,
        created_by=mapping_input.created_by,
        asset_class=AssetClass.ETFS,
        asset_universe=AssetUniverseReference(
            symbols=("QQQ", "SPY"),
            as_of=fixture.logical_available_at,
        ),
        time_range=TimeRange(start_date=min(dates), end_date=max(dates)),
        frequency=mapping_input.result.resolved_config.frequency,
        data_root_uri=fixture_path.as_uri(),
        source_dataset=fixture.source_dataset,
        source_version=fixture.fixture_version,
        source_type=DataSourceType.RESEARCH_GENERATED,
        temporal_coverage=TemporalCoverage.POINT_IN_TIME,
        temporal_coverage_notes=DATA_SNAPSHOT_TEMPORAL_COVERAGE_NOTES,
        as_of=fixture.logical_available_at,
        available_at=fixture.logical_available_at,
        ingestion_completed_at=fixture.logical_available_at,
        source_observed_at=None,
        adjustment_policy=DataAdjustmentPolicy.RAW,
        adjustment_policy_notes=DATA_SNAPSHOT_ADJUSTMENT_POLICY_NOTES,
        calendar="supplied-fixture-sessions-only",
        timezone=fixture.timezone,
        currency=fixture.currency,
        universe_membership_policy=(
            "fixed synthetic QQQ/SPY membership supplied by the fixture"
        ),
        corporate_action_policy=(
            "no splits, dividends, or corporate actions are modeled"
        ),
        survivorship_policy="not applicable to the fixed synthetic fixture",
        delisting_policy="not applicable to the fixed synthetic fixture",
        rollover_policy=None,
        hash_algorithm=HashAlgorithm.SHA256,
        content_hash=f"sha256:{fixture_hash}",
        row_count=len(bars),
        file_count=1,
        size_bytes=fixture_size_bytes,
        vendor_name=None,
        license_notes=None,
        known_limitations=DATA_SNAPSHOT_KNOWN_LIMITATIONS,
    )


def _build_experiment_run_record(
    *,
    mapping_input: CompletedBacktestLedgerMappingInput,
    artifacts: GeneratedArtifactBundle,
    verified_artifacts: _VerifiedArtifacts,
) -> ExperimentRunRecord:
    result = mapping_input.result
    config = result.resolved_config
    execution_metadata = result.execution_metadata
    metrics = result.metrics
    config_entry = verified_artifacts.config_entry

    return ExperimentRunRecord(
        schema_version=RESEARCH_SDK_CONTRACT_SCHEMA_VERSION,
        run_id=result.run_id,
        experiment_id=config.experiment_id,
        created_at=config.logical_execution_at,
        created_by=mapping_input.created_by,
        status=ExperimentRunStatus.COMPLETED,
        status_updated_at=config.logical_execution_at,
        status_updated_by=mapping_input.created_by,
        strategy_id=config.strategy_id,
        strategy_version=config.strategy_version,
        git_commit_sha=execution_metadata.git_commit_sha,
        repo_dirty=False,
        asset_class=AssetClass.ETFS,
        asset_universe=AssetUniverseReference(
            symbols=("QQQ",),
            as_of=config.logical_execution_at,
        ),
        time_range=TimeRange(start_date=config.start_date, end_date=config.end_date),
        frequency=config.frequency,
        benchmark=BenchmarkReference(
            benchmark_id="SPY-gross-normalized",
            snapshot_id=config.benchmark_snapshot_id,
        ),
        data_snapshot_id=config.data_snapshot_id,
        config_uri=config_entry.uri,
        config_hash=_required_content_hash(config_entry.content_hash, "config_hash"),
        artifact_uri=artifacts.artifact_root_uri,
        artifact_manifest_uri=artifacts.artifact_manifest_uri,
        artifact_manifest_hash=artifacts.artifact_manifest_hash,
        cost_model=COST_MODEL_DESCRIPTION.format(
            commission_bps=format(config.commission.bps, "f")
        ),
        slippage_model=SLIPPAGE_MODEL_DESCRIPTION.format(
            slippage_bps=format(config.slippage.bps, "f")
        ),
        lookback=LOOKBACK_DESCRIPTION,
        lag_assumptions=LAG_ASSUMPTIONS_DESCRIPTION,
        leakage_review=LEAKAGE_REVIEW_DESCRIPTION,
        environment=RunEnvironment(
            python_version=execution_metadata.python_version,
            platform=execution_metadata.platform,
            runner="backtest_engine.deterministic_etf",
            container_image_digest=None,
        ),
        dependency_lock_hash=execution_metadata.dependency_lock_hash,
        execution_command=execution_metadata.execution_command,
        engine_version=config.engine_version,
        random_seed=RandomSeedMetadata(
            seed=None,
            rationale=config.no_randomness_reason,
        ),
        parameter_hash=f"sha256:{canonical_json_sha256(config)}",
        metrics_summary={
            "total_return": format(metrics.total_return, "f"),
            "benchmark_total_return": format(metrics.benchmark_total_return, "f"),
            "excess_return": format(metrics.excess_return, "f"),
            "maximum_drawdown": format(metrics.maximum_drawdown, "f"),
            "realized_commission": format(metrics.realized_commission, "f"),
            "realized_slippage": format(metrics.realized_slippage, "f"),
            "ending_equity": format(metrics.ending_equity, "f"),
            "number_of_trades": metrics.number_of_trades,
            "observation_count": metrics.observation_count,
        },
        review=mapping_input.review,
        feature_snapshot_id=None,
        parent_run_id=None,
        supersedes_run_id=None,
        failure_labels=(),
        failure_reason=None,
        failure_logs_uri=None,
        artifacts_incomplete=False,
    )


def _required_payload_filenames() -> tuple[str, ...]:
    return tuple(
        filename for filename, _artifact_format in REQUIRED_ARTIFACT_SPECS.values()
    )


def _required_content_hash(value: str | None, field_name: str) -> str:
    if value is None:
        raise BacktestLedgerMappingError(f"{field_name} must be present")
    _require_sha256_content_hash(value, field_name)
    return value


def _require_sha256_content_hash(value: str, field_name: str) -> None:
    if SHA256_CONTENT_HASH_PATTERN.fullmatch(value) is None:
        raise GeneratedArtifactBundleVerificationError(
            f"{field_name} must use sha256:<64 lowercase hex> format"
        )


def _artifact_error(message: str) -> NoReturn:
    raise GeneratedArtifactBundleVerificationError(message)


__all__ = [
    "BacktestLedgerMappingError",
    "COST_MODEL_DESCRIPTION",
    "CompletedBacktestLedgerMappingInput",
    "CompletedBacktestLedgerRecords",
    "DATA_SNAPSHOT_ADJUSTMENT_POLICY_NOTES",
    "DATA_SNAPSHOT_KNOWN_LIMITATIONS",
    "DATA_SNAPSHOT_TEMPORAL_COVERAGE_NOTES",
    "DirtyBacktestLineageError",
    "GeneratedArtifactBundleVerificationError",
    "LAG_ASSUMPTIONS_DESCRIPTION",
    "LEAKAGE_REVIEW_DESCRIPTION",
    "LOOKBACK_DESCRIPTION",
    "SLIPPAGE_MODEL_DESCRIPTION",
    "map_completed_backtest_to_ledger_records",
    "verify_generated_artifact_bundle",
]
