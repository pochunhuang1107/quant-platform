"""Repository protocols for experiment ledger persistence boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from research_sdk.contracts import (
    DataSnapshotManifest,
    ExperimentRunRecord,
    ResearchNote,
    ReviewMetadata,
    RunArtifactManifest,
)
from research_sdk.persistence.mappers import ReviewSubjectType


@dataclass(frozen=True)
class PersistedRecordMetadata:
    """Minimal result returned by future repository implementations."""

    table_name: str
    primary_key: Mapping[str, str]
    contract_hash: str | None = None


@runtime_checkable
class ExperimentLedgerRepository(Protocol):
    """Protocol boundary for future experiment ledger write repositories."""

    def record_experiment_run(
        self,
        run: ExperimentRunRecord,
    ) -> PersistedRecordMetadata: ...

    def record_data_snapshot_manifest(
        self,
        snapshot: DataSnapshotManifest,
    ) -> PersistedRecordMetadata: ...

    def record_run_artifact_manifest(
        self,
        *,
        manifest_id: str,
        manifest: RunArtifactManifest,
    ) -> PersistedRecordMetadata: ...

    def record_research_note(
        self,
        note: ResearchNote,
    ) -> PersistedRecordMetadata: ...

    def append_review_event(
        self,
        *,
        review_event_id: str,
        subject_type: ReviewSubjectType | str,
        subject_id: str,
        review: ReviewMetadata,
    ) -> PersistedRecordMetadata: ...


__all__ = [
    "ExperimentLedgerRepository",
    "PersistedRecordMetadata",
]
