from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import ValidationError

from research_sdk.contracts import (
    ArtifactFormat,
    ArtifactKind,
    ArtifactStatus,
    DataSnapshotManifest,
    ExperimentRunRecord,
    ExperimentRunStatus,
    RunArtifactEntry,
    RunArtifactManifest,
)
from research_sdk.experiment_recording import CompletedExperimentRecordBundle

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "contracts"


def load_fixture(filename: str) -> dict[str, object]:
    return json.loads((FIXTURE_DIR / filename).read_text(encoding="utf-8"))


@pytest.fixture
def snapshot() -> DataSnapshotManifest:
    return DataSnapshotManifest.model_validate(
        load_fixture("data_snapshot_manifest.json")
    )


@pytest.fixture
def run() -> ExperimentRunRecord:
    loaded = ExperimentRunRecord.model_validate(
        load_fixture("experiment_run_record.json")
    )
    return loaded.model_copy(
        update={
            "failure_labels": (),
            "failure_reason": None,
            "failure_logs_uri": None,
        }
    )


@pytest.fixture
def artifact_manifest() -> RunArtifactManifest:
    return RunArtifactManifest.model_validate(
        load_fixture("run_artifact_manifest.json")
    )


def test_valid_bundle_construction(
    snapshot: DataSnapshotManifest,
    run: ExperimentRunRecord,
    artifact_manifest: RunArtifactManifest,
) -> None:
    bundle = CompletedExperimentRecordBundle(
        snapshot=snapshot,
        run=run,
        manifest_id="manifest-20260709-001",
        artifact_manifest=artifact_manifest,
    )

    assert bundle.snapshot is snapshot
    assert bundle.run is run
    assert bundle.manifest_id == "manifest-20260709-001"
    assert bundle.artifact_manifest is artifact_manifest


@pytest.mark.parametrize(
    "status",
    [
        status
        for status in ExperimentRunStatus
        if status is not ExperimentRunStatus.COMPLETED
    ],
)
def test_every_status_other_than_completed_is_rejected(
    snapshot: DataSnapshotManifest,
    run: ExperimentRunRecord,
    artifact_manifest: RunArtifactManifest,
    status: ExperimentRunStatus,
) -> None:
    changed_run = run.model_copy(update={"status": status})

    with pytest.raises(ValidationError, match="run status must be completed"):
        build_bundle(snapshot=snapshot, run=changed_run, manifest=artifact_manifest)


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("failure_labels", ("execution_error",), "failure labels must be empty"),
        ("failure_reason", "failed", "failure reason must be absent"),
        ("failure_logs_uri", "artifacts/run/failure.log", "failure logs URI"),
    ],
)
def test_run_failure_metadata_is_rejected(
    snapshot: DataSnapshotManifest,
    run: ExperimentRunRecord,
    artifact_manifest: RunArtifactManifest,
    field_name: str,
    value: object,
    message: str,
) -> None:
    changed_run = run.model_copy(update={field_name: value})

    with pytest.raises(ValidationError, match=message):
        build_bundle(snapshot=snapshot, run=changed_run, manifest=artifact_manifest)


def test_artifacts_incomplete_is_rejected(
    snapshot: DataSnapshotManifest,
    run: ExperimentRunRecord,
    artifact_manifest: RunArtifactManifest,
) -> None:
    changed_run = run.model_copy(update={"artifacts_incomplete": True})

    with pytest.raises(ValidationError, match="artifacts must not be incomplete"):
        build_bundle(snapshot=snapshot, run=changed_run, manifest=artifact_manifest)


def test_snapshot_identity_mismatch_is_rejected(
    snapshot: DataSnapshotManifest,
    run: ExperimentRunRecord,
    artifact_manifest: RunArtifactManifest,
) -> None:
    changed_run = run.model_copy(update={"data_snapshot_id": "other-snapshot"})

    with pytest.raises(ValidationError, match="data_snapshot_id must match"):
        build_bundle(snapshot=snapshot, run=changed_run, manifest=artifact_manifest)


def test_artifact_run_identity_mismatch_is_rejected(
    snapshot: DataSnapshotManifest,
    run: ExperimentRunRecord,
    artifact_manifest: RunArtifactManifest,
) -> None:
    changed_manifest = artifact_manifest.model_copy(update={"run_id": "other-run"})

    with pytest.raises(ValidationError, match="artifact manifest run_id must match"):
        build_bundle(snapshot=snapshot, run=run, manifest=changed_manifest)


def test_artifact_experiment_identity_mismatch_is_rejected(
    snapshot: DataSnapshotManifest,
    run: ExperimentRunRecord,
    artifact_manifest: RunArtifactManifest,
) -> None:
    changed_manifest = artifact_manifest.model_copy(
        update={"experiment_id": "other-experiment"}
    )

    with pytest.raises(
        ValidationError,
        match="artifact manifest experiment_id must match",
    ):
        build_bundle(snapshot=snapshot, run=run, manifest=changed_manifest)


def test_artifact_root_mismatch_is_rejected(
    snapshot: DataSnapshotManifest,
    run: ExperimentRunRecord,
    artifact_manifest: RunArtifactManifest,
) -> None:
    changed_run = run.model_copy(update={"artifact_uri": "artifacts/other-run"})

    with pytest.raises(ValidationError, match="artifact_uri must match"):
        build_bundle(snapshot=snapshot, run=changed_run, manifest=artifact_manifest)


def test_artifact_manifest_uri_mismatch_is_rejected(
    snapshot: DataSnapshotManifest,
    run: ExperimentRunRecord,
    artifact_manifest: RunArtifactManifest,
) -> None:
    changed_run = run.model_copy(
        update={"artifact_manifest_uri": "artifacts/run-20260709-001/manifest.json"}
    )

    with pytest.raises(ValidationError, match="artifact_manifest_uri must point"):
        build_bundle(snapshot=snapshot, run=changed_run, manifest=artifact_manifest)


def test_blank_artifact_manifest_hash_is_rejected(
    snapshot: DataSnapshotManifest,
    run: ExperimentRunRecord,
    artifact_manifest: RunArtifactManifest,
) -> None:
    changed_run = run.model_copy(update={"artifact_manifest_hash": " "})

    with pytest.raises(
        ValidationError, match="artifact_manifest_hash must not be blank"
    ):
        build_bundle(snapshot=snapshot, run=changed_run, manifest=artifact_manifest)


def test_incomplete_required_artifacts_are_rejected(
    snapshot: DataSnapshotManifest,
    run: ExperimentRunRecord,
    artifact_manifest: RunArtifactManifest,
) -> None:
    changed_manifest = artifact_manifest.model_copy(
        update={"required_artifacts_complete": False}
    )

    with pytest.raises(ValidationError, match="required_artifacts_complete"):
        build_bundle(snapshot=snapshot, run=run, manifest=changed_manifest)


def test_non_produced_artifact_entry_is_rejected(
    snapshot: DataSnapshotManifest,
    run: ExperimentRunRecord,
    artifact_manifest: RunArtifactManifest,
) -> None:
    optional_skipped_entry = artifact_manifest.artifacts[0].model_copy(
        update={
            "artifact_id": "optional-skipped-diagnostic",
            "artifact_kind": ArtifactKind.OTHER,
            "filename": "diagnostic.txt",
            "format": ArtifactFormat.TEXT,
            "status": ArtifactStatus.SKIPPED,
        }
    )
    changed_manifest = artifact_manifest.model_copy(
        update={"artifacts": (*artifact_manifest.artifacts, optional_skipped_entry)}
    )

    with pytest.raises(ValidationError, match="produced status"):
        build_bundle(snapshot=snapshot, run=run, manifest=changed_manifest)


def test_missing_produced_artifact_status_metadata_is_rejected(
    snapshot: DataSnapshotManifest,
    run: ExperimentRunRecord,
    artifact_manifest: RunArtifactManifest,
) -> None:
    changed_manifest = artifact_manifest_with_replaced_entry(
        artifact_manifest,
        artifact_manifest.artifacts[0].model_copy(update={"hash_algorithm": None}),
    )

    with pytest.raises(ValidationError, match="hash_algorithm"):
        build_bundle(snapshot=snapshot, run=run, manifest=changed_manifest)


def test_missing_required_artifact_metadata_is_rejected(
    snapshot: DataSnapshotManifest,
    run: ExperimentRunRecord,
    artifact_manifest: RunArtifactManifest,
) -> None:
    changed_manifest = artifact_manifest_with_replaced_entry(
        artifact_manifest,
        artifact_manifest.artifacts[0].model_copy(update={"validator_version": None}),
    )

    with pytest.raises(ValidationError, match="validator_version"):
        build_bundle(snapshot=snapshot, run=run, manifest=changed_manifest)


def test_blank_manifest_id_is_rejected(
    snapshot: DataSnapshotManifest,
    run: ExperimentRunRecord,
    artifact_manifest: RunArtifactManifest,
) -> None:
    with pytest.raises(ValidationError, match="manifest_id must not be blank"):
        CompletedExperimentRecordBundle(
            snapshot=snapshot,
            run=run,
            manifest_id=" ",
            artifact_manifest=artifact_manifest,
        )


def test_validation_does_not_inspect_files_or_object_storage(
    snapshot: DataSnapshotManifest,
    run: ExperimentRunRecord,
    artifact_manifest: RunArtifactManifest,
) -> None:
    artifact_root_uri = "file:///definitely/not/present/run-20260709-001"
    changed_run = run.model_copy(
        update={
            "artifact_uri": artifact_root_uri,
            "artifact_manifest_uri": f"{artifact_root_uri}/artifact_manifest.json",
        }
    )
    changed_entries = tuple(
        entry.model_copy(update={"uri": f"{artifact_root_uri}/{entry.filename}"})
        for entry in artifact_manifest.artifacts
    )
    changed_manifest = artifact_manifest.model_copy(
        update={
            "artifact_root_uri": artifact_root_uri,
            "artifacts": changed_entries,
        }
    )

    bundle = build_bundle(
        snapshot=snapshot,
        run=changed_run,
        manifest=changed_manifest,
    )

    assert bundle.run.artifact_uri == artifact_root_uri


def build_bundle(
    *,
    snapshot: DataSnapshotManifest,
    run: ExperimentRunRecord,
    manifest: RunArtifactManifest,
) -> CompletedExperimentRecordBundle:
    return CompletedExperimentRecordBundle(
        snapshot=snapshot,
        run=run,
        manifest_id="manifest-20260709-001",
        artifact_manifest=manifest,
    )


def artifact_manifest_with_replaced_entry(
    manifest: RunArtifactManifest,
    replacement: RunArtifactEntry,
) -> RunArtifactManifest:
    def entries() -> Iterator[RunArtifactEntry]:
        yield replacement
        yield from manifest.artifacts[1:]

    return manifest.model_copy(update={"artifacts": tuple(entries())})
