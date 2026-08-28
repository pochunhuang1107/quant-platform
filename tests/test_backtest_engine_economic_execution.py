from __future__ import annotations

import inspect
from decimal import Decimal

import pytest

import backtest_engine.economic_execution as economic_execution_module
from backtest_engine import (
    BasisPointAssumption,
    EconomicExecutionError,
    run_snapshot_v2_buy_and_hold_backtest,
)
from backtest_engine.economic_models import EconomicAccountingError
from backtest_engine.snapshot_pair import DailyMarketDataSnapshotPairError
from backtest_engine.snapshot_v2_input import DailyMarketDataSnapshotV2InputError
from helpers_backtest_engine_economic import (
    DEFAULT_SESSIONS,
    QQQ_INSTRUMENT_ID,
    SPY_INSTRUMENT_ID,
    bars_jsonl,
    compatible_profile,
    execution_metadata,
    qqq_bundle_files,
    resolved_config,
    spy_bundle_files,
)
from helpers_daily_market_data_snapshots_v2 import (
    cash_distribution_v2,
    split_v2,
    unsupported_event_v2,
)
from research_sdk.contracts.enums import DataAdjustmentPolicy, TemporalCoverage


def test_public_boundary_accepts_exact_bundle_bytes_and_verifies_pair() -> None:
    qqq = qqq_bundle_files()
    spy = spy_bundle_files()

    result = run_snapshot_v2_buy_and_hold_backtest(
        asset_files=qqq,
        benchmark_files=spy,
        research_profile=compatible_profile(qqq),
        resolved_config=resolved_config(),
        execution_metadata=execution_metadata(),
    )

    assert result.market_data_lineage.asset.snapshot_id != (
        result.market_data_lineage.benchmark.snapshot_id
    )
    assert result.market_data_lineage.asset.symbol == "QQQ"
    assert result.market_data_lineage.benchmark.symbol == "SPY"
    assert result.market_data_lineage.run_session_dates == DEFAULT_SESSIONS
    assert result.temporal_coverage is TemporalCoverage.LATEST_KNOWN
    assert len(result.daily_records) == len(DEFAULT_SESSIONS)


def test_public_signature_does_not_accept_preparsed_pair() -> None:
    signature = inspect.signature(run_snapshot_v2_buy_and_hold_backtest)

    assert tuple(signature.parameters) == (
        "asset_files",
        "benchmark_files",
        "research_profile",
        "resolved_config",
        "execution_metadata",
    )


@pytest.mark.parametrize("mutation", ["missing", "extra", "changed_bytes"])
def test_exact_bundle_verification_fails_before_execution(mutation: str) -> None:
    qqq = qqq_bundle_files()
    if mutation == "missing":
        del qqq["policy.json"]
    elif mutation == "extra":
        qqq["untrusted-extra.json"] = b"{}\n"
    else:
        qqq["bars.jsonl"] += b"\n"

    with pytest.raises(DailyMarketDataSnapshotV2InputError):
        _run(qqq=qqq)


def test_qqq_spy_roles_are_enforced() -> None:
    qqq = qqq_bundle_files()
    spy = spy_bundle_files()

    with pytest.raises(DailyMarketDataSnapshotPairError, match="asset snapshot symbol"):
        _run(qqq=spy, spy=qqq, profile=compatible_profile(qqq))


def test_profile_mismatch_and_invalid_adjustment_authority_fail() -> None:
    qqq = qqq_bundle_files()
    mismatch = compatible_profile(qqq, required_currency="CAD")
    with pytest.raises(DailyMarketDataSnapshotPairError, match="asset"):
        _run(qqq=qqq, profile=mismatch)

    invalid_profile = compatible_profile(qqq).model_copy(
        update={"adjustment_policy": DataAdjustmentPolicy.SPLIT_ADJUSTED}
    )
    with pytest.raises(ValueError, match="raw OHLCV"):
        _run(qqq=qqq, profile=invalid_profile)


def test_latest_known_is_required_by_economic_executor() -> None:
    qqq = qqq_bundle_files(temporal_coverage=TemporalCoverage.NOT_APPLICABLE)
    spy = spy_bundle_files(temporal_coverage=TemporalCoverage.NOT_APPLICABLE)
    profile = compatible_profile(qqq).model_copy(
        update={"permitted_temporal_coverage": (TemporalCoverage.NOT_APPLICABLE,)}
    )

    with pytest.raises(EconomicExecutionError, match="LATEST_KNOWN"):
        _run(qqq=qqq, spy=spy, profile=profile)


def test_session_mismatch_fails_without_intersection_or_repair() -> None:
    qqq = qqq_bundle_files()
    spy = spy_bundle_files(sessions=DEFAULT_SESSIONS[:-1])

    with pytest.raises(DailyMarketDataSnapshotPairError):
        _run(qqq=qqq, spy=spy)


def test_unsupported_in_run_corporate_action_fails_closed() -> None:
    unsupported = unsupported_event_v2(
        instrument_id=QQQ_INSTRUMENT_ID,
        effective_date=DEFAULT_SESSIONS[1],
    )
    qqq = qqq_bundle_files(events=(unsupported,))

    with pytest.raises(DailyMarketDataSnapshotPairError, match="unsupported"):
        _run(qqq=qqq)


def test_first_session_ex_date_is_applied_before_zero_position_buys() -> None:
    first = DEFAULT_SESSIONS[0]
    qqq_event = cash_distribution_v2(
        event_id="qqq-first-session-distribution",
        instrument_id=QQQ_INSTRUMENT_ID,
        ex_date=first,
        record_date=first,
        payable_date=first,
    )
    spy_event = cash_distribution_v2(
        event_id="spy-first-session-distribution",
        instrument_id=SPY_INSTRUMENT_ID,
        source_event_reference="synthetic-v2/actions/spy-first-distribution",
        ex_date=first,
        record_date=first,
        payable_date=first,
    )

    result = _run(
        qqq=qqq_bundle_files(events=(qqq_event,)),
        spy=spy_bundle_files(events=(spy_event,)),
    )

    first_audits = [
        row
        for row in result.corporate_action_audit
        if row.session == first
        and row.accounting_action == "cash_distribution_entitlement"
    ]
    assert len(first_audits) == 2
    assert {row.entitlement_position for row in first_audits} == {Decimal("0")}
    assert result.trade_records[0].execution_session == first
    assert result.daily_records[0].strategy_quantity > 0
    assert result.daily_records[0].benchmark_fractional_units > 0
    assert result.ending_strategy_state.receivables == ()
    assert result.ending_benchmark_state.receivables == ()


def test_later_distributions_enter_equity_then_settle_without_reinvestment() -> None:
    ex_date = DEFAULT_SESSIONS[1]
    qqq_event = cash_distribution_v2(
        event_id="qqq-later-distribution",
        instrument_id=QQQ_INSTRUMENT_ID,
        ex_date=ex_date,
        record_date=ex_date,
        payable_date=ex_date,
        amount=Decimal("1"),
    )
    spy_event = cash_distribution_v2(
        event_id="spy-later-distribution",
        instrument_id=SPY_INSTRUMENT_ID,
        source_event_reference="synthetic-v2/actions/spy-later-distribution",
        ex_date=ex_date,
        record_date=ex_date,
        payable_date=ex_date,
        amount=Decimal("1"),
    )
    qqq_bars = _distribution_drop_bars(base="100")
    spy_bars = _distribution_drop_bars(base="400")

    result = _run(
        qqq=qqq_bundle_files(bars=qqq_bars, events=(qqq_event,)),
        spy=spy_bundle_files(bars=spy_bars, events=(spy_event,)),
    )
    first, ex_row, settlement, ending = result.daily_records

    assert ex_row.strategy_total_economic_equity == first.strategy_total_economic_equity
    assert ex_row.benchmark_total_economic_equity == (
        first.benchmark_total_economic_equity
    )
    assert ex_row.strategy_outstanding_receivable_value == Decimal("999.000000")
    assert ex_row.benchmark_outstanding_receivable_value == Decimal("250.000000")
    assert settlement.strategy_total_economic_equity == (
        ex_row.strategy_total_economic_equity
    )
    assert settlement.benchmark_total_economic_equity == (
        ex_row.benchmark_total_economic_equity
    )
    assert settlement.strategy_outstanding_receivable_value == 0
    assert settlement.benchmark_outstanding_receivable_value == 0
    assert settlement.strategy_cash == ex_row.strategy_cash + Decimal("999")
    assert settlement.benchmark_cash == ex_row.benchmark_cash + Decimal("250")
    assert ending.strategy_quantity == first.strategy_quantity
    assert ending.benchmark_fractional_units == first.benchmark_fractional_units
    assert result.transaction_cost_totals.benchmark_commission == 0
    assert result.transaction_cost_totals.benchmark_slippage == 0


def test_horizon_receivables_remain_in_state_and_equity() -> None:
    last = DEFAULT_SESSIONS[-1]
    event = cash_distribution_v2(
        event_id="qqq-horizon-distribution",
        instrument_id=QQQ_INSTRUMENT_ID,
        ex_date=last,
        record_date=last,
        payable_date=last,
        amount=Decimal("0.5"),
    )

    result = _run(qqq=qqq_bundle_files(events=(event,)))

    receivable = result.ending_strategy_state.receivables[0]
    assert receivable.cash_available_session is None
    assert result.daily_records[-1].strategy_outstanding_receivable_value == (
        receivable.receivable_amount
    )


def test_forward_splits_are_economically_neutral_for_both_sides() -> None:
    split_date = DEFAULT_SESSIONS[1]
    qqq_split = split_v2(
        event_id="qqq-forward-split",
        instrument_id=QQQ_INSTRUMENT_ID,
        effective_date=split_date,
        numerator=2,
        denominator=1,
    )
    spy_split = split_v2(
        event_id="spy-forward-split",
        instrument_id=SPY_INSTRUMENT_ID,
        source_event_reference="synthetic-v2/actions/spy-forward-split",
        effective_date=split_date,
        numerator=2,
        denominator=1,
    )

    result = _run(
        qqq=qqq_bundle_files(bars=_split_bars("100", "50"), events=(qqq_split,)),
        spy=spy_bundle_files(bars=_split_bars("400", "200"), events=(spy_split,)),
    )
    before, after = result.daily_records[:2]

    assert after.strategy_quantity == before.strategy_quantity * 2
    assert after.benchmark_fractional_units == before.benchmark_fractional_units * 2
    assert after.strategy_total_economic_equity == before.strategy_total_economic_equity
    assert after.benchmark_total_economic_equity == (
        before.benchmark_total_economic_equity
    )
    assert result.ending_strategy_state.total_book_cost == (
        result.trade_records[0].total_cash_spent
    )


def test_reverse_split_behavior_is_exact_when_integer_strategy_quantity_allows_it() -> (
    None
):
    split_date = DEFAULT_SESSIONS[1]
    qqq_split = split_v2(
        event_id="qqq-reverse-split",
        instrument_id=QQQ_INSTRUMENT_ID,
        effective_date=split_date,
        numerator=1,
        denominator=2,
    )
    spy_split = split_v2(
        event_id="spy-reverse-split",
        instrument_id=SPY_INSTRUMENT_ID,
        source_event_reference="synthetic-v2/actions/spy-reverse-split",
        effective_date=split_date,
        numerator=1,
        denominator=2,
    )
    zero_cost = BasisPointAssumption(bps=0, description="zero for exact test")
    config = resolved_config(commission=zero_cost, slippage=zero_cost)

    result = _run(
        qqq=qqq_bundle_files(bars=_split_bars("100", "200"), events=(qqq_split,)),
        spy=spy_bundle_files(bars=_split_bars("400", "800"), events=(spy_split,)),
        config=config,
    )
    before, after = result.daily_records[:2]

    assert before.strategy_quantity == 1000
    assert after.strategy_quantity == 500
    assert after.benchmark_fractional_units == before.benchmark_fractional_units / 2
    assert after.strategy_total_economic_equity == before.strategy_total_economic_equity
    assert after.benchmark_total_economic_equity == (
        before.benchmark_total_economic_equity
    )


def test_ambiguous_same_session_actions_fail_closed_for_held_positions() -> None:
    action_date = DEFAULT_SESSIONS[1]
    cash = cash_distribution_v2(
        event_id="qqq-ambiguous-cash",
        instrument_id=QQQ_INSTRUMENT_ID,
        ex_date=action_date,
        record_date=action_date,
        payable_date=action_date,
    )
    split = split_v2(
        event_id="qqq-ambiguous-split",
        instrument_id=QQQ_INSTRUMENT_ID,
        effective_date=action_date,
    )

    with pytest.raises(EconomicAccountingError, match="ambiguous"):
        _run(qqq=qqq_bundle_files(events=(cash, split)))


def test_timing_authority_records_pre_run_decision_and_no_same_bar_visibility() -> None:
    result = _run()
    signal = result.signal_records[0]

    assert signal.decision_authority == "pre_run_unconditional"
    assert signal.execution_session == DEFAULT_SESSIONS[0]
    assert signal.latest_observable_complete_bar_session is None
    assert signal.observable_complete_bar_sessions == ()
    assert signal.lookback_authority == "none_pre_run_unconditional"
    assert signal.lag_authority == "pre_run_decision_to_first_session_open"


def test_strategy_fill_uses_raw_open_configured_costs_and_integer_shares() -> None:
    result = _run()
    trade = result.trade_records[0]
    first = result.daily_records[0]

    assert trade.raw_open == Decimal("100.000000")
    assert trade.fill_price == Decimal("100.020000")
    assert trade.quantity == 999
    assert trade.commission == Decimal("9.991998")
    assert trade.slippage == Decimal("19.980000")
    assert first.strategy_total_book_cost == trade.total_cash_spent
    assert first.cumulative_strategy_commission == trade.commission
    assert first.cumulative_strategy_slippage == trade.slippage
    assert result.transaction_cost_totals.strategy_commission == trade.commission
    assert result.transaction_cost_totals.strategy_slippage == trade.slippage
    assert result.transaction_cost_totals.benchmark_commission == 0
    assert result.transaction_cost_totals.benchmark_slippage == 0


def test_identity_replay_and_material_input_mutations() -> None:
    baseline = _run()
    replay = _run()
    assert replay == baseline

    changed_qqq = qqq_bundle_files(
        bars=bars_jsonl(
            tuple(
                (
                    session,
                    str(100 + index),
                    str(102 + index),
                    str(99 + index),
                    str(101 + index),
                    3000 + index,
                )
                for index, session in enumerate(DEFAULT_SESSIONS)
            )
        )
    )
    changed_spy = spy_bundle_files(
        bars=bars_jsonl(
            tuple(
                (
                    session,
                    str(400 + index),
                    str(402 + index),
                    str(399 + index),
                    str(401 + index),
                    4000 + index,
                )
                for index, session in enumerate(DEFAULT_SESSIONS)
            )
        )
    )
    qqq_result = _run(qqq=changed_qqq, profile=compatible_profile(changed_qqq))
    spy_result = _run(spy=changed_spy)
    cost_result = _run(
        config=resolved_config(
            commission=BasisPointAssumption(
                bps=Decimal("3"), description="mutated commission"
            )
        )
    )
    qqq = qqq_bundle_files()
    profile_result = _run(
        qqq=qqq,
        profile=compatible_profile(qqq, profile_id="different-profile-authority"),
    )

    assert (
        len(
            {
                baseline.run_id,
                qqq_result.run_id,
                spy_result.run_id,
                cost_result.run_id,
                profile_result.run_id,
            }
        )
        == 5
    )


def test_runtime_metadata_is_lineage_but_not_economic_identity() -> None:
    first = _run(metadata=execution_metadata(platform="platform-a"))
    second = _run(metadata=execution_metadata(platform="platform-b"))

    assert first.run_id == second.run_id
    assert first.execution_metadata != second.execution_metadata


def test_invalid_timing_or_accounting_policy_copy_fails_revalidation() -> None:
    invalid_timing = resolved_config().model_copy(
        update={"timing_policy_version": "unapproved-timing"}
    )
    with pytest.raises(ValueError):
        _run(config=invalid_timing)

    invalid_accounting = resolved_config().model_copy(
        update={"strategy_accounting_policy_version": "unapproved-accounting"}
    )
    with pytest.raises(ValueError):
        _run(config=invalid_accounting)


def test_each_applicable_event_id_is_applied_once_even_when_settled_later() -> None:
    ex_date = DEFAULT_SESSIONS[1]
    event = cash_distribution_v2(
        event_id="qqq-once-only",
        instrument_id=QQQ_INSTRUMENT_ID,
        ex_date=ex_date,
        record_date=ex_date,
        payable_date=ex_date,
    )
    result = _run(qqq=qqq_bundle_files(events=(event,)))

    assert result.ending_strategy_state.applied_corporate_action_event_ids == (
        event.event_id,
    )
    actions = [
        row.accounting_action
        for row in result.corporate_action_audit
        if row.event_id == event.event_id
    ]
    assert actions == [
        "cash_distribution_entitlement",
        "cash_distribution_settlement",
    ]


def test_executor_source_has_no_io_clock_provider_or_broker_access() -> None:
    source = inspect.getsource(economic_execution_module)
    for prohibited in (
        "datetime.now",
        "datetime.utcnow",
        "date.today",
        "time.time",
        "requests",
        "httpx",
        "socket",
        "Path",
        "open(",
        "read_bytes",
        "write_bytes",
        "sqlalchemy",
        "Massive",
        "boto",
        "broker",
    ):
        assert prohibited not in source


def _run(
    *,
    qqq: dict[str, bytes] | None = None,
    spy: dict[str, bytes] | None = None,
    profile=None,  # type: ignore[no-untyped-def]
    config=None,  # type: ignore[no-untyped-def]
    metadata=None,  # type: ignore[no-untyped-def]
):  # type: ignore[no-untyped-def]
    qqq_files = qqq or qqq_bundle_files()
    return run_snapshot_v2_buy_and_hold_backtest(
        asset_files=qqq_files,
        benchmark_files=spy or spy_bundle_files(),
        research_profile=profile or compatible_profile(qqq_files),
        resolved_config=config or resolved_config(),
        execution_metadata=metadata or execution_metadata(),
    )


def _distribution_drop_bars(*, base: str) -> bytes:
    initial = Decimal(base)
    dropped = initial - Decimal("1")
    return bars_jsonl(
        (
            (
                DEFAULT_SESSIONS[0],
                str(initial),
                str(initial + 1),
                str(initial - 1),
                str(initial),
                1000,
            ),
            (
                DEFAULT_SESSIONS[1],
                str(dropped),
                str(initial),
                str(dropped - 1),
                str(dropped),
                1100,
            ),
            (
                DEFAULT_SESSIONS[2],
                str(dropped),
                str(initial),
                str(dropped - 1),
                str(dropped),
                1200,
            ),
            (
                DEFAULT_SESSIONS[3],
                str(dropped),
                str(initial),
                str(dropped - 1),
                str(dropped),
                1300,
            ),
        )
    )


def _split_bars(before: str, after: str) -> bytes:
    first = Decimal(before)
    subsequent = Decimal(after)
    return bars_jsonl(
        (
            (
                DEFAULT_SESSIONS[0],
                str(first),
                str(first + 1),
                str(first - 1),
                str(first),
                1000,
            ),
            (
                DEFAULT_SESSIONS[1],
                str(subsequent),
                str(subsequent + 1),
                str(subsequent - 1),
                str(subsequent),
                1100,
            ),
            (
                DEFAULT_SESSIONS[2],
                str(subsequent),
                str(subsequent + 1),
                str(subsequent - 1),
                str(subsequent),
                1200,
            ),
            (
                DEFAULT_SESSIONS[3],
                str(subsequent),
                str(subsequent + 1),
                str(subsequent - 1),
                str(subsequent),
                1300,
            ),
        )
    )
