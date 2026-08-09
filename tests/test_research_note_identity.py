from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from research_sdk.contracts import ResearchNote
from research_sdk.persistence.hashing import contract_sha256
from research_sdk.research_note_identity import (
    FINALIZED_RESEARCH_NOTE_ID_PREFIX,
    FINALIZED_RESEARCH_NOTE_IDENTITY_POLICY_VERSION,
    ResearchNoteIdentityError,
    derive_finalized_research_note_id,
    verify_finalized_research_note_identity,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "contracts"
REPORT_CARD_ID = "report-card-" + "a" * 64
OTHER_REPORT_CARD_ID = "report-card-" + "b" * 64


@pytest.fixture
def finalized_note() -> ResearchNote:
    payload = _finalized_note_payload()
    note = ResearchNote.model_validate(payload)
    note_id = derive_finalized_research_note_id(
        note=note,
        report_card_ids=(REPORT_CARD_ID,),
    )
    return note.model_copy(update={"note_id": note_id})


def test_finalized_research_note_id_is_deterministic_and_versioned(
    finalized_note: ResearchNote,
) -> None:
    note_id = derive_finalized_research_note_id(
        note=finalized_note,
        report_card_ids=(REPORT_CARD_ID,),
    )

    assert note_id == finalized_note.note_id
    assert note_id.startswith(FINALIZED_RESEARCH_NOTE_ID_PREFIX)
    assert FINALIZED_RESEARCH_NOTE_IDENTITY_POLICY_VERSION == (
        "finalized-research-note-v1"
    )
    assert len(note_id.removeprefix(FINALIZED_RESEARCH_NOTE_ID_PREFIX)) == 64
    assert note_id == derive_finalized_research_note_id(
        note=finalized_note,
        report_card_ids=(REPORT_CARD_ID,),
    )
    verify_finalized_research_note_identity(
        note=finalized_note,
        report_card_ids=(REPORT_CARD_ID,),
    )


@pytest.mark.parametrize(
    ("field_path", "value"),
    [
        (("created_by",), "human-owner-b"),
        (("interpretation",), "Changed interpretation."),
        (("decision", "outcome"), "reject_result"),
        (("limitations",), ("Changed limitation.",)),
        (("failure_modes",), ("Changed failure mode.",)),
        (("parent_note_id",), "parent-note-001"),
        (("supersedes_note_id",), "superseded-note-001"),
    ],
)
def test_included_identity_fields_change_finalized_id(
    finalized_note: ResearchNote,
    field_path: tuple[str, ...],
    value: Any,
) -> None:
    changed = _note_with_nested_update(finalized_note, field_path, value)

    assert (
        derive_finalized_research_note_id(
            note=changed,
            report_card_ids=(REPORT_CARD_ID,),
        )
        != finalized_note.note_id
    )


def test_changed_report_card_id_changes_finalized_id(
    finalized_note: ResearchNote,
) -> None:
    assert (
        derive_finalized_research_note_id(
            note=finalized_note,
            report_card_ids=(OTHER_REPORT_CARD_ID,),
        )
        != finalized_note.note_id
    )


@pytest.mark.parametrize(
    "status",
    [
        "draft",
        "ready_for_review",
        "under_review",
        "superseded",
        "archived",
    ],
)
def test_derive_rejects_non_finalized_statuses(
    finalized_note: ResearchNote,
    status: str,
) -> None:
    note = _note_with_nested_update(finalized_note, ("status",), status)

    with pytest.raises(ResearchNoteIdentityError, match="finalized"):
        derive_finalized_research_note_id(
            note=note,
            report_card_ids=(REPORT_CARD_ID,),
        )


@pytest.mark.parametrize(
    "status",
    [
        "draft",
        "ready_for_review",
        "under_review",
        "superseded",
        "archived",
    ],
)
def test_verify_rejects_finalized_v1_prefix_for_non_finalized_statuses(
    finalized_note: ResearchNote,
    status: str,
) -> None:
    note = _note_with_nested_update(finalized_note, ("status",), status)

    with pytest.raises(ResearchNoteIdentityError, match="finalized"):
        verify_finalized_research_note_identity(
            note=note,
            report_card_ids=(REPORT_CARD_ID,),
        )


@pytest.mark.parametrize(
    "note_type",
    ["hypothesis", "failure_analysis", "review_note", "other"],
)
def test_derive_rejects_non_experiment_result_note_types(
    finalized_note: ResearchNote,
    note_type: str,
) -> None:
    note = _note_with_nested_update(finalized_note, ("note_type",), note_type)

    with pytest.raises(ResearchNoteIdentityError, match="experiment_result"):
        derive_finalized_research_note_id(
            note=note,
            report_card_ids=(REPORT_CARD_ID,),
        )


@pytest.mark.parametrize(
    "note_type",
    ["hypothesis", "failure_analysis", "review_note", "other"],
)
def test_verify_rejects_finalized_v1_prefix_for_non_experiment_result_note_types(
    finalized_note: ResearchNote,
    note_type: str,
) -> None:
    note = _note_with_nested_update(finalized_note, ("note_type",), note_type)

    with pytest.raises(ResearchNoteIdentityError, match="experiment_result"):
        verify_finalized_research_note_identity(
            note=note,
            report_card_ids=(REPORT_CARD_ID,),
        )


@pytest.mark.parametrize(
    ("field_path", "value"),
    [
        (("review", "reviewer_id"), "other-human-owner"),
        (("review", "reviewed_at"), "2026-07-10T10:00:00Z"),
        (("review", "review_status"), "changes_requested"),
        (("updated_at",), "2026-07-10T10:00:00Z"),
        (("updated_by",), "human-owner-b"),
        (("body_markdown",), "# Changed body\n\nExcluded from natural identity."),
        (("tags",), ("changed", "tags")),
    ],
)
def test_excluded_identity_fields_do_not_change_finalized_id_but_change_contract_hash(
    finalized_note: ResearchNote,
    field_path: tuple[str, ...],
    value: Any,
) -> None:
    changed = _note_with_nested_update(finalized_note, field_path, value)

    assert (
        derive_finalized_research_note_id(
            note=changed,
            report_card_ids=(REPORT_CARD_ID,),
        )
        == finalized_note.note_id
    )
    assert contract_sha256(changed) != contract_sha256(finalized_note)


def test_malformed_prefix_is_rejected(finalized_note: ResearchNote) -> None:
    malformed = finalized_note.model_copy(update={"note_id": "note-" + "0" * 64})

    with pytest.raises(ResearchNoteIdentityError, match="prefix"):
        verify_finalized_research_note_identity(
            note=malformed,
            report_card_ids=(REPORT_CARD_ID,),
        )


def test_stale_digest_is_rejected(finalized_note: ResearchNote) -> None:
    stale = finalized_note.model_copy(
        update={"note_id": FINALIZED_RESEARCH_NOTE_ID_PREFIX + "0" * 64}
    )

    with pytest.raises(ResearchNoteIdentityError, match="stale"):
        verify_finalized_research_note_identity(
            note=stale,
            report_card_ids=(REPORT_CARD_ID,),
        )


def test_identity_helper_import_has_no_persistence_or_engine_side_effects() -> None:
    code = """
import sys
import research_sdk.research_note_identity
for module_name in (
    "sqlalchemy",
    "psycopg",
    "research_sdk.persistence",
    "research_sdk.experiment_recording",
    "backtest_engine",
):
    assert module_name not in sys.modules, module_name
"""

    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def _finalized_note_payload() -> dict[str, Any]:
    payload = json.loads(
        (FIXTURE_DIR / "research_note.json").read_text(encoding="utf-8")
    )
    payload.update(
        {
            "note_id": "temporary-note-id",
            "status": "finalized",
            "created_by": "human-owner-a",
            "updated_by": "human-owner-a",
            "limitations": [
                "Generated synthetic data only.",
                "Infrastructure validation only.",
                "No investment-performance claim.",
                "Not production-data strategy research.",
                "Not paper-trading evidence.",
                "Not live-trading evidence.",
            ],
            "review": {
                "review_status": "approved",
                "reviewer_id": "human-owner-a",
                "review_role": "human_owner",
                "reviewed_at": "2026-07-09T10:00:00Z",
                "risk_approval_required": True,
            },
        }
    )
    return payload


def _note_with_nested_update(
    note: ResearchNote,
    field_path: tuple[str, ...],
    value: Any,
) -> ResearchNote:
    payload = note.model_dump(mode="json")
    current = payload
    for field_name in field_path[:-1]:
        current = current[field_name]
    current[field_path[-1]] = value
    return ResearchNote.model_validate(payload)
