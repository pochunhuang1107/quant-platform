from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from research_sdk.contracts import AssetClass, DataAdjustmentPolicy
from research_sdk.contracts.daily_market_data import (
    DailyMarketDataInstrument,
    DailyMarketDataPolicy,
    DistributionTreatment,
)
from research_sdk.contracts.daily_market_data_snapshots import (
    CORPORATE_ACTION_NOT_INTEGRATED_LIMITATION,
    CorporateActionEvidenceStatus,
    DailyMarketDataExpectedSessions,
)
from research_sdk.contracts.enums import DataSourceType, TemporalCoverage
from research_sdk.daily_market_data_storage import (
    DailyMarketDataSnapshotPlan,
    DailyMarketDataSnapshotProvenanceInput,
    plan_daily_market_data_snapshot,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_FIXTURE_PATH = (
    REPO_ROOT / "tests" / "fixtures" / "daily_market_data" / "synthetic-bars-v1.jsonl"
)
CANONICAL_BARS_BYTES = (
    b'{"close":"100.5","high":"101","low":"99","open":"100",'
    b'"session_date":"2026-01-02","volume":1000}\n'
    b'{"close":"101.5","high":"102","low":"100","open":"101",'
    b'"session_date":"2026-01-05","volume":1100}\n'
)
S3A_GOLDEN_CONTENT_HASH = (
    "sha256:93ec3e3e9fb514519e1131b27f04032c2737bdae0bc5ca7d2f57cf570e3b9e85"
)
BARS_STORAGE_HASH = (
    "sha256:1c783ebfb8db7453593961e9f336eec5b268741e54dafb706017bed832e19b7d"
)
POLICY_HASH = "sha256:e25dd8e0659834ef5a94f3a5ae50e1f8301307f99bf30b9c746ac0e223e37fcb"
EXPECTED_SESSIONS_HASH = (
    "sha256:87d2549180b5247e9f668253caf0f906e0d1cbe17898fbe5fc1ae4ba0491db39"
)
PROVENANCE_HASH = (
    "sha256:d5a55b33fb41662146b4e6042fe9f54aca8d05ab5cae05a64570d1775ec71618"
)
SNAPSHOT_ID = (
    "daily-market-data-snapshot-v1-"
    "0ed0582f66c00f4f03f902c68353282a445753d20d4f8f91e0fd52b74c93c891"
)


def source_bytes() -> bytes:
    return SOURCE_FIXTURE_PATH.read_bytes()


def sample_instrument() -> DailyMarketDataInstrument:
    return DailyMarketDataInstrument(
        instrument_id="instrument-us-etf-qqq-xnas",
        symbol="QQQ",
        venue="XNAS",
    )


def sample_policy(**overrides: object) -> DailyMarketDataPolicy:
    data = {
        "schema_version": "1.0.0",
        "policy_id": "daily-market-data-etf-execution-v1",
        "asset_class": AssetClass.ETFS,
        "frequency": "daily",
        "calendar": "XNYS",
        "timezone": "America/New_York",
        "adjustment_policy": DataAdjustmentPolicy.RAW,
        "distribution_treatment": DistributionTreatment.EXPLICIT_CASH,
        "corporate_action_policy": "raw OHLCV plus explicit corporate-action evidence",
        "universe_membership_policy": "static explicit instrument universe",
        "survivorship_policy": "static named instrument; no survivorship-free claim",
        "delisting_policy": "unsupported for ETF S3a; fail closed if encountered",
        "canonicalization_version": "daily-market-data-canonical-v1",
        "quality_policy_version": "daily-market-data-quality-v1",
    }
    data.update(overrides)
    return DailyMarketDataPolicy(**data)


def sample_expected_sessions(**overrides: object) -> DailyMarketDataExpectedSessions:
    data = {
        "schema_version": "1.0.0",
        "session_source_id": "synthetic-session-fixture-v1",
        "session_source_version": "2026-01-fixture",
        "calendar": "XNYS",
        "timezone": "America/New_York",
        "session_dates": (date(2026, 1, 2), date(2026, 1, 5)),
    }
    data.update(overrides)
    return DailyMarketDataExpectedSessions(**data)


def sample_provenance_input(
    **overrides: object,
) -> DailyMarketDataSnapshotProvenanceInput:
    data = {
        "created_at": datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
        "created_by": "agent-codex",
        "source_dataset": "synthetic-daily-market-data-fixture",
        "source_version": "2026-01-synthetic-v1",
        "source_type": DataSourceType.RESEARCH_GENERATED,
        "source_reference": "fixtures/daily-market-data/synthetic-bars-v1.jsonl",
        "temporal_coverage": TemporalCoverage.NOT_APPLICABLE,
        "as_of": datetime(2026, 1, 5, 0, 0, tzinfo=UTC),
        "ingestion_completed_at": datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
        "available_at": datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
        "source_instrument_reference": "instrument-us-etf-qqq-xnas",
        "currency": "USD",
        "known_limitations": (
            CORPORATE_ACTION_NOT_INTEGRATED_LIMITATION,
            "synthetic infrastructure fixture only",
            "not historical performance evidence",
            "not paper/live input",
        ),
        "corporate_action_evidence_status": (
            CorporateActionEvidenceStatus.NOT_INTEGRATED
        ),
    }
    data.update(overrides)
    return DailyMarketDataSnapshotProvenanceInput(**data)


def sample_plan(**overrides: object) -> DailyMarketDataSnapshotPlan:
    data = {
        "source_bytes": source_bytes(),
        "instrument": sample_instrument(),
        "policy": sample_policy(),
        "expected_sessions": sample_expected_sessions(),
        "provenance_input": sample_provenance_input(),
    }
    data.update(overrides)
    return plan_daily_market_data_snapshot(**data)
