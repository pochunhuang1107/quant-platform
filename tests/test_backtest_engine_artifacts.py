from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import backtest_engine.artifacts as artifact_writer
from backtest_engine import (
    ARTIFACT_VALIDATOR_VERSION,
    ENGINE_VERSION,
    ArtifactFileMetadata,
    BasisPointAssumption,
    ExecutionMetadata,
    ResolvedBacktestConfig,
    canonical_json_bytes,
    file_sha256_bytes,
    generate_artifact_bundle,
    load_daily_bar_snapshot,
    run_buy_and_hold_backtest,
    serialize_artifact_manifest,
)
from research_sdk.contracts import ArtifactStatus, HashAlgorithm
from research_sdk.contracts.artifacts import REQUIRED_ARTIFACT_SPECS

FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "backtest_engine"
    / "synthetic_daily_etf_bars.json"
)
REQUIRED_PAYLOAD_FILENAMES = tuple(
    filename for filename, _artifact_format in REQUIRED_ARTIFACT_SPECS.values()
)
EXPECTED_PAYLOAD_SHA256 = {
    "config.json": "e107be70dab41aae9c89135b7312826ba92e7932f222002c70eb772a297098b2",
    "metrics.json": "1b03d8cfb35df133c403d7be8aa2abbd1471bc69ed1467074223ab25967d46ae",
    "trade_log.parquet": (
        "6bfa25f26882b3511f92b830d1937b618912d4e4abbfd899b6ff66b4fd80fc93"
    ),
    "signal_log.parquet": (
        "cb7f05a028dd70fa47a28db67ce8dd733ce197b15a63525eb0bcbaa738236246"
    ),
    "daily_equity.parquet": (
        "19f6d0b24c49d255a3a8f7e8fe8c0effc022ddf015053afa86ee675ce7403557"
    ),
    "drawdown_series.parquet": (
        "326525c12f9dc5dff97cbcf584af4acf90acc7054f964b9d0ca40852a2e01f99"
    ),
    "monthly_returns.parquet": (
        "0427942de221de6e9694689fb88f0a16b74de393520994751052d9f9d6ab5972"
    ),
    "regime_breakdown.json": (
        "6a9672674643e19c3389620a8671a71023959b6e73548cf3eda75830df5e3f68"
    ),
    "failure_analysis.md": (
        "2057f5de4ab6ab8aaef8b9a1fe8a6bc3f30f03c0a60b50d501e0b35a29ebd189"
    ),
    "research_note.md": (
        "092dec148ea73df64506470e69a5a4538d563e1c072c6c4de027aea1d9ccc277"
    ),
}


def test_all_required_payloads_and_manifest_are_created(tmp_path: Path) -> None:
    bundle = generate_artifact_bundle(
        result=completed_result(),
        artifact_base_dir=tmp_path,
    )

    filenames = {path.name for path in Path(bundle.artifact_root_path).iterdir()}

    assert filenames == set(REQUIRED_PAYLOAD_FILENAMES) | {"artifact_manifest.json"}
    assert bundle.write_order == REQUIRED_PAYLOAD_FILENAMES + (
        "artifact_manifest.json",
    )


def test_payload_artifact_sha256_matches_golden_mac_digests(
    tmp_path: Path,
) -> None:
    bundle = generate_artifact_bundle(
        result=completed_result(),
        artifact_base_dir=tmp_path,
    )

    actual_digests = {
        metadata.filename: file_sha256_bytes(Path(metadata.path).read_bytes())
        for metadata in bundle.payload_artifacts
    }

    assert set(actual_digests) == set(REQUIRED_PAYLOAD_FILENAMES)
    assert "artifact_manifest.json" not in actual_digests
    assert actual_digests == EXPECTED_PAYLOAD_SHA256


def test_artifact_manifest_json_created_last(tmp_path: Path) -> None:
    bundle = generate_artifact_bundle(
        result=completed_result(),
        artifact_base_dir=tmp_path,
    )

    manifest_path = Path(bundle.artifact_manifest_path)

    assert bundle.write_order[-1] == "artifact_manifest.json"
    assert manifest_path.read_bytes() == serialize_artifact_manifest(
        bundle.run_artifact_manifest
    )


def test_manifest_write_is_sequenced_after_payload_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = completed_result()
    observed_order: list[str] = []

    def payload_writer(filename: str, artifact_kind: object, artifact_format: object):
        def write_payload(
            result: object,
            run_dir: Path,
        ) -> ArtifactFileMetadata:
            observed_order.append(filename)
            path = run_dir / filename
            return ArtifactFileMetadata(
                artifact_id=filename,
                artifact_kind=artifact_kind.value,
                filename=filename,
                format=artifact_format.value,
                path=str(path.resolve()),
                uri=path.resolve().as_uri(),
                content_hash="sha256:" + ("0" * 64),
                size_bytes=1,
                row_count=None,
                created_at=resolved_config().logical_execution_at,
                validator_version=ARTIFACT_VALIDATOR_VERSION,
            )

        return write_payload

    for artifact_kind, (filename, artifact_format) in REQUIRED_ARTIFACT_SPECS.items():
        monkeypatch.setattr(
            artifact_writer,
            writer_name_for_filename(filename),
            payload_writer(filename, artifact_kind, artifact_format),
        )

    def write_manifest_file(path: Path, content: bytes) -> None:
        assert path.name == "artifact_manifest.json"
        assert content
        observed_order.append(path.name)

    monkeypatch.setattr(artifact_writer, "_write_manifest_file", write_manifest_file)

    bundle = generate_artifact_bundle(result=result, artifact_base_dir=tmp_path)

    assert tuple(observed_order) == REQUIRED_PAYLOAD_FILENAMES + (
        "artifact_manifest.json",
    )
    assert bundle.write_order == tuple(observed_order)


def test_payload_write_failure_does_not_write_completed_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = completed_result()

    def fail_monthly_returns(
        result: object,
        run_dir: Path,
    ) -> ArtifactFileMetadata:
        raise RuntimeError("monthly write failed")

    def fail_if_manifest_is_written(path: Path, content: bytes) -> None:
        pytest.fail("artifact_manifest.json must not be written after payload failure")

    monkeypatch.setattr(artifact_writer, "_write_monthly_returns", fail_monthly_returns)
    monkeypatch.setattr(
        artifact_writer, "_write_manifest_file", fail_if_manifest_is_written
    )

    with pytest.raises(RuntimeError, match="monthly write failed"):
        generate_artifact_bundle(result=result, artifact_base_dir=tmp_path)

    assert not (tmp_path / result.run_id / "artifact_manifest.json").exists()


def test_parquet_artifacts_are_valid_with_explicit_schemas(tmp_path: Path) -> None:
    bundle = generate_artifact_bundle(
        result=completed_result(),
        artifact_base_dir=tmp_path,
    )

    assert read_schema(bundle, "trade_log.parquet") == pa.schema(
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
    )
    assert read_schema(bundle, "signal_log.parquet") == pa.schema(
        [
            ("trading_date", pa.date32()),
            ("symbol", pa.string()),
            ("signal_name", pa.string()),
            ("target_allocation", pa.string()),
            ("order_type_assumption", pa.string()),
            ("execution_price_field", pa.string()),
            ("no_lookahead", pa.bool_()),
        ]
    )
    assert read_schema(bundle, "daily_equity.parquet") == pa.schema(
        [
            ("trading_date", pa.date32()),
            ("strategy_equity", pa.decimal128(38, 6)),
            ("cash", pa.decimal128(38, 6)),
            ("quantity", pa.int64()),
            ("qqq_close", pa.decimal128(38, 6)),
            ("benchmark_equity", pa.decimal128(38, 6)),
            ("spy_close", pa.decimal128(38, 6)),
        ]
    )
    assert read_schema(bundle, "drawdown_series.parquet") == pa.schema(
        [
            ("trading_date", pa.date32()),
            ("running_peak", pa.decimal128(38, 6)),
            ("drawdown", pa.decimal128(38, 12)),
        ]
    )
    assert read_schema(bundle, "monthly_returns.parquet") == pa.schema(
        [
            ("month", pa.string()),
            ("start_equity", pa.decimal128(38, 6)),
            ("end_equity", pa.decimal128(38, 6)),
            ("return_value", pa.decimal128(38, 12)),
        ]
    )


def test_parquet_artifact_values_are_stable(tmp_path: Path) -> None:
    bundle = generate_artifact_bundle(
        result=completed_result(),
        artifact_base_dir=tmp_path,
    )

    trade_rows = read_table(bundle, "trade_log.parquet").to_pylist()
    equity_rows = read_table(bundle, "daily_equity.parquet").to_pylist()
    monthly_rows = read_table(bundle, "monthly_returns.parquet").to_pylist()

    assert trade_rows == [
        {
            "trading_date": date(2026, 1, 29),
            "symbol": "QQQ",
            "side": "buy",
            "quantity": 999,
            "raw_price": Decimal("100.000000"),
            "fill_price": Decimal("100.020000"),
            "executed_notional": Decimal("99919.980000"),
            "commission": Decimal("9.991998"),
            "slippage": Decimal("19.980000"),
            "total_cash_spent": Decimal("99929.971998"),
        }
    ]
    assert equity_rows[-1]["strategy_equity"] == Decimal("104965.028002")
    assert equity_rows[-1]["benchmark_equity"] == Decimal("102500.000000")
    assert monthly_rows == [
        {
            "month": "2026-01",
            "start_equity": Decimal("100000.000000"),
            "end_equity": Decimal("103966.028002"),
            "return_value": Decimal("0.039660280020"),
        },
        {
            "month": "2026-02",
            "start_equity": Decimal("103966.028002"),
            "end_equity": Decimal("104965.028002"),
            "return_value": Decimal("0.009608908017"),
        },
    ]


def test_canonical_json_and_markdown_bytes(tmp_path: Path) -> None:
    bundle = generate_artifact_bundle(
        result=completed_result(),
        artifact_base_dir=tmp_path,
    )
    root = Path(bundle.artifact_root_path)

    for filename in ("config.json", "metrics.json", "regime_breakdown.json"):
        content = (root / filename).read_bytes()
        assert content.endswith(b"\n")
        assert content == canonical_json_bytes(json.loads(content.decode("utf-8")))

    for filename in ("failure_analysis.md", "research_note.md"):
        content = (root / filename).read_text(encoding="utf-8")
        assert content.endswith("\n")
        assert "\r\n" not in content


def test_hashes_sizes_uris_and_logical_metadata(tmp_path: Path) -> None:
    result = completed_result()
    bundle = generate_artifact_bundle(
        result=result,
        artifact_base_dir=tmp_path,
    )

    for metadata in bundle.payload_artifacts:
        path = Path(metadata.path)
        content = path.read_bytes()
        assert metadata.uri == path.resolve().as_uri()
        assert metadata.content_hash == f"sha256:{file_sha256_bytes(content)}"
        assert metadata.size_bytes == len(content)
        assert metadata.created_at == result.resolved_config.logical_execution_at
        assert metadata.validator_version

    manifest_content = Path(bundle.artifact_manifest_path).read_bytes()
    assert bundle.artifact_manifest_hash == (
        f"sha256:{file_sha256_bytes(manifest_content)}"
    )


def test_complete_produced_artifact_manifest(tmp_path: Path) -> None:
    result = completed_result()
    bundle = generate_artifact_bundle(
        result=result,
        artifact_base_dir=tmp_path,
    )
    manifest = bundle.run_artifact_manifest

    assert manifest.run_id == result.run_id
    assert manifest.experiment_id == result.resolved_config.experiment_id
    assert manifest.artifact_root_uri == bundle.artifact_root_uri
    assert manifest.required_artifacts_complete is True
    assert len(manifest.artifacts) == len(REQUIRED_ARTIFACT_SPECS)
    assert all(entry.status is ArtifactStatus.PRODUCED for entry in manifest.artifacts)
    assert all(
        entry.hash_algorithm is HashAlgorithm.SHA256 for entry in manifest.artifacts
    )
    assert "artifact_manifest.json" not in {
        entry.filename for entry in manifest.artifacts
    }


def test_no_placeholder_content(tmp_path: Path) -> None:
    bundle = generate_artifact_bundle(
        result=completed_result(),
        artifact_base_dir=tmp_path,
    )
    root = Path(bundle.artifact_root_path)

    combined_text = "\n".join(
        [
            (root / "config.json").read_text(encoding="utf-8"),
            (root / "metrics.json").read_text(encoding="utf-8"),
            (root / "regime_breakdown.json").read_text(encoding="utf-8"),
            (root / "failure_analysis.md").read_text(encoding="utf-8"),
            (root / "research_note.md").read_text(encoding="utf-8"),
        ]
    ).casefold()

    assert "placeholder" not in combined_text
    assert "todo" not in combined_text
    assert "tbd" not in combined_text
    assert "no performance claim" in combined_text


def test_payload_bytes_are_independent_of_physical_root(tmp_path: Path) -> None:
    result = completed_result()
    first = generate_artifact_bundle(result=result, artifact_base_dir=tmp_path / "one")
    second = generate_artifact_bundle(result=result, artifact_base_dir=tmp_path / "two")

    assert payload_identity(first) == payload_identity(second)
    assert first.artifact_root_uri != second.artifact_root_uri
    assert first.artifact_manifest_hash != second.artifact_manifest_hash


def test_same_manifest_serializes_deterministically(tmp_path: Path) -> None:
    bundle = generate_artifact_bundle(
        result=completed_result(),
        artifact_base_dir=tmp_path,
    )

    assert serialize_artifact_manifest(
        bundle.run_artifact_manifest
    ) == serialize_artifact_manifest(bundle.run_artifact_manifest)


def test_existing_nonempty_run_directory_is_not_overwritten(tmp_path: Path) -> None:
    result = completed_result()
    run_dir = tmp_path / result.run_id
    run_dir.mkdir(parents=True)
    (run_dir / "existing.txt").write_text("existing\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        generate_artifact_bundle(result=result, artifact_base_dir=tmp_path)


def read_schema(bundle, filename: str) -> pa.Schema:
    return read_table(bundle, filename).schema


def read_table(bundle, filename: str) -> pa.Table:
    return pq.read_table(Path(bundle.artifact_root_path) / filename)


def payload_identity(bundle) -> tuple[tuple[str, str, int], ...]:
    return tuple(
        (metadata.filename, metadata.content_hash, metadata.size_bytes)
        for metadata in bundle.payload_artifacts
    )


def writer_name_for_filename(filename: str) -> str:
    return {
        "config.json": "_write_config",
        "metrics.json": "_write_metrics",
        "trade_log.parquet": "_write_trade_log",
        "signal_log.parquet": "_write_signal_log",
        "daily_equity.parquet": "_write_daily_equity",
        "drawdown_series.parquet": "_write_drawdown_series",
        "monthly_returns.parquet": "_write_monthly_returns",
        "regime_breakdown.json": "_write_regime_breakdown",
        "failure_analysis.md": "_write_failure_analysis",
        "research_note.md": "_write_research_note",
    }[filename]


def completed_result():
    snapshot, fixture_hash = load_daily_bar_snapshot(FIXTURE_PATH)
    return run_buy_and_hold_backtest(
        config=resolved_config(),
        snapshot=snapshot,
        fixture_content_hash=fixture_hash,
        execution_metadata=execution_metadata(),
    )


def resolved_config() -> ResolvedBacktestConfig:
    return ResolvedBacktestConfig(
        experiment_id="exp-fixture-qqq-buy-hold",
        strategy_id="strategies/etfs/qqq_buy_and_hold",
        strategy_version="0.1.0",
        engine_version=ENGINE_VERSION,
        asset_symbol="QQQ",
        benchmark_symbol="SPY",
        start_date=date(2026, 1, 29),
        end_date=date(2026, 2, 5),
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
        data_snapshot_id="synthetic-etf-snapshot-20260206",
        benchmark_snapshot_id="synthetic-spy-benchmark-snapshot-20260206",
        random_seed=None,
        no_randomness_reason="deterministic no-randomness baseline",
        logical_execution_at=datetime(2026, 2, 6, tzinfo=UTC),
    )


def execution_metadata() -> ExecutionMetadata:
    return ExecutionMetadata(
        git_commit_sha="8f09472f18e7be1895f716b9c4a259ec1a5c4050",
        repo_dirty=False,
        python_version="3.13.14",
        platform="test-platform",
        dependency_lock_hash="sha256:test-lock",
        execution_command="python -m backtest_engine",
    )
