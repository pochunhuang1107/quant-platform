from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from backtest_engine import (
    CompletedEconomicBacktestLedgerMappingInput,
    CompletedEconomicBacktestResult,
    EconomicArtifactBundleVerificationError,
    generate_economic_artifact_bundle,
    map_completed_economic_backtest_to_ledger_records,
    run_snapshot_v2_buy_and_hold_backtest,
    verify_economic_artifact_bundle,
)
from backtest_engine.economic_artifacts import (
    ECONOMIC_CORPORATE_ACTION_AUDIT_FILENAME,
)
from helpers_backtest_engine_economic import (
    DEFAULT_SESSIONS,
    QQQ_INSTRUMENT_ID,
    compatible_profile,
    execution_metadata,
    qqq_bundle_files,
    resolved_config,
    spy_bundle_files,
)
from helpers_daily_market_data_snapshots_v2 import cash_distribution_v2
from research_sdk.contracts import (
    ArtifactKind,
    ReviewMetadata,
    ReviewStatus,
    TemporalCoverage,
)
from research_sdk.contracts.artifacts import REQUIRED_ARTIFACT_SPECS
from research_sdk.experiment_recording import CompletedExperimentPairRecordBundle


def test_economic_artifacts_are_complete_and_pair_lineage_is_exposed(
    tmp_path: Path,
) -> None:
    result = completed_result_with_distribution()
    bundle = generate_economic_artifact_bundle(
        result=result,
        artifact_base_dir=tmp_path,
    )

    expected_filenames = {
        filename for filename, _format in REQUIRED_ARTIFACT_SPECS.values()
    } | {ECONOMIC_CORPORATE_ACTION_AUDIT_FILENAME}
    assert {item.filename for item in bundle.payload_artifacts} == expected_filenames
    assert len(bundle.run_artifact_manifest.artifacts) == 11
    assert (
        sum(
            entry.artifact_kind is ArtifactKind.DIAGNOSTIC
            for entry in bundle.run_artifact_manifest.artifacts
        )
        == 1
    )

    config = json.loads((Path(bundle.artifact_root_path) / "config.json").read_bytes())
    lineage = config["market_data_execution_lineage"]
    assert lineage["asset"]["snapshot_id"] == (
        result.market_data_lineage.asset.snapshot_id
    )
    assert lineage["benchmark"]["snapshot_id"] == (
        result.market_data_lineage.benchmark.snapshot_id
    )
    assert lineage["asset"]["snapshot_id"] != lineage["benchmark"]["snapshot_id"]
    assert lineage["temporal_coverage"] == TemporalCoverage.LATEST_KNOWN.value
    assert config["run_id"] == result.run_id


def test_artifact_payload_bytes_and_hashes_are_deterministic_across_roots(
    tmp_path: Path,
) -> None:
    result = completed_result_with_distribution()
    first = generate_economic_artifact_bundle(
        result=result,
        artifact_base_dir=tmp_path / "first",
    )
    second = generate_economic_artifact_bundle(
        result=result,
        artifact_base_dir=tmp_path / "second",
    )

    first_by_filename = {item.filename: item for item in first.payload_artifacts}
    second_by_filename = {item.filename: item for item in second.payload_artifacts}
    assert set(first_by_filename) == set(second_by_filename)
    for filename in first_by_filename:
        first_item = first_by_filename[filename]
        second_item = second_by_filename[filename]
        assert Path(first_item.path).read_bytes() == Path(second_item.path).read_bytes()
        assert first_item.content_hash == second_item.content_hash
        assert first_item.row_count == second_item.row_count
        assert first_item.created_at == second_item.created_at
    assert first.manifest_id == second.manifest_id


def test_daily_and_action_artifacts_reconcile_with_completed_result(
    tmp_path: Path,
) -> None:
    result = completed_result_with_distribution()
    bundle = generate_economic_artifact_bundle(
        result=result,
        artifact_base_dir=tmp_path,
    )
    root = Path(bundle.artifact_root_path)

    daily_rows = pq.read_table(root / "daily_equity.parquet").to_pylist()
    action_rows = pq.read_table(
        root / ECONOMIC_CORPORATE_ACTION_AUDIT_FILENAME
    ).to_pylist()

    assert len(daily_rows) == len(result.daily_records)
    assert daily_rows[-1]["strategy_total_economic_equity"] == (
        result.daily_records[-1].strategy_total_economic_equity
    )
    assert daily_rows[-1]["benchmark_total_economic_equity"] == (
        result.daily_records[-1].benchmark_total_economic_equity
    )
    assert len(action_rows) == len(result.corporate_action_audit)
    assert [row["event_id"] for row in action_rows] == [
        row.event_id for row in result.corporate_action_audit
    ]
    assert [row["accounting_action"] for row in action_rows] == [
        row.accounting_action for row in result.corporate_action_audit
    ]


def test_artifact_verifier_accepts_exact_bundle_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    result = completed_result_with_distribution()
    bundle = generate_economic_artifact_bundle(
        result=result,
        artifact_base_dir=tmp_path,
    )

    manifest, config_entry = verify_economic_artifact_bundle(
        result=result,
        artifacts=bundle,
    )
    assert manifest == bundle.run_artifact_manifest
    assert config_entry.artifact_kind is ArtifactKind.CONFIG

    metrics_path = Path(bundle.artifact_root_path) / "metrics.json"
    metrics_path.write_bytes(metrics_path.read_bytes() + b" ")
    with pytest.raises(EconomicArtifactBundleVerificationError, match="hashes"):
        verify_economic_artifact_bundle(result=result, artifacts=bundle)


def test_pair_aware_ledger_mapping_retains_both_distinct_verified_manifests(
    tmp_path: Path,
) -> None:
    result = completed_result_with_distribution()
    artifacts = generate_economic_artifact_bundle(
        result=result,
        artifact_base_dir=tmp_path,
    )

    records = map_completed_economic_backtest_to_ledger_records(
        CompletedEconomicBacktestLedgerMappingInput(
            result=result,
            artifacts=artifacts,
            created_by="agent-s3d2b-test",
            review=pending_review(),
        )
    )

    pair_bundle = CompletedExperimentPairRecordBundle(
        asset_snapshot=records.asset_snapshot,
        benchmark_snapshot=records.benchmark_snapshot,
        run=records.run,
        manifest_id=records.manifest_id,
        artifact_manifest=records.artifact_manifest,
    )
    assert isinstance(pair_bundle, CompletedExperimentPairRecordBundle)
    assert records.asset_snapshot.snapshot_id == (
        result.market_data_lineage.asset.snapshot_id
    )
    assert records.benchmark_snapshot.snapshot_id == (
        result.market_data_lineage.benchmark.snapshot_id
    )
    assert records.asset_snapshot.snapshot_id != records.benchmark_snapshot.snapshot_id
    assert records.run.data_snapshot_id == records.asset_snapshot.snapshot_id
    assert records.run.benchmark.snapshot_id == records.benchmark_snapshot.snapshot_id
    assert records.run.config_hash == next(
        entry.content_hash
        for entry in records.artifact_manifest.artifacts
        if entry.artifact_kind is ArtifactKind.CONFIG
    )
    assert "LATEST_KNOWN" in records.run.leakage_review
    assert "zero commission" in records.run.cost_model
    assert records.run.repo_dirty is False


def test_dirty_runtime_lineage_cannot_be_recorded(tmp_path: Path) -> None:
    qqq = qqq_bundle_files()
    result = run_snapshot_v2_buy_and_hold_backtest(
        asset_files=qqq,
        benchmark_files=spy_bundle_files(),
        research_profile=compatible_profile(qqq),
        resolved_config=resolved_config(),
        execution_metadata=execution_metadata(repo_dirty=True),
    )
    artifacts = generate_economic_artifact_bundle(
        result=result,
        artifact_base_dir=tmp_path,
    )

    with pytest.raises(ValueError, match="dirty repository"):
        map_completed_economic_backtest_to_ledger_records(
            CompletedEconomicBacktestLedgerMappingInput(
                result=result,
                artifacts=artifacts,
                created_by="agent-s3d2b-test",
                review=pending_review(),
            )
        )


def completed_result_with_distribution() -> CompletedEconomicBacktestResult:
    event = cash_distribution_v2(
        event_id="qqq-artifact-distribution",
        instrument_id=QQQ_INSTRUMENT_ID,
        ex_date=DEFAULT_SESSIONS[1],
        record_date=DEFAULT_SESSIONS[1],
        payable_date=DEFAULT_SESSIONS[1],
    )
    qqq = qqq_bundle_files(events=(event,))
    return run_snapshot_v2_buy_and_hold_backtest(
        asset_files=qqq,
        benchmark_files=spy_bundle_files(),
        research_profile=compatible_profile(qqq),
        resolved_config=resolved_config(),
        execution_metadata=execution_metadata(),
    )


def pending_review() -> ReviewMetadata:
    return ReviewMetadata(
        review_status=ReviewStatus.PENDING,
        risk_approval_required=True,
    )
