"""Snapshot-v2 QQQ/SPY execution-input pair compatibility."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, model_validator

from backtest_engine.snapshot_v2_input import (
    LoadedDailyMarketDataSnapshotV2,
    load_daily_market_data_snapshot_v2,
)
from research_sdk.contracts.daily_market_data import (
    DAILY_MARKET_DATA_FREQUENCY,
    CanonicalDailyBar,
)
from research_sdk.contracts.daily_market_data_economics import (
    DailyMarketDataBarAvailabilityPolicy,
    DailyMarketDataResearchProfile,
    DailyMarketDataUnsupportedCorporateAction,
    corporate_action_event_economic_date,
)
from research_sdk.daily_market_data import (
    DailyMarketDataSnapshotProfileCompatibility,
    derive_daily_market_data_research_profile_hash,
    validate_daily_market_data_snapshot_profile_compatibility,
)


class DailyMarketDataSnapshotPairError(ValueError):
    """Raised when a snapshot-v2 asset/benchmark pair is not execution coherent."""


class SnapshotPairModel(PydanticBaseModel):
    """Frozen operational model base for S3d2a snapshot pairs."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)


class DailyMarketDataSnapshotPairV2(SnapshotPairModel):
    """Loaded snapshot-v2 pair projected to one exact daily run window."""

    asset: LoadedDailyMarketDataSnapshotV2
    benchmark: LoadedDailyMarketDataSnapshotV2
    asset_profile_compatibility: DailyMarketDataSnapshotProfileCompatibility
    benchmark_profile_compatibility: DailyMarketDataSnapshotProfileCompatibility
    profile_hash: str
    start_date: date
    end_date: date
    run_session_dates: tuple[date, ...]
    asset_run_bars: tuple[CanonicalDailyBar, ...]
    benchmark_run_bars: tuple[CanonicalDailyBar, ...]

    @model_validator(mode="after")
    def validate_pair_projection(self) -> DailyMarketDataSnapshotPairV2:
        if tuple(bar.session_date for bar in self.asset_run_bars) != (
            self.run_session_dates
        ):
            raise ValueError("asset_run_bars must match run_session_dates")
        if tuple(bar.session_date for bar in self.benchmark_run_bars) != (
            self.run_session_dates
        ):
            raise ValueError("benchmark_run_bars must match run_session_dates")
        return self


def prepare_daily_market_data_snapshot_pair_v2(
    *,
    asset_files: Mapping[str, bytes],
    benchmark_files: Mapping[str, bytes],
    research_profile: DailyMarketDataResearchProfile,
    start_date: date,
    end_date: date,
) -> DailyMarketDataSnapshotPairV2:
    """Load and validate the first QQQ/SPY snapshot-v2 execution input pair."""

    asset = load_daily_market_data_snapshot_v2(asset_files)
    benchmark = load_daily_market_data_snapshot_v2(benchmark_files)
    profile = DailyMarketDataResearchProfile.model_validate(
        research_profile.model_dump(mode="json")
    )

    asset_compatibility = _validate_profile_compatibility(
        loaded=asset,
        research_profile=profile,
        role="asset",
    )
    benchmark_compatibility = _validate_profile_compatibility(
        loaded=benchmark,
        research_profile=profile,
        role="benchmark",
    )
    expected_profile_hash = derive_daily_market_data_research_profile_hash(profile)
    _require(
        asset_compatibility.profile_hash == expected_profile_hash,
        "asset profile hash must match supplied research profile",
    )
    _require(
        benchmark_compatibility.profile_hash == expected_profile_hash,
        "benchmark profile hash must match supplied research profile",
    )
    _require(
        asset_compatibility.profile_hash == benchmark_compatibility.profile_hash,
        "asset and benchmark profile hashes must match",
    )
    _require_next_expected_session(asset_compatibility, role="asset")
    _require_next_expected_session(benchmark_compatibility, role="benchmark")
    _validate_pair_roles(asset=asset, benchmark=benchmark)
    _validate_pair_policy_coherence(asset=asset, benchmark=benchmark)

    run_session_dates = _derive_run_sessions(
        asset=asset,
        benchmark=benchmark,
        start_date=start_date,
        end_date=end_date,
    )
    _validate_corporate_action_projection(
        loaded=asset,
        role="asset",
        start_date=start_date,
        end_date=end_date,
        run_session_dates=run_session_dates,
    )
    _validate_corporate_action_projection(
        loaded=benchmark,
        role="benchmark",
        start_date=start_date,
        end_date=end_date,
        run_session_dates=run_session_dates,
    )
    return DailyMarketDataSnapshotPairV2(
        asset=asset,
        benchmark=benchmark,
        asset_profile_compatibility=asset_compatibility,
        benchmark_profile_compatibility=benchmark_compatibility,
        profile_hash=asset_compatibility.profile_hash,
        start_date=start_date,
        end_date=end_date,
        run_session_dates=run_session_dates,
        asset_run_bars=_project_run_bars(
            loaded=asset,
            role="asset",
            start_date=start_date,
            end_date=end_date,
            run_session_dates=run_session_dates,
        ),
        benchmark_run_bars=_project_run_bars(
            loaded=benchmark,
            role="benchmark",
            start_date=start_date,
            end_date=end_date,
            run_session_dates=run_session_dates,
        ),
    )


def _validate_profile_compatibility(
    *,
    loaded: LoadedDailyMarketDataSnapshotV2,
    research_profile: DailyMarketDataResearchProfile,
    role: str,
) -> DailyMarketDataSnapshotProfileCompatibility:
    try:
        return validate_daily_market_data_snapshot_profile_compatibility(
            verified_snapshot=loaded.verified_snapshot,
            research_profile=research_profile,
        )
    except Exception as exc:
        raise DailyMarketDataSnapshotPairError(
            f"{role} snapshot/profile compatibility failed: {exc}"
        ) from exc


def _require_next_expected_session(
    compatibility: DailyMarketDataSnapshotProfileCompatibility,
    *,
    role: str,
) -> None:
    _require(
        compatibility.required_daily_bar_availability_policy
        is DailyMarketDataBarAvailabilityPolicy.NEXT_EXPECTED_SESSION,
        f"{role} compatibility must require next-expected-session availability",
    )


def _validate_pair_roles(
    *,
    asset: LoadedDailyMarketDataSnapshotV2,
    benchmark: LoadedDailyMarketDataSnapshotV2,
) -> None:
    asset_verified = asset.verified_snapshot
    benchmark_verified = benchmark.verified_snapshot
    _require(
        asset_verified.snapshot_id != benchmark_verified.snapshot_id,
        "asset and benchmark snapshot IDs must be distinct",
    )
    _require(
        asset_verified.instrument_id != benchmark_verified.instrument_id,
        "asset and benchmark instrument IDs must be distinct",
    )
    _require(
        asset_verified.quality_report.instrument.symbol == "QQQ",
        "asset snapshot symbol must be QQQ",
    )
    _require(
        benchmark_verified.quality_report.instrument.symbol == "SPY",
        "benchmark snapshot symbol must be SPY",
    )


def _validate_pair_policy_coherence(
    *,
    asset: LoadedDailyMarketDataSnapshotV2,
    benchmark: LoadedDailyMarketDataSnapshotV2,
) -> None:
    asset_verified = asset.verified_snapshot
    benchmark_verified = benchmark.verified_snapshot
    _require(
        asset_verified.policy.frequency == DAILY_MARKET_DATA_FREQUENCY
        and benchmark_verified.policy.frequency == DAILY_MARKET_DATA_FREQUENCY,
        "asset and benchmark frequency must be daily",
    )
    for field_name in ("frequency", "calendar", "timezone"):
        _require(
            getattr(asset_verified.policy, field_name)
            == getattr(benchmark_verified.policy, field_name),
            f"asset and benchmark policy {field_name} must match",
        )
    for field_name in (
        "calendar",
        "timezone",
        "session_source_id",
        "session_source_version",
    ):
        _require(
            getattr(asset_verified.expected_sessions, field_name)
            == getattr(benchmark_verified.expected_sessions, field_name),
            f"asset and benchmark expected-session {field_name} must match",
        )
    _require(
        asset_verified.bar_provenance.currency
        == benchmark_verified.bar_provenance.currency,
        "asset and benchmark currencies must match",
    )


def _derive_run_sessions(
    *,
    asset: LoadedDailyMarketDataSnapshotV2,
    benchmark: LoadedDailyMarketDataSnapshotV2,
    start_date: date,
    end_date: date,
) -> tuple[date, ...]:
    _validate_date(start_date, field_name="start_date")
    _validate_date(end_date, field_name="end_date")
    _require(start_date <= end_date, "start_date must be on or before end_date")

    asset_sessions = asset.verified_snapshot.expected_sessions.session_dates
    benchmark_sessions = benchmark.verified_snapshot.expected_sessions.session_dates
    _require(
        start_date in asset_sessions and start_date in benchmark_sessions,
        "start_date must be expected by both snapshots",
    )
    _require(
        end_date in asset_sessions and end_date in benchmark_sessions,
        "end_date must be expected by both snapshots",
    )

    asset_run_sessions = tuple(
        session_date
        for session_date in asset_sessions
        if start_date <= session_date <= end_date
    )
    benchmark_run_sessions = tuple(
        session_date
        for session_date in benchmark_sessions
        if start_date <= session_date <= end_date
    )
    _require(
        asset_run_sessions == benchmark_run_sessions,
        "asset and benchmark run sessions must match exactly",
    )
    _require(
        len(asset_run_sessions) >= 2,
        "at least two run sessions are required",
    )
    return asset_run_sessions


def _project_run_bars(
    *,
    loaded: LoadedDailyMarketDataSnapshotV2,
    role: str,
    start_date: date,
    end_date: date,
    run_session_dates: tuple[date, ...],
) -> tuple[CanonicalDailyBar, ...]:
    bars_by_date: dict[date, CanonicalDailyBar] = {}
    for bar in loaded.bars:
        if start_date <= bar.session_date <= end_date:
            _require(
                bar.session_date not in bars_by_date,
                f"{role} run bars must have unique session dates",
            )
            bars_by_date[bar.session_date] = bar
    actual_run_dates = tuple(sorted(bars_by_date))
    _require(
        actual_run_dates == run_session_dates,
        f"{role} run bars must exactly match run sessions",
    )
    return tuple(bars_by_date[session_date] for session_date in run_session_dates)


def _validate_corporate_action_projection(
    *,
    loaded: LoadedDailyMarketDataSnapshotV2,
    role: str,
    start_date: date,
    end_date: date,
    run_session_dates: tuple[date, ...],
) -> None:
    run_session_set = set(run_session_dates)
    for event in loaded.verified_snapshot.corporate_action_evidence.events:
        economic_date = corporate_action_event_economic_date(event)
        if start_date <= economic_date <= end_date:
            _require(
                economic_date in run_session_set,
                f"{role} in-run corporate-action economic date must be a run session",
            )
            _require(
                not isinstance(event, DailyMarketDataUnsupportedCorporateAction),
                f"{role} unsupported corporate-action event cannot be executed",
            )


def _validate_date(value: date, *, field_name: str) -> None:
    if type(value) is not date:
        raise DailyMarketDataSnapshotPairError(f"{field_name} must be a date")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DailyMarketDataSnapshotPairError(message)


__all__ = [
    "DailyMarketDataSnapshotPairError",
    "DailyMarketDataSnapshotPairV2",
    "prepare_daily_market_data_snapshot_pair_v2",
]
