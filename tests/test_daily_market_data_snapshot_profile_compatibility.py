from __future__ import annotations

import json
from dataclasses import fields, replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from helpers_daily_market_data_snapshots import sample_plan
from helpers_daily_market_data_snapshots_v2 import (
    cash_distribution_v2,
    sample_corporate_action_evidence_v2,
    sample_plan_v2,
    split_v2,
    unsupported_event_v2,
)
from research_sdk.contracts import TemporalCoverage
from research_sdk.contracts.daily_market_data_economics import (
    DailyMarketDataBarAvailabilityPolicy,
    DailyMarketDataCorporateActionEventType,
    DailyMarketDataCorporateActionEvidenceCompleteness,
    DailyMarketDataResearchProfile,
)
from research_sdk.daily_market_data import (
    DailyMarketDataSnapshotProfileCompatibilityError,
    derive_daily_market_data_research_profile_hash,
    validate_daily_market_data_snapshot_profile_compatibility,
)
from research_sdk.daily_market_data_storage import (
    DailyMarketDataSnapshotPlanningV2Error,
    VerifiedDailyMarketDataSnapshotV2,
    verify_daily_market_data_snapshot_bundle,
    verify_daily_market_data_snapshot_bundle_v2,
)

PROFILE_HASH_GOLDEN = (
    "sha256:42883385c79a7609359795390780b7eb2f73c6d6eecbd492b5f943973c9305a8"
)
PROFILE_FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "contracts"
    / "daily_market_data_research_profile.json"
)


def test_public_imports_and_storage_verifier_import_do_not_cycle() -> None:
    from research_sdk.daily_market_data import (
        DailyMarketDataSnapshotProfileCompatibility,
        DailyMarketDataSnapshotProfileCompatibilityError,
        derive_daily_market_data_research_profile_hash,
        validate_daily_market_data_snapshot_profile_compatibility,
    )
    from research_sdk.daily_market_data_storage.verification_v2 import (
        VerifiedDailyMarketDataSnapshotV2,
    )

    assert DailyMarketDataSnapshotProfileCompatibility is not None
    assert DailyMarketDataSnapshotProfileCompatibilityError is not None
    assert derive_daily_market_data_research_profile_hash is not None
    assert validate_daily_market_data_snapshot_profile_compatibility is not None
    assert VerifiedDailyMarketDataSnapshotV2 is not None


def test_profile_hash_is_stable_for_same_profile_and_roundtrip() -> None:
    profile = _committed_profile_fixture()
    roundtripped = DailyMarketDataResearchProfile.model_validate(
        profile.model_dump(mode="json")
    )

    assert derive_daily_market_data_research_profile_hash(profile) == (
        derive_daily_market_data_research_profile_hash(profile)
    )
    assert derive_daily_market_data_research_profile_hash(roundtripped) == (
        derive_daily_market_data_research_profile_hash(profile)
    )


def test_committed_profile_fixture_hash_matches_golden() -> None:
    assert (
        derive_daily_market_data_research_profile_hash(_committed_profile_fixture())
        == PROFILE_HASH_GOLDEN
    )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("schema_version", "1.0.1"),
        ("profile_id", "synthetic-v2-compatible-profile-alt"),
        ("profile_policy_version", "daily-etf-v2-compatible-profile-v2"),
        ("required_currency", "CAD"),
        ("permitted_temporal_coverage", (TemporalCoverage.LATEST_KNOWN,)),
        ("calendar", "XNAS"),
        ("timezone", "UTC"),
        ("session_source_id", "synthetic-session-fixture-v2"),
        ("session_source_version", "2026-02-fixture"),
        ("universe_membership_policy", "alternate fixed ETF universe policy"),
        ("survivorship_policy", "alternate survivorship policy"),
        ("delisting_policy", "alternate delisting policy"),
        (
            "corporate_action_coverage_requirement",
            "structured evidence dates must cover expected sessions",
        ),
    ],
)
def test_profile_hash_changes_for_representative_authoritative_fields(
    field_name: str,
    value: object,
) -> None:
    profile = _compatible_profile_for_v2(_verified_v2())

    changed = _profile_variant(profile, **{field_name: value})

    assert derive_daily_market_data_research_profile_hash(changed) != (
        derive_daily_market_data_research_profile_hash(profile)
    )


def test_compatibility_pass_returns_exact_operational_fields() -> None:
    verified = _verified_v2()
    profile = _compatible_profile_for_v2(verified)

    result = validate_daily_market_data_snapshot_profile_compatibility(
        verified_snapshot=verified,
        research_profile=profile,
    )

    assert tuple(field.name for field in fields(result)) == (
        "snapshot_id",
        "profile_id",
        "profile_hash",
        "profile_policy_version",
        "instrument_id",
        "unsupported_event_count",
        "required_daily_bar_availability_policy",
    )
    assert result.snapshot_id == verified.snapshot_id
    assert result.profile_id == profile.profile_id
    assert result.profile_hash == derive_daily_market_data_research_profile_hash(
        profile
    )
    assert result.profile_policy_version == profile.profile_policy_version
    assert result.instrument_id == verified.instrument_id
    assert result.unsupported_event_count == 0
    assert result.required_daily_bar_availability_policy is (
        DailyMarketDataBarAvailabilityPolicy.NEXT_EXPECTED_SESSION
    )
    assert not hasattr(result, "research_ready")
    assert not hasattr(result, "experiment_ready")
    assert not hasattr(result, "approved")
    assert not hasattr(result, "leakage_safe")


def test_free_text_coverage_requirement_changes_hash_but_not_structured_pass() -> None:
    verified = _verified_v2()
    profile = _compatible_profile_for_v2(verified)
    changed_profile = _profile_variant(
        profile,
        corporate_action_coverage_requirement=(
            "different nonempty coverage policy text for identity only"
        ),
    )

    changed_hash = derive_daily_market_data_research_profile_hash(changed_profile)

    assert changed_hash != derive_daily_market_data_research_profile_hash(profile)
    result = validate_daily_market_data_snapshot_profile_compatibility(
        verified_snapshot=verified,
        research_profile=changed_profile,
    )
    assert result.profile_hash == changed_hash


def test_committed_profile_fixture_does_not_match_synthetic_v2_snapshot() -> None:
    with pytest.raises(DailyMarketDataSnapshotProfileCompatibilityError):
        validate_daily_market_data_snapshot_profile_compatibility(
            verified_snapshot=_verified_v2(),
            research_profile=_committed_profile_fixture(),
        )


@pytest.mark.parametrize(
    ("field_name", "value", "match"),
    [
        ("required_currency", "CAD", "currency"),
        ("permitted_temporal_coverage", (TemporalCoverage.LATEST_KNOWN,), "temporal"),
        ("calendar", "XNAS", "calendar"),
        ("timezone", "UTC", "timezone"),
        ("session_source_id", "different-session-source", "source ID"),
        ("session_source_version", "different-session-version", "source version"),
        ("universe_membership_policy", "different universe policy", "universe"),
        ("survivorship_policy", "different survivorship policy", "survivorship"),
        ("delisting_policy", "different delisting policy", "delisting"),
    ],
)
def test_profile_side_incompatibilities_fail_closed(
    field_name: str,
    value: object,
    match: str,
) -> None:
    verified = _verified_v2()
    profile = _compatible_profile_for_v2(verified, **{field_name: value})

    with pytest.raises(DailyMarketDataSnapshotProfileCompatibilityError, match=match):
        validate_daily_market_data_snapshot_profile_compatibility(
            verified_snapshot=verified,
            research_profile=profile,
        )


def test_snapshot_with_unsupported_corporate_action_fails_profile() -> None:
    verified = _verified_v2(
        corporate_action_evidence=sample_corporate_action_evidence_v2(
            events=(unsupported_event_v2(),)
        )
    )

    with pytest.raises(
        DailyMarketDataSnapshotProfileCompatibilityError,
        match="unsupported",
    ):
        validate_daily_market_data_snapshot_profile_compatibility(
            verified_snapshot=verified,
            research_profile=_compatible_profile_for_v2(verified),
        )


def test_snapshot_with_cash_distribution_currency_mismatch_fails_profile() -> None:
    verified = _verified_v2(
        corporate_action_evidence=sample_corporate_action_evidence_v2(
            events=(cash_distribution_v2(currency="CAD"), split_v2())
        )
    )

    with pytest.raises(
        DailyMarketDataSnapshotProfileCompatibilityError,
        match="cash distribution currency",
    ):
        validate_daily_market_data_snapshot_profile_compatibility(
            verified_snapshot=verified,
            research_profile=_compatible_profile_for_v2(verified),
        )


def test_corporate_action_coverage_gap_is_rejected_before_compatibility() -> None:
    with pytest.raises(DailyMarketDataSnapshotPlanningV2Error, match="coverage"):
        sample_plan_v2(
            corporate_action_evidence=sample_corporate_action_evidence_v2(
                coverage_end_date=date(2026, 1, 4),
                events=(cash_distribution_v2(), split_v2()),
            )
        )


def test_defensive_structured_coverage_check_rejects_manual_verified_v2_gap() -> None:
    verified = _verified_v2()
    shorter_evidence = sample_corporate_action_evidence_v2(
        coverage_end_date=date(2026, 1, 4),
        events=(cash_distribution_v2(), split_v2()),
    )
    # This deliberately inconsistent VerifiedV2 is outside the normal verifier
    # authority path; it exists only to exercise defensive compatibility logic.
    inconsistent_verified = replace(
        verified,
        corporate_action_evidence=shorter_evidence,
    )

    with pytest.raises(
        DailyMarketDataSnapshotProfileCompatibilityError,
        match="cover",
    ):
        validate_daily_market_data_snapshot_profile_compatibility(
            verified_snapshot=inconsistent_verified,
            research_profile=_compatible_profile_for_v2(verified),
        )


def test_v1_verified_snapshot_is_rejected_at_runtime() -> None:
    v1_verified = verify_daily_market_data_snapshot_bundle(sample_plan().as_file_map())

    with pytest.raises(
        DailyMarketDataSnapshotProfileCompatibilityError,
        match="VerifiedDailyMarketDataSnapshotV2",
    ):
        validate_daily_market_data_snapshot_profile_compatibility(
            verified_snapshot=v1_verified,  # type: ignore[arg-type]
            research_profile=_compatible_profile_for_v2(_verified_v2()),
        )


def _verified_v2(**plan_overrides: object) -> VerifiedDailyMarketDataSnapshotV2:
    return verify_daily_market_data_snapshot_bundle_v2(
        sample_plan_v2(**plan_overrides).as_file_map()
    )


def _committed_profile_fixture() -> DailyMarketDataResearchProfile:
    return DailyMarketDataResearchProfile.model_validate(
        json.loads(PROFILE_FIXTURE_PATH.read_text())
    )


def _compatible_profile_for_v2(
    verified: VerifiedDailyMarketDataSnapshotV2,
    **overrides: object,
) -> DailyMarketDataResearchProfile:
    data: dict[str, Any] = {
        "schema_version": "1.0.0",
        "profile_id": "synthetic-v2-compatible-daily-etf-profile",
        "profile_policy_version": "synthetic-v2-compatible-profile-v1",
        "asset_class": verified.policy.asset_class,
        "frequency": verified.policy.frequency,
        "required_currency": verified.bar_provenance.currency,
        "permitted_temporal_coverage": (verified.bar_provenance.temporal_coverage,),
        "adjustment_policy": verified.policy.adjustment_policy,
        "distribution_treatment": verified.policy.distribution_treatment,
        "daily_bar_availability_policy": (
            DailyMarketDataBarAvailabilityPolicy.NEXT_EXPECTED_SESSION
        ),
        "allowed_corporate_action_completeness": (
            DailyMarketDataCorporateActionEvidenceCompleteness.CHECKED_EVENTS_CAPTURED,
            DailyMarketDataCorporateActionEvidenceCompleteness.CHECKED_NO_EVENTS,
        ),
        "supported_corporate_action_event_types": (
            DailyMarketDataCorporateActionEventType.CASH_DISTRIBUTION,
            DailyMarketDataCorporateActionEventType.SPLIT,
        ),
        "unsupported_events_allowed": False,
        "corporate_action_coverage_requirement": (
            "structured corporate-action evidence dates must cover the verified "
            "expected-session range"
        ),
        "calendar": verified.policy.calendar,
        "timezone": verified.policy.timezone,
        "session_source_id": verified.expected_sessions.session_source_id,
        "session_source_version": verified.expected_sessions.session_source_version,
        "universe_membership_policy": verified.policy.universe_membership_policy,
        "survivorship_policy": verified.policy.survivorship_policy,
        "delisting_policy": verified.policy.delisting_policy,
    }
    data.update(overrides)
    return DailyMarketDataResearchProfile(**data)


def _profile_variant(
    profile: DailyMarketDataResearchProfile,
    **overrides: object,
) -> DailyMarketDataResearchProfile:
    data = profile.model_dump(mode="json")
    data.update(overrides)
    return DailyMarketDataResearchProfile(**data)
