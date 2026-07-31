"""Persistence setup primitives for the research SDK."""

from research_sdk.persistence.constraint_translation import (
    translate_constraint_violation,
)
from research_sdk.persistence.database import get_database_url
from research_sdk.persistence.driver_exception_translation import (
    translate_sqlalchemy_integrity_error,
)
from research_sdk.persistence.errors import (
    AggregateIntegrityError,
    ContractHashConflictError,
    DuplicateReviewEventError,
    NaturalKeyConflictError,
    PersistenceConflictError,
    PersistenceError,
    PersistenceErrorContext,
    UnsupportedVersioningConflictError,
)
from research_sdk.persistence.hashing import (
    canonical_contract_json,
    canonical_json_sha256,
    contract_sha256,
)
from research_sdk.persistence.mappers import (
    ArtifactManifestRows,
    ReviewSubjectType,
    data_snapshot_manifest_to_row,
    experiment_run_to_row,
    research_note_to_row,
    review_metadata_to_row,
    run_artifact_manifest_to_rows,
)
from research_sdk.persistence.metadata import metadata
from research_sdk.persistence.protocols import ExperimentLedgerRepository
from research_sdk.persistence.results import (
    PersistedRecordMetadata,
    PersistenceDisposition,
    PersistenceWriteResult,
)
from research_sdk.persistence.statements import (
    ArtifactManifestInsertStatements,
    build_data_snapshot_manifest_insert,
    build_experiment_run_insert,
    build_research_note_insert,
    build_review_event_insert,
    build_run_artifact_manifest_inserts,
)
from research_sdk.persistence.tables import (
    LEDGER_ANCHOR_TABLES,
    data_snapshot_manifests,
    experiment_runs,
)

__all__ = [
    "AggregateIntegrityError",
    "ArtifactManifestInsertStatements",
    "ArtifactManifestRows",
    "ContractHashConflictError",
    "DuplicateReviewEventError",
    "ExperimentLedgerRepository",
    "LEDGER_ANCHOR_TABLES",
    "NaturalKeyConflictError",
    "PersistedRecordMetadata",
    "PersistenceConflictError",
    "PersistenceDisposition",
    "PersistenceError",
    "PersistenceErrorContext",
    "PersistenceWriteResult",
    "ReviewSubjectType",
    "UnsupportedVersioningConflictError",
    "build_data_snapshot_manifest_insert",
    "build_experiment_run_insert",
    "build_research_note_insert",
    "build_review_event_insert",
    "build_run_artifact_manifest_inserts",
    "canonical_contract_json",
    "canonical_json_sha256",
    "contract_sha256",
    "data_snapshot_manifest_to_row",
    "data_snapshot_manifests",
    "experiment_run_to_row",
    "experiment_runs",
    "get_database_url",
    "metadata",
    "research_note_to_row",
    "review_metadata_to_row",
    "run_artifact_manifest_to_rows",
    "translate_constraint_violation",
    "translate_sqlalchemy_integrity_error",
]
