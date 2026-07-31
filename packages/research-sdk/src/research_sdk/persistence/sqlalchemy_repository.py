"""Abstract SQLAlchemy repository skeleton for experiment ledger persistence."""

from __future__ import annotations

from abc import ABC, abstractmethod

from sqlalchemy.engine import Connection

from research_sdk.contracts import (
    DataSnapshotManifest,
    ExperimentRunRecord,
    ResearchNote,
    ReviewMetadata,
    RunArtifactManifest,
)
from research_sdk.persistence.mappers import ReviewSubjectType
from research_sdk.persistence.results import PersistenceWriteResult


class SqlAlchemyExperimentLedgerRepository(ABC):
    """Non-executing SQLAlchemy repository boundary for experiment ledger writes."""

    __slots__ = ("_connection",)

    _connection: Connection

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    @abstractmethod
    def record_experiment_run(
        self,
        run: ExperimentRunRecord,
    ) -> PersistenceWriteResult:
        raise NotImplementedError

    @abstractmethod
    def record_data_snapshot_manifest(
        self,
        snapshot: DataSnapshotManifest,
    ) -> PersistenceWriteResult:
        raise NotImplementedError

    @abstractmethod
    def record_run_artifact_manifest(
        self,
        *,
        manifest_id: str,
        manifest: RunArtifactManifest,
    ) -> PersistenceWriteResult:
        raise NotImplementedError

    @abstractmethod
    def record_research_note(
        self,
        note: ResearchNote,
    ) -> PersistenceWriteResult:
        raise NotImplementedError

    @abstractmethod
    def append_review_event(
        self,
        *,
        review_event_id: str,
        subject_type: ReviewSubjectType | str,
        subject_id: str,
        review: ReviewMetadata,
    ) -> PersistenceWriteResult:
        raise NotImplementedError


__all__ = ["SqlAlchemyExperimentLedgerRepository"]
