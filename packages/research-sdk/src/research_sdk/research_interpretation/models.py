"""Application models for finalized research interpretation recording."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ConfigDict

from research_sdk.contracts import ResearchNote
from research_sdk.contracts.base import BaseContractModel
from research_sdk.contracts.types import NonEmptyString
from research_sdk.persistence.results import PersistenceWriteResult


class FinalizedResearchInterpretationBundle(BaseContractModel):
    """Validated payload for one finalized note interpreting one report card."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    note: ResearchNote
    report_card_id: NonEmptyString


@dataclass(frozen=True)
class FinalizedResearchInterpretationRecordingResult:
    """Successful persistence outcomes for finalized research interpretation."""

    research_note_result: PersistenceWriteResult
    report_card_link_result: PersistenceWriteResult
    report_card_id: str


__all__ = [
    "FinalizedResearchInterpretationBundle",
    "FinalizedResearchInterpretationRecordingResult",
]
