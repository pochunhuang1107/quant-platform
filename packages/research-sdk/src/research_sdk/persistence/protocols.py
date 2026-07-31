"""Repository protocols for experiment ledger persistence boundaries."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from research_sdk.contracts import (
    DataSnapshotManifest,
    ExperimentRunRecord,
    ResearchNote,
    ReviewMetadata,
    RunArtifactManifest,
)
from research_sdk.persistence.mappers import ReviewSubjectType
from research_sdk.persistence.results import (
    PersistedRecordMetadata,
    PersistenceWriteResult,
)


@runtime_checkable
class ExperimentLedgerRepository(Protocol):
    """Protocol boundary for future experiment ledger write repositories."""

    def record_experiment_run(
        self,
        run: ExperimentRunRecord,
    ) -> PersistenceWriteResult: ...

    def record_data_snapshot_manifest(
        self,
        snapshot: DataSnapshotManifest,
    ) -> PersistenceWriteResult: ...

    def record_run_artifact_manifest(
        self,
        *,
        manifest_id: str,
        manifest: RunArtifactManifest,
    ) -> PersistenceWriteResult: ...

    def record_research_note(
        self,
        note: ResearchNote,
    ) -> PersistenceWriteResult: ...

    def append_review_event(
        self,
        *,
        review_event_id: str,
        subject_type: ReviewSubjectType | str,
        subject_id: str,
        review: ReviewMetadata,
    ) -> PersistenceWriteResult: ...


__all__ = [
    "ExperimentLedgerRepository",
    "PersistedRecordMetadata",
    "PersistenceWriteResult",
]
