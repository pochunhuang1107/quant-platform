"""Deterministic artifacts for completed snapshot-v2 economic backtests."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
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
from backtest_engine.economic_result_validation import (
    canonicalize_completed_economic_backtest_result,
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


@dataclass(frozen=True)
class EconomicArtifactSemanticPayload:
    """One artifact's exact result-derived semantic bytes and metadata."""

    artifact_id: str
    artifact_kind: ArtifactKind
    filename: str
    artifact_format: ArtifactFormat
    content: bytes
    row_count: int | None


def generate_economic_artifact_bundle(
    *,
    result: CompletedEconomicBacktestResult,
    artifact_base_dir: Path,
) -> GeneratedArtifactBundle:
    """Canonically validate the result and write its exact semantic artifacts."""

    canonical_result = canonicalize_completed_economic_backtest_result(result)
    semantic_payloads = _build_economic_artifact_semantic_payloads(canonical_result)
    run_dir = artifact_base_dir / canonical_result.run_id
    if run_dir.exists() and any(run_dir.iterdir()):
        raise FileExistsError("refusing to overwrite existing nonempty run directory")
    run_dir.mkdir(parents=True, exist_ok=True)
    payload_artifacts = tuple(
        _write_semantic_payload(
            result=canonical_result,
            run_dir=run_dir,
            payload=payload,
        )
        for payload in semantic_payloads
    )

    created_at = deterministic_artifact_created_at(canonical_result.market_data_lineage)
    root_uri = run_dir.resolve().as_uri()
    manifest = RunArtifactManifest(
        schema_version=RESEARCH_SDK_CONTRACT_SCHEMA_VERSION,
        run_id=canonical_result.run_id,
        experiment_id=canonical_result.resolved_config.experiment_id,
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
        manifest_id=f"manifest-{canonical_result.full_execution_identity_digest}",
        payload_artifacts=payload_artifacts,
        run_artifact_manifest=manifest,
        write_order=tuple(item.filename for item in payload_artifacts)
        + ("artifact_manifest.json",),
    )


def build_economic_artifact_semantic_payloads(
    result: CompletedEconomicBacktestResult,
) -> tuple[EconomicArtifactSemanticPayload, ...]:
    """Return the canonical semantic bytes used by both writer and verifier."""

    canonical_result = canonicalize_completed_economic_backtest_result(result)
    return _build_economic_artifact_semantic_payloads(canonical_result)


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


def _build_economic_artifact_semantic_payloads(
    result: CompletedEconomicBacktestResult,
) -> tuple[EconomicArtifactSemanticPayload, ...]:
    return (
        _json_semantic_payload(
            artifact_id="config",
            kind=ArtifactKind.CONFIG,
            filename="config.json",
            payload=economic_config_artifact_payload(result),
        ),
        _json_semantic_payload(
            artifact_id="metrics",
            kind=ArtifactKind.METRICS,
            filename="metrics.json",
            payload=result.metrics,
        ),
        _parquet_semantic_payload(
            artifact_id="trade-log",
            kind=ArtifactKind.TRADE_LOG,
            filename="trade_log.parquet",
            table=_trade_log_table(result),
        ),
        _parquet_semantic_payload(
            artifact_id="signal-log",
            kind=ArtifactKind.SIGNAL_LOG,
            filename="signal_log.parquet",
            table=_signal_log_table(result),
        ),
        _parquet_semantic_payload(
            artifact_id="daily-equity",
            kind=ArtifactKind.DAILY_EQUITY,
            filename="daily_equity.parquet",
            table=_daily_equity_table(result),
        ),
        _parquet_semantic_payload(
            artifact_id="drawdown-series",
            kind=ArtifactKind.DRAWDOWN_SERIES,
            filename="drawdown_series.parquet",
            table=_drawdown_table(result),
        ),
        _parquet_semantic_payload(
            artifact_id="monthly-returns",
            kind=ArtifactKind.MONTHLY_RETURNS,
            filename="monthly_returns.parquet",
            table=_monthly_returns_table(result),
        ),
        _json_semantic_payload(
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
        _markdown_semantic_payload(
            artifact_id="failure-analysis",
            kind=ArtifactKind.FAILURE_ANALYSIS,
            filename="failure_analysis.md",
            content=_failure_analysis_markdown(result),
        ),
        _markdown_semantic_payload(
            artifact_id="research-note",
            kind=ArtifactKind.RESEARCH_NOTE,
            filename="research_note.md",
            content=_research_note_markdown(),
        ),
        _parquet_semantic_payload(
            artifact_id="economic-corporate-action-audit",
            kind=ArtifactKind.DIAGNOSTIC,
            filename=ECONOMIC_CORPORATE_ACTION_AUDIT_FILENAME,
            table=_corporate_action_audit_table(result),
        ),
    )


def _trade_log_table(result: CompletedEconomicBacktestResult) -> pa.Table:
    rows = result.trade_records
    return pa.Table.from_arrays(
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
    )


def _signal_log_table(result: CompletedEconomicBacktestResult) -> pa.Table:
    rows = result.signal_records
    return pa.Table.from_arrays(
        [
            pa.array([row.decision_authority for row in rows], pa.string()),
            _date_array([row.execution_session for row in rows]),
            pa.array([row.symbol for row in rows], pa.string()),
            pa.array([row.signal_name for row in rows], pa.string()),
            pa.array([row.order_type_assumption for row in rows], pa.string()),
            pa.array([row.execution_price_policy for row in rows], pa.string()),
            _date_array([row.latest_observable_complete_bar_session for row in rows]),
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
    )


def _daily_equity_table(result: CompletedEconomicBacktestResult) -> pa.Table:
    rows = result.daily_records
    return pa.Table.from_arrays(
        [
            _date_array([row.session for row in rows]),
            _money_array([row.strategy_cash for row in rows]),
            pa.array([row.strategy_quantity for row in rows], pa.int64()),
            _money_array([row.strategy_raw_close for row in rows]),
            _money_array([row.strategy_market_value for row in rows]),
            _money_array([row.strategy_outstanding_receivable_value for row in rows]),
            _money_array([row.strategy_total_book_cost for row in rows]),
            _money_array([row.strategy_total_economic_equity for row in rows]),
            _money_array([row.benchmark_cash for row in rows]),
            _unit_array([row.benchmark_fractional_units for row in rows]),
            _money_array([row.benchmark_raw_close for row in rows]),
            _money_array([row.benchmark_market_value for row in rows]),
            _money_array([row.benchmark_outstanding_receivable_value for row in rows]),
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
    )


def _drawdown_table(result: CompletedEconomicBacktestResult) -> pa.Table:
    rows = result.drawdown_series
    return pa.Table.from_arrays(
        [
            _date_array([row.trading_date for row in rows]),
            _money_array([row.running_peak for row in rows]),
            _ratio_array([row.drawdown for row in rows]),
        ],
        names=("trading_date", "running_peak", "drawdown"),
    )


def _monthly_returns_table(result: CompletedEconomicBacktestResult) -> pa.Table:
    rows = result.monthly_returns
    return pa.Table.from_arrays(
        [
            pa.array([row.month for row in rows], pa.string()),
            _money_array([row.start_equity for row in rows]),
            _money_array([row.end_equity for row in rows]),
            _ratio_array([row.return_value for row in rows]),
        ],
        names=("month", "start_equity", "end_equity", "return_value"),
    )


def _corporate_action_audit_table(
    result: CompletedEconomicBacktestResult,
) -> pa.Table:
    rows = result.corporate_action_audit
    return pa.Table.from_arrays(
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
    )


def _json_semantic_payload(
    *,
    artifact_id: str,
    kind: ArtifactKind,
    filename: str,
    payload: Any,
) -> EconomicArtifactSemanticPayload:
    return EconomicArtifactSemanticPayload(
        artifact_id=artifact_id,
        artifact_kind=kind,
        filename=filename,
        artifact_format=ArtifactFormat.JSON,
        content=canonical_json_bytes(payload),
        row_count=None,
    )


def _markdown_semantic_payload(
    *,
    artifact_id: str,
    kind: ArtifactKind,
    filename: str,
    content: str,
) -> EconomicArtifactSemanticPayload:
    return EconomicArtifactSemanticPayload(
        artifact_id=artifact_id,
        artifact_kind=kind,
        filename=filename,
        artifact_format=ArtifactFormat.MARKDOWN,
        content=content.encode("utf-8"),
        row_count=None,
    )


def _parquet_semantic_payload(
    *,
    artifact_id: str,
    kind: ArtifactKind,
    filename: str,
    table: pa.Table,
) -> EconomicArtifactSemanticPayload:
    return EconomicArtifactSemanticPayload(
        artifact_id=artifact_id,
        artifact_kind=kind,
        filename=filename,
        artifact_format=ArtifactFormat.PARQUET,
        content=_serialize_parquet_table(table),
        row_count=table.num_rows,
    )


def _serialize_parquet_table(table: pa.Table) -> bytes:
    sink = pa.BufferOutputStream()
    pq.write_table(
        table.replace_schema_metadata(None),
        sink,
        compression="NONE",
        use_dictionary=False,
        write_statistics=False,
        row_group_size=max(table.num_rows, 1),
        version=_PARQUET_VERSION,
        data_page_version=_PARQUET_DATA_PAGE_VERSION,
        store_schema=False,
    )
    return bytes(sink.getvalue())


def _write_semantic_payload(
    *,
    result: CompletedEconomicBacktestResult,
    run_dir: Path,
    payload: EconomicArtifactSemanticPayload,
) -> ArtifactFileMetadata:
    path = run_dir / payload.filename
    path.write_bytes(payload.content)
    return ArtifactFileMetadata(
        artifact_id=payload.artifact_id,
        artifact_kind=payload.artifact_kind.value,
        filename=payload.filename,
        format=payload.artifact_format.value,
        path=str(path.resolve()),
        uri=path.resolve().as_uri(),
        content_hash=f"sha256:{file_sha256_bytes(payload.content)}",
        size_bytes=len(payload.content),
        row_count=payload.row_count,
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
    "EconomicArtifactSemanticPayload",
    "build_economic_artifact_semantic_payloads",
    "economic_config_artifact_payload",
    "generate_economic_artifact_bundle",
]
