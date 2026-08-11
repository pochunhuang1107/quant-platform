from __future__ import annotations

from dataclasses import fields
from datetime import UTC, date, datetime

import pytest

from helpers_daily_market_data_snapshots import (
    BARS_STORAGE_HASH,
    CANONICAL_BARS_BYTES,
    PROVENANCE_HASH,
    S3A_GOLDEN_CONTENT_HASH,
    SNAPSHOT_ID,
    sample_expected_sessions,
    sample_instrument,
    sample_plan,
    sample_policy,
    sample_provenance_input,
    source_bytes,
)
from research_sdk.contracts import DataSnapshotKind, DataSnapshotStatus, HashAlgorithm
from research_sdk.contracts.daily_market_data_snapshots import (
    CorporateActionEvidenceStatus,
)
from research_sdk.daily_market_data import validate_daily_market_data_snapshot_manifest
from research_sdk.daily_market_data_storage import (
    DailyMarketDataSnapshotPlanningError,
    DailyMarketDataSnapshotProvenanceInput,
    plan_daily_market_data_snapshot,
)
from research_sdk.daily_market_data_storage.planning import (
    PARSER_VERSION,
    PROVENANCE_POLICY_VERSION,
)


def test_planner_builds_happy_path_synthetic_snapshot_plan() -> None:
    plan = sample_plan()

    assert plan.snapshot_id == SNAPSHOT_ID
    assert plan.manifest.content_hash == S3A_GOLDEN_CONTENT_HASH
    assert plan.as_file_map()["bars.jsonl"] == CANONICAL_BARS_BYTES
    assert plan.bundle_manifest.files[0].sha256 == BARS_STORAGE_HASH
    assert tuple(plan.as_file_map()) == (
        "bars.jsonl",
        "expected-sessions.json",
        "policy.json",
        "provenance.json",
        "quality-report.json",
        "snapshot-manifest.json",
        "bundle-manifest.json",
    )


def test_planner_owns_parser_and_provenance_policy_versions() -> None:
    field_names = {
        field.name for field in fields(DailyMarketDataSnapshotProvenanceInput)
    }
    plan = sample_plan()
    provenance = plan.as_file_map()["provenance.json"].decode()

    assert "parser_version" not in field_names
    assert "provenance_policy_version" not in field_names
    assert f'"parser_version":"{PARSER_VERSION}"' in provenance
    assert f'"provenance_policy_version":"{PROVENANCE_POLICY_VERSION}"' in provenance
    assert plan.provenance_hash == PROVENANCE_HASH
    assert plan.snapshot_id == SNAPSHOT_ID


def test_planner_derives_manifest_fields_and_s3a_compatibility() -> None:
    plan = sample_plan()
    manifest = plan.manifest

    assert manifest.snapshot_kind is DataSnapshotKind.MARKET_DATA
    assert manifest.status is DataSnapshotStatus.COMPLETED
    assert manifest.asset_universe.symbols == ("QQQ",)
    assert manifest.asset_universe.universe_id == (
        "daily-market-data-single-instrument-v1:instrument-us-etf-qqq-xnas"
    )
    assert manifest.time_range.start_date == date(2026, 1, 2)
    assert manifest.time_range.end_date == date(2026, 1, 5)
    assert manifest.row_count == 2
    assert manifest.file_count == 1
    assert manifest.size_bytes == len(CANONICAL_BARS_BYTES)
    assert manifest.data_root_uri == f"daily-market-data/{SNAPSHOT_ID}"
    assert manifest.currency == "USD"
    assert manifest.hash_algorithm is HashAlgorithm.SHA256
    validate_daily_market_data_snapshot_manifest(
        manifest=manifest,
        policy=sample_policy(),
        quality_report=plan.quality_report,
    )


@pytest.mark.parametrize(
    "source",
    [
        (
            b'{"session_date":"2026-01-02","open":"100","high":"101",'
            b'"low":"99","close":"100.5","volume":1000}\n'
        ),
        source_bytes()
        + (
            b'{"session_date":"2026-01-02","open":"100.1","high":"101",'
            b'"low":"99","close":"100.5","volume":1000}\n'
        ),
        (
            b'{"session_date":"2026-01-02","open":"100","high":"101",'
            b'"low":"99","close":"100.5","volume":0}\n'
            b'{"session_date":"2026-01-05","open":"101","high":"102",'
            b'"low":"100","close":"101.5","volume":1100}\n'
        ),
    ],
)
def test_quality_fail_prevents_snapshot_planning(source: bytes) -> None:
    with pytest.raises(DailyMarketDataSnapshotPlanningError, match="quality"):
        sample_plan(source_bytes=source)


@pytest.mark.parametrize(
    "status",
    [
        CorporateActionEvidenceStatus.CHECKED_NO_EVENTS,
        CorporateActionEvidenceStatus.EVENTS_PRESENT_UNSUPPORTED,
    ],
)
def test_checked_corporate_action_claims_cannot_be_planned_by_s3b1(
    status: CorporateActionEvidenceStatus,
) -> None:
    with pytest.raises(DailyMarketDataSnapshotPlanningError, match="future dedicated"):
        sample_plan(
            provenance_input=sample_provenance_input(
                corporate_action_evidence_status=status,
            )
        )


def test_not_integrated_corporate_action_status_plans_successfully() -> None:
    assert (
        sample_plan(
            provenance_input=sample_provenance_input(
                corporate_action_evidence_status=(
                    CorporateActionEvidenceStatus.NOT_INTEGRATED
                ),
            )
        ).snapshot_id
        == SNAPSHOT_ID
    )


def test_expected_session_calendar_and_timezone_must_match_policy() -> None:
    with pytest.raises(DailyMarketDataSnapshotPlanningError, match="calendar"):
        sample_plan(expected_sessions=sample_expected_sessions(calendar="XNAS"))
    with pytest.raises(DailyMarketDataSnapshotPlanningError, match="timezone"):
        sample_plan(expected_sessions=sample_expected_sessions(timezone="UTC"))


def test_quality_end_date_must_not_exceed_provenance_as_of_date() -> None:
    with pytest.raises(DailyMarketDataSnapshotPlanningError, match="as_of"):
        sample_plan(
            provenance_input=sample_provenance_input(
                as_of=datetime(2026, 1, 4, 0, 0, tzinfo=UTC)
            )
        )


def test_source_hash_and_size_are_derived_from_exact_source_bytes() -> None:
    plan = sample_plan()

    assert plan.manifest.size_bytes == len(plan.as_file_map()["bars.jsonl"])
    assert plan.provenance_hash
    assert '"source_content_hash":"' in plan.as_file_map()["provenance.json"].decode()
    assert (
        f'"source_size_bytes":{len(source_bytes())}'
        in plan.as_file_map()["provenance.json"].decode()
    )


def test_repeated_identical_planning_is_byte_identical() -> None:
    assert sample_plan().as_file_map() == sample_plan().as_file_map()


def test_snapshot_planner_rejects_non_bytes_source() -> None:
    with pytest.raises(DailyMarketDataSnapshotPlanningError, match="source_bytes"):
        plan_daily_market_data_snapshot(
            source_bytes="not bytes",  # type: ignore[arg-type]
            instrument=sample_instrument(),
            policy=sample_policy(),
            expected_sessions=sample_expected_sessions(),
            provenance_input=sample_provenance_input(),
        )


def test_planner_does_not_accept_caller_manifest_or_snapshot_id_inputs() -> None:
    params = plan_daily_market_data_snapshot.__annotations__

    assert "snapshot_id" not in params
    assert "manifest" not in params
    assert "quality_report" not in params
    assert "content_hash" not in params
