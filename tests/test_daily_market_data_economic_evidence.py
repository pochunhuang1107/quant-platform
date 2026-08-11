from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

import research_sdk.daily_market_data as daily_market_data
from helpers_daily_market_data_snapshots import (
    sample_expected_sessions,
    sample_instrument,
    sample_policy,
    source_bytes,
)
from research_sdk.contracts import (
    DataAdjustmentPolicy,
    DataSourceType,
    TemporalCoverage,
)
from research_sdk.contracts.daily_market_data import (
    CanonicalDailyBar,
    DistributionTreatment,
)
from research_sdk.contracts.daily_market_data_economics import (
    DailyMarketDataBarAvailabilityPolicy,
    DailyMarketDataCashDistribution,
    DailyMarketDataCorporateActionEventType,
    DailyMarketDataCorporateActionEvidence,
    DailyMarketDataCorporateActionEvidenceCompleteness,
    DailyMarketDataResearchProfile,
    DailyMarketDataSplit,
    DailyMarketDataUnsupportedCorporateAction,
)
from research_sdk.contracts.daily_market_data_snapshots import (
    CORPORATE_ACTION_NOT_INTEGRATED_LIMITATION,
    CorporateActionEvidenceStatus,
    DailyMarketDataSnapshotProvenance,
)
from research_sdk.daily_market_data import (
    DailyMarketDataEconomicEvidenceCompatibilityError,
    derive_daily_market_data_corporate_action_content_hash,
    derive_daily_market_data_corporate_action_evidence_content_hash,
    evaluate_daily_market_data_quality,
    validate_daily_market_data_economic_evidence,
)
from research_sdk.daily_market_data_storage.planning import (
    PARSER_VERSION,
    PROVENANCE_POLICY_VERSION,
)
from research_sdk.daily_market_data_storage.serialization import sha256_bytes


def test_evidence_contract_accepts_checked_synthetic_cash_and_split() -> None:
    evidence = sample_corporate_action_evidence()

    assert evidence.completeness is (
        DailyMarketDataCorporateActionEvidenceCompleteness.CHECKED_EVENTS_CAPTURED
    )
    assert tuple(event.event_type for event in evidence.events) == (
        DailyMarketDataCorporateActionEventType.CASH_DISTRIBUTION,
        DailyMarketDataCorporateActionEventType.SPLIT,
    )
    assert evidence.known_limitations == (
        "synthetic corporate-action fixture only",
        "not historical market data",
        "not production source authority",
    )


def test_cash_distribution_rejects_float_nonpositive_and_datetime_dates() -> None:
    with pytest.raises(ValidationError, match="Decimal"):
        cash_distribution(amount=0.25)
    with pytest.raises(ValidationError, match="strictly positive"):
        cash_distribution(amount="0")
    with pytest.raises(ValidationError, match="date values only"):
        cash_distribution(ex_date=datetime(2026, 1, 3, tzinfo=UTC))


def test_source_event_reference_rejects_userinfo_and_obvious_tokens() -> None:
    with pytest.raises(ValidationError, match="userinfo"):
        cash_distribution(source_event_reference="https://user:secret@example.test/a")
    with pytest.raises(ValidationError, match="access tokens"):
        cash_distribution(
            source_event_reference="https://example.test/a?access_token=secret"
        )


def test_split_reduces_ratio_for_semantic_hash_and_rejects_empty_split() -> None:
    reduced = split(numerator=2, denominator=1)
    reducible = split(
        event_id="synthetic-event-split-20260104-copy",
        source_event_reference="synthetic/actions/split-copy-20260104",
        numerator=4,
        denominator=2,
    )

    assert reduced.canonical_numerator == 2
    assert reducible.canonical_numerator == 2
    assert _hash(events=(reduced,)) == _hash(events=(reducible,))
    with pytest.raises(ValidationError, match="1:1"):
        split(numerator=4, denominator=4)
    with pytest.raises(ValidationError, match="positive integers"):
        split(numerator=True)


def test_unsupported_event_preserves_fail_closed_evidence() -> None:
    unsupported = unsupported_event()

    assert unsupported.event_type is DailyMarketDataCorporateActionEventType.UNSUPPORTED
    assert unsupported.provider_event_type == "synthetic_unmodeled_action"


def test_evidence_completeness_rules_separate_empty_and_captured_sets() -> None:
    no_events = sample_corporate_action_evidence(
        completeness=(
            DailyMarketDataCorporateActionEvidenceCompleteness.CHECKED_NO_EVENTS
        ),
        events=(),
    )

    assert no_events.events == ()
    with pytest.raises(ValidationError, match="empty event set"):
        sample_corporate_action_evidence(
            completeness=(
                DailyMarketDataCorporateActionEvidenceCompleteness.CHECKED_NO_EVENTS
            )
        )
    with pytest.raises(ValidationError, match="at least one event"):
        sample_corporate_action_evidence(
            completeness=(
                DailyMarketDataCorporateActionEvidenceCompleteness.CHECKED_EVENTS_CAPTURED
            ),
            events=(),
        )


def test_evidence_rejects_duplicate_event_ids_out_of_order_and_coverage_gaps() -> None:
    first = cash_distribution()
    duplicate = split(event_id=first.event_id)
    with pytest.raises(ValidationError, match="unique"):
        sample_corporate_action_evidence(events=(first, duplicate))

    with pytest.raises(ValidationError, match="canonical"):
        sample_corporate_action_evidence(events=(split(), cash_distribution()))

    with pytest.raises(ValidationError, match="within coverage"):
        sample_corporate_action_evidence(
            events=(cash_distribution(ex_date=date(2026, 1, 6)),)
        )


def test_evidence_rejects_chronology_and_vendor_without_name() -> None:
    with pytest.raises(ValidationError, match="source_observed_at"):
        sample_corporate_action_evidence(
            source_observed_at=datetime(2026, 1, 6, 0, 1, tzinfo=UTC),
            ingestion_completed_at=datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
        )
    with pytest.raises(ValidationError, match="source_available_at"):
        sample_corporate_action_evidence(
            events=(
                cash_distribution(
                    source_available_at=datetime(2026, 1, 7, 0, 0, tzinfo=UTC)
                ),
            )
        )
    with pytest.raises(ValidationError, match="vendor_name"):
        sample_corporate_action_evidence(source_type=DataSourceType.VENDOR)


def test_semantic_hash_excludes_event_id_and_source_reference() -> None:
    original = cash_distribution()
    changed_lineage = cash_distribution(
        event_id="different-event-id",
        source_event_reference="different/synthetic/reference",
    )

    assert _hash(events=(original,)) == _hash(events=(changed_lineage,))


def test_semantic_hash_changes_for_economic_cash_fields() -> None:
    base = _hash(events=(cash_distribution(),))

    assert base != _hash(events=(cash_distribution(amount="0.30"),))
    assert base != _hash(events=(cash_distribution(currency="CAD"),))
    assert base != _hash(events=(cash_distribution(ex_date=date(2026, 1, 4)),))


def test_semantic_hash_changes_for_split_and_unsupported_fields() -> None:
    base_split = _hash(events=(split(),))
    base_unsupported = _hash(events=(unsupported_event(),))

    assert base_split != _hash(events=(split(numerator=3, denominator=1),))
    assert base_unsupported != _hash(
        events=(unsupported_event(provider_event_type="different_unmodeled_action"),)
    )


def test_semantic_hash_is_order_independent_and_binds_empty_coverage() -> None:
    cash = cash_distribution()
    split_event = split()

    assert _hash(events=(cash, split_event)) == _hash(events=(split_event, cash))
    assert _hash(events=()) != _hash(
        coverage_start_date=date(2026, 2, 2),
        coverage_end_date=date(2026, 2, 5),
        events=(),
    )
    assert derive_daily_market_data_corporate_action_evidence_content_hash(
        sample_corporate_action_evidence()
    ) == _hash(events=(cash, split_event))


def test_profile_contract_encodes_complete_daily_etf_candidate_policy() -> None:
    profile = sample_research_profile()

    assert profile.asset_class.value == "etfs"
    assert profile.adjustment_policy is DataAdjustmentPolicy.RAW
    assert profile.distribution_treatment is DistributionTreatment.EXPLICIT_CASH
    assert profile.daily_bar_availability_policy is (
        DailyMarketDataBarAvailabilityPolicy.NEXT_EXPECTED_SESSION
    )
    assert profile.unsupported_events_allowed is False
    assert set(profile.supported_corporate_action_event_types) == {
        DailyMarketDataCorporateActionEventType.CASH_DISTRIBUTION,
        DailyMarketDataCorporateActionEventType.SPLIT,
    }


def test_profile_rejects_price_return_only_as_complete_economic_policy() -> None:
    with pytest.raises(ValidationError, match="explicit cash"):
        sample_research_profile(
            distribution_treatment=DistributionTreatment.EXCLUDED_PRICE_RETURN_ONLY
        )
    with pytest.raises(ValidationError, match="raw OHLCV"):
        sample_research_profile(adjustment_policy=DataAdjustmentPolicy.SPLIT_ADJUSTED)


def test_economic_evidence_profile_coherence_passes_without_readiness_claim() -> None:
    result = validate_daily_market_data_economic_evidence(
        policy=sample_policy(),
        expected_sessions=sample_expected_sessions(),
        provenance=sample_snapshot_provenance(),
        quality_report=sample_quality_report(),
        corporate_action_evidence=sample_corporate_action_evidence(),
        research_profile=sample_research_profile(),
    )

    assert result.profile_id == "candidate-daily-etf-economic-evidence-v1"
    assert result.instrument_id == "instrument-us-etf-qqq-xnas"
    assert result.unsupported_event_count == 0
    assert result.s3b1_snapshot_identity_binds_economic_evidence is False
    assert not hasattr(
        daily_market_data,
        "validate_daily_market_data_research_readiness",
    )
    assert not hasattr(daily_market_data, "assess_daily_market_data_research_readiness")


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("currency", "CAD", "currency"),
        ("calendar", "DIFFERENT", "calendar"),
        ("timezone", "UTC", "timezone"),
        ("temporal_coverage", TemporalCoverage.POINT_IN_TIME, "temporal_coverage"),
    ],
)
def test_economic_evidence_profile_coherence_rejects_context_mismatches(
    field: str,
    value: object,
    match: str,
) -> None:
    kwargs = {field: value}
    provenance = (
        sample_snapshot_provenance(**kwargs)
        if field in {"currency", "temporal_coverage"}
        else sample_snapshot_provenance()
    )
    expected_sessions = (
        sample_expected_sessions(**kwargs)
        if field in {"calendar", "timezone"}
        else sample_expected_sessions()
    )

    with pytest.raises(DailyMarketDataEconomicEvidenceCompatibilityError, match=match):
        validate_daily_market_data_economic_evidence(
            policy=sample_policy(),
            expected_sessions=expected_sessions,
            provenance=provenance,
            quality_report=sample_quality_report(),
            corporate_action_evidence=sample_corporate_action_evidence(),
            research_profile=sample_research_profile(),
        )


def test_economic_evidence_profile_coherence_rejects_evidence_failures() -> None:
    failing_quality = sample_quality_report(
        bars=(sample_bars()[0].model_copy(update={"volume": 0}), sample_bars()[1])
    )
    with pytest.raises(DailyMarketDataEconomicEvidenceCompatibilityError, match="pass"):
        validate_daily_market_data_economic_evidence(
            policy=sample_policy(),
            expected_sessions=sample_expected_sessions(),
            provenance=sample_snapshot_provenance(),
            quality_report=failing_quality,
            corporate_action_evidence=sample_corporate_action_evidence(),
            research_profile=sample_research_profile(),
        )

    with pytest.raises(
        DailyMarketDataEconomicEvidenceCompatibilityError, match="cover"
    ):
        validate_daily_market_data_economic_evidence(
            policy=sample_policy(),
            expected_sessions=sample_expected_sessions(),
            provenance=sample_snapshot_provenance(),
            quality_report=sample_quality_report(),
            corporate_action_evidence=sample_corporate_action_evidence(
                coverage_end_date=date(2026, 1, 4)
            ),
            research_profile=sample_research_profile(),
        )

    with pytest.raises(
        DailyMarketDataEconomicEvidenceCompatibilityError, match="instrument"
    ):
        validate_daily_market_data_economic_evidence(
            policy=sample_policy(),
            expected_sessions=sample_expected_sessions(),
            provenance=sample_snapshot_provenance(),
            quality_report=sample_quality_report(),
            corporate_action_evidence=sample_corporate_action_evidence(
                instrument=sample_instrument().model_copy(
                    update={"instrument_id": "instrument-other"}
                ),
                events=(),
                completeness=(
                    DailyMarketDataCorporateActionEvidenceCompleteness.CHECKED_NO_EVENTS
                ),
            ),
            research_profile=sample_research_profile(),
        )


def test_unsupported_events_fail_complete_economic_profile_coherence() -> None:
    with pytest.raises(
        DailyMarketDataEconomicEvidenceCompatibilityError,
        match="unsupported",
    ):
        validate_daily_market_data_economic_evidence(
            policy=sample_policy(),
            expected_sessions=sample_expected_sessions(),
            provenance=sample_snapshot_provenance(),
            quality_report=sample_quality_report(),
            corporate_action_evidence=sample_corporate_action_evidence(
                events=(unsupported_event(),)
            ),
            research_profile=sample_research_profile(),
        )


def test_v1_not_integrated_provenance_remains_separate_from_s3c1_evidence() -> None:
    provenance = sample_snapshot_provenance(
        corporate_action_evidence_status=CorporateActionEvidenceStatus.NOT_INTEGRATED,
        known_limitations=(
            CORPORATE_ACTION_NOT_INTEGRATED_LIMITATION,
            "synthetic infrastructure fixture only",
            "not historical performance evidence",
        ),
    )

    result = validate_daily_market_data_economic_evidence(
        policy=sample_policy(),
        expected_sessions=sample_expected_sessions(),
        provenance=provenance,
        quality_report=sample_quality_report(),
        corporate_action_evidence=sample_corporate_action_evidence(),
        research_profile=sample_research_profile(),
    )

    assert result.s3b1_snapshot_identity_binds_economic_evidence is False


def cash_distribution(**overrides: object) -> DailyMarketDataCashDistribution:
    data = {
        "schema_version": "1.0.0",
        "event_id": "synthetic-event-cash-20260103",
        "instrument_id": "instrument-us-etf-qqq-xnas",
        "source_event_reference": "synthetic/actions/cash-20260103",
        "source_available_at": datetime(2026, 1, 1, 16, 0, tzinfo=UTC),
        "event_type": DailyMarketDataCorporateActionEventType.CASH_DISTRIBUTION,
        "ex_date": date(2026, 1, 3),
        "amount": Decimal("0.25"),
        "currency": "USD",
        "record_date": date(2026, 1, 4),
        "payable_date": date(2026, 1, 8),
        "announced_at": datetime(2026, 1, 1, 15, 0, tzinfo=UTC),
        "distribution_classification": "synthetic cash distribution",
    }
    data.update(overrides)
    return DailyMarketDataCashDistribution(**data)


def split(**overrides: object) -> DailyMarketDataSplit:
    data = {
        "schema_version": "1.0.0",
        "event_id": "synthetic-event-split-20260104",
        "instrument_id": "instrument-us-etf-qqq-xnas",
        "source_event_reference": "synthetic/actions/split-20260104",
        "source_available_at": datetime(2026, 1, 2, 16, 0, tzinfo=UTC),
        "event_type": DailyMarketDataCorporateActionEventType.SPLIT,
        "effective_date": date(2026, 1, 4),
        "numerator": 2,
        "denominator": 1,
    }
    data.update(overrides)
    return DailyMarketDataSplit(**data)


def unsupported_event(
    **overrides: object,
) -> DailyMarketDataUnsupportedCorporateAction:
    data = {
        "schema_version": "1.0.0",
        "event_id": "synthetic-event-unsupported-20260103",
        "instrument_id": "instrument-us-etf-qqq-xnas",
        "source_event_reference": "synthetic/actions/unsupported-20260103",
        "source_available_at": datetime(2026, 1, 1, 16, 0, tzinfo=UTC),
        "event_type": DailyMarketDataCorporateActionEventType.UNSUPPORTED,
        "provider_event_type": "synthetic_unmodeled_action",
        "effective_date": date(2026, 1, 3),
        "description": "synthetic unsupported event",
    }
    data.update(overrides)
    return DailyMarketDataUnsupportedCorporateAction(**data)


def sample_corporate_action_evidence(
    **overrides: object,
) -> DailyMarketDataCorporateActionEvidence:
    data = {
        "schema_version": "1.0.0",
        "evidence_policy_version": "daily-market-data-corporate-action-evidence-v1",
        "completeness": (
            DailyMarketDataCorporateActionEvidenceCompleteness.CHECKED_EVENTS_CAPTURED
        ),
        "instrument": sample_instrument(),
        "coverage_start_date": date(2026, 1, 2),
        "coverage_end_date": date(2026, 1, 5),
        "source_dataset": "synthetic-corporate-action-fixture",
        "source_version": "2026-01-synthetic-actions-v1",
        "source_type": DataSourceType.RESEARCH_GENERATED,
        "source_reference": "fixtures/corporate-actions/synthetic-actions-v1.jsonl",
        "source_content_hash": f"sha256:{'a' * 64}",
        "source_size_bytes": 321,
        "source_observed_at": datetime(2026, 1, 5, 23, 50, tzinfo=UTC),
        "ingestion_completed_at": datetime(2026, 1, 5, 23, 55, tzinfo=UTC),
        "available_at": datetime(2026, 1, 5, 23, 58, tzinfo=UTC),
        "created_at": datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
        "created_by": "agent-codex",
        "canonicalization_version": ("daily-market-data-corporate-actions-v1"),
        "events": (cash_distribution(), split()),
        "known_limitations": (
            "synthetic corporate-action fixture only",
            "not historical market data",
            "not production source authority",
        ),
    }
    data.update(overrides)
    return DailyMarketDataCorporateActionEvidence(**data)


def sample_research_profile(**overrides: object) -> DailyMarketDataResearchProfile:
    data = {
        "schema_version": "1.0.0",
        "profile_id": "candidate-daily-etf-economic-evidence-v1",
        "profile_policy_version": "daily-etf-economic-evidence-profile-v1",
        "asset_class": "etfs",
        "frequency": "daily",
        "required_currency": "USD",
        "permitted_temporal_coverage": (TemporalCoverage.LATEST_KNOWN,),
        "adjustment_policy": DataAdjustmentPolicy.RAW,
        "distribution_treatment": DistributionTreatment.EXPLICIT_CASH,
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
            "corporate-action evidence coverage must cover the full expected "
            "bar-session coverage"
        ),
        "calendar": "XNYS",
        "timezone": "America/New_York",
        "session_source_id": "synthetic-session-fixture-v1",
        "session_source_version": "2026-01-fixture",
        "universe_membership_policy": "static explicit instrument universe",
        "survivorship_policy": "static named instrument; no survivorship-free claim",
        "delisting_policy": "unsupported for ETF S3a; fail closed if encountered",
    }
    data.update(overrides)
    return DailyMarketDataResearchProfile(**data)


def sample_snapshot_provenance(
    **overrides: object,
) -> DailyMarketDataSnapshotProvenance:
    data = {
        "schema_version": "1.0.0",
        "provenance_policy_version": PROVENANCE_POLICY_VERSION,
        "created_at": datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
        "created_by": "agent-codex",
        "source_dataset": "synthetic-daily-market-data-fixture",
        "source_version": "2026-01-synthetic-v1",
        "source_type": DataSourceType.RESEARCH_GENERATED,
        "source_reference": "fixtures/daily-market-data/synthetic-bars-v1.jsonl",
        "source_content_hash": sha256_bytes(source_bytes()),
        "source_size_bytes": len(source_bytes()),
        "parser_version": PARSER_VERSION,
        "temporal_coverage": TemporalCoverage.LATEST_KNOWN,
        "as_of": datetime(2026, 1, 5, 0, 0, tzinfo=UTC),
        "ingestion_completed_at": datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
        "available_at": datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
        "source_instrument_reference": "instrument-us-etf-qqq-xnas",
        "currency": "USD",
        "known_limitations": (
            CORPORATE_ACTION_NOT_INTEGRATED_LIMITATION,
            "synthetic infrastructure fixture only",
            "not historical performance evidence",
        ),
        "corporate_action_evidence_status": (
            CorporateActionEvidenceStatus.NOT_INTEGRATED
        ),
    }
    data.update(overrides)
    return DailyMarketDataSnapshotProvenance(**data)


def sample_bars() -> tuple[CanonicalDailyBar, ...]:
    return (
        CanonicalDailyBar(
            session_date=date(2026, 1, 2),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100.5"),
            volume=1000,
        ),
        CanonicalDailyBar(
            session_date=date(2026, 1, 5),
            open=Decimal("101"),
            high=Decimal("102"),
            low=Decimal("100"),
            close=Decimal("101.5"),
            volume=1100,
        ),
    )


def sample_quality_report(
    *,
    bars: tuple[CanonicalDailyBar, ...] | None = None,
):
    return evaluate_daily_market_data_quality(
        instrument=sample_instrument(),
        bars=sample_bars() if bars is None else bars,
        expected_session_dates=sample_expected_sessions().session_dates,
        policy=sample_policy(),
    )


def _hash(
    *,
    coverage_start_date: date = date(2026, 1, 2),
    coverage_end_date: date = date(2026, 1, 5),
    events: tuple[
        DailyMarketDataCashDistribution
        | DailyMarketDataSplit
        | DailyMarketDataUnsupportedCorporateAction,
        ...,
    ],
) -> str:
    return derive_daily_market_data_corporate_action_content_hash(
        instrument=sample_instrument(),
        coverage_start_date=coverage_start_date,
        coverage_end_date=coverage_end_date,
        events=events,
    )
