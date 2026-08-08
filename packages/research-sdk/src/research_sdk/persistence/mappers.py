"""Pure row mappers from validated contracts to persistence row dictionaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from research_sdk.contracts import (
    DataSnapshotManifest,
    ExperimentRunRecord,
    ResearchNote,
    ResearchReportCard,
    ReviewMetadata,
    RunArtifactManifest,
)
from research_sdk.persistence.hashing import contract_sha256
from research_sdk.report_card_identity import verify_research_report_card_identity


class ReviewSubjectType(StrEnum):
    """Review event subject types supported by the persistence projection."""

    EXPERIMENT_RUN = "experiment_run"
    RESEARCH_NOTE = "research_note"
    DATA_SNAPSHOT_MANIFEST = "data_snapshot_manifest"
    RUN_ARTIFACT_MANIFEST = "run_artifact_manifest"


@dataclass(frozen=True)
class ArtifactManifestRows:
    """DB-shaped row projections for one artifact manifest contract."""

    manifest: dict[str, Any]
    entries: tuple[dict[str, Any], ...]


def experiment_run_to_row(run: ExperimentRunRecord) -> dict[str, Any]:
    """Project a validated experiment run contract to an experiment_runs row."""

    raw_contract = run.model_dump(mode="json")
    review = raw_contract["review"]

    return {
        "run_id": raw_contract["run_id"],
        "experiment_id": raw_contract["experiment_id"],
        "schema_version": raw_contract["schema_version"],
        "status": raw_contract["status"],
        "created_at": raw_contract["created_at"],
        "created_by": raw_contract["created_by"],
        "status_updated_at": raw_contract["status_updated_at"],
        "status_updated_by": raw_contract["status_updated_by"],
        "strategy_id": raw_contract["strategy_id"],
        "strategy_version": raw_contract["strategy_version"],
        "git_commit_sha": raw_contract["git_commit_sha"],
        "repo_dirty": raw_contract["repo_dirty"],
        "asset_class": raw_contract["asset_class"],
        "frequency": raw_contract["frequency"],
        "data_snapshot_id": raw_contract["data_snapshot_id"],
        "feature_snapshot_id": raw_contract["feature_snapshot_id"],
        "artifact_uri": raw_contract["artifact_uri"],
        "artifact_manifest_uri": raw_contract["artifact_manifest_uri"],
        "artifact_manifest_hash": raw_contract["artifact_manifest_hash"],
        "parent_run_id": raw_contract["parent_run_id"],
        "supersedes_run_id": raw_contract["supersedes_run_id"],
        "review_status": review["review_status"],
        "reviewer_id": review["reviewer_id"],
        "review_role": review["review_role"],
        "reviewed_at": review["reviewed_at"],
        "risk_approval_required": review["risk_approval_required"],
        "contract_hash": contract_sha256(run),
        "raw_contract": raw_contract,
    }


def data_snapshot_manifest_to_row(
    snapshot: DataSnapshotManifest,
) -> dict[str, Any]:
    """Project a validated data snapshot manifest to a DB-shaped row."""

    raw_contract = snapshot.model_dump(mode="json")

    return {
        "snapshot_id": raw_contract["snapshot_id"],
        "schema_version": raw_contract["schema_version"],
        "snapshot_kind": raw_contract["snapshot_kind"],
        "status": raw_contract["status"],
        "created_at": raw_contract["created_at"],
        "created_by": raw_contract["created_by"],
        "asset_class": raw_contract["asset_class"],
        "frequency": raw_contract["frequency"],
        "data_root_uri": raw_contract["data_root_uri"],
        "source_dataset": raw_contract["source_dataset"],
        "source_version": raw_contract["source_version"],
        "source_type": raw_contract["source_type"],
        "vendor_name": raw_contract["vendor_name"],
        "temporal_coverage": raw_contract["temporal_coverage"],
        "as_of": raw_contract["as_of"],
        "available_at": raw_contract["available_at"],
        "ingestion_completed_at": raw_contract["ingestion_completed_at"],
        "adjustment_policy": raw_contract["adjustment_policy"],
        "calendar": raw_contract["calendar"],
        "timezone": raw_contract["timezone"],
        "row_count": raw_contract["row_count"],
        "file_count": raw_contract["file_count"],
        "size_bytes": raw_contract["size_bytes"],
        "contract_hash": contract_sha256(snapshot),
        "raw_contract": raw_contract,
    }


def run_artifact_manifest_to_rows(
    *,
    manifest_id: str,
    manifest: RunArtifactManifest,
) -> ArtifactManifestRows:
    """Project a validated artifact manifest to manifest and entry rows."""

    raw_contract = manifest.model_dump(mode="json")
    manifest_row = {
        "manifest_id": manifest_id,
        "run_id": raw_contract["run_id"],
        "experiment_id": raw_contract["experiment_id"],
        "schema_version": raw_contract["schema_version"],
        "artifact_root_uri": raw_contract["artifact_root_uri"],
        "created_at": raw_contract["created_at"],
        "required_artifacts_complete": raw_contract["required_artifacts_complete"],
        "contract_hash": contract_sha256(manifest),
        "raw_contract": raw_contract,
    }

    entry_rows = tuple(
        {
            "manifest_id": manifest_id,
            "artifact_id": artifact["artifact_id"],
            "run_id": raw_contract["run_id"],
            "artifact_kind": artifact["artifact_kind"],
            "uri": artifact["uri"],
            "filename": artifact["filename"],
            "format": artifact["format"],
            "status": artifact["status"],
            "hash_algorithm": artifact["hash_algorithm"],
            "content_hash": artifact["content_hash"],
            "size_bytes": artifact["size_bytes"],
            "row_count": artifact["row_count"],
            "created_at": artifact["created_at"],
            "validator_version": artifact["validator_version"],
        }
        for artifact in raw_contract["artifacts"]
    )

    return ArtifactManifestRows(manifest=manifest_row, entries=entry_rows)


def research_report_card_to_row(report_card: ResearchReportCard) -> dict[str, Any]:
    """Project a validated report-card contract to a DB-shaped row."""

    verify_research_report_card_identity(report_card)
    raw_contract = report_card.model_dump(mode="json")
    lineage = raw_contract["lineage"]

    return {
        "report_card_id": raw_contract["report_card_id"],
        "schema_version": raw_contract["schema_version"],
        "derivation_policy_version": raw_contract["derivation_policy_version"],
        "source_run_id": raw_contract["source_run_id"],
        "experiment_id": raw_contract["experiment_id"],
        "strategy_id": lineage["strategy_id"],
        "strategy_version": lineage["strategy_version"],
        "data_snapshot_id": lineage["data_snapshot_id"],
        "benchmark_snapshot_id": lineage["benchmark_snapshot_id"],
        "artifact_manifest_id": lineage["artifact_manifest_id"],
        "contract_hash": contract_sha256(report_card),
        "raw_contract": raw_contract,
    }


def research_note_to_row(note: ResearchNote) -> dict[str, Any]:
    """Project a validated research note contract to a research_notes row."""

    raw_contract = note.model_dump(mode="json")
    review = raw_contract["review"]

    return {
        "note_id": raw_contract["note_id"],
        "schema_version": raw_contract["schema_version"],
        "note_type": raw_contract["note_type"],
        "status": raw_contract["status"],
        "created_at": raw_contract["created_at"],
        "created_by": raw_contract["created_by"],
        "updated_at": raw_contract["updated_at"],
        "updated_by": raw_contract["updated_by"],
        "title": raw_contract["title"],
        "hypothesis_status": raw_contract["hypothesis"]["status"],
        "evidence_strength": raw_contract["evidence_strength"],
        "decision_outcome": raw_contract["decision"]["outcome"],
        "parent_note_id": raw_contract["parent_note_id"],
        "supersedes_note_id": raw_contract["supersedes_note_id"],
        "review_status": review["review_status"],
        "reviewer_id": review["reviewer_id"],
        "review_role": review["review_role"],
        "reviewed_at": review["reviewed_at"],
        "risk_approval_required": review["risk_approval_required"],
        "contract_hash": contract_sha256(note),
        "raw_contract": raw_contract,
    }


def review_metadata_to_row(
    *,
    review_event_id: str,
    subject_type: ReviewSubjectType | str,
    subject_id: str,
    review: ReviewMetadata,
) -> dict[str, Any]:
    """Project validated review metadata to a review_events row."""

    subject_type_value = _coerce_review_subject_type(subject_type)
    raw_review = review.model_dump(mode="json")

    return {
        "review_event_id": review_event_id,
        "subject_type": subject_type_value,
        "subject_id": subject_id,
        "review_status": raw_review["review_status"],
        "reviewer_id": raw_review["reviewer_id"],
        "review_role": raw_review["review_role"],
        "reviewed_at": raw_review["reviewed_at"],
        "decision": raw_review["decision"],
        "approval_scope": raw_review["approval_scope"],
        "approval_expires_at": raw_review["approval_expires_at"],
        "linked_pr": raw_review["linked_pr"],
        "review_notes_uri": raw_review["review_notes_uri"],
        "risk_approval_required": raw_review["risk_approval_required"],
        "raw_review": raw_review,
    }


def _coerce_review_subject_type(subject_type: ReviewSubjectType | str) -> str:
    if isinstance(subject_type, ReviewSubjectType):
        return subject_type.value

    try:
        return ReviewSubjectType(subject_type).value
    except ValueError as exc:
        allowed_values = ", ".join(member.value for member in ReviewSubjectType)
        raise ValueError(f"subject_type must be one of: {allowed_values}") from exc
