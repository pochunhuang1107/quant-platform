"""Pure deterministic report-card comparison helpers."""

from research_sdk.report_card_comparison.comparison import (
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
    REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION,
    REPORT_CARD_COMPARISON_DIGEST_LENGTH,
    REPORT_CARD_COMPARISON_ID_PREFIX,
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
)

__all__ = [
    "REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION",
    "REPORT_CARD_COMPARISON_DIGEST_LENGTH",
    "REPORT_CARD_COMPARISON_ID_PREFIX",
    "REPORT_CARD_COMPARISON_METRIC_POLICY_VERSION",
    "REPORT_CARD_COMPARISON_SCHEMA_VERSION",
    "ComparisonCompatibilityStatus",
    "ComparisonDifference",
    "ComparisonDifferenceCode",
    "ReportCardCompatibilityAssessment",
    "ReportCardComparisonMetricName",
    "ReportCardComparisonMetricUnit",
    "ReportCardMetricComparison",
    "ResearchReportCardComparison",
    "ResearchReportCardComparisonIdentityError",
    "ResearchReportCardComparisonInputIntegrityError",
    "ResearchReportCardComparisonIncompatibilityError",
    "assess_research_report_card_compatibility",
    "compare_research_report_cards",
    "derive_research_report_card_comparison_id",
    "verify_research_report_card_comparison_identity",
]
