"""Deterministic bytes serialization for daily market-data snapshot bundles."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from research_sdk.contracts.base import BaseContractModel
from research_sdk.contracts.daily_market_data import CanonicalDailyBar

_BAR_FIELDS = frozenset({"session_date", "open", "high", "low", "close", "volume"})


class DailyMarketDataSnapshotSerializationError(ValueError):
    """Raised when daily market-data snapshot bytes are malformed."""


def parse_canonical_daily_bars(data: bytes) -> tuple[CanonicalDailyBar, ...]:
    """Parse canonicalizable UTF-8 JSON Lines daily bars.

    Source input may omit a final newline, but published output always includes
    exactly one final newline.
    """

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DailyMarketDataSnapshotSerializationError(
            "daily bars JSONL must be UTF-8"
        ) from exc
    if text == "":
        raise DailyMarketDataSnapshotSerializationError(
            "daily bars JSONL must contain at least one line"
        )

    lines = text.splitlines()
    if not lines:
        raise DailyMarketDataSnapshotSerializationError(
            "daily bars JSONL must contain at least one line"
        )

    bars: list[CanonicalDailyBar] = []
    for line_number, line in enumerate(lines, start=1):
        if line == "":
            raise DailyMarketDataSnapshotSerializationError(
                f"daily bars JSONL line {line_number} must not be blank"
            )
        try:
            payload = _strict_json_loads(
                line,
                context=f"daily bars JSONL line {line_number}",
            )
        except json.JSONDecodeError as exc:
            raise DailyMarketDataSnapshotSerializationError(
                f"daily bars JSONL line {line_number} is not valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise DailyMarketDataSnapshotSerializationError(
                f"daily bars JSONL line {line_number} must be a JSON object"
            )
        _validate_bar_payload(payload, line_number)
        bars.append(CanonicalDailyBar.model_validate(payload))
    return tuple(bars)


def render_canonical_daily_bars(
    bars: tuple[CanonicalDailyBar, ...],
) -> bytes:
    """Render deterministic published JSON Lines bytes for canonical daily bars."""

    validated_bars = tuple(_revalidate_bar(bar) for bar in bars)
    ordered_bars = sorted(
        validated_bars,
        key=lambda bar: (
            bar.session_date,
            _canonical_decimal(bar.open),
            _canonical_decimal(bar.high),
            _canonical_decimal(bar.low),
            _canonical_decimal(bar.close),
            bar.volume,
        ),
    )
    rendered_lines = [
        _canonical_json_line(
            {
                "session_date": bar.session_date.isoformat(),
                "open": _canonical_decimal(bar.open),
                "high": _canonical_decimal(bar.high),
                "low": _canonical_decimal(bar.low),
                "close": _canonical_decimal(bar.close),
                "volume": bar.volume,
            }
        )
        for bar in ordered_bars
    ]
    return ("\n".join(rendered_lines) + "\n").encode("utf-8")


def render_contract_json(contract: BaseContractModel) -> bytes:
    """Render a contract as compact canonical UTF-8 JSON bytes."""

    validated = type(contract).model_validate(contract.model_dump(mode="json"))
    return _canonical_json_bytes(validated.model_dump(mode="json"))


def parse_contract_json[ContractT: BaseContractModel](
    data: bytes,
    model: type[ContractT],
) -> ContractT:
    """Parse canonical contract JSON bytes into the requested Pydantic model."""

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DailyMarketDataSnapshotSerializationError(
            "contract JSON must be UTF-8"
        ) from exc
    try:
        payload = _strict_json_loads(text, context="contract JSON")
    except json.JSONDecodeError as exc:
        raise DailyMarketDataSnapshotSerializationError(
            "contract JSON is not valid JSON"
        ) from exc
    return model.model_validate(payload)


def sha256_bytes(data: bytes) -> str:
    """Return repository-standard SHA-256 bytes hash formatting."""

    import hashlib

    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _validate_bar_payload(payload: dict[str, Any], line_number: int) -> None:
    keys = set(payload)
    if keys != _BAR_FIELDS:
        raise DailyMarketDataSnapshotSerializationError(
            f"daily bars JSONL line {line_number} must contain exactly "
            f"{sorted(_BAR_FIELDS)}"
        )
    if not isinstance(payload["session_date"], str):
        raise DailyMarketDataSnapshotSerializationError(
            f"daily bars JSONL line {line_number} session_date must be a string"
        )
    for field_name in ("open", "high", "low", "close"):
        if not isinstance(payload[field_name], str):
            raise DailyMarketDataSnapshotSerializationError(
                f"daily bars JSONL line {line_number} {field_name} must be a string"
            )
        if payload[field_name] == "":
            raise DailyMarketDataSnapshotSerializationError(
                f"daily bars JSONL line {line_number} {field_name} must not be blank"
            )
    if isinstance(payload["volume"], bool) or not isinstance(payload["volume"], int):
        raise DailyMarketDataSnapshotSerializationError(
            f"daily bars JSONL line {line_number} volume must be a JSON integer"
        )
    if any(value is None for value in payload.values()):
        raise DailyMarketDataSnapshotSerializationError(
            f"daily bars JSONL line {line_number} must not contain null values"
        )


def _strict_json_loads(text: str, *, context: str) -> Any:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: set[str] = set()
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in seen:
                raise DailyMarketDataSnapshotSerializationError(
                    f"{context} contains duplicate JSON key: {key}"
                )
            seen.add(key)
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise DailyMarketDataSnapshotSerializationError(
            f"{context} contains non-standard JSON constant: {value}"
        )

    return json.loads(
        text,
        object_pairs_hook=reject_duplicate_keys,
        parse_constant=reject_constant,
    )


def _revalidate_bar(bar: CanonicalDailyBar) -> CanonicalDailyBar:
    return CanonicalDailyBar.model_validate(bar.model_dump(mode="json"))


def _canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("decimal values must be finite")
    if value == value.to_integral_value():
        return format(value, "f").split(".", 1)[0]
    return format(value.normalize(), "f")


def _canonical_json_line(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _canonical_json_bytes(payload: Any) -> bytes:
    return f"{_canonical_json_line(payload)}\n".encode()


__all__ = [
    "DailyMarketDataSnapshotSerializationError",
    "parse_canonical_daily_bars",
    "parse_contract_json",
    "render_canonical_daily_bars",
    "render_contract_json",
    "sha256_bytes",
]
