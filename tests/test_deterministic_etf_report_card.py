from __future__ import annotations

import ast
import inspect
import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

import backtest_engine.report_cards as report_cards
from backtest_engine import (
    ENGINE_VERSION,
    BasisPointAssumption,
    CompletedBacktestLedgerMappingInput,
    ExecutionMetadata,
    ResolvedBacktestConfig,
    build_deterministic_etf_report_card,
    canonical_json_bytes,
    canonical_json_sha256,
    derive_deterministic_etf_report_card_id,
    derive_execution_identity,
    file_sha256_bytes,
    generate_artifact_bundle,
    load_daily_bar_snapshot,
    map_completed_backtest_to_ledger_records,
    run_buy_and_hold_backtest,
    verify_deterministic_etf_report_card_identity,
)
from research_sdk.contracts import (
    ArtifactKind,
    ArtifactStatus,
    DataAdjustmentPolicy,
    DataSnapshotKind,
    DataSourceType,
    ExperimentRunStatus,
    ReportCardUseRestriction,
    ReviewMetadata,
    ReviewStatus,
    RunArtifactManifest,
    TemporalCoverage,
    TimeRange,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "backtest_engine"
    / "synthetic_daily_etf_bars.json"
)
EXPECTED_REPORT_CARD_ID = (
    "report-card-61e34d8f6d38f1e75de6d9d33e4444a3e96fa9bcf61c7261b87498b83089daaf"
)


def test_build_deterministic_etf_report_card_from_mapped_records(
    tmp_path: Path,
) -> None:
    records = mapped_records(tmp_path)
    report_card = report_card_from_records(records)

    assert report_card.report_card_id.startswith("report-card-")
    assert len(report_card.report_card_id.removeprefix("report-card-")) == 64
    assert report_card.derivation_policy_version == (
        report_cards.REPORT_CARD_DERIVATION_POLICY_VERSION
    )
    assert report_card.source_run_id == records.run.run_id
    assert report_card.experiment_id == records.run.experiment_id
    assert report_card.lineage.strategy_id == records.run.strategy_id
    assert report_card.lineage.strategy_version == records.run.strategy_version
    assert report_card.lineage.engine_version == records.run.engine_version
    assert report_card.lineage.git_commit_sha == records.run.git_commit_sha
    assert report_card.lineage.data_snapshot_id == records.snapshot.snapshot_id
    assert report_card.lineage.benchmark_snapshot_id == records.snapshot.snapshot_id
    assert (
        report_card.lineage.data_snapshot_content_hash == records.snapshot.content_hash
    )
    assert (
        report_card.lineage.benchmark_snapshot_content_hash
        == records.snapshot.content_hash
    )
    assert report_card.lineage.artifact_manifest_id == records.manifest_id
    assert report_card.lineage.config_hash == records.run.config_hash
    assert report_card.lineage.parameter_hash == records.run.parameter_hash
    assert (
        report_card.lineage.artifact_manifest_hash == records.run.artifact_manifest_hash
    )
    assert report_card.research_scope.asset_universe.symbols == ("QQQ",)
    assert report_card.research_scope.benchmark_id == "SPY-gross-normalized"
    assert report_card.research_scope.frequency == "daily"
    assert report_card.research_scope.start_date == date(2026, 1, 29)
    assert report_card.research_scope.end_date == date(2026, 2, 5)
    assert report_card.research_scope.observation_count == 6
    assert report_card.research_scope.source_run_status is ExperimentRunStatus.COMPLETED


def test_report_card_metrics_are_exact_approved_scalar_set(tmp_path: Path) -> None:
    report_card = report_card_from_records(mapped_records(tmp_path))

    assert report_card.metrics.model_dump(mode="json") == {
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


def test_report_card_assumptions_and_restrictions_are_explicit(
    tmp_path: Path,
) -> None:
    records = mapped_records(tmp_path)
    report_card = report_card_from_records(records)

    assert report_card.assumptions.cost_model == records.run.cost_model
    assert report_card.assumptions.slippage_model == records.run.slippage_model
    assert report_card.assumptions.lookback == records.run.lookback
    assert report_card.assumptions.lag_assumptions == records.run.lag_assumptions
    assert report_card.assumptions.leakage_review == records.run.leakage_review
    assert report_card.assumptions.random_seed == records.run.random_seed
    assert (
        report_card.assumptions.adjustment_policy == records.snapshot.adjustment_policy
    )
    assert (
        report_card.assumptions.temporal_coverage == records.snapshot.temporal_coverage
    )
    assert (
        report_card.assumptions.corporate_action_policy
        == records.snapshot.corporate_action_policy
    )
    assert (
        report_card.assumptions.survivorship_policy
        == records.snapshot.survivorship_policy
    )
    assert (
        report_card.assumptions.universe_membership_policy
        == records.snapshot.universe_membership_policy
    )
    assert report_card.assumptions.calendar == records.snapshot.calendar
    assert report_card.assumptions.timezone == records.snapshot.timezone
    assert set(report_card.use_restrictions) == {
        ReportCardUseRestriction.RESEARCH_GENERATED_SYNTHETIC_DATA,
        ReportCardUseRestriction.INFRASTRUCTURE_VALIDATION_ONLY,
        ReportCardUseRestriction.NO_INVESTMENT_PERFORMANCE_CLAIM,
        ReportCardUseRestriction.NOT_PRODUCTION_DATA_RESEARCH,
        ReportCardUseRestriction.NOT_PAPER_TRADING_EVIDENCE,
        ReportCardUseRestriction.NOT_LIVE_TRADING_EVIDENCE,
    }


def test_report_card_limitations_copy_source_snapshot_limitations(
    tmp_path: Path,
) -> None:
    records = mapped_records(tmp_path)
    report_card = report_card_from_records(records)

    assert (
        report_card.limitations.source_snapshot_known_limitations
        == records.snapshot.known_limitations
    )


def test_report_card_artifact_evidence_is_copied_and_sorted(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    report_card = report_card_from_records(records)

    evidence = report_card.evidence
    assert evidence.artifact_root_uri == records.run.artifact_uri
    assert evidence.artifact_manifest_uri == records.run.artifact_manifest_uri
    assert evidence.required_artifacts_complete is True
    assert [entry.filename for entry in evidence.artifacts] == sorted(
        [entry.filename for entry in records.artifact_manifest.artifacts],
        key=lambda filename: (
            artifact_entry_by_filename(
                records.artifact_manifest, filename
            ).artifact_kind.value,
            filename,
            artifact_entry_by_filename(records.artifact_manifest, filename).artifact_id,
        ),
    )
    manifest_by_id = {
        entry.artifact_id: entry for entry in records.artifact_manifest.artifacts
    }
    for entry in evidence.artifacts:
        manifest_entry = manifest_by_id[entry.artifact_id]
        assert entry.artifact_kind == manifest_entry.artifact_kind
        assert entry.filename == manifest_entry.filename
        assert entry.uri == manifest_entry.uri
        assert entry.format == manifest_entry.format
        assert entry.status == manifest_entry.status
        assert entry.content_hash == manifest_entry.content_hash
        assert entry.size_bytes == manifest_entry.size_bytes
        assert entry.row_count == manifest_entry.row_count
        assert entry.validator_version == manifest_entry.validator_version


def test_report_card_generation_is_deterministic(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)

    first = report_card_from_records(records)
    second = report_card_from_records(records)

    assert first == second
    assert canonical_json_bytes(first) == canonical_json_bytes(second)


def test_report_card_identity_uses_documented_inputs(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    report_card = report_card_from_records(records)
    expected_digest = canonical_json_sha256(
        {
            "source_run_id": records.run.run_id,
            "schema_version": "1.0.0",
            "derivation_policy_version": (
                report_cards.REPORT_CARD_DERIVATION_POLICY_VERSION
            ),
            "data_snapshot_content_hash": records.snapshot.content_hash,
            "benchmark_snapshot_content_hash": records.snapshot.content_hash,
            "config_hash": records.run.config_hash,
            "parameter_hash": records.run.parameter_hash,
            "artifact_manifest_hash": records.run.artifact_manifest_hash,
        }
    )

    assert report_card.report_card_id == f"report-card-{expected_digest}"


def test_report_card_identity_has_expected_golden_for_stable_identity_inputs(
    tmp_path: Path,
) -> None:
    records = mapped_records(tmp_path)
    stable_run = records.run.model_copy(
        update={
            "config_hash": f"sha256:{'1' * 64}",
            "parameter_hash": f"sha256:{'2' * 64}",
            "artifact_manifest_hash": f"sha256:{'3' * 64}",
        }
    )
    stable_snapshot = records.snapshot.model_copy(
        update={"content_hash": f"sha256:{'4' * 64}"}
    )
    report_card_id = derive_deterministic_etf_report_card_id(
        run=stable_run,
        data_snapshot=stable_snapshot,
        benchmark_snapshot=stable_snapshot,
    )

    assert report_card_id == EXPECTED_REPORT_CARD_ID


def test_generated_report_card_identity_verifies_successfully(tmp_path: Path) -> None:
    report_card = report_card_from_records(mapped_records(tmp_path))

    verify_deterministic_etf_report_card_identity(report_card)


def test_exact_replay_report_card_identity_verifies_successfully(
    tmp_path: Path,
) -> None:
    records = mapped_records(tmp_path)
    first = report_card_from_records(records)
    second = report_card_from_records(records)

    verify_deterministic_etf_report_card_identity(first)
    verify_deterministic_etf_report_card_identity(second)

    assert first == second


def test_metric_change_does_not_redefine_report_card_identity(
    tmp_path: Path,
) -> None:
    report_card = report_card_from_records(mapped_records(tmp_path))
    changed_metrics = report_card.metrics.model_copy(
        update={"total_return": "0.000000000000"}
    )
    changed_report_card = report_card.model_copy(update={"metrics": changed_metrics})

    verify_deterministic_etf_report_card_identity(changed_report_card)

    assert changed_report_card.report_card_id == report_card.report_card_id
    assert canonical_json_bytes(changed_report_card) != canonical_json_bytes(
        report_card
    )


def test_changed_identity_hash_with_unchanged_report_card_id_is_rejected(
    tmp_path: Path,
) -> None:
    report_card = report_card_from_records(mapped_records(tmp_path))
    changed_lineage = report_card.lineage.model_copy(
        update={"config_hash": f"sha256:{'9' * 64}"}
    )
    stale = report_card.model_copy(update={"lineage": changed_lineage})

    with pytest.raises(
        report_cards.DeterministicETFReportCardError,
        match="stale|inconsistent",
    ):
        verify_deterministic_etf_report_card_identity(stale)


def test_changed_source_run_id_with_unchanged_report_card_id_is_rejected(
    tmp_path: Path,
) -> None:
    report_card = report_card_from_records(mapped_records(tmp_path))
    stale = report_card.model_copy(update={"source_run_id": f"run-{'9' * 64}"})

    with pytest.raises(
        report_cards.DeterministicETFReportCardError,
        match="stale|inconsistent",
    ):
        verify_deterministic_etf_report_card_identity(stale)


def test_stale_valid_format_report_card_id_is_rejected(tmp_path: Path) -> None:
    report_card = report_card_from_records(mapped_records(tmp_path))
    stale = report_card.model_copy(update={"report_card_id": f"report-card-{'9' * 64}"})

    with pytest.raises(
        report_cards.DeterministicETFReportCardError,
        match="stale|inconsistent",
    ):
        verify_deterministic_etf_report_card_identity(stale)


def test_malformed_report_card_id_is_rejected_by_verifier(tmp_path: Path) -> None:
    report_card = report_card_from_records(mapped_records(tmp_path))
    malformed = report_card.model_copy(update={"report_card_id": "report-card-short"})

    with pytest.raises(
        report_cards.DeterministicETFReportCardError,
        match="report_card_id",
    ):
        verify_deterministic_etf_report_card_identity(malformed)


def test_unsupported_derivation_policy_is_rejected_by_verifier(
    tmp_path: Path,
) -> None:
    report_card = report_card_from_records(mapped_records(tmp_path))
    stale = report_card.model_copy(update={"derivation_policy_version": "future-v2"})

    with pytest.raises(
        report_cards.DeterministicETFReportCardError,
        match="derivation policy",
    ):
        verify_deterministic_etf_report_card_identity(stale)


def test_report_card_identity_ignores_run_review_metadata(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    changed_review_run = records.run.model_copy(
        update={
            "review": ReviewMetadata(
                review_status=ReviewStatus.PENDING,
                decision="changed review metadata",
                risk_approval_required=True,
            )
        }
    )

    original = report_card_from_records(records)
    changed = build_deterministic_etf_report_card(
        run=changed_review_run,
        data_snapshot=records.snapshot,
        benchmark_snapshot=records.snapshot,
        artifact_manifest_id=records.manifest_id,
        artifact_manifest=records.artifact_manifest,
    )

    assert changed.report_card_id == original.report_card_id


def test_config_artifact_hash_matches_run_config_hash(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    config_entry = artifact_entry_by_filename(
        records.artifact_manifest,
        "config.json",
    )

    assert config_entry.content_hash == records.run.config_hash
    report_card_from_records(records)


def test_changed_run_config_hash_with_unchanged_manifest_is_rejected(
    tmp_path: Path,
) -> None:
    records = mapped_records(tmp_path)
    changed_run = records.run.model_copy(update={"config_hash": f"sha256:{'9' * 64}"})

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="config"):
        build_deterministic_etf_report_card(
            run=changed_run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=records.snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=records.artifact_manifest,
        )


def test_changed_config_entry_hash_with_rehashed_manifest_is_rejected(
    tmp_path: Path,
) -> None:
    records = mapped_records(tmp_path)
    changed_entries = tuple(
        entry.model_copy(update={"content_hash": f"sha256:{'8' * 64}"})
        if entry.artifact_kind is ArtifactKind.CONFIG
        else entry
        for entry in records.artifact_manifest.artifacts
    )
    changed_manifest = records.artifact_manifest.model_copy(
        update={"artifacts": changed_entries}
    )
    changed_manifest_hash = (
        f"sha256:{file_sha256_bytes(canonical_json_bytes(changed_manifest))}"
    )
    changed_run = records.run.model_copy(
        update={"artifact_manifest_hash": changed_manifest_hash}
    )

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="config"):
        build_deterministic_etf_report_card(
            run=changed_run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=records.snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=changed_manifest,
        )


def test_supplied_manifest_matches_run_artifact_manifest_hash(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    expected_hash = (
        f"sha256:{file_sha256_bytes(canonical_json_bytes(records.artifact_manifest))}"
    )

    assert records.run.artifact_manifest_hash == expected_hash
    report_card_from_records(records)


def test_changed_manifest_entry_with_unchanged_run_hash_is_rejected(
    tmp_path: Path,
) -> None:
    records = mapped_records(tmp_path)
    changed_entry = records.artifact_manifest.artifacts[0].model_copy(
        update={"validator_version": "changed-validator"}
    )
    changed_manifest = records.artifact_manifest.model_copy(
        update={
            "artifacts": (changed_entry, *records.artifact_manifest.artifacts[1:]),
        }
    )

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="hash"):
        build_deterministic_etf_report_card(
            run=records.run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=records.snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=changed_manifest,
        )


def test_changed_manifest_created_at_with_unchanged_run_hash_is_rejected(
    tmp_path: Path,
) -> None:
    records = mapped_records(tmp_path)
    changed_manifest = records.artifact_manifest.model_copy(
        update={"created_at": datetime(2026, 2, 7, tzinfo=UTC)}
    )

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="hash"):
        build_deterministic_etf_report_card(
            run=records.run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=records.snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=changed_manifest,
        )


def test_changed_artifact_uri_with_unchanged_run_hash_is_rejected(
    tmp_path: Path,
) -> None:
    records = mapped_records(tmp_path)
    changed_entry = records.artifact_manifest.artifacts[0].model_copy(
        update={"uri": f"{records.artifact_manifest.artifact_root_uri}/wrong.json"}
    )
    changed_manifest = records.artifact_manifest.model_copy(
        update={
            "artifacts": (changed_entry, *records.artifact_manifest.artifacts[1:]),
        }
    )

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="URI"):
        build_deterministic_etf_report_card(
            run=records.run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=records.snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=changed_manifest,
        )


def test_malformed_run_artifact_manifest_hash_is_rejected(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    changed_run = records.run.model_copy(update={"artifact_manifest_hash": "bad"})

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="sha256"):
        build_deterministic_etf_report_card(
            run=changed_run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=records.snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=records.artifact_manifest,
        )


def test_valid_deterministic_manifest_id_is_accepted(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)

    assert records.manifest_id == f"manifest-{records.run.run_id.removeprefix('run-')}"
    report_card_from_records(records)


@pytest.mark.parametrize(
    "manifest_id",
    [
        "manifest-arbitrary",
        "manifest-" + ("a" * 63),
        "manifest-" + ("f" * 64),
    ],
)
def test_invalid_manifest_id_is_rejected(
    tmp_path: Path,
    manifest_id: str,
) -> None:
    records = mapped_records(tmp_path)

    with pytest.raises(
        report_cards.DeterministicETFReportCardError,
        match="artifact_manifest_id",
    ):
        build_deterministic_etf_report_card(
            run=records.run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=records.snapshot,
            artifact_manifest_id=manifest_id,
            artifact_manifest=records.artifact_manifest,
        )


@pytest.mark.parametrize(
    "run_id",
    [
        "bad-run",
        "run-" + ("a" * 63),
        "run-" + ("A" * 64),
    ],
)
def test_malformed_run_id_is_rejected(tmp_path: Path, run_id: str) -> None:
    records = mapped_records(tmp_path)
    changed_run = records.run.model_copy(update={"run_id": run_id})

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="run_id"):
        build_deterministic_etf_report_card(
            run=changed_run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=records.snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=records.artifact_manifest,
        )


def test_mismatched_run_artifact_root_is_rejected(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    changed_manifest = records.artifact_manifest.model_copy(
        update={"artifact_root_uri": "file:///tmp/other-root"}
    )

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="root URI"):
        build_deterministic_etf_report_card(
            run=records.run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=records.snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=changed_manifest,
        )


def test_mismatched_run_manifest_uri_is_rejected(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    changed_run = records.run.model_copy(
        update={"artifact_manifest_uri": "file:///tmp/wrong/artifact_manifest.json"}
    )

    with pytest.raises(
        report_cards.DeterministicETFReportCardError,
        match="artifact_manifest_uri",
    ):
        build_deterministic_etf_report_card(
            run=changed_run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=records.snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=records.artifact_manifest,
        )


def test_artifact_entry_uri_outside_root_is_rejected(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    changed_entry = records.artifact_manifest.artifacts[0].model_copy(
        update={"uri": "file:///tmp/outside/config.json"}
    )
    changed_manifest = records.artifact_manifest.model_copy(
        update={
            "artifacts": (changed_entry, *records.artifact_manifest.artifacts[1:]),
        }
    )

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="URI"):
        build_deterministic_etf_report_card(
            run=records.run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=records.snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=changed_manifest,
        )


def test_artifact_entry_filename_uri_mismatch_is_rejected(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    changed_entry = records.artifact_manifest.artifacts[0].model_copy(
        update={
            "uri": f"{records.artifact_manifest.artifact_root_uri}/metrics.json",
        }
    )
    changed_manifest = records.artifact_manifest.model_copy(
        update={
            "artifacts": (changed_entry, *records.artifact_manifest.artifacts[1:]),
        }
    )

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="URI"):
        build_deterministic_etf_report_card(
            run=records.run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=records.snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=changed_manifest,
        )


def test_report_card_builder_performs_no_filesystem_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = mapped_records(tmp_path)

    def fail_write(*args: object, **kwargs: object) -> None:
        raise AssertionError("report-card builder must not write files")

    monkeypatch.setattr(Path, "write_bytes", fail_write)
    monkeypatch.setattr(Path, "write_text", fail_write)

    report_card_from_records(records)


def test_report_card_builder_rejects_non_completed_runs(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    changed_run = records.run.model_copy(update={"status": ExperimentRunStatus.FAILED})

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="completed"):
        build_deterministic_etf_report_card(
            run=changed_run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=records.snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=records.artifact_manifest,
        )


def test_report_card_builder_rejects_incomplete_run_artifacts(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    changed_run = records.run.model_copy(update={"artifacts_incomplete": True})

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="complete"):
        build_deterministic_etf_report_card(
            run=changed_run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=records.snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=records.artifact_manifest,
        )


def test_report_card_builder_rejects_incomplete_artifact_manifest(
    tmp_path: Path,
) -> None:
    records = mapped_records(tmp_path)
    changed_manifest = records.artifact_manifest.model_copy(
        update={"required_artifacts_complete": False}
    )

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="complete"):
        build_deterministic_etf_report_card(
            run=records.run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=records.snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=changed_manifest,
        )


def test_report_card_builder_rejects_missing_required_artifact(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    changed_manifest = records.artifact_manifest.model_copy(
        update={"artifacts": records.artifact_manifest.artifacts[:-1]}
    )

    with pytest.raises(
        report_cards.DeterministicETFReportCardError,
        match="every required artifact",
    ):
        build_deterministic_etf_report_card(
            run=records.run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=records.snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=changed_manifest,
        )


def test_report_card_builder_rejects_non_produced_required_artifact(
    tmp_path: Path,
) -> None:
    records = mapped_records(tmp_path)
    changed_entry = records.artifact_manifest.artifacts[0].model_copy(
        update={"status": ArtifactStatus.MISSING}
    )
    changed_manifest = records.artifact_manifest.model_copy(
        update={
            "required_artifacts_complete": False,
            "artifacts": (changed_entry, *records.artifact_manifest.artifacts[1:]),
        }
    )

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="complete"):
        build_deterministic_etf_report_card(
            run=records.run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=records.snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=changed_manifest,
        )


def test_report_card_builder_rejects_data_snapshot_mismatch(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    changed_snapshot = records.snapshot.model_copy(update={"snapshot_id": "other"})

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="data"):
        build_deterministic_etf_report_card(
            run=records.run,
            data_snapshot=changed_snapshot,
            benchmark_snapshot=changed_snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=records.artifact_manifest,
        )


def test_report_card_builder_rejects_benchmark_snapshot_mismatch(
    tmp_path: Path,
) -> None:
    records = mapped_records(tmp_path)
    changed_snapshot = records.snapshot.model_copy(update={"snapshot_id": "other"})

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="benchmark"):
        build_deterministic_etf_report_card(
            run=records.run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=changed_snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=records.artifact_manifest,
        )


def test_separate_data_and_benchmark_snapshot_contracts_are_rejected(
    tmp_path: Path,
) -> None:
    records = mapped_records(tmp_path)
    benchmark_snapshot = records.snapshot.model_copy(update={"created_by": "other"})

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="shared"):
        build_deterministic_etf_report_card(
            run=records.run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=benchmark_snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=records.artifact_manifest,
        )


def test_differing_snapshot_content_hashes_are_rejected(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    benchmark_snapshot = records.snapshot.model_copy(
        update={"content_hash": f"sha256:{'0' * 64}"}
    )

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="shared"):
        build_deterministic_etf_report_card(
            run=records.run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=benchmark_snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=records.artifact_manifest,
        )


def test_non_research_generated_source_is_rejected(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    changed_snapshot = records.snapshot.model_copy(
        update={"source_type": DataSourceType.VENDOR, "vendor_name": "vendor"}
    )

    with pytest.raises(
        report_cards.DeterministicETFReportCardError,
        match="research_generated",
    ):
        build_deterministic_etf_report_card(
            run=records.run,
            data_snapshot=changed_snapshot,
            benchmark_snapshot=changed_snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=records.artifact_manifest,
        )


def test_non_market_data_snapshot_is_rejected(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    changed_snapshot = records.snapshot.model_copy(
        update={"snapshot_kind": DataSnapshotKind.BENCHMARK_DATA}
    )

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="market"):
        build_deterministic_etf_report_card(
            run=records.run,
            data_snapshot=changed_snapshot,
            benchmark_snapshot=changed_snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=records.artifact_manifest,
        )


def test_non_raw_adjustment_policy_is_rejected(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    changed_snapshot = records.snapshot.model_copy(
        update={"adjustment_policy": DataAdjustmentPolicy.SPLIT_ADJUSTED}
    )

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="raw"):
        build_deterministic_etf_report_card(
            run=records.run,
            data_snapshot=changed_snapshot,
            benchmark_snapshot=changed_snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=records.artifact_manifest,
        )


def test_unsupported_temporal_coverage_is_rejected(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    changed_snapshot = records.snapshot.model_copy(
        update={"temporal_coverage": TemporalCoverage.LATEST_KNOWN}
    )

    with pytest.raises(
        report_cards.DeterministicETFReportCardError,
        match="point_in_time",
    ):
        build_deterministic_etf_report_card(
            run=records.run,
            data_snapshot=changed_snapshot,
            benchmark_snapshot=changed_snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=records.artifact_manifest,
        )


def test_report_card_builder_rejects_artifact_run_mismatch(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    changed_manifest = records.artifact_manifest.model_copy(update={"run_id": "other"})

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="run_id"):
        build_deterministic_etf_report_card(
            run=records.run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=records.snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=changed_manifest,
        )


def test_report_card_builder_rejects_artifact_experiment_mismatch(
    tmp_path: Path,
) -> None:
    records = mapped_records(tmp_path)
    changed_manifest = records.artifact_manifest.model_copy(
        update={"experiment_id": "other"}
    )

    with pytest.raises(
        report_cards.DeterministicETFReportCardError,
        match="experiment_id",
    ):
        build_deterministic_etf_report_card(
            run=records.run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=records.snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=changed_manifest,
        )


def test_report_card_builder_rejects_frequency_mismatch(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    changed_snapshot = records.snapshot.model_copy(update={"frequency": "weekly"})

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="frequency"):
        build_deterministic_etf_report_card(
            run=records.run,
            data_snapshot=changed_snapshot,
            benchmark_snapshot=changed_snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=records.artifact_manifest,
        )


def test_report_card_builder_rejects_time_range_mismatch(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    changed_snapshot = records.snapshot.model_copy(
        update={
            "time_range": TimeRange(
                start_date=date(2026, 2, 1),
                end_date=records.snapshot.time_range.end_date,
            )
        }
    )

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="start"):
        build_deterministic_etf_report_card(
            run=records.run,
            data_snapshot=changed_snapshot,
            benchmark_snapshot=changed_snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=records.artifact_manifest,
        )


def test_report_card_builder_rejects_missing_metric(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    changed_metrics = dict(records.run.metrics_summary)
    del changed_metrics["total_return"]
    changed_run = records.run.model_copy(update={"metrics_summary": changed_metrics})

    with pytest.raises(
        report_cards.DeterministicETFReportCardError,
        match="approved metrics",
    ):
        build_deterministic_etf_report_card(
            run=changed_run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=records.snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=records.artifact_manifest,
        )


def test_report_card_builder_rejects_invalid_metric_type(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    changed_metrics = dict(records.run.metrics_summary)
    changed_metrics["total_return"] = 0
    changed_run = records.run.model_copy(update={"metrics_summary": changed_metrics})

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="decimal"):
        build_deterministic_etf_report_card(
            run=changed_run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=records.snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=records.artifact_manifest,
        )


@pytest.mark.parametrize(
    ("metric_name", "metric_value"),
    [
        ("total_return", "0.1"),
        ("realized_commission", "9.9919980"),
        ("total_return", "00.100000000000"),
        ("total_return", "+0.100000000000"),
        ("total_return", "1E-12"),
        ("total_return", "NaN"),
        ("total_return", "Infinity"),
        ("total_return", "-0.000000000000"),
        ("benchmark_total_return", "-0.000000000000"),
        ("excess_return", "-0.000000000000"),
        ("maximum_drawdown", "-0.000000000000"),
        ("realized_commission", "-0.000000"),
        ("realized_slippage", "-0.000000"),
        ("ending_equity", "-0.000000"),
        ("realized_commission", "-0.000001"),
        ("realized_slippage", "-0.000001"),
        ("ending_equity", "-1.000000"),
        ("maximum_drawdown", "0.000000000001"),
    ],
)
def test_report_card_builder_rejects_noncanonical_metric_values(
    tmp_path: Path,
    metric_name: str,
    metric_value: str,
) -> None:
    records = mapped_records(tmp_path)
    changed_metrics = dict(records.run.metrics_summary)
    changed_metrics[metric_name] = metric_value
    changed_run = records.run.model_copy(update={"metrics_summary": changed_metrics})

    with pytest.raises(report_cards.DeterministicETFReportCardError):
        build_deterministic_etf_report_card(
            run=changed_run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=records.snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=records.artifact_manifest,
        )


@pytest.mark.parametrize(
    "field_name",
    [
        "data_snapshot.content_hash",
        "benchmark_snapshot.content_hash",
        "run.config_hash",
        "run.parameter_hash",
        "run.artifact_manifest_hash",
    ],
)
def test_report_card_identity_input_hashes_must_be_full_sha256(
    tmp_path: Path,
    field_name: str,
) -> None:
    records = mapped_records(tmp_path)
    run = records.run
    data_snapshot = records.snapshot
    benchmark_snapshot = records.snapshot
    if field_name == "data_snapshot.content_hash":
        data_snapshot = records.snapshot.model_copy(update={"content_hash": "sha256:1"})
    elif field_name == "benchmark_snapshot.content_hash":
        benchmark_snapshot = records.snapshot.model_copy(
            update={"content_hash": "sha256:1"}
        )
    elif field_name == "run.config_hash":
        run = records.run.model_copy(update={"config_hash": "sha256:1"})
    elif field_name == "run.parameter_hash":
        run = records.run.model_copy(update={"parameter_hash": "sha256:1"})
    else:
        run = records.run.model_copy(update={"artifact_manifest_hash": "sha256:1"})

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="sha256"):
        derive_deterministic_etf_report_card_id(
            run=run,
            data_snapshot=data_snapshot,
            benchmark_snapshot=benchmark_snapshot,
        )


def test_report_card_identity_helper_rejects_non_completed_run(
    tmp_path: Path,
) -> None:
    records = mapped_records(tmp_path)
    changed_run = records.run.model_copy(update={"status": ExperimentRunStatus.FAILED})

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="completed"):
        derive_deterministic_etf_report_card_id(
            run=changed_run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=records.snapshot,
        )


def test_report_card_identity_helper_rejects_mismatched_snapshots(
    tmp_path: Path,
) -> None:
    records = mapped_records(tmp_path)
    benchmark_snapshot = records.snapshot.model_copy(update={"created_by": "other"})

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="shared"):
        derive_deterministic_etf_report_card_id(
            run=records.run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=benchmark_snapshot,
        )


def test_report_card_identity_helper_rejects_data_snapshot_reference_mismatch(
    tmp_path: Path,
) -> None:
    records = mapped_records(tmp_path)
    changed_run = records.run.model_copy(update={"data_snapshot_id": "other"})

    with pytest.raises(
        report_cards.DeterministicETFReportCardError,
        match="data_snapshot_id",
    ):
        derive_deterministic_etf_report_card_id(
            run=changed_run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=records.snapshot,
        )


def test_report_card_identity_helper_rejects_benchmark_snapshot_reference_mismatch(
    tmp_path: Path,
) -> None:
    records = mapped_records(tmp_path)
    benchmark = records.run.benchmark.model_copy(update={"snapshot_id": "other"})
    changed_run = records.run.model_copy(update={"benchmark": benchmark})

    with pytest.raises(
        report_cards.DeterministicETFReportCardError,
        match="benchmark",
    ):
        derive_deterministic_etf_report_card_id(
            run=changed_run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=records.snapshot,
        )


def test_report_card_builder_rejects_unsupported_strategy(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    changed_run = records.run.model_copy(update={"strategy_id": "other"})

    with pytest.raises(report_cards.DeterministicETFReportCardError, match="strategy"):
        build_deterministic_etf_report_card(
            run=changed_run,
            data_snapshot=records.snapshot,
            benchmark_snapshot=records.snapshot,
            artifact_manifest_id=records.manifest_id,
            artifact_manifest=records.artifact_manifest,
        )


def test_output_metric_changes_do_not_change_engine_owned_run_id() -> None:
    result = completed_result()
    changed_result = result.model_copy(
        update={
            "metrics": result.metrics.model_copy(update={"total_return": Decimal("0")})
        }
    )

    assert changed_result.run_id == result.run_id
    assert derive_execution_identity(
        config=changed_result.resolved_config,
        execution_metadata=changed_result.execution_metadata,
        fixture_content_hash=changed_result.fixture_content_hash,
    ) == derive_execution_identity(
        config=result.resolved_config,
        execution_metadata=result.execution_metadata,
        fixture_content_hash=result.fixture_content_hash,
    )


def test_report_card_builder_imports_no_database_or_persistence_modules() -> None:
    tree = ast.parse(inspect.getsource(report_cards))

    prohibited_imports = {
        "sqlalchemy",
        "psycopg",
        "research_sdk.persistence",
        "research_sdk.experiment_recording",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert prohibited_imports.isdisjoint({alias.name for alias in node.names})
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert not any(
                module == name or module.startswith(f"{name}.")
                for name in prohibited_imports
            )


@pytest.mark.parametrize(
    "module_name",
    [
        "research_sdk.contracts.report_cards",
        "backtest_engine.report_cards",
    ],
)
def test_report_card_import_boundary_does_not_load_database_modules(
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


def test_full_report_card_execution_does_not_load_database_modules() -> None:
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
    build_deterministic_etf_report_card,
    generate_artifact_bundle,
    load_daily_bar_snapshot,
    map_completed_backtest_to_ledger_records,
    run_buy_and_hold_backtest,
    verify_deterministic_etf_report_card_identity,
)
from research_sdk.contracts import ReviewMetadata, ReviewStatus

fixture_path = Path({str(FIXTURE_PATH)!r})
artifact_root = Path(tempfile.mkdtemp(prefix="report-card-boundary-"))
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
    metadata = ExecutionMetadata(
        git_commit_sha="9d18ce75a48beb65a2c633bcd80b440ebbabff20",
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
        execution_metadata=metadata,
    )
    artifacts = generate_artifact_bundle(result=result, artifact_base_dir=artifact_root)
    records = map_completed_backtest_to_ledger_records(
        CompletedBacktestLedgerMappingInput(
            result=result,
            artifacts=artifacts,
            fixture_path=fixture_path,
            created_by="agent-codex",
            review=ReviewMetadata(
                review_status=ReviewStatus.PENDING,
                risk_approval_required=True,
            ),
        )
    )
    report_card = build_deterministic_etf_report_card(
        run=records.run,
        data_snapshot=records.snapshot,
        benchmark_snapshot=records.snapshot,
        artifact_manifest_id=records.manifest_id,
        artifact_manifest=records.artifact_manifest,
    )
    verify_deterministic_etf_report_card_identity(report_card)
    assert report_card.source_run_id == records.run.run_id
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
        "full report-card execution loaded forbidden modules: "
        f"{completed.stdout}\nstderr:\n{completed.stderr}"
    )


def mapped_records(tmp_path: Path):
    result = completed_result()
    artifacts = generate_artifact_bundle(
        result=result,
        artifact_base_dir=tmp_path / "artifacts",
    )
    return map_completed_backtest_to_ledger_records(
        CompletedBacktestLedgerMappingInput(
            result=result,
            artifacts=artifacts,
            fixture_path=FIXTURE_PATH,
            created_by="agent-codex",
            review=ReviewMetadata(
                review_status=ReviewStatus.PENDING,
                risk_approval_required=True,
            ),
        )
    )


def report_card_from_records(records):
    return build_deterministic_etf_report_card(
        run=records.run,
        data_snapshot=records.snapshot,
        benchmark_snapshot=records.snapshot,
        artifact_manifest_id=records.manifest_id,
        artifact_manifest=records.artifact_manifest,
    )


def completed_result():
    snapshot, fixture_hash = load_daily_bar_snapshot(FIXTURE_PATH)
    return run_buy_and_hold_backtest(
        config=resolved_config(),
        snapshot=snapshot,
        fixture_content_hash=fixture_hash,
        execution_metadata=execution_metadata(),
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


def execution_metadata() -> ExecutionMetadata:
    return ExecutionMetadata(
        git_commit_sha="9d18ce75a48beb65a2c633bcd80b440ebbabff20",
        repo_dirty=False,
        python_version="3.13.14",
        platform="test-platform",
        dependency_lock_hash="sha256:test-lock",
        execution_command="python -m backtest_engine",
    )


def artifact_entry_by_filename(manifest: RunArtifactManifest, filename: str):
    return next(entry for entry in manifest.artifacts if entry.filename == filename)
