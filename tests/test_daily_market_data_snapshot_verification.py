from __future__ import annotations

import json
import os
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from helpers_daily_market_data_snapshots import SNAPSHOT_ID, sample_plan
from research_sdk.daily_market_data_storage import (
    DailyMarketDataSnapshotSerializationError,
    DailyMarketDataSnapshotVerificationError,
    verify_daily_market_data_snapshot_bundle,
)


def test_in_memory_verifier_accepts_planned_snapshot_bundle() -> None:
    verified = verify_daily_market_data_snapshot_bundle(sample_plan().as_file_map())

    assert verified.snapshot_id == SNAPSHOT_ID
    assert verified.manifest.snapshot_id == SNAPSHOT_ID
    assert verified.bundle_manifest.snapshot_id == SNAPSHOT_ID
    assert verified.quality_report.status.value == "pass"


@pytest.mark.parametrize(
    "relative_path",
    [
        "bars.jsonl",
        "expected-sessions.json",
        "policy.json",
        "provenance.json",
        "quality-report.json",
        "snapshot-manifest.json",
        "bundle-manifest.json",
    ],
)
def test_in_memory_verifier_rejects_mutated_authoritative_files(
    relative_path: str,
) -> None:
    files = sample_plan().as_file_map()
    files[relative_path] = _mutate_bytes(files[relative_path])

    with pytest.raises(
        (
            DailyMarketDataSnapshotSerializationError,
            DailyMarketDataSnapshotVerificationError,
            ValidationError,
        )
    ):
        verify_daily_market_data_snapshot_bundle(files)


def test_in_memory_verifier_rejects_missing_and_unexpected_files() -> None:
    missing = sample_plan().as_file_map()
    del missing["policy.json"]
    with pytest.raises(DailyMarketDataSnapshotVerificationError, match="file set"):
        verify_daily_market_data_snapshot_bundle(missing)

    unexpected = sample_plan().as_file_map()
    unexpected["extra.json"] = b"{}\n"
    with pytest.raises(DailyMarketDataSnapshotVerificationError, match="file set"):
        verify_daily_market_data_snapshot_bundle(unexpected)


def test_in_memory_verifier_rejects_changed_payload_hash_and_size() -> None:
    files = sample_plan().as_file_map()
    manifest = json.loads(files["bundle-manifest.json"])
    manifest["files"][0]["sha256"] = f"sha256:{'0' * 64}"
    files["bundle-manifest.json"] = _canonical_json(manifest)

    with pytest.raises(DailyMarketDataSnapshotVerificationError, match="hash"):
        verify_daily_market_data_snapshot_bundle(files)

    files = sample_plan().as_file_map()
    manifest = json.loads(files["bundle-manifest.json"])
    manifest["files"][0]["size_bytes"] += 1
    files["bundle-manifest.json"] = _canonical_json(manifest)

    with pytest.raises(DailyMarketDataSnapshotVerificationError, match="size"):
        verify_daily_market_data_snapshot_bundle(files)


def test_in_memory_verifier_rejects_changed_identity_hashes() -> None:
    for field_name in (
        "semantic_content_hash",
        "policy_hash",
        "expected_sessions_hash",
        "provenance_hash",
    ):
        files = sample_plan().as_file_map()
        manifest = json.loads(files["bundle-manifest.json"])
        manifest[field_name] = f"sha256:{'0' * 64}"
        files["bundle-manifest.json"] = _canonical_json(manifest)

        with pytest.raises(DailyMarketDataSnapshotVerificationError):
            verify_daily_market_data_snapshot_bundle(files)


def test_in_memory_verifier_rejects_changed_snapshot_ids() -> None:
    files = sample_plan().as_file_map()
    manifest = json.loads(files["snapshot-manifest.json"])
    manifest["snapshot_id"] = "daily-market-data-snapshot-v1-" + ("0" * 64)
    files["snapshot-manifest.json"] = _canonical_json(manifest)
    _refresh_bundle_file_entry(files, "snapshot-manifest.json")

    with pytest.raises(DailyMarketDataSnapshotVerificationError):
        verify_daily_market_data_snapshot_bundle(files)


def test_in_memory_verifier_rejects_noncanonical_bars_bytes() -> None:
    files = sample_plan().as_file_map()
    files["bars.jsonl"] = (
        b'{"close":"101.5","high":"102","low":"100","open":"101",'
        b'"session_date":"2026-01-05","volume":1100}\n'
        b'{"close":"100.5","high":"101","low":"99","open":"100",'
        b'"session_date":"2026-01-02","volume":1000}\n'
    )
    _refresh_bundle_file_entry(files, "bars.jsonl")

    with pytest.raises(DailyMarketDataSnapshotVerificationError, match="canonical"):
        verify_daily_market_data_snapshot_bundle(files)


def test_daily_market_data_storage_import_does_not_load_operational_dependencies() -> (
    None
):
    repo_root = Path(__file__).resolve().parents[1]
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [
                str(repo_root / "packages" / "research-sdk" / "src"),
                str(repo_root / "packages" / "backtest-engine" / "src"),
            ]
        ),
    }
    command = [
        sys.executable,
        "-c",
        (
            "import json, sys; import research_sdk.daily_market_data_storage; "
            "print(json.dumps(sorted(sys.modules)))"
        ),
    ]
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    imported_modules = set(json.loads(result.stdout))

    assert {
        "sqlalchemy",
        "psycopg",
        "research_sdk.persistence",
        "backtest_engine",
        "boto3",
        "requests",
        "httpx",
        "pyarrow",
        "pandas",
    }.isdisjoint(imported_modules)


def _mutate_bytes(data: bytes) -> bytes:
    return data + b" "


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
