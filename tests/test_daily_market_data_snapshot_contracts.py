from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from helpers_daily_market_data_snapshots import (
    BARS_STORAGE_HASH,
    POLICY_HASH,
    PROVENANCE_HASH,
    SNAPSHOT_ID,
    sample_expected_sessions,
    sample_plan,
    sample_provenance_input,
    source_bytes,
)
from research_sdk.contracts.daily_market_data_snapshots import (
    CORPORATE_ACTION_NOT_INTEGRATED_LIMITATION,
    CorporateActionEvidenceStatus,
    DailyMarketDataSnapshotBundleManifest,
    DailyMarketDataSnapshotFileEntry,
    DailyMarketDataSnapshotFileRole,
    DailyMarketDataSnapshotProvenance,
)
from research_sdk.contracts.enums import DataSourceType, TemporalCoverage
from research_sdk.daily_market_data_storage.planning import (
    PARSER_VERSION,
    PROVENANCE_POLICY_VERSION,
)


def test_expected_sessions_accepts_sorted_unique_dates() -> None:
    expected = sample_expected_sessions()

    assert expected.session_dates == (date(2026, 1, 2), date(2026, 1, 5))


def test_expected_sessions_rejects_empty_duplicate_and_nonascending_dates() -> None:
    with pytest.raises(ValidationError):
        sample_expected_sessions(session_dates=())
    with pytest.raises(ValidationError, match="duplicates"):
        sample_expected_sessions(session_dates=(date(2026, 1, 2), date(2026, 1, 2)))
    with pytest.raises(ValidationError, match="strictly ascending"):
        sample_expected_sessions(session_dates=(date(2026, 1, 5), date(2026, 1, 2)))


@pytest.mark.parametrize(
    "session_dates",
    [
        (datetime(2026, 1, 2, 0, 0, tzinfo=UTC),),
        (True,),
        (object(),),
    ],
)
def test_expected_sessions_rejects_non_date_values(
    session_dates: tuple[object, ...],
) -> None:
    with pytest.raises(ValidationError):
        sample_expected_sessions(session_dates=session_dates)


@pytest.mark.parametrize(
    "field_name",
    ["session_source_id", "session_source_version", "calendar", "timezone"],
)
def test_expected_sessions_rejects_blank_authority_fields(field_name: str) -> None:
    with pytest.raises(ValidationError):
        sample_expected_sessions(**{field_name: " "})


def test_provenance_accepts_valid_synthetic_not_integrated_fixture() -> None:
    plan = sample_plan()

    assert plan.manifest.source_type is DataSourceType.RESEARCH_GENERATED
    assert plan.manifest.temporal_coverage.value == "not_applicable"
    assert plan.manifest.currency == "USD"
    assert plan.provenance_hash == PROVENANCE_HASH


@pytest.mark.parametrize(
    "temporal_coverage",
    [
        TemporalCoverage.NOT_APPLICABLE,
        TemporalCoverage.POINT_IN_TIME,
        TemporalCoverage.FIRST_AVAILABLE,
        TemporalCoverage.LATEST_KNOWN,
    ],
)
def test_provenance_accepts_non_mixed_temporal_coverage(
    temporal_coverage: TemporalCoverage,
) -> None:
    assert _build_provenance(temporal_coverage=temporal_coverage).temporal_coverage is (
        temporal_coverage
    )


def test_provenance_rejects_mixed_temporal_coverage() -> None:
    with pytest.raises(ValidationError, match="mixed temporal coverage"):
        _build_provenance(temporal_coverage=TemporalCoverage.MIXED)


def test_provenance_rejects_vendor_without_vendor_name() -> None:
    with pytest.raises(ValidationError, match="vendor_name"):
        _build_provenance(source_type=DataSourceType.VENDOR)


def test_provenance_rejects_chronology_violations() -> None:
    with pytest.raises(ValidationError, match="source_observed_at"):
        _build_provenance(source_observed_at=datetime(2026, 1, 7, 0, 0, tzinfo=UTC))
    with pytest.raises(ValidationError, match="ingestion_completed_at"):
        _build_provenance(ingestion_completed_at=datetime(2026, 1, 7, 0, 0, tzinfo=UTC))
    with pytest.raises(ValidationError, match="available_at"):
        _build_provenance(available_at=datetime(2026, 1, 7, 0, 0, tzinfo=UTC))
    with pytest.raises(ValidationError, match="as_of"):
        _build_provenance(as_of=datetime(2026, 1, 7, 0, 0, tzinfo=UTC))


def test_provenance_rejects_bad_source_integrity_and_reference_facts() -> None:
    with pytest.raises(ValidationError, match="sha256"):
        _build_provenance(source_content_hash="sha256:short")
    with pytest.raises(ValidationError):
        _build_provenance(source_size_bytes=-1)
    with pytest.raises(ValidationError):
        _build_provenance(parser_version=" ")
    with pytest.raises(ValidationError, match="userinfo"):
        _build_provenance(source_reference="https://user:secret@example.com/data")


def test_not_integrated_corporate_actions_require_limitation_and_no_source() -> None:
    with pytest.raises(ValidationError, match="known limitation"):
        _build_provenance(known_limitations=("synthetic infrastructure fixture only",))
    with pytest.raises(ValidationError, match="must not include"):
        _build_provenance(corporate_action_source_reference="fixture/actions.json")


def test_checked_corporate_action_states_require_coherent_evidence() -> None:
    with pytest.raises(ValidationError, match="requires"):
        _build_provenance(
            corporate_action_evidence_status=(
                CorporateActionEvidenceStatus.CHECKED_NO_EVENTS
            )
        )
    checked = _build_provenance(
        corporate_action_evidence_status=(
            CorporateActionEvidenceStatus.CHECKED_NO_EVENTS
        ),
        corporate_action_source_reference="fixture/actions.json",
        corporate_action_source_content_hash=f"sha256:{'2' * 64}",
        corporate_action_source_size_bytes=2,
        corporate_action_event_count=0,
    )
    assert checked.corporate_action_event_count == 0
    with pytest.raises(ValidationError, match="event count > 0"):
        _build_provenance(
            corporate_action_evidence_status=(
                CorporateActionEvidenceStatus.EVENTS_PRESENT_UNSUPPORTED
            ),
            corporate_action_source_reference="fixture/actions.json",
            corporate_action_source_content_hash=f"sha256:{'2' * 64}",
            corporate_action_source_size_bytes=2,
            corporate_action_event_count=0,
        )


def test_bundle_manifest_accepts_planned_exact_file_set() -> None:
    bundle = sample_plan().bundle_manifest

    assert bundle.snapshot_id == SNAPSHOT_ID
    assert bundle.policy_hash == POLICY_HASH
    assert tuple(file.relative_path for file in bundle.files) == (
        "bars.jsonl",
        "expected-sessions.json",
        "policy.json",
        "provenance.json",
        "quality-report.json",
        "snapshot-manifest.json",
    )
    assert bundle.files[0].sha256 == BARS_STORAGE_HASH


def test_bundle_manifest_rejects_path_and_role_contradictions() -> None:
    valid = sample_plan().bundle_manifest
    with pytest.raises(ValidationError, match="role order"):
        DailyMarketDataSnapshotBundleManifest(
            **{
                **valid.model_dump(mode="python"),
                "files": tuple(reversed(valid.files)),
            }
        )
    with pytest.raises(ValidationError):
        DailyMarketDataSnapshotFileEntry(
            relative_path="../bars.jsonl",
            role=DailyMarketDataSnapshotFileRole.BARS,
            media_type="application/x-ndjson",
            sha256=f"sha256:{'1' * 64}",
            size_bytes=1,
            row_count=1,
        )
    with pytest.raises(ValidationError):
        DailyMarketDataSnapshotFileEntry(
            relative_path="bundle-manifest.json",
            role=DailyMarketDataSnapshotFileRole.BARS,
            media_type="application/x-ndjson",
            sha256=f"sha256:{'1' * 64}",
            size_bytes=1,
            row_count=1,
        )


def _build_provenance(**overrides: object) -> DailyMarketDataSnapshotProvenance:
    data = sample_provenance_input().__dict__ | {
        "schema_version": "1.0.0",
        "provenance_policy_version": PROVENANCE_POLICY_VERSION,
        "parser_version": PARSER_VERSION,
        "source_content_hash": f"sha256:{'1' * 64}",
        "source_size_bytes": len(source_bytes()),
    }
    data.update(overrides)
    return DailyMarketDataSnapshotProvenance(**data)


def test_corporate_action_limitation_constant_is_precise() -> None:
    assert (
        CORPORATE_ACTION_NOT_INTEGRATED_LIMITATION
        == "corporate-action/distribution evidence is not integrated"
    )
