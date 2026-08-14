"""Canonical serialization for daily market-data source-capture manifests."""

from __future__ import annotations

import json
from typing import Any

from research_sdk.contracts.base import BaseContractModel
from research_sdk.daily_market_data_source_capture.models import (
    DailyMarketDataCASourceManifest,
    DailyMarketDataSourceCaptureManifest,
)
from research_sdk.daily_market_data_storage.serialization import render_contract_json


class DailyMarketDataSourceCaptureSerializationError(ValueError):
    """Raised when source-capture canonical bytes are malformed."""


def render_source_capture_model(model: BaseContractModel) -> bytes:
    """Render an operational source-capture model as canonical JSON bytes."""

    return render_contract_json(model)


def render_capture_manifest(
    manifest: DailyMarketDataSourceCaptureManifest,
) -> bytes:
    """Render canonical source-capture manifest bytes."""

    return render_source_capture_model(manifest)


def render_ca_source_manifest(manifest: DailyMarketDataCASourceManifest) -> bytes:
    """Render canonical corporate-action source-manifest bytes."""

    return render_source_capture_model(manifest)


def parse_capture_manifest(data: bytes) -> DailyMarketDataSourceCaptureManifest:
    """Parse a canonical source-capture manifest from bytes."""

    return _parse_canonical_model(
        data,
        DailyMarketDataSourceCaptureManifest,
        context="capture-manifest.json",
    )


def parse_ca_source_manifest(data: bytes) -> DailyMarketDataCASourceManifest:
    """Parse a canonical corporate-action source manifest from bytes."""

    return _parse_canonical_model(
        data,
        DailyMarketDataCASourceManifest,
        context="ca-source-manifest.json",
    )


def _parse_canonical_model[ModelT: BaseContractModel](
    data: bytes,
    model: type[ModelT],
    *,
    context: str,
) -> ModelT:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DailyMarketDataSourceCaptureSerializationError(
            f"{context} must be UTF-8"
        ) from exc
    try:
        payload = _strict_json_loads(text, context=context)
    except json.JSONDecodeError as exc:
        raise DailyMarketDataSourceCaptureSerializationError(
            f"{context} is not valid JSON"
        ) from exc
    try:
        parsed = model.model_validate(payload)
    except Exception as exc:
        raise DailyMarketDataSourceCaptureSerializationError(
            f"{context} failed model validation"
        ) from exc
    expected = render_source_capture_model(parsed)
    if expected != data:
        raise DailyMarketDataSourceCaptureSerializationError(
            f"{context} must use canonical JSON bytes"
        )
    return parsed


def _strict_json_loads(text: str, *, context: str) -> Any:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: set[str] = set()
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in seen:
                raise DailyMarketDataSourceCaptureSerializationError(
                    f"{context} contains duplicate JSON key: {key}"
                )
            seen.add(key)
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise DailyMarketDataSourceCaptureSerializationError(
            f"{context} contains non-standard JSON constant: {value}"
        )

    return json.loads(
        text,
        object_pairs_hook=reject_duplicate_keys,
        parse_constant=reject_constant,
    )


__all__ = [
    "DailyMarketDataSourceCaptureSerializationError",
    "parse_ca_source_manifest",
    "parse_capture_manifest",
    "render_ca_source_manifest",
    "render_capture_manifest",
    "render_source_capture_model",
]
