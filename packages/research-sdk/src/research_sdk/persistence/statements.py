"""SQLAlchemy Core insert statement builders for persistence rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Table, insert
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.sql.dml import Insert
from sqlalchemy.sql.elements import ColumnElement

from research_sdk.contracts import (
    DataSnapshotManifest,
    ExperimentRunRecord,
    ResearchNote,
    ReviewMetadata,
    RunArtifactManifest,
)
from research_sdk.persistence.mappers import (
    ReviewSubjectType,
    data_snapshot_manifest_to_row,
    experiment_run_to_row,
    research_note_to_row,
    review_metadata_to_row,
    run_artifact_manifest_to_rows,
)
from research_sdk.persistence.tables import (
    data_snapshot_manifests,
    experiment_runs,
    research_notes,
    review_events,
    run_artifact_entries,
    run_artifact_manifests,
)


@dataclass(frozen=True)
class ArtifactManifestInsertStatements:
    """Insert statements for one artifact manifest and its projected entries."""

    manifest: Insert
    entries: tuple[Insert, ...]


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


__all__ = [
    "ArtifactManifestInsertStatements",
    "build_data_snapshot_manifest_insert",
    "build_experiment_run_insert",
    "build_research_note_insert",
    "build_review_event_insert",
    "build_run_artifact_manifest_inserts",
]
