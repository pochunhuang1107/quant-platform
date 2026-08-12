from __future__ import annotations

from datetime import UTC, datetime

import pytest

from helpers_daily_market_data_snapshots import (
    EXPECTED_SESSIONS_HASH,
    POLICY_HASH,
    S3A_GOLDEN_CONTENT_HASH,
)
from helpers_daily_market_data_snapshots_v2 import (
    BAR_PROVENANCE_HASH_V2,
    CORPORATE_ACTION_EVIDENCE_AUTHORITY_HASH,
    CORPORATE_ACTION_SEMANTIC_HASH,
    SNAPSHOT_ID_V2,
    cash_distribution_v2,
    sample_bar_provenance_input_v2,
    sample_corporate_action_evidence_v2,
    sample_plan_v2,
)
from research_sdk.daily_market_data import (
    derive_daily_market_data_corporate_action_evidence_content_hash,
)
from research_sdk.daily_market_data.snapshot_identity_v2 import (
    BAR_SOURCE_PROVENANCE_HASH_VERSION,
    CORPORATE_ACTION_EVIDENCE_AUTHORITY_HASH_VERSION,
    SNAPSHOT_IDENTITY_VERSION_V2,
    DailyMarketDataSnapshotIdentityV2Error,
    derive_daily_market_data_bar_source_provenance_hash_v2,
    derive_daily_market_data_corporate_action_evidence_authority_hash,
    derive_daily_market_data_snapshot_id_v2,
)


def test_snapshot_v2_identity_and_component_hashes_match_goldens() -> None:
    plan = sample_plan_v2()

    assert BAR_SOURCE_PROVENANCE_HASH_VERSION == (
        "daily-market-data-bar-source-provenance-hash-v1"
    )
    assert CORPORATE_ACTION_EVIDENCE_AUTHORITY_HASH_VERSION == (
        "daily-market-data-corporate-action-evidence-authority-v1"
    )
    assert SNAPSHOT_IDENTITY_VERSION_V2 == "daily-market-data-snapshot-v2"
    assert plan.manifest.content_hash == S3A_GOLDEN_CONTENT_HASH
    assert plan.policy_hash == POLICY_HASH
    assert plan.expected_sessions_hash == EXPECTED_SESSIONS_HASH
    assert plan.bar_provenance_hash == BAR_PROVENANCE_HASH_V2
    assert plan.corporate_action_semantic_hash == CORPORATE_ACTION_SEMANTIC_HASH
    assert plan.corporate_action_evidence_authority_hash == (
        CORPORATE_ACTION_EVIDENCE_AUTHORITY_HASH
    )
    assert plan.snapshot_id == SNAPSHOT_ID_V2


def test_v2_identity_rejects_malformed_hashes_and_uses_v2_prefix() -> None:
    with pytest.raises(DailyMarketDataSnapshotIdentityV2Error, match="policy_hash"):
        derive_daily_market_data_snapshot_id_v2(
            semantic_content_hash=S3A_GOLDEN_CONTENT_HASH,
            policy_hash="sha256:not-a-hash",
            expected_sessions_hash=EXPECTED_SESSIONS_HASH,
            bar_provenance_hash=BAR_PROVENANCE_HASH_V2,
            corporate_action_semantic_hash=CORPORATE_ACTION_SEMANTIC_HASH,
            corporate_action_evidence_authority_hash=(
                CORPORATE_ACTION_EVIDENCE_AUTHORITY_HASH
            ),
        )

    assert sample_plan_v2().snapshot_id.startswith("daily-market-data-snapshot-v2-")
    assert sample_plan_v2().snapshot_id == sample_plan_v2().snapshot_id.lower()


@pytest.mark.parametrize(
    "field_name",
    [
        "semantic_content_hash",
        "policy_hash",
        "expected_sessions_hash",
        "bar_provenance_hash",
        "corporate_action_semantic_hash",
        "corporate_action_evidence_authority_hash",
    ],
)
def test_each_v2_identity_component_changes_snapshot_id(field_name: str) -> None:
    inputs = {
        "semantic_content_hash": S3A_GOLDEN_CONTENT_HASH,
        "policy_hash": POLICY_HASH,
        "expected_sessions_hash": EXPECTED_SESSIONS_HASH,
        "bar_provenance_hash": BAR_PROVENANCE_HASH_V2,
        "corporate_action_semantic_hash": CORPORATE_ACTION_SEMANTIC_HASH,
        "corporate_action_evidence_authority_hash": (
            CORPORATE_ACTION_EVIDENCE_AUTHORITY_HASH
        ),
    }
    inputs[field_name] = f"sha256:{'0' * 64}"

    assert derive_daily_market_data_snapshot_id_v2(**inputs) != SNAPSHOT_ID_V2


def test_same_economics_different_source_reference_changes_authority_and_v2_id() -> (
    None
):
    original = sample_corporate_action_evidence_v2()
    changed = sample_corporate_action_evidence_v2(
        source_reference="fixtures/corporate-actions/different-source.json"
    )

    assert derive_daily_market_data_corporate_action_evidence_content_hash(
        original
    ) == derive_daily_market_data_corporate_action_evidence_content_hash(changed)
    assert derive_daily_market_data_corporate_action_evidence_authority_hash(
        original
    ) != derive_daily_market_data_corporate_action_evidence_authority_hash(changed)
    assert (
        sample_plan_v2(corporate_action_evidence=changed).snapshot_id
        != sample_plan_v2().snapshot_id
    )


def test_same_economics_different_event_availability_changes_authority_and_v2_id() -> (
    None
):
    original = sample_corporate_action_evidence_v2()
    changed = sample_corporate_action_evidence_v2(
        events=(
            cash_distribution_v2(
                source_available_at=datetime(2026, 1, 1, 17, 0, tzinfo=UTC)
            ),
            original.events[1],
        )
    )

    assert derive_daily_market_data_corporate_action_evidence_content_hash(
        original
    ) == derive_daily_market_data_corporate_action_evidence_content_hash(changed)
    assert derive_daily_market_data_corporate_action_evidence_authority_hash(
        original
    ) != derive_daily_market_data_corporate_action_evidence_authority_hash(changed)
    assert (
        sample_plan_v2(corporate_action_evidence=changed).snapshot_id
        != sample_plan_v2().snapshot_id
    )


@pytest.mark.parametrize(
    "override",
    [
        {"source_version": "2026-01-synthetic-actions-v2"},
        {"source_content_hash": f"sha256:{'b' * 64}"},
        {"source_observed_at": datetime(2026, 1, 5, 23, 51, tzinfo=UTC)},
        {"available_at": datetime(2026, 1, 5, 23, 59, tzinfo=UTC)},
        {"created_at": datetime(2026, 1, 6, 0, 1, tzinfo=UTC)},
    ],
)
def test_same_economics_different_evidence_vintage_changes_v2_id(
    override: dict[str, object],
) -> None:
    changed = sample_corporate_action_evidence_v2(**override)

    assert (
        derive_daily_market_data_corporate_action_evidence_content_hash(changed)
        == CORPORATE_ACTION_SEMANTIC_HASH
    )
    assert (
        derive_daily_market_data_corporate_action_evidence_authority_hash(changed)
        != CORPORATE_ACTION_EVIDENCE_AUTHORITY_HASH
    )
    assert (
        sample_plan_v2(corporate_action_evidence=changed).snapshot_id != SNAPSHOT_ID_V2
    )


def test_bar_provenance_hash_binds_complete_bar_source_contract() -> None:
    plan = sample_plan_v2()
    changed = plan.bar_provenance.model_copy(update={"source_version": "v2"})

    assert derive_daily_market_data_bar_source_provenance_hash_v2(changed) != (
        BAR_PROVENANCE_HASH_V2
    )
    assert (
        sample_plan_v2(
            bar_provenance_input=sample_bar_provenance_input_v2(source_version="v2")
        ).snapshot_id
        != SNAPSHOT_ID_V2
    )
