"""Pure deterministic identity helpers for report-card comparisons."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from research_sdk.contracts.report_cards import (
    REPORT_CARD_DIGEST_LENGTH,
    REPORT_CARD_ID_PREFIX,
)
from research_sdk.report_card_comparison.models import (
    REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION,
    REPORT_CARD_COMPARISON_DIGEST_LENGTH,
    REPORT_CARD_COMPARISON_ID_PREFIX,
    REPORT_CARD_COMPARISON_METRIC_POLICY_VERSION,
    REPORT_CARD_COMPARISON_SCHEMA_VERSION,
    ResearchReportCardComparison,
)

_LOWER_HEX_DIGITS = frozenset("0123456789abcdef")


class ResearchReportCardComparisonIdentityError(ValueError):
    """Raised when a report-card comparison identity is malformed or stale."""


def derive_research_report_card_comparison_id(
    *,
    schema_version: str,
    compatibility_policy_version: str,
    metric_policy_version: str,
    baseline_report_card_id: str,
    candidate_report_card_id: str,
) -> str:
    """Derive the directional deterministic comparison identity."""

    _validate_supported_schema_version(schema_version)
    _validate_supported_compatibility_policy(compatibility_policy_version)
    _validate_supported_metric_policy(metric_policy_version)
    _validate_report_card_id(baseline_report_card_id, "baseline_report_card_id")
    _validate_report_card_id(candidate_report_card_id, "candidate_report_card_id")
    payload = {
        "schema_version": schema_version,
        "compatibility_policy_version": compatibility_policy_version,
        "metric_policy_version": metric_policy_version,
        "baseline_report_card_id": baseline_report_card_id,
        "candidate_report_card_id": candidate_report_card_id,
    }
    return f"{REPORT_CARD_COMPARISON_ID_PREFIX}{_canonical_json_sha256(payload)}"


def verify_research_report_card_comparison_identity(
    comparison: ResearchReportCardComparison,
) -> None:
    """Verify a comparison ID from the directional identity inputs."""

    _validate_comparison_id(comparison.comparison_id)
    _validate_supported_schema_version(comparison.schema_version)
    _validate_supported_compatibility_policy(comparison.compatibility_policy_version)
    _validate_supported_metric_policy(comparison.metric_policy_version)
    expected = derive_research_report_card_comparison_id(
        schema_version=comparison.schema_version,
        compatibility_policy_version=comparison.compatibility_policy_version,
        metric_policy_version=comparison.metric_policy_version,
        baseline_report_card_id=comparison.baseline_report_card_id,
        candidate_report_card_id=comparison.candidate_report_card_id,
    )
    if comparison.comparison_id != expected:
        raise ResearchReportCardComparisonIdentityError(
            "report-card comparison identity is stale or inconsistent"
        )


def _validate_comparison_id(comparison_id: str) -> None:
    if not comparison_id.startswith(REPORT_CARD_COMPARISON_ID_PREFIX):
        raise ResearchReportCardComparisonIdentityError(
            "comparison_id must use the report-card-comparison-v1- prefix"
        )
    digest = comparison_id.removeprefix(REPORT_CARD_COMPARISON_ID_PREFIX)
    if len(digest) != REPORT_CARD_COMPARISON_DIGEST_LENGTH:
        raise ResearchReportCardComparisonIdentityError(
            "comparison_id must contain a full SHA-256 digest"
        )
    if digest.lower() != digest or any(
        character not in _LOWER_HEX_DIGITS for character in digest
    ):
        raise ResearchReportCardComparisonIdentityError(
            "comparison_id digest must be lowercase hexadecimal"
        )


def _validate_report_card_id(report_card_id: str, field_name: str) -> None:
    if not report_card_id.startswith(REPORT_CARD_ID_PREFIX):
        raise ResearchReportCardComparisonIdentityError(
            f"{field_name} must use the report-card- prefix"
        )
    digest = report_card_id.removeprefix(REPORT_CARD_ID_PREFIX)
    if len(digest) != REPORT_CARD_DIGEST_LENGTH:
        raise ResearchReportCardComparisonIdentityError(
            f"{field_name} must contain a full SHA-256 digest"
        )
    if digest.lower() != digest or any(
        character not in _LOWER_HEX_DIGITS for character in digest
    ):
        raise ResearchReportCardComparisonIdentityError(
            f"{field_name} digest must be lowercase hexadecimal"
        )


def _validate_supported_compatibility_policy(policy_version: str) -> None:
    if policy_version != REPORT_CARD_COMPARISON_COMPATIBILITY_POLICY_VERSION:
        raise ResearchReportCardComparisonIdentityError(
            "unsupported compatibility policy version"
        )


def _validate_supported_schema_version(schema_version: str) -> None:
    if schema_version != REPORT_CARD_COMPARISON_SCHEMA_VERSION:
        raise ResearchReportCardComparisonIdentityError(
            "unsupported comparison schema version"
        )


def _validate_supported_metric_policy(policy_version: str) -> None:
    if policy_version != REPORT_CARD_COMPARISON_METRIC_POLICY_VERSION:
        raise ResearchReportCardComparisonIdentityError(
            "unsupported metric policy version"
        )


def _canonical_json_sha256(payload: Mapping[str, Any]) -> str:
    canonical_json = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(f"{canonical_json}\n".encode()).hexdigest()


__all__ = [
    "ResearchReportCardComparisonIdentityError",
    "derive_research_report_card_comparison_id",
    "verify_research_report_card_comparison_identity",
]
