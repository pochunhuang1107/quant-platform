"""Synthetic fixture daily market-data loading and validation."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from backtest_engine.identity import file_sha256_bytes
from backtest_engine.models import (
    AlignedDailyBars,
    DailyBar,
    DailyBarSnapshot,
    ResolvedBacktestConfig,
)


def load_daily_bar_snapshot(path: Path) -> tuple[DailyBarSnapshot, str]:
    """Load a synthetic daily bar snapshot and return its byte SHA-256."""

    content = path.read_bytes()
    payload = json.loads(content.decode("utf-8"))
    snapshot = DailyBarSnapshot.model_validate(payload)
    return snapshot, file_sha256_bytes(content)


def align_daily_bars(
    *,
    snapshot: DailyBarSnapshot,
    config: ResolvedBacktestConfig,
) -> AlignedDailyBars:
    """Validate and align QQQ/SPY bars for the configured inclusive date range."""

    if snapshot.snapshot_id != config.data_snapshot_id:
        raise ValueError("snapshot identity must match resolved config")

    bars_in_range = tuple(
        bar
        for bar in snapshot.bars
        if config.start_date <= bar.trading_date <= config.end_date
    )
    by_symbol = {
        "QQQ": _bars_by_date(bars_in_range, "QQQ"),
        "SPY": _bars_by_date(bars_in_range, "SPY"),
    }
    qqq_dates = set(by_symbol["QQQ"])
    spy_dates = set(by_symbol["SPY"])
    if qqq_dates != spy_dates:
        raise ValueError("QQQ and SPY must have exactly matching date sets")
    if len(qqq_dates) < 2:
        raise ValueError("at least two aligned observations are required")

    ordered_dates = tuple(sorted(qqq_dates))
    return AlignedDailyBars(
        snapshot=snapshot,
        qqq_bars=tuple(
            by_symbol["QQQ"][trading_date] for trading_date in ordered_dates
        ),
        spy_bars=tuple(
            by_symbol["SPY"][trading_date] for trading_date in ordered_dates
        ),
    )


def snapshot_from_payload(payload: dict[str, Any]) -> DailyBarSnapshot:
    """Build a sorted immutable snapshot from a decoded JSON object."""

    return DailyBarSnapshot.model_validate(payload)


def _bars_by_date(
    bars: tuple[DailyBar, ...],
    symbol: str,
) -> dict[date, DailyBar]:
    return {bar.trading_date: bar for bar in bars if bar.symbol == symbol}


__all__ = [
    "align_daily_bars",
    "load_daily_bar_snapshot",
    "snapshot_from_payload",
]
