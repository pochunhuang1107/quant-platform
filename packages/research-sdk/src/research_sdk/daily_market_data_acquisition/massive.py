"""Bounded Massive daily-market-data acquisition and source-capture planning."""

from __future__ import annotations

import json
import re
import ssl
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from http.client import HTTPSConnection, IncompleteRead
from math import isfinite
from time import monotonic
from typing import Any, NoReturn, Protocol, SupportsIndex
from urllib.parse import quote, urlencode

from research_sdk.contracts.daily_market_data import DailyMarketDataInstrument
from research_sdk.daily_market_data_adapters.massive import (
    MASSIVE_BAR_ENDPOINT_FAMILY,
    MASSIVE_BAR_ENDPOINT_VERSION,
    MASSIVE_DIVIDEND_ENDPOINT_FAMILY,
    MASSIVE_DIVIDEND_ENDPOINT_VERSION,
    MASSIVE_PROVIDER,
    MASSIVE_SOURCE_FAMILY,
    MASSIVE_SPLIT_ENDPOINT_FAMILY,
    MASSIVE_SPLIT_ENDPOINT_VERSION,
)
from research_sdk.daily_market_data_source_capture.models import (
    DailyMarketDataSourceCaptureMemberInput,
    DailyMarketDataSourceCaptureRole,
)
from research_sdk.daily_market_data_source_capture.planning import (
    PlannedDailyMarketDataSourceCapture,
    plan_daily_market_data_source_capture,
)

_MASSIVE_API_HOST = "api.massive.com"
_MASSIVE_API_ORIGIN = f"https://{_MASSIVE_API_HOST}"
_CONNECT_TIMEOUT_SECONDS = 5.0
_READ_INACTIVITY_TIMEOUT_SECONDS = 15.0
_OVERALL_REQUEST_DEADLINE_SECONDS = 30.0
_READ_CHUNK_SIZE_BYTES = 64 * 1024
_BAR_RESPONSE_SIZE_LIMIT_BYTES = 4 * 1024 * 1024
_CORPORATE_ACTION_RESPONSE_SIZE_LIMIT_BYTES = 2 * 1024 * 1024
_INSTRUMENT_RESPONSE_SIZE_LIMIT_BYTES = 8 * 1024 * 1024
_PAIR_RESPONSE_SIZE_LIMIT_BYTES = 16 * 1024 * 1024
_MAX_DATE_SPAN_DAYS = 365
_JSON_MEDIA_TYPE = "application/json"
_CANONICAL_NONNEGATIVE_INTEGER = re.compile(r"^(?:0|[1-9][0-9]*)$")
_HTTP_TOKEN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_HTTP_QUOTED_VALUE = re.compile(r'^"(?:[\x20-\x21\x23-\x5b\x5d-\x7e]|\\[\x20-\x7e])*"$')
_FAILED_OPERATION = object()

_CAPTURE_LIMITATIONS = (
    "historical Massive evidence uses latest-known semantics and is not "
    "point-in-time evidence",
    "pagination following is intentionally unsupported; each captured endpoint "
    "must complete in one provider page",
    "expected exchange sessions are validated independently downstream and are "
    "not inferred from provider responses",
)

_ENDPOINT_AUTHORITY = {
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
}


class MassiveDailyMarketDataAcquisitionError(ValueError):
    """Base error for bounded Massive daily-market-data acquisition."""


class MassiveDailyMarketDataTransportError(MassiveDailyMarketDataAcquisitionError):
    """Raised when the fixed-host HTTPS transport cannot complete safely."""


class MassiveDailyMarketDataResponseError(MassiveDailyMarketDataAcquisitionError):
    """Raised when a provider response fails the operational envelope policy."""


class MassiveApiCredential:
    """Runtime-only Massive API credential with permanently redacted rendering."""

    __slots__ = ("_value",)
    _value: str

    def __init__(self, value: str) -> None:
        object.__setattr__(self, "_value", _validate_credential_value(value))

    def __setattr__(self, name: str, value: object) -> NoReturn:
        raise AttributeError("MassiveApiCredential is immutable")

    def __repr__(self) -> str:
        return "MassiveApiCredential(<redacted>)"

    def __str__(self) -> str:
        return "MassiveApiCredential(<redacted>)"

    def __reduce__(self) -> NoReturn:
        raise TypeError("MassiveApiCredential cannot be serialized")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        raise TypeError("MassiveApiCredential cannot be serialized")

    def __getstate__(self) -> NoReturn:
        raise TypeError("MassiveApiCredential cannot be serialized")


@dataclass(frozen=True, repr=False)
class MassiveDailyMarketDataAcquisitionRequest:
    """One canonical fixed-host Massive request and its persistent authority."""

    role: DailyMarketDataSourceCaptureRole
    path: str
    query_parameters: tuple[tuple[str, str], ...]
    request_parameters: tuple[tuple[str, str], ...]
    requested_scope: tuple[tuple[str, str], ...]
    sanitized_source_reference: str
    response_size_limit_bytes: int

    def __repr__(self) -> str:
        return "MassiveDailyMarketDataAcquisitionRequest(<redacted-authority>)"


@dataclass(frozen=True, repr=False)
class MassiveDailyMarketDataInstrumentAcquisitionPlan:
    """Credential-free canonical request plan for one daily-stock instrument."""

    instrument: DailyMarketDataInstrument
    start_date: date
    end_date: date
    acquisition_batch_id: str
    requests: tuple[MassiveDailyMarketDataAcquisitionRequest, ...]

    def __repr__(self) -> str:
        return "MassiveDailyMarketDataInstrumentAcquisitionPlan(<redacted-authority>)"


@dataclass(frozen=True, repr=False)
class PlannedMassiveDailyMarketDataSourceCapturePair:
    """Two complete in-memory source-capture plans from one acquisition batch."""

    asset: PlannedDailyMarketDataSourceCapture
    benchmark: PlannedDailyMarketDataSourceCapture

    def __repr__(self) -> str:
        return "PlannedMassiveDailyMarketDataSourceCapturePair(<redacted-authority>)"


@dataclass(frozen=True, repr=False)
class MassiveDailyMarketDataHttpResponse:
    """Exact bounded HTTP response returned by an acquisition transport."""

    status_code: int
    headers: tuple[tuple[str, str], ...]
    body: bytes

    def __repr__(self) -> str:
        return "MassiveDailyMarketDataHttpResponse(<redacted-response>)"


class MassiveDailyMarketDataHttpTransport(Protocol):
    """Fakeable Massive GET transport boundary."""

    def get(
        self,
        *,
        request: MassiveDailyMarketDataAcquisitionRequest,
        credential: MassiveApiCredential,
    ) -> MassiveDailyMarketDataHttpResponse:
        """Return one exact bounded response for a canonical request."""


@dataclass(frozen=True)
class _AcceptedResponse:
    body: bytes
    api_request_id: str
    media_type: str


@dataclass(frozen=True)
class _CompletedInstrumentAcquisition:
    plan: PlannedDailyMarketDataSourceCapture
    response_size_bytes: int


@dataclass
class _RequestDeadline:
    deadline_at: float
    last_observed_at: float


def plan_massive_daily_market_data_acquisition(
    *,
    instrument: DailyMarketDataInstrument,
    start_date: date,
    end_date: date,
    acquisition_batch_id: str,
) -> MassiveDailyMarketDataInstrumentAcquisitionPlan:
    """Build the canonical credential-free three-request Massive plan."""

    canonical_instrument = _capture_instrument(instrument)
    start = _require_exact_date(start_date, "start_date")
    end = _require_exact_date(end_date, "end_date")
    if end < start:
        raise MassiveDailyMarketDataAcquisitionError(
            "end_date must be greater than or equal to start_date"
        )
    if (end - start).days > _MAX_DATE_SPAN_DAYS:
        raise MassiveDailyMarketDataAcquisitionError(
            "Massive acquisition range must contain at most 366 calendar days"
        )
    batch_id = _require_batch_id(acquisition_batch_id)
    symbol = canonical_instrument.symbol
    encoded_symbol: object = _FAILED_OPERATION
    try:
        encoded_symbol = quote(symbol, safe="")
    except (UnicodeEncodeError, UnicodeDecodeError, TypeError):
        pass
    if type(encoded_symbol) is not str:
        raise MassiveDailyMarketDataAcquisitionError(
            "instrument symbol cannot be encoded as a Massive path segment"
        )
    start_text = start.isoformat()
    end_text = end.isoformat()

    bar_path = f"/v2/aggs/ticker/{encoded_symbol}/range/1/day/{start_text}/{end_text}"
    requests = (
        MassiveDailyMarketDataAcquisitionRequest(
            role=DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
            path=bar_path,
            query_parameters=(
                ("adjusted", "false"),
                ("limit", "50000"),
                ("sort", "asc"),
            ),
            request_parameters=(
                ("adjusted", "false"),
                ("from", start_text),
                ("limit", "50000"),
                ("multiplier", "1"),
                ("sort", "asc"),
                ("ticker", symbol),
                ("timespan", "day"),
                ("to", end_text),
            ),
            requested_scope=(
                ("from", start_text),
                ("ticker", symbol),
                ("to", end_text),
            ),
            sanitized_source_reference=f"{_MASSIVE_API_ORIGIN}{bar_path}",
            response_size_limit_bytes=_BAR_RESPONSE_SIZE_LIMIT_BYTES,
        ),
        MassiveDailyMarketDataAcquisitionRequest(
            role=DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
            path="/stocks/v1/dividends",
            query_parameters=(
                ("ex_dividend_date.gte", start_text),
                ("ex_dividend_date.lte", end_text),
                ("limit", "5000"),
                ("sort", "ex_dividend_date.asc"),
                ("ticker", symbol),
            ),
            request_parameters=(
                ("ex_dividend_date.gte", start_text),
                ("ex_dividend_date.lte", end_text),
                ("limit", "5000"),
                ("sort", "ex_dividend_date.asc"),
                ("ticker", symbol),
            ),
            requested_scope=(
                ("ex_dividend_date.gte", start_text),
                ("ex_dividend_date.lte", end_text),
                ("ticker", symbol),
            ),
            sanitized_source_reference=(f"{_MASSIVE_API_ORIGIN}/stocks/v1/dividends"),
            response_size_limit_bytes=_CORPORATE_ACTION_RESPONSE_SIZE_LIMIT_BYTES,
        ),
        MassiveDailyMarketDataAcquisitionRequest(
            role=DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
            path="/stocks/v1/splits",
            query_parameters=(
                ("execution_date.gte", start_text),
                ("execution_date.lte", end_text),
                ("limit", "5000"),
                ("sort", "execution_date.asc"),
                ("ticker", symbol),
            ),
            request_parameters=(
                ("execution_date.gte", start_text),
                ("execution_date.lte", end_text),
                ("limit", "5000"),
                ("sort", "execution_date.asc"),
                ("ticker", symbol),
            ),
            requested_scope=(
                ("execution_date.gte", start_text),
                ("execution_date.lte", end_text),
                ("ticker", symbol),
            ),
            sanitized_source_reference=f"{_MASSIVE_API_ORIGIN}/stocks/v1/splits",
            response_size_limit_bytes=_CORPORATE_ACTION_RESPONSE_SIZE_LIMIT_BYTES,
        ),
    )
    return MassiveDailyMarketDataInstrumentAcquisitionPlan(
        instrument=canonical_instrument,
        start_date=start,
        end_date=end,
        acquisition_batch_id=batch_id,
        requests=requests,
    )


def acquire_and_plan_massive_daily_market_data_source_capture_pair(
    *,
    asset_plan: MassiveDailyMarketDataInstrumentAcquisitionPlan,
    benchmark_plan: MassiveDailyMarketDataInstrumentAcquisitionPlan,
    credential: MassiveApiCredential,
    transport: MassiveDailyMarketDataHttpTransport | None = None,
    clock: Callable[[], datetime] | None = None,
) -> PlannedMassiveDailyMarketDataSourceCapturePair:
    """Acquire six bounded responses and return two plans only after full success."""

    canonical_asset = _capture_and_rederive_plan(asset_plan, "asset_plan")
    canonical_benchmark = _capture_and_rederive_plan(benchmark_plan, "benchmark_plan")
    _validate_pair_authority(canonical_asset, canonical_benchmark)
    secret = _capture_credential(credential)
    _require_credential_absent_from_plan(secret, canonical_asset)
    _require_credential_absent_from_plan(secret, canonical_benchmark)
    preserve_internal_transport_errors = transport is None
    effective_transport = (
        _StdlibMassiveDailyMarketDataHttpTransport(secret)
        if transport is None
        else transport
    )
    effective_clock = _utc_now if clock is None else clock

    asset = _acquire_instrument(
        plan=canonical_asset,
        secret=secret,
        transport=effective_transport,
        clock=effective_clock,
        preserve_internal_transport_errors=preserve_internal_transport_errors,
    )
    benchmark = _acquire_instrument(
        plan=canonical_benchmark,
        secret=secret,
        transport=effective_transport,
        clock=effective_clock,
        preserve_internal_transport_errors=preserve_internal_transport_errors,
    )
    if asset.response_size_bytes + benchmark.response_size_bytes > (
        _PAIR_RESPONSE_SIZE_LIMIT_BYTES
    ):
        raise MassiveDailyMarketDataResponseError(
            "Massive pair response bytes exceed the 16 MiB acquisition limit"
        )
    return PlannedMassiveDailyMarketDataSourceCapturePair(
        asset=asset.plan,
        benchmark=benchmark.plan,
    )


class _StdlibMassiveDailyMarketDataHttpTransport:
    """Fixed-host stdlib HTTPS transport with bounded exact-body reads."""

    __slots__ = ("_credential_value",)

    def __init__(self, credential_value: str) -> None:
        self._credential_value = _validate_credential_value(credential_value)

    def get(
        self,
        *,
        request: MassiveDailyMarketDataAcquisitionRequest,
        credential: MassiveApiCredential,
    ) -> MassiveDailyMarketDataHttpResponse:
        secret = self._credential_value
        target = request.path
        if request.query_parameters:
            target = f"{target}?{urlencode(request.query_parameters)}"
        headers = {
            "Authorization": f"Bearer {secret}",
            "Accept": _JSON_MEDIA_TYPE,
            "Accept-Encoding": "identity",
            "Connection": "close",
        }
        deadline = _start_request_deadline()
        connection: Any | None = None
        response: Any | None = None
        try:
            connect_failed = False
            try:
                connection = HTTPSConnection(
                    _MASSIVE_API_HOST,
                    timeout=_CONNECT_TIMEOUT_SECONDS,
                    context=ssl.create_default_context(),
                )
                connection.timeout = min(
                    _CONNECT_TIMEOUT_SECONDS,
                    _observe_request_deadline(deadline),
                )
                connection.connect()
                socket = connection.sock
                if socket is None:
                    raise MassiveDailyMarketDataTransportError(
                        "Massive HTTPS connection did not expose a connected socket"
                    )
            except MassiveDailyMarketDataAcquisitionError:
                raise
            except Exception:
                connect_failed = True
            if connect_failed or connection is None:
                raise MassiveDailyMarketDataTransportError(
                    "Massive HTTPS connect failed for "
                    f"{request.role.value} at {request.path}"
                ) from None

            request_send_failed = False
            try:
                _set_next_socket_timeout(socket, deadline)
                connection.request("GET", target, headers=headers)
            except MassiveDailyMarketDataAcquisitionError:
                raise
            except Exception:
                request_send_failed = True
            if request_send_failed:
                raise MassiveDailyMarketDataTransportError(
                    "Massive HTTPS request send failed for "
                    f"{request.role.value} at {request.path}"
                ) from None

            response_headers_failed = False
            declared_length: int | None = None
            try:
                _set_next_socket_timeout(socket, deadline)
                response = connection.getresponse()
                _observe_request_deadline(deadline)
                status_code = response.status
                response_headers = tuple(response.getheaders())
                if type(status_code) is not int:
                    raise MassiveDailyMarketDataResponseError(
                        "Massive HTTP status must be an exact integer"
                    )
                _validate_header_runtime_shape(response_headers)
                if status_code == 200:
                    declared_length = _parse_content_length(
                        response_headers,
                        response_size_limit_bytes=request.response_size_limit_bytes,
                    )
            except MassiveDailyMarketDataAcquisitionError:
                raise
            except Exception:
                response_headers_failed = True
            if response_headers_failed:
                raise MassiveDailyMarketDataTransportError(
                    "Massive HTTPS response headers failed for "
                    f"{request.role.value} at {request.path}"
                ) from None

            if status_code != 200:
                return MassiveDailyMarketDataHttpResponse(
                    status_code=status_code,
                    headers=response_headers,
                    body=b"",
                )

            response_body_failed = False
            body: bytes | None = None
            try:
                body = _read_bounded_body(
                    response=response,
                    socket=socket,
                    deadline=deadline,
                    role=request.role,
                    path=request.path,
                    response_size_limit_bytes=request.response_size_limit_bytes,
                )
            except MassiveDailyMarketDataAcquisitionError:
                raise
            except Exception:
                response_body_failed = True
            if response_body_failed:
                raise MassiveDailyMarketDataTransportError(
                    "Massive HTTPS response body read failed for "
                    f"{request.role.value} at {request.path}"
                ) from None
            if body is None:
                raise MassiveDailyMarketDataTransportError(
                    f"Massive HTTPS GET produced no result for {request.role.value}"
                )
            if declared_length is not None and len(body) != declared_length:
                raise MassiveDailyMarketDataResponseError(
                    "Massive response body length does not match Content-Length"
                )
            return MassiveDailyMarketDataHttpResponse(
                status_code=status_code,
                headers=response_headers,
                body=body,
            )
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass


def _capture_instrument(value: object) -> DailyMarketDataInstrument:
    if not isinstance(value, DailyMarketDataInstrument):
        raise MassiveDailyMarketDataAcquisitionError(
            "instrument must be DailyMarketDataInstrument"
        )
    instrument_id = value.instrument_id
    symbol = value.symbol
    venue = value.venue
    if any(type(item) is not str for item in (instrument_id, symbol, venue)):
        raise MassiveDailyMarketDataAcquisitionError(
            "instrument authority must contain exact string values"
        )
    captured: object = _FAILED_OPERATION
    try:
        captured = DailyMarketDataInstrument(
            instrument_id=instrument_id,
            symbol=symbol,
            venue=venue,
        )
    except Exception:
        pass
    if type(captured) is not DailyMarketDataInstrument:
        raise MassiveDailyMarketDataAcquisitionError("instrument authority is invalid")
    return captured


def _require_exact_date(value: object, field: str) -> date:
    if type(value) is not date:
        raise MassiveDailyMarketDataAcquisitionError(f"{field} must be an exact date")
    return value


def _require_batch_id(value: object) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise MassiveDailyMarketDataAcquisitionError(
            "acquisition_batch_id must be a nonempty exact string without "
            "surrounding whitespace"
        )
    if len(value) > 128:
        raise MassiveDailyMarketDataAcquisitionError(
            "acquisition_batch_id must be at most 128 characters"
        )
    if any(marker in value.lower() for marker in ("authorization", "bearer")):
        raise MassiveDailyMarketDataAcquisitionError(
            "acquisition_batch_id must not contain credential markers"
        )
    return value


def _capture_and_rederive_plan(
    value: object,
    field: str,
) -> MassiveDailyMarketDataInstrumentAcquisitionPlan:
    if type(value) is not MassiveDailyMarketDataInstrumentAcquisitionPlan:
        raise MassiveDailyMarketDataAcquisitionError(
            f"{field} must be an exact Massive acquisition plan"
        )
    instrument_value = value.instrument
    start_value = value.start_date
    end_value = value.end_date
    batch_value = value.acquisition_batch_id
    requests_value = value.requests
    instrument = _capture_instrument(instrument_value)
    start = _require_exact_date(start_value, f"{field}.start_date")
    end = _require_exact_date(end_value, f"{field}.end_date")
    batch_id = _require_batch_id(batch_value)
    requests = _capture_requests(requests_value, field)
    captured = MassiveDailyMarketDataInstrumentAcquisitionPlan(
        instrument=instrument,
        start_date=start,
        end_date=end,
        acquisition_batch_id=batch_id,
        requests=requests,
    )
    canonical = plan_massive_daily_market_data_acquisition(
        instrument=instrument,
        start_date=start,
        end_date=end,
        acquisition_batch_id=batch_id,
    )
    if captured != canonical:
        raise MassiveDailyMarketDataAcquisitionError(
            f"{field} does not match canonical Massive request authority"
        )
    return canonical


def _capture_requests(
    value: object,
    field: str,
) -> tuple[MassiveDailyMarketDataAcquisitionRequest, ...]:
    if type(value) is not tuple:
        raise MassiveDailyMarketDataAcquisitionError(
            f"{field}.requests must be an exact tuple"
        )
    captured: list[MassiveDailyMarketDataAcquisitionRequest] = []
    for item in value:
        if type(item) is not MassiveDailyMarketDataAcquisitionRequest:
            raise MassiveDailyMarketDataAcquisitionError(
                f"{field}.requests must contain exact acquisition requests"
            )
        role = item.role
        path = item.path
        query_parameters = item.query_parameters
        request_parameters = item.request_parameters
        requested_scope = item.requested_scope
        source_reference = item.sanitized_source_reference
        size_limit = item.response_size_limit_bytes
        if type(role) is not DailyMarketDataSourceCaptureRole:
            raise MassiveDailyMarketDataAcquisitionError(
                f"{field}.requests contain an invalid role"
            )
        if type(path) is not str or type(source_reference) is not str:
            raise MassiveDailyMarketDataAcquisitionError(
                f"{field}.requests contain invalid path authority"
            )
        if type(size_limit) is not int:
            raise MassiveDailyMarketDataAcquisitionError(
                f"{field}.requests contain an invalid response size limit"
            )
        captured.append(
            MassiveDailyMarketDataAcquisitionRequest(
                role=role,
                path=path,
                query_parameters=_capture_parameter_pairs(
                    query_parameters, f"{field}.query_parameters"
                ),
                request_parameters=_capture_parameter_pairs(
                    request_parameters, f"{field}.request_parameters"
                ),
                requested_scope=_capture_parameter_pairs(
                    requested_scope, f"{field}.requested_scope"
                ),
                sanitized_source_reference=source_reference,
                response_size_limit_bytes=size_limit,
            )
        )
    return tuple(captured)


def _capture_parameter_pairs(
    value: object,
    field: str,
) -> tuple[tuple[str, str], ...]:
    if type(value) is not tuple:
        raise MassiveDailyMarketDataAcquisitionError(f"{field} must be an exact tuple")
    captured: list[tuple[str, str]] = []
    for pair in value:
        if type(pair) is not tuple or len(pair) != 2:
            raise MassiveDailyMarketDataAcquisitionError(
                f"{field} must contain two-item exact tuples"
            )
        key, pair_value = pair
        if type(key) is not str or type(pair_value) is not str:
            raise MassiveDailyMarketDataAcquisitionError(
                f"{field} must contain exact string pairs"
            )
        captured.append((key, pair_value))
    return tuple(captured)


def _validate_pair_authority(
    asset: MassiveDailyMarketDataInstrumentAcquisitionPlan,
    benchmark: MassiveDailyMarketDataInstrumentAcquisitionPlan,
) -> None:
    if asset.acquisition_batch_id != benchmark.acquisition_batch_id:
        raise MassiveDailyMarketDataAcquisitionError(
            "asset and benchmark must share acquisition_batch_id"
        )
    if (asset.start_date, asset.end_date) != (
        benchmark.start_date,
        benchmark.end_date,
    ):
        raise MassiveDailyMarketDataAcquisitionError(
            "asset and benchmark must share the requested date range"
        )
    if asset.instrument.instrument_id == benchmark.instrument.instrument_id:
        raise MassiveDailyMarketDataAcquisitionError(
            "asset and benchmark instrument IDs must be distinct"
        )
    if asset.instrument.symbol == benchmark.instrument.symbol:
        raise MassiveDailyMarketDataAcquisitionError(
            "asset and benchmark symbols must be distinct"
        )


def _capture_credential(value: object) -> str:
    if type(value) is not MassiveApiCredential:
        raise MassiveDailyMarketDataAcquisitionError(
            "credential must be an exact MassiveApiCredential"
        )
    secret = value._value
    captured: object = _FAILED_OPERATION
    try:
        captured = _validate_credential_value(secret)
    except MassiveDailyMarketDataAcquisitionError:
        pass
    if type(captured) is not str:
        raise MassiveDailyMarketDataAcquisitionError(
            "Massive API credential authority is invalid"
        )
    return captured


def _validate_credential_value(value: object) -> str:
    if type(value) is not str:
        raise MassiveDailyMarketDataAcquisitionError(
            "Massive API credential must be an exact string"
        )
    if not value or value != value.strip():
        raise MassiveDailyMarketDataAcquisitionError(
            "Massive API credential must be nonempty without surrounding whitespace"
        )
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise MassiveDailyMarketDataAcquisitionError(
            "Massive API credential must not contain control characters"
        )
    encoded: object = _FAILED_OPERATION
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        pass
    if type(encoded) is not bytes:
        raise MassiveDailyMarketDataAcquisitionError(
            "Massive API credential must have a valid UTF-8 representation"
        )
    return value


def _require_credential_absent_from_plan(
    secret: str,
    plan: MassiveDailyMarketDataInstrumentAcquisitionPlan,
) -> None:
    values = [
        MASSIVE_PROVIDER,
        MASSIVE_SOURCE_FAMILY,
        plan.instrument.instrument_id,
        plan.instrument.symbol,
        plan.instrument.venue,
        plan.acquisition_batch_id,
        "200",
        _JSON_MEDIA_TYPE,
        *_CAPTURE_LIMITATIONS,
    ]
    for request in plan.requests:
        endpoint_family, endpoint_version = _ENDPOINT_AUTHORITY[request.role]
        values.extend(
            (
                request.role.value,
                endpoint_family,
                endpoint_version,
                request.path,
                request.sanitized_source_reference,
            )
        )
        values.extend(key for key, _value in request.request_parameters)
        values.extend(value for _key, value in request.request_parameters)
        values.extend(key for key, _value in request.requested_scope)
        values.extend(value for _key, value in request.requested_scope)
        values.extend(key for key, _value in request.query_parameters)
        values.extend(value for _key, value in request.query_parameters)
    _require_credential_absent(secret, values)


def _require_credential_absent(secret: str, values: list[str]) -> None:
    if any(secret in value for value in values):
        raise MassiveDailyMarketDataAcquisitionError(
            "Massive API credential must not appear in persistent acquisition metadata"
        )


def _acquire_instrument(
    *,
    plan: MassiveDailyMarketDataInstrumentAcquisitionPlan,
    secret: str,
    transport: MassiveDailyMarketDataHttpTransport,
    clock: Callable[[], datetime],
    preserve_internal_transport_errors: bool,
) -> _CompletedInstrumentAcquisition:
    accepted: list[
        tuple[MassiveDailyMarketDataAcquisitionRequest, _AcceptedResponse]
    ] = []
    total_size = 0
    for request in plan.requests:
        response: object = _FAILED_OPERATION
        try:
            response = transport.get(
                request=request,
                credential=MassiveApiCredential(secret),
            )
        except MassiveDailyMarketDataAcquisitionError:
            if preserve_internal_transport_errors:
                raise
        except Exception:
            pass
        if response is _FAILED_OPERATION:
            raise MassiveDailyMarketDataTransportError(
                f"Massive transport failed for {request.role.value} at {request.path}"
            )
        member = _validate_response(
            response=response,
            request=request,
            secret=secret,
        )
        total_size += len(member.body)
        if total_size > _INSTRUMENT_RESPONSE_SIZE_LIMIT_BYTES:
            raise MassiveDailyMarketDataResponseError(
                f"Massive responses exceed the 8 MiB limit for {plan.instrument.symbol}"
            )
        accepted.append((request, member))
    observed_at_value: object = _FAILED_OPERATION
    try:
        observed_at_value = clock()
    except Exception:
        pass
    if observed_at_value is _FAILED_OPERATION:
        raise MassiveDailyMarketDataAcquisitionError(
            f"capture clock failed for {plan.instrument.symbol}"
        )
    observed_at = _require_capture_observed_at(observed_at_value)
    request_ids = [member.api_request_id for _request, member in accepted]
    _require_credential_absent(secret, request_ids)

    members = tuple(
        DailyMarketDataSourceCaptureMemberInput(
            role=request.role,
            endpoint_family=_ENDPOINT_AUTHORITY[request.role][0],
            endpoint_version=_ENDPOINT_AUTHORITY[request.role][1],
            request_parameters=request.request_parameters,
            requested_scope=request.requested_scope,
            sanitized_source_reference=request.sanitized_source_reference,
            content=member.body,
            http_status=200,
            media_type=member.media_type,
            api_request_id=member.api_request_id,
            limitations=(),
        )
        for request, member in accepted
    )
    planned: object = _FAILED_OPERATION
    try:
        planned = plan_daily_market_data_source_capture(
            provider=MASSIVE_PROVIDER,
            source_family=MASSIVE_SOURCE_FAMILY,
            instrument_id=plan.instrument.instrument_id,
            symbol=plan.instrument.symbol,
            capture_observed_at=observed_at,
            acquisition_batch_id=plan.acquisition_batch_id,
            members=members,
            limitations=_CAPTURE_LIMITATIONS,
        )
    except Exception:
        pass
    if planned is _FAILED_OPERATION:
        raise MassiveDailyMarketDataAcquisitionError(
            f"source-capture planning failed for {plan.instrument.symbol}"
        )
    if type(planned) is not PlannedDailyMarketDataSourceCapture:
        raise MassiveDailyMarketDataAcquisitionError(
            "source-capture planner returned an invalid result for "
            f"{plan.instrument.symbol}"
        )
    return _CompletedInstrumentAcquisition(
        plan=planned,
        response_size_bytes=total_size,
    )


def _validate_response(
    *,
    response: object,
    request: MassiveDailyMarketDataAcquisitionRequest,
    secret: str,
) -> _AcceptedResponse:
    if type(response) is not MassiveDailyMarketDataHttpResponse:
        raise MassiveDailyMarketDataResponseError(
            f"transport returned an invalid response for {request.role.value}"
        )
    status_code = response.status_code
    headers = response.headers
    body = response.body
    if type(status_code) is not int:
        raise MassiveDailyMarketDataResponseError(
            f"HTTP status must be an exact integer for {request.role.value}"
        )
    if status_code != 200:
        raise MassiveDailyMarketDataResponseError(
            f"Massive returned HTTP {status_code} for {request.role.value}"
        )
    _validate_header_runtime_shape(headers)
    if type(body) is not bytes:
        raise MassiveDailyMarketDataResponseError(
            f"response body must be exact bytes for {request.role.value}"
        )
    if len(body) > request.response_size_limit_bytes:
        raise MassiveDailyMarketDataResponseError(
            f"response exceeds the byte limit for {request.role.value}"
        )
    _require_json_media_type(headers)
    _require_identity_content_encoding(headers)
    declared_length = _parse_content_length(
        headers,
        response_size_limit_bytes=request.response_size_limit_bytes,
    )
    if declared_length is not None and declared_length != len(body):
        raise MassiveDailyMarketDataResponseError(
            f"response length does not match Content-Length for {request.role.value}"
        )
    if not body:
        raise MassiveDailyMarketDataResponseError(
            f"response body must not be empty for {request.role.value}"
        )
    if secret.encode("utf-8") in body:
        raise MassiveDailyMarketDataResponseError(
            f"response body contains credential material for {request.role.value}"
        )
    payload = _parse_operational_envelope(body, request.role)
    request_id = _normalize_request_id(payload, request.role)
    if secret in request_id:
        raise MassiveDailyMarketDataResponseError(
            f"provider request ID contains credential material for {request.role.value}"
        )
    return _AcceptedResponse(
        body=body,
        api_request_id=request_id,
        media_type=_JSON_MEDIA_TYPE,
    )


def _validate_header_runtime_shape(headers: object) -> None:
    if type(headers) is not tuple:
        raise MassiveDailyMarketDataResponseError(
            "Massive response headers must be an exact tuple"
        )
    for header in headers:
        if type(header) is not tuple or len(header) != 2:
            raise MassiveDailyMarketDataResponseError(
                "Massive response headers must contain exact two-item tuples"
            )
        name, value = header
        if type(name) is not str or type(value) is not str:
            raise MassiveDailyMarketDataResponseError(
                "Massive response header names and values must be exact strings"
            )


def _header_values(
    headers: tuple[tuple[str, str], ...],
    name: str,
) -> tuple[str, ...]:
    expected = name.casefold()
    return tuple(value for key, value in headers if key.casefold() == expected)


def _require_json_media_type(headers: tuple[tuple[str, str], ...]) -> None:
    values = _header_values(headers, "Content-Type")
    if len(values) != 1:
        raise MassiveDailyMarketDataResponseError(
            "Massive response requires exactly one Content-Type"
        )
    value = values[0]
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise MassiveDailyMarketDataResponseError(
            "Massive response Content-Type must not contain control characters"
        )
    parts = value.split(";")
    media_type = parts[0].strip().casefold()
    if media_type != _JSON_MEDIA_TYPE:
        raise MassiveDailyMarketDataResponseError(
            "Massive response Content-Type must be application/json"
        )
    for raw_parameter in parts[1:]:
        parameter = raw_parameter.strip()
        if not parameter or parameter.count("=") != 1:
            raise MassiveDailyMarketDataResponseError(
                "Massive response Content-Type parameters must be well formed"
            )
        name, parameter_value = (
            component.strip() for component in parameter.split("=", 1)
        )
        if _HTTP_TOKEN.fullmatch(name) is None or (
            _HTTP_TOKEN.fullmatch(parameter_value) is None
            and _HTTP_QUOTED_VALUE.fullmatch(parameter_value) is None
        ):
            raise MassiveDailyMarketDataResponseError(
                "Massive response Content-Type parameters must be well formed"
            )


def _require_identity_content_encoding(
    headers: tuple[tuple[str, str], ...],
) -> None:
    values = _header_values(headers, "Content-Encoding")
    if len(values) > 1:
        raise MassiveDailyMarketDataResponseError(
            "Massive response must not contain duplicate Content-Encoding"
        )
    if values and values[0].casefold() != "identity":
        raise MassiveDailyMarketDataResponseError(
            "Massive response Content-Encoding must be identity"
        )


def _parse_content_length(
    headers: tuple[tuple[str, str], ...],
    *,
    response_size_limit_bytes: int,
) -> int | None:
    values = _header_values(headers, "Content-Length")
    if len(values) > 1:
        raise MassiveDailyMarketDataResponseError(
            "Massive response must not contain duplicate Content-Length"
        )
    if not values:
        return None
    value = values[0]
    if _CANONICAL_NONNEGATIVE_INTEGER.fullmatch(value) is None:
        raise MassiveDailyMarketDataResponseError(
            "Massive response Content-Length must be a canonical nonnegative integer"
        )
    maximum_text = str(response_size_limit_bytes)
    if len(value) > len(maximum_text):
        raise MassiveDailyMarketDataResponseError(
            "Massive response Content-Length exceeds the role byte limit"
        )
    parsed = int(value)
    if parsed > response_size_limit_bytes:
        raise MassiveDailyMarketDataResponseError(
            "Massive response Content-Length exceeds the role byte limit"
        )
    return parsed


def _parse_operational_envelope(
    body: bytes,
    role: DailyMarketDataSourceCaptureRole,
) -> dict[str, Any]:
    payload: object = _FAILED_OPERATION
    try:
        text = body.decode("utf-8", errors="strict")
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_object_keys,
            parse_constant=_reject_json_constant,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        TypeError,
        RecursionError,
    ):
        pass
    if payload is _FAILED_OPERATION:
        raise MassiveDailyMarketDataResponseError(
            f"response is not strict JSON for {role.value}"
        )
    if type(payload) is not dict:
        raise MassiveDailyMarketDataResponseError(
            f"response must be a top-level JSON object for {role.value}"
        )
    status = payload.get("status")
    if type(status) is not str or status != "OK":
        raise MassiveDailyMarketDataResponseError(
            f"response status must be exact OK for {role.value}"
        )
    if "next_url" in payload:
        raise MassiveDailyMarketDataResponseError(
            f"pagination is unsupported for {role.value}"
        )
    return payload


def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for key, value in pairs:
        if key in parsed:
            raise ValueError("duplicate JSON object key")
        parsed[key] = value
    return parsed


def _reject_json_constant(value: str) -> NoReturn:
    raise ValueError(f"nonstandard JSON constant: {value}")


def _normalize_request_id(
    payload: dict[str, Any],
    role: DailyMarketDataSourceCaptureRole,
) -> str:
    if "request_id" not in payload:
        raise MassiveDailyMarketDataResponseError(
            f"response request_id is required for {role.value}"
        )
    value = payload["request_id"]
    if type(value) is int:
        return str(value)
    if type(value) is str and value and value == value.strip():
        return value
    raise MassiveDailyMarketDataResponseError(
        f"response request_id is invalid for {role.value}"
    )


def _require_capture_observed_at(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is not UTC:
        raise MassiveDailyMarketDataAcquisitionError(
            "capture clock must return an exact UTC datetime"
        )
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise MassiveDailyMarketDataAcquisitionError(
            "capture clock must return an exact UTC datetime"
        )
    return value


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _start_request_deadline() -> _RequestDeadline:
    started_at = _read_monotonic()
    deadline_at = started_at + _OVERALL_REQUEST_DEADLINE_SECONDS
    if not isfinite(deadline_at):
        raise MassiveDailyMarketDataTransportError(
            "Massive HTTPS monotonic deadline is invalid"
        )
    return _RequestDeadline(
        deadline_at=deadline_at,
        last_observed_at=started_at,
    )


def _read_monotonic() -> float:
    value: object = _FAILED_OPERATION
    try:
        value = monotonic()
    except Exception:
        pass
    if type(value) is not float or not isfinite(value):
        raise MassiveDailyMarketDataTransportError(
            "Massive HTTPS monotonic clock returned an invalid value"
        )
    return value


def _set_next_socket_timeout(socket: Any, deadline: _RequestDeadline) -> None:
    remaining = _observe_request_deadline(deadline)
    socket.settimeout(min(_READ_INACTIVITY_TIMEOUT_SECONDS, remaining))


def _observe_request_deadline(deadline: _RequestDeadline) -> float:
    current = _read_monotonic()
    if current < deadline.last_observed_at:
        raise MassiveDailyMarketDataTransportError(
            "Massive HTTPS monotonic clock moved backwards"
        )
    deadline.last_observed_at = current
    remaining = deadline.deadline_at - current
    if remaining <= 0:
        raise MassiveDailyMarketDataTransportError(
            "Massive HTTPS request exceeded the 30-second deadline"
        )
    return remaining


def _read_bounded_body(
    *,
    response: Any,
    socket: Any,
    deadline: _RequestDeadline,
    role: DailyMarketDataSourceCaptureRole,
    path: str,
    response_size_limit_bytes: int,
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        timeout_setup_failed = False
        try:
            _set_next_socket_timeout(socket, deadline)
        except MassiveDailyMarketDataAcquisitionError:
            raise
        except Exception:
            timeout_setup_failed = True
        if timeout_setup_failed:
            raise MassiveDailyMarketDataTransportError(
                "Massive HTTPS response body timeout setup failed for "
                f"{role.value} at {path}"
            ) from None
        read_size = min(
            _READ_CHUNK_SIZE_BYTES,
            response_size_limit_bytes + 1 - total,
        )
        chunk: object = _FAILED_OPERATION
        read_failure: str | None = None
        try:
            chunk = response.read(read_size)
        except Exception as error:
            read_failure = _classify_response_body_read_failure(error)
        if read_failure is not None:
            raise MassiveDailyMarketDataTransportError(
                f"Massive HTTPS response body {read_failure} for {role.value} at {path}"
            ) from None
        if type(chunk) is not bytes:
            raise MassiveDailyMarketDataResponseError(
                "Massive HTTPS response chunks must be exact bytes"
            )
        if not chunk:
            _observe_request_deadline(deadline)
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > response_size_limit_bytes:
            raise MassiveDailyMarketDataResponseError(
                "Massive HTTPS response exceeds the role byte limit"
            )
        if response.isclosed():
            _observe_request_deadline(deadline)
            return b"".join(chunks)


def _classify_response_body_read_failure(error: Exception) -> str:
    if type(error) is TimeoutError:
        return "read timed out"
    if type(error) is ssl.SSLEOFError:
        return "TLS EOF failed"
    if isinstance(error, ssl.SSLError):
        return "TLS read failed"
    if type(error) is IncompleteRead:
        return "incomplete"
    if isinstance(error, ConnectionError):
        return "connection read failed"
    return "read failed"


__all__ = [
    "MassiveApiCredential",
    "MassiveDailyMarketDataAcquisitionError",
    "MassiveDailyMarketDataAcquisitionRequest",
    "MassiveDailyMarketDataHttpResponse",
    "MassiveDailyMarketDataHttpTransport",
    "MassiveDailyMarketDataInstrumentAcquisitionPlan",
    "MassiveDailyMarketDataResponseError",
    "MassiveDailyMarketDataTransportError",
    "PlannedMassiveDailyMarketDataSourceCapturePair",
    "acquire_and_plan_massive_daily_market_data_source_capture_pair",
    "plan_massive_daily_market_data_acquisition",
]
