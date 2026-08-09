from __future__ import annotations

from pathlib import Path
from typing import Never

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection
from sqlalchemy.pool import NullPool

from live_postgres_safety import (
    QUANT_RUN_LIVE_DB_TESTS_ENV_VAR,
    QUANT_TEST_DATABASE_URL_ENV_VAR,
    UnsafePostgresTestUrl,
    get_quant_test_database_url,
    should_run_live_db_tests,
    validate_safe_postgres_test_url,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
HEAD_REVISION = "0007_research_note_report_cards"

EXPECTED_TABLES = {
    "experiment_runs",
    "data_snapshot_manifests",
    "run_artifact_manifests",
    "run_artifact_entries",
    "research_report_cards",
    "research_notes",
    "research_note_report_cards",
    "review_events",
}

EXPECTED_JSONB_COLUMNS = {
    "experiment_runs": {"raw_contract"},
    "data_snapshot_manifests": {"raw_contract"},
    "run_artifact_manifests": {"raw_contract"},
    "research_report_cards": {"raw_contract"},
    "research_notes": {"raw_contract"},
    "review_events": {"raw_review"},
}

EXPECTED_PRIMARY_KEYS = {
    "experiment_runs": ("run_id",),
    "data_snapshot_manifests": ("snapshot_id",),
    "run_artifact_manifests": ("manifest_id",),
    "run_artifact_entries": ("manifest_id", "artifact_id"),
    "research_report_cards": ("report_card_id",),
    "research_notes": ("note_id",),
    "research_note_report_cards": ("note_id", "report_card_id"),
    "review_events": ("review_event_id",),
}

EXPECTED_UNIQUE_CONSTRAINTS = {
    "run_artifact_manifests": {
        "uq_run_artifact_manifests_run_id": ("run_id",),
    },
}

ABSENT_UNIQUE_CONSTRAINTS = {
    "run_artifact_manifests": {
        "uq_run_artifact_manifests_run_id_contract_hash",
    },
}

EXPECTED_CHECK_CONSTRAINT_SUFFIXES = {
    "experiment_runs": {
        "status_values",
        "asset_class_values",
        "review_status_values",
    },
    "data_snapshot_manifests": {
        "row_count_nonnegative",
        "snapshot_kind_values",
        "status_values",
    },
    "run_artifact_entries": {
        "artifact_kind_values",
        "format_values",
        "status_values",
    },
    "research_notes": {
        "note_type_values",
        "status_values",
        "review_status_values",
    },
    "review_events": {
        "subject_type_values",
        "review_status_values",
    },
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
    "research_report_cards": {
        "ix_research_report_cards_source_run_id": ("source_run_id",),
        "ix_research_report_cards_experiment_id": ("experiment_id",),
        "ix_research_report_cards_strategy_id_strategy_version": (
            "strategy_id",
            "strategy_version",
        ),
    },
    "research_notes": {
        "ix_research_notes_status_updated_at": ("status", "updated_at"),
        "ix_research_notes_note_type_created_at": ("note_type", "created_at"),
        "ix_research_notes_review_status_updated_at": (
            "review_status",
            "updated_at",
        ),
        "ix_research_notes_decision_outcome_updated_at": (
            "decision_outcome",
            "updated_at",
        ),
        "ix_research_notes_parent_note_id": ("parent_note_id",),
        "ix_research_notes_supersedes_note_id": ("supersedes_note_id",),
    },
    "research_note_report_cards": {
        "ix_research_note_report_cards_report_card_id": ("report_card_id",),
    },
    "review_events": {
        "ix_review_events_subject_type_subject_id_inserted_at": (
            "subject_type",
            "subject_id",
            "inserted_at",
        ),
        "ix_review_events_reviewer_id_inserted_at": (
            "reviewer_id",
            "inserted_at",
        ),
        "ix_review_events_review_status_inserted_at": (
            "review_status",
            "inserted_at",
        ),
    },
}

ABSENT_INDEXES = {
    "run_artifact_manifests": {
        "ix_run_artifact_manifests_run_id",
    },
}


@pytest.mark.live_db
def test_live_postgres_upgrade_head_and_catalog_shape() -> None:
    database_url = _require_live_database_url()

    alembic_config = Config(str(ALEMBIC_INI))
    alembic_config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(alembic_config, "head")

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            _assert_alembic_head(connection)
            _assert_catalog_shape(connection)
    finally:
        engine.dispose()


def _require_live_database_url() -> str:
    if not should_run_live_db_tests():
        pytest.skip(f"set {QUANT_RUN_LIVE_DB_TESTS_ENV_VAR}=1 to run live DB tests")

    database_url = get_quant_test_database_url()
    if database_url is None:
        pytest.skip(f"{QUANT_TEST_DATABASE_URL_ENV_VAR} is not set")

    try:
        return validate_safe_postgres_test_url(database_url)
    except UnsafePostgresTestUrl as exc:
        _fail_without_traceback(str(exc))


def _fail_without_traceback(message: str) -> Never:
    pytest.fail(message, pytrace=False)


def _assert_alembic_head(connection: Connection) -> None:
    revisions = set(
        connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
    )

    assert revisions == {HEAD_REVISION}


def _assert_catalog_shape(connection: Connection) -> None:
    inspector = inspect(connection)

    assert EXPECTED_TABLES.issubset(set(inspector.get_table_names()))
    _assert_jsonb_columns(inspector)
    _assert_primary_keys(inspector)
    _assert_unique_constraints(inspector)
    _assert_check_constraints(inspector)
    _assert_indexes(inspector)
    _assert_artifact_entry_foreign_key(inspector)
    _assert_research_report_card_foreign_keys(inspector)
    _assert_research_note_report_card_foreign_keys(inspector)


def _assert_jsonb_columns(inspector: object) -> None:
    for table_name, column_names in EXPECTED_JSONB_COLUMNS.items():
        columns = {
            column["name"]: column["type"]
            for column in inspector.get_columns(table_name)
        }

        for column_name in column_names:
            assert isinstance(columns[column_name], JSONB)


def _assert_primary_keys(inspector: object) -> None:
    for table_name, expected_columns in EXPECTED_PRIMARY_KEYS.items():
        primary_key = inspector.get_pk_constraint(table_name)

        assert tuple(primary_key["constrained_columns"]) == expected_columns


def _assert_unique_constraints(inspector: object) -> None:
    for table_name, expected_constraints in EXPECTED_UNIQUE_CONSTRAINTS.items():
        actual_constraints = {
            constraint["name"]: tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints(table_name)
        }

        for constraint_name, expected_columns in expected_constraints.items():
            assert actual_constraints[constraint_name] == expected_columns

        for constraint_name in ABSENT_UNIQUE_CONSTRAINTS.get(table_name, set()):
            assert constraint_name not in actual_constraints


def _assert_check_constraints(inspector: object) -> None:
    for table_name, expected_suffixes in EXPECTED_CHECK_CONSTRAINT_SUFFIXES.items():
        actual_names = {
            constraint["name"]
            for constraint in inspector.get_check_constraints(table_name)
        }

        for expected_suffix in expected_suffixes:
            assert _has_check_constraint(
                actual_names=actual_names,
                table_name=table_name,
                expected_suffix=expected_suffix,
            )


def _has_check_constraint(
    *,
    actual_names: set[str],
    table_name: str,
    expected_suffix: str,
) -> bool:
    return (
        expected_suffix in actual_names
        or f"ck_{table_name}_{expected_suffix}" in actual_names
    )


def _assert_indexes(inspector: object) -> None:
    for table_name, expected_indexes in EXPECTED_INDEXES.items():
        actual_indexes = {
            index["name"]: tuple(index["column_names"])
            for index in inspector.get_indexes(table_name)
        }

        for index_name, expected_columns in expected_indexes.items():
            assert actual_indexes[index_name] == expected_columns

        for index_name in ABSENT_INDEXES.get(table_name, set()):
            assert index_name not in actual_indexes


def _assert_artifact_entry_foreign_key(inspector: object) -> None:
    foreign_keys = inspector.get_foreign_keys("run_artifact_entries")

    assert any(
        foreign_key["name"]
        == "fk_run_artifact_entries_manifest_id_run_artifact_manifests"
        and foreign_key["constrained_columns"] == ["manifest_id"]
        and foreign_key["referred_table"] == "run_artifact_manifests"
        and foreign_key["referred_columns"] == ["manifest_id"]
        for foreign_key in foreign_keys
    )


def _assert_research_report_card_foreign_keys(inspector: object) -> None:
    foreign_keys = {
        foreign_key["name"]: (
            tuple(foreign_key["constrained_columns"]),
            foreign_key["referred_table"],
            tuple(foreign_key["referred_columns"]),
        )
        for foreign_key in inspector.get_foreign_keys("research_report_cards")
    }

    assert foreign_keys["fk_report_cards_source_run_id"] == (
        ("source_run_id",),
        "experiment_runs",
        ("run_id",),
    )
    assert foreign_keys["fk_report_cards_data_snapshot_id"] == (
        ("data_snapshot_id",),
        "data_snapshot_manifests",
        ("snapshot_id",),
    )
    assert foreign_keys["fk_report_cards_benchmark_snapshot_id"] == (
        ("benchmark_snapshot_id",),
        "data_snapshot_manifests",
        ("snapshot_id",),
    )
    assert foreign_keys["fk_report_cards_artifact_manifest_id"] == (
        ("artifact_manifest_id",),
        "run_artifact_manifests",
        ("manifest_id",),
    )


def _assert_research_note_report_card_foreign_keys(inspector: object) -> None:
    foreign_keys = {
        foreign_key["name"]: (
            tuple(foreign_key["constrained_columns"]),
            foreign_key["referred_table"],
            tuple(foreign_key["referred_columns"]),
            tuple(foreign_key.get("options", {}).items()),
        )
        for foreign_key in inspector.get_foreign_keys("research_note_report_cards")
    }

    assert foreign_keys["fk_note_report_cards_note_id"] == (
        ("note_id",),
        "research_notes",
        ("note_id",),
        (),
    )
    assert foreign_keys["fk_note_report_cards_report_card_id"] == (
        ("report_card_id",),
        "research_report_cards",
        ("report_card_id",),
        (),
    )
