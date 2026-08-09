"""Repository protocols for experiment ledger persistence boundaries."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from research_sdk.contracts import (
    DataSnapshotManifest,
    ExperimentRunRecord,
    ResearchNote,
    ResearchReportCard,
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

    def get_research_note(
        self,
        note_id: str,
    ) -> ResearchNote | None: ...

    def record_research_note_report_card_link(
        self,
        *,
        note_id: str,
        report_card_id: str,
    ) -> PersistenceWriteResult: ...

    def get_report_card_ids_for_note(
        self,
        note_id: str,
    ) -> tuple[str, ...]: ...

    def record_research_report_card(
        self,
        report_card: ResearchReportCard,
    ) -> PersistenceWriteResult: ...

    def get_research_report_card(
        self,
        report_card_id: str,
    ) -> ResearchReportCard | None: ...

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
