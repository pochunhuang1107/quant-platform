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

__all__ = [
    "MASSIVE_DAILY_MARKET_DATA_ADAPTER_VERSION",
    "AdaptedMassiveDailyMarketData",
    "MassiveDailyMarketDataAdapterContext",
    "MassiveDailyMarketDataAdapterError",
    "MassiveResponseParsingError",
    "MassiveResponseValidationError",
    "MassiveUnsupportedSemanticError",
    "adapt_massive_daily_market_data_source_capture",
]
