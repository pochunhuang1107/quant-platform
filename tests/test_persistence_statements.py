from __future__ import annotations

import inspect
import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Column, MetaData, Table, Text
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Insert
from sqlalchemy.sql.selectable import Select

import research_sdk.persistence.statements as statements
from research_sdk.contracts import (
    DataSnapshotManifest,
    ExperimentRunRecord,
    ResearchNote,
    ReviewMetadata,
    RunArtifactManifest,
)
from research_sdk.persistence import (
    ArtifactManifestInsertStatements as ExportedArtifactManifestInsertStatements,
)
from research_sdk.persistence import (
    build_data_snapshot_manifest_insert as exported_build_data_snapshot_manifest_insert,
)
from research_sdk.persistence import (
    build_data_snapshot_manifest_replay_select as exported_build_snapshot_replay_select,
)
from research_sdk.persistence import (
    build_experiment_run_insert as exported_build_experiment_run_insert,
)
from research_sdk.persistence import (
    build_experiment_run_replay_select as exported_build_experiment_run_replay_select,
)
from research_sdk.persistence import (
    build_research_note_insert as exported_build_research_note_insert,
)
from research_sdk.persistence import (
    build_review_event_insert as exported_build_review_event_insert,
)
from research_sdk.persistence import (
    build_run_artifact_manifest_inserts as exported_build_run_artifact_manifest_inserts,
)
from research_sdk.persistence.mappers import (
    ReviewSubjectType,
    data_snapshot_manifest_to_row,
    experiment_run_to_row,
    research_note_to_row,
    review_metadata_to_row,
    run_artifact_manifest_to_rows,
)
from research_sdk.persistence.statements import (
    ArtifactManifestInsertStatements,
    _build_replay_candidate_insert,
    build_data_snapshot_manifest_insert,
    build_data_snapshot_manifest_replay_select,
    build_experiment_run_insert,
    build_experiment_run_replay_select,
    build_research_note_insert,
    build_review_event_insert,
    build_run_artifact_manifest_inserts,
)
from research_sdk.persistence.tables import (
    data_snapshot_manifests,
    experiment_runs,
    research_notes,
    review_events,
    run_artifact_entries,
    run_artifact_manifests,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "contracts"
POSTGRESQL_DIALECT = postgresql.dialect()


def load_fixture(filename: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / filename).read_text(encoding="utf-8"))


@pytest.fixture
def experiment_run() -> ExperimentRunRecord:
    return ExperimentRunRecord.model_validate(
        load_fixture("experiment_run_record.json")
    )


@pytest.fixture
def data_snapshot_manifest() -> DataSnapshotManifest:
    return DataSnapshotManifest.model_validate(
        load_fixture("data_snapshot_manifest.json")
    )


@pytest.fixture
def run_artifact_manifest() -> RunArtifactManifest:
    return RunArtifactManifest.model_validate(
        load_fixture("run_artifact_manifest.json")
    )


@pytest.fixture
def research_note() -> ResearchNote:
    return ResearchNote.model_validate(load_fixture("research_note.json"))


@pytest.fixture
def review_metadata() -> ReviewMetadata:
    return ReviewMetadata.model_validate(load_fixture("review_metadata.json"))


def compiled_sql(statement: Insert | Select[Any]) -> str:
    return str(statement.compile(dialect=POSTGRESQL_DIALECT))


def compiled_params(statement: Insert | Select[Any]) -> dict[str, Any]:
    return statement.compile(dialect=POSTGRESQL_DIALECT).params


def normalized_sql(statement: Insert | Select[Any]) -> str:
    return " ".join(compiled_sql(statement).split())


def returning_clause(statement: Insert) -> str:
    sql = compiled_sql(statement)
    _, separator, returning = sql.partition(" RETURNING ")

    assert separator == " RETURNING "
    return " ".join(returning.split())


def assert_insert_targets_table(statement: Insert, table_name: str) -> None:
    sql = normalized_sql(statement)

    assert isinstance(statement, Insert)
    assert "INSERT INTO" in sql
    assert table_name in sql


def assert_replay_candidate_statement(
    *,
    statement: Insert,
    table_name: str,
    conflict_constraint: str,
    returning_columns: tuple[str, ...],
    prohibited_returning_columns: tuple[str, ...],
) -> None:
    sql = normalized_sql(statement)
    returning = returning_clause(statement)

    assert_insert_targets_table(statement, table_name)
    assert f"ON CONFLICT ON CONSTRAINT {conflict_constraint} DO NOTHING" in sql
    assert sql.count("ON CONFLICT") == 1
    assert "ON CONFLICT DO NOTHING" not in sql
    assert "DO UPDATE" not in sql

    assert returning == ", ".join(returning_columns)
    for column_name in prohibited_returning_columns:
        assert column_name not in returning


def assert_strict_insert_statement(
    *,
    statement: Insert,
    table_name: str,
    expected_returning_columns: tuple[str, ...] = (),
) -> None:
    sql = normalized_sql(statement)

    assert_insert_targets_table(statement, table_name)
    assert "ON CONFLICT" not in sql
    assert "DO NOTHING" not in sql
    assert "DO UPDATE" not in sql

    if expected_returning_columns:
        assert returning_clause(statement) == ", ".join(expected_returning_columns)
    else:
        assert "RETURNING" not in sql


def test_statement_builders_import_from_statement_module() -> None:
    assert statements.ArtifactManifestInsertStatements is (
        ArtifactManifestInsertStatements
    )
    assert statements.build_experiment_run_insert is build_experiment_run_insert
    assert statements.build_experiment_run_replay_select is (
        build_experiment_run_replay_select
    )
    assert "build_experiment_run_replay_select" in statements.__all__
    assert statements.build_data_snapshot_manifest_insert is (
        build_data_snapshot_manifest_insert
    )
    assert statements.build_data_snapshot_manifest_replay_select is (
        build_data_snapshot_manifest_replay_select
    )
    assert "build_data_snapshot_manifest_replay_select" in statements.__all__
    assert statements.build_run_artifact_manifest_inserts is (
        build_run_artifact_manifest_inserts
    )
    assert statements.build_research_note_insert is build_research_note_insert
    assert statements.build_review_event_insert is build_review_event_insert


def test_statement_builders_export_from_persistence_package() -> None:
    assert ExportedArtifactManifestInsertStatements is ArtifactManifestInsertStatements
    assert exported_build_experiment_run_insert is build_experiment_run_insert
    assert exported_build_experiment_run_replay_select is (
        build_experiment_run_replay_select
    )
    assert exported_build_data_snapshot_manifest_insert is (
        build_data_snapshot_manifest_insert
    )
    assert exported_build_snapshot_replay_select is (
        build_data_snapshot_manifest_replay_select
    )
    assert exported_build_run_artifact_manifest_inserts is (
        build_run_artifact_manifest_inserts
    )
    assert exported_build_research_note_insert is build_research_note_insert
    assert exported_build_review_event_insert is build_review_event_insert


def test_artifact_manifest_insert_statements_is_frozen() -> None:
    insert_statement = run_artifact_manifests.insert()
    grouped = ArtifactManifestInsertStatements(
        manifest=insert_statement,
        entries=(),
    )

    with pytest.raises(FrozenInstanceError):
        grouped.entries = (insert_statement,)


def test_table_primary_key_constraint_names_match_migrations() -> None:
    assert experiment_runs.primary_key.name == "pk_experiment_runs"
    assert data_snapshot_manifests.primary_key.name == "pk_data_snapshot_manifests"
    assert run_artifact_manifests.primary_key.name == "pk_run_artifact_manifests"
    assert run_artifact_entries.primary_key.name == "pk_run_artifact_entries"
    assert research_notes.primary_key.name == "pk_research_notes"
    assert review_events.primary_key.name == "pk_review_events"


def test_replay_candidate_helper_rejects_unnamed_primary_key_constraint() -> None:
    unnamed_primary_key_table = Table(
        "unnamed_primary_key_examples",
        MetaData(),
        Column("id", Text, primary_key=True),
    )

    assert unnamed_primary_key_table.primary_key.name is None
    with pytest.raises(
        ValueError,
        match="replay-candidate table must have a named primary-key constraint",
    ):
        _build_replay_candidate_insert(
            table=unnamed_primary_key_table,
            row={"id": "example"},
            returning_columns=(unnamed_primary_key_table.c.id,),
        )


def test_contract_builders_return_insert_objects_for_expected_tables(
    experiment_run: ExperimentRunRecord,
    data_snapshot_manifest: DataSnapshotManifest,
    research_note: ResearchNote,
    review_metadata: ReviewMetadata,
) -> None:
    experiment_statement = build_experiment_run_insert(experiment_run)
    snapshot_statement = build_data_snapshot_manifest_insert(data_snapshot_manifest)
    note_statement = build_research_note_insert(research_note)
    review_statement = build_review_event_insert(
        review_event_id="review-event-20260709-001",
        subject_type=ReviewSubjectType.EXPERIMENT_RUN,
        subject_id=experiment_run.run_id,
        review=review_metadata,
    )

    assert experiment_statement.table is experiment_runs
    assert snapshot_statement.table is data_snapshot_manifests
    assert note_statement.table is research_notes
    assert review_statement.table is review_events

    assert_replay_candidate_statement(
        statement=experiment_statement,
        table_name="experiment_runs",
        conflict_constraint="pk_experiment_runs",
        returning_columns=(
            "experiment_runs.run_id",
            "experiment_runs.contract_hash",
            "experiment_runs.inserted_at",
        ),
        prohibited_returning_columns=(
            "raw_contract",
            "status",
            "review_status",
            "artifact_uri",
            "created_at",
        ),
    )
    assert_replay_candidate_statement(
        statement=snapshot_statement,
        table_name="data_snapshot_manifests",
        conflict_constraint="pk_data_snapshot_manifests",
        returning_columns=(
            "data_snapshot_manifests.snapshot_id",
            "data_snapshot_manifests.contract_hash",
            "data_snapshot_manifests.inserted_at",
        ),
        prohibited_returning_columns=(
            "raw_contract",
            "status",
            "data_root_uri",
            "source_dataset",
            "created_at",
        ),
    )
    assert_replay_candidate_statement(
        statement=note_statement,
        table_name="research_notes",
        conflict_constraint="pk_research_notes",
        returning_columns=(
            "research_notes.note_id",
            "research_notes.contract_hash",
            "research_notes.inserted_at",
        ),
        prohibited_returning_columns=(
            "raw_contract",
            "status",
            "review_status",
            "title",
            "created_at",
        ),
    )
    assert_strict_insert_statement(
        statement=review_statement,
        table_name="review_events",
        expected_returning_columns=(
            "review_events.review_event_id",
            "review_events.inserted_at",
        ),
    )


def test_experiment_run_replay_select_shape() -> None:
    run_id = "run-replay-select-sentinel"

    statement = build_experiment_run_replay_select(run_id=run_id)
    sql = normalized_sql(statement)
    params = compiled_params(statement)

    assert isinstance(statement, Select)
    assert tuple(column.name for column in statement.selected_columns) == (
        "run_id",
        "contract_hash",
        "inserted_at",
    )
    assert tuple(statement.get_final_froms()) == (experiment_runs,)
    assert statement.whereclause is not None
    assert str(statement.whereclause.compile(dialect=POSTGRESQL_DIALECT)) == (
        "experiment_runs.run_id = %(run_id_1)s"
    )
    assert sql.startswith(
        "SELECT experiment_runs.run_id, experiment_runs.contract_hash, "
        "experiment_runs.inserted_at FROM experiment_runs WHERE "
        "experiment_runs.run_id = "
    )
    assert params == {"run_id_1": run_id}
    assert run_id not in sql
    assert "raw_contract" not in sql
    assert "SELECT *" not in sql
    assert " JOIN " not in sql
    assert " FOR UPDATE" not in sql
    assert "INSERT" not in sql
    assert "UPDATE" not in sql
    assert "DELETE" not in sql


def test_data_snapshot_manifest_replay_select_shape() -> None:
    snapshot_id = "snapshot-replay-select-sentinel"

    statement = build_data_snapshot_manifest_replay_select(snapshot_id=snapshot_id)
    sql = normalized_sql(statement)
    params = compiled_params(statement)

    assert isinstance(statement, Select)
    assert tuple(column.name for column in statement.selected_columns) == (
        "snapshot_id",
        "contract_hash",
        "inserted_at",
    )
    assert tuple(statement.get_final_froms()) == (data_snapshot_manifests,)
    assert statement.whereclause is not None
    assert str(statement.whereclause.compile(dialect=POSTGRESQL_DIALECT)) == (
        "data_snapshot_manifests.snapshot_id = %(snapshot_id_1)s"
    )
    assert sql.startswith(
        "SELECT data_snapshot_manifests.snapshot_id, "
        "data_snapshot_manifests.contract_hash, "
        "data_snapshot_manifests.inserted_at FROM data_snapshot_manifests WHERE "
        "data_snapshot_manifests.snapshot_id = "
    )
    assert params == {"snapshot_id_1": snapshot_id}
    assert snapshot_id not in sql
    assert "raw_contract" not in sql
    assert "SELECT *" not in sql
    assert " JOIN " not in sql
    assert " FOR UPDATE" not in sql
    assert "INSERT" not in sql
    assert "UPDATE" not in sql
    assert "DELETE" not in sql


def test_contract_builder_params_match_mapper_outputs(
    experiment_run: ExperimentRunRecord,
    data_snapshot_manifest: DataSnapshotManifest,
    research_note: ResearchNote,
    review_metadata: ReviewMetadata,
) -> None:
    assert compiled_params(build_experiment_run_insert(experiment_run)) == (
        experiment_run_to_row(experiment_run)
    )
    assert compiled_params(
        build_data_snapshot_manifest_insert(data_snapshot_manifest)
    ) == data_snapshot_manifest_to_row(data_snapshot_manifest)
    assert compiled_params(build_research_note_insert(research_note)) == (
        research_note_to_row(research_note)
    )
    assert compiled_params(
        build_review_event_insert(
            review_event_id="review-event-20260709-001",
            subject_type=ReviewSubjectType.EXPERIMENT_RUN,
            subject_id=experiment_run.run_id,
            review=review_metadata,
        )
    ) == review_metadata_to_row(
        review_event_id="review-event-20260709-001",
        subject_type=ReviewSubjectType.EXPERIMENT_RUN,
        subject_id=experiment_run.run_id,
        review=review_metadata,
    )


def test_statement_builders_do_not_bind_inserted_at_or_accept_contract_hash_inputs(
    experiment_run: ExperimentRunRecord,
    data_snapshot_manifest: DataSnapshotManifest,
    run_artifact_manifest: RunArtifactManifest,
    research_note: ResearchNote,
    review_metadata: ReviewMetadata,
) -> None:
    grouped = build_run_artifact_manifest_inserts(
        manifest_id="manifest-run-20260709-001",
        manifest=run_artifact_manifest,
    )

    statements_to_check = (
        build_experiment_run_insert(experiment_run),
        build_data_snapshot_manifest_insert(data_snapshot_manifest),
        grouped.manifest,
        build_research_note_insert(research_note),
        build_review_event_insert(
            review_event_id="review-event-20260709-001",
            subject_type=ReviewSubjectType.EXPERIMENT_RUN,
            subject_id=experiment_run.run_id,
            review=review_metadata,
        ),
        *grouped.entries,
    )

    for statement in statements_to_check:
        assert "inserted_at" not in compiled_params(statement)

    for builder in (
        build_experiment_run_insert,
        build_data_snapshot_manifest_insert,
        build_research_note_insert,
    ):
        assert "contract_hash" not in inspect.signature(builder).parameters

    assert (
        "contract_hash"
        not in inspect.signature(build_run_artifact_manifest_inserts).parameters
    )
    assert (
        "contract_hash" not in inspect.signature(build_review_event_insert).parameters
    )


def test_artifact_builder_returns_manifest_and_entry_inserts(
    run_artifact_manifest: RunArtifactManifest,
) -> None:
    manifest_id = "manifest-run-20260709-001"

    grouped = build_run_artifact_manifest_inserts(
        manifest_id=manifest_id,
        manifest=run_artifact_manifest,
    )

    assert isinstance(grouped, ArtifactManifestInsertStatements)
    assert grouped.manifest.table is run_artifact_manifests
    assert len(grouped.entries) == len(run_artifact_manifest.artifacts)
    assert all(entry.table is run_artifact_entries for entry in grouped.entries)

    assert_replay_candidate_statement(
        statement=grouped.manifest,
        table_name="run_artifact_manifests",
        conflict_constraint="pk_run_artifact_manifests",
        returning_columns=(
            "run_artifact_manifests.manifest_id",
            "run_artifact_manifests.contract_hash",
            "run_artifact_manifests.inserted_at",
        ),
        prohibited_returning_columns=(
            "raw_contract",
            "run_id",
            "artifact_root_uri",
            "created_at",
        ),
    )
    assert "uq_run_artifact_manifests_run_id" not in normalized_sql(grouped.manifest)
    for entry in grouped.entries:
        assert_strict_insert_statement(
            statement=entry,
            table_name="run_artifact_entries",
        )


def test_artifact_builder_params_match_mapper_outputs(
    run_artifact_manifest: RunArtifactManifest,
) -> None:
    manifest_id = "manifest-run-20260709-001"

    grouped = build_run_artifact_manifest_inserts(
        manifest_id=manifest_id,
        manifest=run_artifact_manifest,
    )
    rows = run_artifact_manifest_to_rows(
        manifest_id=manifest_id,
        manifest=run_artifact_manifest,
    )

    assert compiled_params(grouped.manifest) == rows.manifest
    assert tuple(compiled_params(entry) for entry in grouped.entries) == rows.entries
    assert len(grouped.entries) == len(rows.entries)


def test_artifact_builder_uses_caller_provided_manifest_id(
    run_artifact_manifest: RunArtifactManifest,
) -> None:
    manifest_id = "caller-provided-manifest-id"

    grouped = build_run_artifact_manifest_inserts(
        manifest_id=manifest_id,
        manifest=run_artifact_manifest,
    )

    assert compiled_params(grouped.manifest)["manifest_id"] == manifest_id
    assert {compiled_params(entry)["manifest_id"] for entry in grouped.entries} == {
        manifest_id
    }


def test_review_builder_accepts_enum_and_valid_string_subject_types(
    review_metadata: ReviewMetadata,
) -> None:
    enum_statement = build_review_event_insert(
        review_event_id="review-event-20260709-001",
        subject_type=ReviewSubjectType.DATA_SNAPSHOT_MANIFEST,
        subject_id="market-snapshot-20260709",
        review=review_metadata,
    )
    string_statement = build_review_event_insert(
        review_event_id="review-event-20260709-002",
        subject_type="run_artifact_manifest",
        subject_id="manifest-run-20260709-001",
        review=review_metadata,
    )

    assert compiled_params(enum_statement)["subject_type"] == "data_snapshot_manifest"
    assert compiled_params(string_statement)["subject_type"] == "run_artifact_manifest"


def test_review_builder_remains_strict_with_safe_returning(
    experiment_run: ExperimentRunRecord,
    review_metadata: ReviewMetadata,
) -> None:
    statement = build_review_event_insert(
        review_event_id="review-event-20260709-001",
        subject_type=ReviewSubjectType.EXPERIMENT_RUN,
        subject_id=experiment_run.run_id,
        review=review_metadata,
    )

    assert_strict_insert_statement(
        statement=statement,
        table_name="review_events",
        expected_returning_columns=(
            "review_events.review_event_id",
            "review_events.inserted_at",
        ),
    )
    assert "contract_hash" not in returning_clause(statement)
    assert "inserted_at" not in compiled_params(statement)


def test_review_builder_rejects_invalid_subject_type(
    review_metadata: ReviewMetadata,
) -> None:
    with pytest.raises(ValueError, match="subject_type must be one of"):
        build_review_event_insert(
            review_event_id="review-event-20260709-001",
            subject_type="invalid_subject",
            subject_id="run-20260709-001",
            review=review_metadata,
        )


def test_statement_module_excludes_db_driver_session_engine_and_io_hooks() -> None:
    source = inspect.getsource(statements)

    for prohibited_term in (
        "create_engine",
        "Engine",
        "Session",
        "Connection",
        "connect(",
        "execute(",
        "begin(",
        "commit(",
        "rollback(",
        "scalar",
        "fetchone",
        "fetchall",
        "get_database_url",
        "ExperimentLedgerRepository",
        "PersistenceWriteResult",
        "PersistenceDisposition",
        "PersistenceError",
        "ContractHashConflictError",
        "SQLSTATE",
        "psycopg",
        "asyncpg",
        "retry",
        "logging",
        "Path(",
        "open(",
        "read_text(",
        "requests",
        "boto3",
        "broker",
        "paper trading",
        "live trading",
    ):
        assert prohibited_term not in source


def test_statement_module_does_not_import_protocols() -> None:
    source = inspect.getsource(statements)
    module_names = set(vars(statements))

    for prohibited_term in (
        "ExperimentLedgerRepository",
        "PersistedRecordMetadata",
        "research_sdk.persistence.protocols",
    ):
        assert prohibited_term not in source

    assert "ExperimentLedgerRepository" not in module_names
    assert "PersistedRecordMetadata" not in module_names
