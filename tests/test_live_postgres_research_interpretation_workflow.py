from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from threading import Barrier
from typing import Any, Never

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, event, func, select, text
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
from research_sdk.contracts import ResearchNote, ResearchReportCard
from research_sdk.experiment_recording import (
    CompletedExperimentRecordBundle,
    record_completed_experiment,
)
from research_sdk.persistence import ContractHashConflictError, PersistenceDisposition
from research_sdk.persistence.sqlalchemy_repository import (
    SqlAlchemyExperimentLedgerRepository,
)
from research_sdk.persistence.tables import research_note_report_cards, research_notes
from research_sdk.research_interpretation import (
    FinalizedResearchInterpretationBundle,
    FinalizedResearchInterpretationRecordingResult,
    FinalizedResearchInterpretationValidationError,
    record_finalized_research_interpretation,
)
from research_sdk.research_note_identity import (
    derive_finalized_research_note_id,
    verify_finalized_research_note_identity,
)
from test_live_postgres_backtest_engine_recording import (
    build_bundle,
    execution_metadata,
)
from test_live_postgres_research_report_card_repository import (
    _report_card_from_bundle,
    cleanup_bundles,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
BARRIER_TIMEOUT_SECONDS = 5.0
POSTGRES_STATEMENT_TIMEOUT_MS = 15_000
FUTURE_RESULT_TIMEOUT_SECONDS = 25.0


@dataclass(frozen=True)
class _WorkflowSpec:
    label: str
    note: ResearchNote
    report_card_id: str


@dataclass(frozen=True)
class _WorkflowOutcome:
    label: str
    result: FinalizedResearchInterpretationRecordingResult | None = None
    error: Exception | None = None


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
def test_direct_note_report_card_link_repository_create_replay_many_to_many_and_fk(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    first_bundle = build_bundle(tmp_path, artifact_label="direct-link-first")
    second_bundle = build_bundle(
        tmp_path,
        artifact_label="direct-link-second",
        metadata=execution_metadata(dependency_lock_hash="sha256:changed-lock"),
    )
    first_report_card = _report_card_from_bundle(first_bundle)
    second_report_card = _report_card_from_bundle(second_bundle)
    note = _finalized_note_for_report_card(first_report_card)
    cleanup_interpretations(migrated_engine, note.note_id, "missing-direct-link-note")
    cleanup_bundles(migrated_engine, first_bundle, second_bundle)
    try:
        _persist_completed_experiment_and_report_card(
            migrated_engine,
            first_bundle,
            first_report_card,
        )
        _persist_completed_experiment_and_report_card(
            migrated_engine,
            second_bundle,
            second_report_card,
        )

        with migrated_engine.begin() as connection:
            repository = SqlAlchemyExperimentLedgerRepository(connection)
            repository.record_research_note(note)
            created = repository.record_research_note_report_card_link(
                note_id=note.note_id,
                report_card_id=second_report_card.report_card_id,
            )
            replayed = repository.record_research_note_report_card_link(
                note_id=note.note_id,
                report_card_id=second_report_card.report_card_id,
            )
            second_created = repository.record_research_note_report_card_link(
                note_id=note.note_id,
                report_card_id=first_report_card.report_card_id,
            )
            linked_ids = repository.get_report_card_ids_for_note(note.note_id)

        assert created.disposition is PersistenceDisposition.CREATED
        assert replayed.disposition is PersistenceDisposition.REPLAYED
        assert second_created.disposition is PersistenceDisposition.CREATED
        assert linked_ids == tuple(
            sorted(
                (
                    first_report_card.report_card_id,
                    second_report_card.report_card_id,
                )
            )
        )
        assert (
            _link_count(
                migrated_engine,
                note.note_id,
                first_report_card.report_card_id,
            )
            == 1
        )
        assert (
            _link_count(
                migrated_engine,
                note.note_id,
                second_report_card.report_card_id,
            )
            == 1
        )

        with pytest.raises(IntegrityError):
            with migrated_engine.begin() as connection:
                repository = SqlAlchemyExperimentLedgerRepository(connection)
                repository.record_research_note_report_card_link(
                    note_id="missing-direct-link-note",
                    report_card_id=first_report_card.report_card_id,
                )
        assert (
            _link_count(
                migrated_engine,
                "missing-direct-link-note",
                first_report_card.report_card_id,
            )
            == 0
        )

        missing_report_card_id = "report-card-" + "e" * 64
        with pytest.raises(IntegrityError):
            with migrated_engine.begin() as connection:
                repository = SqlAlchemyExperimentLedgerRepository(connection)
                repository.record_research_note_report_card_link(
                    note_id=note.note_id,
                    report_card_id=missing_report_card_id,
                )
        assert _link_count(migrated_engine, note.note_id, missing_report_card_id) == 0
    finally:
        cleanup_interpretations(
            migrated_engine,
            note.note_id,
            "missing-direct-link-note",
        )
        cleanup_bundles(migrated_engine, first_bundle, second_bundle)


@pytest.mark.live_db
def test_synthetic_finalized_research_interpretation_vertical_workflow(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path, artifact_label="finalized-note-vertical")
    report_card = _report_card_from_bundle(bundle)
    note = _finalized_note_for_report_card(report_card)
    cleanup_interpretations(migrated_engine, note.note_id)
    cleanup_bundles(migrated_engine, bundle)
    try:
        _persist_completed_experiment_and_report_card(
            migrated_engine, bundle, report_card
        )

        result = record_finalized_research_interpretation(
            bundle=FinalizedResearchInterpretationBundle(
                note=note,
                report_card_id=report_card.report_card_id,
            ),
            transaction_factory=migrated_engine.begin,
        )

        assert result.research_note_result.disposition is PersistenceDisposition.CREATED
        assert result.report_card_link_result.disposition is (
            PersistenceDisposition.CREATED
        )

        with migrated_engine.connect() as connection:
            repository = SqlAlchemyExperimentLedgerRepository(connection)
            loaded_note = repository.get_research_note(note.note_id)
            linked_report_card_ids = repository.get_report_card_ids_for_note(
                note.note_id
            )

        assert loaded_note == note
        assert linked_report_card_ids == (report_card.report_card_id,)
        verify_finalized_research_note_identity(
            note=loaded_note,
            report_card_ids=linked_report_card_ids,
        )

        replayed = record_finalized_research_interpretation(
            bundle=FinalizedResearchInterpretationBundle(
                note=note,
                report_card_id=report_card.report_card_id,
            ),
            transaction_factory=migrated_engine.begin,
        )
        assert replayed.research_note_result.disposition is (
            PersistenceDisposition.REPLAYED
        )
        assert replayed.report_card_link_result.disposition is (
            PersistenceDisposition.REPLAYED
        )

        conflicting_note = note.model_copy(
            update={
                "body_markdown": (
                    "# Changed body\n\nExcluded from natural identity but protected "
                    "by the whole-contract hash."
                )
            }
        )
        with pytest.raises(ContractHashConflictError):
            record_finalized_research_interpretation(
                bundle=FinalizedResearchInterpretationBundle(
                    note=conflicting_note,
                    report_card_id=report_card.report_card_id,
                ),
                transaction_factory=migrated_engine.begin,
            )

        agent_reviewed = _with_review_update(
            note,
            report_card.report_card_id,
            review_role="agent_reviewer",
        )
        with pytest.raises(FinalizedResearchInterpretationValidationError):
            record_finalized_research_interpretation(
                bundle=FinalizedResearchInterpretationBundle(
                    note=agent_reviewed,
                    report_card_id=report_card.report_card_id,
                ),
                transaction_factory=migrated_engine.begin,
            )

        mismatched_run = _with_reference_update(
            note,
            report_card.report_card_id,
            run_ids=("wrong-run",),
        )
        with pytest.raises(FinalizedResearchInterpretationValidationError):
            record_finalized_research_interpretation(
                bundle=FinalizedResearchInterpretationBundle(
                    note=mismatched_run,
                    report_card_id=report_card.report_card_id,
                ),
                transaction_factory=migrated_engine.begin,
            )

        assert _note_count(migrated_engine, note.note_id) == 1
        assert (
            _link_count(migrated_engine, note.note_id, report_card.report_card_id) == 1
        )
    finally:
        cleanup_interpretations(migrated_engine, note.note_id)
        cleanup_bundles(migrated_engine, bundle)


@pytest.mark.live_db
def test_concurrent_identical_finalized_interpretation_calls_converge(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path, artifact_label="finalized-note-race-identical")
    report_card = _report_card_from_bundle(bundle)
    note = _finalized_note_for_report_card(report_card)
    cleanup_interpretations(migrated_engine, note.note_id)
    cleanup_bundles(migrated_engine, bundle)
    try:
        _persist_completed_experiment_and_report_card(
            migrated_engine, bundle, report_card
        )
        outcomes = _run_two_worker_race(
            engine=migrated_engine,
            left=_workflow_spec(label="left", note=note, report_card=report_card),
            right=_workflow_spec(label="right", note=note, report_card=report_card),
            expected_error_types=(),
        )

        assert _errors(outcomes) == []
        assert _note_count(migrated_engine, note.note_id) == 1
        assert (
            _link_count(migrated_engine, note.note_id, report_card.report_card_id) == 1
        )
        assert {
            (
                outcome.result.research_note_result.disposition,
                outcome.result.report_card_link_result.disposition,
            )
            for outcome in outcomes
            if outcome.result is not None
        } <= {
            (PersistenceDisposition.CREATED, PersistenceDisposition.CREATED),
            (PersistenceDisposition.REPLAYED, PersistenceDisposition.REPLAYED),
            (PersistenceDisposition.REPLAYED, PersistenceDisposition.CREATED),
        }
    finally:
        cleanup_interpretations(migrated_engine, note.note_id)
        cleanup_bundles(migrated_engine, bundle)


@pytest.mark.live_db
def test_concurrent_conflicting_finalized_interpretation_rejects_loser(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path, artifact_label="finalized-note-race-conflict")
    report_card = _report_card_from_bundle(bundle)
    note = _finalized_note_for_report_card(report_card)
    conflicting_note = note.model_copy(
        update={"body_markdown": "# Conflicting excluded metadata body."}
    )
    cleanup_interpretations(migrated_engine, note.note_id)
    cleanup_bundles(migrated_engine, bundle)
    try:
        _persist_completed_experiment_and_report_card(
            migrated_engine, bundle, report_card
        )
        outcomes = _run_two_worker_race(
            engine=migrated_engine,
            left=_workflow_spec(label="winner", note=note, report_card=report_card),
            right=_workflow_spec(
                label="conflict",
                note=conflicting_note,
                report_card=report_card,
            ),
            expected_error_types=(ContractHashConflictError,),
        )

        assert len(_errors(outcomes)) == 1
        assert isinstance(_errors(outcomes)[0], ContractHashConflictError)
        assert _note_count(migrated_engine, note.note_id) == 1
        assert (
            _link_count(migrated_engine, note.note_id, report_card.report_card_id) == 1
        )
    finally:
        cleanup_interpretations(migrated_engine, note.note_id)
        cleanup_bundles(migrated_engine, bundle)


def _persist_completed_experiment_and_report_card(
    engine: Engine,
    bundle: CompletedExperimentRecordBundle,
    report_card: ResearchReportCard,
) -> None:
    record_completed_experiment(bundle=bundle, transaction_factory=engine.begin)
    with engine.begin() as connection:
        repository = SqlAlchemyExperimentLedgerRepository(connection)
        repository.record_research_report_card(report_card)


def _workflow_spec(
    *,
    label: str,
    note: ResearchNote,
    report_card: ResearchReportCard,
) -> _WorkflowSpec:
    return _WorkflowSpec(
        label=label,
        note=note,
        report_card_id=report_card.report_card_id,
    )


def _run_two_worker_race(
    *,
    engine: Engine,
    left: _WorkflowSpec,
    right: _WorkflowSpec,
    expected_error_types: tuple[type[Exception], ...],
) -> tuple[_WorkflowOutcome, _WorkflowOutcome]:
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(_run_worker, engine, barrier, left, expected_error_types),
            executor.submit(_run_worker, engine, barrier, right, expected_error_types),
        )
        return tuple(
            future.result(timeout=FUTURE_RESULT_TIMEOUT_SECONDS) for future in futures
        )


def _run_worker(
    engine: Engine,
    barrier: Barrier,
    spec: _WorkflowSpec,
    expected_error_types: tuple[type[Exception], ...],
) -> _WorkflowOutcome:
    def _transaction_factory() -> AbstractContextManager[Connection]:
        base_connection = engine.connect()
        connection = base_connection.execution_options(isolation_level="READ COMMITTED")
        transaction = connection.begin()
        connection.execute(
            text(f"SET LOCAL statement_timeout = {POSTGRES_STATEMENT_TIMEOUT_MS}")
        )
        listener = _install_first_repository_sql_barrier(connection, barrier)
        return _WorkerTransaction(base_connection, connection, transaction, listener)

    try:
        result = record_finalized_research_interpretation(
            bundle=FinalizedResearchInterpretationBundle(
                note=spec.note,
                report_card_id=spec.report_card_id,
            ),
            transaction_factory=_transaction_factory,
        )
    except Exception as error:
        if expected_error_types and isinstance(error, expected_error_types):
            return _WorkflowOutcome(label=spec.label, error=error)
        raise
    return _WorkflowOutcome(label=spec.label, result=result)


class _WorkerTransaction(AbstractContextManager[Connection]):
    def __init__(
        self,
        base_connection: Connection,
        connection: Connection,
        transaction: Any,
        listener: Callable[..., None],
    ) -> None:
        self._base_connection = base_connection
        self._connection = connection
        self._transaction = transaction
        self._listener = listener

    def __enter__(self) -> Connection:
        return self._connection

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        try:
            if exc_type is None:
                self._transaction.commit()
            else:
                self._transaction.rollback()
        finally:
            event.remove(self._connection, "before_cursor_execute", self._listener)
            self._base_connection.close()


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


def _finalized_note_for_report_card(report_card: ResearchReportCard) -> ResearchNote:
    references = {
        "experiment_ids": [report_card.experiment_id],
        "run_ids": [report_card.source_run_id],
        "artifact_uris": [report_card.evidence.artifacts[0].uri],
        "artifact_manifest_uris": [report_card.evidence.artifact_manifest_uri],
        "data_snapshot_ids": [report_card.lineage.data_snapshot_id],
        "feature_snapshot_ids": [],
        "benchmark_snapshot_ids": [report_card.lineage.benchmark_snapshot_id],
        "strategy_ids": [report_card.lineage.strategy_id],
    }
    payload = {
        "note_id": "temporary-note-id",
        "schema_version": "1.0.0",
        "note_type": "experiment_result",
        "status": "finalized",
        "created_at": "2026-07-09T10:00:00Z",
        "created_by": "human-owner-a",
        "updated_at": "2026-07-09T10:00:00Z",
        "updated_by": "human-owner-a",
        "title": "Synthetic ETF infrastructure validation interpretation",
        "hypothesis": {
            "statement": "The deterministic fixture validates persistence plumbing.",
            "status": "supported",
        },
        "motivation": "Confirm finalized interpretation can link to durable facts.",
        "methodology": "Review one deterministic synthetic ETF report card.",
        "benchmark_summary": "Benchmark lineage is copied from the report card.",
        "cost_assumptions": report_card.assumptions.cost_model,
        "slippage_assumptions": report_card.assumptions.slippage_model,
        "lookback": report_card.assumptions.lookback,
        "lag_assumptions": report_card.assumptions.lag_assumptions,
        "leakage_review": report_card.assumptions.leakage_review,
        "results_summary": "Synthetic infrastructure fixture completed successfully.",
        "interpretation": (
            "The human-owner interpretation is limited to durable infrastructure "
            "validation of generated synthetic data."
        ),
        "risks": ["Misreading fixture output as investment evidence."],
        "failure_modes": ["Persistence linkage or readback integrity regression."],
        "validation_plan": (
            "Replay persistence and reject invalid review/reference states."
        ),
        "limitations": [
            "Generated synthetic data only.",
            "Infrastructure validation only.",
            "No investment-performance claim.",
            "Not production-data strategy research.",
            "Not paper-trading evidence.",
            "Not live-trading evidence.",
        ],
        "next_steps": ["Defer comparison workflow to a later slice."],
        "evidence_strength": "moderate",
        "decision": {
            "outcome": "continue_research",
            "rationale": "The fixture validates infrastructure, not strategy merit.",
        },
        "review": {
            "review_status": "approved",
            "reviewer_id": "human-owner-a",
            "review_role": "human_owner",
            "reviewed_at": "2026-07-09T10:00:00Z",
            "risk_approval_required": True,
        },
        "references": references,
        "tags": ["synthetic", "infrastructure"],
        "body_markdown": "# Synthetic ETF infrastructure validation\n",
        "parent_note_id": None,
        "supersedes_note_id": None,
    }
    note = ResearchNote.model_validate(payload)
    note_id = derive_finalized_research_note_id(
        note=note,
        report_card_ids=(report_card.report_card_id,),
    )
    return note.model_copy(update={"note_id": note_id})


def _with_review_update(
    note: ResearchNote,
    report_card_id: str,
    **review_updates: object,
) -> ResearchNote:
    payload = note.model_dump(mode="json")
    payload["review"].update(review_updates)
    return _with_identity(ResearchNote.model_validate(payload), report_card_id)


def _with_reference_update(
    note: ResearchNote,
    report_card_id: str,
    **reference_updates: tuple[str, ...],
) -> ResearchNote:
    payload = note.model_dump(mode="json")
    payload["references"].update(reference_updates)
    return _with_identity(ResearchNote.model_validate(payload), report_card_id)


def _with_identity(note: ResearchNote, report_card_id: str) -> ResearchNote:
    return note.model_copy(
        update={
            "note_id": derive_finalized_research_note_id(
                note=note,
                report_card_ids=(report_card_id,),
            )
        }
    )


def _note_count(engine: Engine, note_id: str) -> int:
    with engine.connect() as connection:
        return connection.execute(
            select(func.count())
            .select_from(research_notes)
            .where(research_notes.c.note_id == note_id)
        ).scalar_one()


def _link_count(engine: Engine, note_id: str, report_card_id: str) -> int:
    with engine.connect() as connection:
        return connection.execute(
            select(func.count())
            .select_from(research_note_report_cards)
            .where(
                research_note_report_cards.c.note_id == note_id,
                research_note_report_cards.c.report_card_id == report_card_id,
            )
        ).scalar_one()


def cleanup_interpretations(engine: Engine, *note_ids: str) -> None:
    if not note_ids:
        return
    with engine.begin() as connection:
        connection.execute(
            delete(research_note_report_cards).where(
                research_note_report_cards.c.note_id.in_(note_ids)
            )
        )
        connection.execute(
            delete(research_notes).where(research_notes.c.note_id.in_(note_ids))
        )


def _errors(outcomes: tuple[_WorkflowOutcome, _WorkflowOutcome]) -> list[Exception]:
    return [outcome.error for outcome in outcomes if outcome.error is not None]


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
