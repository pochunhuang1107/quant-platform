"""Deterministic artifacts for completed snapshot-v2 economic backtests."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from backtest_engine.economic_execution_models import (
    ECONOMIC_ARTIFACT_VALIDATOR_VERSION,
    CompletedEconomicBacktestResult,
    deterministic_artifact_created_at,
)
from backtest_engine.identity import canonical_json_bytes, file_sha256_bytes
from backtest_engine.models import ArtifactFileMetadata, GeneratedArtifactBundle
from research_sdk.contracts import (
    ArtifactFormat,
    ArtifactKind,
    ArtifactStatus,
    HashAlgorithm,
    RunArtifactEntry,
    RunArtifactManifest,
)
from research_sdk.contracts.schema import RESEARCH_SDK_CONTRACT_SCHEMA_VERSION

ECONOMIC_CORPORATE_ACTION_AUDIT_FILENAME = "economic_corporate_action_audit.parquet"
_PARQUET_VERSION = "2.6"
_PARQUET_DATA_PAGE_VERSION = "2.0"


def generate_economic_artifact_bundle(
    *,
    result: CompletedEconomicBacktestResult,
    artifact_base_dir: Path,
) -> GeneratedArtifactBundle:
    """Write the required artifacts plus the economic action audit."""

    run_dir = artifact_base_dir / result.run_id
    if run_dir.exists() and any(run_dir.iterdir()):
        raise FileExistsError("refusing to overwrite existing nonempty run directory")
    run_dir.mkdir(parents=True, exist_ok=True)
    payload_artifacts = [
        _write_json(
            result=result,
            run_dir=run_dir,
            artifact_id="config",
            kind=ArtifactKind.CONFIG,
            filename="config.json",
            payload=economic_config_artifact_payload(result),
        ),
        _write_json(
            result=result,
            run_dir=run_dir,
            artifact_id="metrics",
            kind=ArtifactKind.METRICS,
            filename="metrics.json",
            payload=result.metrics,
        ),
        _write_trade_log(result, run_dir),
        _write_signal_log(result, run_dir),
        _write_daily_equity(result, run_dir),
        _write_drawdown(result, run_dir),
        _write_monthly_returns(result, run_dir),
        _write_json(
            result=result,
            run_dir=run_dir,
            artifact_id="regime-breakdown",
            kind=ArtifactKind.REGIME_BREAKDOWN,
            filename="regime_breakdown.json",
            payload={
                "regime_model": "none",
                "buckets": (
                    {
                        "regime": "all_periods",
                        "observation_count": result.metrics.observation_count,
                        "total_return": result.metrics.total_return,
                        "benchmark_total_return": (
                            result.metrics.benchmark_total_return
                        ),
                        "excess_return": result.metrics.excess_return,
                    },
                ),
            },
        ),
        _write_markdown(
            result=result,
            run_dir=run_dir,
            artifact_id="failure-analysis",
            kind=ArtifactKind.FAILURE_ANALYSIS,
            filename="failure_analysis.md",
            content=_failure_analysis_markdown(result),
        ),
        _write_markdown(
            result=result,
            run_dir=run_dir,
            artifact_id="research-note",
            kind=ArtifactKind.RESEARCH_NOTE,
            filename="research_note.md",
            content=_research_note_markdown(),
        ),
        _write_corporate_action_audit(result, run_dir),
    ]

    created_at = deterministic_artifact_created_at(result.market_data_lineage)
    root_uri = run_dir.resolve().as_uri()
    manifest = RunArtifactManifest(
        schema_version=RESEARCH_SDK_CONTRACT_SCHEMA_VERSION,
        run_id=result.run_id,
        experiment_id=result.resolved_config.experiment_id,
        artifact_root_uri=root_uri,
        created_at=created_at,
        required_artifacts_complete=True,
        artifacts=tuple(
            RunArtifactEntry(
                artifact_id=item.artifact_id,
                artifact_kind=ArtifactKind(item.artifact_kind),
                uri=item.uri,
                filename=item.filename,
                format=ArtifactFormat(item.format),
                status=ArtifactStatus.PRODUCED,
                hash_algorithm=HashAlgorithm.SHA256,
                content_hash=item.content_hash,
                size_bytes=item.size_bytes,
                row_count=item.row_count,
                created_at=item.created_at,
                validator_version=item.validator_version,
            )
            for item in payload_artifacts
        ),
    )
    manifest_path = run_dir / "artifact_manifest.json"
    manifest_bytes = canonical_json_bytes(manifest)
    manifest_path.write_bytes(manifest_bytes)
    return GeneratedArtifactBundle(
        artifact_root_path=str(run_dir.resolve()),
        artifact_root_uri=root_uri,
        artifact_manifest_path=str(manifest_path.resolve()),
        artifact_manifest_uri=manifest_path.resolve().as_uri(),
        artifact_manifest_hash=f"sha256:{file_sha256_bytes(manifest_bytes)}",
        manifest_id=f"manifest-{result.full_execution_identity_digest}",
        payload_artifacts=tuple(payload_artifacts),
        run_artifact_manifest=manifest,
        write_order=tuple(item.filename for item in payload_artifacts)
        + ("artifact_manifest.json",),
    )


def economic_config_artifact_payload(
    result: CompletedEconomicBacktestResult,
) -> dict[str, Any]:
    """Return the exact semantic config payload used by writer and verifier."""

    return {
        "run_id": result.run_id,
        "full_execution_identity_digest": result.full_execution_identity_digest,
        "execution_identity_version": result.execution_identity_version,
        "resolved_economic_config": result.resolved_config,
        "market_data_execution_lineage": result.market_data_lineage,
        "execution_environment_lineage": result.execution_metadata,
        "execution_assumptions": {
            "strategy": "unconditional QQQ buy-and-hold",
            "strategy_prices": "raw open execution and raw close valuation",
            "strategy_shares": "integer",
            "strategy_costs": "configured commission and slippage",
            "benchmark": "gross SPY buy-and-hold",
            "benchmark_prices": "raw open execution and raw close valuation",
            "benchmark_units": "fractional_decimal_12",
            "benchmark_costs": "zero commission and zero slippage",
            "corporate_actions": "explicit splits and cash distributions",
            "distributions": "receivable then retained cash; no reinvestment",
        },
        "deterministic_limitations": result.deterministic_limitations,
    }


def _write_trade_log(
    result: CompletedEconomicBacktestResult,
    run_dir: Path,
) -> ArtifactFileMetadata:
    rows = result.trade_records
    return _write_parquet(
        result=result,
        run_dir=run_dir,
        artifact_id="trade-log",
        kind=ArtifactKind.TRADE_LOG,
        filename="trade_log.parquet",
        table=pa.Table.from_arrays(
            [
                _date_array([row.execution_session for row in rows]),
                pa.array([row.symbol for row in rows], pa.string()),
                pa.array([row.side for row in rows], pa.string()),
                pa.array([row.quantity for row in rows], pa.int64()),
                _money_array([row.raw_open for row in rows]),
                _money_array([row.fill_price for row in rows]),
                _money_array([row.executed_notional for row in rows]),
                _money_array([row.commission for row in rows]),
                _money_array([row.slippage for row in rows]),
                _money_array([row.total_cash_spent for row in rows]),
                pa.array([row.decision_authority for row in rows], pa.string()),
                pa.array([row.timing_policy_version for row in rows], pa.string()),
            ],
            names=(
                "execution_session",
                "symbol",
                "side",
                "quantity",
                "raw_open",
                "fill_price",
                "executed_notional",
                "commission",
                "slippage",
                "total_cash_spent",
                "decision_authority",
                "timing_policy_version",
            ),
        ),
        row_count=len(rows),
    )


def _write_signal_log(
    result: CompletedEconomicBacktestResult,
    run_dir: Path,
) -> ArtifactFileMetadata:
    rows = result.signal_records
    return _write_parquet(
        result=result,
        run_dir=run_dir,
        artifact_id="signal-log",
        kind=ArtifactKind.SIGNAL_LOG,
        filename="signal_log.parquet",
        table=pa.Table.from_arrays(
            [
                pa.array([row.decision_authority for row in rows], pa.string()),
                _date_array([row.execution_session for row in rows]),
                pa.array([row.symbol for row in rows], pa.string()),
                pa.array([row.signal_name for row in rows], pa.string()),
                pa.array([row.order_type_assumption for row in rows], pa.string()),
                pa.array([row.execution_price_policy for row in rows], pa.string()),
                _date_array(
                    [row.latest_observable_complete_bar_session for row in rows]
                ),
                pa.array(
                    [
                        tuple(
                            item.isoformat()
                            for item in row.observable_complete_bar_sessions
                        )
                        for row in rows
                    ],
                    pa.list_(pa.string()),
                ),
                pa.array([row.timing_policy_version for row in rows], pa.string()),
                pa.array([row.lookback_authority for row in rows], pa.string()),
                pa.array([row.lag_authority for row in rows], pa.string()),
            ],
            names=(
                "decision_authority",
                "execution_session",
                "symbol",
                "signal_name",
                "order_type_assumption",
                "execution_price_policy",
                "latest_observable_complete_bar_session",
                "observable_complete_bar_sessions",
                "timing_policy_version",
                "lookback_authority",
                "lag_authority",
            ),
        ),
        row_count=len(rows),
    )


def _write_daily_equity(
    result: CompletedEconomicBacktestResult,
    run_dir: Path,
) -> ArtifactFileMetadata:
    rows = result.daily_records
    return _write_parquet(
        result=result,
        run_dir=run_dir,
        artifact_id="daily-equity",
        kind=ArtifactKind.DAILY_EQUITY,
        filename="daily_equity.parquet",
        table=pa.Table.from_arrays(
            [
                _date_array([row.session for row in rows]),
                _money_array([row.strategy_cash for row in rows]),
                pa.array([row.strategy_quantity for row in rows], pa.int64()),
                _money_array([row.strategy_raw_close for row in rows]),
                _money_array([row.strategy_market_value for row in rows]),
                _money_array(
                    [row.strategy_outstanding_receivable_value for row in rows]
                ),
                _money_array([row.strategy_total_book_cost for row in rows]),
                _money_array([row.strategy_total_economic_equity for row in rows]),
                _money_array([row.benchmark_cash for row in rows]),
                _unit_array([row.benchmark_fractional_units for row in rows]),
                _money_array([row.benchmark_raw_close for row in rows]),
                _money_array([row.benchmark_market_value for row in rows]),
                _money_array(
                    [row.benchmark_outstanding_receivable_value for row in rows]
                ),
                _money_array([row.benchmark_total_economic_equity for row in rows]),
                _money_array([row.cumulative_strategy_commission for row in rows]),
                _money_array([row.cumulative_strategy_slippage for row in rows]),
            ],
            names=(
                "session",
                "strategy_cash",
                "strategy_quantity",
                "strategy_raw_close",
                "strategy_market_value",
                "strategy_outstanding_receivable_value",
                "strategy_total_book_cost",
                "strategy_total_economic_equity",
                "benchmark_cash",
                "benchmark_fractional_units",
                "benchmark_raw_close",
                "benchmark_market_value",
                "benchmark_outstanding_receivable_value",
                "benchmark_total_economic_equity",
                "cumulative_strategy_commission",
                "cumulative_strategy_slippage",
            ),
        ),
        row_count=len(rows),
    )


def _write_drawdown(
    result: CompletedEconomicBacktestResult,
    run_dir: Path,
) -> ArtifactFileMetadata:
    rows = result.drawdown_series
    return _write_parquet(
        result=result,
        run_dir=run_dir,
        artifact_id="drawdown-series",
        kind=ArtifactKind.DRAWDOWN_SERIES,
        filename="drawdown_series.parquet",
        table=pa.Table.from_arrays(
            [
                _date_array([row.trading_date for row in rows]),
                _money_array([row.running_peak for row in rows]),
                _ratio_array([row.drawdown for row in rows]),
            ],
            names=("trading_date", "running_peak", "drawdown"),
        ),
        row_count=len(rows),
    )


def _write_monthly_returns(
    result: CompletedEconomicBacktestResult,
    run_dir: Path,
) -> ArtifactFileMetadata:
    rows = result.monthly_returns
    return _write_parquet(
        result=result,
        run_dir=run_dir,
        artifact_id="monthly-returns",
        kind=ArtifactKind.MONTHLY_RETURNS,
        filename="monthly_returns.parquet",
        table=pa.Table.from_arrays(
            [
                pa.array([row.month for row in rows], pa.string()),
                _money_array([row.start_equity for row in rows]),
                _money_array([row.end_equity for row in rows]),
                _ratio_array([row.return_value for row in rows]),
            ],
            names=("month", "start_equity", "end_equity", "return_value"),
        ),
        row_count=len(rows),
    )


def _write_corporate_action_audit(
    result: CompletedEconomicBacktestResult,
    run_dir: Path,
) -> ArtifactFileMetadata:
    rows = result.corporate_action_audit
    return _write_parquet(
        result=result,
        run_dir=run_dir,
        artifact_id="economic-corporate-action-audit",
        kind=ArtifactKind.DIAGNOSTIC,
        filename=ECONOMIC_CORPORATE_ACTION_AUDIT_FILENAME,
        table=pa.Table.from_arrays(
            [
                pa.array([row.portfolio_role for row in rows], pa.string()),
                _date_array([row.session for row in rows]),
                pa.array([row.event_id for row in rows], pa.string()),
                pa.array([row.instrument_id for row in rows], pa.string()),
                pa.array([row.event_type for row in rows], pa.string()),
                pa.array([row.accounting_action for row in rows], pa.string()),
                pa.array([row.position_unit_policy for row in rows], pa.string()),
                _unit_array([row.pre_position for row in rows]),
                _unit_array([row.post_position for row in rows]),
                _unit_array([row.entitlement_position for row in rows]),
                _money_array([row.receivable_delta for row in rows]),
                _money_array([row.cash_delta for row in rows]),
            ],
            names=(
                "portfolio_role",
                "session",
                "event_id",
                "instrument_id",
                "event_type",
                "accounting_action",
                "position_unit_policy",
                "pre_position",
                "post_position",
                "entitlement_position",
                "receivable_delta",
                "cash_delta",
            ),
        ),
        row_count=len(rows),
    )


def _write_json(
    *,
    result: CompletedEconomicBacktestResult,
    run_dir: Path,
    artifact_id: str,
    kind: ArtifactKind,
    filename: str,
    payload: Any,
) -> ArtifactFileMetadata:
    path = run_dir / filename
    path.write_bytes(canonical_json_bytes(payload))
    return _metadata(result, artifact_id, kind, ArtifactFormat.JSON, path, None)


def _write_markdown(
    *,
    result: CompletedEconomicBacktestResult,
    run_dir: Path,
    artifact_id: str,
    kind: ArtifactKind,
    filename: str,
    content: str,
) -> ArtifactFileMetadata:
    path = run_dir / filename
    path.write_bytes(content.encode("utf-8"))
    return _metadata(result, artifact_id, kind, ArtifactFormat.MARKDOWN, path, None)


def _write_parquet(
    *,
    result: CompletedEconomicBacktestResult,
    run_dir: Path,
    artifact_id: str,
    kind: ArtifactKind,
    filename: str,
    table: pa.Table,
    row_count: int,
) -> ArtifactFileMetadata:
    path = run_dir / filename
    pq.write_table(
        table.replace_schema_metadata(None),
        path,
        compression="NONE",
        use_dictionary=False,
        write_statistics=False,
        row_group_size=max(row_count, 1),
        version=_PARQUET_VERSION,
        data_page_version=_PARQUET_DATA_PAGE_VERSION,
        store_schema=False,
    )
    return _metadata(
        result,
        artifact_id,
        kind,
        ArtifactFormat.PARQUET,
        path,
        row_count,
    )


def _metadata(
    result: CompletedEconomicBacktestResult,
    artifact_id: str,
    kind: ArtifactKind,
    artifact_format: ArtifactFormat,
    path: Path,
    row_count: int | None,
) -> ArtifactFileMetadata:
    content = path.read_bytes()
    return ArtifactFileMetadata(
        artifact_id=artifact_id,
        artifact_kind=kind.value,
        filename=path.name,
        format=artifact_format.value,
        path=str(path.resolve()),
        uri=path.resolve().as_uri(),
        content_hash=f"sha256:{file_sha256_bytes(content)}",
        size_bytes=len(content),
        row_count=row_count,
        created_at=deterministic_artifact_created_at(result.market_data_lineage),
        validator_version=ECONOMIC_ARTIFACT_VALIDATOR_VERSION,
    )


def _failure_analysis_markdown(result: CompletedEconomicBacktestResult) -> str:
    lines = [
        "# Failure Analysis",
        "",
        "Execution completed without a runtime failure.",
        "",
        "Known limitations:",
    ]
    lines.extend(f"- {item}" for item in result.deterministic_limitations)
    lines.extend(
        [
            "- No provider, broker, paper-trading, or live-trading behavior is "
            "included.",
            "",
        ]
    )
    return "\n".join(lines)


def _research_note_markdown() -> str:
    return "\n".join(
        [
            "# Snapshot-v2 QQQ/SPY Economic Infrastructure Validation",
            "",
            "Objective: validate deterministic economic execution infrastructure.",
            "",
            "- QQQ uses raw prices, integer shares, and configured costs.",
            "- SPY uses raw prices, fractional units, and zero costs.",
            "- Splits and cash distributions are accounted for explicitly.",
            "- Distribution cash is retained and never automatically reinvested.",
            "- The first allocation is unconditional and decided before the run.",
            "- Complete bar T is unavailable to a decision executing on T.",
            "- LATEST_KNOWN evidence is not point-in-time strategy knowledge.",
            "",
            "Expected behavior:",
            "- First-session allocations execute only after zero-position action "
            "accounting.",
            "- Economic equity includes explicit receivables and retained cash.",
            "- Splits preserve value and settlement does not create return.",
            "",
            "Failure modes:",
            "- Exact-byte, profile, role, or session validation failure stops the run.",
            "- Unsupported or ambiguous corporate actions fail closed.",
            "- A split requiring fractional QQQ shares fails closed.",
            "",
            "Validation plan:",
            "- Synthetic snapshot-v2 fixtures exercise timing, actions, identity, "
            "artifacts, and pair recording.",
            "- Accepted-data validation remains a separate offline human-reviewed "
            "step after merge.",
            "",
            "No performance claim: this result is research infrastructure output and "
            "is not an investment recommendation.",
            "",
        ]
    )


def _date_array(values: Sequence[date | None]) -> pa.Array:
    return pa.array(values, pa.date32())


def _money_array(values: Sequence[Decimal]) -> pa.Array:
    return pa.array(values, pa.decimal128(38, 6))


def _ratio_array(values: Sequence[Decimal]) -> pa.Array:
    return pa.array(values, pa.decimal128(38, 12))


def _unit_array(values: Sequence[Decimal]) -> pa.Array:
    return pa.array(values, pa.decimal128(38, 12))


__all__ = [
    "ECONOMIC_CORPORATE_ACTION_AUDIT_FILENAME",
    "economic_config_artifact_payload",
    "generate_economic_artifact_bundle",
]
