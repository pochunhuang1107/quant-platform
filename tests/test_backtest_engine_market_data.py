from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from backtest_engine import (
    ENGINE_VERSION,
    BasisPointAssumption,
    ResolvedBacktestConfig,
    align_daily_bars,
    load_daily_bar_snapshot,
    snapshot_from_payload,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "backtest_engine"
FIXTURE_PATH = FIXTURE_DIR / "synthetic_daily_etf_bars.json"
README_PATH = FIXTURE_DIR / "README.md"


def test_fixture_clearly_identifies_itself_as_synthetic() -> None:
    readme = README_PATH.read_text(encoding="utf-8").casefold()
    payload = load_payload()

    assert "synthetic" in readme
    assert "fixture-only" in readme
    assert "not historical market data" in readme
    assert "must not be used for performance claims" in readme
    assert "no splits or dividends" in readme
    assert "not a production data source" in readme
    assert payload["source_dataset"] == "fixture-only-synthetic-daily-etf-bars"
    assert payload["adjustment_policy"] == "none"


def test_snapshot_canonical_sorting() -> None:
    snapshot, _fixture_hash = load_daily_bar_snapshot(FIXTURE_PATH)

    keys = [(bar.trading_date, bar.symbol) for bar in snapshot.bars]

    assert keys == sorted(keys)
    assert keys[0] == (date(2026, 1, 29), "QQQ")


def test_duplicate_symbol_date_rejected() -> None:
    payload = load_payload()
    payload["bars"].append(dict(payload["bars"][0]))

    with pytest.raises(ValueError, match="duplicate symbol/date"):
        snapshot_from_payload(payload)


def test_missing_spy_date_rejected() -> None:
    payload = load_payload()
    payload["bars"] = [
        bar
        for bar in payload["bars"]
        if not (bar["symbol"] == "SPY" and bar["trading_date"] == "2026-01-31")
    ]
    snapshot = snapshot_from_payload(payload)

    with pytest.raises(ValueError, match="matching date sets"):
        align_daily_bars(snapshot=snapshot, config=resolved_config())


def test_missing_qqq_date_rejected() -> None:
    payload = load_payload()
    payload["bars"] = [
        bar
        for bar in payload["bars"]
        if not (bar["symbol"] == "QQQ" and bar["trading_date"] == "2026-02-03")
    ]
    snapshot = snapshot_from_payload(payload)

    with pytest.raises(ValueError, match="matching date sets"):
        align_daily_bars(snapshot=snapshot, config=resolved_config())


def test_unexpected_symbol_rejected() -> None:
    payload = load_payload()
    payload["bars"][0]["symbol"] = "IWM"

    with pytest.raises(ValueError, match="only QQQ and SPY"):
        snapshot_from_payload(payload)


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("open", "0", "open must be positive"),
        ("close", "-1", "close must be positive"),
        ("high", "99", "high must be at least"),
        ("low", "101", "low must be at most"),
    ],
)
def test_invalid_ohlc_rejected(
    field_name: str,
    value: str,
    message: str,
) -> None:
    payload = load_payload()
    qqq_bar = next(bar for bar in payload["bars"] if bar["symbol"] == "QQQ")
    qqq_bar[field_name] = value

    with pytest.raises(ValueError, match=message):
        snapshot_from_payload(payload)


def test_negative_volume_rejected() -> None:
    payload = load_payload()
    payload["bars"][0]["volume"] = -1

    with pytest.raises(ValueError, match="volume must be nonnegative"):
        snapshot_from_payload(payload)


def test_inclusive_range_filtering() -> None:
    snapshot, _fixture_hash = load_daily_bar_snapshot(FIXTURE_PATH)

    aligned = align_daily_bars(
        snapshot=snapshot,
        config=resolved_config(start_date=date(2026, 1, 30), end_date=date(2026, 2, 4)),
    )

    assert aligned.trading_dates == (
        date(2026, 1, 30),
        date(2026, 1, 31),
        date(2026, 2, 3),
        date(2026, 2, 4),
    )


def test_snapshot_identity_mismatch_rejected() -> None:
    snapshot, _fixture_hash = load_daily_bar_snapshot(FIXTURE_PATH)

    with pytest.raises(ValueError, match="snapshot identity"):
        align_daily_bars(
            snapshot=snapshot,
            config=resolved_config(data_snapshot_id="different-snapshot"),
        )


def test_no_silent_session_dropping() -> None:
    snapshot, _fixture_hash = load_daily_bar_snapshot(FIXTURE_PATH)
    config = resolved_config(start_date=date(2026, 1, 29), end_date=date(2026, 2, 5))

    aligned = align_daily_bars(snapshot=snapshot, config=config)

    assert len(aligned.qqq_bars) == 6
    assert len(aligned.spy_bars) == 6
    assert aligned.trading_dates == tuple(bar.trading_date for bar in aligned.spy_bars)


def load_payload() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def resolved_config(
    *,
    start_date: date = date(2026, 1, 29),
    end_date: date = date(2026, 2, 5),
    data_snapshot_id: str = "synthetic-etf-snapshot-20260206",
) -> ResolvedBacktestConfig:
    return ResolvedBacktestConfig(
        experiment_id="exp-fixture-qqq-buy-hold",
        strategy_id="strategies/etfs/qqq_buy_and_hold",
        strategy_version="0.1.0",
        engine_version=ENGINE_VERSION,
        asset_symbol="QQQ",
        benchmark_symbol="SPY",
        start_date=start_date,
        end_date=end_date,
        frequency="daily",
        initial_capital=Decimal("100000"),
        commission=BasisPointAssumption(
            bps=Decimal("1"),
            description="1 basis point commission on executed notional",
        ),
        slippage=BasisPointAssumption(
            bps=Decimal("2"),
            description="2 basis points buy slippage",
        ),
        execution_price_field="open",
        valuation_price_field="close",
        share_policy="integer",
        data_snapshot_id=data_snapshot_id,
        benchmark_snapshot_id="synthetic-spy-benchmark-snapshot-20260206",
        random_seed=None,
        no_randomness_reason="deterministic no-randomness baseline",
        logical_execution_at=datetime(2026, 2, 6, tzinfo=UTC),
    )
