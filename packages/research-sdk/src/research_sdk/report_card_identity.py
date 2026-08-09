"""Pure deterministic identity helpers for research report cards."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from research_sdk.contracts import ResearchReportCard
from research_sdk.contracts.report_cards import (
    REPORT_CARD_DIGEST_LENGTH,
    REPORT_CARD_ID_PREFIX,
    SHA256_CONTENT_HASH_PATTERN,
)

_LOWER_HEX_DIGITS = frozenset("0123456789abcdef")


class ResearchReportCardIdentityError(ValueError):
    """Raised when a report-card natural identity is malformed or stale."""


def derive_research_report_card_id_from_fields(
    *,
    source_run_id: str,
    schema_version: str,
    derivation_policy_version: str,
    data_snapshot_content_hash: str,
    benchmark_snapshot_content_hash: str,
    config_hash: str,
    parameter_hash: str,
    artifact_manifest_hash: str,
) -> str:
    """Derive the B1a natural report-card identity from durable fields."""

    _validate_sha256_content_hash(
        data_snapshot_content_hash,
        "lineage.data_snapshot_content_hash",
    )
    _validate_sha256_content_hash(
        benchmark_snapshot_content_hash,
        "lineage.benchmark_snapshot_content_hash",
    )
    _validate_sha256_content_hash(config_hash, "lineage.config_hash")
    _validate_sha256_content_hash(parameter_hash, "lineage.parameter_hash")
    _validate_sha256_content_hash(
        artifact_manifest_hash,
        "lineage.artifact_manifest_hash",
    )
    payload = {
        "source_run_id": source_run_id,
        "schema_version": schema_version,
        "derivation_policy_version": derivation_policy_version,
        "data_snapshot_content_hash": data_snapshot_content_hash,
        "benchmark_snapshot_content_hash": benchmark_snapshot_content_hash,
        "config_hash": config_hash,
        "parameter_hash": parameter_hash,
        "artifact_manifest_hash": artifact_manifest_hash,
    }
    return f"{REPORT_CARD_ID_PREFIX}{_canonical_json_sha256(payload)}"


def verify_research_report_card_identity(report_card: ResearchReportCard) -> None:
    """Verify a report-card ID by recomputing it from durable card fields."""

    _validate_report_card_id(report_card.report_card_id)
    expected = derive_research_report_card_id_from_fields(
        source_run_id=report_card.source_run_id,
        schema_version=report_card.schema_version,
        derivation_policy_version=report_card.derivation_policy_version,
        data_snapshot_content_hash=report_card.lineage.data_snapshot_content_hash,
        benchmark_snapshot_content_hash=(
            report_card.lineage.benchmark_snapshot_content_hash
        ),
        config_hash=report_card.lineage.config_hash,
        parameter_hash=report_card.lineage.parameter_hash,
        artifact_manifest_hash=report_card.lineage.artifact_manifest_hash,
    )
    if report_card.report_card_id != expected:
        raise ResearchReportCardIdentityError(
            "report-card identity is stale or inconsistent"
        )


def _validate_report_card_id(report_card_id: str) -> None:
    if not report_card_id.startswith(REPORT_CARD_ID_PREFIX):
        raise ResearchReportCardIdentityError(
            "report_card_id must use the report-card- prefix"
        )
    digest = report_card_id.removeprefix(REPORT_CARD_ID_PREFIX)
    if len(digest) != REPORT_CARD_DIGEST_LENGTH:
        raise ResearchReportCardIdentityError(
            "report_card_id must contain a full SHA-256 digest"
        )
    if digest.lower() != digest or any(
        character not in _LOWER_HEX_DIGITS for character in digest
    ):
        raise ResearchReportCardIdentityError(
            "report_card_id digest must be lowercase hexadecimal"
        )


def _validate_sha256_content_hash(value: str, field_name: str) -> None:
    if SHA256_CONTENT_HASH_PATTERN.fullmatch(value) is None:
        raise ResearchReportCardIdentityError(
            f"{field_name} must use sha256:<64 lowercase hex>"
        )


def _canonical_json_sha256(payload: Mapping[str, Any]) -> str:
    canonical_json = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(f"{canonical_json}\n".encode()).hexdigest()


__all__ = [
    "ResearchReportCardIdentityError",
    "derive_research_report_card_id_from_fields",
    "verify_research_report_card_identity",
]
