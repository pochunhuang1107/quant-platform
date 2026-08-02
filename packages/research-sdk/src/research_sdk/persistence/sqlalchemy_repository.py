"""SQLAlchemy repository for experiment ledger persistence."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from research_sdk.contracts import (
    DataSnapshotManifest,
    ExperimentRunRecord,
    ResearchNote,
    ReviewMetadata,
    RunArtifactManifest,
)
from research_sdk.persistence.driver_exception_translation import (
    translate_sqlalchemy_integrity_error,
)
from research_sdk.persistence.errors import (
    AggregateIntegrityError,
    ContractHashConflictError,
    PersistenceErrorContext,
    ReplayLookupError,
)
from research_sdk.persistence.hashing import contract_sha256
from research_sdk.persistence.mappers import (
    ReviewSubjectType,
    run_artifact_manifest_to_rows,
)
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
    build_research_note_insert,
    build_research_note_replay_select,
    build_review_event_insert,
    build_run_artifact_entries_replay_select,
    build_run_artifact_manifest_inserts,
    build_run_artifact_manifest_replay_select,
)


class SqlAlchemyExperimentLedgerRepository:
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

    def record_run_artifact_manifest(
        self,
        *,
        manifest_id: str,
        manifest: RunArtifactManifest,
    ) -> PersistenceWriteResult:
        self._require_active_transaction()

        grouped_statements = build_run_artifact_manifest_inserts(
            manifest_id=manifest_id,
            manifest=manifest,
        )
        try:
            result = self._connection.execute(grouped_statements.manifest)
        except IntegrityError as error:
            attempted_hash = contract_sha256(manifest)
            context = PersistenceErrorContext(
                table_name="run_artifact_manifests",
                operation="record_run_artifact_manifest",
                logical_identity={
                    "manifest_id": manifest_id,
                    "run_id": manifest.run_id,
                },
                attempted_hash_prefix=attempted_hash[:12],
            )
            translated = translate_sqlalchemy_integrity_error(
                error=error,
                context=context,
            )
            if translated is None:
                raise
            raise translated from error

        returned = result.mappings().one_or_none()
        if returned is not None:
            for entry_statement in grouped_statements.entries:
                self._connection.execute(entry_statement)
            return PersistenceWriteResult(
                disposition=PersistenceDisposition.CREATED,
                record=PersistedRecordMetadata(
                    table_name="run_artifact_manifests",
                    primary_key={"manifest_id": returned["manifest_id"]},
                    contract_hash=returned["contract_hash"],
                    inserted_at=returned["inserted_at"],
                ),
                aggregate_entry_count=len(grouped_statements.entries),
            )

        attempted_hash = contract_sha256(manifest)
        replay_result = self._connection.execute(
            build_run_artifact_manifest_replay_select(manifest_id=manifest_id)
        )
        stored = replay_result.mappings().one_or_none()
        if stored is None:
            raise ReplayLookupError(
                PersistenceErrorContext(
                    table_name="run_artifact_manifests",
                    operation="record_run_artifact_manifest",
                    logical_identity={"manifest_id": manifest_id},
                    constraint_name="pk_run_artifact_manifests",
                    attempted_hash_prefix=attempted_hash[:12],
                )
            )

        stored_hash = stored["contract_hash"]
        if stored_hash != attempted_hash:
            raise ContractHashConflictError(
                PersistenceErrorContext(
                    table_name="run_artifact_manifests",
                    operation="record_run_artifact_manifest",
                    logical_identity={"manifest_id": manifest_id},
                    constraint_name="pk_run_artifact_manifests",
                    existing_hash_prefix=stored_hash[:12],
                    attempted_hash_prefix=attempted_hash[:12],
                )
            )

        if stored["run_id"] != manifest.run_id:
            raise AggregateIntegrityError(
                PersistenceErrorContext(
                    table_name="run_artifact_manifests",
                    operation="record_run_artifact_manifest",
                    logical_identity={"manifest_id": manifest_id},
                )
            )

        expected_entries = run_artifact_manifest_to_rows(
            manifest_id=manifest_id,
            manifest=manifest,
        ).entries
        stored_entries_result = self._connection.execute(
            build_run_artifact_entries_replay_select(manifest_id=manifest_id)
        )
        stored_entries = tuple(
            cast(Mapping[str, Any], row) for row in stored_entries_result.mappings()
        )
        if not _artifact_entry_projections_match(
            expected_entries=expected_entries,
            stored_entries=stored_entries,
        ):
            raise AggregateIntegrityError(
                PersistenceErrorContext(
                    table_name="run_artifact_entries",
                    operation="record_run_artifact_manifest",
                    logical_identity={
                        "manifest_id": manifest_id,
                        "run_id": manifest.run_id,
                    },
                )
            )

        return PersistenceWriteResult(
            disposition=PersistenceDisposition.REPLAYED,
            record=PersistedRecordMetadata(
                table_name="run_artifact_manifests",
                primary_key={"manifest_id": stored["manifest_id"]},
                contract_hash=stored_hash,
                inserted_at=stored["inserted_at"],
            ),
            aggregate_entry_count=len(stored_entries),
        )

    def record_research_note(
        self,
        note: ResearchNote,
    ) -> PersistenceWriteResult:
        self._require_active_transaction()

        result = self._connection.execute(build_research_note_insert(note))
        returned = result.mappings().one_or_none()
        if returned is not None:
            return _hash_backed_write_result(
                disposition=PersistenceDisposition.CREATED,
                table_name="research_notes",
                primary_key={"note_id": returned["note_id"]},
                contract_hash=returned["contract_hash"],
                inserted_at=returned["inserted_at"],
            )

        attempted_hash = contract_sha256(note)
        replay_result = self._connection.execute(
            build_research_note_replay_select(note_id=note.note_id)
        )
        stored = replay_result.mappings().one_or_none()
        if stored is None:
            raise ReplayLookupError(
                PersistenceErrorContext(
                    table_name="research_notes",
                    operation="record_research_note",
                    logical_identity={"note_id": note.note_id},
                    constraint_name="pk_research_notes",
                    attempted_hash_prefix=attempted_hash[:12],
                )
            )

        stored_hash = stored["contract_hash"]
        if stored_hash != attempted_hash:
            raise ContractHashConflictError(
                PersistenceErrorContext(
                    table_name="research_notes",
                    operation="record_research_note",
                    logical_identity={"note_id": note.note_id},
                    constraint_name="pk_research_notes",
                    existing_hash_prefix=stored_hash[:12],
                    attempted_hash_prefix=attempted_hash[:12],
                )
            )

        return _hash_backed_write_result(
            disposition=PersistenceDisposition.REPLAYED,
            table_name="research_notes",
            primary_key={"note_id": stored["note_id"]},
            contract_hash=stored_hash,
            inserted_at=stored["inserted_at"],
        )

    def append_review_event(
        self,
        *,
        review_event_id: str,
        subject_type: ReviewSubjectType | str,
        subject_id: str,
        review: ReviewMetadata,
    ) -> PersistenceWriteResult:
        self._require_active_transaction()

        statement = build_review_event_insert(
            review_event_id=review_event_id,
            subject_type=subject_type,
            subject_id=subject_id,
            review=review,
        )
        try:
            result = self._connection.execute(statement)
        except IntegrityError as error:
            context = PersistenceErrorContext(
                table_name="review_events",
                operation="append_review_event",
                logical_identity={"review_event_id": review_event_id},
            )
            translated = translate_sqlalchemy_integrity_error(
                error=error,
                context=context,
            )
            if translated is None:
                raise
            raise translated from error

        returned = result.mappings().one()
        return PersistenceWriteResult(
            disposition=PersistenceDisposition.CREATED,
            record=PersistedRecordMetadata(
                table_name="review_events",
                primary_key={"review_event_id": returned["review_event_id"]},
                contract_hash=None,
                inserted_at=returned["inserted_at"],
            ),
        )


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


_ARTIFACT_ENTRY_REPLAY_COLUMNS = (
    "manifest_id",
    "artifact_id",
    "run_id",
    "artifact_kind",
    "uri",
    "filename",
    "format",
    "status",
    "hash_algorithm",
    "content_hash",
    "size_bytes",
    "row_count",
    "created_at",
    "validator_version",
)


def _artifact_entry_projections_match(
    *,
    expected_entries: tuple[dict[str, Any], ...],
    stored_entries: tuple[Mapping[str, Any], ...],
) -> bool:
    try:
        expected_projection = _artifact_entry_projection_by_id(expected_entries)
        stored_projection = _artifact_entry_projection_by_id(stored_entries)
    except (KeyError, TypeError, ValueError):
        return False

    if expected_projection is None or stored_projection is None:
        return False

    return (
        len(expected_entries) == len(expected_projection)
        and len(stored_entries) == len(stored_projection)
        and expected_projection == stored_projection
    )


def _artifact_entry_projection_by_id(
    entries: tuple[Mapping[str, Any], ...],
) -> dict[str, tuple[tuple[str, object], ...]] | None:
    projection: dict[str, tuple[tuple[str, object], ...]] = {}
    for entry in entries:
        artifact_id = entry["artifact_id"]
        if not isinstance(artifact_id, str) or artifact_id in projection:
            return None

        projection[artifact_id] = tuple(
            (
                column_name,
                _normalize_artifact_entry_value(
                    column_name=column_name,
                    value=entry[column_name],
                ),
            )
            for column_name in _ARTIFACT_ENTRY_REPLAY_COLUMNS
        )

    return projection


def _normalize_artifact_entry_value(
    *,
    column_name: str,
    value: object,
) -> object:
    if column_name == "created_at":
        return _normalize_artifact_entry_created_at(value)
    return value


def _normalize_artifact_entry_created_at(value: object) -> object:
    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("artifact entry created_at must be timezone-aware")
        return _datetime_to_utc_json(value)

    if isinstance(value, str):
        parsed_value = f"{value[:-1]}+00:00" if value.endswith("Z") else value
        parsed_datetime = datetime.fromisoformat(parsed_value)
        if parsed_datetime.tzinfo is None or parsed_datetime.utcoffset() is None:
            raise ValueError("artifact entry created_at must be timezone-aware")
        return _datetime_to_utc_json(parsed_datetime)

    raise TypeError("artifact entry created_at must be datetime, string, or None")


def _datetime_to_utc_json(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = ["SqlAlchemyExperimentLedgerRepository"]
