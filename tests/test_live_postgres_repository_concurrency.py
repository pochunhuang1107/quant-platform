from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from typing import Any, Never

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, event, select, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from live_postgres_safety import (
    QUANT_RUN_LIVE_DB_TESTS_ENV_VAR,
    QUANT_TEST_DATABASE_URL_ENV_VAR,
    UnsafePostgresTestUrl,
    get_quant_test_database_url,
    should_run_live_db_tests,
    validate_safe_postgres_test_url,
)
from research_sdk.contracts import (
    DataSnapshotManifest,
    ExperimentRunRecord,
    ResearchNote,
    ReviewMetadata,
    RunArtifactManifest,
)
from research_sdk.persistence.errors import (
    ContractHashConflictError,
    DuplicateReviewEventError,
    UnsupportedVersioningConflictError,
)
from research_sdk.persistence.hashing import contract_sha256
from research_sdk.persistence.mappers import (
    ReviewSubjectType,
    run_artifact_manifest_to_rows,
)
from research_sdk.persistence.results import (
    PersistenceDisposition,
    PersistenceWriteResult,
)
from research_sdk.persistence.sqlalchemy_repository import (
    SqlAlchemyExperimentLedgerRepository,
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
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "contracts"

BARRIER_TIMEOUT_SECONDS = 5.0
POSTGRES_STATEMENT_TIMEOUT_MS = 15_000
FUTURE_RESULT_TIMEOUT_SECONDS = 25.0


@dataclass(frozen=True)
class _WorkerSpec:
    label: str
    operation: Callable[
        [SqlAlchemyExperimentLedgerRepository],
        PersistenceWriteResult,
    ]
    contract_hash: str | None = None
    raw_contract: dict[str, Any] | None = None
    review_row: dict[str, Any] | None = None
    manifest_id: str | None = None
    artifact_manifest: RunArtifactManifest | None = None


@dataclass(frozen=True)
class _WorkerOutcome:
    label: str
    result: PersistenceWriteResult | None = None
    error: Exception | None = None
    contract_hash: str | None = None
    raw_contract: dict[str, Any] | None = None
    review_row: dict[str, Any] | None = None
    manifest_id: str | None = None
    artifact_manifest: RunArtifactManifest | None = None


@pytest.fixture(scope="module")
def database_url() -> str:
    return _require_live_database_url()


@pytest.fixture(scope="module")
def migrated_engine(database_url: str) -> Engine:
    alembic_config = Config(str(ALEMBIC_INI))
    alembic_config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(alembic_config, "head")

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.mark.live_db
def test_concurrent_identical_experiment_run_replays(
    migrated_engine: Engine,
) -> None:
    run = _experiment_run_with(run_id="run-pr38-concurrency-identical")
    _cleanup_experiment_runs(migrated_engine, run.run_id)

    try:
        outcomes = _run_two_worker_race(
            engine=migrated_engine,
            left=_experiment_run_spec(label="left", run=run),
            right=_experiment_run_spec(label="right", run=run),
            expected_error_types=(),
        )

        created, replayed = _assert_one_created_one_replayed(outcomes)
        _assert_replay_matches_created(replayed=replayed, created=created)
        _assert_hash_backed_durable_state(
            engine=migrated_engine,
            table=experiment_runs,
            identity_column_name="run_id",
            identity_value=run.run_id,
            created=created,
        )
    finally:
        _cleanup_experiment_runs(migrated_engine, run.run_id)


@pytest.mark.live_db
def test_concurrent_conflicting_experiment_run_rejects_loser(
    migrated_engine: Engine,
) -> None:
    run = _experiment_run_with(run_id="run-pr38-concurrency-conflict")
    conflicting_run = run.model_copy(update={"strategy_version": "0.1.1"})
    _cleanup_experiment_runs(migrated_engine, run.run_id)

    try:
        outcomes = _run_two_worker_race(
            engine=migrated_engine,
            left=_experiment_run_spec(label="original", run=run),
            right=_experiment_run_spec(label="conflicting", run=conflicting_run),
            expected_error_types=(ContractHashConflictError,),
        )

        created = _single_created(outcomes)
        conflict = _single_error(outcomes, ContractHashConflictError)
        _assert_hash_conflict_describes_created_and_losing_hash(
            conflict=conflict,
            created=created,
            table_name="experiment_runs",
            operation="record_experiment_run",
            logical_identity={"run_id": run.run_id},
            constraint_name="pk_experiment_runs",
        )
        _assert_hash_backed_durable_state(
            engine=migrated_engine,
            table=experiment_runs,
            identity_column_name="run_id",
            identity_value=run.run_id,
            created=created,
        )
    finally:
        _cleanup_experiment_runs(migrated_engine, run.run_id)


@pytest.mark.live_db
def test_concurrent_identical_data_snapshot_manifest_replays(
    migrated_engine: Engine,
) -> None:
    snapshot = _data_snapshot_manifest_with(
        snapshot_id="snapshot-pr38-concurrency-identical"
    )
    _cleanup_data_snapshot_manifests(migrated_engine, snapshot.snapshot_id)

    try:
        outcomes = _run_two_worker_race(
            engine=migrated_engine,
            left=_data_snapshot_spec(label="left", snapshot=snapshot),
            right=_data_snapshot_spec(label="right", snapshot=snapshot),
            expected_error_types=(),
        )

        created, replayed = _assert_one_created_one_replayed(outcomes)
        _assert_replay_matches_created(replayed=replayed, created=created)
        _assert_hash_backed_durable_state(
            engine=migrated_engine,
            table=data_snapshot_manifests,
            identity_column_name="snapshot_id",
            identity_value=snapshot.snapshot_id,
            created=created,
        )
    finally:
        _cleanup_data_snapshot_manifests(migrated_engine, snapshot.snapshot_id)


@pytest.mark.live_db
def test_concurrent_conflicting_data_snapshot_manifest_rejects_loser(
    migrated_engine: Engine,
) -> None:
    snapshot = _data_snapshot_manifest_with(
        snapshot_id="snapshot-pr38-concurrency-conflict"
    )
    conflicting_snapshot = snapshot.model_copy(update={"source_version": "2026-07-10"})
    _cleanup_data_snapshot_manifests(migrated_engine, snapshot.snapshot_id)

    try:
        outcomes = _run_two_worker_race(
            engine=migrated_engine,
            left=_data_snapshot_spec(label="original", snapshot=snapshot),
            right=_data_snapshot_spec(
                label="conflicting",
                snapshot=conflicting_snapshot,
            ),
            expected_error_types=(ContractHashConflictError,),
        )

        created = _single_created(outcomes)
        conflict = _single_error(outcomes, ContractHashConflictError)
        _assert_hash_conflict_describes_created_and_losing_hash(
            conflict=conflict,
            created=created,
            table_name="data_snapshot_manifests",
            operation="record_data_snapshot_manifest",
            logical_identity={"snapshot_id": snapshot.snapshot_id},
            constraint_name="pk_data_snapshot_manifests",
        )
        _assert_hash_backed_durable_state(
            engine=migrated_engine,
            table=data_snapshot_manifests,
            identity_column_name="snapshot_id",
            identity_value=snapshot.snapshot_id,
            created=created,
        )
    finally:
        _cleanup_data_snapshot_manifests(migrated_engine, snapshot.snapshot_id)


@pytest.mark.live_db
def test_concurrent_identical_research_note_replays(
    migrated_engine: Engine,
) -> None:
    note = _research_note_with(note_id="note-pr38-concurrency-identical")
    _cleanup_research_notes(migrated_engine, note.note_id)

    try:
        outcomes = _run_two_worker_race(
            engine=migrated_engine,
            left=_research_note_spec(label="left", note=note),
            right=_research_note_spec(label="right", note=note),
            expected_error_types=(),
        )

        created, replayed = _assert_one_created_one_replayed(outcomes)
        _assert_replay_matches_created(replayed=replayed, created=created)
        _assert_hash_backed_durable_state(
            engine=migrated_engine,
            table=research_notes,
            identity_column_name="note_id",
            identity_value=note.note_id,
            created=created,
        )
    finally:
        _cleanup_research_notes(migrated_engine, note.note_id)


@pytest.mark.live_db
def test_concurrent_conflicting_research_note_rejects_loser(
    migrated_engine: Engine,
) -> None:
    note = _research_note_with(note_id="note-pr38-concurrency-conflict")
    conflicting_note = note.model_copy(update={"title": f"{note.title} conflict"})
    _cleanup_research_notes(migrated_engine, note.note_id)

    try:
        outcomes = _run_two_worker_race(
            engine=migrated_engine,
            left=_research_note_spec(label="original", note=note),
            right=_research_note_spec(label="conflicting", note=conflicting_note),
            expected_error_types=(ContractHashConflictError,),
        )

        created = _single_created(outcomes)
        conflict = _single_error(outcomes, ContractHashConflictError)
        _assert_hash_conflict_describes_created_and_losing_hash(
            conflict=conflict,
            created=created,
            table_name="research_notes",
            operation="record_research_note",
            logical_identity={"note_id": note.note_id},
            constraint_name="pk_research_notes",
        )
        _assert_hash_backed_durable_state(
            engine=migrated_engine,
            table=research_notes,
            identity_column_name="note_id",
            identity_value=note.note_id,
            created=created,
        )
    finally:
        _cleanup_research_notes(migrated_engine, note.note_id)


@pytest.mark.live_db
def test_concurrent_identical_artifact_manifest_primary_key_replays(
    migrated_engine: Engine,
) -> None:
    manifest_id = "manifest-pr38-pk-identical"
    manifest = _run_artifact_manifest_with(run_id="run-pr38-pk-identical")
    _cleanup_artifact_manifests(
        migrated_engine,
        manifest_ids=(manifest_id,),
        run_ids=(manifest.run_id,),
    )

    try:
        outcomes = _run_two_worker_race(
            engine=migrated_engine,
            left=_artifact_manifest_spec(
                label="left",
                manifest_id=manifest_id,
                manifest=manifest,
            ),
            right=_artifact_manifest_spec(
                label="right",
                manifest_id=manifest_id,
                manifest=manifest,
            ),
            expected_error_types=(),
        )

        created, replayed = _assert_one_created_one_replayed(outcomes)
        _assert_replay_matches_created(replayed=replayed, created=created)
        assert replayed.result is not None
        assert replayed.result.aggregate_entry_count == len(manifest.artifacts)
        _assert_artifact_durable_state(
            engine=migrated_engine,
            created=created,
            candidate_manifest_ids=(manifest_id,),
        )
    finally:
        _cleanup_artifact_manifests(
            migrated_engine,
            manifest_ids=(manifest_id,),
            run_ids=(manifest.run_id,),
        )


@pytest.mark.live_db
def test_concurrent_conflicting_artifact_manifest_primary_key_rejects_loser(
    migrated_engine: Engine,
) -> None:
    manifest_id = "manifest-pr38-pk-conflict"
    manifest = _run_artifact_manifest_with(run_id="run-pr38-pk-conflict")
    conflicting_manifest = _manifest_with_updates(
        manifest,
        artifact_root_uri="artifacts/run-pr38-pk-conflict-changed",
    )
    _cleanup_artifact_manifests(
        migrated_engine,
        manifest_ids=(manifest_id,),
        run_ids=(manifest.run_id,),
    )

    try:
        outcomes = _run_two_worker_race(
            engine=migrated_engine,
            left=_artifact_manifest_spec(
                label="original",
                manifest_id=manifest_id,
                manifest=manifest,
            ),
            right=_artifact_manifest_spec(
                label="conflicting",
                manifest_id=manifest_id,
                manifest=conflicting_manifest,
            ),
            expected_error_types=(ContractHashConflictError,),
        )

        created = _single_created(outcomes)
        conflict = _single_error(outcomes, ContractHashConflictError)
        _assert_hash_conflict_describes_created_and_losing_hash(
            conflict=conflict,
            created=created,
            table_name="run_artifact_manifests",
            operation="record_run_artifact_manifest",
            logical_identity={"manifest_id": manifest_id},
            constraint_name="pk_run_artifact_manifests",
        )
        _assert_artifact_durable_state(
            engine=migrated_engine,
            created=created,
            candidate_manifest_ids=(manifest_id,),
        )
    finally:
        _cleanup_artifact_manifests(
            migrated_engine,
            manifest_ids=(manifest_id,),
            run_ids=(manifest.run_id,),
        )


@pytest.mark.live_db
def test_concurrent_matching_artifact_manifest_natural_key_rejects_alias(
    migrated_engine: Engine,
) -> None:
    manifest_id = "manifest-pr38-natural-matching-original"
    alias_manifest_id = "manifest-pr38-natural-matching-alias"
    manifest = _run_artifact_manifest_with(run_id="run-pr38-natural-matching")
    _cleanup_artifact_manifests(
        migrated_engine,
        manifest_ids=(manifest_id, alias_manifest_id),
        run_ids=(manifest.run_id,),
    )

    try:
        outcomes = _run_two_worker_race(
            engine=migrated_engine,
            left=_artifact_manifest_spec(
                label="original",
                manifest_id=manifest_id,
                manifest=manifest,
            ),
            right=_artifact_manifest_spec(
                label="alias",
                manifest_id=alias_manifest_id,
                manifest=manifest,
            ),
            expected_error_types=(UnsupportedVersioningConflictError,),
        )

        created = _single_created(outcomes)
        conflict = _single_error(outcomes, UnsupportedVersioningConflictError)
        _assert_artifact_natural_key_conflict(
            conflict=conflict,
            created=created,
            run_id=manifest.run_id,
        )
        _assert_artifact_durable_state(
            engine=migrated_engine,
            created=created,
            candidate_manifest_ids=(manifest_id, alias_manifest_id),
        )
    finally:
        _cleanup_artifact_manifests(
            migrated_engine,
            manifest_ids=(manifest_id, alias_manifest_id),
            run_ids=(manifest.run_id,),
        )


@pytest.mark.live_db
def test_concurrent_changed_artifact_manifest_natural_key_rejects_alias(
    migrated_engine: Engine,
) -> None:
    manifest_id = "manifest-pr38-natural-changed-original"
    alias_manifest_id = "manifest-pr38-natural-changed-alias"
    manifest = _run_artifact_manifest_with(run_id="run-pr38-natural-changed")
    changed_manifest = _manifest_with_updates(
        manifest,
        artifact_root_uri="artifacts/run-pr38-natural-changed-version",
    )
    _cleanup_artifact_manifests(
        migrated_engine,
        manifest_ids=(manifest_id, alias_manifest_id),
        run_ids=(manifest.run_id,),
    )

    try:
        outcomes = _run_two_worker_race(
            engine=migrated_engine,
            left=_artifact_manifest_spec(
                label="original",
                manifest_id=manifest_id,
                manifest=manifest,
            ),
            right=_artifact_manifest_spec(
                label="changed",
                manifest_id=alias_manifest_id,
                manifest=changed_manifest,
            ),
            expected_error_types=(UnsupportedVersioningConflictError,),
        )

        created = _single_created(outcomes)
        conflict = _single_error(outcomes, UnsupportedVersioningConflictError)
        _assert_artifact_natural_key_conflict(
            conflict=conflict,
            created=created,
            run_id=manifest.run_id,
        )
        _assert_artifact_durable_state(
            engine=migrated_engine,
            created=created,
            candidate_manifest_ids=(manifest_id, alias_manifest_id),
        )
    finally:
        _cleanup_artifact_manifests(
            migrated_engine,
            manifest_ids=(manifest_id, alias_manifest_id),
            run_ids=(manifest.run_id,),
        )


@pytest.mark.live_db
def test_concurrent_identical_review_event_duplicate_rejects_without_replay(
    migrated_engine: Engine,
) -> None:
    review_event_id = "review-event-pr38-identical"
    review = ReviewMetadata.model_validate(_load_review_metadata_payload())
    _cleanup_review_events(migrated_engine, review_event_id)

    try:
        outcomes = _run_two_worker_race(
            engine=migrated_engine,
            left=_review_event_spec(
                label="left",
                review_event_id=review_event_id,
                subject_type=ReviewSubjectType.EXPERIMENT_RUN,
                subject_id="run-pr38-review-identical",
                review=review,
            ),
            right=_review_event_spec(
                label="right",
                review_event_id=review_event_id,
                subject_type=ReviewSubjectType.EXPERIMENT_RUN,
                subject_id="run-pr38-review-identical",
                review=review,
            ),
            expected_error_types=(DuplicateReviewEventError,),
        )

        created = _single_created(outcomes)
        duplicate = _single_error(outcomes, DuplicateReviewEventError)
        _assert_review_duplicate_conflict(
            duplicate=duplicate,
            review_event_id=review_event_id,
        )
        _assert_no_replayed_results(outcomes)
        _assert_review_event_durable_state(
            engine=migrated_engine,
            review_event_id=review_event_id,
            created=created,
        )
    finally:
        _cleanup_review_events(migrated_engine, review_event_id)


@pytest.mark.live_db
def test_concurrent_changed_review_event_duplicate_rejects_without_replay(
    migrated_engine: Engine,
) -> None:
    review_event_id = "review-event-pr38-changed"
    review = ReviewMetadata.model_validate(_load_review_metadata_payload())
    changed_review = ReviewMetadata.model_validate(
        {
            **review.model_dump(mode="json"),
            "decision": "Changed concurrent duplicate payload.",
        }
    )
    _cleanup_review_events(migrated_engine, review_event_id)

    try:
        outcomes = _run_two_worker_race(
            engine=migrated_engine,
            left=_review_event_spec(
                label="original",
                review_event_id=review_event_id,
                subject_type=ReviewSubjectType.EXPERIMENT_RUN,
                subject_id="run-pr38-review-changed-original",
                review=review,
            ),
            right=_review_event_spec(
                label="changed",
                review_event_id=review_event_id,
                subject_type=ReviewSubjectType.RESEARCH_NOTE,
                subject_id="note-pr38-review-changed",
                review=changed_review,
            ),
            expected_error_types=(DuplicateReviewEventError,),
        )

        created = _single_created(outcomes)
        duplicate = _single_error(outcomes, DuplicateReviewEventError)
        _assert_review_duplicate_conflict(
            duplicate=duplicate,
            review_event_id=review_event_id,
        )
        _assert_no_replayed_results(outcomes)
        _assert_review_event_durable_state(
            engine=migrated_engine,
            review_event_id=review_event_id,
            created=created,
        )
    finally:
        _cleanup_review_events(migrated_engine, review_event_id)


def _run_two_worker_race(
    *,
    engine: Engine,
    left: _WorkerSpec,
    right: _WorkerSpec,
    expected_error_types: tuple[type[Exception], ...],
) -> tuple[_WorkerOutcome, _WorkerOutcome]:
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(
                _run_worker,
                engine,
                barrier,
                left,
                expected_error_types,
            ),
            executor.submit(
                _run_worker,
                engine,
                barrier,
                right,
                expected_error_types,
            ),
        )
        return tuple(
            future.result(timeout=FUTURE_RESULT_TIMEOUT_SECONDS) for future in futures
        )


def _run_worker(
    engine: Engine,
    barrier: Barrier,
    spec: _WorkerSpec,
    expected_error_types: tuple[type[Exception], ...],
) -> _WorkerOutcome:
    with engine.connect() as base_connection:
        connection = base_connection.execution_options(isolation_level="READ COMMITTED")
        transaction = connection.begin()
        connection.execute(
            text(f"SET LOCAL statement_timeout = {POSTGRES_STATEMENT_TIMEOUT_MS}")
        )
        listener = _install_first_repository_sql_barrier(connection, barrier)
        try:
            repository = SqlAlchemyExperimentLedgerRepository(connection)
            result = spec.operation(repository)
        except Exception as error:
            if transaction.is_active:
                transaction.rollback()
            if expected_error_types and isinstance(error, expected_error_types):
                return _outcome_from_spec(spec, error=error)
            raise
        else:
            if result.disposition is PersistenceDisposition.CREATED:
                transaction.commit()
            else:
                transaction.rollback()
            return _outcome_from_spec(spec, result=result)
        finally:
            event.remove(connection, "before_cursor_execute", listener)


def _install_first_repository_sql_barrier(
    connection: Connection,
    barrier: Barrier,
) -> Callable[..., None]:
    has_waited = False

    def _before_cursor_execute(*_: object) -> None:
        nonlocal has_waited
        if has_waited:
            return
        has_waited = True
        barrier.wait(timeout=BARRIER_TIMEOUT_SECONDS)

    event.listen(connection, "before_cursor_execute", _before_cursor_execute)
    return _before_cursor_execute


def _outcome_from_spec(
    spec: _WorkerSpec,
    *,
    result: PersistenceWriteResult | None = None,
    error: Exception | None = None,
) -> _WorkerOutcome:
    return _WorkerOutcome(
        label=spec.label,
        result=result,
        error=error,
        contract_hash=spec.contract_hash,
        raw_contract=spec.raw_contract,
        review_row=spec.review_row,
        manifest_id=spec.manifest_id,
        artifact_manifest=spec.artifact_manifest,
    )


def _experiment_run_spec(
    *,
    label: str,
    run: ExperimentRunRecord,
) -> _WorkerSpec:
    return _WorkerSpec(
        label=label,
        operation=lambda repository: repository.record_experiment_run(run),
        contract_hash=contract_sha256(run),
        raw_contract=run.model_dump(mode="json"),
    )


def _data_snapshot_spec(
    *,
    label: str,
    snapshot: DataSnapshotManifest,
) -> _WorkerSpec:
    return _WorkerSpec(
        label=label,
        operation=lambda repository: repository.record_data_snapshot_manifest(snapshot),
        contract_hash=contract_sha256(snapshot),
        raw_contract=snapshot.model_dump(mode="json"),
    )


def _research_note_spec(
    *,
    label: str,
    note: ResearchNote,
) -> _WorkerSpec:
    return _WorkerSpec(
        label=label,
        operation=lambda repository: repository.record_research_note(note),
        contract_hash=contract_sha256(note),
        raw_contract=note.model_dump(mode="json"),
    )


def _artifact_manifest_spec(
    *,
    label: str,
    manifest_id: str,
    manifest: RunArtifactManifest,
) -> _WorkerSpec:
    return _WorkerSpec(
        label=label,
        operation=lambda repository: repository.record_run_artifact_manifest(
            manifest_id=manifest_id,
            manifest=manifest,
        ),
        contract_hash=contract_sha256(manifest),
        raw_contract=manifest.model_dump(mode="json"),
        manifest_id=manifest_id,
        artifact_manifest=manifest,
    )


def _review_event_spec(
    *,
    label: str,
    review_event_id: str,
    subject_type: ReviewSubjectType,
    subject_id: str,
    review: ReviewMetadata,
) -> _WorkerSpec:
    review_row = {
        "review_event_id": review_event_id,
        "subject_type": subject_type.value,
        "subject_id": subject_id,
        "review_status": review.review_status.value,
        "reviewer_id": review.reviewer_id,
        "review_role": review.review_role.value if review.review_role else None,
        "reviewed_at": review.reviewed_at,
        "decision": review.decision,
        "approval_scope": review.approval_scope,
        "approval_expires_at": review.approval_expires_at,
        "linked_pr": review.linked_pr,
        "review_notes_uri": review.review_notes_uri,
        "risk_approval_required": review.risk_approval_required,
        "raw_review": review.model_dump(mode="json"),
    }
    return _WorkerSpec(
        label=label,
        operation=lambda repository: repository.append_review_event(
            review_event_id=review_event_id,
            subject_type=subject_type,
            subject_id=subject_id,
            review=review,
        ),
        review_row=review_row,
    )


def _assert_one_created_one_replayed(
    outcomes: tuple[_WorkerOutcome, _WorkerOutcome],
) -> tuple[_WorkerOutcome, _WorkerOutcome]:
    created = _single_created(outcomes)
    replayed = _single_replayed(outcomes)
    assert _errors(outcomes) == []
    return created, replayed


def _assert_replay_matches_created(
    *,
    replayed: _WorkerOutcome,
    created: _WorkerOutcome,
) -> None:
    assert replayed.result is not None
    assert created.result is not None
    assert replayed.result.record.primary_key == created.result.record.primary_key
    assert replayed.result.record.contract_hash == created.result.record.contract_hash
    assert replayed.result.record.inserted_at == created.result.record.inserted_at


def _assert_hash_conflict_describes_created_and_losing_hash(
    *,
    conflict: _WorkerOutcome,
    created: _WorkerOutcome,
    table_name: str,
    operation: str,
    logical_identity: dict[str, str],
    constraint_name: str,
) -> None:
    assert isinstance(conflict.error, ContractHashConflictError)
    assert created.contract_hash is not None
    assert conflict.contract_hash is not None
    error = conflict.error
    assert error.context.table_name == table_name
    assert error.context.operation == operation
    assert error.context.logical_identity == logical_identity
    assert error.context.constraint_name == constraint_name
    assert error.context.existing_hash_prefix == created.contract_hash[:12]
    assert error.context.attempted_hash_prefix == conflict.contract_hash[:12]
    assert created.contract_hash not in str(error)
    assert conflict.contract_hash not in str(error)
    assert "raw_contract" not in str(error)


def _assert_artifact_natural_key_conflict(
    *,
    conflict: _WorkerOutcome,
    created: _WorkerOutcome,
    run_id: str,
) -> None:
    assert isinstance(conflict.error, UnsupportedVersioningConflictError)
    assert not isinstance(conflict.error, ContractHashConflictError)
    assert conflict.manifest_id is not None
    assert conflict.contract_hash is not None
    assert created.result is not None
    error = conflict.error
    assert error.context.table_name == "run_artifact_manifests"
    assert error.context.operation == "record_run_artifact_manifest"
    assert error.context.logical_identity == {
        "manifest_id": conflict.manifest_id,
        "run_id": run_id,
    }
    assert error.context.constraint_name == "uq_run_artifact_manifests_run_id"
    assert error.context.existing_hash_prefix is None
    assert error.context.attempted_hash_prefix == conflict.contract_hash[:12]
    assert isinstance(error.__cause__, IntegrityError)


def _assert_review_duplicate_conflict(
    *,
    duplicate: _WorkerOutcome,
    review_event_id: str,
) -> None:
    assert isinstance(duplicate.error, DuplicateReviewEventError)
    error = duplicate.error
    assert error.context.table_name == "review_events"
    assert error.context.operation == "append_review_event"
    assert error.context.logical_identity == {"review_event_id": review_event_id}
    assert error.context.constraint_name == "pk_review_events"
    assert error.context.existing_hash_prefix is None
    assert error.context.attempted_hash_prefix is None
    assert isinstance(error.__cause__, IntegrityError)


def _assert_no_replayed_results(
    outcomes: tuple[_WorkerOutcome, _WorkerOutcome],
) -> None:
    assert all(
        outcome.result is None
        or outcome.result.disposition is not PersistenceDisposition.REPLAYED
        for outcome in outcomes
    )


def _assert_hash_backed_durable_state(
    *,
    engine: Engine,
    table: Any,
    identity_column_name: str,
    identity_value: str,
    created: _WorkerOutcome,
) -> None:
    assert created.result is not None
    assert created.contract_hash is not None
    assert created.raw_contract is not None

    with engine.connect() as connection:
        with connection.begin():
            rows = tuple(
                connection.execute(
                    select(table).where(table.c[identity_column_name] == identity_value)
                ).mappings()
            )

    assert len(rows) == 1
    row = rows[0]
    assert row["contract_hash"] == created.contract_hash
    assert row["raw_contract"] == created.raw_contract
    assert row["inserted_at"] == created.result.record.inserted_at


def _assert_artifact_durable_state(
    *,
    engine: Engine,
    created: _WorkerOutcome,
    candidate_manifest_ids: tuple[str, ...],
) -> None:
    assert created.result is not None
    assert created.contract_hash is not None
    assert created.raw_contract is not None
    assert created.manifest_id is not None
    assert created.artifact_manifest is not None
    expected_rows = run_artifact_manifest_to_rows(
        manifest_id=created.manifest_id,
        manifest=created.artifact_manifest,
    )

    with engine.connect() as connection:
        with connection.begin():
            parent_rows = tuple(
                connection.execute(
                    select(run_artifact_manifests).where(
                        run_artifact_manifests.c.manifest_id.in_(candidate_manifest_ids)
                    )
                ).mappings()
            )
            entry_rows = tuple(
                dict(row)
                for row in connection.execute(
                    select(run_artifact_entries)
                    .where(
                        run_artifact_entries.c.manifest_id.in_(candidate_manifest_ids)
                    )
                    .order_by(run_artifact_entries.c.artifact_id)
                ).mappings()
            )

    assert len(parent_rows) == 1
    parent = parent_rows[0]
    assert parent["manifest_id"] == created.manifest_id
    assert parent["run_id"] == created.artifact_manifest.run_id
    assert parent["contract_hash"] == created.contract_hash
    assert parent["raw_contract"] == created.raw_contract
    assert parent["inserted_at"] == created.result.record.inserted_at
    assert created.result.aggregate_entry_count == len(
        created.artifact_manifest.artifacts
    )
    assert len(entry_rows) == len(created.artifact_manifest.artifacts)
    assert _entry_projection(entry_rows) == _expected_entry_projection(
        expected_rows.entries
    )

    for manifest_id in candidate_manifest_ids:
        if manifest_id == created.manifest_id:
            continue
        assert not any(row["manifest_id"] == manifest_id for row in parent_rows)
        assert not any(row["manifest_id"] == manifest_id for row in entry_rows)


def _assert_review_event_durable_state(
    *,
    engine: Engine,
    review_event_id: str,
    created: _WorkerOutcome,
) -> None:
    assert created.result is not None
    assert created.review_row is not None

    with engine.connect() as connection:
        with connection.begin():
            rows = tuple(
                connection.execute(
                    select(review_events).where(
                        review_events.c.review_event_id == review_event_id
                    )
                ).mappings()
            )

    assert len(rows) == 1
    row = rows[0]
    for key, expected_value in created.review_row.items():
        assert row[key] == expected_value
    assert row["inserted_at"] == created.result.record.inserted_at
    assert created.result.record.contract_hash is None
    assert created.result.aggregate_entry_count is None


def _single_created(
    outcomes: tuple[_WorkerOutcome, _WorkerOutcome],
) -> _WorkerOutcome:
    created = [
        outcome
        for outcome in outcomes
        if outcome.result is not None
        and outcome.result.disposition is PersistenceDisposition.CREATED
    ]
    assert len(created) == 1
    return created[0]


def _single_replayed(
    outcomes: tuple[_WorkerOutcome, _WorkerOutcome],
) -> _WorkerOutcome:
    replayed = [
        outcome
        for outcome in outcomes
        if outcome.result is not None
        and outcome.result.disposition is PersistenceDisposition.REPLAYED
    ]
    assert len(replayed) == 1
    return replayed[0]


def _single_error(
    outcomes: tuple[_WorkerOutcome, _WorkerOutcome],
    error_type: type[Exception],
) -> _WorkerOutcome:
    errors = [
        outcome
        for outcome in outcomes
        if outcome.error is not None and type(outcome.error) is error_type
    ]
    assert len(errors) == 1
    return errors[0]


def _errors(outcomes: tuple[_WorkerOutcome, _WorkerOutcome]) -> list[Exception]:
    return [outcome.error for outcome in outcomes if outcome.error is not None]


def _cleanup_experiment_runs(engine: Engine, *run_ids: str) -> None:
    with engine.connect() as connection:
        with connection.begin():
            connection.execute(
                delete(experiment_runs).where(experiment_runs.c.run_id.in_(run_ids))
            )


def _cleanup_data_snapshot_manifests(engine: Engine, *snapshot_ids: str) -> None:
    with engine.connect() as connection:
        with connection.begin():
            connection.execute(
                delete(data_snapshot_manifests).where(
                    data_snapshot_manifests.c.snapshot_id.in_(snapshot_ids)
                )
            )


def _cleanup_research_notes(engine: Engine, *note_ids: str) -> None:
    with engine.connect() as connection:
        with connection.begin():
            connection.execute(
                delete(research_notes).where(research_notes.c.note_id.in_(note_ids))
            )


def _cleanup_artifact_manifests(
    engine: Engine,
    *,
    manifest_ids: tuple[str, ...],
    run_ids: tuple[str, ...],
) -> None:
    with engine.connect() as connection:
        with connection.begin():
            connection.execute(
                delete(run_artifact_entries).where(
                    run_artifact_entries.c.manifest_id.in_(manifest_ids)
                )
            )
            connection.execute(
                delete(run_artifact_entries).where(
                    run_artifact_entries.c.run_id.in_(run_ids)
                )
            )
            connection.execute(
                delete(run_artifact_manifests).where(
                    run_artifact_manifests.c.manifest_id.in_(manifest_ids)
                )
            )
            connection.execute(
                delete(run_artifact_manifests).where(
                    run_artifact_manifests.c.run_id.in_(run_ids)
                )
            )


def _cleanup_review_events(engine: Engine, *review_event_ids: str) -> None:
    with engine.connect() as connection:
        with connection.begin():
            connection.execute(
                delete(review_events).where(
                    review_events.c.review_event_id.in_(review_event_ids)
                )
            )


def _entry_projection(rows: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            key: _normalize_entry_value(key, value)
            for key, value in row.items()
            if key != "inserted_at"
        }
        for row in rows
    )


def _expected_entry_projection(
    entries: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    return tuple(sorted(entries, key=lambda entry: entry["artifact_id"]))


def _normalize_entry_value(column_name: str, value: object) -> object:
    if column_name != "created_at" or value is None:
        return value
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return value


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


def _load_experiment_run_payload() -> dict[str, Any]:
    return json.loads(
        (FIXTURE_DIR / "experiment_run_record.json").read_text(encoding="utf-8")
    )


def _load_data_snapshot_payload() -> dict[str, Any]:
    return json.loads(
        (FIXTURE_DIR / "data_snapshot_manifest.json").read_text(encoding="utf-8")
    )


def _load_research_note_payload() -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / "research_note.json").read_text(encoding="utf-8"))


def _load_artifact_manifest_payload() -> dict[str, Any]:
    return json.loads(
        (FIXTURE_DIR / "run_artifact_manifest.json").read_text(encoding="utf-8")
    )


def _load_review_metadata_payload() -> dict[str, Any]:
    return json.loads(
        (FIXTURE_DIR / "review_metadata.json").read_text(encoding="utf-8")
    )


def _experiment_run_with(*, run_id: str) -> ExperimentRunRecord:
    run = ExperimentRunRecord.model_validate(_load_experiment_run_payload())
    return run.model_copy(update={"run_id": run_id})


def _data_snapshot_manifest_with(*, snapshot_id: str) -> DataSnapshotManifest:
    snapshot = DataSnapshotManifest.model_validate(_load_data_snapshot_payload())
    return snapshot.model_copy(update={"snapshot_id": snapshot_id})


def _research_note_with(*, note_id: str) -> ResearchNote:
    note = ResearchNote.model_validate(_load_research_note_payload())
    return note.model_copy(update={"note_id": note_id})


def _run_artifact_manifest_with(*, run_id: str) -> RunArtifactManifest:
    payload = _load_artifact_manifest_payload()
    payload["run_id"] = run_id
    payload["artifact_root_uri"] = f"artifacts/{run_id}"
    for artifact in payload["artifacts"]:
        artifact["uri"] = f"artifacts/{run_id}/{artifact['filename']}"
    return RunArtifactManifest.model_validate(payload)


def _manifest_with_updates(
    manifest: RunArtifactManifest,
    **updates: object,
) -> RunArtifactManifest:
    payload = manifest.model_dump(mode="json")
    payload.update(updates)
    return RunArtifactManifest.model_validate(payload)
