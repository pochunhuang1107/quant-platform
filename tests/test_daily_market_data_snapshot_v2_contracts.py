from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from helpers_daily_market_data_snapshots import SNAPSHOT_ID
from helpers_daily_market_data_snapshots_v2 import sample_plan_v2
from research_sdk.contracts import DataSourceType, TemporalCoverage
from research_sdk.contracts.daily_market_data_snapshots import (
    CORPORATE_ACTION_NOT_INTEGRATED_LIMITATION,
)
from research_sdk.contracts.daily_market_data_snapshots_v2 import (
    BUNDLE_FORMAT_VERSION_V2,
    DailyMarketDataBarSourceProvenanceV2,
    DailyMarketDataSnapshotBundleManifestV2,
)


def test_bar_source_provenance_v2_accepts_bar_only_authority() -> None:
    provenance = sample_plan_v2().bar_provenance

    assert isinstance(provenance, DailyMarketDataBarSourceProvenanceV2)
    assert provenance.provenance_policy_version == (
        "daily-market-data-bar-source-provenance-v1"
    )
    assert provenance.parser_version == "daily-market-data-jsonl-parser-v1"
    assert not hasattr(provenance, "corporate_action_evidence_status")
    assert not hasattr(provenance, "corporate_action_source_reference")
    assert CORPORATE_ACTION_NOT_INTEGRATED_LIMITATION not in (
        provenance.known_limitations
    )


def test_bar_source_provenance_v2_rejects_unsafe_or_legacy_authority() -> None:
    base = sample_plan_v2().bar_provenance.model_dump(mode="json")

    bad_hash = dict(base, source_content_hash=f"sha256:{'A' * 64}")
    with pytest.raises(ValidationError, match="sha256"):
        DailyMarketDataBarSourceProvenanceV2.model_validate(bad_hash)

    credentialed = dict(base, source_reference="https://user:secret@example.test/a")
    with pytest.raises(ValidationError, match="userinfo"):
        DailyMarketDataBarSourceProvenanceV2.model_validate(credentialed)

    tokenized = dict(base, source_reference="https://example.test/a?api_key=secret")
    with pytest.raises(ValidationError, match="access tokens"):
        DailyMarketDataBarSourceProvenanceV2.model_validate(tokenized)

    legacy = dict(
        base,
        known_limitations=(
            CORPORATE_ACTION_NOT_INTEGRATED_LIMITATION,
            "synthetic bar fixture only",
        ),
    )
    with pytest.raises(ValidationError, match="legacy"):
        DailyMarketDataBarSourceProvenanceV2.model_validate(legacy)


def test_bar_source_provenance_v2_rejects_bad_chronology_and_vendor_gap() -> None:
    base = sample_plan_v2().bar_provenance.model_dump(mode="json")

    with pytest.raises(ValidationError, match="source_observed_at"):
        DailyMarketDataBarSourceProvenanceV2.model_validate(
            dict(
                base,
                source_observed_at="2026-01-06T00:01:00Z",
                ingestion_completed_at="2026-01-06T00:00:00Z",
            )
        )
    with pytest.raises(ValidationError, match="as_of"):
        DailyMarketDataBarSourceProvenanceV2.model_validate(
            dict(
                base,
                as_of=datetime(2026, 1, 6, 0, 1, tzinfo=UTC),
                available_at=datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
                created_at=datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
            )
        )
    with pytest.raises(ValidationError, match="mixed"):
        DailyMarketDataBarSourceProvenanceV2.model_validate(
            dict(base, temporal_coverage=TemporalCoverage.MIXED)
        )
    with pytest.raises(ValidationError, match="vendor_name"):
        DailyMarketDataBarSourceProvenanceV2.model_validate(
            dict(base, source_type=DataSourceType.VENDOR)
        )


def test_bundle_manifest_v2_requires_exact_v2_file_contract() -> None:
    manifest = sample_plan_v2().bundle_manifest

    assert manifest.bundle_format_version == BUNDLE_FORMAT_VERSION_V2
    assert isinstance(manifest, DailyMarketDataSnapshotBundleManifestV2)
    assert tuple(entry.relative_path for entry in manifest.files) == (
        "bars.jsonl",
        "expected-sessions.json",
        "policy.json",
        "bar-provenance.json",
        "quality-report.json",
        "corporate-action-evidence.json",
        "snapshot-manifest.json",
    )
    assert manifest.files[0].row_count == 2
    assert all(entry.row_count is None for entry in manifest.files[1:])


def test_bundle_manifest_v2_rejects_v1_identity_and_file_shape() -> None:
    manifest = sample_plan_v2().bundle_manifest
    payload = manifest.model_dump(mode="json")

    with pytest.raises(ValidationError, match="snapshot-v2"):
        DailyMarketDataSnapshotBundleManifestV2.model_validate(
            dict(payload, snapshot_id=SNAPSHOT_ID)
        )

    changed_files = list(payload["files"])
    changed_files[3] = dict(changed_files[3], relative_path="provenance.json")
    with pytest.raises(ValidationError, match="paths"):
        DailyMarketDataSnapshotBundleManifestV2.model_validate(
            dict(payload, files=changed_files)
        )

    changed_files = list(payload["files"])
    changed_files[1] = dict(changed_files[1], row_count=2)
    with pytest.raises(ValidationError, match="sidecar"):
        DailyMarketDataSnapshotBundleManifestV2.model_validate(
            dict(payload, files=changed_files)
        )
