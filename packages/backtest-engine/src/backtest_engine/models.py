"""Immutable models for the deterministic daily ETF backtest slice."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Literal, Self

from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, field_validator, model_validator

MONEY_QUANT = Decimal("0.000001")
RATIO_QUANT = Decimal("0.000000000001")
SHARE_QUANT = Decimal("1")
ENGINE_VERSION = "backtest-engine-deterministic-etf-0.1.0"
ARTIFACT_VALIDATOR_VERSION = "backtest-engine-artifact-writer-0.1.0"


class BacktestEngineModel(PydanticBaseModel):
    """Base model for deterministic backtest-engine payloads."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class BasisPointAssumption(BacktestEngineModel):
    """Basis-point assumption with durable explanatory text."""

    bps: Decimal
    description: str

    @field_validator("bps", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return parse_decimal(value)

    @field_validator("bps")
    @classmethod
    def validate_nonnegative_bps(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("basis points must be nonnegative")
        return value

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("description must not be blank")
        return value


class ResolvedBacktestConfig(BacktestEngineModel):
    """Fully resolved deterministic QQQ buy-and-hold configuration."""

    experiment_id: str
    strategy_id: str
    strategy_version: str
    engine_version: str
    asset_symbol: Literal["QQQ"]
    benchmark_symbol: Literal["SPY"]
    start_date: date
    end_date: date
    frequency: Literal["daily"]
    initial_capital: Decimal
    commission: BasisPointAssumption
    slippage: BasisPointAssumption
    execution_price_field: Literal["open"]
    valuation_price_field: Literal["close"]
    share_policy: Literal["integer"]
    data_snapshot_id: str
    benchmark_snapshot_id: str
    random_seed: None
    no_randomness_reason: str
    logical_execution_at: datetime

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
        "engine_version",
        "data_snapshot_id",
        "benchmark_snapshot_id",
        "no_randomness_reason",
    )
    @classmethod
    def validate_nonblank_string(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("string fields must not be blank")
        return value

    @field_validator("logical_execution_at")
    @classmethod
    def normalize_logical_execution_at(cls, value: datetime) -> datetime:
        return require_utc_datetime(value)

    @model_validator(mode="after")
    def validate_config(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if self.random_seed is not None:
            raise ValueError("random_seed must be absent for this deterministic slice")
        return self


class ExecutionMetadata(BacktestEngineModel):
    """Injected execution lineage; the engine never inspects Git or environment."""

    git_commit_sha: str
    repo_dirty: bool
    python_version: str
    platform: str
    dependency_lock_hash: str
    execution_command: str

    @field_validator(
        "git_commit_sha",
        "python_version",
        "platform",
        "dependency_lock_hash",
        "execution_command",
    )
    @classmethod
    def validate_nonblank_string(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("execution metadata string fields must not be blank")
        return value


class DailyBar(BacktestEngineModel):
    """Single synthetic daily OHLCV bar."""

    symbol: str
    trading_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        if value not in {"QQQ", "SPY"}:
            raise ValueError("only QQQ and SPY are supported")
        return value

    @field_validator("open", "high", "low", "close", mode="before")
    @classmethod
    def parse_price(cls, value: object) -> Decimal:
        return parse_decimal(value)

    @field_validator("volume")
    @classmethod
    def validate_volume(cls, value: int) -> int:
        if value < 0:
            raise ValueError("volume must be nonnegative")
        return value

    @model_validator(mode="after")
    def validate_ohlc(self) -> Self:
        for field_name in ("open", "high", "low", "close"):
            if getattr(self, field_name) <= 0:
                raise ValueError(f"{field_name} must be positive")
        if self.high < max(self.open, self.close):
            raise ValueError("high must be at least max(open, close)")
        if self.low > min(self.open, self.close):
            raise ValueError("low must be at most min(open, close)")
        return self


class DailyBarSnapshot(BacktestEngineModel):
    """Synthetic fixture-only daily bar snapshot."""

    fixture_name: str
    fixture_version: str
    snapshot_id: str
    timezone: str
    currency: str
    adjustment_policy: Literal["none"]
    logical_available_at: datetime
    source_dataset: str
    bars: tuple[DailyBar, ...]

    @field_validator(
        "fixture_name",
        "fixture_version",
        "snapshot_id",
        "timezone",
        "currency",
        "source_dataset",
    )
    @classmethod
    def validate_nonblank_string(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("snapshot metadata string fields must not be blank")
        return value

    @field_validator("logical_available_at")
    @classmethod
    def normalize_logical_available_at(cls, value: datetime) -> datetime:
        return require_utc_datetime(value)

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        symbols = {bar.symbol for bar in self.bars}
        if symbols != {"QQQ", "SPY"}:
            raise ValueError("snapshot must contain exactly QQQ and SPY")

        seen: set[tuple[str, date]] = set()
        for bar in self.bars:
            key = (bar.symbol, bar.trading_date)
            if key in seen:
                raise ValueError("duplicate symbol/date rows are not allowed")
            seen.add(key)

        object.__setattr__(
            self,
            "bars",
            tuple(sorted(self.bars, key=lambda bar: (bar.trading_date, bar.symbol))),
        )
        return self


class AlignedDailyBars(BacktestEngineModel):
    """Validated aligned QQQ/SPY daily bars for a requested window."""

    snapshot: DailyBarSnapshot
    qqq_bars: tuple[DailyBar, ...]
    spy_bars: tuple[DailyBar, ...]

    @property
    def trading_dates(self) -> tuple[date, ...]:
        return tuple(bar.trading_date for bar in self.qqq_bars)


class TradeRecord(BacktestEngineModel):
    """Executed strategy trade."""

    trading_date: date
    symbol: str
    side: Literal["buy"]
    quantity: int
    raw_price: Decimal
    fill_price: Decimal
    executed_notional: Decimal
    commission: Decimal
    slippage: Decimal
    total_cash_spent: Decimal


class SignalRecord(BacktestEngineModel):
    """Deterministic signal/order record for the unconditional allocation."""

    trading_date: date
    symbol: str
    signal_name: Literal["unconditional_initial_allocation"]
    target_allocation: Literal["buy_and_hold"]
    order_type_assumption: Literal["market_on_open"]
    execution_price_field: Literal["open"]
    no_lookahead: bool


class DailyEquityRecord(BacktestEngineModel):
    """Daily strategy and benchmark valuation row."""

    trading_date: date
    strategy_equity: Decimal
    cash: Decimal
    quantity: int
    qqq_close: Decimal
    benchmark_equity: Decimal
    spy_close: Decimal


class DrawdownRecord(BacktestEngineModel):
    """Daily drawdown row."""

    trading_date: date
    running_peak: Decimal
    drawdown: Decimal


class MonthlyReturnRecord(BacktestEngineModel):
    """Deterministic month-end return row."""

    month: str
    start_equity: Decimal
    end_equity: Decimal
    return_value: Decimal


class BacktestMetrics(BacktestEngineModel):
    """Approved deterministic metric set for the first engine slice."""

    total_return: Decimal
    benchmark_total_return: Decimal
    excess_return: Decimal
    maximum_drawdown: Decimal
    realized_commission: Decimal
    realized_slippage: Decimal
    ending_equity: Decimal
    number_of_trades: int
    observation_count: int


class CompletedBacktestResult(BacktestEngineModel):
    """Engine-owned completed result envelope without persistence state."""

    run_id: str
    full_execution_identity_digest: str
    resolved_config: ResolvedBacktestConfig
    execution_metadata: ExecutionMetadata
    input_snapshot_id: str
    fixture_content_hash: str
    aligned_dates: tuple[date, ...]
    daily_equity: tuple[DailyEquityRecord, ...]
    drawdown_series: tuple[DrawdownRecord, ...]
    monthly_returns: tuple[MonthlyReturnRecord, ...]
    trades: tuple[TradeRecord, ...]
    signals: tuple[SignalRecord, ...]
    metrics: BacktestMetrics
    total_realized_commission: Decimal
    total_realized_slippage: Decimal
    ending_cash: Decimal
    ending_quantity: int
    ending_equity: Decimal
    deterministic_warnings: tuple[str, ...]
    leakage_assumptions: tuple[str, ...]


class ArtifactFileMetadata(BacktestEngineModel):
    """Deterministic metadata for one generated payload artifact."""

    artifact_id: str
    artifact_kind: str
    filename: str
    format: str
    path: str
    uri: str
    content_hash: str
    size_bytes: int
    row_count: int | None
    created_at: datetime
    validator_version: str


class GeneratedArtifactBundle(BacktestEngineModel):
    """Generated local artifact bundle metadata."""

    artifact_root_path: str
    artifact_root_uri: str
    artifact_manifest_path: str
    artifact_manifest_uri: str
    artifact_manifest_hash: str
    manifest_id: str
    payload_artifacts: tuple[ArtifactFileMetadata, ...]
    run_artifact_manifest: Any
    write_order: tuple[str, ...]


def parse_decimal(value: object) -> Decimal:
    """Parse Decimal values from canonical JSON strings or integral values."""

    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, int):
        parsed = Decimal(value)
    elif isinstance(value, str):
        parsed = Decimal(value)
    else:
        raise TypeError("Decimal values must be encoded as strings or integers")

    if not parsed.is_finite():
        raise ValueError("Decimal values must be finite")
    return parsed


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_EVEN)


def quantize_ratio(value: Decimal) -> Decimal:
    return value.quantize(RATIO_QUANT, rounding=ROUND_HALF_EVEN)


def require_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime values must be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "ARTIFACT_VALIDATOR_VERSION",
    "ENGINE_VERSION",
    "MONEY_QUANT",
    "RATIO_QUANT",
    "AlignedDailyBars",
    "ArtifactFileMetadata",
    "BacktestMetrics",
    "BasisPointAssumption",
    "CompletedBacktestResult",
    "DailyBar",
    "DailyBarSnapshot",
    "DailyEquityRecord",
    "DrawdownRecord",
    "ExecutionMetadata",
    "GeneratedArtifactBundle",
    "MonthlyReturnRecord",
    "ResolvedBacktestConfig",
    "SignalRecord",
    "TradeRecord",
    "parse_decimal",
    "quantize_money",
    "quantize_ratio",
]
