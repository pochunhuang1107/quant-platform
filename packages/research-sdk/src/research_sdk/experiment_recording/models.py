"""Application models for completed experiment recording."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from pydantic import ConfigDict, model_validator

from research_sdk.contracts import (
    ArtifactStatus,
    DataSnapshotManifest,
    ExperimentRunRecord,
    ExperimentRunStatus,
    RunArtifactManifest,
)
from research_sdk.contracts.base import BaseContractModel
from research_sdk.persistence.results import PersistenceWriteResult


class CompletedExperimentRecordBundle(BaseContractModel):
    """Validated terminal experiment payload ready for atomic ledger recording."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot: DataSnapshotManifest
    run: ExperimentRunRecord
    manifest_id: str
    artifact_manifest: RunArtifactManifest

    @model_validator(mode="after")
    def validate_completed_experiment_bundle(self) -> Self:
        """Validate cross-contract consistency for completed-run recording."""

        validate_completed_experiment_bundle(self)
        return self


@dataclass(frozen=True)
class CompletedExperimentRecordingResult:
    """Successful persistence outcomes for a completed experiment bundle."""

    snapshot_result: PersistenceWriteResult
    experiment_run_result: PersistenceWriteResult
    artifact_manifest_result: PersistenceWriteResult


def validate_completed_experiment_bundle(
    bundle: CompletedExperimentRecordBundle,
) -> None:
    """Validate completed experiment invariants before persistence starts."""

    _require(bundle.manifest_id.strip(), "manifest_id must not be blank")

    run = bundle.run
    snapshot = bundle.snapshot
    artifact_manifest = bundle.artifact_manifest

    _require(
        run.status == ExperimentRunStatus.COMPLETED,
        "run status must be completed",
    )
    _require(
        not run.artifacts_incomplete,
        "completed experiment artifacts must not be incomplete",
    )
    _require(
        len(run.failure_labels) == 0,
        "completed experiment run failure labels must be empty",
    )
    _require(
        run.failure_reason is None,
        "completed experiment run failure reason must be absent",
    )
    _require(
        run.failure_logs_uri is None,
        "completed experiment run failure logs URI must be absent",
    )
    _require(
        run.data_snapshot_id == snapshot.snapshot_id,
        "run data_snapshot_id must match snapshot snapshot_id",
    )
    _require(
        artifact_manifest.run_id == run.run_id,
        "artifact manifest run_id must match run run_id",
    )
    _require(
        artifact_manifest.experiment_id == run.experiment_id,
        "artifact manifest experiment_id must match run experiment_id",
    )
    _require(
        run.artifact_uri == artifact_manifest.artifact_root_uri,
        "run artifact_uri must match artifact manifest artifact_root_uri",
    )
    _require(
        run.artifact_manifest_uri
        == _expected_artifact_manifest_uri(artifact_manifest.artifact_root_uri),
        "run artifact_manifest_uri must point to artifact_manifest.json "
        "under artifact_root_uri",
    )
    _require(
        run.artifact_manifest_hash.strip(),
        "run artifact_manifest_hash must not be blank",
    )
    _require(
        artifact_manifest.required_artifacts_complete,
        "artifact manifest required_artifacts_complete must be true",
    )

    for artifact in artifact_manifest.artifacts:
        _require(
            artifact.status == ArtifactStatus.PRODUCED,
            "all artifact entries must have produced status",
        )
        _require(artifact.uri.strip(), "artifact entry URI must not be blank")
        _require(
            artifact.hash_algorithm is not None,
            "produced artifact entries require hash_algorithm",
        )
        _require(
            artifact.content_hash is not None and artifact.content_hash.strip(),
            "produced artifact entries require content_hash",
        )
        _require(
            artifact.size_bytes is not None,
            "produced artifact entries require size_bytes",
        )
        _require(
            artifact.created_at is not None,
            "produced artifact entries require created_at",
        )
        _require(
            artifact.validator_version is not None
            and artifact.validator_version.strip(),
            "produced artifact entries require validator_version",
        )


def _expected_artifact_manifest_uri(artifact_root_uri: str) -> str:
    return f"{artifact_root_uri.rstrip('/')}/artifact_manifest.json"


def _require(condition: object, message: str) -> None:
    if not condition:
        raise ValueError(message)


__all__ = [
    "CompletedExperimentRecordBundle",
    "CompletedExperimentRecordingResult",
    "validate_completed_experiment_bundle",
]
