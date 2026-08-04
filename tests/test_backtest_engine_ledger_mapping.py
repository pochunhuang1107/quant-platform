from __future__ import annotations

import ast
import inspect
import json
import shutil
import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

import backtest_engine.ledger_mapping as ledger_mapping
from backtest_engine import (
    ENGINE_VERSION,
    BasisPointAssumption,
    CompletedBacktestLedgerMappingInput,
    CompletedBacktestLedgerRecords,
    DirtyBacktestLineageError,
    ExecutionMetadata,
    GeneratedArtifactBundleVerificationError,
    ResolvedBacktestConfig,
    canonical_json_bytes,
    canonical_json_sha256,
    derive_execution_identity,
    file_sha256_bytes,
    generate_artifact_bundle,
    identity_from_completed_result,
    load_daily_bar_snapshot,
    map_completed_backtest_to_ledger_records,
    run_buy_and_hold_backtest,
    serialize_artifact_manifest,
    verify_generated_artifact_bundle,
)
from backtest_engine.models import BacktestMetrics, quantize_ratio
from research_sdk.contracts import (
    ArtifactKind,
    ArtifactStatus,
    DataAdjustmentPolicy,
    DataSnapshotKind,
    DataSnapshotStatus,
    DataSourceType,
    HashAlgorithm,
    ReviewMetadata,
    ReviewStatus,
    RunArtifactManifest,
    TemporalCoverage,
)
from research_sdk.contracts.artifacts import REQUIRED_ARTIFACT_SPECS
from research_sdk.persistence.hashing import contract_sha256

FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "backtest_engine"
    / "synthetic_daily_etf_bars.json"
)
EXPECTED_CREATED_BY = "agent-codex"
EXPECTED_PAYLOAD_FILENAMES = tuple(
    filename for filename, _format in REQUIRED_ARTIFACT_SPECS.values()
)


def test_valid_complete_mapping(tmp_path: Path) -> None:
    bundle = mapped_bundle(tmp_path)

    assert isinstance(bundle, CompletedBacktestLedgerRecords)
    assert bundle.snapshot.snapshot_id == "synthetic-etf-snapshot-20260206"
    assert bundle.run.run_id.startswith("run-")
    assert bundle.manifest_id.startswith("manifest-")
    assert bundle.artifact_manifest is not None


def test_returned_records_have_exact_public_fields(tmp_path: Path) -> None:
    records = mapped_bundle(tmp_path)

    assert tuple(records.__dataclass_fields__) == (
        "snapshot",
        "run",
        "manifest_id",
        "artifact_manifest",
    )


def test_records_construct_completed_experiment_bundle_at_application_boundary(
    tmp_path: Path,
) -> None:
    from research_sdk.experiment_recording import CompletedExperimentRecordBundle

    records = mapped_bundle(tmp_path)

    bundle = CompletedExperimentRecordBundle(
        snapshot=records.snapshot,
        run=records.run,
        manifest_id=records.manifest_id,
        artifact_manifest=records.artifact_manifest,
    )

    assert bundle.snapshot == records.snapshot
    assert bundle.run == records.run
    assert bundle.manifest_id == records.manifest_id
    assert bundle.artifact_manifest == records.artifact_manifest


def test_dirty_worktree_rejection_happens_before_filesystem_verification(
    tmp_path: Path,
) -> None:
    result = completed_result().model_copy(
        update={
            "execution_metadata": execution_metadata(repo_dirty=True),
        }
    )
    mapping_input = CompletedBacktestLedgerMappingInput(
        result=result,
        artifacts=artifact_bundle(tmp_path, result=completed_result()),
        fixture_path=tmp_path / "missing-fixture.json",
        created_by=EXPECTED_CREATED_BY,
        review=review_metadata(),
    )

    with pytest.raises(DirtyBacktestLineageError):
        map_completed_backtest_to_ledger_records(mapping_input)


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        (
            "commission",
            BasisPointAssumption(
                bps=Decimal("3"),
                description="changed commission",
            ),
        ),
        ("strategy_version", "0.2.0"),
        ("logical_execution_at", datetime(2026, 2, 7, tzinfo=UTC)),
    ],
)
def test_changed_config_with_stale_identity_is_rejected(
    tmp_path: Path,
    field_name: str,
    replacement: object,
) -> None:
    result = completed_result()
    changed_result = result.model_copy(
        update={
            "resolved_config": result.resolved_config.model_copy(
                update={field_name: replacement}
            )
        }
    )

    with pytest.raises(ledger_mapping.BacktestLedgerMappingError, match="stale"):
        map_completed_backtest_to_ledger_records(
            mapping_input(tmp_path, result=changed_result)
        )


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("git_commit_sha", "changed-git-sha"),
        ("dependency_lock_hash", "sha256:changed-lock"),
        ("execution_command", "python -m changed_command"),
    ],
)
def test_changed_execution_metadata_with_stale_identity_is_rejected(
    tmp_path: Path,
    field_name: str,
    replacement: object,
) -> None:
    result = completed_result()
    changed_result = result.model_copy(
        update={
            "execution_metadata": result.execution_metadata.model_copy(
                update={field_name: replacement}
            )
        }
    )

    with pytest.raises(ledger_mapping.BacktestLedgerMappingError, match="stale"):
        map_completed_backtest_to_ledger_records(
            mapping_input(tmp_path, result=changed_result)
        )


def test_dirty_worktree_rejection_precedes_stale_identity_check(
    tmp_path: Path,
) -> None:
    result = completed_result()
    changed_result = result.model_copy(
        update={
            "resolved_config": result.resolved_config.model_copy(
                update={"strategy_version": "0.2.0"}
            ),
            "execution_metadata": result.execution_metadata.model_copy(
                update={"repo_dirty": True}
            ),
        }
    )

    with pytest.raises(DirtyBacktestLineageError):
        map_completed_backtest_to_ledger_records(
            mapping_input(tmp_path, result=changed_result)
        )


@pytest.mark.parametrize(
    "field_name",
    [
        "input_snapshot_id",
        "data_snapshot_id",
        "benchmark_snapshot_id",
    ],
)
def test_all_snapshot_identities_must_match(
    tmp_path: Path,
    field_name: str,
) -> None:
    result = completed_result()
    if field_name == "input_snapshot_id":
        changed_result = result.model_copy(update={"input_snapshot_id": "other"})
    elif field_name == "data_snapshot_id":
        changed_result = result.model_copy(
            update={
                "resolved_config": result.resolved_config.model_copy(
                    update={"data_snapshot_id": "other"}
                )
            }
        )
        changed_result = result_with_refreshed_identity(changed_result)
    else:
        changed_result = result.model_copy(
            update={
                "resolved_config": result.resolved_config.model_copy(
                    update={"benchmark_snapshot_id": "other"}
                )
            }
        )
        changed_result = result_with_refreshed_identity(changed_result)

    with pytest.raises(ledger_mapping.BacktestLedgerMappingError, match="must match"):
        map_completed_backtest_to_ledger_records(
            mapping_input(tmp_path, result=changed_result)
        )


def test_fixture_snapshot_identity_must_match_result(tmp_path: Path) -> None:
    changed_fixture = tmp_path / "changed-fixture.json"
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload["snapshot_id"] = "other"
    changed_fixture.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ledger_mapping.BacktestLedgerMappingError, match="must match"):
        map_completed_backtest_to_ledger_records(
            mapping_input(tmp_path, fixture_path=changed_fixture)
        )


def test_exact_snapshot_field_mapping(tmp_path: Path) -> None:
    result = completed_result()
    bundle = mapped_bundle(tmp_path, result=result)
    snapshot = bundle.snapshot

    assert snapshot.schema_version == "1.0.0"
    assert snapshot.snapshot_id == result.input_snapshot_id
    assert snapshot.snapshot_kind is DataSnapshotKind.MARKET_DATA
    assert snapshot.status is DataSnapshotStatus.COMPLETED
    assert snapshot.created_at == datetime(2026, 2, 6, tzinfo=UTC)
    assert snapshot.created_by == EXPECTED_CREATED_BY
    assert snapshot.asset_class.value == "etfs"
    assert snapshot.asset_universe.symbols == ("QQQ", "SPY")
    assert snapshot.asset_universe.as_of == datetime(2026, 2, 6, tzinfo=UTC)
    assert snapshot.time_range.start_date == date(2026, 1, 29)
    assert snapshot.time_range.end_date == date(2026, 2, 5)
    assert snapshot.frequency == "daily"
    assert snapshot.data_root_uri == FIXTURE_PATH.resolve().as_uri()
    assert snapshot.source_dataset == "fixture-only-synthetic-daily-etf-bars"
    assert snapshot.source_version == "1.0.0"
    assert snapshot.source_type is DataSourceType.RESEARCH_GENERATED
    assert snapshot.temporal_coverage is TemporalCoverage.POINT_IN_TIME
    assert snapshot.temporal_coverage_notes == (
        ledger_mapping.DATA_SNAPSHOT_TEMPORAL_COVERAGE_NOTES
    )
    assert snapshot.as_of == datetime(2026, 2, 6, tzinfo=UTC)
    assert snapshot.available_at == datetime(2026, 2, 6, tzinfo=UTC)
    assert snapshot.ingestion_completed_at == datetime(2026, 2, 6, tzinfo=UTC)
    assert snapshot.source_observed_at is None
    assert snapshot.adjustment_policy is DataAdjustmentPolicy.RAW
    assert snapshot.adjustment_policy_notes == (
        ledger_mapping.DATA_SNAPSHOT_ADJUSTMENT_POLICY_NOTES
    )
    assert snapshot.calendar == "supplied-fixture-sessions-only"
    assert snapshot.timezone == "America/New_York"
    assert snapshot.currency == "USD"
    assert snapshot.universe_membership_policy == (
        "fixed synthetic QQQ/SPY membership supplied by the fixture"
    )
    assert snapshot.corporate_action_policy == (
        "no splits, dividends, or corporate actions are modeled"
    )
    assert snapshot.survivorship_policy == (
        "not applicable to the fixed synthetic fixture"
    )
    assert snapshot.delisting_policy == "not applicable to the fixed synthetic fixture"
    assert snapshot.rollover_policy is None
    assert snapshot.hash_algorithm is HashAlgorithm.SHA256
    assert snapshot.content_hash == f"sha256:{result.fixture_content_hash}"
    assert snapshot.row_count == 12
    assert snapshot.file_count == 1
    fixture_bytes = FIXTURE_PATH.read_bytes()
    assert snapshot.size_bytes == len(fixture_bytes)
    assert snapshot.content_hash == f"sha256:{file_sha256_bytes(fixture_bytes)}"
    assert snapshot.vendor_name is None
    assert snapshot.license_notes is None
    assert snapshot.known_limitations == ledger_mapping.DATA_SNAPSHOT_KNOWN_LIMITATIONS


def test_exact_run_field_mapping(tmp_path: Path) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result)
    bundle = mapped_bundle(tmp_path, result=result, artifacts=artifacts)
    run = bundle.run
    config_entry = artifact_entry_by_kind(
        artifacts.run_artifact_manifest, ArtifactKind.CONFIG
    )

    assert run.schema_version == "1.0.0"
    assert run.run_id == result.run_id
    assert run.experiment_id == result.resolved_config.experiment_id
    assert run.created_at == result.resolved_config.logical_execution_at
    assert run.created_by == EXPECTED_CREATED_BY
    assert run.status.value == "completed"
    assert run.status_updated_at == result.resolved_config.logical_execution_at
    assert run.status_updated_by == EXPECTED_CREATED_BY
    assert run.strategy_id == result.resolved_config.strategy_id
    assert run.strategy_version == result.resolved_config.strategy_version
    assert run.git_commit_sha == result.execution_metadata.git_commit_sha
    assert run.repo_dirty is False
    assert run.asset_class.value == "etfs"
    assert run.asset_universe.symbols == ("QQQ",)
    assert run.asset_universe.as_of == result.resolved_config.logical_execution_at
    assert run.time_range.start_date == result.resolved_config.start_date
    assert run.time_range.end_date == result.resolved_config.end_date
    assert run.frequency == "daily"
    assert run.benchmark.benchmark_id == "SPY-gross-normalized"
    assert run.benchmark.snapshot_id == result.resolved_config.benchmark_snapshot_id
    assert run.data_snapshot_id == result.resolved_config.data_snapshot_id
    assert run.config_uri == config_entry.uri
    assert run.config_hash == config_entry.content_hash
    assert run.artifact_uri == artifacts.artifact_root_uri
    assert run.artifact_manifest_uri == artifacts.artifact_manifest_uri
    assert run.artifact_manifest_hash == artifacts.artifact_manifest_hash
    assert run.engine_version == ENGINE_VERSION
    assert run.dependency_lock_hash == result.execution_metadata.dependency_lock_hash
    assert run.execution_command == result.execution_metadata.execution_command
    assert run.environment.python_version == result.execution_metadata.python_version
    assert run.environment.platform == result.execution_metadata.platform
    assert run.environment.runner == "backtest_engine.deterministic_etf"
    assert run.environment.container_image_digest is None
    assert run.random_seed.seed is None
    assert run.random_seed.rationale == result.resolved_config.no_randomness_reason
    assert run.review == review_metadata()
    assert run.feature_snapshot_id is None
    assert run.parent_run_id is None
    assert run.supersedes_run_id is None
    assert run.failure_labels == ()
    assert run.failure_reason is None
    assert run.failure_logs_uri is None
    assert run.artifacts_incomplete is False


def test_review_object_is_passed_unchanged(tmp_path: Path) -> None:
    review = review_metadata()
    bundle = mapped_bundle(tmp_path, review=review)

    assert bundle.run.review == review


def test_metrics_summary_keys_and_scalar_types(tmp_path: Path) -> None:
    run = mapped_bundle(tmp_path).run

    assert run.metrics_summary == {
        "total_return": "0.049650280020",
        "benchmark_total_return": "0.025000000000",
        "excess_return": "0.024650280020",
        "maximum_drawdown": "-0.009797188585",
        "realized_commission": "9.991998",
        "realized_slippage": "19.980000",
        "ending_equity": "104965.028002",
        "number_of_trades": 1,
        "observation_count": 6,
    }
    assert all(isinstance(value, str | int) for value in run.metrics_summary.values())


def test_exact_benchmark_leakage_cost_slippage_lookback_and_lag_strings(
    tmp_path: Path,
) -> None:
    run = mapped_bundle(tmp_path).run

    assert run.benchmark.benchmark_id == "SPY-gross-normalized"
    assert run.cost_model == (
        "QQQ commission is 1 basis points on executed notional; "
        "SPY benchmark is gross with no commission"
    )
    assert run.slippage_model == (
        "QQQ buy slippage is 2 basis points on the first aligned open; "
        "SPY benchmark is gross with no slippage"
    )
    assert run.lookback == ledger_mapping.LOOKBACK_DESCRIPTION
    assert run.lag_assumptions == ledger_mapping.LAG_ASSUMPTIONS_DESCRIPTION
    assert run.leakage_review == ledger_mapping.LEAKAGE_REVIEW_DESCRIPTION


def test_parameter_hash_is_canonical_resolved_config_hash(tmp_path: Path) -> None:
    result = completed_result()
    run = mapped_bundle(tmp_path, result=result).run

    assert run.parameter_hash == (
        f"sha256:{canonical_json_sha256(result.resolved_config)}"
    )


def test_config_hash_matches_actual_config_json_bytes(tmp_path: Path) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result)
    run = mapped_bundle(tmp_path, result=result, artifacts=artifacts).run
    config_path = Path(artifacts.artifact_root_path) / "config.json"

    assert run.config_hash == f"sha256:{file_sha256_bytes(config_path.read_bytes())}"


def test_manifest_hash_matches_actual_artifact_manifest_bytes(tmp_path: Path) -> None:
    artifacts = artifact_bundle(tmp_path)
    run = mapped_bundle(tmp_path, artifacts=artifacts).run

    assert run.artifact_manifest_hash == (
        f"sha256:{file_sha256_bytes(Path(artifacts.artifact_manifest_path).read_bytes())}"
    )


def test_run_id_equals_run_prefix_plus_full_digest(tmp_path: Path) -> None:
    result = completed_result()
    bundle = mapped_bundle(tmp_path, result=result)

    assert bundle.run.run_id == f"run-{result.full_execution_identity_digest}"


def test_malformed_run_id_raises_mapping_error(tmp_path: Path) -> None:
    result = completed_result().model_copy(update={"run_id": "bad-run-id"})

    with pytest.raises(
        ledger_mapping.BacktestLedgerMappingError,
        match="identity could not be verified",
    ) as exc_info:
        map_completed_backtest_to_ledger_records(mapping_input(tmp_path, result=result))

    assert exc_info.value.__cause__ is not None


def test_malformed_stored_digest_run_id_relationship_raises_mapping_error(
    tmp_path: Path,
) -> None:
    result = completed_result().model_copy(
        update={"full_execution_identity_digest": "0" * 64}
    )

    with pytest.raises(
        ledger_mapping.BacktestLedgerMappingError,
        match="stale or inconsistent",
    ):
        map_completed_backtest_to_ledger_records(mapping_input(tmp_path, result=result))


def test_cross_contract_identities_agree(tmp_path: Path) -> None:
    bundle = mapped_bundle(tmp_path)

    assert bundle.run.data_snapshot_id == bundle.snapshot.snapshot_id
    assert bundle.artifact_manifest.run_id == bundle.run.run_id
    assert bundle.artifact_manifest.experiment_id == bundle.run.experiment_id
    assert bundle.run.artifact_uri == bundle.artifact_manifest.artifact_root_uri
    assert bundle.run.artifact_manifest_uri == (
        f"{bundle.artifact_manifest.artifact_root_uri}/artifact_manifest.json"
    )


def test_run_artifact_manifest_is_reparsed_from_actual_manifest_bytes(
    tmp_path: Path,
) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result)

    parsed = verify_generated_artifact_bundle(result=result, artifacts=artifacts)

    assert parsed == RunArtifactManifest.model_validate(
        json.loads(Path(artifacts.artifact_manifest_path).read_text(encoding="utf-8"))
    )


def test_public_artifact_verifier_rejects_stale_identity(tmp_path: Path) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result)
    changed_result = result.model_copy(
        update={
            "execution_metadata": result.execution_metadata.model_copy(
                update={"dependency_lock_hash": "sha256:changed-lock"}
            )
        }
    )

    with pytest.raises(
        ledger_mapping.BacktestLedgerMappingError,
        match="stale or inconsistent",
    ):
        verify_generated_artifact_bundle(result=changed_result, artifacts=artifacts)


def test_public_artifact_verifier_accepts_valid_bundle(tmp_path: Path) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result)

    parsed = verify_generated_artifact_bundle(result=result, artifacts=artifacts)

    assert parsed == artifacts.run_artifact_manifest


def test_canonical_manifest_bytes_are_required(tmp_path: Path) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result)
    manifest_path = Path(artifacts.artifact_manifest_path)
    pretty = json.dumps(
        artifacts.run_artifact_manifest.model_dump(mode="json"),
        indent=2,
        sort_keys=True,
    ).encode()
    manifest_path.write_bytes(pretty)
    changed = artifacts.model_copy(
        update={"artifact_manifest_hash": f"sha256:{file_sha256_bytes(pretty)}"}
    )

    with pytest.raises(
        GeneratedArtifactBundleVerificationError,
        match="canonical manifest bytes",
    ):
        verify_generated_artifact_bundle(result=result, artifacts=changed)


def test_config_json_semantic_content_must_match_result_even_with_rewritten_hashes(
    tmp_path: Path,
) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result)
    config_path = Path(artifacts.artifact_root_path) / "config.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["execution_assumptions"]["strategy"] = "changed strategy"
    changed = rewrite_payload_artifact(
        artifacts=artifacts,
        filename="config.json",
        content=canonical_json_bytes(payload),
    )

    with pytest.raises(
        GeneratedArtifactBundleVerificationError,
        match="config.json must semantically match",
    ):
        verify_generated_artifact_bundle(result=result, artifacts=changed)


def test_metrics_json_semantic_content_must_match_result_even_with_rewritten_hashes(
    tmp_path: Path,
) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result)
    metrics_path = Path(artifacts.artifact_root_path) / "metrics.json"
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    payload["total_return"] = "0"
    changed = rewrite_payload_artifact(
        artifacts=artifacts,
        filename="metrics.json",
        content=canonical_json_bytes(payload),
    )

    with pytest.raises(
        GeneratedArtifactBundleVerificationError,
        match="metrics.json must semantically match",
    ):
        verify_generated_artifact_bundle(result=result, artifacts=changed)


def test_in_memory_manifest_mismatch_is_rejected(tmp_path: Path) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result)
    changed_manifest = artifacts.run_artifact_manifest.model_copy(
        update={"created_at": datetime(2026, 2, 7, tzinfo=UTC)}
    )
    changed = artifacts.model_copy(update={"run_artifact_manifest": changed_manifest})

    with pytest.raises(
        GeneratedArtifactBundleVerificationError,
        match="in-memory artifact manifest",
    ):
        verify_generated_artifact_bundle(result=result, artifacts=changed)


def test_missing_manifest_file_is_rejected(tmp_path: Path) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result)
    Path(artifacts.artifact_manifest_path).unlink()

    with pytest.raises(GeneratedArtifactBundleVerificationError, match="must exist"):
        verify_generated_artifact_bundle(result=result, artifacts=artifacts)


def test_changed_manifest_bytes_are_rejected(tmp_path: Path) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result)
    Path(artifacts.artifact_manifest_path).write_bytes(b"{}\n")
    changed = artifacts.model_copy(
        update={"artifact_manifest_hash": f"sha256:{file_sha256_bytes(b'{}\\n')}"}
    )

    with pytest.raises(GeneratedArtifactBundleVerificationError):
        verify_generated_artifact_bundle(result=result, artifacts=changed)


def test_wrong_manifest_hash_is_rejected(tmp_path: Path) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result).model_copy(
        update={"artifact_manifest_hash": "sha256:" + ("0" * 64)}
    )

    with pytest.raises(GeneratedArtifactBundleVerificationError, match="hash"):
        verify_generated_artifact_bundle(result=result, artifacts=artifacts)


def test_wrong_root_uri_is_rejected(tmp_path: Path) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result).model_copy(
        update={"artifact_root_uri": "file:///wrong/root"}
    )

    with pytest.raises(GeneratedArtifactBundleVerificationError, match="root"):
        verify_generated_artifact_bundle(result=result, artifacts=artifacts)


def test_wrong_manifest_uri_is_rejected(tmp_path: Path) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result).model_copy(
        update={"artifact_manifest_uri": "file:///wrong/artifact_manifest.json"}
    )

    with pytest.raises(GeneratedArtifactBundleVerificationError, match="manifest_uri"):
        verify_generated_artifact_bundle(result=result, artifacts=artifacts)


def test_wrong_manifest_relocation_is_rejected(tmp_path: Path) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result)
    relocated = tmp_path / "relocated_manifest.json"
    relocated.write_bytes(Path(artifacts.artifact_manifest_path).read_bytes())
    changed = artifacts.model_copy(
        update={
            "artifact_manifest_path": str(relocated.resolve()),
            "artifact_manifest_uri": relocated.resolve().as_uri(),
        }
    )

    with pytest.raises(
        GeneratedArtifactBundleVerificationError, match="under artifact root"
    ):
        verify_generated_artifact_bundle(result=result, artifacts=changed)


def test_missing_payload_is_rejected(tmp_path: Path) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result)
    (Path(artifacts.artifact_root_path) / "config.json").unlink()

    with pytest.raises(GeneratedArtifactBundleVerificationError, match="regular file"):
        verify_generated_artifact_bundle(result=result, artifacts=artifacts)


def test_changed_payload_bytes_are_rejected(tmp_path: Path) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result)
    (Path(artifacts.artifact_root_path) / "config.json").write_text("changed\n")

    with pytest.raises(GeneratedArtifactBundleVerificationError, match="content hash"):
        verify_generated_artifact_bundle(result=result, artifacts=artifacts)


def test_wrong_payload_size_is_rejected(tmp_path: Path) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result)
    metadata = artifact_metadata_by_filename(artifacts, "config.json").model_copy(
        update={"size_bytes": 1}
    )
    changed = replace_payload_metadata(artifacts, metadata)

    with pytest.raises(GeneratedArtifactBundleVerificationError, match="size"):
        verify_generated_artifact_bundle(result=result, artifacts=changed)


def test_wrong_payload_uri_is_rejected(tmp_path: Path) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result)
    metadata = artifact_metadata_by_filename(artifacts, "config.json").model_copy(
        update={"uri": "file:///wrong/config.json"}
    )
    changed = replace_payload_metadata(artifacts, metadata)

    with pytest.raises(GeneratedArtifactBundleVerificationError, match="URI"):
        verify_generated_artifact_bundle(result=result, artifacts=changed)


def test_payload_path_outside_root_is_rejected(tmp_path: Path) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result)
    outside = tmp_path / "outside-config.json"
    outside.write_bytes(
        (Path(artifacts.artifact_root_path) / "config.json").read_bytes()
    )
    metadata = artifact_metadata_by_filename(artifacts, "config.json").model_copy(
        update={"path": str(outside.resolve()), "uri": outside.resolve().as_uri()}
    )
    changed = replace_payload_metadata(artifacts, metadata)

    with pytest.raises(GeneratedArtifactBundleVerificationError, match="under root"):
        verify_generated_artifact_bundle(result=result, artifacts=changed)


def test_symlink_payload_is_rejected(tmp_path: Path) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result)
    config_path = Path(artifacts.artifact_root_path) / "config.json"
    target = tmp_path / "target-config.json"
    target.write_bytes(config_path.read_bytes())
    config_path.unlink()
    config_path.symlink_to(target)

    with pytest.raises(GeneratedArtifactBundleVerificationError, match="symlink"):
        verify_generated_artifact_bundle(result=result, artifacts=artifacts)


def test_incomplete_required_entries_are_rejected(tmp_path: Path) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result)
    manifest = artifacts.run_artifact_manifest
    changed_entry = manifest.artifacts[0].model_copy(
        update={"status": ArtifactStatus.MISSING}
    )
    changed_manifest = manifest.model_copy(
        update={
            "required_artifacts_complete": False,
            "artifacts": (changed_entry, *manifest.artifacts[1:]),
        }
    )
    changed = rewrite_manifest_artifact(artifacts, changed_manifest)

    with pytest.raises(GeneratedArtifactBundleVerificationError, match="complete"):
        verify_generated_artifact_bundle(result=result, artifacts=changed)


def test_wrong_manifest_id_is_rejected(tmp_path: Path) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result).model_copy(
        update={"manifest_id": "manifest-wrong"}
    )

    with pytest.raises(GeneratedArtifactBundleVerificationError, match="manifest_id"):
        verify_generated_artifact_bundle(result=result, artifacts=artifacts)


def test_duplicate_or_invalid_write_order_is_rejected(tmp_path: Path) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result).model_copy(
        update={
            "write_order": (
                "config.json",
                "config.json",
                *EXPECTED_PAYLOAD_FILENAMES[1:],
                "artifact_manifest.json",
            )
        }
    )

    with pytest.raises(GeneratedArtifactBundleVerificationError, match="write_order"):
        verify_generated_artifact_bundle(result=result, artifacts=artifacts)


def test_artifact_manifest_json_as_entry_is_rejected(tmp_path: Path) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result)
    payload = artifacts.run_artifact_manifest.model_dump(mode="json")
    extra = dict(payload["artifacts"][0])
    extra.update(
        {
            "artifact_id": "artifact-manifest-json",
            "artifact_kind": "other",
            "filename": "artifact_manifest.json",
            "format": "json",
        }
    )
    payload["artifacts"].append(extra)
    manifest_path = Path(artifacts.artifact_manifest_path)
    content = (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
        + b"\n"
    )
    manifest_path.write_bytes(content)
    changed = artifacts.model_copy(
        update={"artifact_manifest_hash": f"sha256:{file_sha256_bytes(content)}"}
    )

    with pytest.raises(GeneratedArtifactBundleVerificationError):
        verify_generated_artifact_bundle(result=result, artifacts=changed)


def test_no_filesystem_writes_occur_during_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mapping = mapping_input(tmp_path)

    def fail_write(*args: object, **kwargs: object) -> None:
        raise AssertionError("mapper must not write files")

    monkeypatch.setattr(Path, "write_bytes", fail_write)
    monkeypatch.setattr(Path, "write_text", fail_write)

    map_completed_backtest_to_ledger_records(mapping)


def test_mapper_imports_no_sqlalchemy_persistence_repository_or_database_package() -> (
    None
):
    tree = ast.parse(inspect.getsource(ledger_mapping))

    prohibited_imports = {
        "sqlalchemy",
        "psycopg",
        "research_sdk.experiment_recording",
        "research_sdk.persistence",
        "SqlAlchemyExperimentLedgerRepository",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported = {alias.name for alias in node.names}
            assert prohibited_imports.isdisjoint(imported)
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert module not in {
                "research_sdk.experiment_recording",
                "research_sdk.experiment_recording.service",
            }
            assert not any(
                module == name or module.startswith(f"{name}.")
                for name in prohibited_imports
            )
            assert "SqlAlchemyExperimentLedgerRepository" not in {
                alias.name for alias in node.names
            }


@pytest.mark.parametrize(
    "module_name",
    [
        "backtest_engine",
        "backtest_engine.ledger_mapping",
    ],
)
def test_import_boundary_does_not_load_persistence_or_database_modules(
    module_name: str,
) -> None:
    script = f"""
import importlib
import json
import sys

importlib.import_module({module_name!r})
forbidden = sorted(
    name
    for name in sys.modules
    if name == "sqlalchemy"
    or name.startswith("sqlalchemy.")
    or name == "psycopg"
    or name.startswith("psycopg.")
    or name == "research_sdk.persistence"
    or name.startswith("research_sdk.persistence.")
    or name == "research_sdk.experiment_recording"
    or name.startswith("research_sdk.experiment_recording.")
    or name == "research_sdk.experiment_recording.service"
)
print(json.dumps(forbidden))
if forbidden:
    raise SystemExit(1)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, (
        f"{module_name} loaded forbidden modules: {completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )


def test_complete_mapping_execution_does_not_load_persistence_or_recording() -> None:
    script = f"""
import json
import shutil
import sys
import tempfile
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from backtest_engine import (
    ENGINE_VERSION,
    BasisPointAssumption,
    CompletedBacktestLedgerMappingInput,
    ExecutionMetadata,
    ResolvedBacktestConfig,
    generate_artifact_bundle,
    load_daily_bar_snapshot,
    map_completed_backtest_to_ledger_records,
    run_buy_and_hold_backtest,
)
from research_sdk.contracts import ReviewMetadata, ReviewStatus

fixture_path = Path({str(FIXTURE_PATH)!r})
artifact_root = Path(tempfile.mkdtemp(prefix="backtest-ledger-mapping-"))
try:
    snapshot, fixture_hash = load_daily_bar_snapshot(fixture_path)
    config = ResolvedBacktestConfig(
        experiment_id="exp-fixture-qqq-buy-hold",
        strategy_id="strategies/etfs/qqq_buy_and_hold",
        strategy_version="0.1.0",
        engine_version=ENGINE_VERSION,
        asset_symbol="QQQ",
        benchmark_symbol="SPY",
        start_date=date(2026, 1, 29),
        end_date=date(2026, 2, 5),
        frequency="daily",
        initial_capital=Decimal("100000"),
        commission=BasisPointAssumption(
            bps=Decimal("1"),
            description="1 basis point commission on executed notional",
        ),
        slippage=BasisPointAssumption(
            bps=Decimal("2"),
            description="2 basis points buy slippage",
        ),
        execution_price_field="open",
        valuation_price_field="close",
        share_policy="integer",
        data_snapshot_id="synthetic-etf-snapshot-20260206",
        benchmark_snapshot_id="synthetic-etf-snapshot-20260206",
        random_seed=None,
        no_randomness_reason="deterministic no-randomness baseline",
        logical_execution_at=datetime(2026, 2, 6, tzinfo=UTC),
    )
    execution_metadata = ExecutionMetadata(
        git_commit_sha="fe79572125f36088218e346451f4d7986cbec562",
        repo_dirty=False,
        python_version="3.13.14",
        platform="test-platform",
        dependency_lock_hash="sha256:test-lock",
        execution_command="python -m backtest_engine",
    )
    result = run_buy_and_hold_backtest(
        config=config,
        snapshot=snapshot,
        fixture_content_hash=fixture_hash,
        execution_metadata=execution_metadata,
    )
    artifacts = generate_artifact_bundle(
        result=result,
        artifact_base_dir=artifact_root,
    )
    records = map_completed_backtest_to_ledger_records(
        CompletedBacktestLedgerMappingInput(
            result=result,
            artifacts=artifacts,
            fixture_path=fixture_path,
            created_by="agent-codex",
            review=ReviewMetadata(
                review_status=ReviewStatus.PENDING,
                reviewer_id=None,
                review_role=None,
                reviewed_at=None,
                decision=None,
                approval_scope=None,
                approval_expires_at=None,
                linked_pr=None,
                review_notes_uri=None,
                risk_approval_required=True,
            ),
        )
    )
    assert records.run.run_id == result.run_id
    assert records.snapshot.snapshot_id == result.input_snapshot_id
    assert records.artifact_manifest.run_id == result.run_id
finally:
    shutil.rmtree(artifact_root)

forbidden = sorted(
    name
    for name in sys.modules
    if name == "sqlalchemy"
    or name.startswith("sqlalchemy.")
    or name == "psycopg"
    or name.startswith("psycopg.")
    or name == "research_sdk.persistence"
    or name.startswith("research_sdk.persistence.")
    or name == "research_sdk.experiment_recording"
    or name.startswith("research_sdk.experiment_recording.")
)
print(json.dumps(forbidden))
if forbidden:
    raise SystemExit(1)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, (
        "complete mapping loaded forbidden modules: "
        f"{completed.stdout}\nstderr:\n{completed.stderr}"
    )


def test_changed_result_metrics_with_original_artifacts_are_rejected(
    tmp_path: Path,
) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result)
    changed_result = result.model_copy(
        update={
            "metrics": BacktestMetrics(
                total_return=quantize_ratio(Decimal("0")),
                benchmark_total_return=result.metrics.benchmark_total_return,
                excess_return=result.metrics.excess_return,
                maximum_drawdown=result.metrics.maximum_drawdown,
                realized_commission=result.metrics.realized_commission,
                realized_slippage=result.metrics.realized_slippage,
                ending_equity=result.metrics.ending_equity,
                number_of_trades=result.metrics.number_of_trades,
                observation_count=result.metrics.observation_count,
            )
        }
    )

    with pytest.raises(
        GeneratedArtifactBundleVerificationError,
        match="metrics.json must semantically match",
    ):
        map_completed_backtest_to_ledger_records(
            mapping_input(tmp_path, result=changed_result, artifacts=artifacts)
        )


def test_output_only_metric_changes_do_not_change_recomputed_run_id() -> None:
    result = completed_result()
    changed_result = result_with_changed_metrics(result)

    assert identity_from_completed_result(
        changed_result
    ) == identity_from_completed_result(result)


def test_changed_outputs_with_regenerated_artifacts_change_mapped_run_contract(
    tmp_path: Path,
) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result)
    original_bundle = mapped_bundle(tmp_path, result=result, artifacts=artifacts)
    changed_result = result_with_changed_metrics(result)

    shutil.rmtree(Path(artifacts.artifact_root_path))
    changed_artifacts = artifact_bundle(tmp_path, result=changed_result)
    changed_bundle = mapped_bundle(
        tmp_path,
        result=changed_result,
        artifacts=changed_artifacts,
    )

    assert changed_bundle.run.run_id == original_bundle.run.run_id
    assert contract_sha256(changed_bundle.run) != contract_sha256(original_bundle.run)


def test_exact_replay_mapping_produces_byte_equivalent_contracts(
    tmp_path: Path,
) -> None:
    result = completed_result()
    artifacts = artifact_bundle(tmp_path, result=result)
    first = mapped_bundle(tmp_path, result=result, artifacts=artifacts)
    second = map_completed_backtest_to_ledger_records(
        CompletedBacktestLedgerMappingInput(
            result=result,
            artifacts=artifacts,
            fixture_path=FIXTURE_PATH,
            created_by=EXPECTED_CREATED_BY,
            review=review_metadata(),
        )
    )

    assert first.snapshot.model_dump(mode="json") == second.snapshot.model_dump(
        mode="json"
    )
    assert first.run.model_dump(mode="json") == second.run.model_dump(mode="json")
    assert first.artifact_manifest.model_dump(
        mode="json"
    ) == second.artifact_manifest.model_dump(mode="json")


def mapped_bundle(
    tmp_path: Path,
    *,
    result=None,
    artifacts=None,
    review: ReviewMetadata | None = None,
):
    return map_completed_backtest_to_ledger_records(
        mapping_input(tmp_path, result=result, artifacts=artifacts, review=review)
    )


def mapping_input(
    tmp_path: Path,
    *,
    result=None,
    artifacts=None,
    fixture_path: Path = FIXTURE_PATH,
    review: ReviewMetadata | None = None,
) -> CompletedBacktestLedgerMappingInput:
    resolved_result = result or completed_result()
    return CompletedBacktestLedgerMappingInput(
        result=resolved_result,
        artifacts=artifacts or artifact_bundle(tmp_path, result=resolved_result),
        fixture_path=fixture_path,
        created_by=EXPECTED_CREATED_BY,
        review=review or review_metadata(),
    )


def completed_result(*, metadata: ExecutionMetadata | None = None):
    snapshot, fixture_hash = load_daily_bar_snapshot(FIXTURE_PATH)
    return run_buy_and_hold_backtest(
        config=resolved_config(),
        snapshot=snapshot,
        fixture_content_hash=fixture_hash,
        execution_metadata=metadata or execution_metadata(),
    )


def result_with_changed_metrics(result):
    return result.model_copy(
        update={
            "metrics": BacktestMetrics(
                total_return=quantize_ratio(Decimal("0")),
                benchmark_total_return=result.metrics.benchmark_total_return,
                excess_return=result.metrics.excess_return,
                maximum_drawdown=result.metrics.maximum_drawdown,
                realized_commission=result.metrics.realized_commission,
                realized_slippage=result.metrics.realized_slippage,
                ending_equity=result.metrics.ending_equity,
                number_of_trades=result.metrics.number_of_trades,
                observation_count=result.metrics.observation_count,
            )
        }
    )


def result_with_refreshed_identity(result):
    digest, run_id = derive_execution_identity(
        config=result.resolved_config,
        execution_metadata=result.execution_metadata,
        fixture_content_hash=result.fixture_content_hash,
    )
    return result.model_copy(
        update={
            "full_execution_identity_digest": digest,
            "run_id": run_id,
        }
    )


def artifact_bundle(
    tmp_path: Path,
    *,
    result=None,
):
    resolved_result = result or completed_result()
    return generate_artifact_bundle(
        result=resolved_result,
        artifact_base_dir=tmp_path / "artifacts",
    )


def resolved_config() -> ResolvedBacktestConfig:
    return ResolvedBacktestConfig(
        experiment_id="exp-fixture-qqq-buy-hold",
        strategy_id="strategies/etfs/qqq_buy_and_hold",
        strategy_version="0.1.0",
        engine_version=ENGINE_VERSION,
        asset_symbol="QQQ",
        benchmark_symbol="SPY",
        start_date=date(2026, 1, 29),
        end_date=date(2026, 2, 5),
        frequency="daily",
        initial_capital=Decimal("100000"),
        commission=BasisPointAssumption(
            bps=Decimal("1"),
            description="1 basis point commission on executed notional",
        ),
        slippage=BasisPointAssumption(
            bps=Decimal("2"),
            description="2 basis points buy slippage",
        ),
        execution_price_field="open",
        valuation_price_field="close",
        share_policy="integer",
        data_snapshot_id="synthetic-etf-snapshot-20260206",
        benchmark_snapshot_id="synthetic-etf-snapshot-20260206",
        random_seed=None,
        no_randomness_reason="deterministic no-randomness baseline",
        logical_execution_at=datetime(2026, 2, 6, tzinfo=UTC),
    )


def execution_metadata(*, repo_dirty: bool = False) -> ExecutionMetadata:
    return ExecutionMetadata(
        git_commit_sha="fe79572125f36088218e346451f4d7986cbec562",
        repo_dirty=repo_dirty,
        python_version="3.13.14",
        platform="test-platform",
        dependency_lock_hash="sha256:test-lock",
        execution_command="python -m backtest_engine",
    )


def review_metadata() -> ReviewMetadata:
    return ReviewMetadata(
        review_status=ReviewStatus.PENDING,
        reviewer_id=None,
        review_role=None,
        reviewed_at=None,
        decision=None,
        approval_scope=None,
        approval_expires_at=None,
        linked_pr=None,
        review_notes_uri=None,
        risk_approval_required=True,
    )


def artifact_entry_by_kind(
    manifest: RunArtifactManifest,
    kind: ArtifactKind,
):
    return next(entry for entry in manifest.artifacts if entry.artifact_kind is kind)


def artifact_metadata_by_filename(
    artifacts,
    filename: str,
):
    return next(
        metadata
        for metadata in artifacts.payload_artifacts
        if metadata.filename == filename
    )


def replace_payload_metadata(
    artifacts,
    replacement,
):
    return artifacts.model_copy(
        update={
            "payload_artifacts": tuple(
                replacement
                if metadata.artifact_id == replacement.artifact_id
                else metadata
                for metadata in artifacts.payload_artifacts
            )
        }
    )


def rewrite_manifest_artifact(
    artifacts,
    manifest: RunArtifactManifest,
):
    content = serialize_artifact_manifest(manifest)
    Path(artifacts.artifact_manifest_path).write_bytes(content)
    return artifacts.model_copy(
        update={
            "artifact_manifest_hash": f"sha256:{file_sha256_bytes(content)}",
            "run_artifact_manifest": manifest,
        }
    )


def rewrite_payload_artifact(
    *,
    artifacts,
    filename: str,
    content: bytes,
):
    path = Path(artifacts.artifact_root_path) / filename
    path.write_bytes(content)
    content_hash = f"sha256:{file_sha256_bytes(content)}"
    metadata = artifact_metadata_by_filename(artifacts, filename).model_copy(
        update={
            "content_hash": content_hash,
            "size_bytes": len(content),
        }
    )
    manifest = artifacts.run_artifact_manifest
    changed_entries = tuple(
        entry.model_copy(
            update={
                "content_hash": content_hash,
                "size_bytes": len(content),
            }
        )
        if entry.filename == filename
        else entry
        for entry in manifest.artifacts
    )
    changed_manifest = manifest.model_copy(update={"artifacts": changed_entries})
    changed_artifacts = replace_payload_metadata(artifacts, metadata)
    return rewrite_manifest_artifact(changed_artifacts, changed_manifest)
