"""SQLAlchemy Core tables for experiment ledger persistence metadata."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from research_sdk.contracts.enums import (
    AssetClass,
    DataAdjustmentPolicy,
    DataSnapshotKind,
    DataSnapshotStatus,
    DataSourceType,
    ExperimentRunStatus,
    ReviewRole,
    ReviewStatus,
    TemporalCoverage,
)
from research_sdk.persistence.metadata import metadata


def _quoted_enum_values(enum_type: type[StrEnum]) -> str:
    return ", ".join(f"'{member.value}'" for member in enum_type)


experiment_runs = Table(
    "experiment_runs",
    metadata,
    Column("run_id", Text, primary_key=True),
    Column("experiment_id", Text, nullable=False),
    Column("schema_version", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("created_by", Text, nullable=False),
    Column("status_updated_at", DateTime(timezone=True), nullable=False),
    Column("status_updated_by", Text, nullable=False),
    Column("strategy_id", Text, nullable=False),
    Column("strategy_version", Text, nullable=False),
    Column("git_commit_sha", Text, nullable=False),
    Column("repo_dirty", Boolean, nullable=False),
    Column("asset_class", Text, nullable=False),
    Column("frequency", Text, nullable=False),
    Column("data_snapshot_id", Text, nullable=False),
    Column("feature_snapshot_id", Text, nullable=True),
    Column("artifact_uri", Text, nullable=False),
    Column("artifact_manifest_uri", Text, nullable=False),
    Column("artifact_manifest_hash", Text, nullable=False),
    Column("parent_run_id", Text, nullable=True),
    Column("supersedes_run_id", Text, nullable=True),
    Column("review_status", Text, nullable=False),
    Column("reviewer_id", Text, nullable=True),
    Column("review_role", Text, nullable=True),
    Column("reviewed_at", DateTime(timezone=True), nullable=True),
    Column("risk_approval_required", Boolean, nullable=False),
    Column("contract_hash", Text, nullable=False),
    Column("raw_contract", JSONB, nullable=False),
    Column(
        "inserted_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
    CheckConstraint(
        "parent_run_id IS NULL OR parent_run_id <> run_id",
        name="parent_run_id_not_self",
    ),
    CheckConstraint(
        "supersedes_run_id IS NULL OR supersedes_run_id <> run_id",
        name="supersedes_run_id_not_self",
    ),
    CheckConstraint(
        f"status IN ({_quoted_enum_values(ExperimentRunStatus)})",
        name="status_values",
    ),
    CheckConstraint(
        f"asset_class IN ({_quoted_enum_values(AssetClass)})",
        name="asset_class_values",
    ),
    CheckConstraint(
        f"review_status IN ({_quoted_enum_values(ReviewStatus)})",
        name="review_status_values",
    ),
    CheckConstraint(
        f"review_role IS NULL OR review_role IN ({_quoted_enum_values(ReviewRole)})",
        name="review_role_values",
    ),
)

Index(
    "ix_experiment_runs_status_created_at",
    experiment_runs.c.status,
    experiment_runs.c.created_at,
)
Index(
    "ix_experiment_runs_strategy_id_created_at",
    experiment_runs.c.strategy_id,
    experiment_runs.c.created_at,
)
Index(
    "ix_experiment_runs_experiment_id_created_at",
    experiment_runs.c.experiment_id,
    experiment_runs.c.created_at,
)
Index("ix_experiment_runs_data_snapshot_id", experiment_runs.c.data_snapshot_id)
Index("ix_experiment_runs_parent_run_id", experiment_runs.c.parent_run_id)
Index("ix_experiment_runs_supersedes_run_id", experiment_runs.c.supersedes_run_id)


data_snapshot_manifests = Table(
    "data_snapshot_manifests",
    metadata,
    Column("snapshot_id", Text, primary_key=True),
    Column("schema_version", Text, nullable=False),
    Column("snapshot_kind", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("created_by", Text, nullable=False),
    Column("asset_class", Text, nullable=False),
    Column("frequency", Text, nullable=False),
    Column("data_root_uri", Text, nullable=False),
    Column("source_dataset", Text, nullable=False),
    Column("source_version", Text, nullable=False),
    Column("source_type", Text, nullable=False),
    Column("vendor_name", Text, nullable=True),
    Column("temporal_coverage", Text, nullable=False),
    Column("as_of", DateTime(timezone=True), nullable=False),
    Column("available_at", DateTime(timezone=True), nullable=False),
    Column("ingestion_completed_at", DateTime(timezone=True), nullable=False),
    Column("adjustment_policy", Text, nullable=False),
    Column("calendar", Text, nullable=False),
    Column("timezone", Text, nullable=False),
    Column("row_count", BigInteger, nullable=False),
    Column("file_count", BigInteger, nullable=True),
    Column("size_bytes", BigInteger, nullable=True),
    Column("contract_hash", Text, nullable=False),
    Column("raw_contract", JSONB, nullable=False),
    Column(
        "inserted_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
    CheckConstraint("row_count >= 0", name="row_count_nonnegative"),
    CheckConstraint(
        "file_count IS NULL OR file_count >= 0",
        name="file_count_nonnegative",
    ),
    CheckConstraint(
        "size_bytes IS NULL OR size_bytes >= 0",
        name="size_bytes_nonnegative",
    ),
    CheckConstraint(
        f"snapshot_kind IN ({_quoted_enum_values(DataSnapshotKind)})",
        name="snapshot_kind_values",
    ),
    CheckConstraint(
        f"status IN ({_quoted_enum_values(DataSnapshotStatus)})",
        name="status_values",
    ),
    CheckConstraint(
        f"asset_class IN ({_quoted_enum_values(AssetClass)})",
        name="asset_class_values",
    ),
    CheckConstraint(
        f"source_type IN ({_quoted_enum_values(DataSourceType)})",
        name="source_type_values",
    ),
    CheckConstraint(
        f"temporal_coverage IN ({_quoted_enum_values(TemporalCoverage)})",
        name="temporal_coverage_values",
    ),
    CheckConstraint(
        f"adjustment_policy IN ({_quoted_enum_values(DataAdjustmentPolicy)})",
        name="adjustment_policy_values",
    ),
)

Index(
    "ix_data_snapshot_manifests_snapshot_kind_status_created_at",
    data_snapshot_manifests.c.snapshot_kind,
    data_snapshot_manifests.c.status,
    data_snapshot_manifests.c.created_at,
)
Index(
    "ix_data_snapshot_manifests_asset_source_created_at",
    data_snapshot_manifests.c.asset_class,
    data_snapshot_manifests.c.source_dataset,
    data_snapshot_manifests.c.created_at,
)


LEDGER_ANCHOR_TABLES = (
    experiment_runs,
    data_snapshot_manifests,
)
