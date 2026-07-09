"""Structured research note contracts for reproducible research review."""

from typing import Self

from pydantic import Field, model_validator

from research_sdk.contracts.base import BaseContractModel
from research_sdk.contracts.enums import (
    DecisionOutcome,
    EvidenceStrength,
    HypothesisStatus,
    ResearchNoteStatus,
    ResearchNoteType,
)
from research_sdk.contracts.review import ReviewMetadata
from research_sdk.contracts.schema import VersionedContract
from research_sdk.contracts.time import UtcDatetime
from research_sdk.contracts.types import NonEmptyString


class ResearchHypothesis(BaseContractModel):
    """Structured hypothesis statement and validation status."""

    statement: NonEmptyString
    status: HypothesisStatus


class ResearchNoteReferences(BaseContractModel):
    """Declarative references linked from a research note."""

    experiment_ids: tuple[NonEmptyString, ...] = ()
    run_ids: tuple[NonEmptyString, ...] = ()
    artifact_uris: tuple[NonEmptyString, ...] = ()
    artifact_manifest_uris: tuple[NonEmptyString, ...] = ()
    data_snapshot_ids: tuple[NonEmptyString, ...] = ()
    feature_snapshot_ids: tuple[NonEmptyString, ...] = ()
    benchmark_snapshot_ids: tuple[NonEmptyString, ...] = ()
    strategy_ids: tuple[NonEmptyString, ...] = ()


class ResearchDecision(BaseContractModel):
    """Structured decision recorded by a research note."""

    outcome: DecisionOutcome
    rationale: NonEmptyString


class ResearchNote(VersionedContract):
    """Structured research note contract for reproducible research review."""

    note_id: NonEmptyString
    note_type: ResearchNoteType
    status: ResearchNoteStatus
    created_at: UtcDatetime
    created_by: NonEmptyString
    updated_at: UtcDatetime
    updated_by: NonEmptyString
    title: NonEmptyString
    hypothesis: ResearchHypothesis
    motivation: NonEmptyString
    methodology: NonEmptyString
    benchmark_summary: NonEmptyString
    cost_assumptions: NonEmptyString
    slippage_assumptions: NonEmptyString
    lookback: NonEmptyString
    lag_assumptions: NonEmptyString
    leakage_review: NonEmptyString
    results_summary: NonEmptyString
    interpretation: NonEmptyString
    risks: tuple[NonEmptyString, ...] = Field(min_length=1)
    failure_modes: tuple[NonEmptyString, ...] = Field(min_length=1)
    validation_plan: NonEmptyString
    limitations: tuple[NonEmptyString, ...] = Field(min_length=1)
    next_steps: tuple[NonEmptyString, ...] = Field(min_length=1)
    evidence_strength: EvidenceStrength
    decision: ResearchDecision
    review: ReviewMetadata
    references: ResearchNoteReferences = Field(default_factory=ResearchNoteReferences)
    tags: tuple[NonEmptyString, ...] = ()
    body_markdown: NonEmptyString | None = None
    parent_note_id: NonEmptyString | None = None
    supersedes_note_id: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_research_note_consistency(self) -> Self:
        """Validate internal note consistency without touching external systems."""

        if self.updated_at < self.created_at:
            raise ValueError("updated_at must be greater than or equal to created_at")
        if self.note_type is ResearchNoteType.EXPERIMENT_RESULT and not (
            self.references.run_ids
        ):
            raise ValueError("experiment_result notes require at least one run_id")
        if self.parent_note_id == self.note_id:
            raise ValueError("parent_note_id cannot equal note_id")
        if self.supersedes_note_id == self.note_id:
            raise ValueError("supersedes_note_id cannot equal note_id")
        return self
