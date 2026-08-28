from __future__ import annotations

import json
from pathlib import Path
from types import TracebackType
from typing import Any, cast

import pytest
from sqlalchemy.engine import Connection

from research_sdk.contracts import (
    DataSnapshotManifest,
    ExperimentRunRecord,
    RunArtifactManifest,
)
from research_sdk.experiment_recording import (
    CompletedExperimentDispositionCoherenceError,
    CompletedExperimentPairRecordBundle,
    CompletedExperimentPairRecordingResult,
    CompletedExperimentRecordBundle,
    CompletedExperimentRecordingResult,
    record_completed_experiment,
    record_completed_experiment_pair,
)
from research_sdk.experiment_recording.service import RepositoryFactory
from research_sdk.persistence import (
    AggregateIntegrityError,
    ContractHashConflictError,
    ExperimentLedgerRepository,
    PersistedRecordMetadata,
    PersistenceDisposition,
    PersistenceErrorContext,
    PersistenceWriteResult,
    UnsupportedVersioningConflictError,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "contracts"
SUPPORTED_DISPOSITION_COMBINATIONS = {
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
DISALLOWED_DISPOSITION_COMBINATIONS = [
    (snapshot, run, artifact)
    for snapshot in PersistenceDisposition
    for run in PersistenceDisposition
    for artifact in PersistenceDisposition
    if (snapshot, run, artifact) not in SUPPORTED_DISPOSITION_COMBINATIONS
]


class CommitFailure(RuntimeError):
    pass


class UnexpectedRepositoryError(RuntimeError):
    pass


class ForbiddenConnectionMethodError(AssertionError):
    pass


class _ConnectionSentinel:
    def begin(self) -> object:
        raise ForbiddenConnectionMethodError("service must not call begin")

    def begin_nested(self) -> object:
        raise ForbiddenConnectionMethodError("service must not create savepoints")


class _TransactionContext:
    def __init__(self, *, fail_on_exit: bool = False) -> None:
        self.connection = cast(Connection, _ConnectionSentinel())
        self.fail_on_exit = fail_on_exit
        self.entered = False
        self.exited = False
        self.exit_exc_type: type[BaseException] | None = None

    def __enter__(self) -> Connection:
        self.entered = True
        return self.connection

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        self.exited = True
        self.exit_exc_type = exc_type
        if self.fail_on_exit and exc_type is None:
            raise CommitFailure("commit failed")
        return False


class _TransactionFactory:
    def __init__(self, context: _TransactionContext) -> None:
        self.context = context
        self.call_count = 0

    def __call__(self) -> _TransactionContext:
        self.call_count += 1
        return self.context


class _FakeRepository:
    def __init__(
        self,
        *,
        snapshot_result: PersistenceWriteResult | BaseException,
        run_result: PersistenceWriteResult | BaseException,
        artifact_result: PersistenceWriteResult | BaseException,
    ) -> None:
        self.snapshot_result = snapshot_result
        self.run_result = run_result
        self.artifact_result = artifact_result
        self.calls: list[tuple[str, object]] = []

    def record_data_snapshot_manifest(
        self,
        snapshot: DataSnapshotManifest,
    ) -> PersistenceWriteResult:
        self.calls.append(("snapshot", snapshot))
        if isinstance(self.snapshot_result, BaseException):
            raise self.snapshot_result
        return self.snapshot_result

    def record_experiment_run(
        self,
        run: ExperimentRunRecord,
    ) -> PersistenceWriteResult:
        self.calls.append(("run", run))
        if isinstance(self.run_result, BaseException):
            raise self.run_result
        return self.run_result

    def record_run_artifact_manifest(
        self,
        *,
        manifest_id: str,
        manifest: RunArtifactManifest,
    ) -> PersistenceWriteResult:
        self.calls.append(("artifact", (manifest_id, manifest)))
        if isinstance(self.artifact_result, BaseException):
            raise self.artifact_result
        return self.artifact_result

    def record_research_note(self, note: Any) -> PersistenceWriteResult:
        raise AssertionError("research notes are outside completed recording")

    def append_review_event(
        self,
        *,
        review_event_id: str,
        subject_type: Any,
        subject_id: str,
        review: Any,
    ) -> PersistenceWriteResult:
        raise AssertionError("review events are outside completed recording")


class _PairFakeRepository(_FakeRepository):
    def __init__(
        self,
        *,
        asset_result: PersistenceWriteResult | BaseException,
        benchmark_result: PersistenceWriteResult | BaseException,
        run_result: PersistenceWriteResult | BaseException,
        artifact_result: PersistenceWriteResult | BaseException,
    ) -> None:
        super().__init__(
            snapshot_result=asset_result,
            run_result=run_result,
            artifact_result=artifact_result,
        )
        self.snapshot_results = (asset_result, benchmark_result)
        self.snapshot_index = 0

    def record_data_snapshot_manifest(
        self,
        snapshot: DataSnapshotManifest,
    ) -> PersistenceWriteResult:
        role = "asset_snapshot" if self.snapshot_index == 0 else "benchmark_snapshot"
        self.calls.append((role, snapshot))
        outcome = self.snapshot_results[self.snapshot_index]
        self.snapshot_index += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _RepositoryFactory:
    def __init__(self, repository: _FakeRepository) -> None:
        self.repository = repository
        self.call_count = 0
        self.connections: list[Connection] = []

    def __call__(self, connection: Connection) -> ExperimentLedgerRepository:
        self.call_count += 1
        self.connections.append(connection)
        return self.repository


@pytest.fixture
def bundle() -> CompletedExperimentRecordBundle:
    snapshot = DataSnapshotManifest.model_validate(
        load_fixture("data_snapshot_manifest.json")
    )
    loaded_run = ExperimentRunRecord.model_validate(
        load_fixture("experiment_run_record.json")
    )
    run = loaded_run.model_copy(
        update={
            "failure_labels": (),
            "failure_reason": None,
            "failure_logs_uri": None,
        }
    )
    artifact_manifest = RunArtifactManifest.model_validate(
        load_fixture("run_artifact_manifest.json")
    )
    return CompletedExperimentRecordBundle(
        snapshot=snapshot,
        run=run,
        manifest_id="manifest-20260709-001",
        artifact_manifest=artifact_manifest,
    )


@pytest.fixture
def pair_bundle(
    bundle: CompletedExperimentRecordBundle,
) -> CompletedExperimentPairRecordBundle:
    benchmark_snapshot_id = "distinct-benchmark-snapshot-for-pair-recording"
    benchmark_snapshot = bundle.snapshot.model_copy(
        update={"snapshot_id": benchmark_snapshot_id}
    )
    run = bundle.run.model_copy(
        update={
            "data_snapshot_id": bundle.snapshot.snapshot_id,
            "benchmark": bundle.run.benchmark.model_copy(
                update={"snapshot_id": benchmark_snapshot_id}
            ),
        }
    )
    return CompletedExperimentPairRecordBundle(
        asset_snapshot=bundle.snapshot,
        benchmark_snapshot=benchmark_snapshot,
        run=run,
        manifest_id=bundle.manifest_id,
        artifact_manifest=bundle.artifact_manifest,
    )


def test_invalid_bundle_opens_no_transaction(
    bundle: CompletedExperimentRecordBundle,
) -> None:
    invalid_bundle = bundle.model_copy(
        update={"run": bundle.run.model_copy(update={"data_snapshot_id": "other"})}
    )
    context = _TransactionContext()
    transaction_factory = _TransactionFactory(context)
    repository_factory = _RepositoryFactory(repository_with_dispositions())

    with pytest.raises(ValueError, match="data_snapshot_id must match"):
        record_completed_experiment(
            bundle=invalid_bundle,
            transaction_factory=transaction_factory,
            repository_factory=repository_factory,
        )

    assert transaction_factory.call_count == 0
    assert repository_factory.call_count == 0
    assert context.entered is False


def test_write_order_and_exact_supplied_contracts(
    bundle: CompletedExperimentRecordBundle,
) -> None:
    repository = repository_with_dispositions()
    result, context, repository_factory = record_with_fake_repository(
        bundle=bundle,
        repository=repository,
    )

    assert context.exit_exc_type is None
    assert repository_factory.connections == [context.connection]
    assert repository.calls == [
        ("snapshot", bundle.snapshot),
        ("run", bundle.run),
        ("artifact", (bundle.manifest_id, bundle.artifact_manifest)),
    ]
    assert result.snapshot_result is repository.snapshot_result
    assert result.experiment_run_result is repository.run_result
    assert result.artifact_manifest_result is repository.artifact_result


@pytest.mark.parametrize(
    "dispositions",
    [
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
    ],
)
def test_supported_disposition_combination_succeeds(
    bundle: CompletedExperimentRecordBundle,
    dispositions: tuple[
        PersistenceDisposition,
        PersistenceDisposition,
        PersistenceDisposition,
    ],
) -> None:
    result, context, _repository_factory = record_with_fake_repository(
        bundle=bundle,
        repository=repository_with_dispositions(*dispositions),
    )

    assert (
        result.snapshot_result.disposition,
        result.experiment_run_result.disposition,
        result.artifact_manifest_result.disposition,
    ) == dispositions
    assert context.exited is True
    assert context.exit_exc_type is None


@pytest.mark.parametrize(
    "dispositions",
    DISALLOWED_DISPOSITION_COMBINATIONS,
)
def test_every_disallowed_disposition_combination_raises_and_rolls_back(
    bundle: CompletedExperimentRecordBundle,
    dispositions: tuple[
        PersistenceDisposition,
        PersistenceDisposition,
        PersistenceDisposition,
    ],
) -> None:
    repository = repository_with_dispositions(*dispositions)
    context = _TransactionContext()
    transaction_factory = _TransactionFactory(context)
    repository_factory = _RepositoryFactory(repository)

    with pytest.raises(CompletedExperimentDispositionCoherenceError):
        record_completed_experiment(
            bundle=bundle,
            transaction_factory=transaction_factory,
            repository_factory=repository_factory,
        )

    assert context.exited is True
    assert context.exit_exc_type is CompletedExperimentDispositionCoherenceError
    assert repository.calls == [
        ("snapshot", bundle.snapshot),
        ("run", bundle.run),
        ("artifact", (bundle.manifest_id, bundle.artifact_manifest)),
    ]


@pytest.mark.parametrize(
    ("stage", "error"),
    [
        (
            "snapshot",
            ContractHashConflictError(
                PersistenceErrorContext(
                    table_name="data_snapshot_manifests",
                    operation="record_data_snapshot_manifest",
                    logical_identity={"snapshot_id": "snapshot"},
                )
            ),
        ),
        (
            "run",
            ContractHashConflictError(
                PersistenceErrorContext(
                    table_name="experiment_runs",
                    operation="record_experiment_run",
                    logical_identity={"run_id": "run"},
                )
            ),
        ),
        (
            "artifact",
            ContractHashConflictError(
                PersistenceErrorContext(
                    table_name="run_artifact_manifests",
                    operation="record_run_artifact_manifest",
                    logical_identity={"manifest_id": "manifest"},
                )
            ),
        ),
        (
            "artifact",
            UnsupportedVersioningConflictError(
                PersistenceErrorContext(
                    table_name="run_artifact_manifests",
                    operation="record_run_artifact_manifest",
                    logical_identity={"run_id": "run"},
                )
            ),
        ),
        (
            "artifact",
            AggregateIntegrityError(
                PersistenceErrorContext(
                    table_name="run_artifact_manifests",
                    operation="record_run_artifact_manifest",
                    logical_identity={"manifest_id": "manifest"},
                )
            ),
        ),
        ("run", UnexpectedRepositoryError("unexpected")),
    ],
)
def test_repository_exception_propagates_and_rolls_back(
    bundle: CompletedExperimentRecordBundle,
    stage: str,
    error: BaseException,
) -> None:
    repository = repository_with_error(stage=stage, error=error)
    context = _TransactionContext()
    transaction_factory = _TransactionFactory(context)
    repository_factory = _RepositoryFactory(repository)

    with pytest.raises(type(error)) as raised:
        record_completed_experiment(
            bundle=bundle,
            transaction_factory=transaction_factory,
            repository_factory=repository_factory,
        )

    assert raised.value is error
    assert context.exited is True
    assert context.exit_exc_type is type(error)
    assert repository_method_names(repository.calls) == expected_calls_for_failure(
        stage
    )


def test_commit_context_exit_failure_propagates_and_returns_no_result(
    bundle: CompletedExperimentRecordBundle,
) -> None:
    repository = repository_with_dispositions()
    context = _TransactionContext(fail_on_exit=True)
    transaction_factory = _TransactionFactory(context)
    repository_factory = _RepositoryFactory(repository)

    with pytest.raises(CommitFailure):
        record_completed_experiment(
            bundle=bundle,
            transaction_factory=transaction_factory,
            repository_factory=repository_factory,
        )

    assert context.exited is True
    assert context.exit_exc_type is None
    assert repository_method_names(repository.calls) == ["snapshot", "run", "artifact"]


def test_transaction_context_exits_normally_only_after_all_writes_succeed(
    bundle: CompletedExperimentRecordBundle,
) -> None:
    repository = repository_with_error(
        stage="artifact",
        error=UnexpectedRepositoryError("artifact failed"),
    )
    context = _TransactionContext()
    transaction_factory = _TransactionFactory(context)
    repository_factory = _RepositoryFactory(repository)

    with pytest.raises(UnexpectedRepositoryError):
        record_completed_experiment(
            bundle=bundle,
            transaction_factory=transaction_factory,
            repository_factory=repository_factory,
        )

    assert context.exited is True
    assert context.exit_exc_type is UnexpectedRepositoryError
    assert repository_method_names(repository.calls) == ["snapshot", "run", "artifact"]


def test_no_retry_occurs(
    bundle: CompletedExperimentRecordBundle,
) -> None:
    repository = repository_with_error(
        stage="run",
        error=UnexpectedRepositoryError("run failed"),
    )
    context = _TransactionContext()
    transaction_factory = _TransactionFactory(context)
    repository_factory = _RepositoryFactory(repository)

    with pytest.raises(UnexpectedRepositoryError):
        record_completed_experiment(
            bundle=bundle,
            transaction_factory=transaction_factory,
            repository_factory=repository_factory,
        )

    assert transaction_factory.call_count == 1
    assert repository_factory.call_count == 1
    assert repository_method_names(repository.calls) == ["snapshot", "run"]


def test_no_savepoint_or_nested_transaction_occurs(
    bundle: CompletedExperimentRecordBundle,
) -> None:
    result, context, _repository_factory = record_with_fake_repository(
        bundle=bundle,
        repository=repository_with_dispositions(),
    )

    assert result.snapshot_result.disposition is PersistenceDisposition.CREATED
    assert context.exited is True


def test_repository_factory_is_called_only_after_bundle_validation(
    bundle: CompletedExperimentRecordBundle,
) -> None:
    invalid_bundle = bundle.model_copy(
        update={
            "artifact_manifest": bundle.artifact_manifest.model_copy(
                update={"run_id": "other-run"}
            )
        }
    )
    context = _TransactionContext()
    transaction_factory = _TransactionFactory(context)
    repository_factory = _RepositoryFactory(repository_with_dispositions())

    with pytest.raises(ValueError, match="artifact manifest run_id must match"):
        record_completed_experiment(
            bundle=invalid_bundle,
            transaction_factory=transaction_factory,
            repository_factory=repository_factory,
        )

    assert repository_factory.call_count == 0
    assert transaction_factory.call_count == 0


def test_result_is_returned_only_after_successful_transaction_context_exit(
    bundle: CompletedExperimentRecordBundle,
) -> None:
    result, context, _repository_factory = record_with_fake_repository(
        bundle=bundle,
        repository=repository_with_dispositions(),
    )

    assert context.exited is True
    assert result.artifact_manifest_result.disposition is PersistenceDisposition.CREATED


def test_pair_recording_writes_distinct_snapshots_before_run_and_artifact(
    pair_bundle: CompletedExperimentPairRecordBundle,
) -> None:
    repository = pair_repository_with_dispositions()
    result, context = record_pair_with_fake_repository(
        bundle=pair_bundle,
        repository=repository,
    )

    assert context.exit_exc_type is None
    assert repository.calls == [
        ("asset_snapshot", pair_bundle.asset_snapshot),
        ("benchmark_snapshot", pair_bundle.benchmark_snapshot),
        ("run", pair_bundle.run),
        ("artifact", (pair_bundle.manifest_id, pair_bundle.artifact_manifest)),
    ]
    assert result.asset_snapshot_result.disposition is PersistenceDisposition.CREATED
    assert (
        result.benchmark_snapshot_result.disposition is PersistenceDisposition.CREATED
    )


@pytest.mark.parametrize(
    "dispositions",
    [
        (
            PersistenceDisposition.CREATED,
            PersistenceDisposition.CREATED,
            PersistenceDisposition.CREATED,
            PersistenceDisposition.CREATED,
        ),
        (
            PersistenceDisposition.REPLAYED,
            PersistenceDisposition.CREATED,
            PersistenceDisposition.CREATED,
            PersistenceDisposition.CREATED,
        ),
        (
            PersistenceDisposition.CREATED,
            PersistenceDisposition.REPLAYED,
            PersistenceDisposition.CREATED,
            PersistenceDisposition.CREATED,
        ),
        (
            PersistenceDisposition.REPLAYED,
            PersistenceDisposition.REPLAYED,
            PersistenceDisposition.REPLAYED,
            PersistenceDisposition.REPLAYED,
        ),
    ],
)
def test_pair_recording_supports_new_run_and_exact_replay(
    pair_bundle: CompletedExperimentPairRecordBundle,
    dispositions: tuple[
        PersistenceDisposition,
        PersistenceDisposition,
        PersistenceDisposition,
        PersistenceDisposition,
    ],
) -> None:
    result, context = record_pair_with_fake_repository(
        bundle=pair_bundle,
        repository=pair_repository_with_dispositions(*dispositions),
    )

    assert context.exit_exc_type is None
    assert (
        result.asset_snapshot_result.disposition,
        result.benchmark_snapshot_result.disposition,
        result.experiment_run_result.disposition,
        result.artifact_manifest_result.disposition,
    ) == dispositions


def test_pair_recording_rejects_missing_or_mismatched_benchmark_before_transaction(
    pair_bundle: CompletedExperimentPairRecordBundle,
) -> None:
    with pytest.raises(ValueError, match="benchmark_snapshot"):
        CompletedExperimentPairRecordBundle.model_validate(
            {
                "asset_snapshot": pair_bundle.asset_snapshot,
                "run": pair_bundle.run,
                "manifest_id": pair_bundle.manifest_id,
                "artifact_manifest": pair_bundle.artifact_manifest,
            }
        )

    invalid = pair_bundle.model_copy(
        update={
            "benchmark_snapshot": pair_bundle.benchmark_snapshot.model_copy(
                update={"snapshot_id": "mismatched-benchmark"}
            )
        }
    )
    context = _TransactionContext()
    transaction_factory = _TransactionFactory(context)
    repository_factory = _RepositoryFactory(pair_repository_with_dispositions())
    with pytest.raises(ValueError, match="benchmark snapshot_id must match"):
        record_completed_experiment_pair(
            bundle=invalid,
            transaction_factory=transaction_factory,
            repository_factory=cast(RepositoryFactory, repository_factory),
        )
    assert transaction_factory.call_count == 0
    assert repository_factory.call_count == 0


def test_pair_recording_rejects_artifact_mismatch_before_transaction(
    pair_bundle: CompletedExperimentPairRecordBundle,
) -> None:
    invalid = pair_bundle.model_copy(
        update={
            "artifact_manifest": pair_bundle.artifact_manifest.model_copy(
                update={"run_id": "different-run"}
            )
        }
    )
    transaction_factory = _TransactionFactory(_TransactionContext())

    with pytest.raises(ValueError, match="artifact manifest run_id must match"):
        record_completed_experiment_pair(
            bundle=invalid,
            transaction_factory=transaction_factory,
        )
    assert transaction_factory.call_count == 0


def test_pair_benchmark_conflict_propagates_and_rolls_back_atomically(
    pair_bundle: CompletedExperimentPairRecordBundle,
) -> None:
    conflict = ContractHashConflictError(
        PersistenceErrorContext(
            table_name="data_snapshot_manifests",
            operation="record_data_snapshot_manifest",
            logical_identity={"snapshot_id": "benchmark"},
        )
    )
    repository = pair_repository_with_dispositions(benchmark=conflict)
    context = _TransactionContext()
    repository_factory = _RepositoryFactory(repository)

    with pytest.raises(ContractHashConflictError) as raised:
        record_completed_experiment_pair(
            bundle=pair_bundle,
            transaction_factory=_TransactionFactory(context),
            repository_factory=cast(RepositoryFactory, repository_factory),
        )

    assert raised.value is conflict
    assert context.exit_exc_type is ContractHashConflictError
    assert repository_method_names(repository.calls) == [
        "asset_snapshot",
        "benchmark_snapshot",
    ]


def test_pair_partial_prior_run_state_is_rejected_inside_transaction(
    pair_bundle: CompletedExperimentPairRecordBundle,
) -> None:
    repository = pair_repository_with_dispositions(
        asset=PersistenceDisposition.REPLAYED,
        benchmark=PersistenceDisposition.REPLAYED,
        run=PersistenceDisposition.REPLAYED,
        artifact=PersistenceDisposition.CREATED,
    )
    context = _TransactionContext()

    with pytest.raises(CompletedExperimentDispositionCoherenceError):
        record_completed_experiment_pair(
            bundle=pair_bundle,
            transaction_factory=_TransactionFactory(context),
            repository_factory=cast(
                RepositoryFactory,
                _RepositoryFactory(repository),
            ),
        )

    assert context.exit_exc_type is CompletedExperimentDispositionCoherenceError
    assert repository_method_names(repository.calls) == [
        "asset_snapshot",
        "benchmark_snapshot",
        "run",
        "artifact",
    ]


def load_fixture(filename: str) -> dict[str, object]:
    return json.loads((FIXTURE_DIR / filename).read_text(encoding="utf-8"))


def repository_with_dispositions(
    snapshot: PersistenceDisposition = PersistenceDisposition.CREATED,
    run: PersistenceDisposition = PersistenceDisposition.CREATED,
    artifact: PersistenceDisposition = PersistenceDisposition.CREATED,
) -> _FakeRepository:
    return _FakeRepository(
        snapshot_result=write_result("data_snapshot_manifests", snapshot),
        run_result=write_result("experiment_runs", run),
        artifact_result=write_result("run_artifact_manifests", artifact),
    )


def repository_with_error(
    *,
    stage: str,
    error: BaseException,
) -> _FakeRepository:
    created = write_result("created", PersistenceDisposition.CREATED)
    return _FakeRepository(
        snapshot_result=error if stage == "snapshot" else created,
        run_result=error if stage == "run" else created,
        artifact_result=error if stage == "artifact" else created,
    )


def pair_repository_with_dispositions(
    asset: PersistenceDisposition | BaseException = PersistenceDisposition.CREATED,
    benchmark: PersistenceDisposition | BaseException = (
        PersistenceDisposition.CREATED
    ),
    run: PersistenceDisposition | BaseException = PersistenceDisposition.CREATED,
    artifact: PersistenceDisposition | BaseException = PersistenceDisposition.CREATED,
) -> _PairFakeRepository:
    def outcome(
        table_name: str,
        value: PersistenceDisposition | BaseException,
    ) -> PersistenceWriteResult | BaseException:
        if isinstance(value, BaseException):
            return value
        return write_result(table_name, value)

    return _PairFakeRepository(
        asset_result=outcome("data_snapshot_manifests", asset),
        benchmark_result=outcome("data_snapshot_manifests", benchmark),
        run_result=outcome("experiment_runs", run),
        artifact_result=outcome("run_artifact_manifests", artifact),
    )


def write_result(
    table_name: str,
    disposition: PersistenceDisposition,
) -> PersistenceWriteResult:
    return PersistenceWriteResult(
        disposition=disposition,
        record=PersistedRecordMetadata(
            table_name=table_name,
            primary_key={"id": table_name},
            contract_hash="abc123",
        ),
    )


def record_with_fake_repository(
    *,
    bundle: CompletedExperimentRecordBundle,
    repository: _FakeRepository,
) -> tuple[
    CompletedExperimentRecordingResult,
    _TransactionContext,
    _RepositoryFactory,
]:
    context = _TransactionContext()
    transaction_factory = _TransactionFactory(context)
    repository_factory = _RepositoryFactory(repository)
    result = record_completed_experiment(
        bundle=bundle,
        transaction_factory=transaction_factory,
        repository_factory=cast(RepositoryFactory, repository_factory),
    )
    return cast(Any, result), context, repository_factory


def record_pair_with_fake_repository(
    *,
    bundle: CompletedExperimentPairRecordBundle,
    repository: _PairFakeRepository,
) -> tuple[CompletedExperimentPairRecordingResult, _TransactionContext]:
    context = _TransactionContext()
    repository_factory = _RepositoryFactory(repository)
    result = record_completed_experiment_pair(
        bundle=bundle,
        transaction_factory=_TransactionFactory(context),
        repository_factory=cast(RepositoryFactory, repository_factory),
    )
    return result, context


def repository_method_names(calls: list[tuple[str, object]]) -> list[str]:
    return [name for name, _payload in calls]


def expected_calls_for_failure(stage: str) -> list[str]:
    if stage == "snapshot":
        return ["snapshot"]
    if stage == "run":
        return ["snapshot", "run"]
    if stage == "artifact":
        return ["snapshot", "run", "artifact"]
    raise AssertionError(f"unexpected stage: {stage}")
