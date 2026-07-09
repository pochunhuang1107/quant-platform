from copy import deepcopy
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from research_sdk.contracts import (
    AssetUniverseReference,
    ExperimentRunRecord,
    ExperimentRunStatus,
    FailureLabel,
    RandomSeedMetadata,
)


def valid_record_data() -> dict[str, Any]:
    return {
        "run_id": "run-20260709-001",
        "experiment_id": "exp-momentum-baseline",
        "schema_version": "1.0.0",
        "created_at": datetime(2026, 7, 9, 9, 0, 0, tzinfo=UTC),
        "created_by": "agent-codex",
        "status": "completed",
        "status_updated_at": datetime(2026, 7, 9, 9, 30, 0, tzinfo=UTC),
        "status_updated_by": "agent-codex",
        "strategy_id": "strategies/equities/momentum_baseline",
        "strategy_version": "0.1.0",
        "git_commit_sha": "761f0db",
        "repo_dirty": False,
        "asset_class": "equities",
        "asset_universe": {
            "universe_id": "sp500-point-in-time",
            "symbols": ("AAPL", "MSFT"),
            "as_of": datetime(
                2026,
                7,
                9,
                2,
                0,
                0,
                tzinfo=timezone(timedelta(hours=-7)),
            ),
        },
        "time_range": {
            "start_date": date(2020, 1, 1),
            "end_date": date(2025, 12, 31),
        },
        "frequency": "1d",
        "benchmark": {
            "benchmark_id": "SPY",
            "snapshot_id": "benchmark-snapshot-20260709",
        },
        "data_snapshot_id": "market-snapshot-20260709",
        "config_uri": "artifacts/run-20260709-001/config.json",
        "config_hash": "sha256:config",
        "artifact_uri": "artifacts/run-20260709-001",
        "artifact_manifest_uri": "artifacts/run-20260709-001/artifact_manifest.json",
        "artifact_manifest_hash": "sha256:manifest",
        "cost_model": "fixed 1bp transaction cost assumption",
        "slippage_model": "fixed 2bp slippage assumption",
        "lookback": "252 trading days",
        "lag_assumptions": "signals use data available at prior close",
        "leakage_review": "point-in-time universe and snapshot references recorded",
        "environment": {
            "python_version": "3.13.0",
            "platform": "macos-arm64",
            "runner": "local",
        },
        "dependency_lock_hash": "sha256:uv-lock",
        "execution_command": "uv run backtest --config config.json",
        "engine_version": "backtest-engine-placeholder-0.1.0",
        "random_seed": {
            "seed": 42,
        },
        "parameter_hash": "sha256:parameters",
        "metrics_summary": {
            "annual_return": 0.12,
            "trade_count": 123,
            "benchmark": "SPY",
            "passed_leakage_review": True,
            "notes": None,
        },
        "review": {
            "review_status": "pending",
            "risk_approval_required": True,
        },
    }


def test_experiment_run_record_accepts_complete_valid_record() -> None:
    record = ExperimentRunRecord(**valid_record_data())

    assert record.run_id == "run-20260709-001"
    assert record.status is ExperimentRunStatus.COMPLETED
    assert record.failure_labels == ()
    assert record.artifacts_incomplete is False


def test_experiment_run_status_contains_documented_values() -> None:
    assert {status.value for status in ExperimentRunStatus} == {
        "created",
        "running",
        "completed",
        "under_review",
        "accepted",
        "rejected",
        "failed",
        "invalid",
        "superseded",
        "cancelled",
    }


def test_failure_label_contains_documented_values() -> None:
    assert {label.value for label in FailureLabel} == {
        "data_unavailable",
        "data_validation_failed",
        "config_validation_failed",
        "leakage_check_failed",
        "artifact_validation_failed",
        "execution_error",
        "timeout",
        "resource_limit",
        "dependency_error",
        "unknown",
    }


def test_experiment_run_record_normalizes_utc_datetimes() -> None:
    data = valid_record_data()
    data["created_at"] = datetime(
        2026,
        7,
        9,
        2,
        0,
        0,
        tzinfo=timezone(timedelta(hours=-7)),
    )

    record = ExperimentRunRecord(**data)

    assert record.created_at == datetime(2026, 7, 9, 9, 0, 0, tzinfo=UTC)
    assert record.status_updated_at == datetime(2026, 7, 9, 9, 30, 0, tzinfo=UTC)
    assert record.asset_universe.as_of == datetime(2026, 7, 9, 9, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "field_path",
    [
        ("created_at",),
        ("status_updated_at",),
        ("asset_universe", "as_of"),
    ],
)
def test_experiment_run_record_rejects_naive_datetimes(
    field_path: tuple[str, ...],
) -> None:
    data = valid_record_data()
    target = data
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = datetime(2026, 7, 9, 9, 0, 0)

    with pytest.raises(ValidationError):
        ExperimentRunRecord(**data)


def test_experiment_run_record_rejects_invalid_status() -> None:
    data = valid_record_data()
    data["status"] = "approved_for_trading"

    with pytest.raises(ValidationError):
        ExperimentRunRecord(**data)


def test_experiment_run_record_rejects_unknown_extra_fields() -> None:
    data = valid_record_data()
    data["broker_account"] = "not-allowed"

    with pytest.raises(ValidationError):
        ExperimentRunRecord(**data)


@pytest.mark.parametrize(
    "field_name",
    [
        "artifact_manifest_uri",
        "artifact_manifest_hash",
        "review",
        "experiment_id",
        "git_commit_sha",
    ],
)
def test_experiment_run_record_requires_core_fields(field_name: str) -> None:
    data = valid_record_data()
    del data[field_name]

    with pytest.raises(ValidationError):
        ExperimentRunRecord(**data)


def test_time_range_rejects_end_date_before_start_date() -> None:
    data = valid_record_data()
    data["time_range"] = {
        "start_date": date(2025, 1, 1),
        "end_date": date(2024, 12, 31),
    }

    with pytest.raises(ValidationError, match="end_date"):
        ExperimentRunRecord(**data)


def test_experiment_run_record_rejects_status_update_before_creation() -> None:
    data = valid_record_data()
    data["status_updated_at"] = datetime(2026, 7, 9, 8, 59, 59, tzinfo=UTC)

    with pytest.raises(ValidationError, match="status_updated_at"):
        ExperimentRunRecord(**data)


def test_experiment_run_record_rejects_parent_run_id_matching_run_id() -> None:
    data = valid_record_data()
    data["parent_run_id"] = data["run_id"]

    with pytest.raises(ValidationError, match="parent_run_id"):
        ExperimentRunRecord(**data)


def test_experiment_run_record_rejects_supersedes_run_id_matching_run_id() -> None:
    data = valid_record_data()
    data["supersedes_run_id"] = data["run_id"]

    with pytest.raises(ValidationError, match="supersedes_run_id"):
        ExperimentRunRecord(**data)


@pytest.mark.parametrize(
    "asset_universe",
    [
        {},
        {"symbols": ()},
        {"symbols": []},
    ],
)
def test_asset_universe_reference_requires_identifier_or_symbols(
    asset_universe: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError, match="universe_id or non-empty symbols"):
        AssetUniverseReference(**asset_universe)


def test_asset_universe_reference_accepts_non_empty_symbols() -> None:
    reference = AssetUniverseReference(symbols=["AAPL", "MSFT"])

    assert reference.symbols == ("AAPL", "MSFT")


def test_metrics_summary_accepts_scalar_json_values() -> None:
    record = ExperimentRunRecord(**valid_record_data())

    assert record.metrics_summary == {
        "annual_return": 0.12,
        "trade_count": 123,
        "benchmark": "SPY",
        "passed_leakage_review": True,
        "notes": None,
    }


@pytest.mark.parametrize(
    "metric_value",
    [
        {"nested": 1},
        [1, 2],
    ],
)
def test_metrics_summary_rejects_nested_objects_and_lists(
    metric_value: object,
) -> None:
    data = valid_record_data()
    data["metrics_summary"] = {"bad_metric": metric_value}

    with pytest.raises(ValidationError, match="scalar JSON values"):
        ExperimentRunRecord(**data)


def test_random_seed_metadata_accepts_integer_seed() -> None:
    metadata = RandomSeedMetadata(seed=7)

    assert metadata.seed == 7
    assert metadata.rationale is None


def test_random_seed_metadata_accepts_null_seed_with_rationale() -> None:
    metadata = RandomSeedMetadata(
        seed=None,
        rationale="deterministic run with no random process",
    )

    assert metadata.seed is None
    assert metadata.rationale == "deterministic run with no random process"


def test_random_seed_metadata_rejects_null_seed_without_rationale() -> None:
    with pytest.raises(ValidationError, match="rationale"):
        RandomSeedMetadata(seed=None)


def test_experiment_run_record_has_no_workflow_or_artifact_behavior() -> None:
    record = ExperimentRunRecord(**valid_record_data())

    assert not hasattr(record, "approve")
    assert not hasattr(record, "transition_status")
    assert not hasattr(record, "validate_artifacts")


def test_optional_failure_metadata_is_contract_data_only() -> None:
    data = deepcopy(valid_record_data())
    data["failure_labels"] = ("execution_error", "timeout")
    data["failure_reason"] = "backtest exceeded runtime limit"
    data["failure_logs_uri"] = "artifacts/run-20260709-001/failure.log"
    data["artifacts_incomplete"] = True

    record = ExperimentRunRecord(**data)

    assert record.failure_labels == (
        FailureLabel.EXECUTION_ERROR,
        FailureLabel.TIMEOUT,
    )
    assert record.artifacts_incomplete is True
