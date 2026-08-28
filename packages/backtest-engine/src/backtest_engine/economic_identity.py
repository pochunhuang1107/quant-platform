"""Deterministic identity for snapshot-v2 economic executions."""

from __future__ import annotations

from backtest_engine.economic_execution_models import (
    ECONOMIC_EXECUTION_IDENTITY_VERSION,
    CompletedEconomicBacktestResult,
    EconomicMarketDataExecutionLineage,
    ResolvedEconomicBacktestConfig,
)
from backtest_engine.identity import RUN_ID_PREFIX, canonical_json_sha256


def derive_economic_execution_identity(
    *,
    config: ResolvedEconomicBacktestConfig,
    market_data_lineage: EconomicMarketDataExecutionLineage,
) -> tuple[str, str]:
    """Derive economic identity without runtime or wall-clock metadata."""

    digest = canonical_json_sha256(
        {
            "identity_version": ECONOMIC_EXECUTION_IDENTITY_VERSION,
            "resolved_economic_config": config,
            "market_data_execution_lineage": market_data_lineage,
        }
    )
    return digest, f"{RUN_ID_PREFIX}{digest}"


def identity_from_completed_economic_result(
    result: CompletedEconomicBacktestResult,
) -> tuple[str, str]:
    """Recompute identity from immutable economic inputs retained in a result."""

    return derive_economic_execution_identity(
        config=result.resolved_config,
        market_data_lineage=result.market_data_lineage,
    )


__all__ = [
    "derive_economic_execution_identity",
    "identity_from_completed_economic_result",
]
