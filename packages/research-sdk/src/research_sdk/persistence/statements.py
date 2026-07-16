"""SQLAlchemy Core insert statement builders for persistence rows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Table, insert
from sqlalchemy.sql.dml import Insert

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

    return _build_insert(experiment_runs, experiment_run_to_row(run))


def build_data_snapshot_manifest_insert(
    snapshot: DataSnapshotManifest,
) -> Insert:
    """Build a non-executing insert statement for a data snapshot manifest."""

    return _build_insert(
        data_snapshot_manifests,
        data_snapshot_manifest_to_row(snapshot),
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
        manifest=_build_insert(run_artifact_manifests, rows.manifest),
        entries=tuple(
            _build_insert(run_artifact_entries, entry) for entry in rows.entries
        ),
    )


def build_research_note_insert(
    note: ResearchNote,
) -> Insert:
    """Build a non-executing insert statement for a research note."""

    return _build_insert(research_notes, research_note_to_row(note))


def build_review_event_insert(
    *,
    review_event_id: str,
    subject_type: ReviewSubjectType | str,
    subject_id: str,
    review: ReviewMetadata,
) -> Insert:
    """Build a non-executing insert statement for review metadata."""

    return _build_insert(
        review_events,
        review_metadata_to_row(
            review_event_id=review_event_id,
            subject_type=subject_type,
            subject_id=subject_id,
            review=review,
        ),
    )


def _build_insert(table: Table, row: Mapping[str, Any]) -> Insert:
    return insert(table).values(dict(row))


__all__ = [
    "ArtifactManifestInsertStatements",
    "build_data_snapshot_manifest_insert",
    "build_experiment_run_insert",
    "build_research_note_insert",
    "build_review_event_insert",
    "build_run_artifact_manifest_inserts",
]
