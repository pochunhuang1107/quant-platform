"""Run artifact manifest contracts for reproducible research runs."""

from typing import Final, Self

from pydantic import Field, model_validator

from research_sdk.contracts.base import BaseContractModel
from research_sdk.contracts.enums import (
    ArtifactFormat,
    ArtifactKind,
    ArtifactStatus,
    HashAlgorithm,
)
from research_sdk.contracts.schema import VersionedContract
from research_sdk.contracts.time import UtcDatetime
from research_sdk.contracts.types import NonEmptyString

REQUIRED_ARTIFACT_SPECS: Final[dict[ArtifactKind, tuple[str, ArtifactFormat]]] = {
    ArtifactKind.CONFIG: ("config.json", ArtifactFormat.JSON),
    ArtifactKind.METRICS: ("metrics.json", ArtifactFormat.JSON),
    ArtifactKind.TRADE_LOG: ("trade_log.parquet", ArtifactFormat.PARQUET),
    ArtifactKind.SIGNAL_LOG: ("signal_log.parquet", ArtifactFormat.PARQUET),
    ArtifactKind.DAILY_EQUITY: ("daily_equity.parquet", ArtifactFormat.PARQUET),
    ArtifactKind.DRAWDOWN_SERIES: (
        "drawdown_series.parquet",
        ArtifactFormat.PARQUET,
    ),
    ArtifactKind.MONTHLY_RETURNS: (
        "monthly_returns.parquet",
        ArtifactFormat.PARQUET,
    ),
    ArtifactKind.REGIME_BREAKDOWN: ("regime_breakdown.json", ArtifactFormat.JSON),
    ArtifactKind.FAILURE_ANALYSIS: ("failure_analysis.md", ArtifactFormat.MARKDOWN),
    ArtifactKind.RESEARCH_NOTE: ("research_note.md", ArtifactFormat.MARKDOWN),
}


class RunArtifactEntry(BaseContractModel):
    """Single artifact entry in a run artifact manifest."""

    artifact_id: NonEmptyString
    artifact_kind: ArtifactKind
    uri: NonEmptyString
    filename: NonEmptyString
    format: ArtifactFormat
    status: ArtifactStatus
    hash_algorithm: HashAlgorithm | None = None
    content_hash: NonEmptyString | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    row_count: int | None = Field(default=None, ge=0)
    created_at: UtcDatetime | None = None
    validator_version: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_produced_integrity_metadata(self) -> Self:
        """Require integrity metadata for produced artifacts."""

        if self.status is not ArtifactStatus.PRODUCED:
            return self

        missing_fields = [
            field_name
            for field_name in (
                "hash_algorithm",
                "content_hash",
                "size_bytes",
                "created_at",
            )
            if getattr(self, field_name) is None
        ]
        if missing_fields:
            raise ValueError(
                f"produced artifacts require {', '.join(sorted(missing_fields))}"
            )
        return self


class RunArtifactManifest(VersionedContract):
    """Manifest describing required and optional artifacts for a research run."""

    run_id: NonEmptyString
    experiment_id: NonEmptyString
    artifact_root_uri: NonEmptyString
    created_at: UtcDatetime
    required_artifacts_complete: bool
    artifacts: tuple[RunArtifactEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_manifest_consistency(self) -> Self:
        """Validate manifest structure without touching artifact storage."""

        artifact_ids = [artifact.artifact_id for artifact in self.artifacts]
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("artifact_id values must be unique")

        required_artifacts: dict[ArtifactKind, RunArtifactEntry] = {}
        for artifact in self.artifacts:
            if artifact.filename == "artifact_manifest.json":
                raise ValueError("artifact_manifest.json cannot be an artifact entry")

            if artifact.artifact_kind not in REQUIRED_ARTIFACT_SPECS:
                continue

            if artifact.artifact_kind in required_artifacts:
                raise ValueError(
                    f"duplicate required artifact kind: {artifact.artifact_kind}"
                )

            expected_filename, expected_format = REQUIRED_ARTIFACT_SPECS[
                artifact.artifact_kind
            ]
            if artifact.filename != expected_filename:
                raise ValueError(
                    f"{artifact.artifact_kind} requires filename {expected_filename}"
                )
            if artifact.format is not expected_format:
                raise ValueError(
                    f"{artifact.artifact_kind} requires format {expected_format.value}"
                )

            required_artifacts[artifact.artifact_kind] = artifact

        missing_required = set(REQUIRED_ARTIFACT_SPECS) - set(required_artifacts)
        if missing_required:
            missing_names = ", ".join(sorted(kind.value for kind in missing_required))
            raise ValueError(f"missing required artifact kinds: {missing_names}")

        required_entries_complete = all(
            artifact.status is ArtifactStatus.PRODUCED
            for artifact in required_artifacts.values()
        )
        if self.required_artifacts_complete != required_entries_complete:
            raise ValueError(
                "required_artifacts_complete must match required artifact statuses"
            )

        return self
