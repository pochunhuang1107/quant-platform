from __future__ import annotations

from datetime import UTC, datetime

from helpers_daily_market_data_snapshots import (
    EXPECTED_SESSIONS_HASH,
    POLICY_HASH,
    PROVENANCE_HASH,
    S3A_GOLDEN_CONTENT_HASH,
    SNAPSHOT_ID,
    sample_expected_sessions,
    sample_plan,
    sample_policy,
    sample_provenance_input,
)
from research_sdk.contracts import DataAdjustmentPolicy
from research_sdk.daily_market_data.snapshot_identity import (
    derive_daily_market_data_expected_sessions_hash,
    derive_daily_market_data_policy_hash,
    derive_daily_market_data_snapshot_id,
)


def test_policy_session_provenance_and_snapshot_identity_match_goldens() -> None:
    plan = sample_plan()

    assert derive_daily_market_data_policy_hash(sample_policy()) == POLICY_HASH
    assert (
        derive_daily_market_data_expected_sessions_hash(sample_expected_sessions())
        == EXPECTED_SESSIONS_HASH
    )
    assert plan.provenance_hash == PROVENANCE_HASH
    assert plan.snapshot_id == SNAPSHOT_ID
    assert plan.manifest.content_hash == S3A_GOLDEN_CONTENT_HASH


def test_same_complete_inputs_produce_same_snapshot_id() -> None:
    assert sample_plan().snapshot_id == sample_plan().snapshot_id
    assert sample_plan().as_file_map() == sample_plan().as_file_map()


def test_changed_semantic_bar_changes_snapshot_id() -> None:
    changed_source = (
        b'{"session_date":"2026-01-05","open":"101.0000","high":"102",'
        b'"low":"100.0","close":"101.60","volume":1100}\n'
        b'{"session_date":"2026-01-02","open":"100.0000","high":"101.0",'
        b'"low":"99","close":"100.5000","volume":1000}\n'
    )

    assert sample_plan(source_bytes=changed_source).snapshot_id != SNAPSHOT_ID


def test_changed_policy_semantics_changes_snapshot_id() -> None:
    changed_policy = sample_policy(
        adjustment_policy=DataAdjustmentPolicy.SPLIT_ADJUSTED
    )

    assert derive_daily_market_data_policy_hash(changed_policy) != POLICY_HASH
    assert sample_plan(policy=changed_policy).snapshot_id != SNAPSHOT_ID


def test_changed_expected_session_authority_changes_snapshot_id() -> None:
    changed = sample_expected_sessions(session_source_version="2026-01-fixture-v2")

    assert derive_daily_market_data_expected_sessions_hash(changed) != (
        EXPECTED_SESSIONS_HASH
    )
    assert sample_plan(expected_sessions=changed).snapshot_id != SNAPSHOT_ID


def test_changed_source_reference_and_timestamp_change_snapshot_id() -> None:
    changed_reference = sample_provenance_input(source_reference="fixture/other.jsonl")
    changed_timestamp = sample_provenance_input(
        created_at=datetime(2026, 1, 6, 1, 0, tzinfo=UTC)
    )

    assert sample_plan(provenance_input=changed_reference).snapshot_id != SNAPSHOT_ID
    assert sample_plan(provenance_input=changed_timestamp).snapshot_id != SNAPSHOT_ID


def test_snapshot_id_projection_excludes_storage_format_and_output_root() -> None:
    first = derive_daily_market_data_snapshot_id(
        semantic_content_hash=S3A_GOLDEN_CONTENT_HASH,
        policy_hash=POLICY_HASH,
        expected_sessions_hash=EXPECTED_SESSIONS_HASH,
        provenance_hash=PROVENANCE_HASH,
    )
    second = derive_daily_market_data_snapshot_id(
        semantic_content_hash=S3A_GOLDEN_CONTENT_HASH,
        policy_hash=POLICY_HASH,
        expected_sessions_hash=EXPECTED_SESSIONS_HASH,
        provenance_hash=PROVENANCE_HASH,
    )

    assert first == second == SNAPSHOT_ID


def test_same_semantic_rows_in_different_source_order_change_snapshot_vintage() -> None:
    reordered_source = (
        b'{"session_date":"2026-01-02","open":"100.0000","high":"101.0",'
        b'"low":"99","close":"100.5000","volume":1000}\n'
        b'{"session_date":"2026-01-05","open":"101.0000","high":"102",'
        b'"low":"100.0","close":"101.50","volume":1100}\n'
    )
    reordered = sample_plan(source_bytes=reordered_source)

    assert reordered.manifest.content_hash == S3A_GOLDEN_CONTENT_HASH
    assert (
        reordered.as_file_map()["bars.jsonl"]
        == sample_plan().as_file_map()["bars.jsonl"]
    )
    assert reordered.provenance_hash != PROVENANCE_HASH
    assert reordered.snapshot_id != SNAPSHOT_ID
