"""Experiment ledger contracts for reproducible research runs."""

from datetime import date
from typing import Any, Self

from pydantic import field_validator, model_validator

from research_sdk.contracts.base import BaseContractModel
from research_sdk.contracts.enums import AssetClass, ExperimentRunStatus, FailureLabel
from research_sdk.contracts.review import ReviewMetadata
from research_sdk.contracts.schema import VersionedContract
from research_sdk.contracts.time import UtcDatetime
from research_sdk.contracts.types import NonEmptyString

type MetricScalar = int | float | str | bool | None


class TimeRange(BaseContractModel):
    """Inclusive date range covered by an experiment run."""

    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_date_order(self) -> Self:
        """Require the range end date to be on or after the start date."""

        if self.end_date < self.start_date:
            raise ValueError("end_date must be greater than or equal to start_date")
        return self


class AssetUniverseReference(BaseContractModel):
    """Reference to a point-in-time asset universe."""

    universe_id: NonEmptyString | None = None
    symbols: tuple[NonEmptyString, ...] | None = None
    as_of: UtcDatetime | None = None

    @model_validator(mode="after")
    def validate_universe_reference(self) -> Self:
        """Require either a universe identifier or at least one symbol."""

        if self.universe_id is None and not self.symbols:
            raise ValueError("must provide universe_id or non-empty symbols")
        return self


class BenchmarkReference(BaseContractModel):
    """Benchmark identifier and point-in-time snapshot reference."""

    benchmark_id: NonEmptyString
    snapshot_id: NonEmptyString


class RunEnvironment(BaseContractModel):
    """Minimal reproducibility metadata for an experiment run environment."""

    python_version: NonEmptyString
    platform: NonEmptyString
    runner: NonEmptyString
    container_image_digest: NonEmptyString | None = None


class RandomSeedMetadata(BaseContractModel):
    """Random seed metadata for stochastic or explicitly deterministic runs."""

    seed: int | None
    rationale: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_null_seed_rationale(self) -> Self:
        """Require a rationale when no random seed is recorded."""

        if self.seed is None and self.rationale is None:
            raise ValueError("rationale is required when seed is None")
        return self


class ExperimentRunRecord(VersionedContract):
    """Experiment ledger record for a reproducible research run."""

    run_id: NonEmptyString
    experiment_id: NonEmptyString
    created_at: UtcDatetime
    created_by: NonEmptyString
    status: ExperimentRunStatus
    status_updated_at: UtcDatetime
    status_updated_by: NonEmptyString
    strategy_id: NonEmptyString
    strategy_version: NonEmptyString
    git_commit_sha: NonEmptyString
    repo_dirty: bool
    asset_class: AssetClass
    asset_universe: AssetUniverseReference
    time_range: TimeRange
    frequency: NonEmptyString
    benchmark: BenchmarkReference
    data_snapshot_id: NonEmptyString
    config_uri: NonEmptyString
    config_hash: NonEmptyString
    artifact_uri: NonEmptyString
    artifact_manifest_uri: NonEmptyString
    artifact_manifest_hash: NonEmptyString
    cost_model: NonEmptyString
    slippage_model: NonEmptyString
    lookback: NonEmptyString
    lag_assumptions: NonEmptyString
    leakage_review: NonEmptyString
    environment: RunEnvironment
    dependency_lock_hash: NonEmptyString
    execution_command: NonEmptyString
    engine_version: NonEmptyString
    random_seed: RandomSeedMetadata
    parameter_hash: NonEmptyString
    metrics_summary: dict[str, MetricScalar]
    review: ReviewMetadata
    feature_snapshot_id: NonEmptyString | None = None
    parent_run_id: NonEmptyString | None = None
    supersedes_run_id: NonEmptyString | None = None
    failure_labels: tuple[FailureLabel, ...] = ()
    failure_reason: NonEmptyString | None = None
    failure_logs_uri: NonEmptyString | None = None
    artifacts_incomplete: bool = False

    @field_validator("metrics_summary", mode="before")
    @classmethod
    def validate_metrics_summary_scalars(
        cls,
        value: Any,
    ) -> dict[str, Any]:
        """Reject nested metrics objects before scalar union parsing."""

        if not isinstance(value, dict):
            raise ValueError("metrics_summary must be a dictionary")

        for metric_name, metric_value in value.items():
            if not isinstance(metric_name, str):
                raise ValueError("metrics_summary keys must be strings")
            if isinstance(metric_value, list | tuple | dict):
                raise ValueError("metrics_summary values must be scalar JSON values")

        return value

    @model_validator(mode="after")
    def validate_record_consistency(self) -> Self:
        """Validate structural consistency within a ledger record."""

        if self.status_updated_at < self.created_at:
            raise ValueError(
                "status_updated_at must be greater than or equal to created_at"
            )
        if self.parent_run_id == self.run_id:
            raise ValueError("parent_run_id cannot equal run_id")
        if self.supersedes_run_id == self.run_id:
            raise ValueError("supersedes_run_id cannot equal run_id")
        return self
