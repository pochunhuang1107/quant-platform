from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from backtest_engine import (
    ECONOMIC_EXECUTION_ENGINE_VERSION,
    BasisPointAssumption,
    ExecutionMetadata,
    ResolvedEconomicBacktestConfig,
)
from backtest_engine.snapshot_v2_input import (
    LoadedDailyMarketDataSnapshotV2,
    load_daily_market_data_snapshot_v2,
)
from helpers_daily_market_data_snapshots import (
    sample_expected_sessions,
    sample_policy,
)
from helpers_daily_market_data_snapshots_v2 import (
    sample_bar_provenance_input_v2,
    sample_corporate_action_evidence_v2,
)
from research_sdk.contracts.daily_market_data import (
    CanonicalDailyBar,
    DailyMarketDataInstrument,
)
from research_sdk.contracts.daily_market_data_economics import (
    DailyMarketDataBarAvailabilityPolicy,
    DailyMarketDataCorporateActionEvent,
    DailyMarketDataCorporateActionEventType,
    DailyMarketDataCorporateActionEvidenceCompleteness,
    DailyMarketDataResearchProfile,
)
from research_sdk.contracts.enums import TemporalCoverage
from research_sdk.daily_market_data_storage import plan_daily_market_data_snapshot_v2
from research_sdk.daily_market_data_storage.serialization import (
    render_canonical_daily_bars,
)

QQQ_INSTRUMENT_ID = "instrument-us-etf-qqq-xnas"
SPY_INSTRUMENT_ID = "instrument-us-etf-spy-arcx"
DEFAULT_SESSIONS = (
    date(2026, 1, 2),
    date(2026, 1, 5),
    date(2026, 1, 6),
    date(2026, 1, 7),
)


def qqq_bundle_files(
    *,
    sessions: tuple[date, ...] = DEFAULT_SESSIONS,
    bars: bytes | None = None,
    events: tuple[DailyMarketDataCorporateActionEvent, ...] = (),
    temporal_coverage: TemporalCoverage = TemporalCoverage.LATEST_KNOWN,
) -> dict[str, bytes]:
    return _bundle_files(
        symbol="QQQ",
        venue="XNAS",
        instrument_id=QQQ_INSTRUMENT_ID,
        sessions=sessions,
        bars=bars or _default_bars(symbol="QQQ", sessions=sessions),
        events=events,
        temporal_coverage=temporal_coverage,
    )


def spy_bundle_files(
    *,
    sessions: tuple[date, ...] = DEFAULT_SESSIONS,
    bars: bytes | None = None,
    events: tuple[DailyMarketDataCorporateActionEvent, ...] = (),
    temporal_coverage: TemporalCoverage = TemporalCoverage.LATEST_KNOWN,
) -> dict[str, bytes]:
    return _bundle_files(
        symbol="SPY",
        venue="ARCX",
        instrument_id=SPY_INSTRUMENT_ID,
        sessions=sessions,
        bars=bars or _default_bars(symbol="SPY", sessions=sessions),
        events=events,
        temporal_coverage=temporal_coverage,
    )


def _bundle_files(
    *,
    symbol: str,
    venue: str,
    instrument_id: str,
    sessions: tuple[date, ...],
    bars: bytes,
    events: tuple[DailyMarketDataCorporateActionEvent, ...],
    temporal_coverage: TemporalCoverage,
) -> dict[str, bytes]:
    instrument = DailyMarketDataInstrument(
        instrument_id=instrument_id,
        symbol=symbol,
        venue=venue,
    )
    timestamps = _timestamps_for(max(sessions))
    evidence = sample_corporate_action_evidence_v2(
        completeness=(
            DailyMarketDataCorporateActionEvidenceCompleteness.CHECKED_EVENTS_CAPTURED
            if events
            else DailyMarketDataCorporateActionEvidenceCompleteness.CHECKED_NO_EVENTS
        ),
        instrument=instrument,
        coverage_start_date=min(sessions),
        coverage_end_date=max(sessions),
        source_dataset=f"synthetic-s3d2b-{symbol.lower()}-actions",
        source_reference=f"fixtures/s3d2b/{symbol.lower()}-actions.json",
        source_content_hash=f"sha256:{('a' if symbol == 'QQQ' else 'b') * 64}",
        source_observed_at=timestamps["source_observed_at"],
        ingestion_completed_at=timestamps["ingestion_completed_at"],
        available_at=timestamps["available_at"],
        created_at=timestamps["created_at"],
        events=events,
    )
    provenance = sample_bar_provenance_input_v2(
        source_dataset=f"synthetic-s3d2b-{symbol.lower()}-bars",
        source_version="synthetic-s3d2b-v1",
        source_reference=f"fixtures/s3d2b/{symbol.lower()}-bars.jsonl",
        temporal_coverage=temporal_coverage,
        as_of=timestamps["as_of"],
        source_observed_at=timestamps["source_observed_at"],
        ingestion_completed_at=timestamps["ingestion_completed_at"],
        available_at=timestamps["available_at"],
        created_at=timestamps["created_at"],
        source_instrument_reference=instrument_id,
        currency="USD",
        known_limitations=(
            "synthetic S3d2b fixture only",
            "LATEST_KNOWN evidence is not point-in-time strategy knowledge",
            "not provider or production data",
            "not paper/live input",
        ),
    )
    return plan_daily_market_data_snapshot_v2(
        source_bytes=bars,
        instrument=instrument,
        policy=sample_policy(),
        expected_sessions=sample_expected_sessions(session_dates=sessions),
        bar_provenance_input=provenance,
        corporate_action_evidence=evidence,
    ).as_file_map()


def compatible_profile(
    qqq_files: dict[str, bytes],
    **overrides: object,
) -> DailyMarketDataResearchProfile:
    loaded: LoadedDailyMarketDataSnapshotV2 = load_daily_market_data_snapshot_v2(
        qqq_files
    )
    verified = loaded.verified_snapshot
    data: dict[str, object] = {
        "schema_version": "1.0.0",
        "profile_id": "synthetic-s3d2b-latest-known-daily-etf-profile",
        "profile_policy_version": "synthetic-s3d2b-profile-v1",
        "asset_class": verified.policy.asset_class,
        "frequency": verified.policy.frequency,
        "required_currency": verified.bar_provenance.currency,
        "permitted_temporal_coverage": (TemporalCoverage.LATEST_KNOWN,),
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
            "structured evidence covers every verified run session"
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


def resolved_config(
    *,
    sessions: tuple[date, ...] = DEFAULT_SESSIONS,
    **overrides: object,
) -> ResolvedEconomicBacktestConfig:
    data: dict[str, object] = {
        "experiment_id": "experiment-s3d2b-synthetic-economic-baseline-v1",
        "strategy_id": "qqq-unconditional-buy-and-hold",
        "strategy_version": "s3d2b-v1",
        "engine_version": ECONOMIC_EXECUTION_ENGINE_VERSION,
        "start_date": min(sessions),
        "end_date": max(sessions),
        "initial_capital": Decimal("100000"),
        "commission": BasisPointAssumption(
            bps=Decimal("1"),
            description="one basis point on QQQ executed notional",
        ),
        "slippage": BasisPointAssumption(
            bps=Decimal("2"),
            description="two basis points on QQQ first-session raw open",
        ),
        "no_randomness_reason": "deterministic unconditional baseline",
    }
    data.update(overrides)
    return ResolvedEconomicBacktestConfig(**data)


def execution_metadata(**overrides: object) -> ExecutionMetadata:
    data: dict[str, object] = {
        "git_commit_sha": "a" * 40,
        "repo_dirty": False,
        "python_version": "3.13.7",
        "platform": "synthetic-test-platform",
        "dependency_lock_hash": f"sha256:{'c' * 64}",
        "execution_command": "python -m synthetic_s3d2b_test",
    }
    data.update(overrides)
    return ExecutionMetadata(**data)


def bars_jsonl(
    rows: tuple[tuple[date, str, str, str, str, int], ...],
) -> bytes:
    return render_canonical_daily_bars(
        tuple(
            CanonicalDailyBar(
                session_date=session,
                open=Decimal(open_price),
                high=Decimal(high),
                low=Decimal(low),
                close=Decimal(close),
                volume=volume,
            )
            for session, open_price, high, low, close, volume in rows
        )
    )


def _default_bars(*, symbol: str, sessions: tuple[date, ...]) -> bytes:
    base = Decimal("100") if symbol == "QQQ" else Decimal("400")
    rows = []
    for index, session in enumerate(sessions):
        open_price = base + Decimal(index)
        rows.append(
            (
                session,
                format(open_price, "f"),
                format(open_price + Decimal("1"), "f"),
                format(open_price - Decimal("1"), "f"),
                format(open_price + Decimal("0.5"), "f"),
                1000 + index * 100,
            )
        )
    return bars_jsonl(tuple(rows))


def _timestamps_for(session: date) -> dict[str, datetime]:
    observed = datetime(session.year, session.month, session.day, 23, 45, tzinfo=UTC)
    return {
        "as_of": datetime(session.year, session.month, session.day, tzinfo=UTC),
        "source_observed_at": observed,
        "ingestion_completed_at": observed + timedelta(minutes=5),
        "available_at": observed + timedelta(minutes=10),
        "created_at": observed + timedelta(minutes=15),
    }


__all__ = [
    "DEFAULT_SESSIONS",
    "QQQ_INSTRUMENT_ID",
    "SPY_INSTRUMENT_ID",
    "bars_jsonl",
    "compatible_profile",
    "execution_metadata",
    "qqq_bundle_files",
    "resolved_config",
    "spy_bundle_files",
]
