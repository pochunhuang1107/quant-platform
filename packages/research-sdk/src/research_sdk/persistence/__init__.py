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
    PersistenceCorruptionError,
    PersistenceError,
    PersistenceErrorContext,
    ReplayLookupError,
    ResearchReportCardSourceCoherenceError,
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
    research_report_card_to_row,
    review_metadata_to_row,
    run_artifact_manifest_to_rows,
)
from research_sdk.persistence.metadata import metadata
from research_sdk.persistence.protocols import ExperimentLedgerRepository
from research_sdk.persistence.report_card_sources import (
    validate_research_report_card_sources,
)
from research_sdk.persistence.results import (
    PersistedRecordMetadata,
    PersistenceDisposition,
    PersistenceWriteResult,
)
from research_sdk.persistence.sqlalchemy_repository import (
    SqlAlchemyExperimentLedgerRepository,
)
from research_sdk.persistence.statements import (
    ArtifactManifestInsertStatements,
    build_data_snapshot_manifest_insert,
    build_data_snapshot_manifest_replay_select,
    build_experiment_run_insert,
    build_experiment_run_replay_select,
    build_report_card_ids_for_note_select,
    build_research_note_ids_for_report_card_select,
    build_research_note_insert,
    build_research_note_read_select,
    build_research_note_replay_select,
    build_research_note_report_card_link_insert,
    build_research_note_report_card_link_replay_select,
    build_research_report_card_insert,
    build_research_report_card_read_select,
    build_research_report_card_replay_select,
    build_review_event_insert,
    build_run_artifact_entries_replay_select,
    build_run_artifact_manifest_advisory_lock_selects,
    build_run_artifact_manifest_inserts,
    build_run_artifact_manifest_replay_select,
)
from research_sdk.persistence.tables import (
    LEDGER_ANCHOR_TABLES,
    REPORT_CARD_TABLES,
    data_snapshot_manifests,
    experiment_runs,
    research_note_report_cards,
    research_notes,
    research_report_cards,
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
    "PersistenceCorruptionError",
    "PersistenceWriteResult",
    "REPORT_CARD_TABLES",
    "ReplayLookupError",
    "ResearchReportCardSourceCoherenceError",
    "ReviewSubjectType",
    "SqlAlchemyExperimentLedgerRepository",
    "UnsupportedVersioningConflictError",
    "build_report_card_ids_for_note_select",
    "build_data_snapshot_manifest_insert",
    "build_data_snapshot_manifest_replay_select",
    "build_experiment_run_insert",
    "build_experiment_run_replay_select",
    "build_research_report_card_insert",
    "build_research_report_card_read_select",
    "build_research_report_card_replay_select",
    "build_research_note_insert",
    "build_research_note_read_select",
    "build_research_note_ids_for_report_card_select",
    "build_research_note_report_card_link_insert",
    "build_research_note_report_card_link_replay_select",
    "build_research_note_replay_select",
    "build_review_event_insert",
    "build_run_artifact_entries_replay_select",
    "build_run_artifact_manifest_advisory_lock_selects",
    "build_run_artifact_manifest_inserts",
    "build_run_artifact_manifest_replay_select",
    "canonical_contract_json",
    "canonical_json_sha256",
    "contract_sha256",
    "data_snapshot_manifest_to_row",
    "data_snapshot_manifests",
    "experiment_run_to_row",
    "experiment_runs",
    "get_database_url",
    "metadata",
    "research_report_card_to_row",
    "research_note_report_cards",
    "research_notes",
    "research_report_cards",
    "research_note_to_row",
    "review_metadata_to_row",
    "run_artifact_manifest_to_rows",
    "translate_constraint_violation",
    "translate_sqlalchemy_integrity_error",
    "validate_research_report_card_sources",
]
