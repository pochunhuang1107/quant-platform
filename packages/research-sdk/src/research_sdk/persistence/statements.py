"""SQLAlchemy Core persistence statement builders."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import BigInteger, Table, bindparam, func, insert, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.sql.dml import Insert
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Select

from research_sdk.contracts import (
    DataSnapshotManifest,
    ExperimentRunRecord,
    ResearchNote,
    ResearchReportCard,
    ReviewMetadata,
    RunArtifactManifest,
)
from research_sdk.persistence.mappers import (
    ReviewSubjectType,
    data_snapshot_manifest_to_row,
    experiment_run_to_row,
    research_note_to_row,
    research_report_card_to_row,
    review_metadata_to_row,
    run_artifact_manifest_to_rows,
)
from research_sdk.persistence.tables import (
    data_snapshot_manifests,
    experiment_runs,
    research_note_report_cards,
    research_notes,
    research_report_cards,
    review_events,
    run_artifact_entries,
    run_artifact_manifests,
)

_ARTIFACT_MANIFEST_ID_LOCK_NAMESPACE = "quant-platform:artifact-manifest:manifest-id:"
_ARTIFACT_RUN_ID_LOCK_NAMESPACE = "quant-platform:artifact-manifest:run-id:"
_POSTGRES_ADVISORY_LOCK_ENTROPY_MASK = (1 << 63) - 1


@dataclass(frozen=True)
class ArtifactManifestInsertStatements:
    """Insert statements for one artifact manifest and its projected entries."""

    manifest: Insert
    entries: tuple[Insert, ...]


def build_run_artifact_manifest_advisory_lock_selects(
    *,
    manifest_id: str,
    run_id: str,
) -> tuple[Select[Any], ...]:
    """Build transaction-scoped advisory-lock statements for artifact identity."""

    manifest_key = _postgres_advisory_lock_key(
        namespace=_ARTIFACT_MANIFEST_ID_LOCK_NAMESPACE,
        value=manifest_id,
        keyspace="manifest",
    )
    run_key = _postgres_advisory_lock_key(
        namespace=_ARTIFACT_RUN_ID_LOCK_NAMESPACE,
        value=run_id,
        keyspace="run",
    )

    ordered_keys = (
        (manifest_key,) if manifest_key == run_key else (manifest_key, run_key)
    )
    return tuple(_build_advisory_xact_lock_select(lock_key=key) for key in ordered_keys)


def build_experiment_run_insert(
    run: ExperimentRunRecord,
) -> Insert:
    """Build a non-executing insert statement for an experiment run."""

    return _build_replay_candidate_insert(
        table=experiment_runs,
        row=experiment_run_to_row(run),
        returning_columns=(
            experiment_runs.c.run_id,
            experiment_runs.c.contract_hash,
            experiment_runs.c.inserted_at,
        ),
    )


def build_experiment_run_replay_select(
    *,
    run_id: str,
) -> Select[Any]:
    """Build a non-executing replay lookup for an experiment run."""

    return select(
        experiment_runs.c.run_id,
        experiment_runs.c.contract_hash,
        experiment_runs.c.inserted_at,
    ).where(experiment_runs.c.run_id == run_id)


def build_data_snapshot_manifest_insert(
    snapshot: DataSnapshotManifest,
) -> Insert:
    """Build a non-executing insert statement for a data snapshot manifest."""

    return _build_replay_candidate_insert(
        table=data_snapshot_manifests,
        row=data_snapshot_manifest_to_row(snapshot),
        returning_columns=(
            data_snapshot_manifests.c.snapshot_id,
            data_snapshot_manifests.c.contract_hash,
            data_snapshot_manifests.c.inserted_at,
        ),
    )


def build_data_snapshot_manifest_replay_select(
    *,
    snapshot_id: str,
) -> Select[Any]:
    """Build a non-executing replay lookup for a data snapshot manifest."""

    return select(
        data_snapshot_manifests.c.snapshot_id,
        data_snapshot_manifests.c.contract_hash,
        data_snapshot_manifests.c.inserted_at,
    ).where(data_snapshot_manifests.c.snapshot_id == snapshot_id)


def build_run_artifact_manifest_inserts(
    *,
    manifest_id: str,
    manifest: RunArtifactManifest,
) -> ArtifactManifestInsertStatements:
    """Build non-executing insert statements for an artifact manifest."""

    rows = run_artifact_manifest_to_rows(
        manifest_id=manifest_id,
        manifest=manifest,
    )

    return ArtifactManifestInsertStatements(
        manifest=_build_replay_candidate_insert(
            table=run_artifact_manifests,
            row=rows.manifest,
            returning_columns=(
                run_artifact_manifests.c.manifest_id,
                run_artifact_manifests.c.contract_hash,
                run_artifact_manifests.c.inserted_at,
            ),
        ),
        entries=tuple(
            _build_strict_insert(table=run_artifact_entries, row=entry)
            for entry in rows.entries
        ),
    )


def build_run_artifact_manifest_replay_select(
    *,
    manifest_id: str,
) -> Select[Any]:
    """Build a non-executing replay lookup for an artifact manifest."""

    return select(
        run_artifact_manifests.c.manifest_id,
        run_artifact_manifests.c.run_id,
        run_artifact_manifests.c.contract_hash,
        run_artifact_manifests.c.inserted_at,
    ).where(run_artifact_manifests.c.manifest_id == manifest_id)


def build_run_artifact_entries_replay_select(
    *,
    manifest_id: str,
) -> Select[Any]:
    """Build a non-executing replay lookup for artifact manifest entries."""

    return (
        select(
            run_artifact_entries.c.manifest_id,
            run_artifact_entries.c.artifact_id,
            run_artifact_entries.c.run_id,
            run_artifact_entries.c.artifact_kind,
            run_artifact_entries.c.uri,
            run_artifact_entries.c.filename,
            run_artifact_entries.c.format,
            run_artifact_entries.c.status,
            run_artifact_entries.c.hash_algorithm,
            run_artifact_entries.c.content_hash,
            run_artifact_entries.c.size_bytes,
            run_artifact_entries.c.row_count,
            run_artifact_entries.c.created_at,
            run_artifact_entries.c.validator_version,
        )
        .where(run_artifact_entries.c.manifest_id == manifest_id)
        .order_by(run_artifact_entries.c.artifact_id)
    )


def build_research_note_insert(
    note: ResearchNote,
) -> Insert:
    """Build a non-executing insert statement for a research note."""

    return _build_replay_candidate_insert(
        table=research_notes,
        row=research_note_to_row(note),
        returning_columns=(
            research_notes.c.note_id,
            research_notes.c.contract_hash,
            research_notes.c.inserted_at,
        ),
    )


def build_research_note_replay_select(
    *,
    note_id: str,
) -> Select[Any]:
    """Build a non-executing replay lookup for a research note."""

    return select(
        research_notes.c.note_id,
        research_notes.c.contract_hash,
        research_notes.c.inserted_at,
    ).where(research_notes.c.note_id == note_id)


def build_research_note_read_select(
    *,
    note_id: str,
) -> Select[Any]:
    """Build a non-executing durable readback lookup for a research note."""

    return select(research_notes).where(research_notes.c.note_id == note_id)


def build_research_note_report_card_link_insert(
    *,
    note_id: str,
    report_card_id: str,
) -> Insert:
    """Build a non-executing insert for a note-to-report-card link."""

    return _build_replay_candidate_insert(
        table=research_note_report_cards,
        row={"note_id": note_id, "report_card_id": report_card_id},
        returning_columns=(
            research_note_report_cards.c.note_id,
            research_note_report_cards.c.report_card_id,
            research_note_report_cards.c.inserted_at,
        ),
    )


def build_research_note_report_card_link_replay_select(
    *,
    note_id: str,
    report_card_id: str,
) -> Select[Any]:
    """Build a non-executing replay lookup for a note-report-card link."""

    return select(
        research_note_report_cards.c.note_id,
        research_note_report_cards.c.report_card_id,
        research_note_report_cards.c.inserted_at,
    ).where(
        research_note_report_cards.c.note_id == note_id,
        research_note_report_cards.c.report_card_id == report_card_id,
    )


def build_report_card_ids_for_note_select(
    *,
    note_id: str,
) -> Select[Any]:
    """Build a non-executing lookup for report-card IDs linked to a note."""

    return (
        select(research_note_report_cards.c.report_card_id)
        .where(research_note_report_cards.c.note_id == note_id)
        .order_by(research_note_report_cards.c.report_card_id)
    )


def build_research_report_card_insert(
    report_card: ResearchReportCard,
) -> Insert:
    """Build a non-executing insert statement for a research report card."""

    return _build_replay_candidate_insert(
        table=research_report_cards,
        row=research_report_card_to_row(report_card),
        returning_columns=(
            research_report_cards.c.report_card_id,
            research_report_cards.c.contract_hash,
            research_report_cards.c.inserted_at,
        ),
    )


def build_research_report_card_replay_select(
    *,
    report_card_id: str,
) -> Select[Any]:
    """Build a non-executing replay lookup for a research report card."""

    return select(
        research_report_cards.c.report_card_id,
        research_report_cards.c.contract_hash,
        research_report_cards.c.inserted_at,
    ).where(research_report_cards.c.report_card_id == report_card_id)


def build_research_report_card_read_select(
    *,
    report_card_id: str,
) -> Select[Any]:
    """Build a non-executing durable readback lookup for a report card."""

    return select(research_report_cards).where(
        research_report_cards.c.report_card_id == report_card_id
    )


def build_review_event_insert(
    *,
    review_event_id: str,
    subject_type: ReviewSubjectType | str,
    subject_id: str,
    review: ReviewMetadata,
) -> Insert:
    """Build a non-executing insert statement for review metadata."""

    return _build_strict_insert(
        table=review_events,
        row=review_metadata_to_row(
            review_event_id=review_event_id,
            subject_type=subject_type,
            subject_id=subject_id,
            review=review,
        ),
        returning_columns=(
            review_events.c.review_event_id,
            review_events.c.inserted_at,
        ),
    )


def _build_replay_candidate_insert(
    *,
    table: Table,
    row: Mapping[str, Any],
    returning_columns: Sequence[ColumnElement[Any]],
) -> Insert:
    if table.primary_key.name is None:
        raise ValueError(
            "replay-candidate table must have a named primary-key constraint"
        )

    return (
        postgresql_insert(table)
        .values(dict(row))
        .on_conflict_do_nothing(constraint=table.primary_key)
        .returning(*returning_columns)
    )


def _build_strict_insert(
    *,
    table: Table,
    row: Mapping[str, Any],
    returning_columns: Sequence[ColumnElement[Any]] = (),
) -> Insert:
    statement = insert(table).values(dict(row))
    if not returning_columns:
        return statement

    return statement.returning(*returning_columns)


def _build_advisory_xact_lock_select(*, lock_key: int) -> Select[Any]:
    return select(
        func.pg_advisory_xact_lock(
            bindparam("lock_key", lock_key, type_=BigInteger()),
        )
    )


def _postgres_advisory_lock_key(
    *,
    namespace: str,
    value: str,
    keyspace: str,
) -> int:
    digest = hashlib.sha256(bytes(f"{namespace}{value}", "utf-8")).digest()
    entropy = (
        int.from_bytes(digest[:8], byteorder="big", signed=False)
        & _POSTGRES_ADVISORY_LOCK_ENTROPY_MASK
    )
    if keyspace == "manifest":
        return entropy
    if keyspace == "run":
        return -entropy - 1
    raise ValueError("keyspace must be manifest or run")


__all__ = [
    "ArtifactManifestInsertStatements",
    "build_data_snapshot_manifest_insert",
    "build_data_snapshot_manifest_replay_select",
    "build_experiment_run_insert",
    "build_experiment_run_replay_select",
    "build_run_artifact_entries_replay_select",
    "build_run_artifact_manifest_advisory_lock_selects",
    "build_research_report_card_insert",
    "build_research_report_card_read_select",
    "build_research_report_card_replay_select",
    "build_research_note_insert",
    "build_research_note_read_select",
    "build_research_note_report_card_link_insert",
    "build_research_note_report_card_link_replay_select",
    "build_research_note_replay_select",
    "build_report_card_ids_for_note_select",
    "build_review_event_insert",
    "build_run_artifact_manifest_inserts",
    "build_run_artifact_manifest_replay_select",
]
