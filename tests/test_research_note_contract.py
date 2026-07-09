from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from research_sdk.contracts import (
    DecisionOutcome,
    EvidenceStrength,
    HypothesisStatus,
    ResearchNote,
    ResearchNoteStatus,
    ResearchNoteType,
)


def valid_note_data() -> dict[str, Any]:
    return {
        "note_id": "note-20260709-001",
        "schema_version": "1.0.0",
        "note_type": "hypothesis",
        "status": "draft",
        "created_at": datetime(2026, 7, 9, 9, 0, 0, tzinfo=UTC),
        "created_by": "agent-codex",
        "updated_at": datetime(2026, 7, 9, 9, 30, 0, tzinfo=UTC),
        "updated_by": "agent-codex",
        "title": "Momentum baseline research note",
        "hypothesis": {
            "statement": "A simple momentum baseline can outperform the benchmark.",
            "status": "proposed",
        },
        "motivation": "Establish a simple, testable baseline before complex models.",
        "methodology": (
            "Compare a deterministic momentum signal against benchmark returns."
        ),
        "benchmark_summary": "SPY benchmark snapshot referenced when applicable.",
        "cost_assumptions": "Fixed 1bp transaction cost assumption.",
        "slippage_assumptions": "Fixed 2bp slippage assumption.",
        "lookback": "252 trading days.",
        "lag_assumptions": "Signals use data available at prior close.",
        "leakage_review": "Point-in-time data and universe controls are required.",
        "results_summary": "No results yet; hypothesis note only.",
        "interpretation": "Initial hypothesis requires reproducible validation.",
        "risks": ("overfitting",),
        "failure_modes": ("momentum reverses in volatile regimes",),
        "validation_plan": (
            "Run against a deterministic baseline with sensitivity checks."
        ),
        "limitations": ("No backtest attached yet.",),
        "next_steps": ("Implement minimal baseline run.",),
        "evidence_strength": "none",
        "decision": {
            "outcome": "continue_research",
            "rationale": "Hypothesis is ready for structured testing.",
        },
        "review": {
            "review_status": "pending",
            "risk_approval_required": True,
        },
    }


def test_research_note_accepts_complete_valid_note() -> None:
    note = ResearchNote(**valid_note_data())

    assert note.note_id == "note-20260709-001"
    assert note.note_type is ResearchNoteType.HYPOTHESIS
    assert note.status is ResearchNoteStatus.DRAFT
    assert note.hypothesis.status is HypothesisStatus.PROPOSED
    assert note.evidence_strength is EvidenceStrength.NONE
    assert note.decision.outcome is DecisionOutcome.CONTINUE_RESEARCH
    assert note.references.run_ids == ()
    assert note.tags == ()


def test_research_note_type_contains_documented_values() -> None:
    assert {note_type.value for note_type in ResearchNoteType} == {
        "hypothesis",
        "experiment_result",
        "failure_analysis",
        "review_note",
        "other",
    }


def test_research_note_status_contains_documented_values() -> None:
    assert {status.value for status in ResearchNoteStatus} == {
        "draft",
        "ready_for_review",
        "under_review",
        "finalized",
        "superseded",
        "archived",
    }


def test_hypothesis_status_contains_documented_values() -> None:
    assert {status.value for status in HypothesisStatus} == {
        "proposed",
        "testing",
        "supported",
        "partially_supported",
        "not_supported",
        "inconclusive",
        "superseded",
    }


def test_evidence_strength_contains_documented_values() -> None:
    assert {strength.value for strength in EvidenceStrength} == {
        "none",
        "weak",
        "moderate",
        "strong",
    }


def test_decision_outcome_contains_documented_values() -> None:
    assert {outcome.value for outcome in DecisionOutcome} == {
        "no_decision",
        "continue_research",
        "accept_result",
        "reject_result",
        "mark_invalid",
        "supersede_prior",
        "needs_changes",
    }


def test_research_note_normalizes_utc_datetimes() -> None:
    data = valid_note_data()
    pacific = timezone(timedelta(hours=-7))
    data["created_at"] = datetime(2026, 7, 9, 2, 0, 0, tzinfo=pacific)
    data["updated_at"] = datetime(2026, 7, 9, 2, 30, 0, tzinfo=pacific)

    note = ResearchNote(**data)

    assert note.created_at == datetime(2026, 7, 9, 9, 0, 0, tzinfo=UTC)
    assert note.updated_at == datetime(2026, 7, 9, 9, 30, 0, tzinfo=UTC)


@pytest.mark.parametrize("field_name", ["created_at", "updated_at"])
def test_research_note_rejects_naive_datetimes(field_name: str) -> None:
    data = valid_note_data()
    data[field_name] = datetime(2026, 7, 9, 9, 0, 0)

    with pytest.raises(ValidationError):
        ResearchNote(**data)


def test_research_note_rejects_update_before_creation() -> None:
    data = valid_note_data()
    data["updated_at"] = datetime(2026, 7, 9, 8, 59, 59, tzinfo=UTC)

    with pytest.raises(ValidationError, match="updated_at"):
        ResearchNote(**data)


@pytest.mark.parametrize(
    ("field_path", "value"),
    [
        (("note_type",), "trade_signal"),
        (("status",), "approved"),
        (("hypothesis", "status"), "proven"),
        (("evidence_strength",), "certain"),
        (("decision", "outcome"), "paper_trade"),
    ],
)
def test_research_note_rejects_invalid_enum_values(
    field_path: tuple[str, ...],
    value: str,
) -> None:
    data = valid_note_data()
    target = data
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = value

    with pytest.raises(ValidationError):
        ResearchNote(**data)


def test_research_note_rejects_unknown_extra_fields() -> None:
    data = valid_note_data()
    data["broker_account"] = "not-allowed"

    with pytest.raises(ValidationError):
        ResearchNote(**data)


@pytest.mark.parametrize(
    "field_name",
    [
        "note_id",
        "title",
        "hypothesis",
        "benchmark_summary",
        "cost_assumptions",
        "slippage_assumptions",
        "leakage_review",
        "decision",
        "review",
    ],
)
def test_research_note_rejects_missing_required_fields(field_name: str) -> None:
    data = valid_note_data()
    del data[field_name]

    with pytest.raises(ValidationError):
        ResearchNote(**data)


@pytest.mark.parametrize(
    "field_name",
    [
        "risks",
        "failure_modes",
        "limitations",
        "next_steps",
    ],
)
def test_research_note_rejects_empty_required_tuples(field_name: str) -> None:
    data = valid_note_data()
    data[field_name] = ()

    with pytest.raises(ValidationError):
        ResearchNote(**data)


def test_research_note_accepts_standalone_hypothesis_without_run_ids() -> None:
    note = ResearchNote(**valid_note_data())

    assert note.note_type is ResearchNoteType.HYPOTHESIS
    assert note.references.run_ids == ()


def test_experiment_result_note_rejects_missing_run_ids() -> None:
    data = valid_note_data()
    data["note_type"] = "experiment_result"

    with pytest.raises(ValidationError, match="run_id"):
        ResearchNote(**data)


def test_experiment_result_note_accepts_linked_run_id() -> None:
    data = valid_note_data()
    data["note_type"] = "experiment_result"
    data["references"] = {"run_ids": ("run-20260709-001",)}

    note = ResearchNote(**data)

    assert note.note_type is ResearchNoteType.EXPERIMENT_RESULT
    assert note.references.run_ids == ("run-20260709-001",)


def test_research_note_rejects_parent_note_id_matching_note_id() -> None:
    data = valid_note_data()
    data["parent_note_id"] = data["note_id"]

    with pytest.raises(ValidationError, match="parent_note_id"):
        ResearchNote(**data)


def test_research_note_rejects_supersedes_note_id_matching_note_id() -> None:
    data = valid_note_data()
    data["supersedes_note_id"] = data["note_id"]

    with pytest.raises(ValidationError, match="supersedes_note_id"):
        ResearchNote(**data)


def test_research_note_preserves_references_as_declarative_strings() -> None:
    data = deepcopy(valid_note_data())
    data["references"] = {
        "experiment_ids": ("exp-momentum-baseline",),
        "run_ids": ("run-that-does-not-need-to-exist",),
        "artifact_uris": ("artifacts/run-001/research_note.md",),
        "artifact_manifest_uris": ("artifacts/run-001/artifact_manifest.json",),
        "data_snapshot_ids": ("market-snapshot-20260709",),
        "feature_snapshot_ids": ("feature-snapshot-20260709",),
        "benchmark_snapshot_ids": ("benchmark-snapshot-20260709",),
        "strategy_ids": ("strategies/equities/momentum_baseline",),
    }

    note = ResearchNote(**data)

    assert note.references.run_ids == ("run-that-does-not-need-to-exist",)
    assert note.references.artifact_uris == ("artifacts/run-001/research_note.md",)


def test_research_note_preserves_optional_body_markdown_exactly() -> None:
    data = valid_note_data()
    markdown = "# Note\n\n- Preserve this text exactly."
    data["body_markdown"] = markdown

    note = ResearchNote(**data)

    assert note.body_markdown == markdown


def test_research_note_accepts_tags_as_tuple_values() -> None:
    data = valid_note_data()
    data["tags"] = ("momentum", "baseline")

    note = ResearchNote(**data)

    assert note.tags == ("momentum", "baseline")


def test_research_note_has_no_workflow_or_rendering_behavior() -> None:
    note = ResearchNote(**valid_note_data())

    for method_name in (
        "render_markdown",
        "generate_summary",
        "embed",
        "index",
        "search",
        "link_graph",
        "execute_workflow",
        "approve",
        "write_note",
    ):
        assert not hasattr(note, method_name)
