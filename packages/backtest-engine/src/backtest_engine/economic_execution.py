"""Pure snapshot-v2 QQQ/SPY economic backtest application boundary."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Literal

from backtest_engine.benchmark_economic_accounting import (
    apply_initial_benchmark_buy,
    apply_session_open_benchmark_economic_accounting,
    value_economic_benchmark,
)
from backtest_engine.benchmark_economic_models import (
    BENCHMARK_ECONOMIC_POLICY_VERSION,
    BenchmarkCorporateActionAccountingRecord,
    EconomicBenchmarkState,
)
from backtest_engine.economic_accounting import (
    apply_session_open_economic_accounting,
    value_economic_portfolio,
)
from backtest_engine.economic_execution_models import (
    ECONOMIC_EXECUTION_ENGINE_VERSION,
    CompletedEconomicBacktestResult,
    EconomicCorporateActionAuditRecord,
    EconomicDailyRecord,
    EconomicExecutionError,
    EconomicMarketDataExecutionLineage,
    EconomicSignalRecord,
    EconomicTradeRecord,
    EconomicTransactionCostTotals,
    ResolvedEconomicBacktestConfig,
    SnapshotV2ExecutionInputLineage,
)
from backtest_engine.economic_identity import derive_economic_execution_identity
from backtest_engine.economic_models import (
    ECONOMIC_ACCOUNTING_POLICY_VERSION,
    CorporateActionAccountingRecord,
    EconomicPortfolioState,
)
from backtest_engine.identity import canonical_json_sha256
from backtest_engine.metrics import (
    build_drawdown_series,
    build_monthly_returns,
    calculate_metrics,
)
from backtest_engine.models import (
    DailyEquityRecord,
    ExecutionMetadata,
    TradeRecord,
)
from backtest_engine.snapshot_pair import (
    DailyMarketDataSnapshotPairV2,
    prepare_daily_market_data_snapshot_pair_v2,
)
from backtest_engine.strategy_execution import apply_initial_integer_buy
from backtest_engine.timing import (
    DAILY_INFORMATION_TIMING_POLICY_VERSION,
    build_daily_decision_information_boundary,
)
from research_sdk.contracts import TemporalCoverage
from research_sdk.contracts.daily_market_data_economics import (
    DailyMarketDataCorporateActionEvent,
    DailyMarketDataResearchProfile,
    corporate_action_event_economic_date,
)
from research_sdk.contracts.daily_market_data_snapshots import (
    DAILY_MARKET_DATA_BUNDLE_MANIFEST_PATH,
)
from research_sdk.daily_market_data_storage.serialization import sha256_bytes
from research_sdk.daily_market_data_storage.verification_v2 import (
    VerifiedDailyMarketDataSnapshotV2,
)

LATEST_KNOWN_LIMITATION = (
    "snapshot-v2 source evidence is LATEST_KNOWN and is not point-in-time "
    "strategy knowledge"
)
CORPORATE_ACTION_INFORMATION_LIMITATION = (
    "corporate-action evidence is economic-accounting input only and is not a "
    "strategy signal"
)
NO_TRADING_AUTOMATION_LIMITATION = (
    "research execution only; paper trading and live trading are not approved"
)


def run_snapshot_v2_buy_and_hold_backtest(
    *,
    asset_files: Mapping[str, bytes],
    benchmark_files: Mapping[str, bytes],
    research_profile: DailyMarketDataResearchProfile,
    resolved_config: ResolvedEconomicBacktestConfig,
    execution_metadata: ExecutionMetadata,
) -> CompletedEconomicBacktestResult:
    """Verify exact snapshot bytes and execute the pure economic baseline."""

    config = ResolvedEconomicBacktestConfig.model_validate(
        resolved_config.model_dump(mode="python")
    )
    metadata = ExecutionMetadata.model_validate(
        execution_metadata.model_dump(mode="python")
    )
    profile = DailyMarketDataResearchProfile.model_validate(
        research_profile.model_dump(mode="python")
    )
    copied_asset_files = _copy_exact_bundle(asset_files, role="asset")
    copied_benchmark_files = _copy_exact_bundle(benchmark_files, role="benchmark")

    pair = prepare_daily_market_data_snapshot_pair_v2(
        asset_files=copied_asset_files,
        benchmark_files=copied_benchmark_files,
        research_profile=profile,
        start_date=config.start_date,
        end_date=config.end_date,
    )
    _validate_execution_authority(pair=pair, config=config)
    lineage = _build_execution_lineage(
        pair=pair,
        profile=profile,
        asset_files=copied_asset_files,
        benchmark_files=copied_benchmark_files,
    )
    digest, run_id = derive_economic_execution_identity(
        config=config,
        market_data_lineage=lineage,
    )
    return _execute_verified_pair(
        pair=pair,
        config=config,
        metadata=metadata,
        lineage=lineage,
        digest=digest,
        run_id=run_id,
    )


def _execute_verified_pair(
    *,
    pair: DailyMarketDataSnapshotPairV2,
    config: ResolvedEconomicBacktestConfig,
    metadata: ExecutionMetadata,
    lineage: EconomicMarketDataExecutionLineage,
    digest: str,
    run_id: str,
) -> CompletedEconomicBacktestResult:
    sessions = pair.run_session_dates
    asset_verified = pair.asset.verified_snapshot
    benchmark_verified = pair.benchmark.verified_snapshot
    strategy_state = EconomicPortfolioState(
        instrument_id=asset_verified.instrument_id,
        currency=asset_verified.bar_provenance.currency,
        cash=config.initial_capital,
        quantity=0,
        total_book_cost=Decimal("0"),
    )
    benchmark_state = EconomicBenchmarkState(
        policy_version="daily-etf-gross-benchmark-economic-accounting-v1",
        instrument_id=benchmark_verified.instrument_id,
        currency=benchmark_verified.bar_provenance.currency,
        cash=config.initial_capital,
        fractional_units=Decimal("0"),
    )

    first_boundary = build_daily_decision_information_boundary(
        decision_session=sessions[0],
        expected_session_dates=sessions,
    )
    if (
        first_boundary.latest_observable_complete_bar_session is not None
        or first_boundary.observable_complete_bar_sessions
    ):
        raise EconomicExecutionError(
            "first pre-run decision must not observe a complete daily bar"
        )
    signals = (
        EconomicSignalRecord(
            decision_authority="pre_run_unconditional",
            execution_session=sessions[0],
            symbol="QQQ",
            signal_name="unconditional_initial_allocation",
            order_type_assumption="market_on_open",
            execution_price_policy="raw_open",
            latest_observable_complete_bar_session=None,
            observable_complete_bar_sessions=(),
            timing_policy_version=config.timing_policy_version,
            lookback_authority="none_pre_run_unconditional",
            lag_authority="pre_run_decision_to_first_session_open",
        ),
    )

    asset_events = asset_verified.corporate_action_evidence.events
    benchmark_events = benchmark_verified.corporate_action_evidence.events
    daily_records: list[EconomicDailyRecord] = []
    audit_records: list[EconomicCorporateActionAuditRecord] = []
    trades: tuple[EconomicTradeRecord, ...] = ()
    cumulative_commission = Decimal("0")
    cumulative_slippage = Decimal("0")

    for index, (session, asset_bar, benchmark_bar) in enumerate(
        zip(
            sessions,
            pair.asset_run_bars,
            pair.benchmark_run_bars,
            strict=True,
        )
    ):
        strategy_state, strategy_audit = apply_session_open_economic_accounting(
            state=strategy_state,
            session_date=session,
            expected_session_dates=sessions,
            corporate_action_events=_events_for_session(asset_events, session),
        )
        benchmark_state, benchmark_audit = (
            apply_session_open_benchmark_economic_accounting(
                state=benchmark_state,
                session_date=session,
                expected_session_dates=sessions,
                corporate_action_events=_events_for_session(
                    benchmark_events,
                    session,
                ),
            )
        )
        audit_records.extend(_strategy_audit_records(strategy_audit))
        audit_records.extend(_benchmark_audit_records(benchmark_audit))

        if index == 0:
            strategy_state, fill = apply_initial_integer_buy(
                state=strategy_state,
                raw_execution_price=asset_bar.open,
                commission=config.commission,
                slippage=config.slippage,
            )
            benchmark_state = apply_initial_benchmark_buy(
                state=benchmark_state,
                raw_execution_price=benchmark_bar.open,
            )
            cumulative_commission = fill.commission
            cumulative_slippage = fill.slippage
            trades = (
                EconomicTradeRecord(
                    execution_session=session,
                    symbol="QQQ",
                    side="buy",
                    quantity=fill.quantity,
                    raw_open=fill.raw_price,
                    fill_price=fill.fill_price,
                    executed_notional=fill.executed_notional,
                    commission=fill.commission,
                    slippage=fill.slippage,
                    total_cash_spent=fill.total_cash_spent,
                    decision_authority="pre_run_unconditional",
                    timing_policy_version=config.timing_policy_version,
                ),
            )

        strategy_valuation = value_economic_portfolio(
            state=strategy_state,
            session_date=session,
            market_price=asset_bar.close,
        )
        benchmark_valuation = value_economic_benchmark(
            state=benchmark_state,
            session_date=session,
            raw_market_price=benchmark_bar.close,
        )
        daily_records.append(
            EconomicDailyRecord(
                session=session,
                strategy_cash=strategy_valuation.cash,
                strategy_quantity=strategy_valuation.quantity,
                strategy_raw_close=strategy_valuation.market_price,
                strategy_market_value=strategy_valuation.market_value,
                strategy_outstanding_receivable_value=(
                    strategy_valuation.receivable_value
                ),
                strategy_total_book_cost=strategy_valuation.total_book_cost,
                strategy_total_economic_equity=strategy_valuation.total_equity,
                benchmark_cash=benchmark_valuation.cash,
                benchmark_fractional_units=benchmark_valuation.fractional_units,
                benchmark_raw_close=benchmark_valuation.market_price,
                benchmark_market_value=benchmark_valuation.market_value,
                benchmark_outstanding_receivable_value=(
                    benchmark_valuation.receivable_value
                ),
                benchmark_total_economic_equity=benchmark_valuation.total_equity,
                cumulative_strategy_commission=cumulative_commission,
                cumulative_strategy_slippage=cumulative_slippage,
            )
        )

    _require_all_events_applied_once(
        state_event_ids=strategy_state.applied_corporate_action_event_ids,
        events=asset_events,
        sessions=sessions,
        role="asset",
    )
    _require_all_events_applied_once(
        state_event_ids=benchmark_state.applied_corporate_action_event_ids,
        events=benchmark_events,
        sessions=sessions,
        role="benchmark",
    )
    daily = tuple(daily_records)
    legacy_daily = tuple(
        DailyEquityRecord(
            trading_date=row.session,
            strategy_equity=row.strategy_total_economic_equity,
            cash=row.strategy_cash,
            quantity=row.strategy_quantity,
            qqq_close=row.strategy_raw_close,
            benchmark_equity=row.benchmark_total_economic_equity,
            spy_close=row.benchmark_raw_close,
        )
        for row in daily
    )
    legacy_trades = tuple(
        TradeRecord(
            trading_date=trade.execution_session,
            symbol=trade.symbol,
            side=trade.side,
            quantity=trade.quantity,
            raw_price=trade.raw_open,
            fill_price=trade.fill_price,
            executed_notional=trade.executed_notional,
            commission=trade.commission,
            slippage=trade.slippage,
            total_cash_spent=trade.total_cash_spent,
        )
        for trade in trades
    )
    drawdown = build_drawdown_series(legacy_daily)
    monthly_returns = build_monthly_returns(
        initial_capital=config.initial_capital,
        daily_equity=legacy_daily,
    )
    metrics = calculate_metrics(
        initial_capital=config.initial_capital,
        daily_equity=legacy_daily,
        drawdown_series=drawdown,
        trades=legacy_trades,
    )
    return CompletedEconomicBacktestResult(
        run_id=run_id,
        full_execution_identity_digest=digest,
        resolved_config=config,
        market_data_lineage=lineage,
        execution_metadata=metadata,
        daily_records=daily,
        trade_records=trades,
        signal_records=signals,
        corporate_action_audit=tuple(audit_records),
        metrics=metrics,
        drawdown_series=drawdown,
        monthly_returns=monthly_returns,
        ending_strategy_state=strategy_state,
        ending_benchmark_state=benchmark_state,
        transaction_cost_totals=EconomicTransactionCostTotals(
            strategy_commission=cumulative_commission,
            strategy_slippage=cumulative_slippage,
        ),
        deterministic_limitations=(
            LATEST_KNOWN_LIMITATION,
            CORPORATE_ACTION_INFORMATION_LIMITATION,
            NO_TRADING_AUTOMATION_LIMITATION,
        ),
    )


def _validate_execution_authority(
    *,
    pair: DailyMarketDataSnapshotPairV2,
    config: ResolvedEconomicBacktestConfig,
) -> None:
    if config.engine_version != ECONOMIC_EXECUTION_ENGINE_VERSION:
        raise EconomicExecutionError("unsupported economic engine version")
    if config.strategy_accounting_policy_version != ECONOMIC_ACCOUNTING_POLICY_VERSION:
        raise EconomicExecutionError("unsupported strategy accounting policy")
    if config.benchmark_accounting_policy_version != (
        BENCHMARK_ECONOMIC_POLICY_VERSION
    ):
        raise EconomicExecutionError("unsupported benchmark accounting policy")
    if config.timing_policy_version != DAILY_INFORMATION_TIMING_POLICY_VERSION:
        raise EconomicExecutionError("unsupported timing policy")
    for role, loaded in (("asset", pair.asset), ("benchmark", pair.benchmark)):
        coverage = loaded.verified_snapshot.bar_provenance.temporal_coverage
        if coverage is not TemporalCoverage.LATEST_KNOWN:
            raise EconomicExecutionError(
                f"{role} snapshot temporal coverage must be LATEST_KNOWN"
            )


def _build_execution_lineage(
    *,
    pair: DailyMarketDataSnapshotPairV2,
    profile: DailyMarketDataResearchProfile,
    asset_files: Mapping[str, bytes],
    benchmark_files: Mapping[str, bytes],
) -> EconomicMarketDataExecutionLineage:
    return EconomicMarketDataExecutionLineage(
        asset=_snapshot_lineage(
            verified=pair.asset.verified_snapshot,
            role="asset",
            files=asset_files,
        ),
        benchmark=_snapshot_lineage(
            verified=pair.benchmark.verified_snapshot,
            role="benchmark",
            files=benchmark_files,
        ),
        research_profile=profile,
        research_profile_hash=pair.profile_hash,
        run_session_dates=pair.run_session_dates,
        run_session_authority_hash=(
            f"sha256:{canonical_json_sha256(pair.run_session_dates)}"
        ),
    )


def _snapshot_lineage(
    *,
    verified: VerifiedDailyMarketDataSnapshotV2,
    role: Literal["asset", "benchmark"],
    files: Mapping[str, bytes],
) -> SnapshotV2ExecutionInputLineage:
    symbol: Literal["QQQ", "SPY"] = "QQQ" if role == "asset" else "SPY"
    if verified.quality_report.instrument.symbol != symbol:
        raise EconomicExecutionError("verified snapshot symbol does not match role")
    temporal_coverage = verified.bar_provenance.temporal_coverage
    if temporal_coverage is not TemporalCoverage.LATEST_KNOWN:
        raise EconomicExecutionError("snapshot lineage requires LATEST_KNOWN")
    return SnapshotV2ExecutionInputLineage(
        role=role,
        symbol=symbol,
        snapshot_id=verified.snapshot_id,
        instrument_id=verified.instrument_id,
        data_snapshot_manifest=verified.manifest,
        semantic_content_hash=verified.semantic_content_hash,
        policy_hash=verified.policy_hash,
        expected_sessions_hash=verified.expected_sessions_hash,
        bar_provenance_hash=verified.bar_provenance_hash,
        corporate_action_semantic_hash=verified.corporate_action_semantic_hash,
        corporate_action_evidence_authority_hash=(
            verified.corporate_action_evidence_authority_hash
        ),
        bundle_manifest_content_hash=sha256_bytes(
            files[DAILY_MARKET_DATA_BUNDLE_MANIFEST_PATH]
        ),
        bundle_files=verified.bundle_manifest.files,
        temporal_coverage=temporal_coverage,
    )


def _events_for_session(
    events: tuple[DailyMarketDataCorporateActionEvent, ...],
    session: date,
) -> tuple[DailyMarketDataCorporateActionEvent, ...]:
    return tuple(
        event
        for event in events
        if corporate_action_event_economic_date(event) == session
    )


def _strategy_audit_records(
    records: tuple[CorporateActionAccountingRecord, ...],
) -> tuple[EconomicCorporateActionAuditRecord, ...]:
    return tuple(
        EconomicCorporateActionAuditRecord(
            portfolio_role="strategy",
            session=record.session_date,
            event_id=record.event_id,
            instrument_id=record.instrument_id,
            event_type=record.event_type,
            accounting_action=record.accounting_action,
            position_unit_policy="integer_shares",
            pre_position=Decimal(record.pre_quantity),
            post_position=Decimal(record.post_quantity),
            entitlement_position=Decimal(record.entitlement_quantity),
            receivable_delta=record.receivable_delta,
            cash_delta=record.cash_delta,
        )
        for record in records
    )


def _benchmark_audit_records(
    records: tuple[BenchmarkCorporateActionAccountingRecord, ...],
) -> tuple[EconomicCorporateActionAuditRecord, ...]:
    return tuple(
        EconomicCorporateActionAuditRecord(
            portfolio_role="benchmark",
            session=record.session_date,
            event_id=record.event_id,
            instrument_id=record.instrument_id,
            event_type=record.event_type,
            accounting_action=record.accounting_action,
            position_unit_policy="fractional_decimal_12_units",
            pre_position=record.pre_units,
            post_position=record.post_units,
            entitlement_position=record.entitlement_units,
            receivable_delta=record.receivable_delta,
            cash_delta=record.cash_delta,
        )
        for record in records
    )


def _require_all_events_applied_once(
    *,
    state_event_ids: tuple[str, ...],
    events: tuple[DailyMarketDataCorporateActionEvent, ...],
    sessions: tuple[date, ...],
    role: str,
) -> None:
    in_run_event_ids = tuple(
        sorted(
            event.event_id
            for event in events
            if corporate_action_event_economic_date(event) in set(sessions)
        )
    )
    if state_event_ids != in_run_event_ids:
        raise EconomicExecutionError(
            f"{role} corporate-action events were not each applied exactly once"
        )


def _copy_exact_bundle(
    files: Mapping[str, bytes],
    *,
    role: str,
) -> dict[str, bytes]:
    copied: dict[str, bytes] = {}
    for path, content in files.items():
        if type(path) is not str or type(content) is not bytes:
            raise EconomicExecutionError(
                f"{role} bundle must map exact string paths to bytes"
            )
        copied[path] = content
    return copied


__all__ = [
    "CORPORATE_ACTION_INFORMATION_LIMITATION",
    "LATEST_KNOWN_LIMITATION",
    "NO_TRADING_AUTOMATION_LIMITATION",
    "run_snapshot_v2_buy_and_hold_backtest",
]
