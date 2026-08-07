"""Deterministic research report-card contracts."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Final, Self

from pydantic import Field, field_validator, model_validator

from research_sdk.contracts.artifacts import REQUIRED_ARTIFACT_SPECS
from research_sdk.contracts.base import BaseContractModel
from research_sdk.contracts.enums import (
    ArtifactFormat,
    ArtifactKind,
    ArtifactStatus,
    AssetClass,
    DataAdjustmentPolicy,
    ExperimentRunStatus,
    TemporalCoverage,
)
from research_sdk.contracts.ledger import AssetUniverseReference, RandomSeedMetadata
from research_sdk.contracts.schema import VersionedContract
from research_sdk.contracts.types import NonEmptyString

REPORT_CARD_ID_PREFIX: Final = "report-card-"
REPORT_CARD_DIGEST_LENGTH: Final = 64
RATIO_METRIC_SCALE: Final = 12
MONEY_METRIC_SCALE: Final = 6
SHA256_CONTENT_HASH_PATTERN: Final = re.compile(r"^sha256:[0-9a-f]{64}$")

RATIO_METRIC_FIELDS: Final = frozenset(
    {
        "total_return",
        "benchmark_total_return",
        "excess_return",
        "maximum_drawdown",
    }
)
MONEY_METRIC_FIELDS: Final = frozenset(
    {
        "realized_commission",
        "realized_slippage",
        "ending_equity",
    }
)


class ReportCardUseRestriction(StrEnum):
    """Stable use restrictions for deterministic report-card evidence."""

    RESEARCH_GENERATED_SYNTHETIC_DATA = "research_generated_synthetic_data"
    INFRASTRUCTURE_VALIDATION_ONLY = "infrastructure_validation_only"
    NO_INVESTMENT_PERFORMANCE_CLAIM = "no_investment_performance_claim"
    NOT_PRODUCTION_DATA_RESEARCH = "not_production_data_research"
    NOT_PAPER_TRADING_EVIDENCE = "not_paper_trading_evidence"
    NOT_LIVE_TRADING_EVIDENCE = "not_live_trading_evidence"


class ReportCardLineage(BaseContractModel):
    """Source lineage copied from immutable experiment-ledger records."""

    strategy_id: NonEmptyString
    strategy_version: NonEmptyString
    engine_version: NonEmptyString
    git_commit_sha: NonEmptyString
    data_snapshot_id: NonEmptyString
    benchmark_snapshot_id: NonEmptyString
    data_snapshot_content_hash: NonEmptyString
    benchmark_snapshot_content_hash: NonEmptyString
    artifact_manifest_id: NonEmptyString
    config_hash: NonEmptyString
    parameter_hash: NonEmptyString
    artifact_manifest_hash: NonEmptyString

    @field_validator(
        "data_snapshot_content_hash",
        "benchmark_snapshot_content_hash",
        "config_hash",
        "parameter_hash",
        "artifact_manifest_hash",
    )
    @classmethod
    def validate_sha256_content_hash(cls, value: str) -> str:
        """Require full lowercase SHA-256 content hashes."""

        if SHA256_CONTENT_HASH_PATTERN.fullmatch(value) is None:
            raise ValueError("hash fields must use sha256:<64 lowercase hex>")
        return value


class ReportCardResearchScope(BaseContractModel):
    """Experiment scope summarized by the report card."""

    asset_class: AssetClass
    asset_universe: AssetUniverseReference
    benchmark_id: NonEmptyString
    frequency: NonEmptyString
    start_date: date
    end_date: date
    observation_count: int = Field(ge=0)
    source_run_status: ExperimentRunStatus

    @model_validator(mode="after")
    def validate_completed_scope(self) -> Self:
        """Report cards in this slice summarize completed runs only."""

        if self.source_run_status is not ExperimentRunStatus.COMPLETED:
            raise ValueError("source_run_status must be completed")
        if self.end_date < self.start_date:
            raise ValueError("end_date must be greater than or equal to start_date")
        return self


class ReportCardAssumptions(BaseContractModel):
    """Deterministic assumptions copied from run and snapshot contracts."""

    cost_model: NonEmptyString
    slippage_model: NonEmptyString
    lookback: NonEmptyString
    lag_assumptions: NonEmptyString
    leakage_review: NonEmptyString
    random_seed: RandomSeedMetadata
    adjustment_policy: DataAdjustmentPolicy
    temporal_coverage: TemporalCoverage
    corporate_action_policy: NonEmptyString
    survivorship_policy: NonEmptyString
    universe_membership_policy: NonEmptyString
    calendar: NonEmptyString
    timezone: NonEmptyString


class ReportCardMetrics(BaseContractModel):
    """Approved scalar metric set for deterministic report cards."""

    total_return: NonEmptyString
    benchmark_total_return: NonEmptyString
    excess_return: NonEmptyString
    maximum_drawdown: NonEmptyString
    realized_commission: NonEmptyString
    realized_slippage: NonEmptyString
    ending_equity: NonEmptyString
    number_of_trades: int = Field(ge=0)
    observation_count: int = Field(ge=0)

    @field_validator(
        "total_return",
        "benchmark_total_return",
        "excess_return",
        "maximum_drawdown",
        "realized_commission",
        "realized_slippage",
        "ending_equity",
    )
    @classmethod
    def validate_canonical_decimal_string(
        cls,
        value: str,
        info: object,
    ) -> str:
        """Require canonical finite fixed-point decimal strings."""

        field_name = getattr(info, "field_name")
        scale = (
            RATIO_METRIC_SCALE
            if field_name in RATIO_METRIC_FIELDS
            else MONEY_METRIC_SCALE
        )
        pattern = re.compile(rf"^-?(0|[1-9][0-9]*)\.[0-9]{{{scale}}}$")
        if pattern.fullmatch(value) is None:
            raise ValueError(
                f"{field_name} must use canonical fixed-point scale {scale}"
            )
        try:
            decimal_value = Decimal(value)
        except Exception as exc:
            raise ValueError("metric values must be decimal strings") from exc
        if not decimal_value.is_finite():
            raise ValueError("metric values must be finite")
        if value.startswith("-") and decimal_value == 0:
            raise ValueError("negative zero is not a canonical metric value")
        if (
            field_name
            in {
                "realized_commission",
                "realized_slippage",
                "ending_equity",
            }
            and decimal_value < 0
        ):
            raise ValueError(f"{field_name} must be nonnegative")
        if field_name == "maximum_drawdown" and decimal_value > 0:
            raise ValueError("maximum_drawdown must be less than or equal to zero")
        return value


class ReportCardArtifactEvidenceEntry(BaseContractModel):
    """Immutable evidence copied from a run artifact manifest entry."""

    artifact_id: NonEmptyString
    artifact_kind: ArtifactKind
    filename: NonEmptyString
    uri: NonEmptyString
    format: ArtifactFormat
    status: ArtifactStatus
    content_hash: NonEmptyString
    size_bytes: int = Field(ge=0)
    row_count: int | None = Field(default=None, ge=0)
    validator_version: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_produced_entry(self) -> Self:
        """Report-card evidence only records produced artifact facts."""

        if self.status is not ArtifactStatus.PRODUCED:
            raise ValueError("artifact evidence status must be produced")
        if SHA256_CONTENT_HASH_PATTERN.fullmatch(self.content_hash) is None:
            raise ValueError("content_hash must use sha256:<64 lowercase hex>")
        return self


class ReportCardEvidence(BaseContractModel):
    """Artifact evidence summarized by the report card."""

    artifact_root_uri: NonEmptyString
    artifact_manifest_uri: NonEmptyString
    required_artifacts_complete: bool
    artifacts: tuple[ReportCardArtifactEvidenceEntry, ...] = Field(min_length=1)

    @field_validator("artifacts")
    @classmethod
    def normalize_artifact_order(
        cls,
        value: tuple[ReportCardArtifactEvidenceEntry, ...],
    ) -> tuple[ReportCardArtifactEvidenceEntry, ...]:
        """Normalize artifact evidence order deterministically."""

        return tuple(
            sorted(
                value,
                key=lambda entry: (
                    entry.artifact_kind.value,
                    entry.filename,
                    entry.artifact_id,
                ),
            )
        )

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        """Reject duplicate, incomplete, or incoherent required evidence."""

        if not self.required_artifacts_complete:
            raise ValueError("required_artifacts_complete must be true")
        artifact_ids = [entry.artifact_id for entry in self.artifacts]
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("artifact_id values must be unique")
        filenames = [entry.filename for entry in self.artifacts]
        if len(set(filenames)) != len(filenames):
            raise ValueError("artifact filenames must be unique")

        required_entries: dict[ArtifactKind, ReportCardArtifactEvidenceEntry] = {}
        required_filenames = {
            filename for filename, _artifact_format in REQUIRED_ARTIFACT_SPECS.values()
        }
        for entry in self.artifacts:
            if (
                entry.artifact_kind not in REQUIRED_ARTIFACT_SPECS
                and entry.filename in required_filenames
            ):
                raise ValueError("optional artifacts cannot use required filenames")
            if entry.artifact_kind not in REQUIRED_ARTIFACT_SPECS:
                continue
            if entry.artifact_kind in required_entries:
                raise ValueError("required artifact kinds must be unique")
            expected_filename, expected_format = REQUIRED_ARTIFACT_SPECS[
                entry.artifact_kind
            ]
            if entry.filename != expected_filename:
                raise ValueError("required artifact filename mismatch")
            if entry.format is not expected_format:
                raise ValueError("required artifact format mismatch")
            if entry.status is not ArtifactStatus.PRODUCED:
                raise ValueError("required artifacts must be produced")
            if entry.uri != f"{self.artifact_root_uri}/{entry.filename}":
                raise ValueError("required artifact URI must match artifact root")
            required_entries[entry.artifact_kind] = entry

        missing_required = set(REQUIRED_ARTIFACT_SPECS) - set(required_entries)
        if missing_required:
            missing_names = ", ".join(sorted(kind.value for kind in missing_required))
            raise ValueError(f"missing required artifact kinds: {missing_names}")
        return self


class ReportCardLimitations(BaseContractModel):
    """Known source and report-card limitations."""

    source_snapshot_known_limitations: tuple[NonEmptyString, ...] = Field(min_length=1)


class ResearchReportCard(VersionedContract):
    """Deterministic evidence summary derived from immutable research records."""

    report_card_id: NonEmptyString
    derivation_policy_version: NonEmptyString
    source_run_id: NonEmptyString
    experiment_id: NonEmptyString
    lineage: ReportCardLineage
    research_scope: ReportCardResearchScope
    assumptions: ReportCardAssumptions
    metrics: ReportCardMetrics
    evidence: ReportCardEvidence
    limitations: ReportCardLimitations
    use_restrictions: tuple[ReportCardUseRestriction, ...] = Field(min_length=1)

    @field_validator("report_card_id")
    @classmethod
    def validate_report_card_id(cls, value: str) -> str:
        """Require report-card IDs to include a full lowercase SHA-256 digest."""

        if not value.startswith(REPORT_CARD_ID_PREFIX):
            raise ValueError("report_card_id must use the report-card- prefix")
        digest = value.removeprefix(REPORT_CARD_ID_PREFIX)
        if len(digest) != REPORT_CARD_DIGEST_LENGTH:
            raise ValueError("report_card_id must contain a full SHA-256 digest")
        if digest.lower() != digest or not all(
            character in "0123456789abcdef" for character in digest
        ):
            raise ValueError("report_card_id digest must be lowercase hexadecimal")
        return value

    @field_validator("use_restrictions")
    @classmethod
    def normalize_use_restrictions(
        cls,
        value: tuple[ReportCardUseRestriction, ...],
    ) -> tuple[ReportCardUseRestriction, ...]:
        """Normalize use restrictions as deterministic set-like metadata."""

        if len(set(value)) != len(value):
            raise ValueError("use_restrictions values must be unique")
        return tuple(sorted(value, key=lambda restriction: restriction.value))

    @model_validator(mode="after")
    def validate_report_card_consistency(self) -> Self:
        """Validate internal report-card consistency."""

        if self.research_scope.observation_count != self.metrics.observation_count:
            raise ValueError("observation_count must agree across scope and metrics")
        return self


__all__ = [
    "REPORT_CARD_DIGEST_LENGTH",
    "REPORT_CARD_ID_PREFIX",
    "ReportCardArtifactEvidenceEntry",
    "ReportCardAssumptions",
    "ReportCardEvidence",
    "ReportCardLimitations",
    "ReportCardLineage",
    "ReportCardMetrics",
    "ReportCardResearchScope",
    "ReportCardUseRestriction",
    "ResearchReportCard",
]
