"""Pure Massive source-capture composition for snapshot-v2 planning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import NoReturn

from pydantic import ValidationError

from research_sdk.contracts.daily_market_data import (
    CanonicalDailyBar,
    DailyMarketDataInstrument,
    DailyMarketDataPolicy,
)
from research_sdk.contracts.daily_market_data_economics import (
    DailyMarketDataCashDistribution,
    DailyMarketDataCorporateActionEvent,
    DailyMarketDataCorporateActionEvidence,
    DailyMarketDataCorporateActionEvidenceCompleteness,
)
from research_sdk.contracts.daily_market_data_snapshots import (
    DailyMarketDataExpectedSessions,
)
from research_sdk.contracts.enums import (
    DataAdjustmentPolicy,
    DataSourceType,
    TemporalCoverage,
)
from research_sdk.contracts.schema import RESEARCH_SDK_CONTRACT_SCHEMA_VERSION
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
    AdaptedMassiveDailyMarketData,
)
from research_sdk.daily_market_data_source_capture.models import (
    CA_SOURCE_MANIFEST_PATH,
    CANONICAL_SOURCE_CAPTURE_ROLE_ORDER,
    SOURCE_CAPTURE_FORMAT_VERSION,
    SOURCE_CAPTURE_MEMBER_PATHS,
    DailyMarketDataSourceCaptureManifest,
    DailyMarketDataSourceCaptureMemberMetadata,
    DailyMarketDataSourceCaptureRequestParameter,
    DailyMarketDataSourceCaptureRole,
)
from research_sdk.daily_market_data_source_capture.verification import (
    VerifiedDailyMarketDataSourceCapture,
)
from research_sdk.daily_market_data_storage.planning_v2 import (
    DailyMarketDataBarSourceAuthorityInputV2,
    DailyMarketDataBarSourceProvenanceInputV2,
    DailyMarketDataSnapshotPlanV2,
    plan_daily_market_data_snapshot_v2,
)
from research_sdk.daily_market_data_storage.serialization import (
    render_canonical_daily_bars,
    sha256_bytes,
)

_CORPORATE_ACTION_EVIDENCE_POLICY_VERSION = (
    "daily-market-data-corporate-action-evidence-v1"
)
_SOURCE_CAPTURE_REFERENCE_PREFIX = "daily-market-data-source-capture://"


class MassiveDailyMarketDataSnapshotBridgeError(ValueError):
    """Raised when Massive evidence cannot be composed into snapshot-v2 input."""


class MassiveDailyMarketDataCapturePairCompatibilityError(
    MassiveDailyMarketDataSnapshotBridgeError
):
    """Raised when two Massive captures are not one compatible acquisition vintage."""


@dataclass(frozen=True)
class MassiveDailyMarketDataSnapshotBridgeContext:
    """Explicit operational and human-review facts for snapshot-v2 composition."""

    ingestion_completed_at: datetime
    available_at: datetime
    created_at: datetime
    created_by: str
    license_notes: str
    known_limitations: tuple[str, ...]


@dataclass(frozen=True)
class _CapturedBridgeContext:
    ingestion_completed_at: datetime
    available_at: datetime
    created_at: datetime
    created_by: str
    license_notes: str
    known_limitations: tuple[str, ...]


@dataclass(frozen=True)
class _CapturedAdaptedMassiveDailyMarketData:
    source_capture: VerifiedDailyMarketDataSourceCapture
    instrument: DailyMarketDataInstrument
    currency: str
    bars: tuple[CanonicalDailyBar, ...]
    corporate_action_events: tuple[DailyMarketDataCorporateActionEvent, ...]
    corporate_action_completeness: DailyMarketDataCorporateActionEvidenceCompleteness
    bar_requested_start_date: date
    bar_requested_end_date: date
    corporate_action_coverage_start_date: date
    corporate_action_coverage_end_date: date
    parser_version: str
    temporal_coverage: TemporalCoverage


@dataclass(frozen=True)
class _CapturedSourceAuthority:
    capture_id: str
    manifest: DailyMarketDataSourceCaptureManifest
    bar_member: DailyMarketDataSourceCaptureMemberMetadata
    dividend_member: DailyMarketDataSourceCaptureMemberMetadata
    split_member: DailyMarketDataSourceCaptureMemberMetadata
    bar_response_bytes: bytes
    ca_source_manifest_bytes: bytes


def plan_massive_daily_market_data_snapshot_v2(
    *,
    adapted: AdaptedMassiveDailyMarketData,
    policy: DailyMarketDataPolicy,
    expected_sessions: DailyMarketDataExpectedSessions,
    context: MassiveDailyMarketDataSnapshotBridgeContext,
) -> DailyMarketDataSnapshotPlanV2:
    """Compose verified offline Massive evidence into the generic v2 planner."""

    captured_adapted = _capture_adapted(
        adapted,
        name="adapted",
        error_type=MassiveDailyMarketDataSnapshotBridgeError,
    )
    authority = _capture_source_authority(
        captured_adapted.source_capture,
        error_type=MassiveDailyMarketDataSnapshotBridgeError,
    )
    _validate_massive_adapted_authority(
        captured_adapted,
        authority,
        error_type=MassiveDailyMarketDataSnapshotBridgeError,
    )
    captured_context = _capture_context(context)
    validated_policy = _validate_bridge_policy(policy)
    _validate_bridge_chronology(
        capture_observed_at=authority.manifest.capture_observed_at,
        context=captured_context,
    )

    bar_limitations = _merge_limitations(
        authority.manifest.limitations,
        authority.bar_member.limitations,
        captured_context.known_limitations,
    )
    ca_limitations = _merge_limitations(
        authority.manifest.limitations,
        authority.dividend_member.limitations,
        authority.split_member.limitations,
        captured_context.known_limitations,
    )
    if not bar_limitations:
        raise MassiveDailyMarketDataSnapshotBridgeError(
            "bar provenance requires at least one known limitation"
        )
    if not ca_limitations:
        raise MassiveDailyMarketDataSnapshotBridgeError(
            "corporate-action evidence requires at least one known limitation"
        )

    bar_provenance_input = DailyMarketDataBarSourceProvenanceInputV2(
        created_at=captured_context.created_at,
        created_by=captured_context.created_by,
        source_dataset=authority.manifest.source_family,
        source_version=authority.capture_id,
        source_type=DataSourceType.VENDOR,
        source_reference=_source_capture_reference(
            authority.capture_id,
            SOURCE_CAPTURE_MEMBER_PATHS[DailyMarketDataSourceCaptureRole.BAR_RESPONSE],
        ),
        temporal_coverage=captured_adapted.temporal_coverage,
        as_of=authority.manifest.capture_observed_at,
        source_observed_at=authority.manifest.capture_observed_at,
        ingestion_completed_at=captured_context.ingestion_completed_at,
        available_at=captured_context.available_at,
        vendor_name=authority.manifest.provider,
        license_notes=captured_context.license_notes,
        source_instrument_reference=authority.manifest.symbol,
        currency=captured_adapted.currency,
        known_limitations=bar_limitations,
    )
    corporate_action_evidence = DailyMarketDataCorporateActionEvidence(
        schema_version=RESEARCH_SDK_CONTRACT_SCHEMA_VERSION,
        evidence_policy_version=_CORPORATE_ACTION_EVIDENCE_POLICY_VERSION,
        completeness=captured_adapted.corporate_action_completeness,
        instrument=captured_adapted.instrument,
        coverage_start_date=captured_adapted.corporate_action_coverage_start_date,
        coverage_end_date=captured_adapted.corporate_action_coverage_end_date,
        source_dataset=authority.manifest.source_family,
        source_version=authority.capture_id,
        source_type=DataSourceType.VENDOR,
        source_reference=_source_capture_reference(
            authority.capture_id,
            CA_SOURCE_MANIFEST_PATH,
        ),
        source_content_hash=sha256_bytes(authority.ca_source_manifest_bytes),
        source_size_bytes=len(authority.ca_source_manifest_bytes),
        source_observed_at=authority.manifest.capture_observed_at,
        ingestion_completed_at=captured_context.ingestion_completed_at,
        available_at=captured_context.available_at,
        created_at=captured_context.created_at,
        created_by=captured_context.created_by,
        canonicalization_version=captured_adapted.parser_version,
        events=captured_adapted.corporate_action_events,
        known_limitations=ca_limitations,
        vendor_name=authority.manifest.provider,
        license_notes=captured_context.license_notes,
    )
    canonical_bar_bytes = render_canonical_daily_bars(captured_adapted.bars)
    return plan_daily_market_data_snapshot_v2(
        source_bytes=canonical_bar_bytes,
        bar_source_authority=DailyMarketDataBarSourceAuthorityInputV2(
            content=authority.bar_response_bytes,
            parser_version=captured_adapted.parser_version,
        ),
        instrument=captured_adapted.instrument,
        policy=validated_policy,
        expected_sessions=expected_sessions,
        bar_provenance_input=bar_provenance_input,
        corporate_action_evidence=corporate_action_evidence,
    )


def validate_massive_daily_market_data_capture_pair_compatibility(
    *,
    asset: AdaptedMassiveDailyMarketData,
    benchmark: AdaptedMassiveDailyMarketData,
) -> None:
    """Require two adapted captures to share one acquisition specification."""

    asset_values = _capture_adapted(
        asset,
        name="asset",
        error_type=MassiveDailyMarketDataCapturePairCompatibilityError,
    )
    benchmark_values = _capture_adapted(
        benchmark,
        name="benchmark",
        error_type=MassiveDailyMarketDataCapturePairCompatibilityError,
    )
    asset_authority = _capture_source_authority(
        asset_values.source_capture,
        error_type=MassiveDailyMarketDataCapturePairCompatibilityError,
    )
    benchmark_authority = _capture_source_authority(
        benchmark_values.source_capture,
        error_type=MassiveDailyMarketDataCapturePairCompatibilityError,
    )
    _validate_massive_adapted_authority(
        asset_values,
        asset_authority,
        error_type=MassiveDailyMarketDataCapturePairCompatibilityError,
    )
    _validate_massive_adapted_authority(
        benchmark_values,
        benchmark_authority,
        error_type=MassiveDailyMarketDataCapturePairCompatibilityError,
    )
    asset_manifest = asset_authority.manifest
    benchmark_manifest = benchmark_authority.manifest

    asset_batch_id = asset_manifest.acquisition_batch_id
    benchmark_batch_id = benchmark_manifest.acquisition_batch_id
    if not asset_batch_id or not benchmark_batch_id:
        _compatibility_error("both captures require acquisition_batch_id")
    _require_compatible_value(
        "acquisition_batch_id",
        asset_batch_id,
        benchmark_batch_id,
    )
    _require_compatible_value(
        "provider",
        asset_manifest.provider,
        benchmark_manifest.provider,
    )
    _require_compatible_value(
        "source_family",
        asset_manifest.source_family,
        benchmark_manifest.source_family,
    )
    _require_compatible_value(
        "capture_format_version",
        asset_manifest.capture_format_version,
        benchmark_manifest.capture_format_version,
    )
    _require_compatible_value(
        "parser_version",
        asset_values.parser_version,
        benchmark_values.parser_version,
    )
    _require_compatible_value(
        "temporal_coverage",
        asset_values.temporal_coverage,
        benchmark_values.temporal_coverage,
    )
    _require_compatible_value(
        "currency",
        asset_values.currency,
        benchmark_values.currency,
    )
    _require_compatible_value(
        "bar requested date range",
        (
            asset_values.bar_requested_start_date,
            asset_values.bar_requested_end_date,
        ),
        (
            benchmark_values.bar_requested_start_date,
            benchmark_values.bar_requested_end_date,
        ),
    )
    _require_compatible_value(
        "corporate-action coverage date range",
        (
            asset_values.corporate_action_coverage_start_date,
            asset_values.corporate_action_coverage_end_date,
        ),
        (
            benchmark_values.corporate_action_coverage_start_date,
            benchmark_values.corporate_action_coverage_end_date,
        ),
    )
    if asset_authority.capture_id == benchmark_authority.capture_id:
        _compatibility_error("capture IDs must be distinct")
    if (
        asset_values.instrument.instrument_id
        == benchmark_values.instrument.instrument_id
    ):
        _compatibility_error("instrument IDs must be distinct")
    if asset_values.instrument.symbol == benchmark_values.instrument.symbol:
        _compatibility_error("instrument symbols must be distinct")

    for role, asset_member, benchmark_member in zip(
        CANONICAL_SOURCE_CAPTURE_ROLE_ORDER,
        (
            asset_authority.bar_member,
            asset_authority.dividend_member,
            asset_authority.split_member,
        ),
        (
            benchmark_authority.bar_member,
            benchmark_authority.dividend_member,
            benchmark_authority.split_member,
        ),
        strict=True,
    ):
        _require_compatible_value(
            f"{role.value} endpoint_family",
            asset_member.endpoint_family,
            benchmark_member.endpoint_family,
        )
        _require_compatible_value(
            f"{role.value} endpoint_version",
            asset_member.endpoint_version,
            benchmark_member.endpoint_version,
        )
        _require_compatible_value(
            f"{role.value} request_parameters excluding ticker",
            _parameters_without_ticker(asset_member.request_parameters),
            _parameters_without_ticker(benchmark_member.request_parameters),
        )
        _require_compatible_value(
            f"{role.value} requested_scope excluding ticker",
            _parameters_without_ticker(asset_member.requested_scope),
            _parameters_without_ticker(benchmark_member.requested_scope),
        )


def _capture_adapted(
    value: AdaptedMassiveDailyMarketData,
    *,
    name: str,
    error_type: type[MassiveDailyMarketDataSnapshotBridgeError],
) -> _CapturedAdaptedMassiveDailyMarketData:
    if not isinstance(value, AdaptedMassiveDailyMarketData):
        _raise_bridge_error(error_type, f"{name} must be AdaptedMassiveDailyMarketData")

    source_capture = value.source_capture
    instrument = value.instrument
    currency = value.currency
    bars = value.bars
    corporate_action_events = value.corporate_action_events
    corporate_action_completeness = value.corporate_action_completeness
    bar_requested_start_date = value.bar_requested_start_date
    bar_requested_end_date = value.bar_requested_end_date
    corporate_action_coverage_start_date = value.corporate_action_coverage_start_date
    corporate_action_coverage_end_date = value.corporate_action_coverage_end_date
    parser_version = value.parser_version
    temporal_coverage = value.temporal_coverage

    if not isinstance(source_capture, VerifiedDailyMarketDataSourceCapture):
        _raise_bridge_error(
            error_type,
            f"{name}.source_capture must be VerifiedDailyMarketDataSourceCapture",
        )
    if not isinstance(instrument, DailyMarketDataInstrument):
        _raise_bridge_error(
            error_type,
            f"{name}.instrument must be DailyMarketDataInstrument",
        )
    try:
        validated_instrument = DailyMarketDataInstrument.model_validate(
            instrument.model_dump(mode="json")
        )
    except ValidationError as exc:
        _raise_bridge_error(
            error_type,
            f"{name}.instrument is invalid",
            cause=exc,
        )
    _require_exact_nonempty_string(
        currency,
        name=f"{name}.currency",
        error_type=error_type,
    )
    _require_exact_nonempty_string(
        parser_version,
        name=f"{name}.parser_version",
        error_type=error_type,
    )
    if type(bars) is not tuple:
        _raise_bridge_error(error_type, f"{name}.bars must be a tuple")
    if type(corporate_action_events) is not tuple:
        _raise_bridge_error(
            error_type,
            f"{name}.corporate_action_events must be a tuple",
        )
    if not isinstance(
        corporate_action_completeness,
        DailyMarketDataCorporateActionEvidenceCompleteness,
    ):
        _raise_bridge_error(
            error_type,
            f"{name}.corporate_action_completeness is invalid",
        )
    for field_name, field_value in (
        ("bar_requested_start_date", bar_requested_start_date),
        ("bar_requested_end_date", bar_requested_end_date),
        (
            "corporate_action_coverage_start_date",
            corporate_action_coverage_start_date,
        ),
        ("corporate_action_coverage_end_date", corporate_action_coverage_end_date),
    ):
        if type(field_value) is not date:
            _raise_bridge_error(
                error_type,
                f"{name}.{field_name} must be a date",
            )
    if not isinstance(temporal_coverage, TemporalCoverage):
        _raise_bridge_error(error_type, f"{name}.temporal_coverage is invalid")

    return _CapturedAdaptedMassiveDailyMarketData(
        source_capture=source_capture,
        instrument=validated_instrument,
        currency=currency,
        bars=bars,
        corporate_action_events=corporate_action_events,
        corporate_action_completeness=corporate_action_completeness,
        bar_requested_start_date=bar_requested_start_date,
        bar_requested_end_date=bar_requested_end_date,
        corporate_action_coverage_start_date=corporate_action_coverage_start_date,
        corporate_action_coverage_end_date=corporate_action_coverage_end_date,
        parser_version=parser_version,
        temporal_coverage=temporal_coverage,
    )


def _capture_source_authority(
    source_capture: VerifiedDailyMarketDataSourceCapture,
    *,
    error_type: type[MassiveDailyMarketDataSnapshotBridgeError],
) -> _CapturedSourceAuthority:
    capture_id = source_capture.capture_id
    manifest_value = source_capture.capture_manifest
    member_bytes = source_capture.member_bytes
    ca_source_manifest_bytes = source_capture.ca_source_manifest_bytes

    _require_exact_nonempty_string(
        capture_id,
        name="source_capture.capture_id",
        error_type=error_type,
    )
    if not isinstance(manifest_value, DailyMarketDataSourceCaptureManifest):
        _raise_bridge_error(
            error_type,
            "source_capture.capture_manifest must be "
            "DailyMarketDataSourceCaptureManifest",
        )
    try:
        manifest = DailyMarketDataSourceCaptureManifest.model_validate(
            manifest_value.model_dump(mode="json")
        )
    except ValidationError as exc:
        _raise_bridge_error(
            error_type,
            "source_capture.capture_manifest is invalid",
            cause=exc,
        )
    members = {member.role: member for member in manifest.members}
    try:
        bar_member = members[DailyMarketDataSourceCaptureRole.BAR_RESPONSE]
        dividend_member = members[DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE]
        split_member = members[DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE]
        bar_response_bytes = member_bytes[DailyMarketDataSourceCaptureRole.BAR_RESPONSE]
    except (KeyError, TypeError):
        _raise_bridge_error(
            error_type,
            "source capture is missing canonical Massive member authority",
        )
    if type(bar_response_bytes) is not bytes:
        _raise_bridge_error(error_type, "BAR_RESPONSE authority must be exact bytes")
    if type(ca_source_manifest_bytes) is not bytes:
        _raise_bridge_error(
            error_type,
            "ca-source-manifest.json authority must be exact bytes",
        )
    return _CapturedSourceAuthority(
        capture_id=capture_id,
        manifest=manifest,
        bar_member=bar_member,
        dividend_member=dividend_member,
        split_member=split_member,
        bar_response_bytes=bar_response_bytes,
        ca_source_manifest_bytes=ca_source_manifest_bytes,
    )


def _validate_massive_adapted_authority(
    adapted: _CapturedAdaptedMassiveDailyMarketData,
    authority: _CapturedSourceAuthority,
    *,
    error_type: type[MassiveDailyMarketDataSnapshotBridgeError],
) -> None:
    manifest = authority.manifest
    for label, actual, expected in (
        ("provider", manifest.provider, MASSIVE_PROVIDER),
        ("source_family", manifest.source_family, MASSIVE_SOURCE_FAMILY),
        (
            "capture_format_version",
            manifest.capture_format_version,
            SOURCE_CAPTURE_FORMAT_VERSION,
        ),
        (
            "parser_version",
            adapted.parser_version,
            MASSIVE_DAILY_MARKET_DATA_ADAPTER_VERSION,
        ),
    ):
        if actual != expected:
            _raise_bridge_error(
                error_type,
                f"Massive {label} must be {expected!r}; got {actual!r}",
            )
    if adapted.temporal_coverage is not TemporalCoverage.LATEST_KNOWN:
        _raise_bridge_error(
            error_type,
            "the historical Massive bridge requires latest_known temporal coverage",
        )
    if authority.capture_id != manifest.capture_id:
        _raise_bridge_error(
            error_type,
            "source_capture.capture_id must match capture_manifest.capture_id",
        )
    if adapted.instrument.instrument_id != manifest.instrument_id:
        _raise_bridge_error(
            error_type,
            "adapted instrument_id must match the source-capture manifest",
        )
    if adapted.instrument.symbol != manifest.symbol:
        _raise_bridge_error(
            error_type,
            "adapted instrument symbol must match the source-capture manifest",
        )

    _validate_member_authority(
        authority.bar_member,
        endpoint_family=MASSIVE_BAR_ENDPOINT_FAMILY,
        endpoint_version=MASSIVE_BAR_ENDPOINT_VERSION,
        expected_parameters={
            "adjusted": "false",
            "from": adapted.bar_requested_start_date.isoformat(),
            "multiplier": "1",
            "ticker": manifest.symbol,
            "timespan": "day",
            "to": adapted.bar_requested_end_date.isoformat(),
        },
        error_type=error_type,
    )
    _validate_member_authority(
        authority.dividend_member,
        endpoint_family=MASSIVE_DIVIDEND_ENDPOINT_FAMILY,
        endpoint_version=MASSIVE_DIVIDEND_ENDPOINT_VERSION,
        expected_parameters={
            "ex_dividend_date.gte": (
                adapted.corporate_action_coverage_start_date.isoformat()
            ),
            "ex_dividend_date.lte": (
                adapted.corporate_action_coverage_end_date.isoformat()
            ),
            "ticker": manifest.symbol,
        },
        error_type=error_type,
    )
    _validate_member_authority(
        authority.split_member,
        endpoint_family=MASSIVE_SPLIT_ENDPOINT_FAMILY,
        endpoint_version=MASSIVE_SPLIT_ENDPOINT_VERSION,
        expected_parameters={
            "execution_date.gte": (
                adapted.corporate_action_coverage_start_date.isoformat()
            ),
            "execution_date.lte": (
                adapted.corporate_action_coverage_end_date.isoformat()
            ),
            "ticker": manifest.symbol,
        },
        error_type=error_type,
    )
    for event in adapted.corporate_action_events:
        if (
            isinstance(event, DailyMarketDataCashDistribution)
            and event.currency != adapted.currency
        ):
            _raise_bridge_error(
                error_type,
                "cash-distribution currency must match adapted currency",
            )


def _validate_member_authority(
    member: DailyMarketDataSourceCaptureMemberMetadata,
    *,
    endpoint_family: str,
    endpoint_version: str,
    expected_parameters: dict[str, str],
    error_type: type[MassiveDailyMarketDataSnapshotBridgeError],
) -> None:
    if member.endpoint_family != endpoint_family:
        _raise_bridge_error(
            error_type,
            f"{member.role.value} endpoint_family is not Massive authority",
        )
    if member.endpoint_version != endpoint_version:
        _raise_bridge_error(
            error_type,
            f"{member.role.value} endpoint_version is not Massive authority",
        )
    parameters = {
        parameter.key: parameter.value for parameter in member.request_parameters
    }
    for key, expected in expected_parameters.items():
        if parameters.get(key) != expected:
            _raise_bridge_error(
                error_type,
                f"{member.role.value} {key!r} does not match adapted authority",
            )


def _capture_context(
    context: MassiveDailyMarketDataSnapshotBridgeContext,
) -> _CapturedBridgeContext:
    if not isinstance(context, MassiveDailyMarketDataSnapshotBridgeContext):
        raise MassiveDailyMarketDataSnapshotBridgeError(
            "context must be MassiveDailyMarketDataSnapshotBridgeContext"
        )
    ingestion_completed_at = context.ingestion_completed_at
    available_at = context.available_at
    created_at = context.created_at
    created_by = context.created_by
    license_notes = context.license_notes
    known_limitations = context.known_limitations

    created_by = _require_context_string(created_by, name="created_by")
    license_notes = _require_context_string(license_notes, name="license_notes")
    if type(known_limitations) is not tuple:
        raise MassiveDailyMarketDataSnapshotBridgeError(
            "known_limitations must be a tuple"
        )
    validated_limitations = tuple(
        _require_context_string(limitation, name="known_limitations entries")
        for limitation in known_limitations
    )
    return _CapturedBridgeContext(
        ingestion_completed_at=_normalize_context_datetime(
            ingestion_completed_at,
            name="ingestion_completed_at",
        ),
        available_at=_normalize_context_datetime(
            available_at,
            name="available_at",
        ),
        created_at=_normalize_context_datetime(created_at, name="created_at"),
        created_by=created_by,
        license_notes=license_notes,
        known_limitations=validated_limitations,
    )


def _require_context_string(value: object, *, name: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise MassiveDailyMarketDataSnapshotBridgeError(
            f"{name} must be a non-empty string without surrounding whitespace"
        )
    return value


def _normalize_context_datetime(value: object, *, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None:
        raise MassiveDailyMarketDataSnapshotBridgeError(
            f"{name} must be a timezone-aware datetime"
        )
    try:
        offset = value.utcoffset()
        if offset is None:
            raise ValueError("missing UTC offset")
        return (value.replace(tzinfo=None) - offset).replace(tzinfo=UTC)
    except (OverflowError, TypeError, ValueError) as exc:
        raise MassiveDailyMarketDataSnapshotBridgeError(
            f"{name} must be a valid timezone-aware datetime"
        ) from exc


def _validate_bridge_policy(policy: DailyMarketDataPolicy) -> DailyMarketDataPolicy:
    if not isinstance(policy, DailyMarketDataPolicy):
        raise MassiveDailyMarketDataSnapshotBridgeError(
            "policy must be DailyMarketDataPolicy"
        )
    validated_policy = DailyMarketDataPolicy.model_validate(
        policy.model_dump(mode="json")
    )
    if validated_policy.adjustment_policy is not DataAdjustmentPolicy.RAW:
        raise MassiveDailyMarketDataSnapshotBridgeError(
            "the Massive snapshot-v2 bridge requires a raw adjustment policy"
        )
    return validated_policy


def _validate_bridge_chronology(
    *,
    capture_observed_at: datetime,
    context: _CapturedBridgeContext,
) -> None:
    if capture_observed_at > context.ingestion_completed_at:
        raise MassiveDailyMarketDataSnapshotBridgeError(
            "capture_observed_at must be less than or equal to ingestion_completed_at"
        )
    if context.ingestion_completed_at > context.available_at:
        raise MassiveDailyMarketDataSnapshotBridgeError(
            "ingestion_completed_at must be less than or equal to available_at"
        )
    if context.available_at > context.created_at:
        raise MassiveDailyMarketDataSnapshotBridgeError(
            "available_at must be less than or equal to created_at"
        )


def _require_exact_nonempty_string(
    value: object,
    *,
    name: str,
    error_type: type[MassiveDailyMarketDataSnapshotBridgeError],
) -> None:
    if type(value) is not str or not value.strip() or value != value.strip():
        _raise_bridge_error(
            error_type,
            f"{name} must be a non-empty string without surrounding whitespace",
        )


def _raise_bridge_error(
    error_type: type[MassiveDailyMarketDataSnapshotBridgeError],
    message: str,
    *,
    cause: Exception | None = None,
) -> NoReturn:
    if cause is None:
        raise error_type(message)
    raise error_type(message) from cause


def _merge_limitations(*groups: tuple[str, ...]) -> tuple[str, ...]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for limitation in group:
            if limitation not in seen:
                seen.add(limitation)
                merged.append(limitation)
    return tuple(merged)


def _source_capture_reference(capture_id: str, relative_path: str) -> str:
    return f"{_SOURCE_CAPTURE_REFERENCE_PREFIX}{capture_id}/{relative_path}"


def _parameters_without_ticker(
    parameters: tuple[DailyMarketDataSourceCaptureRequestParameter, ...],
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (parameter.key, parameter.value)
        for parameter in parameters
        if parameter.key != "ticker"
    )


def _require_compatible_value(label: str, asset: object, benchmark: object) -> None:
    if asset != benchmark:
        _compatibility_error(
            f"{label} mismatch: asset={asset!r}; benchmark={benchmark!r}"
        )


def _compatibility_error(message: str) -> NoReturn:
    raise MassiveDailyMarketDataCapturePairCompatibilityError(message)


__all__ = [
    "MassiveDailyMarketDataCapturePairCompatibilityError",
    "MassiveDailyMarketDataSnapshotBridgeContext",
    "MassiveDailyMarketDataSnapshotBridgeError",
    "plan_massive_daily_market_data_snapshot_v2",
    "validate_massive_daily_market_data_capture_pair_compatibility",
]
