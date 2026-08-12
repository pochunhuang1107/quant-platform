from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from helpers_daily_market_data_snapshots import (
    EXPECTED_SESSIONS_HASH,
    POLICY_HASH,
    S3A_GOLDEN_CONTENT_HASH,
    sample_expected_sessions,
    sample_instrument,
    sample_policy,
    source_bytes,
)
from research_sdk.contracts.daily_market_data_economics import (
    DailyMarketDataCashDistribution,
    DailyMarketDataCorporateActionEventType,
    DailyMarketDataCorporateActionEvidence,
    DailyMarketDataCorporateActionEvidenceCompleteness,
    DailyMarketDataSplit,
    DailyMarketDataUnsupportedCorporateAction,
)
from research_sdk.contracts.enums import DataSourceType, TemporalCoverage
from research_sdk.daily_market_data_storage import (
    DailyMarketDataBarSourceProvenanceInputV2,
    DailyMarketDataSnapshotPlanV2,
    plan_daily_market_data_snapshot_v2,
)

BAR_PROVENANCE_HASH_V2 = (
    "sha256:e10a9054160ca8f5009582350f391847ab61a8cecc63cc6e950aac9b2f9a0d4b"
)
CORPORATE_ACTION_SEMANTIC_HASH = (
    "sha256:548a9a9de5da0c18ec20a95f8e0efcbc09a61031b8b85259942fa56beab091d9"
)
CORPORATE_ACTION_EVIDENCE_AUTHORITY_HASH = (
    "sha256:1e9f5198d52952075919981e15faae01817e6afc06e0f811834971bf2f0bc658"
)
SNAPSHOT_ID_V2 = (
    "daily-market-data-snapshot-v2-"
    "1c3330ff28e07de31a10b9337b503fdf069c1216e51f3950242862be61b1f07d"
)


def cash_distribution_v2(**overrides: object) -> DailyMarketDataCashDistribution:
    data = {
        "schema_version": "1.0.0",
        "event_id": "synthetic-v2-event-cash-20260103",
        "instrument_id": "instrument-us-etf-qqq-xnas",
        "source_event_reference": "synthetic-v2/actions/cash-20260103",
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


def split_v2(**overrides: object) -> DailyMarketDataSplit:
    data = {
        "schema_version": "1.0.0",
        "event_id": "synthetic-v2-event-split-20260104",
        "instrument_id": "instrument-us-etf-qqq-xnas",
        "source_event_reference": "synthetic-v2/actions/split-20260104",
        "source_available_at": datetime(2026, 1, 2, 16, 0, tzinfo=UTC),
        "event_type": DailyMarketDataCorporateActionEventType.SPLIT,
        "effective_date": date(2026, 1, 4),
        "numerator": 2,
        "denominator": 1,
    }
    data.update(overrides)
    return DailyMarketDataSplit(**data)


def unsupported_event_v2(
    **overrides: object,
) -> DailyMarketDataUnsupportedCorporateAction:
    data = {
        "schema_version": "1.0.0",
        "event_id": "synthetic-v2-event-unsupported-20260103",
        "instrument_id": "instrument-us-etf-qqq-xnas",
        "source_event_reference": "synthetic-v2/actions/unsupported-20260103",
        "source_available_at": datetime(2026, 1, 1, 16, 0, tzinfo=UTC),
        "event_type": DailyMarketDataCorporateActionEventType.UNSUPPORTED,
        "provider_event_type": "synthetic_unmodeled_action",
        "effective_date": date(2026, 1, 3),
        "description": "synthetic unsupported event",
    }
    data.update(overrides)
    return DailyMarketDataUnsupportedCorporateAction(**data)


def sample_corporate_action_evidence_v2(
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
        "source_dataset": "synthetic-v2-corporate-action-fixture",
        "source_version": "2026-01-synthetic-actions-v1",
        "source_type": DataSourceType.RESEARCH_GENERATED,
        "source_reference": "fixtures/corporate-actions/synthetic-v2-actions-v1.json",
        "source_content_hash": f"sha256:{'a' * 64}",
        "source_size_bytes": 321,
        "source_observed_at": datetime(2026, 1, 5, 23, 50, tzinfo=UTC),
        "ingestion_completed_at": datetime(2026, 1, 5, 23, 55, tzinfo=UTC),
        "available_at": datetime(2026, 1, 5, 23, 58, tzinfo=UTC),
        "created_at": datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
        "created_by": "agent-codex",
        "canonicalization_version": "daily-market-data-corporate-actions-v1",
        "events": (cash_distribution_v2(), split_v2()),
        "known_limitations": (
            "synthetic corporate-action fixture only",
            "not historical market data",
            "not production source authority",
        ),
    }
    data.update(overrides)
    return DailyMarketDataCorporateActionEvidence(**data)


def sample_bar_provenance_input_v2(
    **overrides: object,
) -> DailyMarketDataBarSourceProvenanceInputV2:
    data = {
        "created_at": datetime(2026, 1, 5, 23, 56, tzinfo=UTC),
        "created_by": "agent-codex",
        "source_dataset": "synthetic-daily-market-data-fixture",
        "source_version": "2026-01-synthetic-v1",
        "source_type": DataSourceType.RESEARCH_GENERATED,
        "source_reference": "fixtures/daily-market-data/synthetic-bars-v1.jsonl",
        "temporal_coverage": TemporalCoverage.NOT_APPLICABLE,
        "as_of": datetime(2026, 1, 5, 0, 0, tzinfo=UTC),
        "source_observed_at": datetime(2026, 1, 5, 23, 45, tzinfo=UTC),
        "ingestion_completed_at": datetime(2026, 1, 5, 23, 50, tzinfo=UTC),
        "available_at": datetime(2026, 1, 5, 23, 55, tzinfo=UTC),
        "source_instrument_reference": "instrument-us-etf-qqq-xnas",
        "currency": "USD",
        "known_limitations": (
            "synthetic bar fixture only",
            "not historical performance evidence",
            "not production source authority",
            "not paper/live input",
        ),
    }
    data.update(overrides)
    return DailyMarketDataBarSourceProvenanceInputV2(**data)


def sample_plan_v2(**overrides: object) -> DailyMarketDataSnapshotPlanV2:
    data = {
        "source_bytes": source_bytes(),
        "instrument": sample_instrument(),
        "policy": sample_policy(),
        "expected_sessions": sample_expected_sessions(),
        "bar_provenance_input": sample_bar_provenance_input_v2(),
        "corporate_action_evidence": sample_corporate_action_evidence_v2(),
    }
    data.update(overrides)
    return plan_daily_market_data_snapshot_v2(**data)


__all__ = [
    "BAR_PROVENANCE_HASH_V2",
    "CORPORATE_ACTION_EVIDENCE_AUTHORITY_HASH",
    "CORPORATE_ACTION_SEMANTIC_HASH",
    "EXPECTED_SESSIONS_HASH",
    "POLICY_HASH",
    "S3A_GOLDEN_CONTENT_HASH",
    "SNAPSHOT_ID_V2",
    "cash_distribution_v2",
    "sample_bar_provenance_input_v2",
    "sample_corporate_action_evidence_v2",
    "sample_plan_v2",
    "split_v2",
    "unsupported_event_v2",
]
