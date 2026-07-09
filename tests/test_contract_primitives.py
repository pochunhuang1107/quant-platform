from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

import research_sdk
import research_sdk.contracts as contracts
from research_sdk.contracts import (
    RESEARCH_SDK_CONTRACT_SCHEMA_VERSION,
    AssetClass,
    BaseContractModel,
    ReviewMetadata,
    ReviewRole,
    ReviewStatus,
    SchemaVersion,
    UtcDatetime,
    ensure_utc_datetime,
)


def test_research_sdk_imports() -> None:
    assert research_sdk.__all__ == []


def test_contracts_exports_primitives() -> None:
    assert contracts.BaseContractModel is BaseContractModel
    assert contracts.AssetClass is AssetClass
    assert contracts.ReviewMetadata is ReviewMetadata
    assert contracts.RESEARCH_SDK_CONTRACT_SCHEMA_VERSION == "1.0.0"


def test_asset_class_contains_documented_values() -> None:
    assert {asset_class.value for asset_class in AssetClass} == {
        "equities",
        "etfs",
        "futures",
        "fx",
        "crypto",
        "indices",
        "options",
        "mixed",
    }


def test_review_status_contains_documented_values() -> None:
    assert {status.value for status in ReviewStatus} == {
        "pending",
        "approved",
        "rejected",
        "changes_requested",
    }


def test_review_role_contains_documented_values() -> None:
    assert {role.value for role in ReviewRole} == {
        "human_owner",
        "risk_reviewer",
        "agent_reviewer",
    }


def test_base_contract_model_rejects_unknown_fields() -> None:
    class ExampleContract(BaseContractModel):
        name: str

    with pytest.raises(ValidationError):
        ExampleContract(name="example", unexpected=True)


def test_schema_version_accepts_semantic_version() -> None:
    assert RESEARCH_SDK_CONTRACT_SCHEMA_VERSION == "1.0.0"
    assert TypeAdapter(SchemaVersion).validate_python("1.0.0") == "1.0.0"


@pytest.mark.parametrize("schema_version", ["1", "1.0", "v1.0.0", "1.0.0.0"])
def test_schema_version_rejects_malformed_values(schema_version: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(SchemaVersion).validate_python(schema_version)


def test_ensure_utc_datetime_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ensure_utc_datetime(datetime(2026, 1, 1, 12, 0, 0))


def test_ensure_utc_datetime_accepts_utc_aware_datetimes() -> None:
    timestamp = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    assert ensure_utc_datetime(timestamp) == timestamp


def test_ensure_utc_datetime_converts_non_utc_aware_datetimes() -> None:
    pacific = timezone(timedelta(hours=-8))
    timestamp = datetime(2026, 1, 1, 4, 0, 0, tzinfo=pacific)

    assert ensure_utc_datetime(timestamp) == datetime(
        2026,
        1,
        1,
        12,
        0,
        0,
        tzinfo=UTC,
    )


def test_utc_datetime_annotation_validates_pydantic_fields() -> None:
    class TimestampedContract(BaseModel):
        timestamp: UtcDatetime

    model = TimestampedContract(
        timestamp=datetime(2026, 1, 1, 4, 0, 0, tzinfo=timezone(timedelta(hours=-8)))
    )

    assert model.timestamp == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def test_review_metadata_validates_utc_fields_and_enum_values() -> None:
    review = ReviewMetadata(
        review_status="pending",
        reviewer_id="agent-1",
        review_role="agent_reviewer",
        reviewed_at=datetime(
            2026,
            1,
            1,
            4,
            0,
            0,
            tzinfo=timezone(timedelta(hours=-8)),
        ),
        approval_expires_at=datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC),
        risk_approval_required=True,
    )

    assert review.review_status is ReviewStatus.PENDING
    assert review.review_role is ReviewRole.AGENT_REVIEWER
    assert review.reviewed_at == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def test_review_metadata_requires_risk_approval_required() -> None:
    with pytest.raises(ValidationError):
        ReviewMetadata(review_status="pending")


def test_review_metadata_rejects_empty_reviewer_id() -> None:
    with pytest.raises(ValidationError):
        ReviewMetadata(
            review_status="pending",
            reviewer_id=" ",
            risk_approval_required=True,
        )


def test_review_metadata_does_not_implement_approval_authority() -> None:
    review = ReviewMetadata(
        review_status="approved",
        reviewer_id="agent-1",
        review_role="agent_reviewer",
        risk_approval_required=True,
    )

    assert not hasattr(review, "approve")
    assert "approval_authority" not in type(review).model_fields
