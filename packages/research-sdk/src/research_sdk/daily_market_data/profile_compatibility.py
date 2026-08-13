"""Pure research-profile identity and snapshot-v2 compatibility checks."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NoReturn

from research_sdk.contracts.daily_market_data import DailyMarketDataQualityStatus
from research_sdk.contracts.daily_market_data_economics import (
    DailyMarketDataBarAvailabilityPolicy,
    DailyMarketDataCashDistribution,
    DailyMarketDataCorporateActionEventType,
    DailyMarketDataResearchProfile,
)

if TYPE_CHECKING:
    from research_sdk.daily_market_data_storage.verification_v2 import (
        VerifiedDailyMarketDataSnapshotV2,
    )


class DailyMarketDataSnapshotProfileCompatibilityError(ValueError):
    """Raised when a verified snapshot-v2 does not satisfy a research profile."""


@dataclass(frozen=True)
class DailyMarketDataSnapshotProfileCompatibility:
    """Operational facts from a verified snapshot-v2/profile compatibility check.

    This result is not research readiness, experiment readiness, provider
    approval, benchmark compatibility, accounting support, or execution
    leakage proof. The required daily-bar availability policy is carried as a
    downstream obligation.
    """

    snapshot_id: str
    profile_id: str
    profile_hash: str
    profile_policy_version: str
    instrument_id: str
    unsupported_event_count: int
    required_daily_bar_availability_policy: DailyMarketDataBarAvailabilityPolicy


def derive_daily_market_data_research_profile_hash(
    profile: DailyMarketDataResearchProfile,
) -> str:
    """Hash the complete validated daily market-data research profile contract."""

    validated_profile = DailyMarketDataResearchProfile.model_validate(
        profile.model_dump(mode="json")
    )
    return _sha256_prefixed(
        {
            "domain": "daily-market-data-research-profile",
            "identity_version": "daily-market-data-research-profile-hash-v1",
            "research_profile": validated_profile.model_dump(mode="json"),
        }
    )


def validate_daily_market_data_snapshot_profile_compatibility(
    *,
    verified_snapshot: VerifiedDailyMarketDataSnapshotV2,
    research_profile: DailyMarketDataResearchProfile,
) -> DailyMarketDataSnapshotProfileCompatibility:
    """Validate snapshot-evaluable profile compatibility for verified v2 only.

    Callers should obtain ``verified_snapshot`` from the pure or local
    snapshot-v2 verifier. A manually constructed Python dataclass instance is
    outside the normal verifier-produced trust path; this function does not
    recompute snapshot-v2 identity or component hashes.
    """

    from research_sdk.daily_market_data_storage.verification_v2 import (
        VerifiedDailyMarketDataSnapshotV2,
    )

    if not isinstance(verified_snapshot, VerifiedDailyMarketDataSnapshotV2):
        _compatibility_error(
            "verified_snapshot must be VerifiedDailyMarketDataSnapshotV2"
        )

    validated_profile = DailyMarketDataResearchProfile.model_validate(
        research_profile.model_dump(mode="json")
    )

    _require(
        verified_snapshot.policy.asset_class is validated_profile.asset_class,
        "policy asset_class must match profile",
    )
    _require(
        verified_snapshot.policy.frequency == validated_profile.frequency,
        "policy frequency must match profile",
    )
    _require(
        verified_snapshot.policy.adjustment_policy
        is validated_profile.adjustment_policy,
        "policy adjustment_policy must match profile",
    )
    _require(
        verified_snapshot.policy.distribution_treatment
        is validated_profile.distribution_treatment,
        "policy distribution_treatment must match profile",
    )
    _require(
        verified_snapshot.policy.calendar == validated_profile.calendar,
        "policy calendar must match profile",
    )
    _require(
        verified_snapshot.policy.timezone == validated_profile.timezone,
        "policy timezone must match profile",
    )
    _require(
        verified_snapshot.policy.universe_membership_policy
        == validated_profile.universe_membership_policy,
        "policy universe_membership_policy must match profile",
    )
    _require(
        verified_snapshot.policy.survivorship_policy
        == validated_profile.survivorship_policy,
        "policy survivorship_policy must match profile",
    )
    _require(
        verified_snapshot.policy.delisting_policy == validated_profile.delisting_policy,
        "policy delisting_policy must match profile",
    )

    _require(
        verified_snapshot.quality_report.status is DailyMarketDataQualityStatus.PASS,
        "quality report status must pass",
    )
    _require(
        verified_snapshot.instrument_id
        == verified_snapshot.quality_report.instrument.instrument_id,
        "verified snapshot instrument_id must match quality report",
    )
    _require(
        verified_snapshot.corporate_action_evidence.instrument
        == verified_snapshot.quality_report.instrument,
        "corporate-action evidence instrument must match quality report",
    )

    _require(
        verified_snapshot.bar_provenance.currency
        == validated_profile.required_currency,
        "bar provenance currency must match profile required_currency",
    )
    _require(
        verified_snapshot.bar_provenance.temporal_coverage
        in validated_profile.permitted_temporal_coverage,
        "bar provenance temporal_coverage must be permitted by profile",
    )

    _require(
        verified_snapshot.expected_sessions.calendar == validated_profile.calendar,
        "expected sessions calendar must match profile",
    )
    _require(
        verified_snapshot.expected_sessions.timezone == validated_profile.timezone,
        "expected sessions timezone must match profile",
    )
    _require(
        verified_snapshot.expected_sessions.session_source_id
        == validated_profile.session_source_id,
        "expected sessions source ID must match profile",
    )
    _require(
        verified_snapshot.expected_sessions.session_source_version
        == validated_profile.session_source_version,
        "expected sessions source version must match profile",
    )

    evidence = verified_snapshot.corporate_action_evidence
    _require(
        evidence.coverage_start_date
        <= verified_snapshot.quality_report.expected_start_date,
        "corporate-action evidence must cover quality start date",
    )
    _require(
        evidence.coverage_end_date
        >= verified_snapshot.quality_report.expected_end_date,
        "corporate-action evidence must cover quality end date",
    )
    _require(
        evidence.completeness
        in validated_profile.allowed_corporate_action_completeness,
        "corporate-action evidence completeness must be allowed by profile",
    )

    unsupported_event_count = sum(
        1
        for event in evidence.events
        if event.event_type == DailyMarketDataCorporateActionEventType.UNSUPPORTED
    )
    if unsupported_event_count > 0 and not validated_profile.unsupported_events_allowed:
        _compatibility_error("unsupported corporate-action events are not allowed")

    supported_event_types = set(
        validated_profile.supported_corporate_action_event_types
    )
    for event in evidence.events:
        if event.event_type not in supported_event_types:
            _compatibility_error(
                "corporate-action event type is not supported by profile"
            )
        if (
            isinstance(event, DailyMarketDataCashDistribution)
            and event.currency != validated_profile.required_currency
        ):
            _compatibility_error("cash distribution currency must match profile")

    return DailyMarketDataSnapshotProfileCompatibility(
        snapshot_id=verified_snapshot.snapshot_id,
        profile_id=validated_profile.profile_id,
        profile_hash=derive_daily_market_data_research_profile_hash(validated_profile),
        profile_policy_version=validated_profile.profile_policy_version,
        instrument_id=verified_snapshot.instrument_id,
        unsupported_event_count=unsupported_event_count,
        required_daily_bar_availability_policy=(
            validated_profile.daily_bar_availability_policy
        ),
    )


def _sha256_prefixed(payload: Mapping[str, Any]) -> str:
    return f"sha256:{_sha256_hex(payload)}"


def _sha256_hex(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    rendered = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return f"{rendered}\n".encode()


def _require(condition: bool, message: str) -> None:
    if not condition:
        _compatibility_error(message)


def _compatibility_error(message: str) -> NoReturn:
    raise DailyMarketDataSnapshotProfileCompatibilityError(message)


__all__ = [
    "DailyMarketDataSnapshotProfileCompatibility",
    "DailyMarketDataSnapshotProfileCompatibilityError",
    "derive_daily_market_data_research_profile_hash",
    "validate_daily_market_data_snapshot_profile_compatibility",
]
