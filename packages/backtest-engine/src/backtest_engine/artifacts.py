"""Deterministic local artifact generation for completed backtest results."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from backtest_engine.identity import canonical_json_bytes, file_sha256_bytes
from backtest_engine.models import (
    ARTIFACT_VALIDATOR_VERSION,
    ArtifactFileMetadata,
    CompletedBacktestResult,
    GeneratedArtifactBundle,
)
from research_sdk.contracts import (
    ArtifactFormat,
    ArtifactKind,
    ArtifactStatus,
    HashAlgorithm,
    RunArtifactEntry,
    RunArtifactManifest,
)
from research_sdk.contracts.schema import RESEARCH_SDK_CONTRACT_SCHEMA_VERSION

_PARQUET_VERSION = "2.6"
_PARQUET_DATA_PAGE_VERSION = "2.0"


def generate_artifact_bundle(
    *,
    result: CompletedBacktestResult,
    artifact_base_dir: Path,
) -> GeneratedArtifactBundle:
    """Write deterministic local artifacts and return their manifest metadata."""

    run_dir = artifact_base_dir / result.run_id
    if run_dir.exists() and any(run_dir.iterdir()):
        raise FileExistsError("refusing to overwrite existing nonempty run directory")
    run_dir.mkdir(parents=True, exist_ok=True)

    payload_artifacts = [
        _write_config(result, run_dir),
        _write_metrics(result, run_dir),
        _write_trade_log(result, run_dir),
        _write_signal_log(result, run_dir),
        _write_daily_equity(result, run_dir),
        _write_drawdown_series(result, run_dir),
        _write_monthly_returns(result, run_dir),
        _write_regime_breakdown(result, run_dir),
        _write_failure_analysis(result, run_dir),
        _write_research_note(result, run_dir),
    ]

    artifact_root_uri = run_dir.resolve().as_uri()
    manifest = RunArtifactManifest(
        schema_version=RESEARCH_SDK_CONTRACT_SCHEMA_VERSION,
        run_id=result.run_id,
        experiment_id=result.resolved_config.experiment_id,
        artifact_root_uri=artifact_root_uri,
        created_at=result.resolved_config.logical_execution_at,
        required_artifacts_complete=True,
        artifacts=tuple(
            RunArtifactEntry(
                artifact_id=artifact.artifact_id,
                artifact_kind=ArtifactKind(artifact.artifact_kind),
                uri=artifact.uri,
                filename=artifact.filename,
                format=ArtifactFormat(artifact.format),
                status=ArtifactStatus.PRODUCED,
                hash_algorithm=HashAlgorithm.SHA256,
                content_hash=artifact.content_hash,
                size_bytes=artifact.size_bytes,
                row_count=artifact.row_count,
                created_at=artifact.created_at,
                validator_version=artifact.validator_version,
            )
            for artifact in payload_artifacts
        ),
    )
    manifest_path = run_dir / "artifact_manifest.json"
    manifest_bytes = canonical_json_bytes(manifest)
    _write_manifest_file(manifest_path, manifest_bytes)
    manifest_hash = f"sha256:{file_sha256_bytes(manifest_bytes)}"

    return GeneratedArtifactBundle(
        artifact_root_path=str(run_dir.resolve()),
        artifact_root_uri=artifact_root_uri,
        artifact_manifest_path=str(manifest_path.resolve()),
        artifact_manifest_uri=manifest_path.resolve().as_uri(),
        artifact_manifest_hash=manifest_hash,
        manifest_id=f"manifest-{result.full_execution_identity_digest}",
        payload_artifacts=tuple(payload_artifacts),
        run_artifact_manifest=manifest,
        write_order=tuple(artifact.filename for artifact in payload_artifacts)
        + ("artifact_manifest.json",),
    )


def serialize_artifact_manifest(manifest: RunArtifactManifest) -> bytes:
    """Serialize an artifact manifest using the engine's canonical JSON policy."""

    return canonical_json_bytes(manifest)


def _write_manifest_file(path: Path, content: bytes) -> None:
    path.write_bytes(content)


def _write_config(
    result: CompletedBacktestResult, run_dir: Path
) -> ArtifactFileMetadata:
    payload = {
        "run_id": result.run_id,
        "full_execution_identity_digest": result.full_execution_identity_digest,
        "resolved_config": result.resolved_config,
        "execution_metadata": result.execution_metadata,
        "input_fixture_content_hash": result.fixture_content_hash,
        "execution_assumptions": {
            "strategy": "unconditional QQQ buy-and-hold",
            "execution_price_field": "open",
            "valuation_price_field": "close",
            "share_policy": "integer",
            "benchmark": "gross SPY normalized from first aligned open",
        },
        "leakage_assumptions": result.leakage_assumptions,
    }
    return _write_json_artifact(
        result=result,
        run_dir=run_dir,
        artifact_id="config",
        artifact_kind=ArtifactKind.CONFIG,
        filename="config.json",
        payload=payload,
    )


def _write_metrics(
    result: CompletedBacktestResult,
    run_dir: Path,
) -> ArtifactFileMetadata:
    return _write_json_artifact(
        result=result,
        run_dir=run_dir,
        artifact_id="metrics",
        artifact_kind=ArtifactKind.METRICS,
        filename="metrics.json",
        payload=result.metrics,
    )


def _write_trade_log(
    result: CompletedBacktestResult,
    run_dir: Path,
) -> ArtifactFileMetadata:
    return _write_parquet_artifact(
        result=result,
        run_dir=run_dir,
        artifact_id="trade-log",
        artifact_kind=ArtifactKind.TRADE_LOG,
        filename="trade_log.parquet",
        table=pa.Table.from_arrays(
            [
                _date_array([trade.trading_date for trade in result.trades]),
                pa.array([trade.symbol for trade in result.trades], pa.string()),
                pa.array([trade.side for trade in result.trades], pa.string()),
                pa.array([trade.quantity for trade in result.trades], pa.int64()),
                _money_array([trade.raw_price for trade in result.trades]),
                _money_array([trade.fill_price for trade in result.trades]),
                _money_array([trade.executed_notional for trade in result.trades]),
                _money_array([trade.commission for trade in result.trades]),
                _money_array([trade.slippage for trade in result.trades]),
                _money_array([trade.total_cash_spent for trade in result.trades]),
            ],
            schema=pa.schema(
                [
                    ("trading_date", pa.date32()),
                    ("symbol", pa.string()),
                    ("side", pa.string()),
                    ("quantity", pa.int64()),
                    ("raw_price", pa.decimal128(38, 6)),
                    ("fill_price", pa.decimal128(38, 6)),
                    ("executed_notional", pa.decimal128(38, 6)),
                    ("commission", pa.decimal128(38, 6)),
                    ("slippage", pa.decimal128(38, 6)),
                    ("total_cash_spent", pa.decimal128(38, 6)),
                ]
            ),
        ),
        row_count=len(result.trades),
    )


def _write_signal_log(
    result: CompletedBacktestResult,
    run_dir: Path,
) -> ArtifactFileMetadata:
    return _write_parquet_artifact(
        result=result,
        run_dir=run_dir,
        artifact_id="signal-log",
        artifact_kind=ArtifactKind.SIGNAL_LOG,
        filename="signal_log.parquet",
        table=pa.Table.from_arrays(
            [
                _date_array([signal.trading_date for signal in result.signals]),
                pa.array([signal.symbol for signal in result.signals], pa.string()),
                pa.array(
                    [signal.signal_name for signal in result.signals], pa.string()
                ),
                pa.array(
                    [signal.target_allocation for signal in result.signals],
                    pa.string(),
                ),
                pa.array(
                    [signal.order_type_assumption for signal in result.signals],
                    pa.string(),
                ),
                pa.array(
                    [signal.execution_price_field for signal in result.signals],
                    pa.string(),
                ),
                pa.array(
                    [signal.no_lookahead for signal in result.signals], pa.bool_()
                ),
            ],
            schema=pa.schema(
                [
                    ("trading_date", pa.date32()),
                    ("symbol", pa.string()),
                    ("signal_name", pa.string()),
                    ("target_allocation", pa.string()),
                    ("order_type_assumption", pa.string()),
                    ("execution_price_field", pa.string()),
                    ("no_lookahead", pa.bool_()),
                ]
            ),
        ),
        row_count=len(result.signals),
    )


def _write_daily_equity(
    result: CompletedBacktestResult,
    run_dir: Path,
) -> ArtifactFileMetadata:
    rows = result.daily_equity
    return _write_parquet_artifact(
        result=result,
        run_dir=run_dir,
        artifact_id="daily-equity",
        artifact_kind=ArtifactKind.DAILY_EQUITY,
        filename="daily_equity.parquet",
        table=pa.Table.from_arrays(
            [
                _date_array([row.trading_date for row in rows]),
                _money_array([row.strategy_equity for row in rows]),
                _money_array([row.cash for row in rows]),
                pa.array([row.quantity for row in rows], pa.int64()),
                _money_array([row.qqq_close for row in rows]),
                _money_array([row.benchmark_equity for row in rows]),
                _money_array([row.spy_close for row in rows]),
            ],
            schema=pa.schema(
                [
                    ("trading_date", pa.date32()),
                    ("strategy_equity", pa.decimal128(38, 6)),
                    ("cash", pa.decimal128(38, 6)),
                    ("quantity", pa.int64()),
                    ("qqq_close", pa.decimal128(38, 6)),
                    ("benchmark_equity", pa.decimal128(38, 6)),
                    ("spy_close", pa.decimal128(38, 6)),
                ]
            ),
        ),
        row_count=len(rows),
    )


def _write_drawdown_series(
    result: CompletedBacktestResult,
    run_dir: Path,
) -> ArtifactFileMetadata:
    rows = result.drawdown_series
    return _write_parquet_artifact(
        result=result,
        run_dir=run_dir,
        artifact_id="drawdown-series",
        artifact_kind=ArtifactKind.DRAWDOWN_SERIES,
        filename="drawdown_series.parquet",
        table=pa.Table.from_arrays(
            [
                _date_array([row.trading_date for row in rows]),
                _money_array([row.running_peak for row in rows]),
                _ratio_array([row.drawdown for row in rows]),
            ],
            schema=pa.schema(
                [
                    ("trading_date", pa.date32()),
                    ("running_peak", pa.decimal128(38, 6)),
                    ("drawdown", pa.decimal128(38, 12)),
                ]
            ),
        ),
        row_count=len(rows),
    )


def _write_monthly_returns(
    result: CompletedBacktestResult,
    run_dir: Path,
) -> ArtifactFileMetadata:
    rows = result.monthly_returns
    return _write_parquet_artifact(
        result=result,
        run_dir=run_dir,
        artifact_id="monthly-returns",
        artifact_kind=ArtifactKind.MONTHLY_RETURNS,
        filename="monthly_returns.parquet",
        table=pa.Table.from_arrays(
            [
                pa.array([row.month for row in rows], pa.string()),
                _money_array([row.start_equity for row in rows]),
                _money_array([row.end_equity for row in rows]),
                _ratio_array([row.return_value for row in rows]),
            ],
            schema=pa.schema(
                [
                    ("month", pa.string()),
                    ("start_equity", pa.decimal128(38, 6)),
                    ("end_equity", pa.decimal128(38, 6)),
                    ("return_value", pa.decimal128(38, 12)),
                ]
            ),
        ),
        row_count=len(rows),
    )


def _write_regime_breakdown(
    result: CompletedBacktestResult,
    run_dir: Path,
) -> ArtifactFileMetadata:
    payload = {
        "regime_model": "none",
        "buckets": [
            {
                "regime": "all_periods",
                "observation_count": result.metrics.observation_count,
                "total_return": result.metrics.total_return,
                "benchmark_total_return": result.metrics.benchmark_total_return,
                "excess_return": result.metrics.excess_return,
            }
        ],
    }
    return _write_json_artifact(
        result=result,
        run_dir=run_dir,
        artifact_id="regime-breakdown",
        artifact_kind=ArtifactKind.REGIME_BREAKDOWN,
        filename="regime_breakdown.json",
        payload=payload,
    )


def _write_failure_analysis(
    result: CompletedBacktestResult,
    run_dir: Path,
) -> ArtifactFileMetadata:
    content = "\n".join(
        [
            "# Failure Analysis",
            "",
            "Execution completed without a runtime failure.",
            "",
            "Known limitations:",
            "- Synthetic fixture-only data is not historical market data.",
            "- The baseline excludes corporate actions, dividends, and splits.",
            "- The baseline excludes broker execution, shorting, leverage, and taxes.",
            "- Failed-run ledger persistence remains deferred.",
            "",
            "Excluded failure modes:",
            "- Market-data vendor outage.",
            "- Broker rejection or partial fill.",
            "- Live or paper-trading execution failure.",
            "",
        ]
    )
    return _write_markdown_artifact(
        result=result,
        run_dir=run_dir,
        artifact_id="failure-analysis",
        artifact_kind=ArtifactKind.FAILURE_ANALYSIS,
        filename="failure_analysis.md",
        content=content,
    )


def _write_research_note(
    result: CompletedBacktestResult,
    run_dir: Path,
) -> ArtifactFileMetadata:
    content = "\n".join(
        [
            "# QQQ Buy-And-Hold Infrastructure Validation",
            "",
            "Objective: validate deterministic backtest infrastructure and "
            "artifact generation.",
            "",
            "Scope:",
            "- Synthetic fixture-only QQQ data with SPY as a gross benchmark.",
            "- One unconditional QQQ buy at the first aligned session open.",
            "- Integer shares, retained cash, no end-of-period liquidation.",
            "- Commission is 1 basis point and buy slippage is 2 basis points.",
            "",
            "No-lookahead design:",
            "- The order decision is unconditional.",
            "- Same-day close, future values, indicators, and prior performance "
            "are not used for the buy decision.",
            "",
            "Limitations:",
            "- This is not historical market data.",
            "- This is not a production data source.",
            "- Splits, dividends, taxes, capacity, and broker behavior are excluded.",
            "",
            "No performance claim: results are fixture-only infrastructure outputs "
            "and are not an investment recommendation.",
            "",
        ]
    )
    return _write_markdown_artifact(
        result=result,
        run_dir=run_dir,
        artifact_id="research-note",
        artifact_kind=ArtifactKind.RESEARCH_NOTE,
        filename="research_note.md",
        content=content,
    )


def _write_json_artifact(
    *,
    result: CompletedBacktestResult,
    run_dir: Path,
    artifact_id: str,
    artifact_kind: ArtifactKind,
    filename: str,
    payload: Any,
) -> ArtifactFileMetadata:
    path = run_dir / filename
    path.write_bytes(canonical_json_bytes(payload))
    return _metadata_for_file(
        result=result,
        artifact_id=artifact_id,
        artifact_kind=artifact_kind,
        artifact_format=ArtifactFormat.JSON,
        path=path,
        row_count=None,
    )


def _write_markdown_artifact(
    *,
    result: CompletedBacktestResult,
    run_dir: Path,
    artifact_id: str,
    artifact_kind: ArtifactKind,
    filename: str,
    content: str,
) -> ArtifactFileMetadata:
    path = run_dir / filename
    path.write_bytes(content.encode("utf-8"))
    return _metadata_for_file(
        result=result,
        artifact_id=artifact_id,
        artifact_kind=artifact_kind,
        artifact_format=ArtifactFormat.MARKDOWN,
        path=path,
        row_count=None,
    )


def _write_parquet_artifact(
    *,
    result: CompletedBacktestResult,
    run_dir: Path,
    artifact_id: str,
    artifact_kind: ArtifactKind,
    filename: str,
    table: pa.Table,
    row_count: int,
) -> ArtifactFileMetadata:
    path = run_dir / filename
    table = table.replace_schema_metadata(None)
    pq.write_table(
        table,
        path,
        compression="NONE",
        use_dictionary=False,
        write_statistics=False,
        row_group_size=max(row_count, 1),
        version=_PARQUET_VERSION,
        data_page_version=_PARQUET_DATA_PAGE_VERSION,
        store_schema=False,
    )
    return _metadata_for_file(
        result=result,
        artifact_id=artifact_id,
        artifact_kind=artifact_kind,
        artifact_format=ArtifactFormat.PARQUET,
        path=path,
        row_count=row_count,
    )


def _metadata_for_file(
    *,
    result: CompletedBacktestResult,
    artifact_id: str,
    artifact_kind: ArtifactKind,
    artifact_format: ArtifactFormat,
    path: Path,
    row_count: int | None,
) -> ArtifactFileMetadata:
    content = path.read_bytes()
    return ArtifactFileMetadata(
        artifact_id=artifact_id,
        artifact_kind=artifact_kind.value,
        filename=path.name,
        format=artifact_format.value,
        path=str(path.resolve()),
        uri=path.resolve().as_uri(),
        content_hash=f"sha256:{file_sha256_bytes(content)}",
        size_bytes=len(content),
        row_count=row_count,
        created_at=result.resolved_config.logical_execution_at,
        validator_version=ARTIFACT_VALIDATOR_VERSION,
    )


def _date_array(values: Sequence[date]) -> pa.Array:
    return pa.array(values, pa.date32())


def _money_array(values: Sequence[Decimal]) -> pa.Array:
    return pa.array(values, pa.decimal128(38, 6))


def _ratio_array(values: Sequence[Decimal]) -> pa.Array:
    return pa.array(values, pa.decimal128(38, 12))


__all__ = [
    "generate_artifact_bundle",
    "serialize_artifact_manifest",
]
