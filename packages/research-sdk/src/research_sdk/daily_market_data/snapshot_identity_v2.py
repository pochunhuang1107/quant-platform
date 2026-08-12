"""Pure natural identity helpers for daily market-data snapshot v2."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from research_sdk.contracts.daily_market_data import SHA256_CONTENT_HASH_PATTERN
from research_sdk.contracts.daily_market_data_economics import (
    DailyMarketDataCorporateActionEvidence,
)
from research_sdk.contracts.daily_market_data_snapshots_v2 import (
    SNAPSHOT_ID_V2_PREFIX,
    DailyMarketDataBarSourceProvenanceV2,
)

BAR_SOURCE_PROVENANCE_HASH_DOMAIN = "daily-market-data-bar-source-provenance"
BAR_SOURCE_PROVENANCE_HASH_VERSION = "daily-market-data-bar-source-provenance-hash-v1"
CORPORATE_ACTION_EVIDENCE_AUTHORITY_HASH_DOMAIN = (
    "daily-market-data-corporate-action-evidence-authority"
)
CORPORATE_ACTION_EVIDENCE_AUTHORITY_HASH_VERSION = (
    "daily-market-data-corporate-action-evidence-authority-v1"
)
SNAPSHOT_IDENTITY_DOMAIN_V2 = "daily-market-data-snapshot"
SNAPSHOT_IDENTITY_VERSION_V2 = "daily-market-data-snapshot-v2"


class DailyMarketDataSnapshotIdentityV2Error(ValueError):
    """Raised when daily market-data snapshot-v2 identity inputs are invalid."""


def derive_daily_market_data_bar_source_provenance_hash_v2(
    provenance: DailyMarketDataBarSourceProvenanceV2,
) -> str:
    """Hash the complete validated bar-source provenance-v2 contract."""

    validated = DailyMarketDataBarSourceProvenanceV2.model_validate(
        provenance.model_dump(mode="json")
    )
    return _sha256_prefixed(
        {
            "domain": BAR_SOURCE_PROVENANCE_HASH_DOMAIN,
            "identity_version": BAR_SOURCE_PROVENANCE_HASH_VERSION,
            "bar_provenance": validated.model_dump(mode="json"),
        }
    )


def derive_daily_market_data_corporate_action_evidence_authority_hash(
    evidence: DailyMarketDataCorporateActionEvidence,
) -> str:
    """Hash the complete validated corporate-action evidence authority contract."""

    validated = DailyMarketDataCorporateActionEvidence.model_validate(
        evidence.model_dump(mode="json")
    )
    return _sha256_prefixed(
        {
            "domain": CORPORATE_ACTION_EVIDENCE_AUTHORITY_HASH_DOMAIN,
            "identity_version": CORPORATE_ACTION_EVIDENCE_AUTHORITY_HASH_VERSION,
            "corporate_action_evidence": validated.model_dump(mode="json"),
        }
    )


def derive_daily_market_data_snapshot_id_v2(
    *,
    semantic_content_hash: str,
    policy_hash: str,
    expected_sessions_hash: str,
    bar_provenance_hash: str,
    corporate_action_semantic_hash: str,
    corporate_action_evidence_authority_hash: str,
) -> str:
    """Derive the immutable snapshot-v2 natural identity."""

    for field_name, field_value in (
        ("semantic_content_hash", semantic_content_hash),
        ("policy_hash", policy_hash),
        ("expected_sessions_hash", expected_sessions_hash),
        ("bar_provenance_hash", bar_provenance_hash),
        ("corporate_action_semantic_hash", corporate_action_semantic_hash),
        (
            "corporate_action_evidence_authority_hash",
            corporate_action_evidence_authority_hash,
        ),
    ):
        if SHA256_CONTENT_HASH_PATTERN.fullmatch(field_value) is None:
            raise DailyMarketDataSnapshotIdentityV2Error(
                f"{field_name} must use sha256:<64 lowercase hex>"
            )

    digest = _sha256_hex(
        {
            "domain": SNAPSHOT_IDENTITY_DOMAIN_V2,
            "identity_version": SNAPSHOT_IDENTITY_VERSION_V2,
            "semantic_content_hash": semantic_content_hash,
            "policy_hash": policy_hash,
            "expected_sessions_hash": expected_sessions_hash,
            "bar_provenance_hash": bar_provenance_hash,
            "corporate_action_semantic_hash": corporate_action_semantic_hash,
            "corporate_action_evidence_authority_hash": (
                corporate_action_evidence_authority_hash
            ),
        }
    )
    return f"{SNAPSHOT_ID_V2_PREFIX}{digest}"


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
    "BAR_SOURCE_PROVENANCE_HASH_DOMAIN",
    "BAR_SOURCE_PROVENANCE_HASH_VERSION",
    "CORPORATE_ACTION_EVIDENCE_AUTHORITY_HASH_DOMAIN",
    "CORPORATE_ACTION_EVIDENCE_AUTHORITY_HASH_VERSION",
    "SNAPSHOT_IDENTITY_DOMAIN_V2",
    "SNAPSHOT_IDENTITY_VERSION_V2",
    "DailyMarketDataSnapshotIdentityV2Error",
    "derive_daily_market_data_bar_source_provenance_hash_v2",
    "derive_daily_market_data_corporate_action_evidence_authority_hash",
    "derive_daily_market_data_snapshot_id_v2",
]
