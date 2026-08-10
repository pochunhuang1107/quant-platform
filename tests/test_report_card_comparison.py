from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from research_sdk.contracts import (
    AssetClass,
    AssetUniverseReference,
    DataAdjustmentPolicy,
    RandomSeedMetadata,
    ReportCardUseRestriction,
    TemporalCoverage,
)
from research_sdk.report_card_comparison import (
    REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION,
    REPORT_CARD_COMPARISON_METRIC_POLICY_VERSION,
    REPORT_CARD_COMPARISON_SCHEMA_VERSION,
    ComparisonCompatibilityStatus,
    ComparisonDifference,
    ComparisonDifferenceCode,
    ReportCardComparisonMetricName,
    ReportCardComparisonMetricUnit,
    ReportCardCompatibilityAssessment,
    ReportCardMetricComparison,
    ResearchReportCardComparison,
    ResearchReportCardComparisonIncompatibilityError,
    ResearchReportCardComparisonInputIntegrityError,
    assess_research_report_card_compatibility,
    compare_research_report_cards,
)
from research_sdk.report_card_comparison.identity import (
    ResearchReportCardComparisonIdentityError,
    derive_research_report_card_comparison_id,
    verify_research_report_card_comparison_identity,
)
from research_sdk.report_card_comparison.models import (
    COMPARISON_DIFFERENCE_FIELD_PATH_BY_CODE,
)
from research_sdk.report_card_identity import derive_research_report_card_id_from_fields
from test_deterministic_etf_report_card import mapped_records, report_card_from_records


def test_comparison_identity_is_deterministic_and_directional(tmp_path: Path) -> None:
    baseline = report_card_from_records(mapped_records(tmp_path))
    candidate = _with_recomputed_report_card_id(
        _with_lineage_update(baseline, config_hash=_hash("9"))
    )

    forward = compare_research_report_cards(baseline=baseline, candidate=candidate)
    reverse = compare_research_report_cards(baseline=candidate, candidate=baseline)

    assert forward.comparison_id == derive_research_report_card_comparison_id(
        schema_version=REPORT_CARD_COMPARISON_SCHEMA_VERSION,
        compatibility_policy_version=(
            REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION
        ),
        metric_policy_version=REPORT_CARD_COMPARISON_METRIC_POLICY_VERSION,
        baseline_report_card_id=baseline.report_card_id,
        candidate_report_card_id=candidate.report_card_id,
    )
    assert forward.comparison_id != reverse.comparison_id
    verify_research_report_card_comparison_identity(forward)
    verify_research_report_card_comparison_identity(reverse)


def test_comparison_identity_golden_id_stays_stable() -> None:
    baseline_report_card_id = "report-card-" + ("1" * 64)
    candidate_report_card_id = "report-card-" + ("2" * 64)

    comparison_id = derive_research_report_card_comparison_id(
        schema_version=REPORT_CARD_COMPARISON_SCHEMA_VERSION,
        compatibility_policy_version=(
            REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION
        ),
        metric_policy_version=REPORT_CARD_COMPARISON_METRIC_POLICY_VERSION,
        baseline_report_card_id=baseline_report_card_id,
        candidate_report_card_id=candidate_report_card_id,
    )

    assert comparison_id == (
        "report-card-comparison-v1-"
        "28eb0afd52ee743cfc0163a6ce08034f40ce9a3f0d4f7742b32825bd04722e0c"
    )


def test_comparison_identity_derive_rejects_unsupported_schema() -> None:
    with pytest.raises(
        ResearchReportCardComparisonIdentityError,
        match="schema",
    ):
        derive_research_report_card_comparison_id(
            schema_version="2.0.0",
            compatibility_policy_version=(
                REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION
            ),
            metric_policy_version=REPORT_CARD_COMPARISON_METRIC_POLICY_VERSION,
            baseline_report_card_id="report-card-" + ("1" * 64),
            candidate_report_card_id="report-card-" + ("2" * 64),
        )


@pytest.mark.parametrize(
    "comparison_id",
    [
        "bad-prefix-" + ("a" * 64),
        "report-card-comparison-v1-" + ("a" * 63),
        "report-card-comparison-v1-" + ("A" * 64),
    ],
)
def test_comparison_identity_rejects_malformed_id(
    tmp_path: Path,
    comparison_id: str,
) -> None:
    report_card = report_card_from_records(mapped_records(tmp_path))
    comparison = compare_research_report_cards(
        baseline=report_card,
        candidate=report_card,
    ).model_copy(update={"comparison_id": comparison_id})

    with pytest.raises(ResearchReportCardComparisonIdentityError):
        verify_research_report_card_comparison_identity(comparison)


def test_comparison_identity_rejects_stale_digest(tmp_path: Path) -> None:
    report_card = report_card_from_records(mapped_records(tmp_path))
    comparison = compare_research_report_cards(
        baseline=report_card,
        candidate=report_card,
    ).model_copy(update={"comparison_id": "report-card-comparison-v1-" + ("9" * 64)})

    with pytest.raises(
        ResearchReportCardComparisonIdentityError,
        match="stale|inconsistent",
    ):
        verify_research_report_card_comparison_identity(comparison)


@pytest.mark.parametrize(
    "update",
    [
        {"schema_version": "2.0.0"},
        {"compatibility_policy_version": "future-compatibility-v2"},
        {"metric_policy_version": "future-metrics-v2"},
    ],
)
def test_comparison_identity_rejects_unsupported_policy_versions(
    tmp_path: Path,
    update: dict[str, str],
) -> None:
    report_card = report_card_from_records(mapped_records(tmp_path))
    valid_comparison = compare_research_report_cards(
        baseline=report_card,
        candidate=report_card,
    )
    comparison = valid_comparison.model_construct(
        **{**valid_comparison.model_dump(), **update}
    )

    with pytest.raises(
        ResearchReportCardComparisonIdentityError,
        match="unsupported",
    ):
        verify_research_report_card_comparison_identity(comparison)


def test_same_card_comparison_is_strict_with_zero_deltas(tmp_path: Path) -> None:
    report_card = report_card_from_records(mapped_records(tmp_path))

    comparison = compare_research_report_cards(
        baseline=report_card,
        candidate=report_card,
    )

    assert comparison.compatibility.status is (
        ComparisonCompatibilityStatus.STRICT_COMPATIBLE
    )
    assert comparison.compatibility.required_context_differences == ()
    assert comparison.compatibility.observed_lineage_differences == ()
    assert _metric_delta(comparison, "total_return") == "0.000000000000"
    assert _metric_delta(comparison, "excess_return") == "0.000000000000"
    assert _metric_delta(comparison, "maximum_drawdown") == "0.000000000000"
    assert _metric_delta(comparison, "number_of_trades") == 0


def test_valid_card_is_canonically_accepted(tmp_path: Path) -> None:
    report_card = report_card_from_records(mapped_records(tmp_path))

    comparison = compare_research_report_cards(
        baseline=report_card,
        candidate=report_card,
    )

    assert comparison.compatibility.status is (
        ComparisonCompatibilityStatus.STRICT_COMPATIBLE
    )


def test_stale_source_report_card_id_is_input_integrity_error(
    tmp_path: Path,
) -> None:
    baseline = report_card_from_records(mapped_records(tmp_path))
    candidate = baseline.model_copy(
        update={"report_card_id": "report-card-" + ("9" * 64)}
    )

    with pytest.raises(
        ResearchReportCardComparisonInputIntegrityError,
        match="identity",
    ):
        assess_research_report_card_compatibility(
            baseline=baseline,
            candidate=candidate,
        )


def test_malformed_source_report_card_id_is_input_integrity_error(
    tmp_path: Path,
) -> None:
    baseline = report_card_from_records(mapped_records(tmp_path))
    candidate = baseline.model_copy(update={"report_card_id": "report-card-short"})

    with pytest.raises(
        ResearchReportCardComparisonInputIntegrityError,
        match="identity|contract",
    ):
        compare_research_report_cards(baseline=baseline, candidate=candidate)


def test_invalid_identity_hash_is_input_integrity_error(tmp_path: Path) -> None:
    baseline = report_card_from_records(mapped_records(tmp_path))
    candidate = _with_lineage_update(baseline, config_hash="sha256:not-a-digest")

    with pytest.raises(
        ResearchReportCardComparisonInputIntegrityError,
        match="contract",
    ):
        compare_research_report_cards(baseline=baseline, candidate=candidate)


def test_canonical_revalidation_catches_model_copy_invalid_state(
    tmp_path: Path,
) -> None:
    baseline = report_card_from_records(mapped_records(tmp_path))
    candidate = _with_metrics_update(baseline, total_return="-0.000000000000")

    with pytest.raises(
        ResearchReportCardComparisonInputIntegrityError,
        match="contract",
    ):
        compare_research_report_cards(baseline=baseline, candidate=candidate)


def test_same_id_different_full_contract_is_input_integrity_error(
    tmp_path: Path,
) -> None:
    baseline = report_card_from_records(mapped_records(tmp_path))
    candidate = _with_metrics_update(baseline, total_return="0.039650280020")

    with pytest.raises(
        ResearchReportCardComparisonInputIntegrityError,
        match="same report_card_id",
    ):
        compare_research_report_cards(baseline=baseline, candidate=candidate)


def test_equivalent_reconstructed_card_is_strict_compatible(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    baseline = report_card_from_records(records)
    candidate = report_card_from_records(records)

    assessment = assess_research_report_card_compatibility(
        baseline=baseline,
        candidate=candidate,
    )

    assert assessment.status is ComparisonCompatibilityStatus.STRICT_COMPATIBLE


@pytest.mark.parametrize(
    ("field_name", "code"),
    [
        ("strategy_id", ComparisonDifferenceCode.STRATEGY_ID_DIFFERENCE),
        ("strategy_version", ComparisonDifferenceCode.STRATEGY_VERSION_DIFFERENCE),
        ("config_hash", ComparisonDifferenceCode.CONFIG_HASH_DIFFERENCE),
        ("parameter_hash", ComparisonDifferenceCode.PARAMETER_HASH_DIFFERENCE),
    ],
)
def test_observed_lineage_differences_are_context_compatible(
    tmp_path: Path,
    field_name: str,
    code: ComparisonDifferenceCode,
) -> None:
    baseline = report_card_from_records(mapped_records(tmp_path))
    candidate = _with_lineage_update(
        baseline,
        **{field_name: _lineage_value(field_name)},
    )
    candidate = _with_distinct_source_identity(candidate)

    assessment = assess_research_report_card_compatibility(
        baseline=baseline,
        candidate=candidate,
    )

    assert assessment.status is ComparisonCompatibilityStatus.CONTEXT_COMPATIBLE
    assert assessment.required_context_differences == ()
    assert [
        difference.code for difference in assessment.observed_lineage_differences
    ] == [code]


def test_asset_universe_as_of_difference_is_not_required_context(
    tmp_path: Path,
) -> None:
    baseline = report_card_from_records(mapped_records(tmp_path))
    changed_universe = baseline.research_scope.asset_universe.model_copy(
        update={"as_of": datetime(2026, 2, 7, tzinfo=UTC)}
    )
    candidate = _with_scope_update(
        baseline,
        asset_universe=changed_universe,
    )
    candidate = _with_distinct_source_identity(candidate)

    assessment = assess_research_report_card_compatibility(
        baseline=baseline,
        candidate=candidate,
    )

    assert assessment.status is ComparisonCompatibilityStatus.STRICT_COMPATIBLE
    assert assessment.required_context_differences == ()


@pytest.mark.parametrize(
    ("code", "mutator"),
    [
        (
            ComparisonDifferenceCode.SCHEMA_VERSION_MISMATCH,
            lambda card: _with_recomputed_report_card_id(
                card.model_copy(update={"schema_version": "2.0.0"})
            ),
        ),
        (
            ComparisonDifferenceCode.DERIVATION_POLICY_MISMATCH,
            lambda card: _with_recomputed_report_card_id(
                card.model_copy(update={"derivation_policy_version": "future-policy"})
            ),
        ),
        (
            ComparisonDifferenceCode.ASSET_CLASS_MISMATCH,
            lambda card: _with_scope_update(card, asset_class=AssetClass.EQUITIES),
        ),
        (
            ComparisonDifferenceCode.ASSET_UNIVERSE_ID_MISMATCH,
            lambda card: _with_scope_update(
                card,
                asset_universe=AssetUniverseReference(
                    universe_id="other-universe",
                    symbols=card.research_scope.asset_universe.symbols,
                    as_of=card.research_scope.asset_universe.as_of,
                ),
            ),
        ),
        (
            ComparisonDifferenceCode.ASSET_UNIVERSE_SYMBOLS_MISMATCH,
            lambda card: _with_scope_update(
                card,
                asset_universe=AssetUniverseReference(symbols=("IWM",)),
            ),
        ),
        (
            ComparisonDifferenceCode.DATE_RANGE_MISMATCH,
            lambda card: _with_scope_update(card, start_date=date(2026, 1, 30)),
        ),
        (
            ComparisonDifferenceCode.FREQUENCY_MISMATCH,
            lambda card: _with_scope_update(card, frequency="weekly"),
        ),
        (
            ComparisonDifferenceCode.OBSERVATION_COUNT_MISMATCH,
            lambda card: _with_metrics_update(
                _with_scope_update(card, observation_count=7),
                observation_count=7,
            ),
        ),
        (
            ComparisonDifferenceCode.DATA_SNAPSHOT_ID_MISMATCH,
            lambda card: _with_lineage_update(card, data_snapshot_id="other-snapshot"),
        ),
        (
            ComparisonDifferenceCode.DATA_SNAPSHOT_HASH_MISMATCH,
            lambda card: _with_recomputed_report_card_id(
                _with_lineage_update(card, data_snapshot_content_hash=_hash("8"))
            ),
        ),
        (
            ComparisonDifferenceCode.BENCHMARK_ID_MISMATCH,
            lambda card: _with_scope_update(card, benchmark_id="other-benchmark"),
        ),
        (
            ComparisonDifferenceCode.BENCHMARK_SNAPSHOT_ID_MISMATCH,
            lambda card: _with_lineage_update(
                card,
                benchmark_snapshot_id="other-benchmark-snapshot",
            ),
        ),
        (
            ComparisonDifferenceCode.BENCHMARK_SNAPSHOT_HASH_MISMATCH,
            lambda card: _with_recomputed_report_card_id(
                _with_lineage_update(card, benchmark_snapshot_content_hash=_hash("7"))
            ),
        ),
        (
            ComparisonDifferenceCode.BENCHMARK_TOTAL_RETURN_MISMATCH,
            lambda card: _with_metrics_update(
                card,
                benchmark_total_return="0.030000000000",
            ),
        ),
        (
            ComparisonDifferenceCode.COST_MODEL_MISMATCH,
            lambda card: _with_assumptions_update(card, cost_model="other cost"),
        ),
        (
            ComparisonDifferenceCode.SLIPPAGE_MODEL_MISMATCH,
            lambda card: _with_assumptions_update(card, slippage_model="other slip"),
        ),
        (
            ComparisonDifferenceCode.LOOKBACK_MISMATCH,
            lambda card: _with_assumptions_update(card, lookback="5 sessions"),
        ),
        (
            ComparisonDifferenceCode.LAG_ASSUMPTIONS_MISMATCH,
            lambda card: _with_assumptions_update(card, lag_assumptions="other lag"),
        ),
        (
            ComparisonDifferenceCode.LEAKAGE_REVIEW_MISMATCH,
            lambda card: _with_assumptions_update(card, leakage_review="other review"),
        ),
        (
            ComparisonDifferenceCode.RANDOM_SEED_MISMATCH,
            lambda card: _with_assumptions_update(
                card,
                random_seed=RandomSeedMetadata(seed=1, rationale=None),
            ),
        ),
        (
            ComparisonDifferenceCode.ADJUSTMENT_POLICY_MISMATCH,
            lambda card: _with_assumptions_update(
                card,
                adjustment_policy=DataAdjustmentPolicy.SPLIT_ADJUSTED,
            ),
        ),
        (
            ComparisonDifferenceCode.TEMPORAL_COVERAGE_MISMATCH,
            lambda card: _with_assumptions_update(
                card,
                temporal_coverage=TemporalCoverage.LATEST_KNOWN,
            ),
        ),
        (
            ComparisonDifferenceCode.CORPORATE_ACTION_POLICY_MISMATCH,
            lambda card: _with_assumptions_update(
                card,
                corporate_action_policy="other corporate action policy",
            ),
        ),
        (
            ComparisonDifferenceCode.SURVIVORSHIP_POLICY_MISMATCH,
            lambda card: _with_assumptions_update(
                card,
                survivorship_policy="other survivorship policy",
            ),
        ),
        (
            ComparisonDifferenceCode.UNIVERSE_MEMBERSHIP_POLICY_MISMATCH,
            lambda card: _with_assumptions_update(
                card,
                universe_membership_policy="other universe membership policy",
            ),
        ),
        (
            ComparisonDifferenceCode.CALENDAR_MISMATCH,
            lambda card: _with_assumptions_update(card, calendar="other calendar"),
        ),
        (
            ComparisonDifferenceCode.TIMEZONE_MISMATCH,
            lambda card: _with_assumptions_update(card, timezone="UTC"),
        ),
        (
            ComparisonDifferenceCode.ENGINE_VERSION_MISMATCH,
            lambda card: _with_lineage_update(card, engine_version="other-engine"),
        ),
        (
            ComparisonDifferenceCode.GIT_COMMIT_MISMATCH,
            lambda card: _with_lineage_update(card, git_commit_sha="other-git-sha"),
        ),
        (
            ComparisonDifferenceCode.SOURCE_LIMITATIONS_MISMATCH,
            lambda card: card.model_copy(
                update={
                    "limitations": card.limitations.model_copy(
                        update={
                            "source_snapshot_known_limitations": (
                                "different limitation",
                            )
                        }
                    )
                }
            ),
        ),
        (
            ComparisonDifferenceCode.USE_RESTRICTIONS_MISMATCH,
            lambda card: card.model_copy(
                update={
                    "use_restrictions": (
                        ReportCardUseRestriction.NO_INVESTMENT_PERFORMANCE_CLAIM,
                    )
                }
            ),
        ),
    ],
)
def test_required_context_difference_is_incompatible(
    tmp_path: Path,
    code: ComparisonDifferenceCode,
    mutator: object,
) -> None:
    baseline = report_card_from_records(mapped_records(tmp_path))
    candidate = _with_distinct_source_identity(mutator(baseline))  # type: ignore[operator]

    assessment = assess_research_report_card_compatibility(
        baseline=baseline,
        candidate=candidate,
    )

    assert assessment.status is ComparisonCompatibilityStatus.INCOMPATIBLE
    assert code in {
        difference.code for difference in assessment.required_context_differences
    }
    with pytest.raises(
        ResearchReportCardComparisonIncompatibilityError,
    ) as exc_info:
        compare_research_report_cards(baseline=baseline, candidate=candidate)
    assert exc_info.value.assessment == assessment


def test_metric_arithmetic_is_exact_decimal_and_directional(tmp_path: Path) -> None:
    baseline = report_card_from_records(mapped_records(tmp_path))
    candidate = _with_recomputed_report_card_id(
        _with_metrics_update(
            _with_lineage_update(baseline, config_hash=_hash("9")),
            total_return="0.039650280020",
            excess_return="0.034650280020",
            maximum_drawdown="-0.019797188585",
            number_of_trades=3,
        )
    )

    forward = compare_research_report_cards(baseline=baseline, candidate=candidate)
    reverse = compare_research_report_cards(baseline=candidate, candidate=baseline)

    assert _metric_delta(forward, "total_return") == "-0.010000000000"
    assert _metric_delta(forward, "excess_return") == "0.010000000000"
    assert _metric_delta(forward, "maximum_drawdown") == "-0.010000000000"
    assert _metric_delta(forward, "number_of_trades") == 2
    assert _metric_delta(reverse, "total_return") == "0.010000000000"
    assert _metric_delta(reverse, "excess_return") == "-0.010000000000"
    assert _metric_delta(reverse, "maximum_drawdown") == "0.010000000000"
    assert _metric_delta(reverse, "number_of_trades") == -2


def test_comparison_excludes_annualized_money_and_ranking_fields(
    tmp_path: Path,
) -> None:
    report_card = report_card_from_records(mapped_records(tmp_path))
    comparison = compare_research_report_cards(
        baseline=report_card,
        candidate=report_card,
    )

    metric_names = {
        metric.metric_name.value for metric in comparison.metric_comparisons
    }
    assert metric_names == {
        "total_return",
        "excess_return",
        "maximum_drawdown",
        "number_of_trades",
    }
    serialized = json.dumps(comparison.model_dump(mode="json"), sort_keys=True)
    for excluded in (
        "benchmark_total_return",
        "observation_count",
        "realized_commission",
        "realized_slippage",
        "ending_equity",
        "cagr",
        "sharpe",
        "volatility",
        "winner",
        "rank",
        "higher_is_better",
        "lower_is_better",
    ):
        _assert_no_key(json.loads(serialized), excluded)


def test_context_compatibility_limitation_is_explicit(tmp_path: Path) -> None:
    baseline = report_card_from_records(mapped_records(tmp_path))
    candidate = _with_recomputed_report_card_id(
        _with_lineage_update(baseline, parameter_hash=_hash("6"))
    )

    comparison = compare_research_report_cards(
        baseline=baseline,
        candidate=candidate,
    )

    assert comparison.compatibility.status is (
        ComparisonCompatibilityStatus.CONTEXT_COMPATIBLE
    )
    assert (
        "context compatibility does not prove one-variable causal attribution"
        in comparison.limitations
    )
    assert comparison.use_restrictions == baseline.use_restrictions


@pytest.mark.parametrize(
    "assessment",
    [
        lambda: ReportCardCompatibilityAssessment(
            compatibility_policy_version=(
                REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION
            ),
            status=ComparisonCompatibilityStatus.STRICT_COMPATIBLE,
            required_context_differences=(
                _difference(ComparisonDifferenceCode.FREQUENCY_MISMATCH),
            ),
        ),
        lambda: ReportCardCompatibilityAssessment(
            compatibility_policy_version=(
                REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION
            ),
            status=ComparisonCompatibilityStatus.STRICT_COMPATIBLE,
            observed_lineage_differences=(
                _difference(ComparisonDifferenceCode.STRATEGY_ID_DIFFERENCE),
            ),
        ),
        lambda: ReportCardCompatibilityAssessment(
            compatibility_policy_version=(
                REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION
            ),
            status=ComparisonCompatibilityStatus.CONTEXT_COMPATIBLE,
        ),
        lambda: ReportCardCompatibilityAssessment(
            compatibility_policy_version=(
                REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION
            ),
            status=ComparisonCompatibilityStatus.CONTEXT_COMPATIBLE,
            required_context_differences=(
                _difference(ComparisonDifferenceCode.FREQUENCY_MISMATCH),
            ),
            observed_lineage_differences=(
                _difference(ComparisonDifferenceCode.STRATEGY_ID_DIFFERENCE),
            ),
        ),
        lambda: ReportCardCompatibilityAssessment(
            compatibility_policy_version=(
                REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION
            ),
            status=ComparisonCompatibilityStatus.INCOMPATIBLE,
        ),
        lambda: ReportCardCompatibilityAssessment(
            compatibility_policy_version=(
                REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION
            ),
            status=ComparisonCompatibilityStatus.INCOMPATIBLE,
            required_context_differences=(
                _difference(ComparisonDifferenceCode.FREQUENCY_MISMATCH),
                _difference(ComparisonDifferenceCode.FREQUENCY_MISMATCH),
            ),
        ),
        lambda: ReportCardCompatibilityAssessment(
            compatibility_policy_version=(
                REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION
            ),
            status=ComparisonCompatibilityStatus.CONTEXT_COMPATIBLE,
            observed_lineage_differences=(
                _difference(ComparisonDifferenceCode.STRATEGY_ID_DIFFERENCE),
                _difference(ComparisonDifferenceCode.STRATEGY_ID_DIFFERENCE),
            ),
        ),
        lambda: ReportCardCompatibilityAssessment(
            compatibility_policy_version=(
                REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION
            ),
            status=ComparisonCompatibilityStatus.INCOMPATIBLE,
            required_context_differences=(
                _difference(
                    ComparisonDifferenceCode.FREQUENCY_MISMATCH,
                    field_path="same.path",
                ),
                _difference(
                    ComparisonDifferenceCode.DATE_RANGE_MISMATCH,
                    field_path="same.path",
                ),
            ),
        ),
    ],
)
def test_assessment_direct_construction_rejects_invalid_invariants(
    assessment: object,
) -> None:
    with pytest.raises(ValidationError):
        assessment()


def test_difference_rejects_non_json_safe_values() -> None:
    with pytest.raises(ValidationError):
        ComparisonDifference(
            code=ComparisonDifferenceCode.FREQUENCY_MISMATCH,
            field_path="research_scope.frequency",
            baseline_value=object(),
            candidate_value="daily",
        )


@pytest.mark.parametrize(
    ("code", "field_path"),
    [
        (
            ComparisonDifferenceCode.FREQUENCY_MISMATCH,
            "lineage.strategy_id",
        ),
        (
            ComparisonDifferenceCode.STRATEGY_ID_DIFFERENCE,
            "research_scope.frequency",
        ),
    ],
)
def test_difference_direct_construction_rejects_wrong_field_path(
    code: ComparisonDifferenceCode,
    field_path: str,
) -> None:
    with pytest.raises(ValidationError):
        ComparisonDifference(
            code=code,
            field_path=field_path,
            baseline_value="baseline",
            candidate_value="candidate",
        )


def test_difference_direct_construction_accepts_canonical_field_path() -> None:
    difference = _difference(ComparisonDifferenceCode.FREQUENCY_MISMATCH)

    assert difference.field_path == "research_scope.frequency"


@pytest.mark.parametrize(
    "metric",
    [
        lambda: ReportCardMetricComparison(
            metric_name=ReportCardComparisonMetricName.TOTAL_RETURN,
            unit=ReportCardComparisonMetricUnit.COUNT,
            scale=12,
            baseline_value="0.010000000000",
            candidate_value="0.020000000000",
            delta="0.010000000000",
        ),
        lambda: ReportCardMetricComparison(
            metric_name=ReportCardComparisonMetricName.TOTAL_RETURN,
            unit=ReportCardComparisonMetricUnit.RATIO,
            scale=0,
            baseline_value="0.010000000000",
            candidate_value="0.020000000000",
            delta="0.010000000000",
        ),
        lambda: ReportCardMetricComparison(
            metric_name=ReportCardComparisonMetricName.TOTAL_RETURN,
            unit=ReportCardComparisonMetricUnit.RATIO,
            scale=12,
            baseline_value="0.01",
            candidate_value="0.020000000000",
            delta="0.010000000000",
        ),
        lambda: ReportCardMetricComparison(
            metric_name=ReportCardComparisonMetricName.TOTAL_RETURN,
            unit=ReportCardComparisonMetricUnit.RATIO,
            scale=12,
            baseline_value="-0.000000000000",
            candidate_value="0.020000000000",
            delta="0.020000000000",
        ),
        lambda: ReportCardMetricComparison(
            metric_name=ReportCardComparisonMetricName.NUMBER_OF_TRADES,
            unit=ReportCardComparisonMetricUnit.RATIO,
            scale=0,
            baseline_value=1,
            candidate_value=2,
            delta=1,
        ),
        lambda: ReportCardMetricComparison(
            metric_name=ReportCardComparisonMetricName.NUMBER_OF_TRADES,
            unit=ReportCardComparisonMetricUnit.COUNT,
            scale=12,
            baseline_value=1,
            candidate_value=2,
            delta=1,
        ),
        lambda: ReportCardMetricComparison(
            metric_name=ReportCardComparisonMetricName.NUMBER_OF_TRADES,
            unit=ReportCardComparisonMetricUnit.COUNT,
            scale=0,
            baseline_value="1",
            candidate_value=2,
            delta=1,
        ),
        lambda: ReportCardMetricComparison(
            metric_name=ReportCardComparisonMetricName.NUMBER_OF_TRADES,
            unit=ReportCardComparisonMetricUnit.COUNT,
            scale=0,
            baseline_value=True,
            candidate_value=2,
            delta=1,
        ),
    ],
)
def test_metric_direct_construction_rejects_invalid_invariants(metric: object) -> None:
    with pytest.raises(ValidationError):
        metric()


@pytest.mark.parametrize(
    ("baseline_value", "candidate_value", "delta"),
    [
        ("0.010000000000", "0.020000000000", "0.010000000000"),
        ("0.020000000000", "0.010000000000", "-0.010000000000"),
        ("0.010000000000", "0.010000000000", "0.000000000000"),
    ],
)
def test_ratio_metric_direct_construction_accepts_exact_delta(
    baseline_value: str,
    candidate_value: str,
    delta: str,
) -> None:
    metric = _ratio_metric(
        baseline_value=baseline_value,
        candidate_value=candidate_value,
        delta=delta,
    )

    assert metric.delta == delta


@pytest.mark.parametrize(
    "metric",
    [
        lambda: _ratio_metric(
            baseline_value="0.010000000000",
            candidate_value="0.020000000000",
            delta="0.999000000000",
        ),
        lambda: _ratio_metric(
            metric_name=ReportCardComparisonMetricName.MAXIMUM_DRAWDOWN,
            baseline_value="0.010000000000",
            candidate_value="-0.020000000000",
            delta="-0.030000000000",
        ),
        lambda: _ratio_metric(
            metric_name=ReportCardComparisonMetricName.MAXIMUM_DRAWDOWN,
            baseline_value="-0.020000000000",
            candidate_value="0.010000000000",
            delta="0.030000000000",
        ),
    ],
)
def test_ratio_metric_direct_construction_rejects_derived_fact_violations(
    metric: object,
) -> None:
    with pytest.raises(ValidationError):
        metric()


@pytest.mark.parametrize(
    ("baseline_value", "candidate_value", "delta"),
    [
        (1, 3, 2),
        (3, 1, -2),
        (3, 3, 0),
    ],
)
def test_count_metric_direct_construction_accepts_exact_delta(
    baseline_value: int,
    candidate_value: int,
    delta: int,
) -> None:
    metric = _count_metric(
        baseline_value=baseline_value,
        candidate_value=candidate_value,
        delta=delta,
    )

    assert metric.delta == delta


@pytest.mark.parametrize(
    "metric",
    [
        lambda: _count_metric(baseline_value=1, candidate_value=3, delta=99),
        lambda: _count_metric(baseline_value=-1, candidate_value=3, delta=4),
        lambda: _count_metric(baseline_value=1, candidate_value=-3, delta=-4),
    ],
)
def test_count_metric_direct_construction_rejects_derived_fact_violations(
    metric: object,
) -> None:
    with pytest.raises(ValidationError):
        metric()


@pytest.mark.parametrize(
    "assessment",
    [
        lambda: ReportCardCompatibilityAssessment(
            compatibility_policy_version=(
                REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION
            ),
            status=ComparisonCompatibilityStatus.INCOMPATIBLE,
            required_context_differences=(
                _difference(ComparisonDifferenceCode.STRATEGY_ID_DIFFERENCE),
            ),
        ),
        lambda: ReportCardCompatibilityAssessment(
            compatibility_policy_version=(
                REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION
            ),
            status=ComparisonCompatibilityStatus.INCOMPATIBLE,
            required_context_differences=(
                _difference(ComparisonDifferenceCode.CONFIG_HASH_DIFFERENCE),
            ),
        ),
        lambda: ReportCardCompatibilityAssessment(
            compatibility_policy_version=(
                REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION
            ),
            status=ComparisonCompatibilityStatus.CONTEXT_COMPATIBLE,
            observed_lineage_differences=(
                _difference(ComparisonDifferenceCode.FREQUENCY_MISMATCH),
            ),
        ),
        lambda: ReportCardCompatibilityAssessment(
            compatibility_policy_version=(
                REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION
            ),
            status=ComparisonCompatibilityStatus.CONTEXT_COMPATIBLE,
            observed_lineage_differences=(
                _difference(ComparisonDifferenceCode.DATA_SNAPSHOT_HASH_MISMATCH),
            ),
        ),
    ],
)
def test_assessment_direct_construction_rejects_wrong_difference_category(
    assessment: object,
) -> None:
    with pytest.raises(ValidationError):
        assessment()


def test_assessment_direct_construction_rejects_noncanonical_difference_order() -> None:
    with pytest.raises(ValidationError):
        ReportCardCompatibilityAssessment(
            compatibility_policy_version=(
                REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION
            ),
            status=ComparisonCompatibilityStatus.INCOMPATIBLE,
            required_context_differences=(
                _difference(ComparisonDifferenceCode.FREQUENCY_MISMATCH),
                _difference(ComparisonDifferenceCode.DATE_RANGE_MISMATCH),
            ),
        )

    with pytest.raises(ValidationError):
        ReportCardCompatibilityAssessment(
            compatibility_policy_version=(
                REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION
            ),
            status=ComparisonCompatibilityStatus.CONTEXT_COMPATIBLE,
            observed_lineage_differences=(
                _difference(ComparisonDifferenceCode.PARAMETER_HASH_DIFFERENCE),
                _difference(ComparisonDifferenceCode.CONFIG_HASH_DIFFERENCE),
            ),
        )


def test_assessment_direct_construction_serializes_in_canonical_order() -> None:
    required_assessment = ReportCardCompatibilityAssessment(
        compatibility_policy_version=(
            REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION
        ),
        status=ComparisonCompatibilityStatus.INCOMPATIBLE,
        required_context_differences=(
            _difference(ComparisonDifferenceCode.DATE_RANGE_MISMATCH),
            _difference(ComparisonDifferenceCode.FREQUENCY_MISMATCH),
        ),
    )
    observed_assessment = ReportCardCompatibilityAssessment(
        compatibility_policy_version=(
            REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION
        ),
        status=ComparisonCompatibilityStatus.CONTEXT_COMPATIBLE,
        observed_lineage_differences=(
            _difference(ComparisonDifferenceCode.CONFIG_HASH_DIFFERENCE),
            _difference(ComparisonDifferenceCode.PARAMETER_HASH_DIFFERENCE),
        ),
    )

    required_serialized = required_assessment.model_dump(mode="json")
    observed_serialized = observed_assessment.model_dump(mode="json")

    assert [
        difference["code"]
        for difference in required_serialized["required_context_differences"]
    ] == ["DATE_RANGE_MISMATCH", "FREQUENCY_MISMATCH"]
    assert [
        difference["code"]
        for difference in observed_serialized["observed_lineage_differences"]
    ] == ["CONFIG_HASH_DIFFERENCE", "PARAMETER_HASH_DIFFERENCE"]


@pytest.mark.parametrize(
    "metrics",
    [
        lambda: _valid_metric_comparisons()[:-1],
        lambda: (
            *_valid_metric_comparisons(),
            _valid_metric_comparisons()[0],
        ),
        lambda: (
            ReportCardMetricComparison.model_construct(
                metric_name="unexpected_metric",
                unit=ReportCardComparisonMetricUnit.RATIO,
                scale=12,
                baseline_value="0.000000000000",
                candidate_value="0.000000000000",
                delta="0.000000000000",
            ),
            *_valid_metric_comparisons()[1:],
        ),
    ],
)
def test_comparison_contract_rejects_invalid_metric_sets(metrics: object) -> None:
    with pytest.raises(ValidationError):
        _comparison_contract(metric_comparisons=metrics())


def test_comparison_contract_rejects_incompatible_assessment() -> None:
    with pytest.raises(ValidationError):
        _comparison_contract(
            compatibility=ReportCardCompatibilityAssessment(
                compatibility_policy_version=(
                    REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION
                ),
                status=ComparisonCompatibilityStatus.INCOMPATIBLE,
                required_context_differences=(
                    _difference(ComparisonDifferenceCode.FREQUENCY_MISMATCH),
                ),
            )
        )


def test_pure_comparison_import_boundary() -> None:
    code = """
import json
import sys
from research_sdk.report_card_comparison import compare_research_report_cards

forbidden = sorted(
    name
    for name in sys.modules
    if name == "sqlalchemy"
    or name.startswith("sqlalchemy.")
    or name == "psycopg"
    or name.startswith("psycopg.")
    or name == "research_sdk.persistence"
    or name.startswith("research_sdk.persistence.")
    or name == "research_sdk.experiment_recording"
    or name.startswith("research_sdk.experiment_recording.")
    or name == "backtest_engine"
    or name.startswith("backtest_engine.")
)
print(json.dumps(forbidden))
if forbidden:
    raise SystemExit(1)
assert compare_research_report_cards is not None
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, (
        "report-card comparison imported forbidden modules: "
        f"{completed.stdout}\nstderr:\n{completed.stderr}"
    )


def _with_lineage_update(card, **updates):
    return card.model_copy(update={"lineage": card.lineage.model_copy(update=updates)})


def _with_scope_update(card, **updates):
    return card.model_copy(
        update={"research_scope": card.research_scope.model_copy(update=updates)}
    )


def _with_assumptions_update(card, **updates):
    return card.model_copy(
        update={"assumptions": card.assumptions.model_copy(update=updates)}
    )


def _with_metrics_update(card, **updates):
    return card.model_copy(update={"metrics": card.metrics.model_copy(update=updates)})


def _with_recomputed_report_card_id(card):
    return card.model_copy(
        update={
            "report_card_id": derive_research_report_card_id_from_fields(
                source_run_id=card.source_run_id,
                schema_version=card.schema_version,
                derivation_policy_version=card.derivation_policy_version,
                data_snapshot_content_hash=card.lineage.data_snapshot_content_hash,
                benchmark_snapshot_content_hash=(
                    card.lineage.benchmark_snapshot_content_hash
                ),
                config_hash=card.lineage.config_hash,
                parameter_hash=card.lineage.parameter_hash,
                artifact_manifest_hash=card.lineage.artifact_manifest_hash,
            )
        }
    )


def _with_distinct_source_identity(card):
    distinct_source = card.model_copy(
        update={
            "source_run_id": "run-" + ("5" * 64),
            "experiment_id": "exp-distinct-comparison-source",
            "lineage": card.lineage.model_copy(
                update={"artifact_manifest_id": "manifest-" + ("5" * 64)}
            ),
        }
    )
    return _with_recomputed_report_card_id(distinct_source)


def _difference(
    code: ComparisonDifferenceCode,
    *,
    field_path: str | None = None,
) -> ComparisonDifference:
    return ComparisonDifference(
        code=code,
        field_path=field_path or COMPARISON_DIFFERENCE_FIELD_PATH_BY_CODE[code],
        baseline_value="baseline",
        candidate_value="candidate",
    )


def _ratio_metric(
    *,
    metric_name: ReportCardComparisonMetricName = (
        ReportCardComparisonMetricName.TOTAL_RETURN
    ),
    baseline_value: str,
    candidate_value: str,
    delta: str,
) -> ReportCardMetricComparison:
    return ReportCardMetricComparison(
        metric_name=metric_name,
        unit=ReportCardComparisonMetricUnit.RATIO,
        scale=12,
        baseline_value=baseline_value,
        candidate_value=candidate_value,
        delta=delta,
    )


def _count_metric(
    *,
    baseline_value: int,
    candidate_value: int,
    delta: int,
) -> ReportCardMetricComparison:
    return ReportCardMetricComparison(
        metric_name=ReportCardComparisonMetricName.NUMBER_OF_TRADES,
        unit=ReportCardComparisonMetricUnit.COUNT,
        scale=0,
        baseline_value=baseline_value,
        candidate_value=candidate_value,
        delta=delta,
    )


def _valid_metric_comparisons() -> tuple[ReportCardMetricComparison, ...]:
    return (
        ReportCardMetricComparison(
            metric_name=ReportCardComparisonMetricName.TOTAL_RETURN,
            unit=ReportCardComparisonMetricUnit.RATIO,
            scale=12,
            baseline_value="0.010000000000",
            candidate_value="0.020000000000",
            delta="0.010000000000",
        ),
        ReportCardMetricComparison(
            metric_name=ReportCardComparisonMetricName.EXCESS_RETURN,
            unit=ReportCardComparisonMetricUnit.RATIO,
            scale=12,
            baseline_value="0.010000000000",
            candidate_value="0.020000000000",
            delta="0.010000000000",
        ),
        ReportCardMetricComparison(
            metric_name=ReportCardComparisonMetricName.MAXIMUM_DRAWDOWN,
            unit=ReportCardComparisonMetricUnit.RATIO,
            scale=12,
            baseline_value="-0.020000000000",
            candidate_value="-0.010000000000",
            delta="0.010000000000",
        ),
        ReportCardMetricComparison(
            metric_name=ReportCardComparisonMetricName.NUMBER_OF_TRADES,
            unit=ReportCardComparisonMetricUnit.COUNT,
            scale=0,
            baseline_value=1,
            candidate_value=2,
            delta=1,
        ),
    )


def _comparison_contract(**updates) -> ResearchReportCardComparison:
    baseline_report_card_id = "report-card-" + ("1" * 64)
    candidate_report_card_id = "report-card-" + ("2" * 64)
    payload = {
        "comparison_id": derive_research_report_card_comparison_id(
            schema_version=REPORT_CARD_COMPARISON_SCHEMA_VERSION,
            compatibility_policy_version=(
                REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION
            ),
            metric_policy_version=REPORT_CARD_COMPARISON_METRIC_POLICY_VERSION,
            baseline_report_card_id=baseline_report_card_id,
            candidate_report_card_id=candidate_report_card_id,
        ),
        "schema_version": REPORT_CARD_COMPARISON_SCHEMA_VERSION,
        "compatibility_policy_version": (
            REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION
        ),
        "metric_policy_version": REPORT_CARD_COMPARISON_METRIC_POLICY_VERSION,
        "baseline_report_card_id": baseline_report_card_id,
        "candidate_report_card_id": candidate_report_card_id,
        "compatibility": ReportCardCompatibilityAssessment(
            compatibility_policy_version=(
                REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION
            ),
            status=ComparisonCompatibilityStatus.STRICT_COMPATIBLE,
        ),
        "metric_comparisons": _valid_metric_comparisons(),
        "limitations": ("comparison reports deterministic evidence differences only",),
        "use_restrictions": (ReportCardUseRestriction.NO_INVESTMENT_PERFORMANCE_CLAIM,),
    }
    payload.update(updates)
    return ResearchReportCardComparison(**payload)


def _metric_delta(comparison, metric_name: str):
    return next(
        metric.delta
        for metric in comparison.metric_comparisons
        if metric.metric_name.value == metric_name
    )


def _hash(digit: str) -> str:
    return f"sha256:{digit * 64}"


def _assert_no_key(value: object, forbidden_key: str) -> None:
    if isinstance(value, dict):
        assert forbidden_key not in value
        for nested in value.values():
            _assert_no_key(nested, forbidden_key)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_key(nested, forbidden_key)


def _lineage_value(field_name: str) -> str:
    if field_name == "strategy_id":
        return "strategies/etfs/alternate"
    if field_name == "strategy_version":
        return "0.2.0"
    if field_name == "config_hash":
        return _hash("9")
    if field_name == "parameter_hash":
        return _hash("8")
    raise AssertionError(f"unsupported lineage field: {field_name}")
