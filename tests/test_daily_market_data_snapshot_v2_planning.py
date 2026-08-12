from __future__ import annotations

from dataclasses import fields
from datetime import UTC, date, datetime

import pytest

from helpers_daily_market_data_snapshots import (
    CANONICAL_BARS_BYTES,
    EXPECTED_SESSIONS_HASH,
    POLICY_HASH,
    S3A_GOLDEN_CONTENT_HASH,
    sample_expected_sessions,
    sample_instrument,
    sample_policy,
)
from helpers_daily_market_data_snapshots_v2 import (
    BAR_PROVENANCE_HASH_V2,
    CORPORATE_ACTION_EVIDENCE_AUTHORITY_HASH,
    CORPORATE_ACTION_SEMANTIC_HASH,
    SNAPSHOT_ID_V2,
    sample_bar_provenance_input_v2,
    sample_corporate_action_evidence_v2,
    sample_plan_v2,
    unsupported_event_v2,
)
from research_sdk.contracts import DataSnapshotKind, DataSnapshotStatus, HashAlgorithm
from research_sdk.contracts.daily_market_data_economics import (
    DailyMarketDataCorporateActionEvidenceCompleteness,
)
from research_sdk.daily_market_data_storage import (
    DailyMarketDataBarSourceProvenanceInputV2,
    DailyMarketDataSnapshotPlanningV2Error,
    plan_daily_market_data_snapshot_v2,
)
from research_sdk.daily_market_data_storage.planning_v2 import (
    BAR_PARSER_VERSION,
    BAR_PROVENANCE_POLICY_VERSION,
)


def test_planner_v2_builds_happy_path_synthetic_snapshot_plan() -> None:
    plan = sample_plan_v2()

    assert plan.snapshot_id == SNAPSHOT_ID_V2
    assert plan.manifest.content_hash == S3A_GOLDEN_CONTENT_HASH
    assert plan.as_file_map()["bars.jsonl"] == CANONICAL_BARS_BYTES
    assert tuple(plan.as_file_map()) == (
        "bars.jsonl",
        "expected-sessions.json",
        "policy.json",
        "bar-provenance.json",
        "quality-report.json",
        "corporate-action-evidence.json",
        "snapshot-manifest.json",
        "bundle-manifest.json",
    )
    assert plan.policy_hash == POLICY_HASH
    assert plan.expected_sessions_hash == EXPECTED_SESSIONS_HASH
    assert plan.bar_provenance_hash == BAR_PROVENANCE_HASH_V2
    assert plan.corporate_action_semantic_hash == CORPORATE_ACTION_SEMANTIC_HASH
    assert plan.corporate_action_evidence_authority_hash == (
        CORPORATE_ACTION_EVIDENCE_AUTHORITY_HASH
    )


def test_planner_v2_owns_bar_parser_and_provenance_policy_versions() -> None:
    field_names = {
        field.name for field in fields(DailyMarketDataBarSourceProvenanceInputV2)
    }
    plan = sample_plan_v2()
    provenance = plan.as_file_map()["bar-provenance.json"].decode()

    assert "parser_version" not in field_names
    assert "provenance_policy_version" not in field_names
    assert f'"parser_version":"{BAR_PARSER_VERSION}"' in provenance
    assert f'"provenance_policy_version":"{BAR_PROVENANCE_POLICY_VERSION}"' in (
        provenance
    )


def test_planner_v2_derives_manifest_fields_and_combined_timestamps() -> None:
    plan = sample_plan_v2()
    manifest = plan.manifest

    assert manifest.snapshot_kind is DataSnapshotKind.MARKET_DATA
    assert manifest.status is DataSnapshotStatus.COMPLETED
    assert manifest.asset_universe.symbols == ("QQQ",)
    assert manifest.asset_universe.universe_id == (
        "daily-market-data-single-instrument-v2:instrument-us-etf-qqq-xnas"
    )
    assert manifest.time_range.start_date == date(2026, 1, 2)
    assert manifest.time_range.end_date == date(2026, 1, 5)
    assert manifest.row_count == 2
    assert manifest.file_count == 1
    assert manifest.size_bytes == len(CANONICAL_BARS_BYTES)
    assert manifest.data_root_uri == f"daily-market-data/{SNAPSHOT_ID_V2}"
    assert manifest.currency == "USD"
    assert manifest.hash_algorithm is HashAlgorithm.SHA256
    assert manifest.ingestion_completed_at == datetime(2026, 1, 5, 23, 55, tzinfo=UTC)
    assert manifest.available_at == datetime(2026, 1, 5, 23, 58, tzinfo=UTC)
    assert manifest.created_at == datetime(2026, 1, 6, 0, 0, tzinfo=UTC)
    assert manifest.as_of == datetime(2026, 1, 5, 23, 50, tzinfo=UTC)


def test_manifest_v2_keeps_bar_primary_source_and_bars_payload_semantics() -> None:
    changed_ca = sample_corporate_action_evidence_v2(
        source_dataset="synthetic-different-ca-source",
        source_version="2026-01-different-ca-vintage",
    )
    plan = sample_plan_v2(corporate_action_evidence=changed_ca)

    assert plan.manifest.source_dataset == "synthetic-daily-market-data-fixture"
    assert plan.manifest.source_version == "2026-01-synthetic-v1"
    assert plan.manifest.content_hash == S3A_GOLDEN_CONTENT_HASH
    assert plan.manifest.row_count == 2
    assert plan.manifest.file_count == 1
    assert plan.manifest.size_bytes == len(CANONICAL_BARS_BYTES)
    assert plan.corporate_action_evidence_authority_hash != (
        CORPORATE_ACTION_EVIDENCE_AUTHORITY_HASH
    )
    assert plan.snapshot_id != SNAPSHOT_ID_V2


def test_manifest_v2_known_limitations_merge_is_stable_and_unique() -> None:
    plan = sample_plan_v2(
        corporate_action_evidence=sample_corporate_action_evidence_v2(
            known_limitations=(
                "not production source authority",
                "synthetic corporate-action fixture only",
            )
        )
    )

    assert plan.manifest.known_limitations == (
        "synthetic bar fixture only",
        "not historical performance evidence",
        "not production source authority",
        "not paper/live input",
        "synthetic corporate-action fixture only",
    )


def test_planner_v2_rejects_non_bytes_source() -> None:
    with pytest.raises(DailyMarketDataSnapshotPlanningV2Error, match="source_bytes"):
        plan_daily_market_data_snapshot_v2(
            source_bytes="not bytes",  # type: ignore[arg-type]
            instrument=sample_instrument(),
            policy=sample_policy(),
            expected_sessions=sample_expected_sessions(),
            bar_provenance_input=sample_bar_provenance_input_v2(),
            corporate_action_evidence=sample_corporate_action_evidence_v2(),
        )


def test_planner_v2_rejects_quality_and_policy_session_failures() -> None:
    bad_source = (
        b'{"session_date":"2026-01-02","open":"100","high":"101",'
        b'"low":"99","close":"100.5","volume":0}\n'
        b'{"session_date":"2026-01-05","open":"101","high":"102",'
        b'"low":"100","close":"101.5","volume":1100}\n'
    )
    with pytest.raises(DailyMarketDataSnapshotPlanningV2Error, match="quality"):
        sample_plan_v2(source_bytes=bad_source)
    with pytest.raises(DailyMarketDataSnapshotPlanningV2Error, match="calendar"):
        sample_plan_v2(expected_sessions=sample_expected_sessions(calendar="XNAS"))
    with pytest.raises(DailyMarketDataSnapshotPlanningV2Error, match="timezone"):
        sample_plan_v2(expected_sessions=sample_expected_sessions(timezone="UTC"))


def test_planner_v2_rejects_bar_as_of_instrument_and_ca_coverage_gaps() -> None:
    with pytest.raises(DailyMarketDataSnapshotPlanningV2Error, match="as_of"):
        sample_plan_v2(
            bar_provenance_input=sample_bar_provenance_input_v2(
                as_of=datetime(2026, 1, 4, 0, 0, tzinfo=UTC)
            )
        )

    with pytest.raises(DailyMarketDataSnapshotPlanningV2Error, match="instrument"):
        sample_plan_v2(
            corporate_action_evidence=sample_corporate_action_evidence_v2(
                instrument=sample_instrument().model_copy(
                    update={"instrument_id": "instrument-other"}
                ),
                events=(),
                completeness=(
                    DailyMarketDataCorporateActionEvidenceCompleteness.CHECKED_NO_EVENTS
                ),
            )
        )

    with pytest.raises(DailyMarketDataSnapshotPlanningV2Error, match="coverage"):
        sample_plan_v2(
            corporate_action_evidence=sample_corporate_action_evidence_v2(
                coverage_end_date=date(2026, 1, 4)
            )
        )


def test_planner_v2_allows_broader_coverage_and_unsupported_events() -> None:
    broader = sample_plan_v2(
        corporate_action_evidence=sample_corporate_action_evidence_v2(
            coverage_start_date=date(2026, 1, 1),
            coverage_end_date=date(2026, 1, 6),
        )
    )
    assert broader.snapshot_id != SNAPSHOT_ID_V2

    unsupported = sample_plan_v2(
        corporate_action_evidence=sample_corporate_action_evidence_v2(
            events=(unsupported_event_v2(),)
        )
    )
    assert unsupported.corporate_action_evidence.events[0].event_type.value == (
        "unsupported"
    )


def test_planner_v2_is_deterministic_and_has_no_profile_or_caller_hash_inputs() -> None:
    assert sample_plan_v2().as_file_map() == sample_plan_v2().as_file_map()

    params = plan_daily_market_data_snapshot_v2.__annotations__
    assert "research_profile" not in params
    assert "snapshot_id" not in params
    assert "manifest" not in params
    assert "content_hash" not in params

    changed_order_source = (
        b'{"session_date":"2026-01-05","open":"101","high":"102",'
        b'"low":"100","close":"101.5","volume":1100}\n'
        b'{"session_date":"2026-01-02","open":"100","high":"101",'
        b'"low":"99","close":"100.5","volume":1000}\n'
    )
    plan = sample_plan_v2(source_bytes=changed_order_source)
    assert plan.manifest.content_hash == S3A_GOLDEN_CONTENT_HASH
    assert plan.as_file_map()["bars.jsonl"] == CANONICAL_BARS_BYTES
    assert (
        plan.bar_provenance.source_content_hash
        != sample_plan_v2().bar_provenance.source_content_hash
    )
