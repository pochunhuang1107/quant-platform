"""Atomic service boundary for completed experiment recording."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlalchemy.engine import Connection

from research_sdk.experiment_recording.models import (
    CompletedExperimentRecordBundle,
    CompletedExperimentRecordingResult,
    validate_completed_experiment_bundle,
)
from research_sdk.persistence import (
    ExperimentLedgerRepository,
    PersistenceDisposition,
    SqlAlchemyExperimentLedgerRepository,
)

type TransactionFactory = Callable[[], AbstractContextManager[Connection]]
type RepositoryFactory = Callable[[Connection], ExperimentLedgerRepository]

_SUPPORTED_DISPOSITION_COMBINATIONS = frozenset(
    {
        (
            PersistenceDisposition.CREATED,
            PersistenceDisposition.CREATED,
            PersistenceDisposition.CREATED,
        ),
        (
            PersistenceDisposition.REPLAYED,
            PersistenceDisposition.CREATED,
            PersistenceDisposition.CREATED,
        ),
        (
            PersistenceDisposition.REPLAYED,
            PersistenceDisposition.REPLAYED,
            PersistenceDisposition.REPLAYED,
        ),
    }
)


class CompletedExperimentDispositionCoherenceError(ValueError):
    """Raised when component write outcomes imply partial prior state."""


def record_completed_experiment(
    *,
    bundle: CompletedExperimentRecordBundle,
    transaction_factory: TransactionFactory,
    repository_factory: RepositoryFactory = SqlAlchemyExperimentLedgerRepository,
) -> CompletedExperimentRecordingResult:
    """Record a completed experiment bundle in one caller-owned transaction."""

    validate_completed_experiment_bundle(bundle)

    recording_result: CompletedExperimentRecordingResult | None = None
    with transaction_factory() as connection:
        repository = repository_factory(connection)
        snapshot_result = repository.record_data_snapshot_manifest(bundle.snapshot)
        experiment_run_result = repository.record_experiment_run(bundle.run)
        artifact_manifest_result = repository.record_run_artifact_manifest(
            manifest_id=bundle.manifest_id,
            manifest=bundle.artifact_manifest,
        )
        recording_result = CompletedExperimentRecordingResult(
            snapshot_result=snapshot_result,
            experiment_run_result=experiment_run_result,
            artifact_manifest_result=artifact_manifest_result,
        )
        _validate_disposition_coherence(recording_result)

    if recording_result is None:
        raise RuntimeError("completed experiment recording produced no result")
    return recording_result


def _validate_disposition_coherence(
    result: CompletedExperimentRecordingResult,
) -> None:
    dispositions = (
        result.snapshot_result.disposition,
        result.experiment_run_result.disposition,
        result.artifact_manifest_result.disposition,
    )
    if dispositions not in _SUPPORTED_DISPOSITION_COMBINATIONS:
        joined = ", ".join(disposition.value for disposition in dispositions)
        raise CompletedExperimentDispositionCoherenceError(
            f"completed experiment write disposition combination is not supported: "
            f"{joined}"
        )


__all__ = [
    "CompletedExperimentDispositionCoherenceError",
    "CompletedExperimentRecordingResult",
    "RepositoryFactory",
    "TransactionFactory",
    "record_completed_experiment",
]
