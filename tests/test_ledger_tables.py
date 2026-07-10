from __future__ import annotations

from sqlalchemy import CheckConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import CreateIndex, CreateTable

from research_sdk.persistence.metadata import metadata
from research_sdk.persistence.tables import (
    LEDGER_ANCHOR_TABLES,
    data_snapshot_manifests,
    experiment_runs,
)

EXPECTED_TABLE_NAMES = {
    "experiment_runs",
    "data_snapshot_manifests",
}

EXPECTED_EXPERIMENT_RUN_COLUMNS = {
    "run_id",
    "experiment_id",
    "schema_version",
    "status",
    "created_at",
    "created_by",
    "status_updated_at",
    "status_updated_by",
    "strategy_id",
    "strategy_version",
    "git_commit_sha",
    "repo_dirty",
    "asset_class",
    "frequency",
    "data_snapshot_id",
    "feature_snapshot_id",
    "artifact_uri",
    "artifact_manifest_uri",
    "artifact_manifest_hash",
    "parent_run_id",
    "supersedes_run_id",
    "review_status",
    "reviewer_id",
    "review_role",
    "reviewed_at",
    "risk_approval_required",
    "contract_hash",
    "raw_contract",
    "inserted_at",
}

EXPECTED_DATA_SNAPSHOT_COLUMNS = {
    "snapshot_id",
    "schema_version",
    "snapshot_kind",
    "status",
    "created_at",
    "created_by",
    "asset_class",
    "frequency",
    "data_root_uri",
    "source_dataset",
    "source_version",
    "source_type",
    "vendor_name",
    "temporal_coverage",
    "as_of",
    "available_at",
    "ingestion_completed_at",
    "adjustment_policy",
    "calendar",
    "timezone",
    "row_count",
    "file_count",
    "size_bytes",
    "contract_hash",
    "raw_contract",
    "inserted_at",
}

NULLABLE_EXPERIMENT_RUN_COLUMNS = {
    "feature_snapshot_id",
    "parent_run_id",
    "supersedes_run_id",
    "reviewer_id",
    "review_role",
    "reviewed_at",
}

NULLABLE_DATA_SNAPSHOT_COLUMNS = {
    "vendor_name",
    "file_count",
    "size_bytes",
}

EXPECTED_EXPERIMENT_RUN_CHECKS = {
    "ck_experiment_runs_parent_run_id_not_self",
    "ck_experiment_runs_supersedes_run_id_not_self",
    "ck_experiment_runs_status_values",
    "ck_experiment_runs_asset_class_values",
    "ck_experiment_runs_review_status_values",
    "ck_experiment_runs_review_role_values",
}

EXPECTED_DATA_SNAPSHOT_CHECKS = {
    "ck_data_snapshot_manifests_row_count_nonnegative",
    "ck_data_snapshot_manifests_file_count_nonnegative",
    "ck_data_snapshot_manifests_size_bytes_nonnegative",
    "ck_data_snapshot_manifests_snapshot_kind_values",
    "ck_data_snapshot_manifests_status_values",
    "ck_data_snapshot_manifests_asset_class_values",
    "ck_data_snapshot_manifests_source_type_values",
    "ck_data_snapshot_manifests_temporal_coverage_values",
    "ck_data_snapshot_manifests_adjustment_policy_values",
}

EXPECTED_INDEXES = {
    "experiment_runs": {
        "ix_experiment_runs_status_created_at": ("status", "created_at"),
        "ix_experiment_runs_strategy_id_created_at": ("strategy_id", "created_at"),
        "ix_experiment_runs_experiment_id_created_at": (
            "experiment_id",
            "created_at",
        ),
        "ix_experiment_runs_data_snapshot_id": ("data_snapshot_id",),
        "ix_experiment_runs_parent_run_id": ("parent_run_id",),
        "ix_experiment_runs_supersedes_run_id": ("supersedes_run_id",),
    },
    "data_snapshot_manifests": {
        "ix_data_snapshot_manifests_snapshot_kind_status_created_at": (
            "snapshot_kind",
            "status",
            "created_at",
        ),
        "ix_data_snapshot_manifests_asset_source_created_at": (
            "asset_class",
            "source_dataset",
            "created_at",
        ),
    },
}


def test_metadata_contains_only_ledger_anchor_tables() -> None:
    assert set(metadata.tables) == EXPECTED_TABLE_NAMES
    assert LEDGER_ANCHOR_TABLES == (
        experiment_runs,
        data_snapshot_manifests,
    )


def test_ledger_anchor_tables_have_expected_columns() -> None:
    assert set(experiment_runs.c.keys()) == EXPECTED_EXPERIMENT_RUN_COLUMNS
    assert set(data_snapshot_manifests.c.keys()) == EXPECTED_DATA_SNAPSHOT_COLUMNS


def test_ledger_anchor_table_nullability_matches_scope() -> None:
    for column in experiment_runs.c:
        expected_nullable = column.name in NULLABLE_EXPERIMENT_RUN_COLUMNS
        assert column.nullable is expected_nullable

    for column in data_snapshot_manifests.c:
        expected_nullable = column.name in NULLABLE_DATA_SNAPSHOT_COLUMNS
        assert column.nullable is expected_nullable


def test_ledger_anchor_table_primary_keys_match_contract_ids() -> None:
    assert [column.name for column in experiment_runs.primary_key] == ["run_id"]
    assert [column.name for column in data_snapshot_manifests.primary_key] == [
        "snapshot_id"
    ]


def test_raw_contract_columns_use_postgresql_jsonb() -> None:
    assert isinstance(experiment_runs.c.raw_contract.type, JSONB)
    assert isinstance(data_snapshot_manifests.c.raw_contract.type, JSONB)


def test_inserted_at_columns_have_server_defaults() -> None:
    assert experiment_runs.c.inserted_at.server_default is not None
    assert data_snapshot_manifests.c.inserted_at.server_default is not None


def test_ledger_anchor_table_check_constraints_are_named() -> None:
    experiment_run_checks = {
        constraint.name
        for constraint in experiment_runs.constraints
        if isinstance(constraint, CheckConstraint)
    }
    data_snapshot_checks = {
        constraint.name
        for constraint in data_snapshot_manifests.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert experiment_run_checks == EXPECTED_EXPERIMENT_RUN_CHECKS
    assert data_snapshot_checks == EXPECTED_DATA_SNAPSHOT_CHECKS


def test_ledger_anchor_table_indexes_are_named_and_target_expected_columns() -> None:
    for table in LEDGER_ANCHOR_TABLES:
        actual_indexes = {
            index.name: tuple(column.name for column in index.columns)
            for index in table.indexes
        }

        assert actual_indexes == EXPECTED_INDEXES[table.name]


def test_ledger_anchor_tables_compile_for_postgresql_without_connection() -> None:
    dialect = postgresql.dialect()

    for table in LEDGER_ANCHOR_TABLES:
        compiled_table = str(CreateTable(table).compile(dialect=dialect))
        assert f"CREATE TABLE {table.name}" in compiled_table
        assert "JSONB" in compiled_table

        for index in table.indexes:
            compiled_index = str(CreateIndex(index).compile(dialect=dialect))
            assert f"CREATE INDEX {index.name}" in compiled_index
