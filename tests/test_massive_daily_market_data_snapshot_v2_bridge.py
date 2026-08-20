from __future__ import annotations

import inspect
import json
from dataclasses import fields, replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from helpers_daily_market_data_snapshots import sample_policy
from research_sdk.contracts.daily_market_data import DailyMarketDataInstrument
from research_sdk.contracts.daily_market_data_snapshots import (
    DailyMarketDataExpectedSessions,
)
from research_sdk.contracts.enums import (
    DataAdjustmentPolicy,
    DataSourceType,
    TemporalCoverage,
)
from research_sdk.daily_market_data_adapters import (
    AdaptedMassiveDailyMarketData,
    MassiveDailyMarketDataAdapterContext,
    MassiveDailyMarketDataCapturePairCompatibilityError,
    MassiveDailyMarketDataSnapshotBridgeContext,
    MassiveDailyMarketDataSnapshotBridgeError,
    adapt_massive_daily_market_data_source_capture,
    plan_massive_daily_market_data_snapshot_v2,
    validate_massive_daily_market_data_capture_pair_compatibility,
)
from research_sdk.daily_market_data_adapters.massive import (
    MASSIVE_BAR_ENDPOINT_FAMILY,
    MASSIVE_BAR_ENDPOINT_VERSION,
    MASSIVE_DAILY_MARKET_DATA_ADAPTER_VERSION,
    MASSIVE_DIVIDEND_ENDPOINT_FAMILY,
    MASSIVE_DIVIDEND_ENDPOINT_VERSION,
    MASSIVE_PROVIDER,
    MASSIVE_SOURCE_FAMILY,
    MASSIVE_SPLIT_ENDPOINT_FAMILY,
    MASSIVE_SPLIT_ENDPOINT_VERSION,
)
from research_sdk.daily_market_data_source_capture.models import (
    SOURCE_CAPTURE_MEMBER_PATHS,
    DailyMarketDataSourceCaptureMemberInput,
    DailyMarketDataSourceCaptureRequestParameter,
    DailyMarketDataSourceCaptureRole,
)
from research_sdk.daily_market_data_source_capture.planning import (
    plan_daily_market_data_source_capture,
)
from research_sdk.daily_market_data_source_capture.verification import (
    verify_daily_market_data_source_capture,
)
from research_sdk.daily_market_data_storage import (
    DailyMarketDataSnapshotPlanningV2Error,
    DailyMarketDataSnapshotPlanV2,
    render_canonical_daily_bars,
    verify_daily_market_data_snapshot_bundle_v2,
)
from research_sdk.daily_market_data_storage.serialization import sha256_bytes

ASSET_OBSERVED_AT = datetime(2026, 8, 14, 16, 0, tzinfo=UTC)
BENCHMARK_OBSERVED_AT = datetime(2026, 9, 14, 16, 2, tzinfo=UTC)
ACQUISITION_BATCH_ID = "synthetic-s3c3c3-compatible-batch"
ROLE_ORDER = (
    DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
    DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
    DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
)


def test_bridge_maps_exact_massive_authority_into_verified_snapshot_v2() -> None:
    adapted = adapted_capture(symbol="QQQ", observed_at=ASSET_OBSERVED_AT)
    context = bridge_context()

    plan = bridge_plan(adapted, context=context)

    assert isinstance(plan, DailyMarketDataSnapshotPlanV2)
    assert plan.as_file_map()["bars.jsonl"] == render_canonical_daily_bars(adapted.bars)
    raw_bars = adapted.source_capture.member_bytes[
        DailyMarketDataSourceCaptureRole.BAR_RESPONSE
    ]
    assert plan.as_file_map()["bars.jsonl"] != raw_bars
    assert plan.bar_provenance.source_content_hash == sha256_bytes(raw_bars)
    assert plan.bar_provenance.source_size_bytes == len(raw_bars)
    assert plan.bar_provenance.parser_version == adapted.parser_version
    assert plan.bar_provenance.temporal_coverage is TemporalCoverage.LATEST_KNOWN
    assert plan.bar_provenance.as_of == ASSET_OBSERVED_AT
    assert plan.bar_provenance.source_observed_at == ASSET_OBSERVED_AT
    assert plan.bar_provenance.source_version == adapted.capture_id
    assert plan.bar_provenance.source_dataset == MASSIVE_SOURCE_FAMILY
    assert plan.bar_provenance.source_type is DataSourceType.VENDOR
    assert plan.bar_provenance.vendor_name == MASSIVE_PROVIDER
    assert plan.bar_provenance.source_instrument_reference == "QQQ"
    assert plan.bar_provenance.currency == "USD"
    assert plan.bar_provenance.created_at == context.created_at
    assert plan.bar_provenance.created_by == context.created_by
    assert plan.bar_provenance.ingestion_completed_at == (
        context.ingestion_completed_at
    )
    assert plan.bar_provenance.available_at == context.available_at
    assert plan.bar_provenance.license_notes == context.license_notes

    verified = verify_daily_market_data_snapshot_bundle_v2(plan.as_file_map())
    assert verified.snapshot_id == plan.snapshot_id
    assert verified.bar_provenance == plan.bar_provenance
    assert verified.corporate_action_evidence == plan.corporate_action_evidence


@pytest.mark.parametrize(
    "variant",
    ("no-final-newline", "crlf-whitespace", "top-level-field-order"),
)
def test_bridge_preserves_adapter_valid_raw_bar_byte_distinctions(
    variant: str,
) -> None:
    responses = source_responses(symbol="QQQ", response_marker="raw-variant")
    original_bytes = responses[DailyMarketDataSourceCaptureRole.BAR_RESPONSE]
    changed_bytes = raw_bar_variant(original_bytes, variant=variant)
    original = adapted_capture(
        symbol="QQQ",
        observed_at=ASSET_OBSERVED_AT,
        response_marker="raw-variant",
        response_overrides={
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE: original_bytes
        },
    )
    changed = adapted_capture(
        symbol="QQQ",
        observed_at=ASSET_OBSERVED_AT,
        response_marker="raw-variant",
        response_overrides={
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE: changed_bytes
        },
    )

    original_plan = bridge_plan(original)
    changed_plan = bridge_plan(changed)

    assert original.bars == changed.bars
    assert (
        original_plan.as_file_map()["bars.jsonl"]
        == (changed_plan.as_file_map()["bars.jsonl"])
    )
    assert original_plan.bar_provenance.source_content_hash == sha256_bytes(
        original_bytes
    )
    assert changed_plan.bar_provenance.source_content_hash == sha256_bytes(
        changed_bytes
    )
    assert (
        original_plan.bar_provenance.source_content_hash
        != changed_plan.bar_provenance.source_content_hash
    )
    assert original_plan.bar_provenance.source_size_bytes == len(original_bytes)
    assert changed_plan.bar_provenance.source_size_bytes == len(changed_bytes)


def test_bridge_binds_ca_evidence_to_exact_ca_source_manifest() -> None:
    adapted = adapted_capture(symbol="QQQ", observed_at=ASSET_OBSERVED_AT)
    context = bridge_context()
    evidence = bridge_plan(adapted, context=context).corporate_action_evidence
    ca_bytes = adapted.source_capture.ca_source_manifest_bytes

    assert evidence.schema_version == "1.0.0"
    assert (
        evidence.evidence_policy_version
        == "daily-market-data-corporate-action-evidence-v1"
    )
    assert evidence.events == adapted.corporate_action_events
    assert evidence.completeness == adapted.corporate_action_completeness
    assert evidence.instrument == adapted.instrument
    assert evidence.coverage_start_date == (
        adapted.corporate_action_coverage_start_date
    )
    assert evidence.coverage_end_date == adapted.corporate_action_coverage_end_date
    assert evidence.source_content_hash == sha256_bytes(ca_bytes)
    assert evidence.source_size_bytes == len(ca_bytes)
    assert evidence.source_dataset == MASSIVE_SOURCE_FAMILY
    assert evidence.source_version == adapted.capture_id
    assert evidence.source_type is DataSourceType.VENDOR
    assert evidence.source_observed_at == ASSET_OBSERVED_AT
    assert evidence.ingestion_completed_at == context.ingestion_completed_at
    assert evidence.available_at == context.available_at
    assert evidence.created_at == context.created_at
    assert evidence.created_by == context.created_by
    assert evidence.canonicalization_version == adapted.parser_version
    assert evidence.vendor_name == MASSIVE_PROVIDER
    assert evidence.license_notes == context.license_notes
    assert tuple(event.source_available_at for event in evidence.events) == tuple(
        event.source_available_at for event in adapted.corporate_action_events
    )


@pytest.mark.parametrize(
    "role",
    (
        DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
        DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
    ),
)
def test_bridge_ca_authority_changes_for_each_exact_ca_member(
    role: DailyMarketDataSourceCaptureRole,
) -> None:
    responses = source_responses(symbol="QQQ", response_marker="ca-variant")
    changed_member_bytes = b"\r\n " + responses[role].rstrip(b"\n") + b"\r\n"
    original = adapted_capture(
        symbol="QQQ",
        observed_at=ASSET_OBSERVED_AT,
        response_marker="ca-variant",
        response_overrides=responses,
    )
    changed = adapted_capture(
        symbol="QQQ",
        observed_at=ASSET_OBSERVED_AT,
        response_marker="ca-variant",
        response_overrides={**responses, role: changed_member_bytes},
    )

    original_evidence = bridge_plan(original).corporate_action_evidence
    changed_evidence = bridge_plan(changed).corporate_action_evidence

    assert original.corporate_action_events == changed.corporate_action_events
    assert original_evidence.events == changed_evidence.events
    assert original.source_capture.ca_source_manifest_bytes != (
        changed.source_capture.ca_source_manifest_bytes
    )
    assert original_evidence.source_content_hash == sha256_bytes(
        original.source_capture.ca_source_manifest_bytes
    )
    assert changed_evidence.source_content_hash == sha256_bytes(
        changed.source_capture.ca_source_manifest_bytes
    )
    assert original_evidence.source_content_hash != changed_evidence.source_content_hash


def test_bridge_source_references_are_credential_free_capture_authority() -> None:
    adapted = adapted_capture(symbol="QQQ", observed_at=ASSET_OBSERVED_AT)

    plan = bridge_plan(adapted)

    expected_prefix = f"daily-market-data-source-capture://{adapted.capture_id}/"
    assert plan.bar_provenance.source_reference == expected_prefix + "bars.json"
    assert (
        plan.corporate_action_evidence.source_reference
        == expected_prefix + "ca-source-manifest.json"
    )
    for reference in (
        plan.bar_provenance.source_reference,
        plan.corporate_action_evidence.source_reference,
    ):
        assert "?" not in reference
        assert "api_key" not in reference.lower()
        assert "authorization" not in reference.lower()
        assert "bearer" not in reference.lower()


def test_bridge_exposes_no_caller_hash_or_size_authority() -> None:
    assert tuple(
        inspect.signature(plan_massive_daily_market_data_snapshot_v2).parameters
    ) == (
        "adapted",
        "policy",
        "expected_sessions",
        "context",
    )
    assert {
        field.name for field in fields(MassiveDailyMarketDataSnapshotBridgeContext)
    } == {
        "ingestion_completed_at",
        "available_at",
        "created_at",
        "created_by",
        "license_notes",
        "known_limitations",
    }


def test_bridge_uses_caller_expected_sessions_without_inference_or_repair() -> None:
    adapted = adapted_capture(symbol="QQQ", observed_at=ASSET_OBSERVED_AT)
    deliberately_incomplete = expected_sessions(session_dates=(date(2026, 1, 5),))

    with pytest.raises(
        DailyMarketDataSnapshotPlanningV2Error,
        match="quality must pass",
    ):
        plan_massive_daily_market_data_snapshot_v2(
            adapted=adapted,
            policy=sample_policy(),
            expected_sessions=deliberately_incomplete,
            context=bridge_context(),
        )


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    (
        (
            "ingestion_completed_at",
            datetime(2026, 8, 14, 15, 59, tzinfo=UTC),
            "capture_observed_at",
        ),
        (
            "ingestion_completed_at",
            datetime(2026, 8, 14, 18, 1, tzinfo=UTC),
            "ingestion_completed_at",
        ),
        (
            "available_at",
            datetime(2026, 8, 14, 19, 1, tzinfo=UTC),
            "available_at",
        ),
    ),
)
def test_bridge_rejects_invalid_chronology_without_reordering(
    field_name: str,
    value: datetime,
    message: str,
) -> None:
    adapted = adapted_capture(symbol="QQQ", observed_at=ASSET_OBSERVED_AT)
    context = bridge_context(**{field_name: value})

    with pytest.raises(MassiveDailyMarketDataSnapshotBridgeError, match=message):
        bridge_plan(adapted, context=context)


def test_bridge_accepts_equal_chronology_boundaries() -> None:
    adapted = adapted_capture(symbol="QQQ", observed_at=ASSET_OBSERVED_AT)
    context = bridge_context(
        ingestion_completed_at=ASSET_OBSERVED_AT,
        available_at=ASSET_OBSERVED_AT,
        created_at=ASSET_OBSERVED_AT,
    )

    plan = bridge_plan(adapted, context=context)

    assert plan.bar_provenance.source_observed_at == ASSET_OBSERVED_AT
    assert plan.bar_provenance.ingestion_completed_at == ASSET_OBSERVED_AT
    assert plan.bar_provenance.available_at == ASSET_OBSERVED_AT
    assert plan.bar_provenance.created_at == ASSET_OBSERVED_AT


def test_bridge_normalizes_timezone_equivalent_context_instants_once() -> None:
    adapted = adapted_capture(symbol="QQQ", observed_at=ASSET_OBSERVED_AT)
    pacific_offset = timezone(timedelta(hours=-7))
    context = bridge_context(
        ingestion_completed_at=datetime(2026, 8, 14, 10, 0, tzinfo=pacific_offset),
        available_at=datetime(2026, 8, 14, 11, 0, tzinfo=pacific_offset),
        created_at=datetime(2026, 8, 14, 12, 0, tzinfo=pacific_offset),
    )

    plan = bridge_plan(adapted, context=context)

    assert plan.bar_provenance.ingestion_completed_at == datetime(
        2026, 8, 14, 17, 0, tzinfo=UTC
    )
    assert plan.bar_provenance.available_at == datetime(2026, 8, 14, 18, 0, tzinfo=UTC)
    assert plan.bar_provenance.created_at == datetime(2026, 8, 14, 19, 0, tzinfo=UTC)


def test_bridge_reads_each_context_authority_once() -> None:
    class AlternatingContext(MassiveDailyMarketDataSnapshotBridgeContext):
        def __getattribute__(self, name: str) -> object:
            if name != "created_by":
                return super().__getattribute__(name)
            reads = super().__getattribute__("_created_by_reads")
            object.__setattr__(self, "_created_by_reads", reads + 1)
            if reads == 0:
                return "single captured creator"
            return "attacker-controlled later creator"

    base_context = bridge_context()
    context = AlternatingContext(
        **{
            field.name: getattr(base_context, field.name)
            for field in fields(MassiveDailyMarketDataSnapshotBridgeContext)
        }
    )
    object.__setattr__(context, "_created_by_reads", 0)
    adapted = adapted_capture(symbol="QQQ", observed_at=ASSET_OBSERVED_AT)

    plan = bridge_plan(adapted, context=context)

    assert context._created_by_reads == 1
    assert plan.bar_provenance.created_by == "single captured creator"
    assert plan.corporate_action_evidence.created_by == plan.bar_provenance.created_by


def test_bridge_reads_each_adapted_authority_once() -> None:
    class AlternatingAdapted(AdaptedMassiveDailyMarketData):
        def __getattribute__(self, name: str) -> object:
            if name != "parser_version":
                return super().__getattribute__(name)
            reads = super().__getattribute__("_parser_version_reads")
            object.__setattr__(self, "_parser_version_reads", reads + 1)
            if reads == 0:
                return MASSIVE_DAILY_MARKET_DATA_ADAPTER_VERSION
            return "attacker-controlled-later-parser"

    base_adapted = adapted_capture(symbol="QQQ", observed_at=ASSET_OBSERVED_AT)
    adapted = AlternatingAdapted(
        **{
            field.name: getattr(base_adapted, field.name)
            for field in fields(AdaptedMassiveDailyMarketData)
        }
    )
    object.__setattr__(adapted, "_parser_version_reads", 0)

    plan = bridge_plan(adapted)

    assert adapted._parser_version_reads == 1
    assert (
        plan.bar_provenance.parser_version == MASSIVE_DAILY_MARKET_DATA_ADAPTER_VERSION
    )
    assert (
        plan.corporate_action_evidence.canonicalization_version
        == plan.bar_provenance.parser_version
    )


def test_bridge_requires_real_license_notes() -> None:
    adapted = adapted_capture(symbol="QQQ", observed_at=ASSET_OBSERVED_AT)

    with pytest.raises(
        MassiveDailyMarketDataSnapshotBridgeError,
        match="license_notes must be a non-empty string",
    ):
        bridge_plan(adapted, context=bridge_context(license_notes="  "))


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("created_by", " creator"),
        ("license_notes", "notes "),
        ("known_limitations", (" limitation",)),
    ),
)
def test_bridge_rejects_context_strings_with_surrounding_whitespace(
    field_name: str,
    value: object,
) -> None:
    adapted = adapted_capture(symbol="QQQ", observed_at=ASSET_OBSERVED_AT)

    with pytest.raises(
        MassiveDailyMarketDataSnapshotBridgeError,
        match="without surrounding whitespace",
    ):
        bridge_plan(adapted, context=bridge_context(**{field_name: value}))


def test_bridge_rejects_datetime_subclasses() -> None:
    class DatetimeSubclass(datetime):
        pass

    adapted = adapted_capture(symbol="QQQ", observed_at=ASSET_OBSERVED_AT)
    created_at = DatetimeSubclass(2026, 8, 14, 19, 0, tzinfo=UTC)

    with pytest.raises(
        MassiveDailyMarketDataSnapshotBridgeError,
        match="created_at must be a timezone-aware datetime",
    ):
        bridge_plan(adapted, context=bridge_context(created_at=created_at))


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    (
        ("created_by", 7, "created_by must be a non-empty string"),
        ("known_limitations", ["not a tuple"], "must be a tuple"),
        (
            "ingestion_completed_at",
            datetime(2026, 8, 14, 17, 0),
            "must be a timezone-aware datetime",
        ),
    ),
)
def test_bridge_rejects_wrong_context_runtime_types(
    field_name: str,
    value: object,
    message: str,
) -> None:
    adapted = adapted_capture(symbol="QQQ", observed_at=ASSET_OBSERVED_AT)

    with pytest.raises(MassiveDailyMarketDataSnapshotBridgeError, match=message):
        bridge_plan(adapted, context=bridge_context(**{field_name: value}))


def test_bridge_rejects_policy_that_mislabels_raw_massive_bars() -> None:
    adapted = adapted_capture(symbol="QQQ", observed_at=ASSET_OBSERVED_AT)

    with pytest.raises(
        MassiveDailyMarketDataSnapshotBridgeError,
        match="requires a raw adjustment policy",
    ):
        plan_massive_daily_market_data_snapshot_v2(
            adapted=adapted,
            policy=sample_policy(adjustment_policy=DataAdjustmentPolicy.SPLIT_ADJUSTED),
            expected_sessions=expected_sessions(),
            context=bridge_context(),
        )


def test_bridge_rejects_non_latest_known_historical_adapter_output() -> None:
    adapted = replace(
        adapted_capture(symbol="QQQ", observed_at=ASSET_OBSERVED_AT),
        temporal_coverage=TemporalCoverage.POINT_IN_TIME,
    )

    with pytest.raises(
        MassiveDailyMarketDataSnapshotBridgeError,
        match="requires latest_known temporal coverage",
    ):
        bridge_plan(adapted)


@pytest.mark.parametrize(
    ("field_name", "message"),
    (
        ("provider", "Massive provider must be"),
        ("source_family", "Massive source_family must be"),
        ("instrument_symbol", "adapted instrument symbol must match"),
        ("capture_id", "must match capture_manifest.capture_id"),
        ("bar_range", "BAR_RESPONSE 'from' does not match"),
        ("ca_range", "DIVIDEND_RESPONSE 'ex_dividend_date.gte' does not match"),
        ("currency", "cash-distribution currency must match"),
    ),
)
def test_bridge_rejects_incoherent_publicly_constructible_adapted_values(
    field_name: str,
    message: str,
) -> None:
    adapted = mutate_bridge_authority(
        adapted_capture(symbol="QQQ", observed_at=ASSET_OBSERVED_AT),
        field_name=field_name,
    )

    with pytest.raises(MassiveDailyMarketDataSnapshotBridgeError, match=message):
        bridge_plan(adapted)


def test_bridge_fails_when_no_limitation_authority_exists() -> None:
    adapted = adapted_capture(
        symbol="QQQ",
        observed_at=ASSET_OBSERVED_AT,
        capture_limitations=(),
        member_limitations={role: () for role in ROLE_ORDER},
    )

    with pytest.raises(
        MassiveDailyMarketDataSnapshotBridgeError,
        match="bar provenance requires at least one known limitation",
    ):
        bridge_plan(adapted, context=bridge_context(known_limitations=()))


def test_bridge_merges_limitations_by_authority_in_stable_deduplicated_order() -> None:
    adapted = adapted_capture(symbol="QQQ", observed_at=ASSET_OBSERVED_AT)

    plan = bridge_plan(adapted)

    assert plan.bar_provenance.known_limitations == (
        "capture limitation",
        "shared limitation",
        "bar limitation",
        "context limitation",
        "context second limitation",
    )
    assert plan.corporate_action_evidence.known_limitations == (
        "capture limitation",
        "shared limitation",
        "dividend limitation",
        "split limitation",
        "context limitation",
        "context second limitation",
    )


def test_compatible_pair_allows_sequential_capture_timestamps_and_response_facts() -> (
    None
):
    asset = adapted_capture(
        symbol="QQQ",
        observed_at=ASSET_OBSERVED_AT,
        response_marker="asset",
    )
    benchmark = adapted_capture(
        symbol="SPY",
        observed_at=BENCHMARK_OBSERVED_AT,
        response_marker="benchmark-with-different-size",
        capture_limitations=("benchmark-only capture limitation",),
        member_limitations={
            role: (f"benchmark-only {role.value} limitation",) for role in ROLE_ORDER
        },
    )

    assert asset.source_capture.capture_manifest.capture_observed_at != (
        benchmark.source_capture.capture_manifest.capture_observed_at
    )
    assert asset.capture_id != benchmark.capture_id
    assert asset.source_capture.capture_manifest.limitations != (
        benchmark.source_capture.capture_manifest.limitations
    )
    assert tuple(event.event_id for event in asset.corporate_action_events) != tuple(
        event.event_id for event in benchmark.corporate_action_events
    )
    for role in ROLE_ORDER:
        asset_member = member_for_role(asset, role)
        benchmark_member = member_for_role(benchmark, role)
        assert asset_member.request_parameters != benchmark_member.request_parameters
        assert asset_member.sanitized_source_reference != (
            benchmark_member.sanitized_source_reference
        )
        assert asset_member.api_request_id != benchmark_member.api_request_id
        assert asset_member.content_sha256 != benchmark_member.content_sha256
        assert asset_member.size_bytes != benchmark_member.size_bytes
        assert asset_member.limitations != benchmark_member.limitations

    assert (
        validate_massive_daily_market_data_capture_pair_compatibility(
            asset=asset,
            benchmark=benchmark,
        )
        is None
    )


@pytest.mark.parametrize(
    ("asset_batch_id", "benchmark_batch_id", "message"),
    (
        (None, ACQUISITION_BATCH_ID, "both captures require acquisition_batch_id"),
        (
            ACQUISITION_BATCH_ID,
            "different-synthetic-batch",
            "acquisition_batch_id mismatch",
        ),
    ),
)
def test_pair_rejects_missing_or_different_acquisition_batch(
    asset_batch_id: str | None,
    benchmark_batch_id: str | None,
    message: str,
) -> None:
    asset = adapted_capture(
        symbol="QQQ",
        observed_at=ASSET_OBSERVED_AT,
        acquisition_batch_id=asset_batch_id,
    )
    benchmark = adapted_capture(
        symbol="SPY",
        observed_at=BENCHMARK_OBSERVED_AT,
        acquisition_batch_id=benchmark_batch_id,
    )

    with pytest.raises(
        MassiveDailyMarketDataCapturePairCompatibilityError,
        match=message,
    ):
        validate_massive_daily_market_data_capture_pair_compatibility(
            asset=asset,
            benchmark=benchmark,
        )


@pytest.mark.parametrize(
    ("role", "request_override"),
    (
        (DailyMarketDataSourceCaptureRole.BAR_RESPONSE, {"limit": "49999"}),
        (
            DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
            {"sort": "ex_dividend_date.desc"},
        ),
        (
            DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
            {"limit": "4999"},
        ),
    ),
)
def test_pair_rejects_role_acquisition_spec_mismatches(
    role: DailyMarketDataSourceCaptureRole,
    request_override: dict[str, str],
) -> None:
    asset, benchmark = compatible_pair(
        benchmark_request_overrides={role: request_override}
    )

    with pytest.raises(
        MassiveDailyMarketDataCapturePairCompatibilityError,
        match=rf"{role.value} request_parameters excluding ticker mismatch",
    ):
        validate_massive_daily_market_data_capture_pair_compatibility(
            asset=asset,
            benchmark=benchmark,
        )


def test_pair_rejects_bar_requested_date_range_mismatch() -> None:
    asset, benchmark = compatible_pair(
        benchmark_request_overrides={
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE: {"from": "2026-01-04"}
        }
    )

    with pytest.raises(
        MassiveDailyMarketDataCapturePairCompatibilityError,
        match="bar requested date range mismatch",
    ):
        validate_massive_daily_market_data_capture_pair_compatibility(
            asset=asset,
            benchmark=benchmark,
        )


def test_pair_rejects_corporate_action_coverage_mismatch() -> None:
    ca_overrides = {
        DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE: {
            "ex_dividend_date.gte": "2025-12-31"
        },
        DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE: {
            "execution_date.gte": "2025-12-31"
        },
    }
    asset, benchmark = compatible_pair(benchmark_request_overrides=ca_overrides)

    with pytest.raises(
        MassiveDailyMarketDataCapturePairCompatibilityError,
        match="corporate-action coverage date range mismatch",
    ):
        validate_massive_daily_market_data_capture_pair_compatibility(
            asset=asset,
            benchmark=benchmark,
        )


@pytest.mark.parametrize(
    ("field_name", "message"),
    (
        ("provider", "Massive provider must be"),
        ("source_family", "Massive source_family must be"),
        ("capture_format_version", "capture_manifest is invalid"),
        ("parser_version", "Massive parser_version must be"),
        ("temporal_coverage", "requires latest_known temporal coverage"),
        ("currency", "cash-distribution currency must match"),
        ("capture_id", "must match capture_manifest.capture_id"),
        ("instrument_id", "adapted instrument_id must match"),
        ("symbol", "adapted instrument symbol must match"),
    ),
)
def test_pair_rejects_incompatible_capture_and_adapter_facts(
    field_name: str,
    message: str,
) -> None:
    asset, benchmark = compatible_pair()
    benchmark = mutate_pair_fact(
        benchmark=benchmark,
        asset=asset,
        field_name=field_name,
    )

    with pytest.raises(
        MassiveDailyMarketDataCapturePairCompatibilityError,
        match=message,
    ):
        validate_massive_daily_market_data_capture_pair_compatibility(
            asset=asset,
            benchmark=benchmark,
        )


def test_pair_rejects_shared_non_massive_provider_authority() -> None:
    asset, benchmark = compatible_pair()
    asset = replace_manifest_fields(asset, provider="other-provider")
    benchmark = replace_manifest_fields(benchmark, provider="other-provider")

    with pytest.raises(
        MassiveDailyMarketDataCapturePairCompatibilityError,
        match="Massive provider must be",
    ):
        validate_massive_daily_market_data_capture_pair_compatibility(
            asset=asset,
            benchmark=benchmark,
        )


def test_pair_rejects_shared_non_massive_parser_authority() -> None:
    asset, benchmark = compatible_pair()
    asset = replace(asset, parser_version="shared-other-parser")
    benchmark = replace(benchmark, parser_version="shared-other-parser")

    with pytest.raises(
        MassiveDailyMarketDataCapturePairCompatibilityError,
        match="Massive parser_version must be",
    ):
        validate_massive_daily_market_data_capture_pair_compatibility(
            asset=asset,
            benchmark=benchmark,
        )


def test_pair_rejects_different_valid_adapter_currencies() -> None:
    asset = adapted_capture(symbol="QQQ", observed_at=ASSET_OBSERVED_AT)
    benchmark = adapted_capture(
        symbol="SPY",
        observed_at=BENCHMARK_OBSERVED_AT,
        currency="CAD",
    )

    with pytest.raises(
        MassiveDailyMarketDataCapturePairCompatibilityError,
        match="currency mismatch",
    ):
        validate_massive_daily_market_data_capture_pair_compatibility(
            asset=asset,
            benchmark=benchmark,
        )


def test_pair_requires_distinct_capture_ids() -> None:
    asset = adapted_capture(symbol="QQQ", observed_at=ASSET_OBSERVED_AT)

    with pytest.raises(
        MassiveDailyMarketDataCapturePairCompatibilityError,
        match="capture IDs must be distinct",
    ):
        validate_massive_daily_market_data_capture_pair_compatibility(
            asset=asset,
            benchmark=asset,
        )


def test_pair_requires_distinct_instrument_ids() -> None:
    asset = adapted_capture(symbol="QQQ", observed_at=ASSET_OBSERVED_AT)
    benchmark = adapted_capture(symbol="QQQ", observed_at=BENCHMARK_OBSERVED_AT)

    with pytest.raises(
        MassiveDailyMarketDataCapturePairCompatibilityError,
        match="instrument IDs must be distinct",
    ):
        validate_massive_daily_market_data_capture_pair_compatibility(
            asset=asset,
            benchmark=benchmark,
        )


def test_pair_requires_distinct_instrument_symbols() -> None:
    asset = adapted_capture(
        symbol="QQQ",
        instrument_id="us-equity:QQQ:asset",
        observed_at=ASSET_OBSERVED_AT,
    )
    benchmark = adapted_capture(
        symbol="QQQ",
        instrument_id="us-equity:QQQ:benchmark",
        observed_at=BENCHMARK_OBSERVED_AT,
    )

    with pytest.raises(
        MassiveDailyMarketDataCapturePairCompatibilityError,
        match="instrument symbols must be distinct",
    ):
        validate_massive_daily_market_data_capture_pair_compatibility(
            asset=asset,
            benchmark=benchmark,
        )


@pytest.mark.parametrize("field_name", ("endpoint_family", "endpoint_version"))
def test_pair_rejects_endpoint_authority_mismatch(field_name: str) -> None:
    asset, benchmark = compatible_pair()
    benchmark = replace_member_field(
        benchmark,
        role=DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
        **{field_name: "different-authority"},
    )

    with pytest.raises(
        MassiveDailyMarketDataCapturePairCompatibilityError,
        match=rf"SPLIT_RESPONSE {field_name} is not Massive authority",
    ):
        validate_massive_daily_market_data_capture_pair_compatibility(
            asset=asset,
            benchmark=benchmark,
        )


@pytest.mark.parametrize(
    ("extra_ticker_key", "message"),
    (
        ("Ticker", "source_capture.capture_manifest is invalid"),
        ("vendor.ticker", "request_parameters excluding ticker mismatch"),
    ),
)
def test_pair_excludes_only_exact_ticker_parameter(
    extra_ticker_key: str,
    message: str,
) -> None:
    asset, benchmark = compatible_pair()
    bar_member = member_for_role(
        benchmark,
        DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
    )
    parameters = tuple(
        sorted(
            (
                *bar_member.request_parameters,
                DailyMarketDataSourceCaptureRequestParameter(
                    key=extra_ticker_key,
                    value="SPY",
                ),
            ),
            key=lambda parameter: parameter.key,
        )
    )
    benchmark = replace_member_field(
        benchmark,
        role=DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
        request_parameters=parameters,
    )

    with pytest.raises(
        MassiveDailyMarketDataCapturePairCompatibilityError,
        match=message,
    ):
        validate_massive_daily_market_data_capture_pair_compatibility(
            asset=asset,
            benchmark=benchmark,
        )


def test_pair_rejects_requested_scope_mismatch_after_removing_only_ticker() -> None:
    asset, benchmark = compatible_pair()
    bar_member = member_for_role(
        benchmark,
        DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
    )
    changed_scope = tuple(
        parameter.model_copy(
            update={"value": "2026-01-04"} if parameter.key == "from" else {},
        )
        for parameter in bar_member.requested_scope
    )
    benchmark = replace_member_field(
        benchmark,
        role=DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
        requested_scope=changed_scope,
    )

    with pytest.raises(
        MassiveDailyMarketDataCapturePairCompatibilityError,
        match="BAR_RESPONSE requested_scope excluding ticker mismatch",
    ):
        validate_massive_daily_market_data_capture_pair_compatibility(
            asset=asset,
            benchmark=benchmark,
        )


def compatible_pair(
    *,
    benchmark_request_overrides: dict[DailyMarketDataSourceCaptureRole, dict[str, str]]
    | None = None,
) -> tuple[AdaptedMassiveDailyMarketData, AdaptedMassiveDailyMarketData]:
    return (
        adapted_capture(symbol="QQQ", observed_at=ASSET_OBSERVED_AT),
        adapted_capture(
            symbol="SPY",
            observed_at=BENCHMARK_OBSERVED_AT,
            request_overrides=benchmark_request_overrides,
            response_marker="benchmark-with-different-size",
        ),
    )


def bridge_plan(
    adapted: AdaptedMassiveDailyMarketData,
    *,
    context: MassiveDailyMarketDataSnapshotBridgeContext | None = None,
) -> DailyMarketDataSnapshotPlanV2:
    return plan_massive_daily_market_data_snapshot_v2(
        adapted=adapted,
        policy=sample_policy(),
        expected_sessions=expected_sessions(),
        context=context or bridge_context(),
    )


def bridge_context(**overrides: object) -> MassiveDailyMarketDataSnapshotBridgeContext:
    data = {
        "ingestion_completed_at": datetime(2026, 8, 14, 17, 0, tzinfo=UTC),
        "available_at": datetime(2026, 8, 14, 18, 0, tzinfo=UTC),
        "created_at": datetime(2026, 8, 14, 19, 0, tzinfo=UTC),
        "created_by": "synthetic-s3c3c3-test",
        "license_notes": "synthetic offline fixture; no licensing conclusion",
        "known_limitations": (
            "context limitation",
            "shared limitation",
            "context second limitation",
        ),
    }
    data.update(overrides)
    return MassiveDailyMarketDataSnapshotBridgeContext(**data)  # type: ignore[arg-type]


def expected_sessions(
    *,
    session_dates: tuple[date, ...] = (date(2026, 1, 5), date(2026, 7, 6)),
) -> DailyMarketDataExpectedSessions:
    return DailyMarketDataExpectedSessions(
        schema_version="1.0.0",
        session_source_id="synthetic-independent-session-authority",
        session_source_version="s3c3c3-test-v1",
        calendar="XNYS",
        timezone="America/New_York",
        session_dates=session_dates,
    )


def adapted_capture(
    *,
    symbol: str,
    observed_at: datetime,
    instrument_id: str | None = None,
    currency: str = "USD",
    acquisition_batch_id: str | None = ACQUISITION_BATCH_ID,
    request_overrides: dict[DailyMarketDataSourceCaptureRole, dict[str, str]]
    | None = None,
    response_overrides: dict[DailyMarketDataSourceCaptureRole, bytes] | None = None,
    response_marker: str = "default",
    capture_limitations: tuple[str, ...] = (
        "shared limitation",
        "capture limitation",
    ),
    member_limitations: dict[DailyMarketDataSourceCaptureRole, tuple[str, ...]]
    | None = None,
) -> AdaptedMassiveDailyMarketData:
    instrument = DailyMarketDataInstrument(
        instrument_id=instrument_id or f"us-equity:{symbol}",
        symbol=symbol,
        venue="XNAS",
    )
    limitations = member_limitations or {
        DailyMarketDataSourceCaptureRole.BAR_RESPONSE: (
            "shared limitation",
            "bar limitation",
        ),
        DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE: (
            "shared limitation",
            "dividend limitation",
        ),
        DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE: (
            "shared limitation",
            "split limitation",
        ),
    }
    responses = source_responses(
        symbol=symbol,
        response_marker=response_marker,
        currency=currency,
    )
    responses.update(response_overrides or {})
    members = tuple(
        member_input(
            role=role,
            symbol=symbol,
            content=responses[role],
            request_override=(request_overrides or {}).get(role, {}),
            limitations=limitations.get(role, ()),
            response_marker=response_marker,
        )
        for role in ROLE_ORDER
    )
    capture_plan = plan_daily_market_data_source_capture(
        provider=MASSIVE_PROVIDER,
        source_family=MASSIVE_SOURCE_FAMILY,
        instrument_id=instrument.instrument_id,
        symbol=symbol,
        capture_observed_at=observed_at,
        members=members,
        acquisition_batch_id=acquisition_batch_id,
        limitations=capture_limitations,
    )
    verified = verify_daily_market_data_source_capture(capture_plan.as_file_map())
    return adapt_massive_daily_market_data_source_capture(
        source_capture=verified,
        context=MassiveDailyMarketDataAdapterContext(
            instrument=instrument,
            currency=currency,
        ),
    )


def member_input(
    *,
    role: DailyMarketDataSourceCaptureRole,
    symbol: str,
    content: bytes,
    request_override: dict[str, str],
    limitations: tuple[str, ...],
    response_marker: str,
) -> DailyMarketDataSourceCaptureMemberInput:
    endpoint_family, endpoint_version = {
        DailyMarketDataSourceCaptureRole.BAR_RESPONSE: (
            MASSIVE_BAR_ENDPOINT_FAMILY,
            MASSIVE_BAR_ENDPOINT_VERSION,
        ),
        DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE: (
            MASSIVE_DIVIDEND_ENDPOINT_FAMILY,
            MASSIVE_DIVIDEND_ENDPOINT_VERSION,
        ),
        DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE: (
            MASSIVE_SPLIT_ENDPOINT_FAMILY,
            MASSIVE_SPLIT_ENDPOINT_VERSION,
        ),
    }[role]
    parameters = {
        DailyMarketDataSourceCaptureRole.BAR_RESPONSE: {
            "adjusted": "false",
            "from": "2026-01-05",
            "multiplier": "1",
            "ticker": symbol,
            "timespan": "day",
            "to": "2026-07-06",
        },
        DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE: {
            "ex_dividend_date.gte": "2026-01-01",
            "ex_dividend_date.lte": "2026-12-31",
            "ticker": symbol,
        },
        DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE: {
            "execution_date.gte": "2026-01-01",
            "execution_date.lte": "2026-12-31",
            "ticker": symbol,
        },
    }[role]
    parameters.update(request_override)
    scope_fields = {
        DailyMarketDataSourceCaptureRole.BAR_RESPONSE: ("from", "ticker", "to"),
        DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE: (
            "ex_dividend_date.gte",
            "ex_dividend_date.lte",
            "ticker",
        ),
        DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE: (
            "execution_date.gte",
            "execution_date.lte",
            "ticker",
        ),
    }[role]
    requested_scope = tuple((key, parameters[key]) for key in scope_fields)
    return DailyMarketDataSourceCaptureMemberInput(
        role=role,
        endpoint_family=endpoint_family,
        endpoint_version=endpoint_version,
        request_parameters=tuple(sorted(parameters.items())),
        requested_scope=tuple(sorted(requested_scope)),
        sanitized_source_reference=(
            f"synthetic:massive:{symbol}:{response_marker}:{role.value}"
        ),
        content=content,
        http_status=200,
        media_type="application/json",
        api_request_id=(
            f"synthetic-{symbol}-{response_marker}-{role.value.lower()}-request"
        ),
        limitations=limitations,
    )


def source_responses(
    *,
    symbol: str,
    response_marker: str,
    currency: str = "USD",
) -> dict[DailyMarketDataSourceCaptureRole, bytes]:
    return {
        DailyMarketDataSourceCaptureRole.BAR_RESPONSE: render_json(
            {
                "adjusted": False,
                "queryCount": 2,
                "request_id": (
                    f"synthetic-{symbol}-{response_marker}-bar_response-request"
                ),
                "results": [
                    {
                        "c": Decimal("100.5"),
                        "h": Decimal("101.25"),
                        "l": Decimal("99.75"),
                        "n": 12,
                        "o": Decimal("100.123456789123456789"),
                        "otc": False,
                        "t": 1767589200000,
                        "v": Decimal("1000"),
                        "vw": Decimal("100.333333333333333333"),
                    },
                    {
                        "c": Decimal("201.01"),
                        "h": Decimal("202.2"),
                        "l": Decimal("199.9"),
                        "n": 15,
                        "o": Decimal("200.1"),
                        "otc": False,
                        "t": 1783310400000,
                        "v": Decimal("2000"),
                        "vw": Decimal("200.7"),
                    },
                ],
                "resultsCount": 2,
                "status": "OK",
                "ticker": symbol,
            }
        ),
        DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE: render_json(
            {
                "request_id": (
                    f"synthetic-{symbol}-{response_marker}-dividend_response-request"
                ),
                "results": [
                    {
                        "cash_amount": Decimal("0.123456789123456789"),
                        "currency": currency,
                        "declaration_date": "2026-03-01",
                        "distribution_type": "recurring",
                        "ex_dividend_date": "2026-03-15",
                        "frequency": 4,
                        "historical_adjustment_factor": Decimal("1"),
                        "id": f"synthetic-{symbol.lower()}-dividend-1",
                        "pay_date": "2026-03-30",
                        "record_date": "2026-03-16",
                        "split_adjusted_cash_amount": Decimal("0.123456789123456789"),
                        "ticker": symbol,
                    }
                ],
                "status": "OK",
            }
        ),
        DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE: render_json(
            {
                "request_id": (
                    f"synthetic-{symbol}-{response_marker}-split_response-request"
                ),
                "results": [
                    {
                        "adjustment_type": "forward_split",
                        "execution_date": "2026-06-01",
                        "historical_adjustment_factor": Decimal("1"),
                        "id": f"synthetic-{symbol.lower()}-split-1",
                        "split_from": Decimal("1"),
                        "split_to": Decimal("2"),
                        "ticker": symbol,
                    }
                ],
                "status": "OK",
            }
        ),
    }


def render_json(value: object) -> bytes:
    return (_render_json_value(value) + "\n").encode()


def raw_bar_variant(data: bytes, *, variant: str) -> bytes:
    if variant == "no-final-newline":
        return data.removesuffix(b"\n")
    if variant == "crlf-whitespace":
        return b" \r\n" + data.removesuffix(b"\n") + b" \r\n"
    if variant == "top-level-field-order":
        prefix = b'{"adjusted":false,"queryCount":2,'
        assert data.startswith(prefix)
        return data.replace(
            prefix,
            b'{"queryCount":2,"adjusted":false,',
            1,
        )
    raise AssertionError(f"unknown raw bar variant: {variant}")


def _render_json_value(value: object) -> str:
    if isinstance(value, dict):
        return (
            "{"
            + ",".join(
                json.dumps(str(key), separators=(",", ":"))
                + ":"
                + _render_json_value(item)
                for key, item in sorted(value.items())
            )
            + "}"
        )
    if isinstance(value, list):
        return "[" + ",".join(_render_json_value(item) for item in value) + "]"
    if isinstance(value, Decimal):
        return format(value, "f")
    return json.dumps(value, separators=(",", ":"))


def member_for_role(
    adapted: AdaptedMassiveDailyMarketData,
    role: DailyMarketDataSourceCaptureRole,
):
    return next(
        member
        for member in adapted.source_capture.capture_manifest.members
        if member.role is role
    )


def replace_member_field(
    adapted: AdaptedMassiveDailyMarketData,
    *,
    role: DailyMarketDataSourceCaptureRole,
    **updates: object,
) -> AdaptedMassiveDailyMarketData:
    members = tuple(
        member.model_copy(update=updates) if member.role is role else member
        for member in adapted.source_capture.capture_manifest.members
    )
    manifest = adapted.source_capture.capture_manifest.model_copy(
        update={"members": members}
    )
    capture = replace(adapted.source_capture, capture_manifest=manifest)
    return replace(adapted, source_capture=capture)


def replace_manifest_fields(
    adapted: AdaptedMassiveDailyMarketData,
    **updates: object,
) -> AdaptedMassiveDailyMarketData:
    manifest = adapted.source_capture.capture_manifest.model_copy(update=updates)
    capture = replace(adapted.source_capture, capture_manifest=manifest)
    return replace(adapted, source_capture=capture)


def mutate_pair_fact(
    *,
    benchmark: AdaptedMassiveDailyMarketData,
    asset: AdaptedMassiveDailyMarketData,
    field_name: str,
) -> AdaptedMassiveDailyMarketData:
    if field_name in {"provider", "source_family", "capture_format_version"}:
        manifest = benchmark.source_capture.capture_manifest.model_copy(
            update={field_name: "different-value"}
        )
        return replace(
            benchmark,
            source_capture=replace(
                benchmark.source_capture,
                capture_manifest=manifest,
            ),
        )
    if field_name == "parser_version":
        return replace(benchmark, parser_version="different-parser-version")
    if field_name == "temporal_coverage":
        return replace(benchmark, temporal_coverage=TemporalCoverage.POINT_IN_TIME)
    if field_name == "currency":
        return replace(benchmark, currency="CAD")
    if field_name == "capture_id":
        return replace(
            benchmark,
            source_capture=replace(
                benchmark.source_capture,
                capture_id=asset.capture_id,
            ),
        )
    if field_name == "instrument_id":
        return replace(
            benchmark,
            instrument=benchmark.instrument.model_copy(
                update={"instrument_id": asset.instrument.instrument_id}
            ),
        )
    if field_name == "symbol":
        return replace(
            benchmark,
            instrument=benchmark.instrument.model_copy(
                update={"symbol": asset.instrument.symbol}
            ),
        )
    raise AssertionError(f"unsupported test mutation: {field_name}")


def mutate_bridge_authority(
    adapted: AdaptedMassiveDailyMarketData,
    *,
    field_name: str,
) -> AdaptedMassiveDailyMarketData:
    if field_name == "provider":
        return replace_manifest_fields(adapted, provider="other-provider")
    if field_name == "source_family":
        return replace_manifest_fields(adapted, source_family="other-source-family")
    if field_name == "instrument_symbol":
        return replace(
            adapted,
            instrument=adapted.instrument.model_copy(update={"symbol": "SPY"}),
        )
    if field_name == "capture_id":
        return replace(
            adapted,
            source_capture=replace(
                adapted.source_capture,
                capture_id=("daily-market-data-source-capture-v1-" + "0" * 64),
            ),
        )
    if field_name == "bar_range":
        return replace(adapted, bar_requested_start_date=date(2026, 1, 4))
    if field_name == "ca_range":
        return replace(
            adapted,
            corporate_action_coverage_start_date=date(2025, 12, 31),
        )
    if field_name == "currency":
        return replace(adapted, currency="CAD")
    raise AssertionError(f"unsupported bridge mutation: {field_name}")


def test_bridge_uses_exact_verified_bar_member_mapping() -> None:
    adapted = adapted_capture(symbol="QQQ", observed_at=ASSET_OBSERVED_AT)
    plan = bridge_plan(adapted)
    raw_member = adapted.source_capture.member_bytes[
        DailyMarketDataSourceCaptureRole.BAR_RESPONSE
    ]
    metadata = member_for_role(
        adapted,
        DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
    )

    assert plan.bar_provenance.source_content_hash == metadata.content_sha256
    assert plan.bar_provenance.source_size_bytes == metadata.size_bytes
    assert (
        raw_member
        is adapted.source_capture.member_bytes[
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE
        ]
    )
    assert (
        SOURCE_CAPTURE_MEMBER_PATHS[DailyMarketDataSourceCaptureRole.BAR_RESPONSE]
        == "bars.json"
    )


def test_pair_rejects_adjusted_authority_mismatch_fail_closed() -> None:
    asset, benchmark = compatible_pair()
    bar_member = member_for_role(
        benchmark,
        DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
    )
    changed_parameters = tuple(
        parameter.model_copy(update={"value": "true"})
        if parameter.key == "adjusted"
        else parameter
        for parameter in bar_member.request_parameters
    )
    benchmark = replace_member_field(
        benchmark,
        role=DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
        request_parameters=changed_parameters,
    )

    with pytest.raises(
        MassiveDailyMarketDataCapturePairCompatibilityError,
        match="BAR_RESPONSE 'adjusted' does not match adapted authority",
    ):
        validate_massive_daily_market_data_capture_pair_compatibility(
            asset=asset,
            benchmark=benchmark,
        )
