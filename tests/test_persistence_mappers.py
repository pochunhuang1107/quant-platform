from __future__ import annotations

import inspect
import json
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Table

import research_sdk.persistence.mappers as mappers
from research_sdk.contracts import (
    DataSnapshotManifest,
    ExperimentRunRecord,
    ResearchNote,
    ReviewMetadata,
    RunArtifactManifest,
)
from research_sdk.persistence.hashing import contract_sha256
from research_sdk.persistence.mappers import (
    ArtifactManifestRows,
    ReviewSubjectType,
    data_snapshot_manifest_to_row,
    experiment_run_to_row,
    research_note_to_row,
    review_metadata_to_row,
    run_artifact_manifest_to_rows,
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
PROJECTED_SERVER_COLUMNS = {"inserted_at"}


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


def projected_column_names(table: Table) -> set[str]:
    return set(table.c.keys()) - PROJECTED_SERVER_COLUMNS


def assert_row_matches_projected_table(
    row: Mapping[str, Any],
    table: Table,
) -> None:
    assert set(row) == projected_column_names(table)

    for column in table.c:
        if column.name in PROJECTED_SERVER_COLUMNS:
            continue
        if not column.nullable and column.server_default is None:
            assert row[column.name] is not None


def test_fixture_contracts_validate_and_map_successfully(
    experiment_run: ExperimentRunRecord,
    data_snapshot_manifest: DataSnapshotManifest,
    run_artifact_manifest: RunArtifactManifest,
    research_note: ResearchNote,
    review_metadata: ReviewMetadata,
) -> None:
    assert experiment_run_to_row(experiment_run)
    assert data_snapshot_manifest_to_row(data_snapshot_manifest)
    assert run_artifact_manifest_to_rows(
        manifest_id="manifest-run-20260709-001",
        manifest=run_artifact_manifest,
    )
    assert research_note_to_row(research_note)
    assert review_metadata_to_row(
        review_event_id="review-event-20260709-001",
        subject_type=ReviewSubjectType.EXPERIMENT_RUN,
        subject_id=experiment_run.run_id,
        review=review_metadata,
    )


def test_contract_backed_mapper_keys_match_table_columns(
    experiment_run: ExperimentRunRecord,
    data_snapshot_manifest: DataSnapshotManifest,
    research_note: ResearchNote,
) -> None:
    assert_row_matches_projected_table(
        experiment_run_to_row(experiment_run),
        experiment_runs,
    )
    assert_row_matches_projected_table(
        data_snapshot_manifest_to_row(data_snapshot_manifest),
        data_snapshot_manifests,
    )
    assert_row_matches_projected_table(
        research_note_to_row(research_note),
        research_notes,
    )


def test_artifact_mapper_keys_match_table_columns(
    run_artifact_manifest: RunArtifactManifest,
) -> None:
    rows = run_artifact_manifest_to_rows(
        manifest_id="manifest-run-20260709-001",
        manifest=run_artifact_manifest,
    )

    assert_row_matches_projected_table(rows.manifest, run_artifact_manifests)
    for entry in rows.entries:
        assert_row_matches_projected_table(entry, run_artifact_entries)


def test_review_mapper_keys_match_table_columns(
    review_metadata: ReviewMetadata,
) -> None:
    row = review_metadata_to_row(
        review_event_id="review-event-20260709-001",
        subject_type="experiment_run",
        subject_id="run-20260709-001",
        review=review_metadata,
    )

    assert_row_matches_projected_table(row, review_events)


def test_contract_hash_and_raw_contract_match_contract_payloads(
    experiment_run: ExperimentRunRecord,
    data_snapshot_manifest: DataSnapshotManifest,
    run_artifact_manifest: RunArtifactManifest,
    research_note: ResearchNote,
) -> None:
    experiment_row = experiment_run_to_row(experiment_run)
    snapshot_row = data_snapshot_manifest_to_row(data_snapshot_manifest)
    artifact_rows = run_artifact_manifest_to_rows(
        manifest_id="manifest-run-20260709-001",
        manifest=run_artifact_manifest,
    )
    note_row = research_note_to_row(research_note)

    for contract, row in (
        (experiment_run, experiment_row),
        (data_snapshot_manifest, snapshot_row),
        (run_artifact_manifest, artifact_rows.manifest),
        (research_note, note_row),
    ):
        assert row["contract_hash"] == contract_sha256(contract)
        assert row["raw_contract"] == contract.model_dump(mode="json")


def test_review_mapper_raw_review_matches_review_payload(
    review_metadata: ReviewMetadata,
) -> None:
    row = review_metadata_to_row(
        review_event_id="review-event-20260709-001",
        subject_type=ReviewSubjectType.RESEARCH_NOTE,
        subject_id="note-20260709-001",
        review=review_metadata,
    )

    assert row["raw_review"] == review_metadata.model_dump(mode="json")


def test_artifact_mapper_returns_manifest_row_and_one_entry_per_artifact(
    run_artifact_manifest: RunArtifactManifest,
) -> None:
    rows = run_artifact_manifest_to_rows(
        manifest_id="manifest-run-20260709-001",
        manifest=run_artifact_manifest,
    )

    assert isinstance(rows, ArtifactManifestRows)
    assert len(rows.entries) == len(run_artifact_manifest.artifacts)


def test_artifact_mapper_uses_caller_provided_manifest_id(
    run_artifact_manifest: RunArtifactManifest,
) -> None:
    manifest_id = "caller-provided-manifest-id"

    rows = run_artifact_manifest_to_rows(
        manifest_id=manifest_id,
        manifest=run_artifact_manifest,
    )

    assert rows.manifest["manifest_id"] == manifest_id
    assert {entry["manifest_id"] for entry in rows.entries} == {manifest_id}


def test_artifact_entry_rows_keep_declared_content_hash_without_file_checks(
    run_artifact_manifest: RunArtifactManifest,
) -> None:
    payload = run_artifact_manifest.model_dump(mode="json")
    payload["artifacts"][0]["uri"] = "not-a-real-artifact-uri"
    payload["artifacts"][0]["content_hash"] = "declared-hash-only"
    manifest = RunArtifactManifest.model_validate(payload)

    rows = run_artifact_manifest_to_rows(
        manifest_id="manifest-run-20260709-001",
        manifest=manifest,
    )

    assert rows.entries[0]["uri"] == "not-a-real-artifact-uri"
    assert rows.entries[0]["content_hash"] == "declared-hash-only"


def test_review_mapper_rejects_invalid_subject_type(
    review_metadata: ReviewMetadata,
) -> None:
    with pytest.raises(ValueError, match="subject_type must be one of"):
        review_metadata_to_row(
            review_event_id="review-event-20260709-001",
            subject_type="invalid_subject",
            subject_id="run-20260709-001",
            review=review_metadata,
        )


def test_review_mapper_accepts_enum_and_valid_string_subject_types(
    review_metadata: ReviewMetadata,
) -> None:
    enum_row = review_metadata_to_row(
        review_event_id="review-event-20260709-001",
        subject_type=ReviewSubjectType.DATA_SNAPSHOT_MANIFEST,
        subject_id="market-snapshot-20260709",
        review=review_metadata,
    )
    string_row = review_metadata_to_row(
        review_event_id="review-event-20260709-002",
        subject_type="run_artifact_manifest",
        subject_id="manifest-run-20260709-001",
        review=review_metadata,
    )

    assert enum_row["subject_type"] == "data_snapshot_manifest"
    assert string_row["subject_type"] == "run_artifact_manifest"


def test_review_mapper_has_no_event_hash_or_schema_version(
    review_metadata: ReviewMetadata,
) -> None:
    row = review_metadata_to_row(
        review_event_id="review-event-20260709-001",
        subject_type=ReviewSubjectType.EXPERIMENT_RUN,
        subject_id="run-20260709-001",
        review=review_metadata,
    )

    assert "event_hash" not in row
    assert "schema_version" not in row


def test_mappers_do_not_mutate_input_contracts(
    experiment_run: ExperimentRunRecord,
    data_snapshot_manifest: DataSnapshotManifest,
    run_artifact_manifest: RunArtifactManifest,
    research_note: ResearchNote,
    review_metadata: ReviewMetadata,
) -> None:
    before = {
        "experiment_run": deepcopy(experiment_run.model_dump(mode="json")),
        "data_snapshot_manifest": deepcopy(
            data_snapshot_manifest.model_dump(mode="json")
        ),
        "run_artifact_manifest": deepcopy(
            run_artifact_manifest.model_dump(mode="json")
        ),
        "research_note": deepcopy(research_note.model_dump(mode="json")),
        "review_metadata": deepcopy(review_metadata.model_dump(mode="json")),
    }

    experiment_run_to_row(experiment_run)
    data_snapshot_manifest_to_row(data_snapshot_manifest)
    run_artifact_manifest_to_rows(
        manifest_id="manifest-run-20260709-001",
        manifest=run_artifact_manifest,
    )
    research_note_to_row(research_note)
    review_metadata_to_row(
        review_event_id="review-event-20260709-001",
        subject_type=ReviewSubjectType.EXPERIMENT_RUN,
        subject_id="run-20260709-001",
        review=review_metadata,
    )

    assert experiment_run.model_dump(mode="json") == before["experiment_run"]
    assert (
        data_snapshot_manifest.model_dump(mode="json")
        == before["data_snapshot_manifest"]
    )
    assert (
        run_artifact_manifest.model_dump(mode="json") == before["run_artifact_manifest"]
    )
    assert research_note.model_dump(mode="json") == before["research_note"]
    assert review_metadata.model_dump(mode="json") == before["review_metadata"]


def test_mapper_module_excludes_db_driver_session_engine_and_io_hooks() -> None:
    source = inspect.getsource(mappers)

    for prohibited_term in (
        "sqlalchemy",
        "create_engine",
        "Session",
        "connect(",
        "execute(",
        "Path(",
        "open(",
        "read_text(",
        "requests",
        "boto3",
    ):
        assert prohibited_term not in source


def test_mapper_module_does_not_import_table_metadata() -> None:
    module_names = set(vars(mappers))

    assert "metadata" not in module_names
    assert "experiment_runs" not in module_names
    assert "data_snapshot_manifests" not in module_names
    assert "run_artifact_manifests" not in module_names
    assert "run_artifact_entries" not in module_names
    assert "research_notes" not in module_names
    assert "review_events" not in module_names
