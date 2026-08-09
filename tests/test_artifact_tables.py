from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import CreateIndex, CreateTable

from research_sdk.persistence.metadata import metadata
from research_sdk.persistence.tables import (
    ARTIFACT_TABLES,
    data_snapshot_manifests,
    experiment_runs,
    run_artifact_entries,
    run_artifact_manifests,
)

EXPECTED_TABLE_NAMES = {
    "experiment_runs",
    "data_snapshot_manifests",
    "run_artifact_manifests",
    "run_artifact_entries",
    "research_report_cards",
    "research_notes",
    "review_events",
}

EXPECTED_MANIFEST_COLUMNS = {
    "manifest_id",
    "run_id",
    "experiment_id",
    "schema_version",
    "artifact_root_uri",
    "created_at",
    "required_artifacts_complete",
    "contract_hash",
    "raw_contract",
    "inserted_at",
}

EXPECTED_ENTRY_COLUMNS = {
    "manifest_id",
    "artifact_id",
    "run_id",
    "artifact_kind",
    "uri",
    "filename",
    "format",
    "status",
    "hash_algorithm",
    "content_hash",
    "size_bytes",
    "row_count",
    "created_at",
    "validator_version",
    "inserted_at",
}

NULLABLE_MANIFEST_COLUMNS: set[str] = set()

NULLABLE_ENTRY_COLUMNS = {
    "hash_algorithm",
    "content_hash",
    "size_bytes",
    "row_count",
    "created_at",
    "validator_version",
}

EXPECTED_ENTRY_CHECKS = {
    "ck_run_artifact_entries_artifact_kind_values",
    "ck_run_artifact_entries_format_values",
    "ck_run_artifact_entries_status_values",
    "ck_run_artifact_entries_hash_algorithm_values",
    "ck_run_artifact_entries_size_bytes_nonnegative",
    "ck_run_artifact_entries_row_count_nonnegative",
}

EXPECTED_INDEXES = {
    "run_artifact_manifests": {
        "ix_run_artifact_manifests_experiment_id_created_at": (
            "experiment_id",
            "created_at",
        ),
    },
    "run_artifact_entries": {
        "ix_run_artifact_entries_run_id_artifact_kind": (
            "run_id",
            "artifact_kind",
        ),
        "ix_run_artifact_entries_status": ("status",),
        "ix_run_artifact_entries_manifest_id": ("manifest_id",),
    },
}


def test_metadata_contains_current_ledger_tables_only() -> None:
    assert set(metadata.tables) == EXPECTED_TABLE_NAMES
    assert ARTIFACT_TABLES == (
        run_artifact_manifests,
        run_artifact_entries,
    )
    assert metadata.tables["experiment_runs"] is experiment_runs
    assert metadata.tables["data_snapshot_manifests"] is data_snapshot_manifests


def test_artifact_tables_have_expected_columns() -> None:
    assert set(run_artifact_manifests.c.keys()) == EXPECTED_MANIFEST_COLUMNS
    assert set(run_artifact_entries.c.keys()) == EXPECTED_ENTRY_COLUMNS


def test_artifact_table_nullability_matches_scope() -> None:
    for column in run_artifact_manifests.c:
        assert column.nullable is (column.name in NULLABLE_MANIFEST_COLUMNS)

    for column in run_artifact_entries.c:
        assert column.nullable is (column.name in NULLABLE_ENTRY_COLUMNS)


def test_artifact_table_primary_keys_match_contract_ids() -> None:
    assert [column.name for column in run_artifact_manifests.primary_key] == [
        "manifest_id"
    ]
    assert [column.name for column in run_artifact_entries.primary_key] == [
        "manifest_id",
        "artifact_id",
    ]


def test_artifact_manifest_has_run_id_unique_constraint() -> None:
    unique_constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in run_artifact_manifests.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert unique_constraints == {"uq_run_artifact_manifests_run_id": ("run_id",)}
    assert "uq_run_artifact_manifests_run_id_contract_hash" not in unique_constraints


def test_artifact_manifest_raw_contract_uses_postgresql_jsonb() -> None:
    assert isinstance(run_artifact_manifests.c.raw_contract.type, JSONB)


def test_artifact_inserted_at_columns_have_server_defaults() -> None:
    assert run_artifact_manifests.c.inserted_at.server_default is not None
    assert run_artifact_entries.c.inserted_at.server_default is not None


def test_artifact_entry_check_constraints_are_named() -> None:
    checks = {
        constraint.name
        for constraint in run_artifact_entries.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert checks == EXPECTED_ENTRY_CHECKS


def test_artifact_table_indexes_are_named_and_target_expected_columns() -> None:
    for table in ARTIFACT_TABLES:
        actual_indexes = {
            index.name: tuple(column.name for column in index.columns)
            for index in table.indexes
        }

        assert actual_indexes == EXPECTED_INDEXES[table.name]


def test_artifact_tables_have_only_entry_to_manifest_foreign_key() -> None:
    manifest_foreign_keys = list(run_artifact_manifests.foreign_key_constraints)
    entry_foreign_keys = list(run_artifact_entries.foreign_key_constraints)

    assert manifest_foreign_keys == []
    assert len(entry_foreign_keys) == 1

    foreign_key = entry_foreign_keys[0]
    assert isinstance(foreign_key, ForeignKeyConstraint)
    assert foreign_key.name == (
        "fk_run_artifact_entries_manifest_id_run_artifact_manifests"
    )
    assert [element.parent.name for element in foreign_key.elements] == ["manifest_id"]
    assert [element.column.table.name for element in foreign_key.elements] == [
        "run_artifact_manifests"
    ]
    assert [element.column.name for element in foreign_key.elements] == ["manifest_id"]

    all_referred_tables = {
        element.column.table.name
        for table in ARTIFACT_TABLES
        for constraint in table.foreign_key_constraints
        for element in constraint.elements
    }
    assert "experiment_runs" not in all_referred_tables


def test_artifact_tables_compile_for_postgresql_without_connection() -> None:
    dialect = postgresql.dialect()

    for table in ARTIFACT_TABLES:
        compiled_table = str(CreateTable(table).compile(dialect=dialect))
        assert f"CREATE TABLE {table.name}" in compiled_table

        for index in table.indexes:
            compiled_index = str(CreateIndex(index).compile(dialect=dialect))
            assert f"CREATE INDEX {index.name}" in compiled_index

    compiled_manifest = str(
        CreateTable(run_artifact_manifests).compile(dialect=dialect)
    )
    assert "JSONB" in compiled_manifest
