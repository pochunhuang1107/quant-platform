"""Offline Massive daily market-data source-capture adapter."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from math import gcd
from typing import Any, NoReturn
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from research_sdk.contracts.daily_market_data import (
    CanonicalDailyBar,
    DailyMarketDataInstrument,
)
from research_sdk.contracts.daily_market_data_economics import (
    DailyMarketDataCashDistribution,
    DailyMarketDataCorporateActionEvent,
    DailyMarketDataCorporateActionEvidenceCompleteness,
    DailyMarketDataSplit,
    DailyMarketDataUnsupportedCorporateAction,
    corporate_action_event_sort_key,
)
from research_sdk.contracts.enums import TemporalCoverage
from research_sdk.contracts.schema import RESEARCH_SDK_CONTRACT_SCHEMA_VERSION
from research_sdk.daily_market_data_source_capture.models import (
    DailyMarketDataSourceCaptureMemberMetadata,
    DailyMarketDataSourceCaptureRequestParameter,
    DailyMarketDataSourceCaptureRole,
)
from research_sdk.daily_market_data_source_capture.verification import (
    VerifiedDailyMarketDataSourceCapture,
)

MASSIVE_DAILY_MARKET_DATA_ADAPTER_VERSION = "massive-daily-market-data-adapter-v1"
MASSIVE_PROVIDER = "massive"
MASSIVE_SOURCE_FAMILY = "massive-stocks-rest-v1"
MASSIVE_BAR_ENDPOINT_FAMILY = "massive-stocks-aggregates-custom-bars"
MASSIVE_BAR_ENDPOINT_VERSION = "v2"
MASSIVE_DIVIDEND_ENDPOINT_FAMILY = "massive-stocks-dividends"
MASSIVE_DIVIDEND_ENDPOINT_VERSION = "v1"
MASSIVE_SPLIT_ENDPOINT_FAMILY = "massive-stocks-splits"
MASSIVE_SPLIT_ENDPOINT_VERSION = "v1"

_NEW_YORK = ZoneInfo("America/New_York")
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BAR_TOP_LEVEL_FIELDS = frozenset(
    {
        "adjusted",
        "next_url",
        "queryCount",
        "request_id",
        "results",
        "resultsCount",
        "status",
        "ticker",
    }
)
_BAR_ROW_FIELDS = frozenset({"c", "h", "l", "n", "o", "otc", "t", "v", "vw"})
_DIVIDEND_TOP_LEVEL_FIELDS = frozenset({"next_url", "request_id", "results", "status"})
_DIVIDEND_ROW_FIELDS = frozenset(
    {
        "cash_amount",
        "currency",
        "declaration_date",
        "distribution_type",
        "ex_dividend_date",
        "frequency",
        "historical_adjustment_factor",
        "id",
        "pay_date",
        "record_date",
        "split_adjusted_cash_amount",
        "ticker",
    }
)
_DOCUMENTED_DISTRIBUTION_TYPES = frozenset(
    {"irregular", "recurring", "special", "supplemental", "unknown"}
)
_SPLIT_TOP_LEVEL_FIELDS = frozenset({"next_url", "request_id", "results", "status"})
_SPLIT_ROW_FIELDS = frozenset(
    {
        "adjustment_type",
        "execution_date",
        "historical_adjustment_factor",
        "id",
        "split_from",
        "split_to",
        "ticker",
    }
)
_ORDINARY_SPLIT_TYPES = frozenset({"forward_split", "reverse_split"})
_DOCUMENTED_SPLIT_TYPES = frozenset(
    {"forward_split", "reverse_split", "stock_dividend"}
)
_BAR_REQUEST_FIELDS = frozenset(
    {"adjusted", "from", "limit", "multiplier", "sort", "ticker", "timespan", "to"}
)
_BAR_REQUEST_SCOPE_FIELDS = frozenset({"from", "ticker", "to"})
_DIVIDEND_REQUEST_FIELDS = frozenset(
    {"ex_dividend_date.gte", "ex_dividend_date.lte", "limit", "sort", "ticker"}
)
_DIVIDEND_REQUEST_SCOPE_FIELDS = frozenset(
    {"ex_dividend_date.gte", "ex_dividend_date.lte", "ticker"}
)
_SPLIT_REQUEST_FIELDS = frozenset(
    {"execution_date.gte", "execution_date.lte", "limit", "sort", "ticker"}
)
_SPLIT_REQUEST_SCOPE_FIELDS = frozenset(
    {"execution_date.gte", "execution_date.lte", "ticker"}
)
_BAR_SORT_VALUES = frozenset({"asc", "desc"})
_DIVIDEND_SORT_VALUES = frozenset({"ex_dividend_date.asc", "ex_dividend_date.desc"})
_SPLIT_SORT_VALUES = frozenset({"execution_date.asc", "execution_date.desc"})
_BAR_LIMIT_MAX = 50_000
_CORPORATE_ACTION_LIMIT_MAX = 5_000
_CANONICAL_POSITIVE_INTEGER_PATTERN = re.compile(r"^[1-9]\d*$")


class MassiveDailyMarketDataAdapterError(ValueError):
    """Base error for offline Massive source-capture adaptation."""


class MassiveResponseParsingError(MassiveDailyMarketDataAdapterError):
    """Raised when exact Massive response bytes are not strict JSON objects."""


class MassiveResponseValidationError(MassiveDailyMarketDataAdapterError):
    """Raised when Massive response metadata or mapped fields are incoherent."""


class MassiveUnsupportedSemanticError(MassiveDailyMarketDataAdapterError):
    """Raised when Massive semantics cannot be safely mapped by this adapter."""


class MassiveDailyMarketDataAdapterDiagnostic(StrEnum):
    """Finite operator-safe failure locations in the Massive adapter pipeline."""

    CAPTURE_CONTEXT_AUTHORITY = "capture/context authority"
    BAR_RESPONSE_MEMBER_AUTHORITY = "BAR_RESPONSE member authority"
    DIVIDEND_RESPONSE_MEMBER_AUTHORITY = "DIVIDEND_RESPONSE member authority"
    SPLIT_RESPONSE_MEMBER_AUTHORITY = "SPLIT_RESPONSE member authority"
    BAR_RESPONSE_REQUEST_AUTHORITY = "BAR_RESPONSE request authority"
    DIVIDEND_RESPONSE_REQUEST_AUTHORITY = "DIVIDEND_RESPONSE request authority"
    SPLIT_RESPONSE_REQUEST_AUTHORITY = "SPLIT_RESPONSE request authority"
    CORPORATE_ACTION_REQUEST_COMPATIBILITY = "corporate-action request compatibility"
    BAR_RESPONSE_PARSING = "BAR_RESPONSE parsing"
    DIVIDEND_RESPONSE_PARSING = "DIVIDEND_RESPONSE parsing"
    SPLIT_RESPONSE_PARSING = "SPLIT_RESPONSE parsing"
    BAR_RESPONSE_SEMANTIC_ADAPTATION = "BAR_RESPONSE semantic adaptation"
    BAR_RESPONSE_TOP_LEVEL_FIELD_AUTHORITY = "BAR_RESPONSE top-level field authority"
    BAR_RESPONSE_METADATA_AUTHORITY = "BAR_RESPONSE response metadata authority"
    BAR_RESPONSE_TICKER_ADJUSTED_AUTHORITY = "BAR_RESPONSE ticker/adjusted authority"
    BAR_RESPONSE_RESULTS_AUTHORITY = "BAR_RESPONSE results authority"
    BAR_RESPONSE_COUNT_METADATA_AUTHORITY = "BAR_RESPONSE count metadata authority"
    BAR_RESPONSE_ROW_STRUCTURE_AUTHORITY = "BAR_RESPONSE row structure authority"
    BAR_RESPONSE_OHLC_NUMERIC_AUTHORITY = "BAR_RESPONSE OHLC numeric authority"
    BAR_RESPONSE_VOLUME_AUTHORITY = "BAR_RESPONSE volume authority"
    BAR_RESPONSE_TIMESTAMP_SESSION_AUTHORITY = (
        "BAR_RESPONSE timestamp/session authority"
    )
    BAR_RESPONSE_OPTIONAL_METRICS_AUTHORITY = "BAR_RESPONSE optional metrics authority"
    BAR_RESPONSE_REQUESTED_RANGE_AUTHORITY = "BAR_RESPONSE requested-range authority"
    BAR_RESPONSE_CANONICAL_OHLCV_AUTHORITY = "BAR_RESPONSE canonical OHLCV authority"
    BAR_RESPONSE_DUPLICATE_SESSION_AUTHORITY = (
        "BAR_RESPONSE duplicate-session authority"
    )
    DIVIDEND_RESPONSE_SEMANTIC_ADAPTATION = "DIVIDEND_RESPONSE semantic adaptation"
    SPLIT_RESPONSE_SEMANTIC_ADAPTATION = "SPLIT_RESPONSE semantic adaptation"
    CORPORATE_ACTION_CANONICALIZATION = "corporate-action canonicalization"
    ADAPTED_RESULT_CONSTRUCTION = "adapted-result construction"
    UNKNOWN_ADAPTER_FAILURE = "unknown adapter failure"


class _MassiveDailyMarketDataAdapterDiagnosticFailure(Exception):
    """Internal fixed-only signal consumed before leaving the safe adapter API."""

    def __init__(self, diagnostic: MassiveDailyMarketDataAdapterDiagnostic) -> None:
        self.diagnostic = diagnostic
        super().__init__(diagnostic.value)


@dataclass(frozen=True)
class MassiveDailyMarketDataAdapterContext:
    """Explicit non-provider facts required by the offline Massive adapter."""

    instrument: DailyMarketDataInstrument
    currency: str


@dataclass(frozen=True)
class AdaptedMassiveDailyMarketData:
    """Provider-neutral facts adapted from one verified Massive source capture."""

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

    @property
    def capture_id(self) -> str:
        """Return the immutable source-capture lineage ID."""

        return self.source_capture.capture_id


@dataclass(frozen=True)
class MassiveDailyMarketDataAdapterDiagnosticResult:
    """Either adapted data or one fixed diagnostic, without an exception object."""

    adapted: AdaptedMassiveDailyMarketData | None
    diagnostic: MassiveDailyMarketDataAdapterDiagnostic | None


def adapt_massive_daily_market_data_source_capture(
    *,
    source_capture: VerifiedDailyMarketDataSourceCapture,
    context: MassiveDailyMarketDataAdapterContext,
) -> AdaptedMassiveDailyMarketData:
    """Adapt a verified source capture into provider-neutral daily facts."""

    return _adapt_massive_daily_market_data_source_capture(
        source_capture=source_capture,
        context=context,
        safe_diagnostics=False,
    )


def adapt_massive_daily_market_data_source_capture_with_diagnostics(
    *,
    source_capture: VerifiedDailyMarketDataSourceCapture,
    context: MassiveDailyMarketDataAdapterContext,
) -> MassiveDailyMarketDataAdapterDiagnosticResult:
    """Adapt with only a finite fixed diagnostic available on failure."""

    adapted: AdaptedMassiveDailyMarketData | None = None
    diagnostic: MassiveDailyMarketDataAdapterDiagnostic | None = None
    try:
        adapted = _adapt_massive_daily_market_data_source_capture(
            source_capture=source_capture,
            context=context,
            safe_diagnostics=True,
        )
    except _MassiveDailyMarketDataAdapterDiagnosticFailure as failure:
        diagnostic = failure.diagnostic
    except Exception:
        diagnostic = MassiveDailyMarketDataAdapterDiagnostic.UNKNOWN_ADAPTER_FAILURE
    if diagnostic is not None:
        return MassiveDailyMarketDataAdapterDiagnosticResult(
            adapted=None,
            diagnostic=diagnostic,
        )
    return MassiveDailyMarketDataAdapterDiagnosticResult(
        adapted=adapted,
        diagnostic=None,
    )


def _adapt_massive_daily_market_data_source_capture(
    *,
    source_capture: VerifiedDailyMarketDataSourceCapture,
    context: MassiveDailyMarketDataAdapterContext,
    safe_diagnostics: bool,
) -> AdaptedMassiveDailyMarketData:
    instrument, currency = _run_adapter_stage(
        MassiveDailyMarketDataAdapterDiagnostic.CAPTURE_CONTEXT_AUTHORITY,
        lambda: _capture_adapter_context(
            source_capture=source_capture,
            context=context,
        ),
        safe_diagnostics=safe_diagnostics,
    )
    members = _run_adapter_stage(
        MassiveDailyMarketDataAdapterDiagnostic.CAPTURE_CONTEXT_AUTHORITY,
        lambda: _member_metadata_by_role(source_capture),
        safe_diagnostics=safe_diagnostics,
    )
    _run_adapter_stage(
        MassiveDailyMarketDataAdapterDiagnostic.BAR_RESPONSE_MEMBER_AUTHORITY,
        lambda: _validate_member_authority(
            member=members[DailyMarketDataSourceCaptureRole.BAR_RESPONSE],
            endpoint_family=MASSIVE_BAR_ENDPOINT_FAMILY,
            endpoint_version=MASSIVE_BAR_ENDPOINT_VERSION,
        ),
        safe_diagnostics=safe_diagnostics,
    )
    _run_adapter_stage(
        MassiveDailyMarketDataAdapterDiagnostic.DIVIDEND_RESPONSE_MEMBER_AUTHORITY,
        lambda: _validate_member_authority(
            member=members[DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE],
            endpoint_family=MASSIVE_DIVIDEND_ENDPOINT_FAMILY,
            endpoint_version=MASSIVE_DIVIDEND_ENDPOINT_VERSION,
        ),
        safe_diagnostics=safe_diagnostics,
    )
    _run_adapter_stage(
        MassiveDailyMarketDataAdapterDiagnostic.SPLIT_RESPONSE_MEMBER_AUTHORITY,
        lambda: _validate_member_authority(
            member=members[DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE],
            endpoint_family=MASSIVE_SPLIT_ENDPOINT_FAMILY,
            endpoint_version=MASSIVE_SPLIT_ENDPOINT_VERSION,
        ),
        safe_diagnostics=safe_diagnostics,
    )

    bar_scope = _run_adapter_stage(
        MassiveDailyMarketDataAdapterDiagnostic.BAR_RESPONSE_REQUEST_AUTHORITY,
        lambda: _validate_bar_request_authority(
            members[DailyMarketDataSourceCaptureRole.BAR_RESPONSE],
            symbol=source_capture.capture_manifest.symbol,
            capture_id=source_capture.capture_id,
        ),
        safe_diagnostics=safe_diagnostics,
    )
    dividend_scope = _run_adapter_stage(
        MassiveDailyMarketDataAdapterDiagnostic.DIVIDEND_RESPONSE_REQUEST_AUTHORITY,
        lambda: _validate_ca_request_authority(
            members[DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE],
            symbol=source_capture.capture_manifest.symbol,
            start_key="ex_dividend_date.gte",
            end_key="ex_dividend_date.lte",
            role=DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
            capture_id=source_capture.capture_id,
        ),
        safe_diagnostics=safe_diagnostics,
    )
    split_scope = _run_adapter_stage(
        MassiveDailyMarketDataAdapterDiagnostic.SPLIT_RESPONSE_REQUEST_AUTHORITY,
        lambda: _validate_ca_request_authority(
            members[DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE],
            symbol=source_capture.capture_manifest.symbol,
            start_key="execution_date.gte",
            end_key="execution_date.lte",
            role=DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
            capture_id=source_capture.capture_id,
        ),
        safe_diagnostics=safe_diagnostics,
    )
    _run_adapter_stage(
        MassiveDailyMarketDataAdapterDiagnostic.CORPORATE_ACTION_REQUEST_COMPATIBILITY,
        lambda: _validate_corporate_action_request_compatibility(
            dividend_scope=dividend_scope,
            split_scope=split_scope,
            capture_id=source_capture.capture_id,
        ),
        safe_diagnostics=safe_diagnostics,
    )

    bars_response = _run_adapter_stage(
        MassiveDailyMarketDataAdapterDiagnostic.BAR_RESPONSE_PARSING,
        lambda: _parse_response_bytes(
            source_capture.member_bytes[DailyMarketDataSourceCaptureRole.BAR_RESPONSE],
            role=DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
            capture_id=source_capture.capture_id,
        ),
        safe_diagnostics=safe_diagnostics,
    )
    dividends_response = _run_adapter_stage(
        MassiveDailyMarketDataAdapterDiagnostic.DIVIDEND_RESPONSE_PARSING,
        lambda: _parse_response_bytes(
            source_capture.member_bytes[
                DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE
            ],
            role=DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
            capture_id=source_capture.capture_id,
        ),
        safe_diagnostics=safe_diagnostics,
    )
    splits_response = _run_adapter_stage(
        MassiveDailyMarketDataAdapterDiagnostic.SPLIT_RESPONSE_PARSING,
        lambda: _parse_response_bytes(
            source_capture.member_bytes[
                DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE
            ],
            role=DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
            capture_id=source_capture.capture_id,
        ),
        safe_diagnostics=safe_diagnostics,
    )

    bars = _run_adapter_stage(
        MassiveDailyMarketDataAdapterDiagnostic.BAR_RESPONSE_SEMANTIC_ADAPTATION,
        lambda: _adapt_bars(
            bars_response,
            member=members[DailyMarketDataSourceCaptureRole.BAR_RESPONSE],
            symbol=source_capture.capture_manifest.symbol,
            requested_scope=bar_scope,
            capture_id=source_capture.capture_id,
            safe_diagnostics=safe_diagnostics,
        ),
        safe_diagnostics=safe_diagnostics,
    )
    dividend_events = _run_adapter_stage(
        MassiveDailyMarketDataAdapterDiagnostic.DIVIDEND_RESPONSE_SEMANTIC_ADAPTATION,
        lambda: _adapt_dividends(
            dividends_response,
            member=members[DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE],
            instrument=instrument,
            expected_currency=currency,
            requested_scope=dividend_scope,
            source_available_at=source_capture.capture_manifest.capture_observed_at,
            capture_id=source_capture.capture_id,
        ),
        safe_diagnostics=safe_diagnostics,
    )
    split_events = _run_adapter_stage(
        MassiveDailyMarketDataAdapterDiagnostic.SPLIT_RESPONSE_SEMANTIC_ADAPTATION,
        lambda: _adapt_splits(
            splits_response,
            member=members[DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE],
            instrument=instrument,
            symbol=source_capture.capture_manifest.symbol,
            requested_scope=split_scope,
            source_available_at=source_capture.capture_manifest.capture_observed_at,
            capture_id=source_capture.capture_id,
        ),
        safe_diagnostics=safe_diagnostics,
    )
    events = _run_adapter_stage(
        MassiveDailyMarketDataAdapterDiagnostic.CORPORATE_ACTION_CANONICALIZATION,
        lambda: _canonicalize_events(
            (*dividend_events, *split_events), source_capture.capture_id
        ),
        safe_diagnostics=safe_diagnostics,
    )
    return _run_adapter_stage(
        MassiveDailyMarketDataAdapterDiagnostic.ADAPTED_RESULT_CONSTRUCTION,
        lambda: _build_adapted_result(
            source_capture=source_capture,
            instrument=instrument,
            currency=currency,
            bars=bars,
            events=events,
            bar_scope=bar_scope,
            corporate_action_scope=dividend_scope,
        ),
        safe_diagnostics=safe_diagnostics,
    )


def _run_adapter_stage[T](
    diagnostic: MassiveDailyMarketDataAdapterDiagnostic,
    operation: Callable[[], T],
    *,
    safe_diagnostics: bool,
) -> T:
    if not safe_diagnostics:
        return operation()
    failure: _MassiveDailyMarketDataAdapterDiagnosticFailure | None = None
    try:
        return operation()
    except _MassiveDailyMarketDataAdapterDiagnosticFailure:
        raise
    except (MassiveDailyMarketDataAdapterError, ValidationError):
        failure = _MassiveDailyMarketDataAdapterDiagnosticFailure(diagnostic)
    except Exception:
        failure = _MassiveDailyMarketDataAdapterDiagnosticFailure(
            MassiveDailyMarketDataAdapterDiagnostic.UNKNOWN_ADAPTER_FAILURE
        )
    raise failure from None


def _capture_adapter_context(
    *,
    source_capture: VerifiedDailyMarketDataSourceCapture,
    context: MassiveDailyMarketDataAdapterContext,
) -> tuple[DailyMarketDataInstrument, str]:
    if not isinstance(source_capture, VerifiedDailyMarketDataSourceCapture):
        _validation_error("source_capture must be VerifiedDailyMarketDataSourceCapture")
    instrument = DailyMarketDataInstrument.model_validate(
        context.instrument.model_dump(mode="json")
    )
    currency = _require_non_empty_string(context.currency, "context.currency")
    _validate_capture_and_context(source_capture=source_capture, instrument=instrument)
    return instrument, currency


def _validate_corporate_action_request_compatibility(
    *,
    dividend_scope: tuple[date, date],
    split_scope: tuple[date, date],
    capture_id: str,
) -> None:
    if dividend_scope != split_scope:
        _validation_error(
            "dividend and split source members must use identical requested coverage",
            capture_id=capture_id,
        )


def _build_adapted_result(
    *,
    source_capture: VerifiedDailyMarketDataSourceCapture,
    instrument: DailyMarketDataInstrument,
    currency: str,
    bars: tuple[CanonicalDailyBar, ...],
    events: tuple[DailyMarketDataCorporateActionEvent, ...],
    bar_scope: tuple[date, date],
    corporate_action_scope: tuple[date, date],
) -> AdaptedMassiveDailyMarketData:
    completeness = (
        DailyMarketDataCorporateActionEvidenceCompleteness.CHECKED_EVENTS_CAPTURED
        if events
        else DailyMarketDataCorporateActionEvidenceCompleteness.CHECKED_NO_EVENTS
    )
    return AdaptedMassiveDailyMarketData(
        source_capture=source_capture,
        instrument=instrument,
        currency=currency,
        bars=bars,
        corporate_action_events=events,
        corporate_action_completeness=completeness,
        bar_requested_start_date=bar_scope[0],
        bar_requested_end_date=bar_scope[1],
        corporate_action_coverage_start_date=corporate_action_scope[0],
        corporate_action_coverage_end_date=corporate_action_scope[1],
        parser_version=MASSIVE_DAILY_MARKET_DATA_ADAPTER_VERSION,
        temporal_coverage=TemporalCoverage.LATEST_KNOWN,
    )


def _validate_capture_and_context(
    *,
    source_capture: VerifiedDailyMarketDataSourceCapture,
    instrument: DailyMarketDataInstrument,
) -> None:
    manifest = source_capture.capture_manifest
    if manifest.provider != MASSIVE_PROVIDER:
        _validation_error(
            f"unsupported provider {manifest.provider!r}",
            capture_id=source_capture.capture_id,
        )
    if manifest.source_family != MASSIVE_SOURCE_FAMILY:
        _validation_error(
            f"unsupported source family {manifest.source_family!r}",
            capture_id=source_capture.capture_id,
        )
    if instrument.instrument_id != manifest.instrument_id:
        _validation_error(
            "adapter instrument_id must match source capture",
            capture_id=source_capture.capture_id,
        )
    if instrument.symbol != manifest.symbol:
        _validation_error(
            "adapter instrument symbol must match source capture",
            capture_id=source_capture.capture_id,
        )


def _member_metadata_by_role(
    source_capture: VerifiedDailyMarketDataSourceCapture,
) -> dict[DailyMarketDataSourceCaptureRole, DailyMarketDataSourceCaptureMemberMetadata]:
    return {member.role: member for member in source_capture.capture_manifest.members}


def _validate_member_authority(
    *,
    member: DailyMarketDataSourceCaptureMemberMetadata,
    endpoint_family: str,
    endpoint_version: str,
) -> None:
    if member.endpoint_family != endpoint_family:
        _validation_error(
            f"{member.role.value} endpoint_family mismatch: {member.endpoint_family!r}",
        )
    if member.endpoint_version != endpoint_version:
        _validation_error(
            (
                f"{member.role.value} endpoint_version mismatch: "
                f"{member.endpoint_version!r}"
            ),
        )


def _validate_bar_request_authority(
    member: DailyMarketDataSourceCaptureMemberMetadata,
    *,
    symbol: str,
    capture_id: str,
) -> tuple[date, date]:
    parameters = _parameter_map(member.request_parameters)
    _validate_request_parameter_fields(
        parameters,
        allowed_fields=_BAR_REQUEST_FIELDS,
        role=member.role,
        capture_id=capture_id,
    )
    _validate_redundant_scope_authority(
        primary=parameters,
        redundant=member.requested_scope,
        allowed_scope_fields=_BAR_REQUEST_SCOPE_FIELDS,
        role=member.role,
        capture_id=capture_id,
    )
    _require_parameter(parameters, "ticker", symbol, member.role, capture_id)
    _require_parameter(parameters, "multiplier", "1", member.role, capture_id)
    _require_parameter(parameters, "timespan", "day", member.role, capture_id)
    _require_parameter(parameters, "adjusted", "false", member.role, capture_id)
    start_date = _parse_provider_date(
        _required_parameter_value(parameters, "from", member.role, capture_id),
        field="from",
        role=member.role,
        capture_id=capture_id,
    )
    end_date = _parse_provider_date(
        _required_parameter_value(parameters, "to", member.role, capture_id),
        field="to",
        role=member.role,
        capture_id=capture_id,
    )
    if end_date < start_date:
        _validation_error(
            "bar request end date precedes start date", capture_id=capture_id
        )
    _validate_optional_sort(
        parameters,
        allowed_values=_BAR_SORT_VALUES,
        role=member.role,
        capture_id=capture_id,
    )
    _validate_optional_limit(
        parameters,
        max_value=_BAR_LIMIT_MAX,
        role=member.role,
        capture_id=capture_id,
    )
    return (start_date, end_date)


def _validate_ca_request_authority(
    member: DailyMarketDataSourceCaptureMemberMetadata,
    *,
    symbol: str,
    start_key: str,
    end_key: str,
    role: DailyMarketDataSourceCaptureRole,
    capture_id: str,
) -> tuple[date, date]:
    parameters = _parameter_map(member.request_parameters)
    if role is DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE:
        allowed_fields = _DIVIDEND_REQUEST_FIELDS
        allowed_scope_fields = _DIVIDEND_REQUEST_SCOPE_FIELDS
        sort_values = _DIVIDEND_SORT_VALUES
    else:
        allowed_fields = _SPLIT_REQUEST_FIELDS
        allowed_scope_fields = _SPLIT_REQUEST_SCOPE_FIELDS
        sort_values = _SPLIT_SORT_VALUES
    _validate_request_parameter_fields(
        parameters,
        allowed_fields=allowed_fields,
        role=role,
        capture_id=capture_id,
    )
    _validate_redundant_scope_authority(
        primary=parameters,
        redundant=member.requested_scope,
        allowed_scope_fields=allowed_scope_fields,
        role=role,
        capture_id=capture_id,
    )
    _require_parameter(parameters, "ticker", symbol, role, capture_id)
    start_date = _parse_provider_date(
        _required_parameter_value(parameters, start_key, role, capture_id),
        field=start_key,
        role=role,
        capture_id=capture_id,
    )
    end_date = _parse_provider_date(
        _required_parameter_value(parameters, end_key, role, capture_id),
        field=end_key,
        role=role,
        capture_id=capture_id,
    )
    if end_date < start_date:
        _validation_error(
            f"{role.value} coverage end date precedes start date",
            capture_id=capture_id,
        )
    _validate_optional_sort(
        parameters,
        allowed_values=sort_values,
        role=role,
        capture_id=capture_id,
    )
    _validate_optional_limit(
        parameters,
        max_value=_CORPORATE_ACTION_LIMIT_MAX,
        role=role,
        capture_id=capture_id,
    )
    return (start_date, end_date)


def _parameter_map(
    parameters: Sequence[DailyMarketDataSourceCaptureRequestParameter],
) -> dict[str, str]:
    return {parameter.key: parameter.value for parameter in parameters}


def _validate_redundant_scope_authority(
    *,
    primary: Mapping[str, str],
    redundant: Sequence[DailyMarketDataSourceCaptureRequestParameter],
    allowed_scope_fields: frozenset[str],
    role: DailyMarketDataSourceCaptureRole,
    capture_id: str,
) -> None:
    by_lower = {key.lower(): (key, value) for key, value in primary.items()}
    allowed_by_lower = {key.lower(): key for key in allowed_scope_fields}
    for parameter in redundant:
        expected_key = allowed_by_lower.get(parameter.key.lower())
        if expected_key is None or parameter.key != expected_key:
            _validation_error(
                (
                    f"{role.value} requested_scope contains unsupported scope "
                    f"field {parameter.key!r}"
                ),
                capture_id=capture_id,
            )
        existing = by_lower.get(parameter.key.lower())
        if existing is None:
            _validation_error(
                (
                    f"{role.value} requested_scope cannot supply missing actual "
                    f"request authority for {parameter.key!r}"
                ),
                capture_id=capture_id,
            )
        if existing[1] != parameter.value:
            _validation_error(
                (
                    f"{role.value} request_parameters and requested_scope "
                    f"contradict on {parameter.key!r}"
                ),
                capture_id=capture_id,
            )


def _validate_request_parameter_fields(
    parameters: Mapping[str, str],
    *,
    allowed_fields: frozenset[str],
    role: DailyMarketDataSourceCaptureRole,
    capture_id: str,
) -> None:
    unexpected = sorted(key for key in parameters if key not in allowed_fields)
    if unexpected:
        _validation_error(
            (
                f"{role.value} request authority contains unsupported field(s): "
                f"{unexpected}"
            ),
            capture_id=capture_id,
        )


def _validate_optional_sort(
    parameters: Mapping[str, str],
    *,
    allowed_values: frozenset[str],
    role: DailyMarketDataSourceCaptureRole,
    capture_id: str,
) -> None:
    sort = parameters.get("sort")
    if sort is None:
        return
    if sort != sort.strip() or sort not in allowed_values:
        _validation_error(
            f"{role.value} sort is not supported: {sort!r}",
            capture_id=capture_id,
        )


def _validate_optional_limit(
    parameters: Mapping[str, str],
    *,
    max_value: int,
    role: DailyMarketDataSourceCaptureRole,
    capture_id: str,
) -> None:
    limit = parameters.get("limit")
    if limit is None:
        return
    if _CANONICAL_POSITIVE_INTEGER_PATTERN.fullmatch(limit) is None:
        _validation_error(
            f"{role.value} limit must be a canonical positive integer string",
            capture_id=capture_id,
        )
    value = int(limit)
    if value > max_value:
        _validation_error(
            f"{role.value} limit must be between 1 and {max_value}",
            capture_id=capture_id,
        )


def _required_parameter_value(
    parameters: Mapping[str, str],
    key: str,
    role: DailyMarketDataSourceCaptureRole,
    capture_id: str,
) -> str:
    try:
        return parameters[key]
    except KeyError:
        _validation_error(
            f"{role.value} request authority missing {key!r}",
            capture_id=capture_id,
        )


def _require_parameter(
    parameters: Mapping[str, str],
    key: str,
    expected: str,
    role: DailyMarketDataSourceCaptureRole,
    capture_id: str,
) -> None:
    actual = _required_parameter_value(parameters, key, role, capture_id)
    if actual != expected:
        _validation_error(
            f"{role.value} request authority {key!r} must be {expected!r}",
            capture_id=capture_id,
        )


def _parse_response_bytes(
    data: bytes,
    *,
    role: DailyMarketDataSourceCaptureRole,
    capture_id: str,
) -> dict[str, Any]:
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise MassiveResponseParsingError(
            f"{role.value} in source capture {capture_id} is not valid UTF-8"
        ) from exc
    try:
        payload = json.loads(
            text,
            parse_float=Decimal,
            parse_int=int,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except MassiveResponseParsingError:
        raise
    except json.JSONDecodeError as exc:
        raise MassiveResponseParsingError(
            f"{role.value} in source capture {capture_id} is not valid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise MassiveResponseParsingError(
            f"{role.value} in source capture {capture_id} must be a JSON object"
        )
    return payload


def _reject_json_constant(value: str) -> NoReturn:
    raise MassiveResponseParsingError(
        f"non-standard JSON constant is not allowed: {value}"
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MassiveResponseParsingError(
                f"duplicate JSON key is not allowed: {key}"
            )
        result[key] = value
    return result


def _adapt_bars(
    response: Mapping[str, Any],
    *,
    member: DailyMarketDataSourceCaptureMemberMetadata,
    symbol: str,
    requested_scope: tuple[date, date],
    capture_id: str,
    safe_diagnostics: bool,
) -> tuple[CanonicalDailyBar, ...]:
    _run_adapter_stage(
        MassiveDailyMarketDataAdapterDiagnostic.BAR_RESPONSE_TOP_LEVEL_FIELD_AUTHORITY,
        lambda: _validate_known_fields(response, _BAR_TOP_LEVEL_FIELDS, "BAR_RESPONSE"),
        safe_diagnostics=safe_diagnostics,
    )
    _run_adapter_stage(
        MassiveDailyMarketDataAdapterDiagnostic.BAR_RESPONSE_METADATA_AUTHORITY,
        lambda: _validate_common_response_metadata(
            response,
            member=member,
            role=DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
            capture_id=capture_id,
        ),
        safe_diagnostics=safe_diagnostics,
    )
    _run_adapter_stage(
        MassiveDailyMarketDataAdapterDiagnostic.BAR_RESPONSE_TICKER_ADJUSTED_AUTHORITY,
        lambda: _validate_bar_ticker_and_adjusted(
            response,
            symbol=symbol,
            capture_id=capture_id,
        ),
        safe_diagnostics=safe_diagnostics,
    )
    results = _run_adapter_stage(
        MassiveDailyMarketDataAdapterDiagnostic.BAR_RESPONSE_RESULTS_AUTHORITY,
        lambda: _results_list(
            response,
            role=DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
            capture_id=capture_id,
        ),
        safe_diagnostics=safe_diagnostics,
    )
    _run_adapter_stage(
        MassiveDailyMarketDataAdapterDiagnostic.BAR_RESPONSE_COUNT_METADATA_AUTHORITY,
        lambda: _validate_count_metadata(
            response,
            results,
            role=DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
            capture_id=capture_id,
        ),
        safe_diagnostics=safe_diagnostics,
    )
    bars = []
    for index, row in enumerate(results):
        _run_adapter_stage(
            MassiveDailyMarketDataAdapterDiagnostic.BAR_RESPONSE_ROW_STRUCTURE_AUTHORITY,
            lambda: _validate_bar_row_structure(
                row,
                index=index,
                capture_id=capture_id,
            ),
            safe_diagnostics=safe_diagnostics,
        )
        open_, high, low, close = _run_adapter_stage(
            MassiveDailyMarketDataAdapterDiagnostic.BAR_RESPONSE_OHLC_NUMERIC_AUTHORITY,
            lambda: (
                _required_decimal(row, "o", role="BAR_RESPONSE", capture_id=capture_id),
                _required_decimal(row, "h", role="BAR_RESPONSE", capture_id=capture_id),
                _required_decimal(row, "l", role="BAR_RESPONSE", capture_id=capture_id),
                _required_decimal(row, "c", role="BAR_RESPONSE", capture_id=capture_id),
            ),
            safe_diagnostics=safe_diagnostics,
        )
        volume = _run_adapter_stage(
            MassiveDailyMarketDataAdapterDiagnostic.BAR_RESPONSE_VOLUME_AUTHORITY,
            lambda: _required_integral(
                row,
                "v",
                role="BAR_RESPONSE",
                capture_id=capture_id,
                allow_decimal=True,
            ),
            safe_diagnostics=safe_diagnostics,
        )
        timestamp = _run_adapter_stage(
            MassiveDailyMarketDataAdapterDiagnostic.BAR_RESPONSE_TIMESTAMP_SESSION_AUTHORITY,
            lambda: _required_epoch_millis(
                row, "t", role="BAR_RESPONSE", capture_id=capture_id
            ),
            safe_diagnostics=safe_diagnostics,
        )
        session_date = _run_adapter_stage(
            MassiveDailyMarketDataAdapterDiagnostic.BAR_RESPONSE_TIMESTAMP_SESSION_AUTHORITY,
            lambda: _session_date_from_massive_timestamp(timestamp),
            safe_diagnostics=safe_diagnostics,
        )
        _run_adapter_stage(
            MassiveDailyMarketDataAdapterDiagnostic.BAR_RESPONSE_OPTIONAL_METRICS_AUTHORITY,
            lambda: _validate_bar_optional_metrics(row, capture_id=capture_id),
            safe_diagnostics=safe_diagnostics,
        )
        _run_adapter_stage(
            MassiveDailyMarketDataAdapterDiagnostic.BAR_RESPONSE_REQUESTED_RANGE_AUTHORITY,
            lambda: _validate_bar_requested_range(
                session_date,
                requested_scope=requested_scope,
                capture_id=capture_id,
            ),
            safe_diagnostics=safe_diagnostics,
        )
        bars.append(
            _run_adapter_stage(
                MassiveDailyMarketDataAdapterDiagnostic.BAR_RESPONSE_CANONICAL_OHLCV_AUTHORITY,
                lambda: _canonical_bar(
                    session_date=session_date,
                    open_=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    index=index,
                ),
                safe_diagnostics=safe_diagnostics,
            )
        )
    return _run_adapter_stage(
        MassiveDailyMarketDataAdapterDiagnostic.BAR_RESPONSE_DUPLICATE_SESSION_AUTHORITY,
        lambda: _order_and_validate_unique_bar_sessions(
            bars,
            capture_id=capture_id,
        ),
        safe_diagnostics=safe_diagnostics,
    )


def _validate_bar_ticker_and_adjusted(
    response: Mapping[str, Any],
    *,
    symbol: str,
    capture_id: str,
) -> None:
    if response.get("ticker") != symbol:
        _validation_error(
            "BAR_RESPONSE ticker must match capture symbol", capture_id=capture_id
        )
    if response.get("adjusted") is not False:
        _validation_error(
            "BAR_RESPONSE adjusted must be boolean false", capture_id=capture_id
        )


def _validate_bar_row_structure(
    row: object,
    *,
    index: int,
    capture_id: str,
) -> None:
    if not isinstance(row, dict):
        _validation_error(
            f"BAR_RESPONSE row {index} must be an object", capture_id=capture_id
        )
    _validate_known_fields(row, _BAR_ROW_FIELDS, f"BAR_RESPONSE row {index}")


def _validate_bar_optional_metrics(
    row: Mapping[str, Any],
    *,
    capture_id: str,
) -> None:
    if "vw" in row:
        _required_decimal(row, "vw", role="BAR_RESPONSE", capture_id=capture_id)
    if "n" in row:
        _required_integral(
            row, "n", role="BAR_RESPONSE", capture_id=capture_id, allow_decimal=True
        )
    if "otc" in row and type(row["otc"]) is not bool:
        _validation_error(
            "BAR_RESPONSE otc must be boolean when present", capture_id=capture_id
        )


def _validate_bar_requested_range(
    session_date: date,
    *,
    requested_scope: tuple[date, date],
    capture_id: str,
) -> None:
    if not requested_scope[0] <= session_date <= requested_scope[1]:
        _validation_error(
            "BAR_RESPONSE row session date is outside requested range",
            capture_id=capture_id,
        )


def _canonical_bar(
    *,
    session_date: date,
    open_: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    volume: int,
    index: int,
) -> CanonicalDailyBar:
    try:
        return CanonicalDailyBar(
            session_date=session_date,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )
    except Exception as exc:
        raise MassiveResponseValidationError(
            f"BAR_RESPONSE row {index} failed canonical OHLCV validation"
        ) from exc


def _order_and_validate_unique_bar_sessions(
    bars: Sequence[CanonicalDailyBar],
    *,
    capture_id: str,
) -> tuple[CanonicalDailyBar, ...]:
    ordered = tuple(sorted(bars, key=lambda bar: bar.session_date))
    session_dates = tuple(bar.session_date for bar in ordered)
    if len(set(session_dates)) != len(session_dates):
        _validation_error(
            "BAR_RESPONSE contains duplicate normalized session dates",
            capture_id=capture_id,
        )
    return ordered


def _adapt_dividends(
    response: Mapping[str, Any],
    *,
    member: DailyMarketDataSourceCaptureMemberMetadata,
    instrument: DailyMarketDataInstrument,
    expected_currency: str,
    requested_scope: tuple[date, date],
    source_available_at: datetime,
    capture_id: str,
) -> tuple[DailyMarketDataCashDistribution, ...]:
    _validate_known_fields(response, _DIVIDEND_TOP_LEVEL_FIELDS, "DIVIDEND_RESPONSE")
    _validate_common_response_metadata(
        response,
        member=member,
        role=DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
        capture_id=capture_id,
    )
    results = _results_list(
        response,
        role=DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
        capture_id=capture_id,
    )
    _validate_count_metadata(
        response,
        results,
        role=DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
        capture_id=capture_id,
    )
    events: list[DailyMarketDataCashDistribution] = []
    seen_ids: set[str] = set()
    for index, row in enumerate(results):
        if not isinstance(row, dict):
            _validation_error(
                f"DIVIDEND_RESPONSE row {index} must be an object",
                capture_id=capture_id,
            )
        _validate_known_fields(
            row, _DIVIDEND_ROW_FIELDS, f"DIVIDEND_RESPONSE row {index}"
        )
        event_id = _required_non_empty_string(
            row, "id", role="DIVIDEND_RESPONSE", capture_id=capture_id
        )
        if event_id in seen_ids:
            _validation_error(
                "DIVIDEND_RESPONSE contains duplicate dividend id",
                capture_id=capture_id,
            )
        seen_ids.add(event_id)
        ticker = _required_non_empty_string(
            row, "ticker", role="DIVIDEND_RESPONSE", capture_id=capture_id
        )
        if ticker != instrument.symbol:
            _validation_error(
                "DIVIDEND_RESPONSE ticker must match capture symbol",
                capture_id=capture_id,
            )
        currency = _required_non_empty_string(
            row, "currency", role="DIVIDEND_RESPONSE", capture_id=capture_id
        )
        if currency != expected_currency:
            _validation_error(
                "DIVIDEND_RESPONSE currency must match adapter context",
                capture_id=capture_id,
            )
        ex_date = _required_provider_date(
            row, "ex_dividend_date", role="DIVIDEND_RESPONSE", capture_id=capture_id
        )
        if not requested_scope[0] <= ex_date <= requested_scope[1]:
            _validation_error(
                "DIVIDEND_RESPONSE ex date is outside requested coverage",
                capture_id=capture_id,
            )
        distribution_type = _required_non_empty_string(
            row, "distribution_type", role="DIVIDEND_RESPONSE", capture_id=capture_id
        )
        if distribution_type not in _DOCUMENTED_DISTRIBUTION_TYPES:
            raise MassiveUnsupportedSemanticError(
                "DIVIDEND_RESPONSE distribution_type is unsupported: "
                f"{distribution_type!r}"
            )
        if "declaration_date" in row and row["declaration_date"] is not None:
            _parse_provider_date(
                row["declaration_date"],
                field="declaration_date",
                role=DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
                capture_id=capture_id,
            )
        if "frequency" in row and row["frequency"] is not None:
            _required_integral(
                row,
                "frequency",
                role="DIVIDEND_RESPONSE",
                capture_id=capture_id,
                allow_decimal=False,
            )
        for field_name in (
            "historical_adjustment_factor",
            "split_adjusted_cash_amount",
        ):
            if field_name in row and row[field_name] is not None:
                _required_positive_decimal(
                    row, field_name, role="DIVIDEND_RESPONSE", capture_id=capture_id
                )
        try:
            events.append(
                DailyMarketDataCashDistribution(
                    schema_version=RESEARCH_SDK_CONTRACT_SCHEMA_VERSION,
                    event_id=event_id,
                    instrument_id=instrument.instrument_id,
                    source_event_reference=event_id,
                    source_available_at=source_available_at,
                    ex_date=ex_date,
                    amount=_required_positive_decimal(
                        row,
                        "cash_amount",
                        role="DIVIDEND_RESPONSE",
                        capture_id=capture_id,
                    ),
                    currency=currency,
                    record_date=_optional_provider_date(
                        row,
                        "record_date",
                        role=DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
                        capture_id=capture_id,
                    ),
                    payable_date=_optional_provider_date(
                        row,
                        "pay_date",
                        role=DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
                        capture_id=capture_id,
                    ),
                    announced_at=None,
                    distribution_classification=distribution_type,
                )
            )
        except ValidationError as exc:
            raise MassiveResponseValidationError(
                f"DIVIDEND_RESPONSE row {index} failed cash-distribution validation"
            ) from exc
    return tuple(events)


def _adapt_splits(
    response: Mapping[str, Any],
    *,
    member: DailyMarketDataSourceCaptureMemberMetadata,
    instrument: DailyMarketDataInstrument,
    symbol: str,
    requested_scope: tuple[date, date],
    source_available_at: datetime,
    capture_id: str,
) -> tuple[DailyMarketDataSplit | DailyMarketDataUnsupportedCorporateAction, ...]:
    _validate_known_fields(response, _SPLIT_TOP_LEVEL_FIELDS, "SPLIT_RESPONSE")
    _validate_common_response_metadata(
        response,
        member=member,
        role=DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
        capture_id=capture_id,
    )
    results = _results_list(
        response,
        role=DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
        capture_id=capture_id,
    )
    _validate_count_metadata(
        response,
        results,
        role=DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
        capture_id=capture_id,
    )
    events: list[DailyMarketDataSplit | DailyMarketDataUnsupportedCorporateAction] = []
    seen_ids: set[str] = set()
    for index, row in enumerate(results):
        if not isinstance(row, dict):
            _validation_error(
                f"SPLIT_RESPONSE row {index} must be an object", capture_id=capture_id
            )
        _validate_known_fields(row, _SPLIT_ROW_FIELDS, f"SPLIT_RESPONSE row {index}")
        event_id = _required_non_empty_string(
            row, "id", role="SPLIT_RESPONSE", capture_id=capture_id
        )
        if event_id in seen_ids:
            _validation_error(
                "SPLIT_RESPONSE contains duplicate split id", capture_id=capture_id
            )
        seen_ids.add(event_id)
        ticker = _required_non_empty_string(
            row, "ticker", role="SPLIT_RESPONSE", capture_id=capture_id
        )
        if ticker != symbol:
            _validation_error(
                "SPLIT_RESPONSE ticker must match capture symbol", capture_id=capture_id
            )
        execution_date = _required_provider_date(
            row, "execution_date", role="SPLIT_RESPONSE", capture_id=capture_id
        )
        if not requested_scope[0] <= execution_date <= requested_scope[1]:
            _validation_error(
                "SPLIT_RESPONSE execution date is outside requested coverage",
                capture_id=capture_id,
            )
        adjustment_type = _required_non_empty_string(
            row, "adjustment_type", role="SPLIT_RESPONSE", capture_id=capture_id
        )
        if (
            "historical_adjustment_factor" in row
            and row["historical_adjustment_factor"] is not None
        ):
            _required_positive_decimal(
                row,
                "historical_adjustment_factor",
                role="SPLIT_RESPONSE",
                capture_id=capture_id,
            )
        if adjustment_type in _ORDINARY_SPLIT_TYPES:
            numerator, denominator = _split_ratio(row, capture_id=capture_id)
            if numerator == denominator:
                _validation_error(
                    "SPLIT_RESPONSE 1:1 split ratio is not supported",
                    capture_id=capture_id,
                )
            if adjustment_type == "forward_split" and numerator <= denominator:
                _validation_error(
                    "forward_split ratio must be greater than 1", capture_id=capture_id
                )
            if adjustment_type == "reverse_split" and numerator >= denominator:
                _validation_error(
                    "reverse_split ratio must be less than 1", capture_id=capture_id
                )
            try:
                events.append(
                    DailyMarketDataSplit(
                        schema_version=RESEARCH_SDK_CONTRACT_SCHEMA_VERSION,
                        event_id=event_id,
                        instrument_id=instrument.instrument_id,
                        source_event_reference=event_id,
                        source_available_at=source_available_at,
                        effective_date=execution_date,
                        numerator=numerator,
                        denominator=denominator,
                    )
                )
            except ValidationError as exc:
                raise MassiveResponseValidationError(
                    "SPLIT_RESPONSE ordinary split failed contract validation"
                ) from exc
        else:
            if adjustment_type not in _DOCUMENTED_SPLIT_TYPES:
                _require_non_empty_string(adjustment_type, "adjustment_type")
            for field_name in ("split_from", "split_to"):
                if field_name in row and row[field_name] is not None:
                    _required_positive_decimal(
                        row,
                        field_name,
                        role="SPLIT_RESPONSE",
                        capture_id=capture_id,
                    )
            try:
                events.append(
                    DailyMarketDataUnsupportedCorporateAction(
                        schema_version=RESEARCH_SDK_CONTRACT_SCHEMA_VERSION,
                        event_id=event_id,
                        instrument_id=instrument.instrument_id,
                        source_event_reference=event_id,
                        source_available_at=source_available_at,
                        provider_event_type=adjustment_type,
                        effective_date=execution_date,
                        description=None,
                    )
                )
            except ValidationError as exc:
                raise MassiveResponseValidationError(
                    f"SPLIT_RESPONSE row {index} failed unsupported-event validation"
                ) from exc
    return tuple(events)


def _validate_common_response_metadata(
    response: Mapping[str, Any],
    *,
    member: DailyMarketDataSourceCaptureMemberMetadata,
    role: DailyMarketDataSourceCaptureRole,
    capture_id: str,
) -> None:
    if response.get("status") != "OK":
        _validation_error(f"{role.value} status must be OK", capture_id=capture_id)
    if "request_id" not in response:
        _validation_error(f"{role.value} request_id is required", capture_id=capture_id)
    response_request_id = _normalize_request_id(
        response["request_id"], role=role, capture_id=capture_id
    )
    if (
        member.api_request_id is not None
        and response_request_id != member.api_request_id
    ):
        _validation_error(
            f"{role.value} request_id does not match capture metadata",
            capture_id=capture_id,
        )
    if "next_url" not in response:
        return
    next_url = response["next_url"]
    if isinstance(next_url, str) and next_url:
        _validation_error(
            f"{role.value} has next_url pagination", capture_id=capture_id
        )
    _validation_error(
        f"{role.value} next_url must be absent unless pagination is present",
        capture_id=capture_id,
    )


def _normalize_request_id(
    value: object,
    *,
    role: DailyMarketDataSourceCaptureRole,
    capture_id: str,
) -> str:
    if type(value) is str:
        if not value.strip() or value != value.strip():
            _validation_error(
                (
                    f"{role.value} request_id must be non-empty without "
                    "surrounding whitespace"
                ),
                capture_id=capture_id,
            )
        return value
    if type(value) is int:
        return str(value)
    _validation_error(
        f"{role.value} request_id must be string or integer", capture_id=capture_id
    )


def _results_list(
    response: Mapping[str, Any],
    *,
    role: DailyMarketDataSourceCaptureRole,
    capture_id: str,
) -> list[Any]:
    results = response.get("results")
    if results is None:
        if _nonnegative_int(response.get("resultsCount"), field="resultsCount") == 0:
            return []
        _validation_error(
            f"{role.value} results list is required", capture_id=capture_id
        )
    if not isinstance(results, list):
        _validation_error(f"{role.value} results must be a list", capture_id=capture_id)
    return results


def _validate_count_metadata(
    response: Mapping[str, Any],
    results: Sequence[object],
    *,
    role: DailyMarketDataSourceCaptureRole,
    capture_id: str,
) -> None:
    if "queryCount" in response and response["queryCount"] is not None:
        _nonnegative_int(response["queryCount"], field="queryCount")
    if "resultsCount" in response and response["resultsCount"] is not None:
        results_count = _nonnegative_int(response["resultsCount"], field="resultsCount")
        if results_count != len(results):
            _validation_error(
                f"{role.value} resultsCount must match result row count",
                capture_id=capture_id,
            )


def _nonnegative_int(value: object, *, field: str) -> int:
    if type(value) is not int:
        raise MassiveResponseValidationError(f"{field} must be a nonnegative integer")
    if value < 0:
        raise MassiveResponseValidationError(f"{field} must be a nonnegative integer")
    return value


def _validate_known_fields(
    value: Mapping[str, Any],
    allowed: frozenset[str],
    context: str,
) -> None:
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise MassiveResponseValidationError(
            f"{context} contains unknown provider fields: {unexpected}"
        )


def _required_decimal(
    row: Mapping[str, Any],
    field: str,
    *,
    role: str,
    capture_id: str,
) -> Decimal:
    value = _required_value(row, field, role=role, capture_id=capture_id)
    if type(value) is int:
        return Decimal(value)
    if type(value) is Decimal:
        if not value.is_finite():
            _validation_error(f"{role} {field} must be finite", capture_id=capture_id)
        return value
    _validation_error(
        f"{role} {field} must be an exact JSON number", capture_id=capture_id
    )


def _required_positive_decimal(
    row: Mapping[str, Any],
    field: str,
    *,
    role: str,
    capture_id: str,
) -> Decimal:
    value = _required_decimal(row, field, role=role, capture_id=capture_id)
    if value <= 0:
        _validation_error(
            f"{role} {field} must be strictly positive", capture_id=capture_id
        )
    return value


def _required_integral(
    row: Mapping[str, Any],
    field: str,
    *,
    role: str,
    capture_id: str,
    allow_decimal: bool,
) -> int:
    value = _required_value(row, field, role=role, capture_id=capture_id)
    if type(value) is int:
        if value < 0:
            _validation_error(
                f"{role} {field} must be nonnegative", capture_id=capture_id
            )
        return value
    if allow_decimal and isinstance(value, Decimal):
        if not value.is_finite() or value < 0 or value != value.to_integral_value():
            _validation_error(
                f"{role} {field} must be an exact nonnegative integer",
                capture_id=capture_id,
            )
        return int(value)
    _validation_error(
        f"{role} {field} must be an exact nonnegative integer", capture_id=capture_id
    )


def _required_epoch_millis(
    row: Mapping[str, Any],
    field: str,
    *,
    role: str,
    capture_id: str,
) -> int:
    value = _required_value(row, field, role=role, capture_id=capture_id)
    if type(value) is not int or value < 0:
        _validation_error(
            f"{role} {field} must be a nonnegative integer millisecond timestamp",
            capture_id=capture_id,
        )
    try:
        _datetime_from_epoch_millis(value)
    except (OSError, OverflowError, ValueError) as exc:
        raise MassiveResponseValidationError(
            f"{role} {field} timestamp is out of range"
        ) from exc
    return value


def _session_date_from_massive_timestamp(milliseconds: int) -> date:
    return _datetime_from_epoch_millis(milliseconds).astimezone(_NEW_YORK).date()


def _datetime_from_epoch_millis(milliseconds: int) -> datetime:
    seconds, remainder_ms = divmod(milliseconds, 1000)
    return datetime.fromtimestamp(seconds, tz=UTC) + timedelta(
        milliseconds=remainder_ms
    )


def _required_non_empty_string(
    row: Mapping[str, Any],
    field: str,
    *,
    role: str,
    capture_id: str,
) -> str:
    value = _required_value(row, field, role=role, capture_id=capture_id)
    return _require_non_empty_string(value, f"{role} {field}")


def _require_non_empty_string(value: object, field: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise MassiveResponseValidationError(
            f"{field} must be a non-empty string without surrounding whitespace"
        )
    return value


def _required_value(
    row: Mapping[str, Any],
    field: str,
    *,
    role: str,
    capture_id: str,
) -> object:
    if field not in row or row[field] is None:
        _validation_error(f"{role} {field} is required", capture_id=capture_id)
    return row[field]


def _required_provider_date(
    row: Mapping[str, Any],
    field: str,
    *,
    role: str,
    capture_id: str,
) -> date:
    return _parse_provider_date(
        _required_value(row, field, role=role, capture_id=capture_id),
        field=field,
        role=DailyMarketDataSourceCaptureRole(role),
        capture_id=capture_id,
    )


def _optional_provider_date(
    row: Mapping[str, Any],
    field: str,
    *,
    role: DailyMarketDataSourceCaptureRole,
    capture_id: str,
) -> date | None:
    if field not in row or row[field] is None:
        return None
    return _parse_provider_date(
        row[field], field=field, role=role, capture_id=capture_id
    )


def _parse_provider_date(
    value: object,
    *,
    field: str,
    role: DailyMarketDataSourceCaptureRole,
    capture_id: str,
) -> date:
    if type(value) is not str or _DATE_PATTERN.fullmatch(value) is None:
        _validation_error(
            f"{role.value} {field} must use YYYY-MM-DD",
            capture_id=capture_id,
        )
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise MassiveResponseValidationError(
            f"{role.value} {field} must be a valid calendar date"
        ) from exc


def _split_ratio(
    row: Mapping[str, Any],
    *,
    capture_id: str,
) -> tuple[int, int]:
    split_to = _required_positive_decimal(
        row, "split_to", role="SPLIT_RESPONSE", capture_id=capture_id
    )
    split_from = _required_positive_decimal(
        row, "split_from", role="SPLIT_RESPONSE", capture_id=capture_id
    )
    numerator_raw, numerator_scale = _decimal_integer_ratio(split_to)
    denominator_raw, denominator_scale = _decimal_integer_ratio(split_from)
    numerator = numerator_raw * denominator_scale
    denominator = denominator_raw * numerator_scale
    divisor = gcd(numerator, denominator)
    return numerator // divisor, denominator // divisor


def _decimal_integer_ratio(value: Decimal) -> tuple[int, int]:
    if not value.is_finite() or value <= 0:
        raise MassiveResponseValidationError(
            "split ratio values must be positive finite numbers"
        )
    numerator, denominator = value.as_integer_ratio()
    return numerator, denominator


def _canonicalize_events(
    events: tuple[DailyMarketDataCorporateActionEvent, ...],
    capture_id: str,
) -> tuple[DailyMarketDataCorporateActionEvent, ...]:
    event_ids = tuple(event.event_id for event in events)
    if len(set(event_ids)) != len(event_ids):
        _validation_error(
            "corporate action event IDs must be unique across endpoints",
            capture_id=capture_id,
        )
    return tuple(sorted(events, key=corporate_action_event_sort_key))


def _validation_error(message: str, *, capture_id: str | None = None) -> NoReturn:
    if capture_id is not None:
        raise MassiveResponseValidationError(f"source capture {capture_id}: {message}")
    raise MassiveResponseValidationError(message)


__all__ = [
    "MASSIVE_BAR_ENDPOINT_FAMILY",
    "MASSIVE_BAR_ENDPOINT_VERSION",
    "MASSIVE_DAILY_MARKET_DATA_ADAPTER_VERSION",
    "MASSIVE_DIVIDEND_ENDPOINT_FAMILY",
    "MASSIVE_DIVIDEND_ENDPOINT_VERSION",
    "MASSIVE_PROVIDER",
    "MASSIVE_SOURCE_FAMILY",
    "MASSIVE_SPLIT_ENDPOINT_FAMILY",
    "MASSIVE_SPLIT_ENDPOINT_VERSION",
    "AdaptedMassiveDailyMarketData",
    "MassiveDailyMarketDataAdapterDiagnostic",
    "MassiveDailyMarketDataAdapterDiagnosticResult",
    "MassiveDailyMarketDataAdapterContext",
    "MassiveDailyMarketDataAdapterError",
    "MassiveResponseParsingError",
    "MassiveResponseValidationError",
    "MassiveUnsupportedSemanticError",
    "adapt_massive_daily_market_data_source_capture",
    "adapt_massive_daily_market_data_source_capture_with_diagnostics",
]
