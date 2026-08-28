"""Atomic service boundary for completed experiment recording."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlalchemy.engine import Connection

from research_sdk.experiment_recording.models import (
    CompletedExperimentPairRecordBundle,
    CompletedExperimentPairRecordingResult,
    CompletedExperimentRecordBundle,
    CompletedExperimentRecordingResult,
    validate_completed_experiment_bundle,
    validate_completed_experiment_pair_bundle,
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


def record_completed_experiment_pair(
    *,
    bundle: CompletedExperimentPairRecordBundle,
    transaction_factory: TransactionFactory,
    repository_factory: RepositoryFactory = SqlAlchemyExperimentLedgerRepository,
) -> CompletedExperimentPairRecordingResult:
    """Record distinct asset/benchmark snapshots and one run atomically."""

    validate_completed_experiment_pair_bundle(bundle)
    recording_result: CompletedExperimentPairRecordingResult | None = None
    with transaction_factory() as connection:
        repository = repository_factory(connection)
        asset_snapshot_result = repository.record_data_snapshot_manifest(
            bundle.asset_snapshot
        )
        benchmark_snapshot_result = repository.record_data_snapshot_manifest(
            bundle.benchmark_snapshot
        )
        experiment_run_result = repository.record_experiment_run(bundle.run)
        artifact_manifest_result = repository.record_run_artifact_manifest(
            manifest_id=bundle.manifest_id,
            manifest=bundle.artifact_manifest,
        )
        recording_result = CompletedExperimentPairRecordingResult(
            asset_snapshot_result=asset_snapshot_result,
            benchmark_snapshot_result=benchmark_snapshot_result,
            experiment_run_result=experiment_run_result,
            artifact_manifest_result=artifact_manifest_result,
        )
        _validate_pair_disposition_coherence(recording_result)

    if recording_result is None:
        raise RuntimeError("completed experiment pair recording produced no result")
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


def _validate_pair_disposition_coherence(
    result: CompletedExperimentPairRecordingResult,
) -> None:
    asset = result.asset_snapshot_result.disposition
    benchmark = result.benchmark_snapshot_result.disposition
    run = result.experiment_run_result.disposition
    artifact = result.artifact_manifest_result.disposition
    snapshots = {asset, benchmark}
    new_run_is_coherent = (
        run is PersistenceDisposition.CREATED
        and artifact is PersistenceDisposition.CREATED
        and snapshots
        <= {
            PersistenceDisposition.CREATED,
            PersistenceDisposition.REPLAYED,
        }
    )
    replay_is_coherent = (
        run is PersistenceDisposition.REPLAYED
        and artifact is PersistenceDisposition.REPLAYED
        and snapshots == {PersistenceDisposition.REPLAYED}
    )
    if not new_run_is_coherent and not replay_is_coherent:
        joined = ", ".join(item.value for item in (asset, benchmark, run, artifact))
        raise CompletedExperimentDispositionCoherenceError(
            "completed experiment pair write disposition combination is not "
            f"supported: {joined}"
        )


__all__ = [
    "CompletedExperimentDispositionCoherenceError",
    "CompletedExperimentRecordingResult",
    "RepositoryFactory",
    "TransactionFactory",
    "record_completed_experiment",
    "record_completed_experiment_pair",
]
