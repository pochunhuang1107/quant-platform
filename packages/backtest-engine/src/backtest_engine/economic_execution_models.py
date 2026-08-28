"""Versioned contracts for snapshot-v2 economic backtest execution."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import field_validator, model_validator

from backtest_engine.benchmark_economic_models import EconomicBenchmarkState
from backtest_engine.economic_models import (
    EconomicPortfolioState,
    quantize_economic_money,
)
from backtest_engine.models import (
    BacktestEngineModel,
    BacktestMetrics,
    BasisPointAssumption,
    DrawdownRecord,
    ExecutionMetadata,
    MonthlyReturnRecord,
    parse_decimal,
    require_utc_datetime,
)
from research_sdk.contracts import DataSnapshotManifest, TemporalCoverage
from research_sdk.contracts.daily_market_data_economics import (
    DailyMarketDataResearchProfile,
)
from research_sdk.contracts.daily_market_data_snapshots_v2 import (
    DailyMarketDataSnapshotFileEntryV2,
)
from research_sdk.daily_market_data import (
    derive_daily_market_data_research_profile_hash,
)

ECONOMIC_EXECUTION_CONTRACT_VERSION = "snapshot-v2-economic-backtest-v1"
ECONOMIC_EXECUTION_ENGINE_VERSION = (
    "backtest-engine-snapshot-v2-economic-buy-and-hold-0.1.0"
)
ECONOMIC_EXECUTION_LINEAGE_VERSION = "snapshot-v2-market-data-lineage-v1"
ECONOMIC_EXECUTION_IDENTITY_VERSION = "snapshot-v2-economic-execution-identity-v1"
ECONOMIC_ARTIFACT_VALIDATOR_VERSION = "snapshot-v2-economic-artifact-writer-v1"


class EconomicExecutionError(ValueError):
    """Raised when verified inputs cannot be executed without ambiguity."""


class ResolvedEconomicBacktestConfig(BacktestEngineModel):
    """Fully resolved economic policy for the first snapshot-v2 baseline."""

    contract_version: Literal["snapshot-v2-economic-backtest-v1"] = (
        "snapshot-v2-economic-backtest-v1"
    )
    experiment_id: str
    strategy_id: str
    strategy_version: str
    engine_version: Literal[
        "backtest-engine-snapshot-v2-economic-buy-and-hold-0.1.0"
    ] = "backtest-engine-snapshot-v2-economic-buy-and-hold-0.1.0"
    asset_symbol: Literal["QQQ"] = "QQQ"
    benchmark_symbol: Literal["SPY"] = "SPY"
    start_date: date
    end_date: date
    frequency: Literal["daily"] = "daily"
    initial_capital: Decimal
    commission: BasisPointAssumption
    slippage: BasisPointAssumption
    strategy_execution_price_policy: Literal["raw_open"] = "raw_open"
    strategy_valuation_price_policy: Literal["raw_close"] = "raw_close"
    strategy_share_policy: Literal["integer"] = "integer"
    benchmark_execution_price_policy: Literal["raw_open"] = "raw_open"
    benchmark_valuation_price_policy: Literal["raw_close"] = "raw_close"
    benchmark_unit_policy: Literal["fractional_decimal_12"] = "fractional_decimal_12"
    price_adjustment_policy: Literal["raw"] = "raw"
    distribution_policy: Literal["explicit_receivable_retain_cash"] = (
        "explicit_receivable_retain_cash"
    )
    dividend_reinvestment: Literal[False] = False
    benchmark_commission_policy: Literal["none"] = "none"
    benchmark_slippage_policy: Literal["none"] = "none"
    strategy_accounting_policy_version: Literal["daily-etf-economic-accounting-v1"] = (
        "daily-etf-economic-accounting-v1"
    )
    benchmark_accounting_policy_version: Literal[
        "daily-etf-gross-benchmark-economic-accounting-v1"
    ] = "daily-etf-gross-benchmark-economic-accounting-v1"
    timing_policy_version: Literal["daily-etf-next-expected-session-v1"] = (
        "daily-etf-next-expected-session-v1"
    )
    temporal_coverage_requirement: Literal["latest_known"] = "latest_known"
    random_seed: None = None
    no_randomness_reason: str

    @field_validator("initial_capital", mode="before")
    @classmethod
    def parse_initial_capital(cls, value: object) -> Decimal:
        return parse_decimal(value)

    @field_validator("initial_capital")
    @classmethod
    def validate_initial_capital(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("initial_capital must be positive")
        return value

    @field_validator(
        "experiment_id",
        "strategy_id",
        "strategy_version",
        "no_randomness_reason",
    )
    @classmethod
    def validate_nonblank_string(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("string fields must not be blank")
        return value

    @model_validator(mode="after")
    def validate_config(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class SnapshotV2ExecutionInputLineage(BacktestEngineModel):
    """Exact verified authority retained for one snapshot-v2 input."""

    role: Literal["asset", "benchmark"]
    symbol: Literal["QQQ", "SPY"]
    snapshot_id: str
    instrument_id: str
    data_snapshot_manifest: DataSnapshotManifest
    semantic_content_hash: str
    policy_hash: str
    expected_sessions_hash: str
    bar_provenance_hash: str
    corporate_action_semantic_hash: str
    corporate_action_evidence_authority_hash: str
    bundle_manifest_content_hash: str
    bundle_files: tuple[DailyMarketDataSnapshotFileEntryV2, ...]
    temporal_coverage: Literal[TemporalCoverage.LATEST_KNOWN]

    @model_validator(mode="after")
    def validate_authority(self) -> Self:
        if self.data_snapshot_manifest.snapshot_id != self.snapshot_id:
            raise ValueError("snapshot manifest identity must match lineage")
        expected_symbol = "QQQ" if self.role == "asset" else "SPY"
        if self.symbol != expected_symbol:
            raise ValueError("snapshot role and symbol must match")
        return self


class EconomicMarketDataExecutionLineage(BacktestEngineModel):
    """Dedicated pair lineage used to derive economic execution identity."""

    lineage_version: Literal["snapshot-v2-market-data-lineage-v1"] = (
        "snapshot-v2-market-data-lineage-v1"
    )
    asset: SnapshotV2ExecutionInputLineage
    benchmark: SnapshotV2ExecutionInputLineage
    research_profile: DailyMarketDataResearchProfile
    research_profile_hash: str
    run_session_dates: tuple[date, ...]
    run_session_authority_hash: str
    temporal_coverage: Literal[TemporalCoverage.LATEST_KNOWN] = (
        TemporalCoverage.LATEST_KNOWN
    )
    limitation: Literal[
        "LATEST_KNOWN evidence is not point-in-time strategy knowledge"
    ] = "LATEST_KNOWN evidence is not point-in-time strategy knowledge"

    @model_validator(mode="after")
    def validate_pair_lineage(self) -> Self:
        if self.asset.role != "asset" or self.benchmark.role != "benchmark":
            raise ValueError("lineage roles must be asset then benchmark")
        if self.asset.snapshot_id == self.benchmark.snapshot_id:
            raise ValueError("asset and benchmark snapshot IDs must be distinct")
        if not self.run_session_dates:
            raise ValueError("run_session_dates must not be empty")
        if self.run_session_dates != tuple(sorted(set(self.run_session_dates))):
            raise ValueError("run_session_dates must be unique and ascending")
        if self.research_profile_hash != (
            derive_daily_market_data_research_profile_hash(self.research_profile)
        ):
            raise ValueError("research profile hash must match profile authority")
        return self


class EconomicSignalRecord(BacktestEngineModel):
    """Timing-authoritative record for the unconditional pre-run decision."""

    decision_authority: Literal["pre_run_unconditional"]
    execution_session: date
    symbol: Literal["QQQ"]
    signal_name: Literal["unconditional_initial_allocation"]
    order_type_assumption: Literal["market_on_open"]
    execution_price_policy: Literal["raw_open"]
    latest_observable_complete_bar_session: None
    observable_complete_bar_sessions: tuple[date, ...]
    timing_policy_version: Literal["daily-etf-next-expected-session-v1"]
    lookback_authority: Literal["none_pre_run_unconditional"]
    lag_authority: Literal["pre_run_decision_to_first_session_open"]

    @model_validator(mode="after")
    def validate_no_bar_visibility(self) -> Self:
        if self.observable_complete_bar_sessions:
            raise ValueError("pre-run signal cannot observe complete bars")
        return self


class EconomicTradeRecord(BacktestEngineModel):
    """Executed first-session strategy fill with explicit costs."""

    execution_session: date
    symbol: Literal["QQQ"]
    side: Literal["buy"]
    quantity: int
    raw_open: Decimal
    fill_price: Decimal
    executed_notional: Decimal
    commission: Decimal
    slippage: Decimal
    total_cash_spent: Decimal
    decision_authority: Literal["pre_run_unconditional"]
    timing_policy_version: Literal["daily-etf-next-expected-session-v1"]


class EconomicDailyRecord(BacktestEngineModel):
    """Fully reconcilable daily strategy and benchmark economics."""

    session: date
    strategy_cash: Decimal
    strategy_quantity: int
    strategy_raw_close: Decimal
    strategy_market_value: Decimal
    strategy_outstanding_receivable_value: Decimal
    strategy_total_book_cost: Decimal
    strategy_total_economic_equity: Decimal
    benchmark_cash: Decimal
    benchmark_fractional_units: Decimal
    benchmark_raw_close: Decimal
    benchmark_market_value: Decimal
    benchmark_outstanding_receivable_value: Decimal
    benchmark_total_economic_equity: Decimal
    cumulative_strategy_commission: Decimal
    cumulative_strategy_slippage: Decimal

    @model_validator(mode="after")
    def validate_daily_reconciliation(self) -> Self:
        strategy_market = quantize_economic_money(
            Decimal(self.strategy_quantity) * self.strategy_raw_close
        )
        if self.strategy_market_value != strategy_market:
            raise ValueError(
                "strategy market value must equal quantity times raw close"
            )
        strategy_equity = quantize_economic_money(
            self.strategy_cash
            + self.strategy_market_value
            + self.strategy_outstanding_receivable_value
        )
        if self.strategy_total_economic_equity != strategy_equity:
            raise ValueError("strategy economic equity must reconcile")
        benchmark_market = quantize_economic_money(
            self.benchmark_fractional_units * self.benchmark_raw_close
        )
        if self.benchmark_market_value != benchmark_market:
            raise ValueError("benchmark market value must equal units times raw close")
        benchmark_equity = quantize_economic_money(
            self.benchmark_cash
            + self.benchmark_market_value
            + self.benchmark_outstanding_receivable_value
        )
        if self.benchmark_total_economic_equity != benchmark_equity:
            raise ValueError("benchmark economic equity must reconcile")
        return self


class EconomicCorporateActionAuditRecord(BacktestEngineModel):
    """Normalized immutable audit row across strategy and benchmark kernels."""

    portfolio_role: Literal["strategy", "benchmark"]
    session: date
    event_id: str
    instrument_id: str
    event_type: Literal["cash_distribution", "split", "unsupported"]
    accounting_action: Literal[
        "split_applied",
        "cash_distribution_entitlement",
        "cash_distribution_settlement",
    ]
    position_unit_policy: Literal["integer_shares", "fractional_decimal_12_units"]
    pre_position: Decimal
    post_position: Decimal
    entitlement_position: Decimal
    receivable_delta: Decimal
    cash_delta: Decimal


class EconomicTransactionCostTotals(BacktestEngineModel):
    """Explicit strategy and benchmark transaction-cost reconciliation."""

    strategy_commission: Decimal
    strategy_slippage: Decimal
    benchmark_commission: Decimal = Decimal("0")
    benchmark_slippage: Decimal = Decimal("0")

    @model_validator(mode="after")
    def validate_zero_benchmark_costs(self) -> Self:
        if self.benchmark_commission != 0 or self.benchmark_slippage != 0:
            raise ValueError("benchmark commission and slippage must be zero")
        return self


class CompletedEconomicBacktestResult(BacktestEngineModel):
    """Completed versioned economic result, separate from the legacy runner."""

    result_contract_version: Literal["snapshot-v2-economic-backtest-v1"] = (
        "snapshot-v2-economic-backtest-v1"
    )
    run_id: str
    full_execution_identity_digest: str
    execution_identity_version: Literal[
        "snapshot-v2-economic-execution-identity-v1"
    ] = "snapshot-v2-economic-execution-identity-v1"
    resolved_config: ResolvedEconomicBacktestConfig
    market_data_lineage: EconomicMarketDataExecutionLineage
    execution_metadata: ExecutionMetadata
    daily_records: tuple[EconomicDailyRecord, ...]
    trade_records: tuple[EconomicTradeRecord, ...]
    signal_records: tuple[EconomicSignalRecord, ...]
    corporate_action_audit: tuple[EconomicCorporateActionAuditRecord, ...]
    metrics: BacktestMetrics
    drawdown_series: tuple[DrawdownRecord, ...]
    monthly_returns: tuple[MonthlyReturnRecord, ...]
    ending_strategy_state: EconomicPortfolioState
    ending_benchmark_state: EconomicBenchmarkState
    transaction_cost_totals: EconomicTransactionCostTotals
    temporal_coverage: Literal[TemporalCoverage.LATEST_KNOWN] = (
        TemporalCoverage.LATEST_KNOWN
    )
    deterministic_limitations: tuple[str, ...]

    @model_validator(mode="after")
    def validate_result_reconciliation(self) -> Self:
        if not self.daily_records:
            raise ValueError("completed result requires daily records")
        ending = self.daily_records[-1]
        if ending.strategy_cash != self.ending_strategy_state.cash:
            raise ValueError("ending strategy cash must reconcile")
        if ending.strategy_quantity != self.ending_strategy_state.quantity:
            raise ValueError("ending strategy quantity must reconcile")
        if ending.benchmark_cash != self.ending_benchmark_state.cash:
            raise ValueError("ending benchmark cash must reconcile")
        if ending.benchmark_fractional_units != (
            self.ending_benchmark_state.fractional_units
        ):
            raise ValueError("ending benchmark units must reconcile")
        if self.metrics.ending_equity != ending.strategy_total_economic_equity:
            raise ValueError("ending metric equity must reconcile")
        sessions = tuple(row.session for row in self.daily_records)
        if sessions != self.market_data_lineage.run_session_dates:
            raise ValueError("daily records must exactly match run sessions")
        if len(self.trade_records) != 1 or len(self.signal_records) != 1:
            raise ValueError("economic baseline requires exactly one trade and signal")
        if self.trade_records[0].execution_session != sessions[0]:
            raise ValueError("initial trade must execute on first run session")
        if self.signal_records[0].execution_session != sessions[0]:
            raise ValueError("initial signal must authorize first run session")
        if self.transaction_cost_totals.strategy_commission != (
            self.trade_records[0].commission
        ):
            raise ValueError("strategy commission total must reconcile")
        if self.transaction_cost_totals.strategy_slippage != (
            self.trade_records[0].slippage
        ):
            raise ValueError("strategy slippage total must reconcile")
        if ending.cumulative_strategy_commission != (
            self.transaction_cost_totals.strategy_commission
        ):
            raise ValueError("ending cumulative commission must reconcile")
        if ending.cumulative_strategy_slippage != (
            self.transaction_cost_totals.strategy_slippage
        ):
            raise ValueError("ending cumulative slippage must reconcile")
        return self


def deterministic_artifact_created_at(
    lineage: EconomicMarketDataExecutionLineage,
) -> datetime:
    """Derive artifact time only from already identity-bound input authority."""

    return require_utc_datetime(
        max(
            lineage.asset.data_snapshot_manifest.created_at,
            lineage.benchmark.data_snapshot_manifest.created_at,
        )
    )


__all__ = [
    "ECONOMIC_ARTIFACT_VALIDATOR_VERSION",
    "ECONOMIC_EXECUTION_CONTRACT_VERSION",
    "ECONOMIC_EXECUTION_ENGINE_VERSION",
    "ECONOMIC_EXECUTION_IDENTITY_VERSION",
    "ECONOMIC_EXECUTION_LINEAGE_VERSION",
    "CompletedEconomicBacktestResult",
    "EconomicCorporateActionAuditRecord",
    "EconomicDailyRecord",
    "EconomicExecutionError",
    "EconomicMarketDataExecutionLineage",
    "EconomicSignalRecord",
    "EconomicTradeRecord",
    "EconomicTransactionCostTotals",
    "ResolvedEconomicBacktestConfig",
    "SnapshotV2ExecutionInputLineage",
    "deterministic_artifact_created_at",
]
