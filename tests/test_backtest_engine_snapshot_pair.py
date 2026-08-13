from __future__ import annotations

import inspect
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

import backtest_engine.snapshot_pair as snapshot_pair_module
from backtest_engine.snapshot_pair import (
    DailyMarketDataSnapshotPairError,
    prepare_daily_market_data_snapshot_pair_v2,
)
from backtest_engine.snapshot_v2_input import (
    LoadedDailyMarketDataSnapshotV2,
    load_daily_market_data_snapshot_v2,
)
from helpers_daily_market_data_snapshots import (
    sample_expected_sessions,
    sample_policy,
    source_bytes,
)
from helpers_daily_market_data_snapshots_v2 import (
    cash_distribution_v2,
    sample_bar_provenance_input_v2,
    sample_corporate_action_evidence_v2,
    sample_plan_v2,
    split_v2,
    unsupported_event_v2,
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
from research_sdk.daily_market_data import (
    DailyMarketDataSnapshotProfileCompatibility,
    derive_daily_market_data_research_profile_hash,
)
from research_sdk.daily_market_data_storage import plan_daily_market_data_snapshot_v2
from research_sdk.daily_market_data_storage.serialization import (
    render_canonical_daily_bars,
)
from research_sdk.daily_market_data_storage.verification_v2 import (
    VerifiedDailyMarketDataSnapshotV2,
)

SESSIONS = (date(2026, 1, 2), date(2026, 1, 5))
QQQ_INSTRUMENT_ID = "instrument-us-etf-qqq-xnas"
SPY_INSTRUMENT_ID = "instrument-us-etf-spy-arcx"


def test_valid_synthetic_qqq_spy_pair_succeeds() -> None:
    qqq_files = qqq_bundle_files()
    spy_files = spy_bundle_files()
    profile = compatible_profile(load_daily_market_data_snapshot_v2(qqq_files))

    pair = prepare_daily_market_data_snapshot_pair_v2(
        asset_files=qqq_files,
        benchmark_files=spy_files,
        research_profile=profile,
        start_date=SESSIONS[0],
        end_date=SESSIONS[-1],
    )

    assert pair.asset.verified_snapshot.quality_report.instrument.symbol == "QQQ"
    assert pair.benchmark.verified_snapshot.quality_report.instrument.symbol == "SPY"
    assert pair.asset.verified_snapshot.snapshot_id != (
        pair.benchmark.verified_snapshot.snapshot_id
    )
    assert pair.asset.verified_snapshot.instrument_id != (
        pair.benchmark.verified_snapshot.instrument_id
    )
    assert pair.asset_profile_compatibility.profile_hash == pair.profile_hash
    assert pair.benchmark_profile_compatibility.profile_hash == pair.profile_hash
    assert pair.profile_hash == derive_daily_market_data_research_profile_hash(profile)
    assert (
        pair.asset_profile_compatibility.required_daily_bar_availability_policy
        is DailyMarketDataBarAvailabilityPolicy.NEXT_EXPECTED_SESSION
    )
    assert (
        pair.benchmark_profile_compatibility.required_daily_bar_availability_policy
        is DailyMarketDataBarAvailabilityPolicy.NEXT_EXPECTED_SESSION
    )
    assert pair.run_session_dates == SESSIONS
    assert tuple(bar.session_date for bar in pair.asset_run_bars) == SESSIONS
    assert tuple(bar.session_date for bar in pair.benchmark_run_bars) == SESSIONS
    assert pair.asset_run_bars == pair.asset.bars
    assert pair.benchmark_run_bars == pair.benchmark.bars


def test_distinct_outer_snapshot_coverage_may_pass_for_aligned_window() -> None:
    wider_sessions = (*SESSIONS, date(2026, 1, 6))
    qqq_files = qqq_bundle_files(
        session_dates=wider_sessions,
        source_bytes_override=bars_jsonl(
            (
                ("2026-01-02", "100", "101", "99", "100.5", 1000),
                ("2026-01-05", "101", "102", "100", "101.5", 1100),
                ("2026-01-06", "102", "103", "101", "102.5", 1200),
            )
        ),
    )
    spy_files = spy_bundle_files()
    profile = compatible_profile(load_daily_market_data_snapshot_v2(qqq_files))

    pair = prepare_daily_market_data_snapshot_pair_v2(
        asset_files=qqq_files,
        benchmark_files=spy_files,
        research_profile=profile,
        start_date=SESSIONS[0],
        end_date=SESSIONS[-1],
    )

    assert pair.run_session_dates == SESSIONS
    assert tuple(bar.session_date for bar in pair.asset_run_bars) == SESSIONS
    assert pair.asset.verified_snapshot.quality_report.expected_session_count == 3
    assert pair.benchmark.verified_snapshot.quality_report.expected_session_count == 2


def test_pair_result_is_deterministic_for_same_inputs() -> None:
    qqq_files = qqq_bundle_files()
    spy_files = spy_bundle_files()
    profile = compatible_profile(load_daily_market_data_snapshot_v2(qqq_files))

    first = prepare_daily_market_data_snapshot_pair_v2(
        asset_files=qqq_files,
        benchmark_files=spy_files,
        research_profile=profile,
        start_date=SESSIONS[0],
        end_date=SESSIONS[-1],
    )
    second = prepare_daily_market_data_snapshot_pair_v2(
        asset_files=qqq_files,
        benchmark_files=spy_files,
        research_profile=profile,
        start_date=SESSIONS[0],
        end_date=SESSIONS[-1],
    )

    assert first == second


def test_pair_public_signature_accepts_raw_bundle_mappings_only() -> None:
    signature = inspect.signature(prepare_daily_market_data_snapshot_pair_v2)

    assert tuple(signature.parameters) == (
        "asset_files",
        "benchmark_files",
        "research_profile",
        "start_date",
        "end_date",
    )
    assert signature.parameters["asset_files"].annotation != (
        LoadedDailyMarketDataSnapshotV2
    )
    assert signature.parameters["benchmark_files"].annotation != (
        LoadedDailyMarketDataSnapshotV2
    )


def test_pair_producer_output_invariants() -> None:
    qqq_files = qqq_bundle_files()
    spy_files = spy_bundle_files()
    profile = compatible_profile(load_daily_market_data_snapshot_v2(qqq_files))

    pair = prepare_daily_market_data_snapshot_pair_v2(
        asset_files=qqq_files,
        benchmark_files=spy_files,
        research_profile=profile,
        start_date=SESSIONS[0],
        end_date=SESSIONS[-1],
    )

    assert pair.profile_hash == pair.asset_profile_compatibility.profile_hash
    assert pair.profile_hash == pair.benchmark_profile_compatibility.profile_hash
    assert pair.run_session_dates == tuple(sorted(set(pair.run_session_dates)))
    assert len(pair.run_session_dates) >= 2
    assert len(pair.asset_run_bars) == len(pair.run_session_dates)
    assert len(pair.benchmark_run_bars) == len(pair.run_session_dates)
    assert tuple(bar.session_date for bar in pair.asset_run_bars) == (
        pair.run_session_dates
    )
    assert tuple(bar.session_date for bar in pair.benchmark_run_bars) == (
        pair.run_session_dates
    )
    assert pair.start_date == pair.run_session_dates[0]
    assert pair.end_date == pair.run_session_dates[-1]


def test_qqq_used_for_both_roles_fails() -> None:
    qqq_files = qqq_bundle_files()
    profile = compatible_profile(load_daily_market_data_snapshot_v2(qqq_files))

    with pytest.raises(DailyMarketDataSnapshotPairError):
        prepare_daily_market_data_snapshot_pair_v2(
            asset_files=qqq_files,
            benchmark_files=qqq_files,
            research_profile=profile,
            start_date=SESSIONS[0],
            end_date=SESSIONS[-1],
        )


def test_spy_in_strategy_role_fails() -> None:
    qqq_files = qqq_bundle_files()
    spy_files = spy_bundle_files()
    profile = compatible_profile(load_daily_market_data_snapshot_v2(qqq_files))

    with pytest.raises(DailyMarketDataSnapshotPairError, match="asset snapshot symbol"):
        prepare_daily_market_data_snapshot_pair_v2(
            asset_files=spy_files,
            benchmark_files=qqq_files,
            research_profile=profile,
            start_date=SESSIONS[0],
            end_date=SESSIONS[-1],
        )


def test_same_instrument_id_fails_even_when_symbols_are_distinct() -> None:
    qqq_files = qqq_bundle_files()
    spy_same_instrument = spy_bundle_files(instrument_id=QQQ_INSTRUMENT_ID)
    profile = compatible_profile(load_daily_market_data_snapshot_v2(qqq_files))

    with pytest.raises(DailyMarketDataSnapshotPairError, match="instrument IDs"):
        prepare_daily_market_data_snapshot_pair_v2(
            asset_files=qqq_files,
            benchmark_files=spy_same_instrument,
            research_profile=profile,
            start_date=SESSIONS[0],
            end_date=SESSIONS[-1],
        )


def test_asset_profile_incompatibility_fails() -> None:
    qqq_files = qqq_bundle_files()
    spy_files = spy_bundle_files()
    profile = compatible_profile(
        load_daily_market_data_snapshot_v2(qqq_files),
        required_currency="CAD",
    )

    with pytest.raises(DailyMarketDataSnapshotPairError, match="asset"):
        prepare_daily_market_data_snapshot_pair_v2(
            asset_files=qqq_files,
            benchmark_files=spy_files,
            research_profile=profile,
            start_date=SESSIONS[0],
            end_date=SESSIONS[-1],
        )


def test_benchmark_profile_incompatibility_fails() -> None:
    qqq_files = qqq_bundle_files()
    spy_cad_files = spy_bundle_files(currency="CAD")
    profile = compatible_profile(load_daily_market_data_snapshot_v2(qqq_files))

    with pytest.raises(DailyMarketDataSnapshotPairError, match="benchmark"):
        prepare_daily_market_data_snapshot_pair_v2(
            asset_files=qqq_files,
            benchmark_files=spy_cad_files,
            research_profile=profile,
            start_date=SESSIONS[0],
            end_date=SESSIONS[-1],
        )


def test_defensive_profile_hash_mismatch_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    qqq_files = qqq_bundle_files()
    spy_files = spy_bundle_files()
    profile = compatible_profile(load_daily_market_data_snapshot_v2(qqq_files))

    def fake_compatibility(
        **kwargs: Any,
    ) -> DailyMarketDataSnapshotProfileCompatibility:
        verified = kwargs["verified_snapshot"]
        profile_hash = (
            "sha256:" + "1" * 64
            if verified.quality_report.instrument.symbol == "QQQ"
            else "sha256:" + "2" * 64
        )
        return compatibility_result(verified, profile, profile_hash=profile_hash)

    monkeypatch.setattr(
        snapshot_pair_module,
        "validate_daily_market_data_snapshot_profile_compatibility",
        fake_compatibility,
    )

    with pytest.raises(DailyMarketDataSnapshotPairError, match="profile hash"):
        prepare_daily_market_data_snapshot_pair_v2(
            asset_files=qqq_files,
            benchmark_files=spy_files,
            research_profile=profile,
            start_date=SESSIONS[0],
            end_date=SESSIONS[-1],
        )


def test_non_next_expected_session_compatibility_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    qqq_files = qqq_bundle_files()
    spy_files = spy_bundle_files()
    profile = compatible_profile(load_daily_market_data_snapshot_v2(qqq_files))
    profile_hash = derive_daily_market_data_research_profile_hash(profile)

    def fake_compatibility(
        **kwargs: Any,
    ) -> DailyMarketDataSnapshotProfileCompatibility:
        return replace(
            compatibility_result(
                kwargs["verified_snapshot"], profile_hash=profile_hash
            ),
            required_daily_bar_availability_policy="same_day",  # type: ignore[arg-type]
        )

    monkeypatch.setattr(
        snapshot_pair_module,
        "validate_daily_market_data_snapshot_profile_compatibility",
        fake_compatibility,
    )

    with pytest.raises(DailyMarketDataSnapshotPairError, match="next-expected-session"):
        prepare_daily_market_data_snapshot_pair_v2(
            asset_files=qqq_files,
            benchmark_files=spy_files,
            research_profile=profile,
            start_date=SESSIONS[0],
            end_date=SESSIONS[-1],
        )


def test_start_date_after_end_date_fails() -> None:
    qqq_files = qqq_bundle_files()
    spy_files = spy_bundle_files()
    profile = compatible_profile(load_daily_market_data_snapshot_v2(qqq_files))

    with pytest.raises(DailyMarketDataSnapshotPairError, match="start_date"):
        prepare_daily_market_data_snapshot_pair_v2(
            asset_files=qqq_files,
            benchmark_files=spy_files,
            research_profile=profile,
            start_date=SESSIONS[-1],
            end_date=SESSIONS[0],
        )


def test_datetime_run_boundaries_fail() -> None:
    qqq_files = qqq_bundle_files()
    spy_files = spy_bundle_files()
    profile = compatible_profile(load_daily_market_data_snapshot_v2(qqq_files))

    with pytest.raises(DailyMarketDataSnapshotPairError, match="start_date"):
        prepare_daily_market_data_snapshot_pair_v2(
            asset_files=qqq_files,
            benchmark_files=spy_files,
            research_profile=profile,
            start_date=datetime(2026, 1, 2),  # type: ignore[arg-type]
            end_date=SESSIONS[-1],
        )
    with pytest.raises(DailyMarketDataSnapshotPairError, match="end_date"):
        prepare_daily_market_data_snapshot_pair_v2(
            asset_files=qqq_files,
            benchmark_files=spy_files,
            research_profile=profile,
            start_date=SESSIONS[0],
            end_date=datetime(2026, 1, 5),  # type: ignore[arg-type]
        )


def test_start_and_end_endpoints_must_be_expected_sessions() -> None:
    qqq_files = qqq_bundle_files()
    spy_files = spy_bundle_files()
    profile = compatible_profile(load_daily_market_data_snapshot_v2(qqq_files))

    with pytest.raises(DailyMarketDataSnapshotPairError, match="start_date"):
        prepare_daily_market_data_snapshot_pair_v2(
            asset_files=qqq_files,
            benchmark_files=spy_files,
            research_profile=profile,
            start_date=date(2026, 1, 3),
            end_date=SESSIONS[-1],
        )
    with pytest.raises(DailyMarketDataSnapshotPairError, match="end_date"):
        prepare_daily_market_data_snapshot_pair_v2(
            asset_files=qqq_files,
            benchmark_files=spy_files,
            research_profile=profile,
            start_date=SESSIONS[0],
            end_date=date(2026, 1, 6),
        )


def test_one_session_run_fails() -> None:
    qqq_files = qqq_bundle_files()
    spy_files = spy_bundle_files()
    profile = compatible_profile(load_daily_market_data_snapshot_v2(qqq_files))

    with pytest.raises(DailyMarketDataSnapshotPairError, match="two run sessions"):
        prepare_daily_market_data_snapshot_pair_v2(
            asset_files=qqq_files,
            benchmark_files=spy_files,
            research_profile=profile,
            start_date=SESSIONS[0],
            end_date=SESSIONS[0],
        )


def test_run_session_mismatch_fails() -> None:
    qqq_files = qqq_bundle_files()
    benchmark_sessions = (date(2026, 1, 2), date(2026, 1, 3), date(2026, 1, 5))
    spy_files = spy_bundle_files(
        session_dates=benchmark_sessions,
        source_bytes_override=bars_jsonl(
            (
                ("2026-01-02", "400", "401", "399", "400.5", 2000),
                ("2026-01-03", "401", "402", "400", "401.5", 2100),
                ("2026-01-05", "402", "403", "401", "402.5", 2200),
            )
        ),
    )
    profile = compatible_profile(load_daily_market_data_snapshot_v2(qqq_files))

    with pytest.raises(DailyMarketDataSnapshotPairError, match="run sessions"):
        prepare_daily_market_data_snapshot_pair_v2(
            asset_files=qqq_files,
            benchmark_files=spy_files,
            research_profile=profile,
            start_date=SESSIONS[0],
            end_date=SESSIONS[-1],
        )


@pytest.mark.parametrize(
    ("benchmark_kwargs", "match"),
    [
        ({"calendar": "XNAS"}, "benchmark"),
        ({"timezone": "UTC"}, "benchmark"),
        ({"session_source_id": "other-source"}, "benchmark"),
        ({"session_source_version": "other-version"}, "benchmark"),
    ],
)
def test_pair_context_mismatch_fails(
    benchmark_kwargs: dict[str, object],
    match: str,
) -> None:
    qqq_files = qqq_bundle_files()
    spy_files = spy_bundle_files(**benchmark_kwargs)
    profile = compatible_profile(load_daily_market_data_snapshot_v2(qqq_files))

    with pytest.raises(DailyMarketDataSnapshotPairError, match=match):
        prepare_daily_market_data_snapshot_pair_v2(
            asset_files=qqq_files,
            benchmark_files=spy_files,
            research_profile=profile,
            start_date=SESSIONS[0],
            end_date=SESSIONS[-1],
        )


def test_missing_run_bar_fails_for_defensive_loaded_object() -> None:
    loaded = load_daily_market_data_snapshot_v2(qqq_bundle_files())
    # This deliberately bypasses verifier authority to exercise projection defense.
    inconsistent = loaded.model_copy(update={"bars": loaded.bars[:1]})

    with pytest.raises(DailyMarketDataSnapshotPairError, match="run bars"):
        snapshot_pair_module._project_run_bars(
            loaded=inconsistent,
            role="asset",
            start_date=SESSIONS[0],
            end_date=SESSIONS[-1],
            run_session_dates=SESSIONS,
        )


def test_unexpected_run_bar_fails_for_defensive_loaded_object() -> None:
    loaded = load_daily_market_data_snapshot_v2(qqq_bundle_files())
    # This deliberately bypasses verifier authority to exercise projection defense.
    inconsistent = loaded.model_copy(
        update={
            "bars": (
                *loaded.bars,
                CanonicalDailyBar(
                    session_date=date(2026, 1, 3),
                    open=Decimal("101"),
                    high=Decimal("102"),
                    low=Decimal("100"),
                    close=Decimal("101.5"),
                    volume=1200,
                ),
            )
        }
    )

    with pytest.raises(DailyMarketDataSnapshotPairError, match="run bars"):
        snapshot_pair_module._project_run_bars(
            loaded=inconsistent,
            role="asset",
            start_date=SESSIONS[0],
            end_date=SESSIONS[-1],
            run_session_dates=SESSIONS,
        )


def test_historical_default_v2_fixture_fails_for_non_session_ca_dates() -> None:
    historical_qqq_files = sample_plan_v2().as_file_map()
    spy_files = spy_bundle_files()
    profile = compatible_profile(
        load_daily_market_data_snapshot_v2(historical_qqq_files)
    )

    with pytest.raises(DailyMarketDataSnapshotPairError, match="economic date"):
        prepare_daily_market_data_snapshot_pair_v2(
            asset_files=historical_qqq_files,
            benchmark_files=spy_files,
            research_profile=profile,
            start_date=SESSIONS[0],
            end_date=SESSIONS[-1],
        )


def test_supported_outside_run_ca_dates_do_not_require_run_sessions() -> None:
    wider_sessions = (*SESSIONS, date(2026, 1, 6))
    split = split_v2(
        event_id="synthetic-v2-event-split-20260106",
        effective_date=date(2026, 1, 6),
    )
    qqq_files = qqq_bundle_files(
        session_dates=wider_sessions,
        source_bytes_override=bars_jsonl(
            (
                ("2026-01-02", "100", "101", "99", "100.5", 1000),
                ("2026-01-05", "101", "102", "100", "101.5", 1100),
                ("2026-01-06", "102", "103", "101", "102.5", 1200),
            )
        ),
        events=(split,),
    )
    spy_files = spy_bundle_files()
    profile = compatible_profile(load_daily_market_data_snapshot_v2(qqq_files))

    pair = prepare_daily_market_data_snapshot_pair_v2(
        asset_files=qqq_files,
        benchmark_files=spy_files,
        research_profile=profile,
        start_date=SESSIONS[0],
        end_date=SESSIONS[-1],
    )

    assert pair.run_session_dates == SESSIONS


def test_pre_run_ex_date_with_in_run_payable_date_does_not_define_run_event() -> None:
    wider_sessions = (date(2026, 1, 1), *SESSIONS)
    cash = cash_distribution_v2(
        event_id="synthetic-v2-event-cash-20260101",
        ex_date=date(2026, 1, 1),
        record_date=date(2026, 1, 1),
        payable_date=SESSIONS[-1],
    )
    qqq_files = qqq_bundle_files(
        session_dates=wider_sessions,
        source_bytes_override=bars_jsonl(
            (
                ("2026-01-01", "99", "100", "98", "99.5", 900),
                ("2026-01-02", "100", "101", "99", "100.5", 1000),
                ("2026-01-05", "101", "102", "100", "101.5", 1100),
            )
        ),
        events=(cash,),
    )
    spy_files = spy_bundle_files()
    profile = compatible_profile(load_daily_market_data_snapshot_v2(qqq_files))

    pair = prepare_daily_market_data_snapshot_pair_v2(
        asset_files=qqq_files,
        benchmark_files=spy_files,
        research_profile=profile,
        start_date=SESSIONS[0],
        end_date=SESSIONS[-1],
    )

    assert pair.run_session_dates == SESSIONS


def test_in_run_ex_date_with_post_run_payable_date_is_valid_input() -> None:
    cash = cash_distribution_v2(
        event_id="synthetic-v2-event-cash-20260105",
        ex_date=SESSIONS[-1],
        record_date=SESSIONS[-1],
        payable_date=date(2026, 1, 6),
    )
    qqq_files = qqq_bundle_files(events=(cash,))
    spy_files = spy_bundle_files()
    profile = compatible_profile(load_daily_market_data_snapshot_v2(qqq_files))

    pair = prepare_daily_market_data_snapshot_pair_v2(
        asset_files=qqq_files,
        benchmark_files=spy_files,
        research_profile=profile,
        start_date=SESSIONS[0],
        end_date=SESSIONS[-1],
    )

    assert pair.run_session_dates == SESSIONS


def test_unsupported_evidence_outside_requested_run_fails_profile_globally() -> None:
    wider_sessions = (*SESSIONS, date(2026, 1, 6))
    unsupported = unsupported_event_v2(effective_date=date(2026, 1, 6))
    qqq_files = qqq_bundle_files(
        session_dates=wider_sessions,
        source_bytes_override=bars_jsonl(
            (
                ("2026-01-02", "100", "101", "99", "100.5", 1000),
                ("2026-01-05", "101", "102", "100", "101.5", 1100),
                ("2026-01-06", "102", "103", "101", "102.5", 1200),
            )
        ),
        events=(unsupported,),
    )
    spy_files = spy_bundle_files()
    profile = compatible_profile(load_daily_market_data_snapshot_v2(qqq_files))

    with pytest.raises(DailyMarketDataSnapshotPairError, match="unsupported"):
        prepare_daily_market_data_snapshot_pair_v2(
            asset_files=qqq_files,
            benchmark_files=spy_files,
            research_profile=profile,
            start_date=SESSIONS[0],
            end_date=SESSIONS[-1],
        )


def test_unsupported_in_run_ca_fails_profile_globally() -> None:
    unsupported = unsupported_event_v2(effective_date=SESSIONS[-1])
    qqq_files = qqq_bundle_files(events=(unsupported,))
    spy_files = spy_bundle_files()
    profile = compatible_profile(load_daily_market_data_snapshot_v2(qqq_files))

    with pytest.raises(DailyMarketDataSnapshotPairError, match="unsupported"):
        prepare_daily_market_data_snapshot_pair_v2(
            asset_files=qqq_files,
            benchmark_files=spy_files,
            research_profile=profile,
            start_date=SESSIONS[0],
            end_date=SESSIONS[-1],
        )


def test_supported_in_run_ca_on_expected_session_passes_input_projection() -> None:
    cash = cash_distribution_v2(
        event_id="synthetic-v2-event-cash-20260105",
        ex_date=SESSIONS[-1],
        record_date=SESSIONS[-1],
        payable_date=SESSIONS[-1],
    )
    qqq_files = qqq_bundle_files(events=(cash,))
    spy_files = spy_bundle_files()
    profile = compatible_profile(load_daily_market_data_snapshot_v2(qqq_files))

    pair = prepare_daily_market_data_snapshot_pair_v2(
        asset_files=qqq_files,
        benchmark_files=spy_files,
        research_profile=profile,
        start_date=SESSIONS[0],
        end_date=SESSIONS[-1],
    )

    assert pair.run_session_dates == SESSIONS


def test_pair_source_has_no_filesystem_network_or_clock_access() -> None:
    source = inspect.getsource(snapshot_pair_module)

    for prohibited in (
        "datetime.now",
        "datetime.utcnow",
        "date.today",
        "time.time",
        "requests",
        "httpx",
        "urllib.request",
        "socket",
        "Path",
        "open(",
        "read_bytes",
        "write_bytes",
        "os.",
        "shutil",
        "tempfile",
    ):
        assert prohibited not in source


def qqq_bundle_files(
    *,
    source_bytes_override: bytes | None = None,
    session_dates: tuple[date, ...] = SESSIONS,
    currency: str = "USD",
    events: tuple[DailyMarketDataCorporateActionEvent, ...] = (),
    calendar: str = "XNYS",
    timezone: str = "America/New_York",
    session_source_id: str = "synthetic-session-fixture-v1",
    session_source_version: str = "2026-01-fixture",
) -> dict[str, bytes]:
    return bundle_files(
        symbol="QQQ",
        venue="XNAS",
        instrument_id=QQQ_INSTRUMENT_ID,
        source_bytes=(
            source_bytes_override
            if source_bytes_override is not None
            else source_bytes()
        ),
        session_dates=session_dates,
        currency=currency,
        events=events,
        calendar=calendar,
        timezone=timezone,
        session_source_id=session_source_id,
        session_source_version=session_source_version,
    )


def spy_bundle_files(
    *,
    instrument_id: str = SPY_INSTRUMENT_ID,
    source_bytes_override: bytes | None = None,
    session_dates: tuple[date, ...] = SESSIONS,
    currency: str = "USD",
    events: tuple[DailyMarketDataCorporateActionEvent, ...] = (),
    calendar: str = "XNYS",
    timezone: str = "America/New_York",
    session_source_id: str = "synthetic-session-fixture-v1",
    session_source_version: str = "2026-01-fixture",
) -> dict[str, bytes]:
    return bundle_files(
        symbol="SPY",
        venue="ARCX",
        instrument_id=instrument_id,
        source_bytes=source_bytes_override
        if source_bytes_override is not None
        else bars_jsonl(
            (
                ("2026-01-02", "400", "401", "399", "400.5", 2000),
                ("2026-01-05", "401", "402", "400", "401.5", 2100),
            )
        ),
        session_dates=session_dates,
        currency=currency,
        events=events,
        calendar=calendar,
        timezone=timezone,
        session_source_id=session_source_id,
        session_source_version=session_source_version,
    )


def bundle_files(
    *,
    symbol: str,
    venue: str,
    instrument_id: str,
    source_bytes: bytes,
    session_dates: tuple[date, ...],
    currency: str,
    events: tuple[DailyMarketDataCorporateActionEvent, ...],
    calendar: str,
    timezone: str,
    session_source_id: str,
    session_source_version: str,
) -> dict[str, bytes]:
    instrument = DailyMarketDataInstrument(
        instrument_id=instrument_id,
        symbol=symbol,
        venue=venue,
    )
    last_session = max(session_dates)
    timestamps = timestamps_for(last_session)
    expected_sessions = sample_expected_sessions(
        session_dates=session_dates,
        calendar=calendar,
        timezone=timezone,
        session_source_id=session_source_id,
        session_source_version=session_source_version,
    )
    policy = sample_policy(calendar=calendar, timezone=timezone)
    evidence = sample_corporate_action_evidence_v2(
        completeness=(
            DailyMarketDataCorporateActionEvidenceCompleteness.CHECKED_EVENTS_CAPTURED
            if events
            else DailyMarketDataCorporateActionEvidenceCompleteness.CHECKED_NO_EVENTS
        ),
        instrument=instrument,
        coverage_start_date=min(session_dates),
        coverage_end_date=last_session,
        source_dataset=f"synthetic-v2-{symbol.lower()}-corporate-action-fixture",
        source_reference=f"fixtures/corporate-actions/{symbol.lower()}-actions.json",
        source_content_hash="sha256:" + ("a" if symbol == "QQQ" else "b") * 64,
        source_observed_at=timestamps["source_observed_at"],
        ingestion_completed_at=timestamps["ingestion_completed_at"],
        available_at=timestamps["available_at"],
        created_at=timestamps["created_at"],
        events=events,
    )
    bar_provenance_input = sample_bar_provenance_input_v2(
        source_reference=f"fixtures/daily-market-data/{symbol.lower()}-bars.jsonl",
        source_instrument_reference=instrument_id,
        currency=currency,
        as_of=timestamps["as_of"],
        source_observed_at=timestamps["source_observed_at"],
        ingestion_completed_at=timestamps["ingestion_completed_at"],
        available_at=timestamps["available_at"],
        created_at=timestamps["created_at"],
    )
    return plan_daily_market_data_snapshot_v2(
        source_bytes=source_bytes,
        instrument=instrument,
        policy=policy,
        expected_sessions=expected_sessions,
        bar_provenance_input=bar_provenance_input,
        corporate_action_evidence=evidence,
    ).as_file_map()


def compatible_profile(
    loaded: LoadedDailyMarketDataSnapshotV2,
    **overrides: object,
) -> DailyMarketDataResearchProfile:
    verified = loaded.verified_snapshot
    data: dict[str, object] = {
        "schema_version": "1.0.0",
        "profile_id": "synthetic-s3d2a-compatible-daily-etf-profile",
        "profile_policy_version": "synthetic-s3d2a-compatible-profile-v1",
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
            "structured corporate-action evidence dates must cover verified sessions"
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


def compatibility_result(
    verified: VerifiedDailyMarketDataSnapshotV2,
    profile: DailyMarketDataResearchProfile | None = None,
    *,
    profile_hash: str | None = None,
) -> DailyMarketDataSnapshotProfileCompatibility:
    if profile is None:
        profile = compatible_profile(
            LoadedDailyMarketDataSnapshotV2(
                verified_snapshot=verified,
                bars=(),
            )
        )
    return DailyMarketDataSnapshotProfileCompatibility(
        snapshot_id=verified.snapshot_id,
        profile_id=profile.profile_id,
        profile_hash=profile_hash
        if profile_hash is not None
        else derive_daily_market_data_research_profile_hash(profile),
        profile_policy_version=profile.profile_policy_version,
        instrument_id=verified.instrument_id,
        unsupported_event_count=0,
        required_daily_bar_availability_policy=(
            DailyMarketDataBarAvailabilityPolicy.NEXT_EXPECTED_SESSION
        ),
    )


def bars_jsonl(
    rows: tuple[tuple[str, str, str, str, str, int], ...],
) -> bytes:
    return render_canonical_daily_bars(
        tuple(
            CanonicalDailyBar(
                session_date=date.fromisoformat(session_date),
                open=Decimal(open_price),
                high=Decimal(high),
                low=Decimal(low),
                close=Decimal(close),
                volume=volume,
            )
            for session_date, open_price, high, low, close, volume in rows
        )
    )


def timestamps_for(session_date: date) -> dict[str, datetime]:
    observed = datetime(
        session_date.year,
        session_date.month,
        session_date.day,
        23,
        45,
        tzinfo=UTC,
    )
    return {
        "as_of": datetime(
            session_date.year,
            session_date.month,
            session_date.day,
            tzinfo=UTC,
        ),
        "source_observed_at": observed,
        "ingestion_completed_at": observed + timedelta(minutes=5),
        "available_at": observed + timedelta(minutes=10),
        "created_at": observed + timedelta(minutes=15),
    }
