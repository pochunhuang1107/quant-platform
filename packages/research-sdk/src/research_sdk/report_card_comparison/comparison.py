"""Pure deterministic comparison of already validated report cards."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from typing import Final

from pydantic import BaseModel

from research_sdk.contracts import ResearchReportCard
from research_sdk.report_card_comparison.identity import (
    derive_research_report_card_comparison_id,
    verify_research_report_card_comparison_identity,
)
from research_sdk.report_card_comparison.models import (
    COMPARISON_DIFFERENCE_FIELD_PATH_BY_CODE,
    OBSERVED_LINEAGE_DIFFERENCE_CODE_PATHS,
    RATIO_COMPARISON_SCALE,
    REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION,
    REPORT_CARD_COMPARISON_METRIC_POLICY_VERSION,
    REPORT_CARD_COMPARISON_SCHEMA_VERSION,
    REQUIRED_CONTEXT_DIFFERENCE_CODE_PATHS,
    ComparisonCompatibilityStatus,
    ComparisonDifference,
    ComparisonDifferenceCode,
    JsonValue,
    ReportCardComparisonMetricName,
    ReportCardComparisonMetricUnit,
    ReportCardCompatibilityAssessment,
    ReportCardMetricComparison,
    ResearchReportCardComparison,
)
from research_sdk.report_card_identity import (
    ResearchReportCardIdentityError,
    verify_research_report_card_identity,
)

_RATIO_QUANT: Final = Decimal("0.000000000001")
_COMPARISON_LIMITATIONS: Final = (
    "comparison reports deterministic evidence differences only",
    "comparison does not rank or select strategies",
    "comparison excludes annualized and risk-adjusted metrics",
    "context compatibility does not prove one-variable causal attribution",
)


class ResearchReportCardComparisonIncompatibilityError(ValueError):
    """Raised when required context differences prevent numeric comparison."""

    def __init__(self, assessment: ReportCardCompatibilityAssessment) -> None:
        super().__init__("report-card comparison context is incompatible")
        self.assessment = assessment


class ResearchReportCardComparisonInputIntegrityError(ValueError):
    """Raised when supplied report-card inputs are invalid evidence."""


@dataclass(frozen=True)
class _DifferenceSpec:
    code: ComparisonDifferenceCode
    value: Callable[[ResearchReportCard], object]


_REQUIRED_CONTEXT_SPECS: Final = (
    _DifferenceSpec(
        ComparisonDifferenceCode.SCHEMA_VERSION_MISMATCH,
        lambda card: card.schema_version,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.DERIVATION_POLICY_MISMATCH,
        lambda card: card.derivation_policy_version,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.ASSET_CLASS_MISMATCH,
        lambda card: card.research_scope.asset_class,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.ASSET_UNIVERSE_ID_MISMATCH,
        lambda card: card.research_scope.asset_universe.universe_id,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.ASSET_UNIVERSE_SYMBOLS_MISMATCH,
        lambda card: card.research_scope.asset_universe.symbols,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.DATE_RANGE_MISMATCH,
        lambda card: {
            "start_date": card.research_scope.start_date,
            "end_date": card.research_scope.end_date,
        },
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.FREQUENCY_MISMATCH,
        lambda card: card.research_scope.frequency,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.OBSERVATION_COUNT_MISMATCH,
        lambda card: card.research_scope.observation_count,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.DATA_SNAPSHOT_ID_MISMATCH,
        lambda card: card.lineage.data_snapshot_id,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.DATA_SNAPSHOT_HASH_MISMATCH,
        lambda card: card.lineage.data_snapshot_content_hash,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.BENCHMARK_ID_MISMATCH,
        lambda card: card.research_scope.benchmark_id,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.BENCHMARK_SNAPSHOT_ID_MISMATCH,
        lambda card: card.lineage.benchmark_snapshot_id,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.BENCHMARK_SNAPSHOT_HASH_MISMATCH,
        lambda card: card.lineage.benchmark_snapshot_content_hash,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.BENCHMARK_TOTAL_RETURN_MISMATCH,
        lambda card: card.metrics.benchmark_total_return,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.COST_MODEL_MISMATCH,
        lambda card: card.assumptions.cost_model,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.SLIPPAGE_MODEL_MISMATCH,
        lambda card: card.assumptions.slippage_model,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.LOOKBACK_MISMATCH,
        lambda card: card.assumptions.lookback,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.LAG_ASSUMPTIONS_MISMATCH,
        lambda card: card.assumptions.lag_assumptions,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.LEAKAGE_REVIEW_MISMATCH,
        lambda card: card.assumptions.leakage_review,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.RANDOM_SEED_MISMATCH,
        lambda card: card.assumptions.random_seed,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.ADJUSTMENT_POLICY_MISMATCH,
        lambda card: card.assumptions.adjustment_policy,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.TEMPORAL_COVERAGE_MISMATCH,
        lambda card: card.assumptions.temporal_coverage,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.CORPORATE_ACTION_POLICY_MISMATCH,
        lambda card: card.assumptions.corporate_action_policy,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.SURVIVORSHIP_POLICY_MISMATCH,
        lambda card: card.assumptions.survivorship_policy,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.UNIVERSE_MEMBERSHIP_POLICY_MISMATCH,
        lambda card: card.assumptions.universe_membership_policy,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.CALENDAR_MISMATCH,
        lambda card: card.assumptions.calendar,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.TIMEZONE_MISMATCH,
        lambda card: card.assumptions.timezone,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.ENGINE_VERSION_MISMATCH,
        lambda card: card.lineage.engine_version,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.GIT_COMMIT_MISMATCH,
        lambda card: card.lineage.git_commit_sha,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.SOURCE_LIMITATIONS_MISMATCH,
        lambda card: card.limitations.source_snapshot_known_limitations,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.USE_RESTRICTIONS_MISMATCH,
        lambda card: card.use_restrictions,
    ),
)

_OBSERVED_LINEAGE_SPECS: Final = (
    _DifferenceSpec(
        ComparisonDifferenceCode.STRATEGY_ID_DIFFERENCE,
        lambda card: card.lineage.strategy_id,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.STRATEGY_VERSION_DIFFERENCE,
        lambda card: card.lineage.strategy_version,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.CONFIG_HASH_DIFFERENCE,
        lambda card: card.lineage.config_hash,
    ),
    _DifferenceSpec(
        ComparisonDifferenceCode.PARAMETER_HASH_DIFFERENCE,
        lambda card: card.lineage.parameter_hash,
    ),
)
_REQUIRED_CONTEXT_SPEC_CODES: Final = tuple(
    spec.code for spec in _REQUIRED_CONTEXT_SPECS
)
_OBSERVED_LINEAGE_SPEC_CODES: Final = tuple(
    spec.code for spec in _OBSERVED_LINEAGE_SPECS
)
if _REQUIRED_CONTEXT_SPEC_CODES != tuple(
    code for code, _ in REQUIRED_CONTEXT_DIFFERENCE_CODE_PATHS
):
    raise RuntimeError("required context difference specs must use canonical order")
if _OBSERVED_LINEAGE_SPEC_CODES != tuple(
    code for code, _ in OBSERVED_LINEAGE_DIFFERENCE_CODE_PATHS
):
    raise RuntimeError("observed lineage difference specs must use canonical order")


def assess_research_report_card_compatibility(
    *,
    baseline: ResearchReportCard,
    candidate: ResearchReportCard,
) -> ReportCardCompatibilityAssessment:
    """Assess C2a compatibility without producing numeric metric deltas."""

    baseline, candidate = _validate_comparison_inputs(
        baseline=baseline,
        candidate=candidate,
    )
    return _assess_validated_report_cards(baseline=baseline, candidate=candidate)


def _assess_validated_report_cards(
    *,
    baseline: ResearchReportCard,
    candidate: ResearchReportCard,
) -> ReportCardCompatibilityAssessment:
    required_context_differences = _collect_differences(
        baseline=baseline,
        candidate=candidate,
        specs=_REQUIRED_CONTEXT_SPECS,
    )
    observed_lineage_differences = _collect_differences(
        baseline=baseline,
        candidate=candidate,
        specs=_OBSERVED_LINEAGE_SPECS,
    )
    if required_context_differences:
        status = ComparisonCompatibilityStatus.INCOMPATIBLE
    elif observed_lineage_differences:
        status = ComparisonCompatibilityStatus.CONTEXT_COMPATIBLE
    else:
        status = ComparisonCompatibilityStatus.STRICT_COMPATIBLE
    return ReportCardCompatibilityAssessment(
        compatibility_policy_version=REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION,
        status=status,
        required_context_differences=required_context_differences,
        observed_lineage_differences=observed_lineage_differences,
    )


def compare_research_report_cards(
    *,
    baseline: ResearchReportCard,
    candidate: ResearchReportCard,
) -> ResearchReportCardComparison:
    """Build a deterministic two-report-card comparison."""

    baseline, candidate = _validate_comparison_inputs(
        baseline=baseline,
        candidate=candidate,
    )
    assessment = _assess_validated_report_cards(baseline=baseline, candidate=candidate)
    if assessment.status is ComparisonCompatibilityStatus.INCOMPATIBLE:
        raise ResearchReportCardComparisonIncompatibilityError(assessment)

    comparison_id = derive_research_report_card_comparison_id(
        schema_version=REPORT_CARD_COMPARISON_SCHEMA_VERSION,
        compatibility_policy_version=REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION,
        metric_policy_version=REPORT_CARD_COMPARISON_METRIC_POLICY_VERSION,
        baseline_report_card_id=baseline.report_card_id,
        candidate_report_card_id=candidate.report_card_id,
    )
    comparison = ResearchReportCardComparison(
        comparison_id=comparison_id,
        schema_version=REPORT_CARD_COMPARISON_SCHEMA_VERSION,
        compatibility_policy_version=REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION,
        metric_policy_version=REPORT_CARD_COMPARISON_METRIC_POLICY_VERSION,
        baseline_report_card_id=baseline.report_card_id,
        candidate_report_card_id=candidate.report_card_id,
        compatibility=assessment,
        metric_comparisons=_build_metric_comparisons(
            baseline=baseline,
            candidate=candidate,
        ),
        limitations=_COMPARISON_LIMITATIONS,
        use_restrictions=baseline.use_restrictions,
    )
    verify_research_report_card_comparison_identity(comparison)
    return comparison


def _collect_differences(
    *,
    baseline: ResearchReportCard,
    candidate: ResearchReportCard,
    specs: tuple[_DifferenceSpec, ...],
) -> tuple[ComparisonDifference, ...]:
    differences: list[ComparisonDifference] = []
    for spec in specs:
        baseline_value = spec.value(baseline)
        candidate_value = spec.value(candidate)
        if baseline_value != candidate_value:
            differences.append(
                ComparisonDifference(
                    code=spec.code,
                    field_path=COMPARISON_DIFFERENCE_FIELD_PATH_BY_CODE[spec.code],
                    baseline_value=_json_value(baseline_value),
                    candidate_value=_json_value(candidate_value),
                )
            )
    return tuple(differences)


def _build_metric_comparisons(
    *,
    baseline: ResearchReportCard,
    candidate: ResearchReportCard,
) -> tuple[ReportCardMetricComparison, ...]:
    return (
        _ratio_metric_comparison(
            metric_name=ReportCardComparisonMetricName.TOTAL_RETURN,
            baseline_value=baseline.metrics.total_return,
            candidate_value=candidate.metrics.total_return,
        ),
        _ratio_metric_comparison(
            metric_name=ReportCardComparisonMetricName.EXCESS_RETURN,
            baseline_value=baseline.metrics.excess_return,
            candidate_value=candidate.metrics.excess_return,
        ),
        _ratio_metric_comparison(
            metric_name=ReportCardComparisonMetricName.MAXIMUM_DRAWDOWN,
            baseline_value=baseline.metrics.maximum_drawdown,
            candidate_value=candidate.metrics.maximum_drawdown,
        ),
        ReportCardMetricComparison(
            metric_name=ReportCardComparisonMetricName.NUMBER_OF_TRADES,
            unit=ReportCardComparisonMetricUnit.COUNT,
            scale=0,
            baseline_value=baseline.metrics.number_of_trades,
            candidate_value=candidate.metrics.number_of_trades,
            delta=candidate.metrics.number_of_trades
            - baseline.metrics.number_of_trades,
        ),
    )


def _ratio_metric_comparison(
    *,
    metric_name: ReportCardComparisonMetricName,
    baseline_value: str,
    candidate_value: str,
) -> ReportCardMetricComparison:
    return ReportCardMetricComparison(
        metric_name=metric_name,
        unit=ReportCardComparisonMetricUnit.RATIO,
        scale=RATIO_COMPARISON_SCALE,
        baseline_value=baseline_value,
        candidate_value=candidate_value,
        delta=_decimal_delta(
            baseline_value=baseline_value,
            candidate_value=candidate_value,
        ),
    )


def _decimal_delta(*, baseline_value: str, candidate_value: str) -> str:
    delta = (Decimal(candidate_value) - Decimal(baseline_value)).quantize(
        _RATIO_QUANT,
        rounding=ROUND_HALF_EVEN,
    )
    if delta == 0:
        delta = abs(delta)
    return f"{delta:.{RATIO_COMPARISON_SCALE}f}"


def _json_value(value: object) -> JsonValue:
    if isinstance(value, BaseModel):
        return _json_value(value.model_dump(mode="json"))
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return tuple(_json_value(item) for item in value)
    if isinstance(value, list):
        return tuple(_json_value(item) for item in value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if value is None or isinstance(value, str | int | bool):
        return value
    raise TypeError("difference values must be JSON-safe")


def _validate_comparison_inputs(
    *,
    baseline: ResearchReportCard,
    candidate: ResearchReportCard,
) -> tuple[ResearchReportCard, ResearchReportCard]:
    validated_baseline = _canonical_validated_report_card(baseline, "baseline")
    validated_candidate = _canonical_validated_report_card(candidate, "candidate")
    if (
        validated_baseline.report_card_id == validated_candidate.report_card_id
        and validated_baseline != validated_candidate
    ):
        raise ResearchReportCardComparisonInputIntegrityError(
            "same report_card_id cannot represent different report-card contracts"
        )
    return validated_baseline, validated_candidate


def _canonical_validated_report_card(
    value: object,
    argument_name: str,
) -> ResearchReportCard:
    if not isinstance(value, ResearchReportCard):
        raise ResearchReportCardComparisonInputIntegrityError(
            f"{argument_name} must be a ResearchReportCard"
        )
    try:
        validated = ResearchReportCard.model_validate(value.model_dump(mode="json"))
        verify_research_report_card_identity(validated)
    except ResearchReportCardIdentityError as exc:
        raise ResearchReportCardComparisonInputIntegrityError(
            f"{argument_name} report-card identity is invalid"
        ) from exc
    except Exception as exc:
        raise ResearchReportCardComparisonInputIntegrityError(
            f"{argument_name} report-card contract is invalid"
        ) from exc
    return validated


__all__ = [
    "ResearchReportCardComparisonInputIntegrityError",
    "ResearchReportCardComparisonIncompatibilityError",
    "assess_research_report_card_compatibility",
    "compare_research_report_cards",
]
