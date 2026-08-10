from __future__ import annotations

from pathlib import Path
from typing import Never

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from live_postgres_safety import (
    QUANT_RUN_LIVE_DB_TESTS_ENV_VAR,
    QUANT_TEST_DATABASE_URL_ENV_VAR,
    UnsafePostgresTestUrl,
    get_quant_test_database_url,
    should_run_live_db_tests,
    validate_safe_postgres_test_url,
)
from research_sdk.contracts import ResearchNote
from research_sdk.persistence.sqlalchemy_repository import (
    SqlAlchemyExperimentLedgerRepository,
)
from research_sdk.persistence.tables import (
    data_snapshot_manifests,
    experiment_runs,
    research_note_report_cards,
    research_notes,
    research_report_cards,
    run_artifact_entries,
    run_artifact_manifests,
)
from research_sdk.report_card_comparison import ComparisonCompatibilityStatus
from research_sdk.report_card_comparison_query import (
    query_research_report_card_comparison,
)
from test_live_postgres_backtest_engine_recording import (
    build_bundle,
    execution_metadata,
)
from test_live_postgres_research_interpretation_workflow import (
    _persist_completed_experiment_and_report_card,
    cleanup_interpretations,
)
from test_live_postgres_research_report_card_repository import (
    _report_card_from_bundle,
    cleanup_bundles,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


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
def test_persisted_report_card_comparison_query_exposes_review_state_read_only(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    baseline_bundle = build_bundle(tmp_path, artifact_label="c2b-query-baseline")
    candidate_bundle = build_bundle(
        tmp_path,
        artifact_label="c2b-query-candidate",
        metadata=execution_metadata(dependency_lock_hash="sha256:c2b-query-lock"),
    )
    baseline = _report_card_from_bundle(baseline_bundle)
    candidate = _report_card_from_bundle(candidate_bundle)
    baseline_note = _generic_note(
        note_id="note-c2b-query-baseline",
        status="draft",
        review_status="pending",
        review_decision="draft visibility only",
    )
    candidate_note_a = _generic_note(
        note_id="note-c2b-query-candidate-a",
        status="under_review",
        review_status="changes_requested",
        review_decision="candidate needs changes",
    )
    candidate_note_b = _generic_note(
        note_id="note-c2b-query-candidate-b",
        status="finalized",
        review_status="approved",
        review_decision="candidate review metadata visible",
    )
    note_ids = (
        baseline_note.note_id,
        candidate_note_a.note_id,
        candidate_note_b.note_id,
    )
    cleanup_interpretations(migrated_engine, *note_ids)
    cleanup_bundles(migrated_engine, baseline_bundle, candidate_bundle)
    try:
        _persist_completed_experiment_and_report_card(
            migrated_engine,
            baseline_bundle,
            baseline,
        )
        _persist_completed_experiment_and_report_card(
            migrated_engine,
            candidate_bundle,
            candidate,
        )
        with migrated_engine.begin() as connection:
            repository = SqlAlchemyExperimentLedgerRepository(connection)
            for note in (baseline_note, candidate_note_a, candidate_note_b):
                repository.record_research_note(note)
            repository.record_research_note_report_card_link(
                note_id=baseline_note.note_id,
                report_card_id=baseline.report_card_id,
            )
            repository.record_research_note_report_card_link(
                note_id=candidate_note_b.note_id,
                report_card_id=candidate.report_card_id,
            )
            repository.record_research_note_report_card_link(
                note_id=candidate_note_a.note_id,
                report_card_id=candidate.report_card_id,
            )

        before_counts = _row_counts(migrated_engine)
        with migrated_engine.connect() as connection:
            repository = SqlAlchemyExperimentLedgerRepository(connection)
            result = query_research_report_card_comparison(
                baseline_report_card_id=baseline.report_card_id,
                candidate_report_card_id=candidate.report_card_id,
                repository=repository,
            )
            same_card = query_research_report_card_comparison(
                baseline_report_card_id=baseline.report_card_id,
                candidate_report_card_id=baseline.report_card_id,
                repository=repository,
            )
        after_counts = _row_counts(migrated_engine)

        assert result.baseline_report_card_id == baseline.report_card_id
        assert result.candidate_report_card_id == candidate.report_card_id
        assert result.comparison is not None
        assert result.comparison.baseline_report_card_id == baseline.report_card_id
        assert result.comparison.candidate_report_card_id == candidate.report_card_id
        assert result.compatibility.status in {
            ComparisonCompatibilityStatus.STRICT_COMPATIBLE,
            ComparisonCompatibilityStatus.CONTEXT_COMPATIBLE,
        }
        assert [state.note_id for state in result.baseline_review_states] == [
            baseline_note.note_id
        ]
        assert [state.note_id for state in result.candidate_review_states] == [
            candidate_note_a.note_id,
            candidate_note_b.note_id,
        ]
        assert result.baseline_review_states[0].note_status.value == "draft"
        assert result.baseline_review_states[0].review_status.value == "pending"
        assert (
            result.candidate_review_states[0].review_decision
            == "candidate needs changes"
        )
        assert result.candidate_review_states[1].review_status.value == "approved"
        assert same_card.compatibility.status is (
            ComparisonCompatibilityStatus.STRICT_COMPATIBLE
        )
        assert same_card.comparison is not None
        assert same_card.baseline_review_states == same_card.candidate_review_states
        assert before_counts == after_counts
    finally:
        cleanup_interpretations(migrated_engine, *note_ids)
        cleanup_bundles(migrated_engine, baseline_bundle, candidate_bundle)


def _generic_note(
    *,
    note_id: str,
    status: str,
    review_status: str,
    review_decision: str,
) -> ResearchNote:
    return ResearchNote.model_validate(
        {
            "note_id": note_id,
            "schema_version": "1.0.0",
            "note_type": "review_note",
            "status": status,
            "created_at": "2026-07-09T10:00:00Z",
            "created_by": "agent-a",
            "updated_at": "2026-07-09T11:00:00Z",
            "updated_by": "agent-a",
            "title": f"C2b review visibility {note_id}",
            "hypothesis": {
                "statement": "C2b exposes persisted review facts.",
                "status": "inconclusive",
            },
            "motivation": "Exercise generic ResearchNote visibility.",
            "methodology": "Read linked notes after durable report-card readback.",
            "benchmark_summary": "Benchmark authority remains in report cards.",
            "cost_assumptions": "Cost authority remains in report cards.",
            "slippage_assumptions": "Slippage authority remains in report cards.",
            "lookback": "Lookback authority remains in report cards.",
            "lag_assumptions": "Lag authority remains in report cards.",
            "leakage_review": "Leakage authority remains in report cards.",
            "results_summary": "Free-form result prose is not projected by C2b.",
            "interpretation": "Free-form interpretation is not projected by C2b.",
            "risks": ["Metadata is not approval authority."],
            "failure_modes": ["Missing linked note should fail the query."],
            "validation_plan": "Verify read-only row counts.",
            "limitations": ["Read-time review-state projection only."],
            "next_steps": ["Human review remains external to C2b."],
            "evidence_strength": "weak",
            "decision": {
                "outcome": "continue_research",
                "rationale": "Projection is factual visibility, not authority.",
            },
            "review": {
                "review_status": review_status,
                "reviewer_id": "agent-reviewer-a",
                "review_role": "agent_reviewer",
                "reviewed_at": "2026-07-09T11:30:00Z",
                "decision": review_decision,
                "approval_scope": "metadata visibility only",
                "approval_expires_at": "2026-08-09T11:30:00Z",
                "linked_pr": "PR-c2b-query",
                "review_notes_uri": "notes://c2b-query",
                "risk_approval_required": True,
            },
            "references": {},
            "tags": ["c2b"],
            "body_markdown": "# Not part of C2b projection\n",
            "parent_note_id": None,
            "supersedes_note_id": None,
        }
    )


def _row_counts(engine: Engine) -> dict[str, int]:
    tables = (
        experiment_runs,
        data_snapshot_manifests,
        run_artifact_manifests,
        run_artifact_entries,
        research_report_cards,
        research_notes,
        research_note_report_cards,
    )
    with engine.connect() as connection:
        return {
            table.name: connection.execute(
                select(func.count()).select_from(table)
            ).scalar_one()
            for table in tables
        }


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
