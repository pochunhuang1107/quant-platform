"""Pure deterministic identity helpers for finalized research notes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from research_sdk.contracts import ResearchNote, ResearchNoteStatus, ResearchNoteType

FINALIZED_RESEARCH_NOTE_IDENTITY_POLICY_VERSION = "finalized-research-note-v1"
FINALIZED_RESEARCH_NOTE_ID_PREFIX = "research-note-finalized-v1-"
FINALIZED_RESEARCH_NOTE_DIGEST_LENGTH = 64

_LOWER_HEX_DIGITS = frozenset("0123456789abcdef")


class ResearchNoteIdentityError(ValueError):
    """Raised when a finalized research-note identity is malformed or stale."""


def derive_finalized_research_note_id(
    *,
    note: ResearchNote,
    report_card_ids: tuple[str, ...],
) -> str:
    """Derive the finalized-v1 natural identity for a human-reviewed note."""

    _validate_finalized_research_note_eligibility(note)
    payload = _finalized_research_note_identity_payload(
        note=note,
        report_card_ids=report_card_ids,
    )
    return f"{FINALIZED_RESEARCH_NOTE_ID_PREFIX}{_canonical_json_sha256(payload)}"


def verify_finalized_research_note_identity(
    *,
    note: ResearchNote,
    report_card_ids: tuple[str, ...],
) -> None:
    """Verify a finalized-v1 note ID by recomputing its natural identity."""

    _validate_finalized_research_note_eligibility(note)
    _validate_finalized_research_note_id(note.note_id)
    expected = derive_finalized_research_note_id(
        note=note,
        report_card_ids=report_card_ids,
    )
    if note.note_id != expected:
        raise ResearchNoteIdentityError(
            "finalized research-note identity is stale or inconsistent"
        )


def _validate_finalized_research_note_eligibility(note: ResearchNote) -> None:
    if note.note_type is not ResearchNoteType.EXPERIMENT_RESULT:
        raise ResearchNoteIdentityError(
            "finalized-v1 identity is reserved for experiment_result notes"
        )
    if note.status is not ResearchNoteStatus.FINALIZED:
        raise ResearchNoteIdentityError(
            "finalized-v1 identity is reserved for finalized notes"
        )


def _finalized_research_note_identity_payload(
    *,
    note: ResearchNote,
    report_card_ids: tuple[str, ...],
) -> dict[str, Any]:
    raw_note = note.model_dump(mode="json")
    normalized_report_card_ids = tuple(sorted(set(report_card_ids)))

    return {
        "identity_policy_version": FINALIZED_RESEARCH_NOTE_IDENTITY_POLICY_VERSION,
        "schema_version": raw_note["schema_version"],
        "note_type": raw_note["note_type"],
        "linked_report_card_ids": normalized_report_card_ids,
        "created_by": raw_note["created_by"],
        "title": raw_note["title"],
        "hypothesis": raw_note["hypothesis"],
        "motivation": raw_note["motivation"],
        "methodology": raw_note["methodology"],
        "benchmark_summary": raw_note["benchmark_summary"],
        "cost_assumptions": raw_note["cost_assumptions"],
        "slippage_assumptions": raw_note["slippage_assumptions"],
        "lookback": raw_note["lookback"],
        "lag_assumptions": raw_note["lag_assumptions"],
        "leakage_review": raw_note["leakage_review"],
        "results_summary": raw_note["results_summary"],
        "interpretation": raw_note["interpretation"],
        "risks": raw_note["risks"],
        "failure_modes": raw_note["failure_modes"],
        "validation_plan": raw_note["validation_plan"],
        "limitations": raw_note["limitations"],
        "next_steps": raw_note["next_steps"],
        "evidence_strength": raw_note["evidence_strength"],
        "decision": raw_note["decision"],
        "references": raw_note["references"],
        "parent_note_id": raw_note["parent_note_id"],
        "supersedes_note_id": raw_note["supersedes_note_id"],
    }


def _validate_finalized_research_note_id(note_id: str) -> None:
    if not note_id.startswith(FINALIZED_RESEARCH_NOTE_ID_PREFIX):
        raise ResearchNoteIdentityError(
            "note_id must use the research-note-finalized-v1- prefix"
        )
    digest = note_id.removeprefix(FINALIZED_RESEARCH_NOTE_ID_PREFIX)
    if len(digest) != FINALIZED_RESEARCH_NOTE_DIGEST_LENGTH:
        raise ResearchNoteIdentityError("note_id must contain a full SHA-256 digest")
    if digest.lower() != digest or any(
        character not in _LOWER_HEX_DIGITS for character in digest
    ):
        raise ResearchNoteIdentityError("note_id digest must be lowercase hexadecimal")


def _canonical_json_sha256(payload: Mapping[str, Any]) -> str:
    canonical_json = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(f"{canonical_json}\n".encode()).hexdigest()


__all__ = [
    "FINALIZED_RESEARCH_NOTE_IDENTITY_POLICY_VERSION",
    "FINALIZED_RESEARCH_NOTE_ID_PREFIX",
    "ResearchNoteIdentityError",
    "derive_finalized_research_note_id",
    "verify_finalized_research_note_identity",
]
