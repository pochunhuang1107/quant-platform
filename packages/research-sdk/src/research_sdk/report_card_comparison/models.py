"""Pure models for deterministic report-card comparison."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from typing import Final, Self

from pydantic import Field, field_validator, model_validator

from research_sdk.contracts import BaseContractModel, ReportCardUseRestriction
from research_sdk.contracts.schema import RESEARCH_SDK_CONTRACT_SCHEMA_VERSION
from research_sdk.contracts.types import NonEmptyString

REPORT_CARD_COMPARISON_SCHEMA_VERSION: Final = RESEARCH_SDK_CONTRACT_SCHEMA_VERSION
REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION: Final = (
    "research-comparison-compatibility-v1"
)
REPORT_CARD_COMPARISON_METRIC_POLICY_VERSION: Final = "research-comparison-metrics-v1"
REPORT_CARD_COMPARISON_ID_PREFIX: Final = "report-card-comparison-v1-"
REPORT_CARD_COMPARISON_DIGEST_LENGTH: Final = 64
RATIO_COMPARISON_SCALE: Final = 12
_LOWER_HEX_DIGITS: Final = frozenset("0123456789abcdef")
_RATIO_DECIMAL_PATTERN: Final = re.compile(r"^-?(0|[1-9][0-9]*)\.[0-9]{12}$")
_RATIO_QUANT: Final = Decimal("0.000000000001")
_CANONICAL_METRIC_ORDER: Final = (
    "total_return",
    "excess_return",
    "maximum_drawdown",
    "number_of_trades",
)

type JsonValue = str | int | bool | None | tuple[JsonValue, ...] | dict[str, JsonValue]


class ComparisonCompatibilityStatus(StrEnum):
    """Compatibility classifications for two validated report cards."""

    STRICT_COMPATIBLE = "STRICT_COMPATIBLE"
    CONTEXT_COMPATIBLE = "CONTEXT_COMPATIBLE"
    INCOMPATIBLE = "INCOMPATIBLE"


class ComparisonDifferenceCode(StrEnum):
    """Stable difference codes for comparison compatibility assessments."""

    SCHEMA_VERSION_MISMATCH = "SCHEMA_VERSION_MISMATCH"
    DERIVATION_POLICY_MISMATCH = "DERIVATION_POLICY_MISMATCH"
    ASSET_CLASS_MISMATCH = "ASSET_CLASS_MISMATCH"
    ASSET_UNIVERSE_ID_MISMATCH = "ASSET_UNIVERSE_ID_MISMATCH"
    ASSET_UNIVERSE_SYMBOLS_MISMATCH = "ASSET_UNIVERSE_SYMBOLS_MISMATCH"
    DATE_RANGE_MISMATCH = "DATE_RANGE_MISMATCH"
    FREQUENCY_MISMATCH = "FREQUENCY_MISMATCH"
    OBSERVATION_COUNT_MISMATCH = "OBSERVATION_COUNT_MISMATCH"
    DATA_SNAPSHOT_ID_MISMATCH = "DATA_SNAPSHOT_ID_MISMATCH"
    DATA_SNAPSHOT_HASH_MISMATCH = "DATA_SNAPSHOT_HASH_MISMATCH"
    BENCHMARK_ID_MISMATCH = "BENCHMARK_ID_MISMATCH"
    BENCHMARK_SNAPSHOT_ID_MISMATCH = "BENCHMARK_SNAPSHOT_ID_MISMATCH"
    BENCHMARK_SNAPSHOT_HASH_MISMATCH = "BENCHMARK_SNAPSHOT_HASH_MISMATCH"
    BENCHMARK_TOTAL_RETURN_MISMATCH = "BENCHMARK_TOTAL_RETURN_MISMATCH"
    COST_MODEL_MISMATCH = "COST_MODEL_MISMATCH"
    SLIPPAGE_MODEL_MISMATCH = "SLIPPAGE_MODEL_MISMATCH"
    LOOKBACK_MISMATCH = "LOOKBACK_MISMATCH"
    LAG_ASSUMPTIONS_MISMATCH = "LAG_ASSUMPTIONS_MISMATCH"
    LEAKAGE_REVIEW_MISMATCH = "LEAKAGE_REVIEW_MISMATCH"
    RANDOM_SEED_MISMATCH = "RANDOM_SEED_MISMATCH"
    ADJUSTMENT_POLICY_MISMATCH = "ADJUSTMENT_POLICY_MISMATCH"
    TEMPORAL_COVERAGE_MISMATCH = "TEMPORAL_COVERAGE_MISMATCH"
    CORPORATE_ACTION_POLICY_MISMATCH = "CORPORATE_ACTION_POLICY_MISMATCH"
    SURVIVORSHIP_POLICY_MISMATCH = "SURVIVORSHIP_POLICY_MISMATCH"
    UNIVERSE_MEMBERSHIP_POLICY_MISMATCH = "UNIVERSE_MEMBERSHIP_POLICY_MISMATCH"
    CALENDAR_MISMATCH = "CALENDAR_MISMATCH"
    TIMEZONE_MISMATCH = "TIMEZONE_MISMATCH"
    ENGINE_VERSION_MISMATCH = "ENGINE_VERSION_MISMATCH"
    GIT_COMMIT_MISMATCH = "GIT_COMMIT_MISMATCH"
    SOURCE_LIMITATIONS_MISMATCH = "SOURCE_LIMITATIONS_MISMATCH"
    USE_RESTRICTIONS_MISMATCH = "USE_RESTRICTIONS_MISMATCH"
    STRATEGY_ID_DIFFERENCE = "STRATEGY_ID_DIFFERENCE"
    STRATEGY_VERSION_DIFFERENCE = "STRATEGY_VERSION_DIFFERENCE"
    CONFIG_HASH_DIFFERENCE = "CONFIG_HASH_DIFFERENCE"
    PARAMETER_HASH_DIFFERENCE = "PARAMETER_HASH_DIFFERENCE"


REQUIRED_CONTEXT_DIFFERENCE_CODE_PATHS: Final = (
    (ComparisonDifferenceCode.SCHEMA_VERSION_MISMATCH, "schema_version"),
    (
        ComparisonDifferenceCode.DERIVATION_POLICY_MISMATCH,
        "derivation_policy_version",
    ),
    (ComparisonDifferenceCode.ASSET_CLASS_MISMATCH, "research_scope.asset_class"),
    (
        ComparisonDifferenceCode.ASSET_UNIVERSE_ID_MISMATCH,
        "research_scope.asset_universe.universe_id",
    ),
    (
        ComparisonDifferenceCode.ASSET_UNIVERSE_SYMBOLS_MISMATCH,
        "research_scope.asset_universe.symbols",
    ),
    (ComparisonDifferenceCode.DATE_RANGE_MISMATCH, "research_scope.date_range"),
    (ComparisonDifferenceCode.FREQUENCY_MISMATCH, "research_scope.frequency"),
    (
        ComparisonDifferenceCode.OBSERVATION_COUNT_MISMATCH,
        "research_scope.observation_count",
    ),
    (ComparisonDifferenceCode.DATA_SNAPSHOT_ID_MISMATCH, "lineage.data_snapshot_id"),
    (
        ComparisonDifferenceCode.DATA_SNAPSHOT_HASH_MISMATCH,
        "lineage.data_snapshot_content_hash",
    ),
    (ComparisonDifferenceCode.BENCHMARK_ID_MISMATCH, "research_scope.benchmark_id"),
    (
        ComparisonDifferenceCode.BENCHMARK_SNAPSHOT_ID_MISMATCH,
        "lineage.benchmark_snapshot_id",
    ),
    (
        ComparisonDifferenceCode.BENCHMARK_SNAPSHOT_HASH_MISMATCH,
        "lineage.benchmark_snapshot_content_hash",
    ),
    (
        ComparisonDifferenceCode.BENCHMARK_TOTAL_RETURN_MISMATCH,
        "metrics.benchmark_total_return",
    ),
    (ComparisonDifferenceCode.COST_MODEL_MISMATCH, "assumptions.cost_model"),
    (ComparisonDifferenceCode.SLIPPAGE_MODEL_MISMATCH, "assumptions.slippage_model"),
    (ComparisonDifferenceCode.LOOKBACK_MISMATCH, "assumptions.lookback"),
    (ComparisonDifferenceCode.LAG_ASSUMPTIONS_MISMATCH, "assumptions.lag_assumptions"),
    (ComparisonDifferenceCode.LEAKAGE_REVIEW_MISMATCH, "assumptions.leakage_review"),
    (ComparisonDifferenceCode.RANDOM_SEED_MISMATCH, "assumptions.random_seed"),
    (
        ComparisonDifferenceCode.ADJUSTMENT_POLICY_MISMATCH,
        "assumptions.adjustment_policy",
    ),
    (
        ComparisonDifferenceCode.TEMPORAL_COVERAGE_MISMATCH,
        "assumptions.temporal_coverage",
    ),
    (
        ComparisonDifferenceCode.CORPORATE_ACTION_POLICY_MISMATCH,
        "assumptions.corporate_action_policy",
    ),
    (
        ComparisonDifferenceCode.SURVIVORSHIP_POLICY_MISMATCH,
        "assumptions.survivorship_policy",
    ),
    (
        ComparisonDifferenceCode.UNIVERSE_MEMBERSHIP_POLICY_MISMATCH,
        "assumptions.universe_membership_policy",
    ),
    (ComparisonDifferenceCode.CALENDAR_MISMATCH, "assumptions.calendar"),
    (ComparisonDifferenceCode.TIMEZONE_MISMATCH, "assumptions.timezone"),
    (ComparisonDifferenceCode.ENGINE_VERSION_MISMATCH, "lineage.engine_version"),
    (ComparisonDifferenceCode.GIT_COMMIT_MISMATCH, "lineage.git_commit_sha"),
    (
        ComparisonDifferenceCode.SOURCE_LIMITATIONS_MISMATCH,
        "limitations.source_snapshot_known_limitations",
    ),
    (ComparisonDifferenceCode.USE_RESTRICTIONS_MISMATCH, "use_restrictions"),
)
OBSERVED_LINEAGE_DIFFERENCE_CODE_PATHS: Final = (
    (ComparisonDifferenceCode.STRATEGY_ID_DIFFERENCE, "lineage.strategy_id"),
    (ComparisonDifferenceCode.STRATEGY_VERSION_DIFFERENCE, "lineage.strategy_version"),
    (ComparisonDifferenceCode.CONFIG_HASH_DIFFERENCE, "lineage.config_hash"),
    (ComparisonDifferenceCode.PARAMETER_HASH_DIFFERENCE, "lineage.parameter_hash"),
)
COMPARISON_DIFFERENCE_FIELD_PATH_BY_CODE: Final = {
    code: field_path
    for code, field_path in (
        *REQUIRED_CONTEXT_DIFFERENCE_CODE_PATHS,
        *OBSERVED_LINEAGE_DIFFERENCE_CODE_PATHS,
    )
}
_REQUIRED_CONTEXT_CODE_ORDER: Final = {
    code: index
    for index, (code, _) in enumerate(REQUIRED_CONTEXT_DIFFERENCE_CODE_PATHS)
}
_OBSERVED_LINEAGE_CODE_ORDER: Final = {
    code: index
    for index, (code, _) in enumerate(OBSERVED_LINEAGE_DIFFERENCE_CODE_PATHS)
}


class ReportCardComparisonMetricName(StrEnum):
    """Metric names supported by comparison metrics-v1."""

    TOTAL_RETURN = "total_return"
    EXCESS_RETURN = "excess_return"
    MAXIMUM_DRAWDOWN = "maximum_drawdown"
    NUMBER_OF_TRADES = "number_of_trades"


class ReportCardComparisonMetricUnit(StrEnum):
    """Deterministic units for comparison metrics."""

    RATIO = "ratio"
    COUNT = "count"


class ComparisonDifference(BaseContractModel):
    """One deterministic field difference between baseline and candidate cards."""

    code: ComparisonDifferenceCode
    field_path: NonEmptyString
    baseline_value: JsonValue
    candidate_value: JsonValue

    @field_validator("baseline_value", "candidate_value", mode="before")
    @classmethod
    def validate_json_safe_value(cls, value: object) -> JsonValue:
        """Accept only deterministic JSON-safe difference values."""

        return _json_safe_value(value)

    @model_validator(mode="after")
    def validate_difference_field_path(self) -> Self:
        """Require the canonical field path for each stable difference code."""

        expected = COMPARISON_DIFFERENCE_FIELD_PATH_BY_CODE[self.code]
        if self.field_path != expected:
            raise ValueError(f"{self.code} requires field_path {expected}")
        return self


class ReportCardCompatibilityAssessment(BaseContractModel):
    """Compatibility assessment for two report-card contracts."""

    compatibility_policy_version: NonEmptyString
    status: ComparisonCompatibilityStatus
    required_context_differences: tuple[ComparisonDifference, ...] = ()
    observed_lineage_differences: tuple[ComparisonDifference, ...] = ()

    @field_validator("compatibility_policy_version")
    @classmethod
    def validate_compatibility_policy_version(cls, value: str) -> str:
        """Require the supported C2a compatibility policy."""

        if value != REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION:
            raise ValueError("unsupported compatibility policy version")
        return value

    @model_validator(mode="after")
    def validate_assessment_consistency(self) -> Self:
        """Reject contradictory compatibility-assessment states."""

        _reject_duplicate_differences(
            self.required_context_differences,
            "required_context_differences",
        )
        _reject_duplicate_differences(
            self.observed_lineage_differences,
            "observed_lineage_differences",
        )
        _validate_canonical_difference_category_and_order(
            differences=self.required_context_differences,
            canonical_order=_REQUIRED_CONTEXT_CODE_ORDER,
            field_name="required_context_differences",
        )
        _validate_canonical_difference_category_and_order(
            differences=self.observed_lineage_differences,
            canonical_order=_OBSERVED_LINEAGE_CODE_ORDER,
            field_name="observed_lineage_differences",
        )
        if self.status is ComparisonCompatibilityStatus.STRICT_COMPATIBLE:
            if self.required_context_differences or self.observed_lineage_differences:
                raise ValueError(
                    "STRICT_COMPATIBLE requires no required or observed differences"
                )
        elif self.status is ComparisonCompatibilityStatus.CONTEXT_COMPATIBLE:
            if self.required_context_differences:
                raise ValueError(
                    "CONTEXT_COMPATIBLE requires no required context differences"
                )
            if not self.observed_lineage_differences:
                raise ValueError(
                    "CONTEXT_COMPATIBLE requires observed lineage differences"
                )
        elif self.status is ComparisonCompatibilityStatus.INCOMPATIBLE:
            if not self.required_context_differences:
                raise ValueError("INCOMPATIBLE requires required context differences")
        return self


class ReportCardMetricComparison(BaseContractModel):
    """Deterministic baseline/candidate/delta fact for one metric."""

    metric_name: ReportCardComparisonMetricName
    unit: ReportCardComparisonMetricUnit
    scale: int = Field(ge=0)
    baseline_value: NonEmptyString | int
    candidate_value: NonEmptyString | int
    delta: NonEmptyString | int

    @field_validator("baseline_value", "candidate_value", "delta", mode="before")
    @classmethod
    def reject_bool_metric_values(cls, value: object) -> object:
        """Reject bools before Pydantic can treat them as integers."""

        if isinstance(value, bool):
            raise ValueError("metric values must not be booleans")
        return value

    @model_validator(mode="after")
    def validate_metric_representation(self) -> Self:
        """Require metric-specific unit, scale, and value representation."""

        if self.metric_name in {
            ReportCardComparisonMetricName.TOTAL_RETURN,
            ReportCardComparisonMetricName.EXCESS_RETURN,
            ReportCardComparisonMetricName.MAXIMUM_DRAWDOWN,
        }:
            if self.unit is not ReportCardComparisonMetricUnit.RATIO:
                raise ValueError("ratio metrics require ratio unit")
            if self.scale != RATIO_COMPARISON_SCALE:
                raise ValueError("ratio metrics require scale 12")
            for field_name in ("baseline_value", "candidate_value", "delta"):
                _validate_ratio_decimal_string(getattr(self, field_name), field_name)
            _validate_ratio_metric_arithmetic(
                metric_name=self.metric_name,
                baseline_value=self.baseline_value,
                candidate_value=self.candidate_value,
                delta=self.delta,
            )
        elif self.metric_name is ReportCardComparisonMetricName.NUMBER_OF_TRADES:
            if self.unit is not ReportCardComparisonMetricUnit.COUNT:
                raise ValueError("number_of_trades requires count unit")
            if self.scale != 0:
                raise ValueError("number_of_trades requires scale 0")
            for field_name in ("baseline_value", "candidate_value", "delta"):
                _validate_count_integer(getattr(self, field_name), field_name)
            _validate_count_metric_arithmetic(
                baseline_value=self.baseline_value,
                candidate_value=self.candidate_value,
                delta=self.delta,
            )
        return self


class ResearchReportCardComparison(BaseContractModel):
    """Pure deterministic comparison of two compatible report cards."""

    comparison_id: NonEmptyString
    schema_version: NonEmptyString
    compatibility_policy_version: NonEmptyString
    metric_policy_version: NonEmptyString
    baseline_report_card_id: NonEmptyString
    candidate_report_card_id: NonEmptyString
    compatibility: ReportCardCompatibilityAssessment
    metric_comparisons: tuple[ReportCardMetricComparison, ...]
    limitations: tuple[NonEmptyString, ...] = Field(min_length=1)
    use_restrictions: tuple[ReportCardUseRestriction, ...] = Field(min_length=1)

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        """Require the current pure comparison schema version."""

        if value != REPORT_CARD_COMPARISON_SCHEMA_VERSION:
            raise ValueError("unsupported comparison schema version")
        return value

    @field_validator("compatibility_policy_version")
    @classmethod
    def validate_compatibility_policy_version(cls, value: str) -> str:
        """Require the supported C2a compatibility policy."""

        if value != REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION:
            raise ValueError("unsupported compatibility policy version")
        return value

    @field_validator("metric_policy_version")
    @classmethod
    def validate_metric_policy_version(cls, value: str) -> str:
        """Require the supported C2a metric policy."""

        if value != REPORT_CARD_COMPARISON_METRIC_POLICY_VERSION:
            raise ValueError("unsupported metric policy version")
        return value

    @field_validator("use_restrictions")
    @classmethod
    def normalize_use_restrictions(
        cls,
        value: tuple[ReportCardUseRestriction, ...],
    ) -> tuple[ReportCardUseRestriction, ...]:
        """Normalize restrictions as deterministic set-like metadata."""

        if len(set(value)) != len(value):
            raise ValueError("use_restrictions values must be unique")
        return tuple(sorted(value, key=lambda restriction: restriction.value))

    @model_validator(mode="after")
    def validate_comparison_invariants(self) -> Self:
        """Require canonical metric set and compatible assessment state."""

        _validate_comparison_id_shape(self.comparison_id)
        if self.compatibility.status is ComparisonCompatibilityStatus.INCOMPATIBLE:
            raise ValueError("comparison cannot contain incompatible assessment")

        metric_names = tuple(metric.metric_name for metric in self.metric_comparisons)
        if len(set(metric_names)) != len(metric_names):
            raise ValueError("metric_comparisons must not contain duplicate metrics")
        expected_order = tuple(
            ReportCardComparisonMetricName(metric_name)
            for metric_name in _CANONICAL_METRIC_ORDER
        )
        if metric_names != expected_order:
            raise ValueError("metric_comparisons must use canonical metrics-v1 order")
        return self


def _json_safe_value(value: object) -> JsonValue:
    if value is None:
        return None
    if isinstance(value, str | int | bool):
        return value
    if isinstance(value, list | tuple):
        return tuple(_json_safe_value(item) for item in value)
    if isinstance(value, dict):
        normalized: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            normalized[key] = _json_safe_value(item)
        return normalized
    raise ValueError("difference values must be JSON-safe")


def _reject_duplicate_differences(
    differences: tuple[ComparisonDifference, ...],
    field_name: str,
) -> None:
    codes = [difference.code for difference in differences]
    if len(set(codes)) != len(codes):
        raise ValueError(f"{field_name} must not contain duplicate codes")
    field_paths = [difference.field_path for difference in differences]
    if len(set(field_paths)) != len(field_paths):
        raise ValueError(f"{field_name} must not contain duplicate field paths")


def _validate_canonical_difference_category_and_order(
    *,
    differences: tuple[ComparisonDifference, ...],
    canonical_order: dict[ComparisonDifferenceCode, int],
    field_name: str,
) -> None:
    indexes: list[int] = []
    for difference in differences:
        index = canonical_order.get(difference.code)
        if index is None:
            raise ValueError(f"{field_name} contains unsupported difference code")
        indexes.append(index)
    if indexes != sorted(indexes):
        raise ValueError(f"{field_name} must use canonical difference order")


def _validate_ratio_decimal_string(value: object, field_name: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a canonical ratio decimal string")
    if _RATIO_DECIMAL_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a canonical 12-place decimal string")
    parsed = Decimal(value)
    if not parsed.is_finite():
        raise ValueError(f"{field_name} must be finite")
    if value.startswith("-") and parsed == 0:
        raise ValueError(f"{field_name} must not use negative zero")


def _validate_count_integer(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer count")


def _validate_ratio_metric_arithmetic(
    *,
    metric_name: ReportCardComparisonMetricName,
    baseline_value: NonEmptyString | int,
    candidate_value: NonEmptyString | int,
    delta: NonEmptyString | int,
) -> None:
    baseline_decimal = Decimal(str(baseline_value))
    candidate_decimal = Decimal(str(candidate_value))
    delta_decimal = Decimal(str(delta))
    if metric_name is ReportCardComparisonMetricName.MAXIMUM_DRAWDOWN:
        if baseline_decimal > 0:
            raise ValueError("maximum_drawdown baseline_value must be nonpositive")
        if candidate_decimal > 0:
            raise ValueError("maximum_drawdown candidate_value must be nonpositive")
    expected_delta = (candidate_decimal - baseline_decimal).quantize(
        _RATIO_QUANT,
        rounding=ROUND_HALF_EVEN,
    )
    if expected_delta == 0:
        expected_delta = abs(expected_delta)
    if delta_decimal != expected_delta:
        raise ValueError(
            "ratio metric delta must equal candidate_value - baseline_value"
        )


def _validate_count_metric_arithmetic(
    *,
    baseline_value: NonEmptyString | int,
    candidate_value: NonEmptyString | int,
    delta: NonEmptyString | int,
) -> None:
    if (
        not isinstance(baseline_value, int)
        or not isinstance(candidate_value, int)
        or not isinstance(delta, int)
    ):
        raise ValueError("number_of_trades values must be integer counts")
    if baseline_value < 0:
        raise ValueError("number_of_trades baseline_value must be nonnegative")
    if candidate_value < 0:
        raise ValueError("number_of_trades candidate_value must be nonnegative")
    if delta != candidate_value - baseline_value:
        raise ValueError(
            "count metric delta must equal candidate_value - baseline_value"
        )


def _validate_comparison_id_shape(comparison_id: str) -> None:
    if not comparison_id.startswith(REPORT_CARD_COMPARISON_ID_PREFIX):
        raise ValueError("comparison_id must use the report-card-comparison-v1- prefix")
    digest = comparison_id.removeprefix(REPORT_CARD_COMPARISON_ID_PREFIX)
    if len(digest) != REPORT_CARD_COMPARISON_DIGEST_LENGTH:
        raise ValueError("comparison_id must contain a full SHA-256 digest")
    if digest.lower() != digest or any(
        character not in _LOWER_HEX_DIGITS for character in digest
    ):
        raise ValueError("comparison_id digest must be lowercase hexadecimal")


__all__ = [
    "REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION",
    "REPORT_CARD_COMPARISON_DIGEST_LENGTH",
    "REPORT_CARD_COMPARISON_ID_PREFIX",
    "REPORT_CARD_COMPARISON_METRIC_POLICY_VERSION",
    "REPORT_CARD_COMPARISON_SCHEMA_VERSION",
    "RATIO_COMPARISON_SCALE",
    "COMPARISON_DIFFERENCE_FIELD_PATH_BY_CODE",
    "ComparisonCompatibilityStatus",
    "ComparisonDifference",
    "ComparisonDifferenceCode",
    "JsonValue",
    "OBSERVED_LINEAGE_DIFFERENCE_CODE_PATHS",
    "REQUIRED_CONTEXT_DIFFERENCE_CODE_PATHS",
    "ReportCardCompatibilityAssessment",
    "ReportCardComparisonMetricName",
    "ReportCardComparisonMetricUnit",
    "ReportCardMetricComparison",
    "ResearchReportCardComparison",
]
