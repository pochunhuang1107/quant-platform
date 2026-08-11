"""Pure economic evidence/profile coherence checks for daily market data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from research_sdk.contracts.daily_market_data import (
    DailyMarketDataPolicy,
    DailyMarketDataQualityReport,
    DailyMarketDataQualityStatus,
)
from research_sdk.contracts.daily_market_data_economics import (
    DailyMarketDataCorporateActionEventType,
    DailyMarketDataCorporateActionEvidence,
    DailyMarketDataResearchProfile,
)
from research_sdk.contracts.daily_market_data_snapshots import (
    DailyMarketDataExpectedSessions,
    DailyMarketDataSnapshotProvenance,
)


class DailyMarketDataEconomicEvidenceCompatibilityError(ValueError):
    """Raised when economic evidence does not satisfy a research-data profile."""


@dataclass(frozen=True)
class DailyMarketDataEconomicEvidenceCompatibility:
    """Facts from an economic evidence/profile compatibility check.

    This is not snapshot research readiness. S3c1 evidence remains separate
    from S3b1 snapshot identity; S3c2 must bind economic evidence into a new
    versioned snapshot identity before any snapshot can pass a readiness gate.
    """

    profile_id: str
    instrument_id: str
    unsupported_event_count: int
    s3b1_snapshot_identity_binds_economic_evidence: bool = False


def validate_daily_market_data_economic_evidence(
    *,
    policy: DailyMarketDataPolicy,
    expected_sessions: DailyMarketDataExpectedSessions,
    provenance: DailyMarketDataSnapshotProvenance,
    quality_report: DailyMarketDataQualityReport,
    corporate_action_evidence: DailyMarketDataCorporateActionEvidence,
    research_profile: DailyMarketDataResearchProfile,
) -> DailyMarketDataEconomicEvidenceCompatibility:
    """Validate economic evidence/profile coherence only.

    A successful result does not make an S3b1/S3b2 snapshot research-ready and
    does not imply provider, licensing, benchmark, strategy, or accounting
    approval.
    """

    validated_policy = DailyMarketDataPolicy.model_validate(
        policy.model_dump(mode="json")
    )
    validated_expected_sessions = DailyMarketDataExpectedSessions.model_validate(
        expected_sessions.model_dump(mode="json")
    )
    validated_provenance = DailyMarketDataSnapshotProvenance.model_validate(
        provenance.model_dump(mode="json")
    )
    validated_quality_report = DailyMarketDataQualityReport.model_validate(
        quality_report.model_dump(mode="json")
    )
    validated_evidence = DailyMarketDataCorporateActionEvidence.model_validate(
        corporate_action_evidence.model_dump(mode="json")
    )
    validated_profile = DailyMarketDataResearchProfile.model_validate(
        research_profile.model_dump(mode="json")
    )

    _require(
        validated_policy.asset_class is validated_profile.asset_class,
        "policy asset_class must match profile",
    )
    _require(
        validated_policy.frequency == validated_profile.frequency,
        "policy frequency must match profile",
    )
    _require(
        validated_policy.adjustment_policy is validated_profile.adjustment_policy,
        "policy adjustment_policy must match profile",
    )
    _require(
        validated_policy.distribution_treatment
        is validated_profile.distribution_treatment,
        "policy distribution_treatment must match profile",
    )
    _require(
        validated_policy.calendar == validated_profile.calendar,
        "policy calendar must match profile",
    )
    _require(
        validated_policy.timezone == validated_profile.timezone,
        "policy timezone must match profile",
    )
    _require(
        validated_policy.universe_membership_policy
        == validated_profile.universe_membership_policy,
        "policy universe_membership_policy must match profile",
    )
    _require(
        validated_policy.survivorship_policy == validated_profile.survivorship_policy,
        "policy survivorship_policy must match profile",
    )
    _require(
        validated_policy.delisting_policy == validated_profile.delisting_policy,
        "policy delisting_policy must match profile",
    )
    _require(
        validated_quality_report.status is DailyMarketDataQualityStatus.PASS,
        "quality report status must pass",
    )
    _require(
        validated_quality_report.instrument == validated_evidence.instrument,
        "quality instrument must match corporate-action evidence instrument",
    )
    _require(
        validated_evidence.instrument.instrument_id
        == validated_quality_report.instrument.instrument_id,
        "corporate-action evidence instrument_id must match quality report",
    )
    _require(
        validated_provenance.currency == validated_profile.required_currency,
        "provenance currency must match profile required_currency",
    )
    _require(
        validated_provenance.temporal_coverage
        in set(validated_profile.permitted_temporal_coverage),
        "provenance temporal_coverage must be permitted by profile",
    )
    _require(
        validated_expected_sessions.calendar == validated_profile.calendar,
        "expected sessions calendar must match profile",
    )
    _require(
        validated_expected_sessions.timezone == validated_profile.timezone,
        "expected sessions timezone must match profile",
    )
    _require(
        validated_expected_sessions.session_source_id
        == validated_profile.session_source_id,
        "expected sessions source ID must match profile",
    )
    _require(
        validated_expected_sessions.session_source_version
        == validated_profile.session_source_version,
        "expected sessions source version must match profile",
    )
    _require(
        validated_evidence.coverage_start_date
        <= validated_quality_report.expected_start_date,
        "corporate-action evidence must cover quality start date",
    )
    _require(
        validated_evidence.coverage_end_date
        >= validated_quality_report.expected_end_date,
        "corporate-action evidence must cover quality end date",
    )
    _require(
        validated_evidence.completeness
        in set(validated_profile.allowed_corporate_action_completeness),
        "corporate-action evidence completeness must be allowed by profile",
    )

    unsupported_event_count = sum(
        1
        for event in validated_evidence.events
        if event.event_type is DailyMarketDataCorporateActionEventType.UNSUPPORTED
    )
    if unsupported_event_count and not validated_profile.unsupported_events_allowed:
        _compatibility_error("unsupported corporate-action events are not allowed")

    supported_types = set(validated_profile.supported_corporate_action_event_types)
    for event in validated_evidence.events:
        if event.event_type not in supported_types:
            _compatibility_error(
                "corporate-action event type is not supported by profile"
            )
        if hasattr(event, "currency") and event.currency != (
            validated_profile.required_currency
        ):
            _compatibility_error("cash distribution currency must match profile")

    return DailyMarketDataEconomicEvidenceCompatibility(
        profile_id=validated_profile.profile_id,
        instrument_id=validated_evidence.instrument.instrument_id,
        unsupported_event_count=unsupported_event_count,
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        _compatibility_error(message)


def _compatibility_error(message: str) -> NoReturn:
    raise DailyMarketDataEconomicEvidenceCompatibilityError(message)


__all__ = [
    "DailyMarketDataEconomicEvidenceCompatibility",
    "DailyMarketDataEconomicEvidenceCompatibilityError",
    "validate_daily_market_data_economic_evidence",
]
