"""Deterministic identity helpers for the ETF backtest engine."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from backtest_engine.models import (
    CompletedBacktestResult,
    ExecutionMetadata,
    ResolvedBacktestConfig,
)

RUN_ID_PREFIX = "run-"
SHA256_HEX_LENGTH = 64


def canonical_json_bytes(payload: Any) -> bytes:
    """Render canonical UTF-8 JSON bytes with one trailing newline."""

    normalized = normalize_for_canonical_json(payload)
    rendered = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return f"{rendered}\n".encode()


def canonical_json_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def file_sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def derive_execution_identity(
    *,
    config: ResolvedBacktestConfig,
    execution_metadata: ExecutionMetadata,
    fixture_content_hash: str,
) -> tuple[str, str]:
    """Return full digest and public run_id derived only from execution inputs."""

    payload = {
        "resolved_config": config,
        "fixture_content_hash": fixture_content_hash,
        "data_snapshot_id": config.data_snapshot_id,
        "benchmark_snapshot_id": config.benchmark_snapshot_id,
        "strategy_id": config.strategy_id,
        "strategy_version": config.strategy_version,
        "engine_version": config.engine_version,
        "execution_metadata": execution_metadata,
        "no_randomness_marker": {
            "random_seed": config.random_seed,
            "no_randomness_reason": config.no_randomness_reason,
        },
    }
    digest = canonical_json_sha256(payload)
    return digest, f"{RUN_ID_PREFIX}{digest}"


def identity_from_completed_result(result: CompletedBacktestResult) -> tuple[str, str]:
    """Recompute identity from a result without reading result outputs."""

    return derive_execution_identity(
        config=result.resolved_config,
        execution_metadata=result.execution_metadata,
        fixture_content_hash=result.fixture_content_hash,
    )


def normalize_for_canonical_json(value: Any) -> Any:
    """Normalize supported model values to deterministic JSON primitives."""

    if isinstance(value, BaseModel):
        return normalize_for_canonical_json(value.model_dump(mode="python"))
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Decimal values must be finite")
        return format(value, "f")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("datetime values must be timezone-aware")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple | list):
        return [normalize_for_canonical_json(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): normalize_for_canonical_json(inner_value)
            for key, inner_value in value.items()
        }
    return value


def validate_run_id_contract_compatibility(run_id: str) -> None:
    """Verify the current contract accepts the full-digest run_id shape."""

    if not run_id.startswith(RUN_ID_PREFIX):
        raise ValueError("run_id must use the run- prefix")
    suffix = run_id.removeprefix(RUN_ID_PREFIX)
    if len(suffix) != SHA256_HEX_LENGTH:
        raise ValueError("run_id must contain the full SHA-256 digest")
    if suffix.lower() != suffix or not all(
        char in "0123456789abcdef" for char in suffix
    ):
        raise ValueError("run_id digest must be lowercase hexadecimal")


__all__ = [
    "RUN_ID_PREFIX",
    "SHA256_HEX_LENGTH",
    "canonical_json_bytes",
    "canonical_json_sha256",
    "derive_execution_identity",
    "file_sha256_bytes",
    "identity_from_completed_result",
    "normalize_for_canonical_json",
    "validate_run_id_contract_compatibility",
]
