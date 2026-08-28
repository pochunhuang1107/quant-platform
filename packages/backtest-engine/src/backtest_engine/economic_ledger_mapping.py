"""Pair-aware ledger mapping for completed economic snapshot-v2 backtests."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import NoReturn

from backtest_engine.economic_artifacts import (
    EconomicArtifactSemanticPayload,
    build_economic_artifact_semantic_payloads,
)
from backtest_engine.economic_execution_models import (
    ECONOMIC_ARTIFACT_VALIDATOR_VERSION,
    CompletedEconomicBacktestResult,
    deterministic_artifact_created_at,
)
from backtest_engine.economic_identity import identity_from_completed_economic_result
from backtest_engine.economic_result_validation import (
    canonicalize_completed_economic_backtest_result,
)
from backtest_engine.identity import (
    RUN_ID_PREFIX,
    canonical_json_bytes,
    canonical_json_sha256,
    file_sha256_bytes,
    validate_run_id_contract_compatibility,
)
from backtest_engine.models import GeneratedArtifactBundle
from research_sdk.contracts import (
    ArtifactKind,
    ArtifactStatus,
    AssetClass,
    AssetUniverseReference,
    BenchmarkReference,
    DataSnapshotManifest,
    ExperimentRunRecord,
    ExperimentRunStatus,
    HashAlgorithm,
    RandomSeedMetadata,
    ReviewMetadata,
    RunArtifactEntry,
    RunArtifactManifest,
    RunEnvironment,
    TimeRange,
)
from research_sdk.contracts.artifacts import REQUIRED_ARTIFACT_SPECS
from research_sdk.contracts.schema import RESEARCH_SDK_CONTRACT_SCHEMA_VERSION

ECONOMIC_COST_MODEL_DESCRIPTION = (
    "QQQ commission is {commission_bps} basis points on executed notional; "
    "explicit corporate-action accounting has no transaction cost; SPY benchmark "
    "has zero commission"
)
ECONOMIC_SLIPPAGE_MODEL_DESCRIPTION = (
    "QQQ buy slippage is {slippage_bps} basis points on first-session raw open; "
    "corporate actions have no slippage; SPY benchmark has zero slippage"
)
ECONOMIC_LOOKBACK_DESCRIPTION = (
    "no lookback; pre-run unconditional QQQ initial allocation"
)
ECONOMIC_LAG_DESCRIPTION = (
    "pre-run decision executes at first supplied raw open; complete bar T is not "
    "visible for a decision on T; a future T-1 bar-driven decision could execute "
    "no earlier than T open"
)
ECONOMIC_LEAKAGE_REVIEW_DESCRIPTION = (
    "NEXT_EXPECTED_SESSION timing; pre-run unconditional allocation observes no "
    "complete bars; corporate-action evidence is accounting-only; exact QQQ/SPY "
    "session equality with no repair or intersection; LATEST_KNOWN evidence is not "
    "point-in-time strategy knowledge"
)
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class EconomicLedgerMappingError(ValueError):
    """Raised when economic output cannot be mapped without losing authority."""


class EconomicArtifactBundleVerificationError(EconomicLedgerMappingError):
    """Raised when economic artifact files and manifest are inconsistent."""


@dataclass(frozen=True)
class CompletedEconomicBacktestLedgerMappingInput:
    """Inputs for one pure pair-aware economic ledger mapping."""

    result: CompletedEconomicBacktestResult
    artifacts: GeneratedArtifactBundle
    created_by: str
    review: ReviewMetadata


@dataclass(frozen=True)
class CompletedEconomicBacktestLedgerRecords:
    """Mapped records retaining distinct QQQ and SPY snapshot authority."""

    asset_snapshot: DataSnapshotManifest
    benchmark_snapshot: DataSnapshotManifest
    run: ExperimentRunRecord
    manifest_id: str
    artifact_manifest: RunArtifactManifest


def map_completed_economic_backtest_to_ledger_records(
    mapping_input: CompletedEconomicBacktestLedgerMappingInput,
) -> CompletedEconomicBacktestLedgerRecords:
    """Verify artifacts and build a distinct-snapshot recording bundle."""

    result = canonicalize_completed_economic_backtest_result(mapping_input.result)
    canonical_input = CompletedEconomicBacktestLedgerMappingInput(
        result=result,
        artifacts=mapping_input.artifacts,
        created_by=mapping_input.created_by,
        review=mapping_input.review,
    )
    if result.execution_metadata.repo_dirty:
        raise EconomicLedgerMappingError(
            "dirty repository state cannot be recorded as a completed backtest"
        )
    _verify_result_identity(result)
    manifest, config_entry = verify_economic_artifact_bundle(
        result=result,
        artifacts=mapping_input.artifacts,
    )
    run = _build_run(
        mapping_input=canonical_input,
        config_entry=config_entry,
    )
    return CompletedEconomicBacktestLedgerRecords(
        asset_snapshot=result.market_data_lineage.asset.data_snapshot_manifest,
        benchmark_snapshot=(
            result.market_data_lineage.benchmark.data_snapshot_manifest
        ),
        run=run,
        manifest_id=mapping_input.artifacts.manifest_id,
        artifact_manifest=manifest,
    )


def verify_economic_artifact_bundle(
    *,
    result: CompletedEconomicBacktestResult,
    artifacts: GeneratedArtifactBundle,
) -> tuple[RunArtifactManifest, RunArtifactEntry]:
    """Read and verify economic payloads against manifest and completed result."""

    canonical_result = canonicalize_completed_economic_backtest_result(result)
    _verify_result_identity(canonical_result)
    try:
        return _verify_economic_artifact_bundle_inner(
            result=canonical_result,
            artifacts=artifacts,
        )
    except EconomicArtifactBundleVerificationError:
        raise
    except Exception as exc:
        raise EconomicArtifactBundleVerificationError(
            "economic artifact bundle could not be verified"
        ) from exc


def _verify_economic_artifact_bundle_inner(
    *,
    result: CompletedEconomicBacktestResult,
    artifacts: GeneratedArtifactBundle,
) -> tuple[RunArtifactManifest, RunArtifactEntry]:
    root_path = Path(artifacts.artifact_root_path)
    if root_path.is_symlink():
        _artifact_error("artifact root must not be a symlink")
    root = root_path.resolve()
    if not root.is_dir() or root.name != result.run_id:
        _artifact_error("artifact root must be an existing run_id directory")
    if artifacts.artifact_root_uri != root.as_uri():
        _artifact_error("artifact root URI must match resolved artifact root")

    manifest_path = Path(artifacts.artifact_manifest_path)
    if manifest_path.is_symlink():
        _artifact_error("artifact manifest must not be a symlink")
    resolved_manifest_path = manifest_path.resolve()
    if resolved_manifest_path != root / "artifact_manifest.json":
        _artifact_error("artifact manifest must be directly under artifact root")
    if artifacts.artifact_manifest_uri != resolved_manifest_path.as_uri():
        _artifact_error("artifact manifest URI must match resolved path")
    if not resolved_manifest_path.is_file():
        _artifact_error("artifact_manifest.json must exist")

    expected_manifest_id = f"manifest-{result.full_execution_identity_digest}"
    if artifacts.manifest_id != expected_manifest_id:
        _artifact_error("manifest_id must derive from economic execution identity")
    payload_filenames = tuple(item.filename for item in artifacts.payload_artifacts)
    if artifacts.write_order != payload_filenames + ("artifact_manifest.json",):
        _artifact_error("write_order must match payload metadata and end with manifest")
    semantic_payloads = build_economic_artifact_semantic_payloads(result)
    expected_artifact_ids = tuple(payload.artifact_id for payload in semantic_payloads)
    expected_by_id = {payload.artifact_id: payload for payload in semantic_payloads}
    expected_filenames = {payload.filename for payload in semantic_payloads}
    if set(payload_filenames) != expected_filenames or len(payload_filenames) != len(
        expected_filenames
    ):
        _artifact_error("economic payload set must be exact and complete")

    manifest_bytes = resolved_manifest_path.read_bytes()
    expected_manifest_hash = f"sha256:{file_sha256_bytes(manifest_bytes)}"
    if artifacts.artifact_manifest_hash != expected_manifest_hash:
        _artifact_error("artifact manifest hash must match file bytes")
    _require_sha256(artifacts.artifact_manifest_hash, "artifact_manifest_hash")
    parsed_manifest = RunArtifactManifest.model_validate(
        json.loads(manifest_bytes.decode("utf-8"))
    )
    if canonical_json_bytes(parsed_manifest) != manifest_bytes:
        _artifact_error("artifact manifest must use canonical JSON bytes")
    if parsed_manifest != artifacts.run_artifact_manifest:
        _artifact_error("parsed and in-memory artifact manifests must match")
    if (
        parsed_manifest.run_id != result.run_id
        or parsed_manifest.experiment_id != result.resolved_config.experiment_id
        or parsed_manifest.artifact_root_uri != artifacts.artifact_root_uri
    ):
        _artifact_error("artifact manifest identity must match completed result")
    if not parsed_manifest.required_artifacts_complete:
        _artifact_error("artifact manifest must declare complete required artifacts")
    expected_created_at = deterministic_artifact_created_at(result.market_data_lineage)
    if parsed_manifest.created_at != expected_created_at:
        _artifact_error("artifact manifest time must derive from input authority")
    if (
        tuple(item.artifact_id for item in artifacts.payload_artifacts)
        != expected_artifact_ids
        or tuple(entry.artifact_id for entry in parsed_manifest.artifacts)
        != expected_artifact_ids
    ):
        _artifact_error("economic artifacts must use canonical deterministic order")

    entries_by_id = {entry.artifact_id: entry for entry in parsed_manifest.artifacts}
    metadata_by_id = {item.artifact_id: item for item in artifacts.payload_artifacts}
    if (
        len(entries_by_id) != len(parsed_manifest.artifacts)
        or set(entries_by_id) != set(metadata_by_id)
        or set(entries_by_id) != set(expected_by_id)
    ):
        _artifact_error(
            "manifest, payload metadata, and semantic payloads must match one-to-one"
        )
    if (
        sum(
            entry.artifact_kind is ArtifactKind.DIAGNOSTIC
            for entry in parsed_manifest.artifacts
        )
        != 1
    ):
        _artifact_error("one economic corporate-action diagnostic is required")
    required_kinds = set(REQUIRED_ARTIFACT_SPECS)
    if not required_kinds <= {
        entry.artifact_kind for entry in parsed_manifest.artifacts
    }:
        _artifact_error("all required artifact kinds must be present")

    config_entry: RunArtifactEntry | None = None
    metrics_entry: RunArtifactEntry | None = None
    for artifact_id, entry in entries_by_id.items():
        metadata = metadata_by_id[artifact_id]
        _verify_payload_file(
            root=root,
            entry=entry,
            metadata=metadata,
            expected=expected_by_id[artifact_id],
            expected_created_at=expected_created_at,
        )
        if entry.artifact_kind is ArtifactKind.CONFIG:
            config_entry = entry
        elif entry.artifact_kind is ArtifactKind.METRICS:
            metrics_entry = entry
    if config_entry is None or metrics_entry is None:
        _artifact_error("config and metrics artifacts are required")
    return parsed_manifest, config_entry


def _verify_payload_file(
    *,
    root: Path,
    entry: RunArtifactEntry,
    metadata: object,
    expected: EconomicArtifactSemanticPayload,
    expected_created_at: datetime,
) -> None:
    path = Path(getattr(metadata, "path"))
    if path.is_symlink():
        _artifact_error("payload artifact must not be a symlink")
    resolved = path.resolve()
    if resolved.parent != root or not resolved.is_file():
        _artifact_error("payload artifact must be a regular file under run root")
    if entry.uri != resolved.as_uri() or getattr(metadata, "uri") != resolved.as_uri():
        _artifact_error("payload URIs must match resolved file")
    if (
        entry.filename != resolved.name
        or getattr(metadata, "filename") != resolved.name
    ):
        _artifact_error("payload filenames must agree")
    if entry.artifact_kind.value != getattr(metadata, "artifact_kind"):
        _artifact_error("payload artifact kinds must agree")
    if entry.format.value != getattr(metadata, "format"):
        _artifact_error("payload formats must agree")
    if entry.status is not ArtifactStatus.PRODUCED:
        _artifact_error("payload status must be produced")
    if entry.hash_algorithm is not HashAlgorithm.SHA256:
        _artifact_error("payload hash algorithm must be SHA256")
    content = resolved.read_bytes()
    if (
        entry.artifact_id != expected.artifact_id
        or entry.filename != expected.filename
        or entry.artifact_kind is not expected.artifact_kind
        or entry.format is not expected.artifact_format
        or entry.row_count != expected.row_count
        or getattr(metadata, "artifact_id") != expected.artifact_id
        or getattr(metadata, "filename") != expected.filename
        or getattr(metadata, "artifact_kind") != expected.artifact_kind.value
        or getattr(metadata, "format") != expected.artifact_format.value
        or getattr(metadata, "row_count") != expected.row_count
    ):
        _artifact_error("payload metadata must match semantic artifact authority")
    if content != expected.content:
        _artifact_error(f"semantic artifact mismatch: {expected.filename}")
    expected_hash = f"sha256:{file_sha256_bytes(content)}"
    if (
        entry.content_hash != expected_hash
        or getattr(metadata, "content_hash") != expected_hash
    ):
        _artifact_error("payload hashes must match bytes")
    if entry.size_bytes != len(content) or getattr(metadata, "size_bytes") != len(
        content
    ):
        _artifact_error("payload sizes must match bytes")
    if entry.row_count != getattr(metadata, "row_count"):
        _artifact_error("payload row counts must agree")
    if (
        entry.created_at != expected_created_at
        or getattr(metadata, "created_at") != expected_created_at
    ):
        _artifact_error("payload time must derive from input authority")
    if (
        entry.validator_version != ECONOMIC_ARTIFACT_VALIDATOR_VERSION
        or getattr(metadata, "validator_version") != ECONOMIC_ARTIFACT_VALIDATOR_VERSION
    ):
        _artifact_error("payload validator version must match economic writer")


def _verify_result_identity(result: CompletedEconomicBacktestResult) -> None:
    try:
        validate_run_id_contract_compatibility(result.run_id)
        digest, run_id = identity_from_completed_economic_result(result)
    except Exception as exc:
        raise EconomicLedgerMappingError(
            "completed economic result identity could not be verified"
        ) from exc
    if (
        result.run_id != f"{RUN_ID_PREFIX}{result.full_execution_identity_digest}"
        or digest != result.full_execution_identity_digest
        or run_id != result.run_id
    ):
        raise EconomicLedgerMappingError(
            "completed economic result identity is stale or inconsistent"
        )


def _build_run(
    *,
    mapping_input: CompletedEconomicBacktestLedgerMappingInput,
    config_entry: RunArtifactEntry,
) -> ExperimentRunRecord:
    result = mapping_input.result
    config = result.resolved_config
    metadata = result.execution_metadata
    lineage = result.market_data_lineage
    created_at = deterministic_artifact_created_at(lineage)
    artifacts = mapping_input.artifacts
    metrics = result.metrics
    return ExperimentRunRecord(
        schema_version=RESEARCH_SDK_CONTRACT_SCHEMA_VERSION,
        run_id=result.run_id,
        experiment_id=config.experiment_id,
        created_at=created_at,
        created_by=mapping_input.created_by,
        status=ExperimentRunStatus.COMPLETED,
        status_updated_at=created_at,
        status_updated_by=mapping_input.created_by,
        strategy_id=config.strategy_id,
        strategy_version=config.strategy_version,
        git_commit_sha=metadata.git_commit_sha,
        repo_dirty=False,
        asset_class=AssetClass.ETFS,
        asset_universe=AssetUniverseReference(symbols=("QQQ",), as_of=created_at),
        time_range=TimeRange(start_date=config.start_date, end_date=config.end_date),
        frequency=config.frequency,
        benchmark=BenchmarkReference(
            benchmark_id="SPY-gross-economic-raw-explicit-cash-v1",
            snapshot_id=lineage.benchmark.snapshot_id,
        ),
        data_snapshot_id=lineage.asset.snapshot_id,
        config_uri=config_entry.uri,
        config_hash=_required_hash(config_entry.content_hash, "config_hash"),
        artifact_uri=artifacts.artifact_root_uri,
        artifact_manifest_uri=artifacts.artifact_manifest_uri,
        artifact_manifest_hash=artifacts.artifact_manifest_hash,
        cost_model=ECONOMIC_COST_MODEL_DESCRIPTION.format(
            commission_bps=format(config.commission.bps, "f")
        ),
        slippage_model=ECONOMIC_SLIPPAGE_MODEL_DESCRIPTION.format(
            slippage_bps=format(config.slippage.bps, "f")
        ),
        lookback=ECONOMIC_LOOKBACK_DESCRIPTION,
        lag_assumptions=ECONOMIC_LAG_DESCRIPTION,
        leakage_review=ECONOMIC_LEAKAGE_REVIEW_DESCRIPTION,
        environment=RunEnvironment(
            python_version=metadata.python_version,
            platform=metadata.platform,
            runner="backtest_engine.snapshot_v2_economic_buy_and_hold",
            container_image_digest=None,
        ),
        dependency_lock_hash=metadata.dependency_lock_hash,
        execution_command=metadata.execution_command,
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


def _required_hash(value: str | None, field_name: str) -> str:
    if value is None:
        raise EconomicLedgerMappingError(f"{field_name} must be present")
    _require_sha256(value, field_name)
    return value


def _require_sha256(value: str, field_name: str) -> None:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise EconomicArtifactBundleVerificationError(
            f"{field_name} must use sha256:<64 lowercase hex> format"
        )


def _artifact_error(message: str) -> NoReturn:
    raise EconomicArtifactBundleVerificationError(message)


__all__ = [
    "ECONOMIC_COST_MODEL_DESCRIPTION",
    "ECONOMIC_LAG_DESCRIPTION",
    "ECONOMIC_LEAKAGE_REVIEW_DESCRIPTION",
    "ECONOMIC_LOOKBACK_DESCRIPTION",
    "ECONOMIC_SLIPPAGE_MODEL_DESCRIPTION",
    "CompletedEconomicBacktestLedgerMappingInput",
    "CompletedEconomicBacktestLedgerRecords",
    "EconomicArtifactBundleVerificationError",
    "EconomicLedgerMappingError",
    "map_completed_economic_backtest_to_ledger_records",
    "verify_economic_artifact_bundle",
]
