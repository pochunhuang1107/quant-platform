"""Offline daily market-data provider adapters."""

from research_sdk.daily_market_data_adapters.massive import (
    MASSIVE_DAILY_MARKET_DATA_ADAPTER_VERSION,
    AdaptedMassiveDailyMarketData,
    MassiveDailyMarketDataAdapterContext,
    MassiveDailyMarketDataAdapterError,
    MassiveResponseParsingError,
    MassiveResponseValidationError,
    MassiveUnsupportedSemanticError,
    adapt_massive_daily_market_data_source_capture,
)
from research_sdk.daily_market_data_adapters.massive_snapshot_v2 import (
    MassiveDailyMarketDataCapturePairCompatibilityError,
    MassiveDailyMarketDataSnapshotBridgeContext,
    MassiveDailyMarketDataSnapshotBridgeError,
    plan_massive_daily_market_data_snapshot_v2,
    validate_massive_daily_market_data_capture_pair_compatibility,
)

__all__ = [
    "MASSIVE_DAILY_MARKET_DATA_ADAPTER_VERSION",
    "AdaptedMassiveDailyMarketData",
    "MassiveDailyMarketDataAdapterContext",
    "MassiveDailyMarketDataAdapterError",
    "MassiveDailyMarketDataCapturePairCompatibilityError",
    "MassiveDailyMarketDataSnapshotBridgeContext",
    "MassiveDailyMarketDataSnapshotBridgeError",
    "MassiveResponseParsingError",
    "MassiveResponseValidationError",
    "MassiveUnsupportedSemanticError",
    "adapt_massive_daily_market_data_source_capture",
    "plan_massive_daily_market_data_snapshot_v2",
    "validate_massive_daily_market_data_capture_pair_compatibility",
]
