"""Pure natural identity helpers for daily market-data snapshots."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from research_sdk.contracts.daily_market_data import (
    SHA256_CONTENT_HASH_PATTERN,
    DailyMarketDataPolicy,
)
from research_sdk.contracts.daily_market_data_snapshots import (
    SNAPSHOT_ID_PREFIX,
    DailyMarketDataExpectedSessions,
    DailyMarketDataSnapshotProvenance,
)


class DailyMarketDataSnapshotIdentityError(ValueError):
    """Raised when daily market-data snapshot identity inputs are invalid."""


def derive_daily_market_data_policy_hash(
    policy: DailyMarketDataPolicy,
) -> str:
    """Hash the complete canonical daily market-data policy contract."""

    validated_policy = DailyMarketDataPolicy.model_validate(
        policy.model_dump(mode="json")
    )
    return _sha256_prefixed(
        {
            "domain": "daily-market-data-policy",
            "identity_version": "daily-market-data-policy-hash-v1",
            "policy": validated_policy.model_dump(mode="json"),
        }
    )


def derive_daily_market_data_expected_sessions_hash(
    expected_sessions: DailyMarketDataExpectedSessions,
) -> str:
    """Hash the complete expected-session authority contract."""

    validated_expected_sessions = DailyMarketDataExpectedSessions.model_validate(
        expected_sessions.model_dump(mode="json")
    )
    return _sha256_prefixed(
        {
            "domain": "daily-market-data-expected-sessions",
            "identity_version": "daily-market-data-expected-sessions-hash-v1",
            "expected_sessions": validated_expected_sessions.model_dump(mode="json"),
        }
    )


def derive_daily_market_data_provenance_hash(
    provenance: DailyMarketDataSnapshotProvenance,
) -> str:
    """Hash the complete persisted snapshot provenance contract."""

    validated_provenance = DailyMarketDataSnapshotProvenance.model_validate(
        provenance.model_dump(mode="json")
    )
    return _sha256_prefixed(
        {
            "domain": "daily-market-data-snapshot-provenance",
            "identity_version": "daily-market-data-provenance-hash-v1",
            "provenance": validated_provenance.model_dump(mode="json"),
        }
    )


def derive_daily_market_data_snapshot_id(
    *,
    semantic_content_hash: str,
    policy_hash: str,
    expected_sessions_hash: str,
    provenance_hash: str,
) -> str:
    """Derive the immutable snapshot natural identity."""

    for field_name, field_value in (
        ("semantic_content_hash", semantic_content_hash),
        ("policy_hash", policy_hash),
        ("expected_sessions_hash", expected_sessions_hash),
        ("provenance_hash", provenance_hash),
    ):
        if SHA256_CONTENT_HASH_PATTERN.fullmatch(field_value) is None:
            raise DailyMarketDataSnapshotIdentityError(
                f"{field_name} must use sha256:<64 lowercase hex>"
            )

    digest = _sha256_hex(
        {
            "domain": "daily-market-data-snapshot",
            "identity_version": "daily-market-data-snapshot-v1",
            "semantic_content_hash": semantic_content_hash,
            "policy_hash": policy_hash,
            "expected_sessions_hash": expected_sessions_hash,
            "provenance_hash": provenance_hash,
        }
    )
    return f"{SNAPSHOT_ID_PREFIX}{digest}"


def _sha256_prefixed(payload: Mapping[str, Any]) -> str:
    return f"sha256:{_sha256_hex(payload)}"


def _sha256_hex(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    rendered = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return f"{rendered}\n".encode()


__all__ = [
    "DailyMarketDataSnapshotIdentityError",
    "derive_daily_market_data_expected_sessions_hash",
    "derive_daily_market_data_policy_hash",
    "derive_daily_market_data_provenance_hash",
    "derive_daily_market_data_snapshot_id",
]
