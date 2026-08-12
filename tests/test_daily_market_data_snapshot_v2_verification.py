from __future__ import annotations

import json
from hashlib import sha256

import pytest
from pydantic import ValidationError

from helpers_daily_market_data_snapshots import SNAPSHOT_ID
from helpers_daily_market_data_snapshots_v2 import SNAPSHOT_ID_V2, sample_plan_v2
from research_sdk.daily_market_data_storage import (
    DailyMarketDataSnapshotSerializationError,
    DailyMarketDataSnapshotVerificationV2Error,
    verify_daily_market_data_snapshot_bundle_v2,
)


def test_in_memory_verifier_v2_accepts_planned_snapshot_bundle() -> None:
    verified = verify_daily_market_data_snapshot_bundle_v2(
        sample_plan_v2().as_file_map()
    )

    assert verified.snapshot_id == SNAPSHOT_ID_V2
    assert verified.manifest.snapshot_id == SNAPSHOT_ID_V2
    assert verified.bundle_manifest.snapshot_id == SNAPSHOT_ID_V2
    assert verified.quality_report.status.value == "pass"
    assert verified.bar_provenance.source_dataset == (
        "synthetic-daily-market-data-fixture"
    )
    assert verified.corporate_action_evidence.source_dataset == (
        "synthetic-v2-corporate-action-fixture"
    )


@pytest.mark.parametrize(
    "relative_path",
    [
        "bars.jsonl",
        "expected-sessions.json",
        "policy.json",
        "bar-provenance.json",
        "quality-report.json",
        "corporate-action-evidence.json",
        "snapshot-manifest.json",
        "bundle-manifest.json",
    ],
)
def test_in_memory_verifier_v2_rejects_mutated_authoritative_files(
    relative_path: str,
) -> None:
    files = sample_plan_v2().as_file_map()
    files[relative_path] = files[relative_path] + b" "

    with pytest.raises(
        (
            DailyMarketDataSnapshotSerializationError,
            DailyMarketDataSnapshotVerificationV2Error,
            ValidationError,
        )
    ):
        verify_daily_market_data_snapshot_bundle_v2(files)


def test_in_memory_verifier_v2_rejects_missing_and_unexpected_files() -> None:
    missing = sample_plan_v2().as_file_map()
    del missing["corporate-action-evidence.json"]
    with pytest.raises(DailyMarketDataSnapshotVerificationV2Error, match="file set"):
        verify_daily_market_data_snapshot_bundle_v2(missing)

    unexpected = sample_plan_v2().as_file_map()
    unexpected["provenance.json"] = b"{}\n"
    with pytest.raises(DailyMarketDataSnapshotVerificationV2Error, match="file set"):
        verify_daily_market_data_snapshot_bundle_v2(unexpected)


def test_in_memory_verifier_v2_rejects_changed_payload_hash_and_size() -> None:
    files = sample_plan_v2().as_file_map()
    manifest = json.loads(files["bundle-manifest.json"])
    manifest["files"][5]["sha256"] = f"sha256:{'0' * 64}"
    files["bundle-manifest.json"] = _canonical_json(manifest)

    with pytest.raises(DailyMarketDataSnapshotVerificationV2Error, match="hash"):
        verify_daily_market_data_snapshot_bundle_v2(files)

    files = sample_plan_v2().as_file_map()
    manifest = json.loads(files["bundle-manifest.json"])
    manifest["files"][5]["size_bytes"] += 1
    files["bundle-manifest.json"] = _canonical_json(manifest)

    with pytest.raises(DailyMarketDataSnapshotVerificationV2Error, match="size"):
        verify_daily_market_data_snapshot_bundle_v2(files)


def test_in_memory_verifier_v2_rejects_changed_identity_hashes() -> None:
    for field_name in (
        "semantic_content_hash",
        "policy_hash",
        "expected_sessions_hash",
        "bar_provenance_hash",
        "corporate_action_semantic_hash",
        "corporate_action_evidence_authority_hash",
    ):
        files = sample_plan_v2().as_file_map()
        manifest = json.loads(files["bundle-manifest.json"])
        manifest[field_name] = f"sha256:{'0' * 64}"
        files["bundle-manifest.json"] = _canonical_json(manifest)

        with pytest.raises(DailyMarketDataSnapshotVerificationV2Error):
            verify_daily_market_data_snapshot_bundle_v2(files)


def test_in_memory_verifier_v2_rejects_v1_snapshot_id_version() -> None:
    files = sample_plan_v2().as_file_map()
    manifest = json.loads(files["bundle-manifest.json"])
    manifest["snapshot_id"] = SNAPSHOT_ID
    files["bundle-manifest.json"] = _canonical_json(manifest)

    with pytest.raises(ValidationError, match="snapshot-v2"):
        verify_daily_market_data_snapshot_bundle_v2(files)

    files = sample_plan_v2().as_file_map()
    snapshot_manifest = json.loads(files["snapshot-manifest.json"])
    snapshot_manifest["snapshot_id"] = SNAPSHOT_ID
    snapshot_manifest["data_root_uri"] = f"daily-market-data/{SNAPSHOT_ID}"
    files["snapshot-manifest.json"] = _canonical_json(snapshot_manifest)
    _refresh_bundle_file_entry(files, "snapshot-manifest.json")

    with pytest.raises(
        DailyMarketDataSnapshotVerificationV2Error,
        match="manifest snapshot_id mismatch",
    ):
        verify_daily_market_data_snapshot_bundle_v2(files)


def test_in_memory_verifier_v2_rejects_manifest_boundary_corruption() -> None:
    files = sample_plan_v2().as_file_map()
    manifest = json.loads(files["snapshot-manifest.json"])
    manifest["file_count"] = 8
    files["snapshot-manifest.json"] = _canonical_json(manifest)
    _refresh_bundle_file_entry(files, "snapshot-manifest.json")

    with pytest.raises(DailyMarketDataSnapshotVerificationV2Error, match="file_count"):
        verify_daily_market_data_snapshot_bundle_v2(files)

    files = sample_plan_v2().as_file_map()
    manifest = json.loads(files["snapshot-manifest.json"])
    manifest["source_dataset"] = "synthetic-v2-corporate-action-fixture"
    files["snapshot-manifest.json"] = _canonical_json(manifest)
    _refresh_bundle_file_entry(files, "snapshot-manifest.json")

    with pytest.raises(DailyMarketDataSnapshotVerificationV2Error, match="bar-primary"):
        verify_daily_market_data_snapshot_bundle_v2(files)


def test_in_memory_verifier_v2_rejects_noncanonical_payload_bytes() -> None:
    files = sample_plan_v2().as_file_map()
    files["bars.jsonl"] = (
        b'{"close":"101.5","high":"102","low":"100","open":"101",'
        b'"session_date":"2026-01-05","volume":1100}\n'
        b'{"close":"100.5","high":"101","low":"99","open":"100",'
        b'"session_date":"2026-01-02","volume":1000}\n'
    )
    _refresh_bundle_file_entry(files, "bars.jsonl")

    with pytest.raises(DailyMarketDataSnapshotVerificationV2Error, match="canonical"):
        verify_daily_market_data_snapshot_bundle_v2(files)

    files = sample_plan_v2().as_file_map()
    policy = json.loads(files["policy.json"])
    files["policy.json"] = json.dumps(policy, indent=2).encode() + b"\n"
    _refresh_bundle_file_entry(files, "policy.json")

    with pytest.raises(DailyMarketDataSnapshotVerificationV2Error, match="canonical"):
        verify_daily_market_data_snapshot_bundle_v2(files)


def _canonical_json(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _refresh_bundle_file_entry(files: dict[str, bytes], relative_path: str) -> None:
    manifest = json.loads(files["bundle-manifest.json"])
    for entry in manifest["files"]:
        if entry["relative_path"] == relative_path:
            entry["sha256"] = f"sha256:{sha256(files[relative_path]).hexdigest()}"
            entry["size_bytes"] = len(files[relative_path])
            break
    files["bundle-manifest.json"] = _canonical_json(manifest)
