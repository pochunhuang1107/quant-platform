"""Abstract SQLAlchemy repository for experiment ledger persistence."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from datetime import datetime

from sqlalchemy.engine import Connection

from research_sdk.contracts import (
    DataSnapshotManifest,
    ExperimentRunRecord,
    ResearchNote,
    ReviewMetadata,
    RunArtifactManifest,
)
from research_sdk.persistence.errors import (
    ContractHashConflictError,
    PersistenceErrorContext,
    ReplayLookupError,
)
from research_sdk.persistence.hashing import contract_sha256
from research_sdk.persistence.mappers import ReviewSubjectType
from research_sdk.persistence.results import (
    PersistedRecordMetadata,
    PersistenceDisposition,
    PersistenceWriteResult,
)
from research_sdk.persistence.statements import (
    build_data_snapshot_manifest_insert,
    build_data_snapshot_manifest_replay_select,
    build_experiment_run_insert,
    build_experiment_run_replay_select,
)


class SqlAlchemyExperimentLedgerRepository(ABC):
    """SQLAlchemy repository boundary for experiment ledger writes."""

    __slots__ = ("_connection",)

    _connection: Connection

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def record_experiment_run(
        self,
        run: ExperimentRunRecord,
    ) -> PersistenceWriteResult:
        self._require_active_transaction()

        result = self._connection.execute(build_experiment_run_insert(run))
        returned = result.mappings().one_or_none()
        if returned is not None:
            return _hash_backed_write_result(
                disposition=PersistenceDisposition.CREATED,
                table_name="experiment_runs",
                primary_key={"run_id": returned["run_id"]},
                contract_hash=returned["contract_hash"],
                inserted_at=returned["inserted_at"],
            )

        attempted_hash = contract_sha256(run)
        replay_result = self._connection.execute(
            build_experiment_run_replay_select(run_id=run.run_id)
        )
        stored = replay_result.mappings().one_or_none()
        if stored is None:
            raise ReplayLookupError(
                PersistenceErrorContext(
                    table_name="experiment_runs",
                    operation="record_experiment_run",
                    logical_identity={"run_id": run.run_id},
                    constraint_name="pk_experiment_runs",
                    attempted_hash_prefix=attempted_hash[:12],
                )
            )

        stored_hash = stored["contract_hash"]
        if stored_hash != attempted_hash:
            raise ContractHashConflictError(
                PersistenceErrorContext(
                    table_name="experiment_runs",
                    operation="record_experiment_run",
                    logical_identity={"run_id": run.run_id},
                    constraint_name="pk_experiment_runs",
                    existing_hash_prefix=stored_hash[:12],
                    attempted_hash_prefix=attempted_hash[:12],
                )
            )

        return _hash_backed_write_result(
            disposition=PersistenceDisposition.REPLAYED,
            table_name="experiment_runs",
            primary_key={"run_id": stored["run_id"]},
            contract_hash=stored_hash,
            inserted_at=stored["inserted_at"],
        )

    def record_data_snapshot_manifest(
        self,
        snapshot: DataSnapshotManifest,
    ) -> PersistenceWriteResult:
        self._require_active_transaction()

        result = self._connection.execute(build_data_snapshot_manifest_insert(snapshot))
        returned = result.mappings().one_or_none()
        if returned is not None:
            return _hash_backed_write_result(
                disposition=PersistenceDisposition.CREATED,
                table_name="data_snapshot_manifests",
                primary_key={"snapshot_id": returned["snapshot_id"]},
                contract_hash=returned["contract_hash"],
                inserted_at=returned["inserted_at"],
            )

        attempted_hash = contract_sha256(snapshot)
        replay_result = self._connection.execute(
            build_data_snapshot_manifest_replay_select(
                snapshot_id=snapshot.snapshot_id,
            )
        )
        stored = replay_result.mappings().one_or_none()
        if stored is None:
            raise ReplayLookupError(
                PersistenceErrorContext(
                    table_name="data_snapshot_manifests",
                    operation="record_data_snapshot_manifest",
                    logical_identity={"snapshot_id": snapshot.snapshot_id},
                    constraint_name="pk_data_snapshot_manifests",
                    attempted_hash_prefix=attempted_hash[:12],
                )
            )

        stored_hash = stored["contract_hash"]
        if stored_hash != attempted_hash:
            raise ContractHashConflictError(
                PersistenceErrorContext(
                    table_name="data_snapshot_manifests",
                    operation="record_data_snapshot_manifest",
                    logical_identity={"snapshot_id": snapshot.snapshot_id},
                    constraint_name="pk_data_snapshot_manifests",
                    existing_hash_prefix=stored_hash[:12],
                    attempted_hash_prefix=attempted_hash[:12],
                )
            )

        return _hash_backed_write_result(
            disposition=PersistenceDisposition.REPLAYED,
            table_name="data_snapshot_manifests",
            primary_key={"snapshot_id": stored["snapshot_id"]},
            contract_hash=stored_hash,
            inserted_at=stored["inserted_at"],
        )

    def _require_active_transaction(self) -> None:
        if not self._connection.in_transaction():
            raise RuntimeError(
                "repository write requires an active caller-owned transaction"
            )

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


def _hash_backed_write_result(
    *,
    disposition: PersistenceDisposition,
    table_name: str,
    primary_key: Mapping[str, str],
    contract_hash: str,
    inserted_at: datetime,
) -> PersistenceWriteResult:
    return PersistenceWriteResult(
        disposition=disposition,
        record=PersistedRecordMetadata(
            table_name=table_name,
            primary_key=dict(primary_key),
            contract_hash=contract_hash,
            inserted_at=inserted_at,
        ),
    )


__all__ = ["SqlAlchemyExperimentLedgerRepository"]
