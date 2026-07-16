from __future__ import annotations

import inspect
import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Insert

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
    build_experiment_run_insert as exported_build_experiment_run_insert,
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
    build_data_snapshot_manifest_insert,
    build_experiment_run_insert,
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


def compiled_sql(statement: Insert) -> str:
    return str(statement.compile(dialect=POSTGRESQL_DIALECT))


def compiled_params(statement: Insert) -> dict[str, Any]:
    return statement.compile(dialect=POSTGRESQL_DIALECT).params


def assert_insert_targets_table(statement: Insert, table_name: str) -> None:
    sql = compiled_sql(statement)

    assert isinstance(statement, Insert)
    assert "INSERT INTO" in sql
    assert table_name in sql
    assert "ON CONFLICT" not in sql


def test_statement_builders_import_from_statement_module() -> None:
    assert statements.ArtifactManifestInsertStatements is (
        ArtifactManifestInsertStatements
    )
    assert statements.build_experiment_run_insert is build_experiment_run_insert
    assert statements.build_data_snapshot_manifest_insert is (
        build_data_snapshot_manifest_insert
    )
    assert statements.build_run_artifact_manifest_inserts is (
        build_run_artifact_manifest_inserts
    )
    assert statements.build_research_note_insert is build_research_note_insert
    assert statements.build_review_event_insert is build_review_event_insert


def test_statement_builders_export_from_persistence_package() -> None:
    assert ExportedArtifactManifestInsertStatements is ArtifactManifestInsertStatements
    assert exported_build_experiment_run_insert is build_experiment_run_insert
    assert exported_build_data_snapshot_manifest_insert is (
        build_data_snapshot_manifest_insert
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

    assert_insert_targets_table(experiment_statement, "experiment_runs")
    assert_insert_targets_table(snapshot_statement, "data_snapshot_manifests")
    assert_insert_targets_table(note_statement, "research_notes")
    assert_insert_targets_table(review_statement, "review_events")


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

    assert_insert_targets_table(grouped.manifest, "run_artifact_manifests")
    for entry in grouped.entries:
        assert_insert_targets_table(entry, "run_artifact_entries")


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
        "Session",
        "connect(",
        "execute(",
        "get_database_url",
        "psycopg",
        "asyncpg",
        "Path(",
        "open(",
        "read_text(",
        "requests",
        "boto3",
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
