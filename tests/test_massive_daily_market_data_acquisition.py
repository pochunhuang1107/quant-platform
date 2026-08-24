from __future__ import annotations

import json
import pickle
import ssl
import subprocess
import sys
import traceback
from collections.abc import Callable
from dataclasses import fields, replace
from datetime import UTC, date, datetime, timedelta, timezone
from http.client import HTTPConnection, IncompleteRead
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

import pytest

import research_sdk.daily_market_data_acquisition.massive as acquisition_module
from research_sdk.contracts.daily_market_data import DailyMarketDataInstrument
from research_sdk.daily_market_data_acquisition import (
    MassiveApiCredential,
    MassiveDailyMarketDataAcquisitionError,
    MassiveDailyMarketDataAcquisitionRequest,
    MassiveDailyMarketDataHttpResponse,
    MassiveDailyMarketDataInstrumentAcquisitionPlan,
    MassiveDailyMarketDataResponseError,
    MassiveDailyMarketDataTransportError,
    acquire_and_plan_massive_daily_market_data_source_capture_pair,
    plan_massive_daily_market_data_acquisition,
)
from research_sdk.daily_market_data_adapters import (
    MassiveDailyMarketDataAdapterContext,
    MassiveResponseValidationError,
    adapt_massive_daily_market_data_source_capture,
    validate_massive_daily_market_data_capture_pair_compatibility,
)
from research_sdk.daily_market_data_source_capture import (
    DailyMarketDataSourceCaptureRole,
    verify_daily_market_data_source_capture,
)
from research_sdk.daily_market_data_storage.serialization import sha256_bytes

START = date(2024, 1, 2)
END = date(2024, 12, 31)
BATCH_ID = "synthetic-2024-pair"
CREDENTIAL_VALUE = "test-only-massive-key-Z9"
SECRET_SENTINEL = (
    f"SECRET_SENTINEL arbitrary external exception message Bearer {CREDENTIAL_VALUE}"
)
ASSET = DailyMarketDataInstrument(
    instrument_id="us-equity:QQQ",
    symbol="QQQ",
    venue="XNAS",
)
BENCHMARK = DailyMarketDataInstrument(
    instrument_id="us-equity:SPY",
    symbol="SPY",
    venue="ARCX",
)
ASSET_OBSERVED_AT = datetime(2026, 8, 20, 16, 0, tzinfo=UTC)
BENCHMARK_OBSERVED_AT = datetime(2026, 8, 20, 23, 0, tzinfo=UTC)
ROLE_ORDER = (
    DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
    DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
    DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
)


@pytest.fixture(autouse=True)
def forbid_real_https_connection(monkeypatch) -> None:
    class ForbiddenHttpsConnection:
        def __init__(self, *args, **kwargs) -> None:
            pytest.fail("S3c3c5 tests must never construct a real HTTPS connection")

    monkeypatch.setattr(
        acquisition_module,
        "HTTPSConnection",
        ForbiddenHttpsConnection,
    )


class FakeTransport:
    def __init__(
        self,
        response_factory: Callable[
            [MassiveDailyMarketDataAcquisitionRequest, int],
            MassiveDailyMarketDataHttpResponse,
        ]
        | None = None,
        *,
        fail_at: int | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.calls: list[MassiveDailyMarketDataAcquisitionRequest] = []
        self.credentials: list[MassiveApiCredential] = []
        self.response_factory = response_factory or valid_response
        self.fail_at = fail_at
        self.failure = failure or TimeoutError("unsafe provider detail")

    def get(
        self,
        *,
        request: MassiveDailyMarketDataAcquisitionRequest,
        credential: MassiveApiCredential,
    ) -> MassiveDailyMarketDataHttpResponse:
        self.calls.append(request)
        self.credentials.append(credential)
        if self.fail_at == len(self.calls):
            raise self.failure
        return self.response_factory(request, len(self.calls))


class CountingClock:
    def __init__(self, values: tuple[object, ...]) -> None:
        self.values = values
        self.calls = 0

    def __call__(self) -> object:
        value = self.values[self.calls]
        self.calls += 1
        return value


def instrument_plan(
    instrument: DailyMarketDataInstrument = ASSET,
    *,
    start: date = START,
    end: date = END,
    batch_id: str = BATCH_ID,
):
    return plan_massive_daily_market_data_acquisition(
        instrument=instrument,
        start_date=start,
        end_date=end,
        acquisition_batch_id=batch_id,
    )


def acquire_pair(
    *,
    transport: FakeTransport | Any | None = None,
    clock: Callable[[], datetime] | None = None,
    asset_plan=None,
    benchmark_plan=None,
    credential: MassiveApiCredential | None = None,
):
    return acquire_and_plan_massive_daily_market_data_source_capture_pair(
        asset_plan=asset_plan or instrument_plan(ASSET),
        benchmark_plan=benchmark_plan or instrument_plan(BENCHMARK),
        credential=credential or MassiveApiCredential(CREDENTIAL_VALUE),
        transport=FakeTransport() if transport is None else transport,
        clock=(
            CountingClock((ASSET_OBSERVED_AT, BENCHMARK_OBSERVED_AT))
            if clock is None
            else clock
        ),
    )


def valid_response(
    request: MassiveDailyMarketDataAcquisitionRequest,
    call_number: int,
) -> MassiveDailyMarketDataHttpResponse:
    symbol = dict(request.request_parameters)["ticker"]
    body = response_body(request.role, symbol, f"request-{call_number}")
    return MassiveDailyMarketDataHttpResponse(
        status_code=200,
        headers=(
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ),
        body=body,
    )


def response_body(
    role: DailyMarketDataSourceCaptureRole,
    symbol: str,
    request_id: str | int,
    *,
    extra: dict[str, object] | None = None,
) -> bytes:
    if role is DailyMarketDataSourceCaptureRole.BAR_RESPONSE:
        payload: dict[str, object] = {
            "adjusted": False,
            "queryCount": 0,
            "request_id": request_id,
            "results": [],
            "resultsCount": 0,
            "status": "OK",
            "ticker": symbol,
        }
    else:
        payload = {"request_id": request_id, "results": [], "status": "OK"}
    payload.update(extra or {})
    return (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode()


def http_response(
    body: bytes,
    *,
    status: int = 200,
    headers: tuple[tuple[str, str], ...] | None = None,
) -> MassiveDailyMarketDataHttpResponse:
    return MassiveDailyMarketDataHttpResponse(
        status_code=status,
        headers=headers
        if headers is not None
        else (
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
        ),
        body=body,
    )


def member_bytes(plan, role: DailyMarketDataSourceCaptureRole) -> bytes:
    return next(member.content for member in plan.member_bytes if member.role is role)


def test_plans_exact_qqq_2024_requests() -> None:
    plan = instrument_plan()

    assert plan.instrument == ASSET
    assert plan.start_date == START
    assert plan.end_date == END
    assert plan.acquisition_batch_id == BATCH_ID
    assert tuple(request.role for request in plan.requests) == ROLE_ORDER
    bars, dividends, splits = plan.requests
    assert bars.path == "/v2/aggs/ticker/QQQ/range/1/day/2024-01-02/2024-12-31"
    assert bars.query_parameters == (
        ("adjusted", "false"),
        ("limit", "50000"),
        ("sort", "asc"),
    )
    assert bars.request_parameters == (
        ("adjusted", "false"),
        ("from", "2024-01-02"),
        ("limit", "50000"),
        ("multiplier", "1"),
        ("sort", "asc"),
        ("ticker", "QQQ"),
        ("timespan", "day"),
        ("to", "2024-12-31"),
    )
    assert bars.requested_scope == (
        ("from", "2024-01-02"),
        ("ticker", "QQQ"),
        ("to", "2024-12-31"),
    )
    assert bars.sanitized_source_reference == (
        "https://api.massive.com/v2/aggs/ticker/QQQ/range/1/day/2024-01-02/2024-12-31"
    )
    assert bars.response_size_limit_bytes == 4 * 1024 * 1024
    assert dividends.path == "/stocks/v1/dividends"
    assert (
        dividends.query_parameters
        == dividends.request_parameters
        == (
            ("ex_dividend_date.gte", "2024-01-02"),
            ("ex_dividend_date.lte", "2024-12-31"),
            ("limit", "5000"),
            ("sort", "ex_dividend_date.asc"),
            ("ticker", "QQQ"),
        )
    )
    assert dividends.requested_scope == (
        ("ex_dividend_date.gte", "2024-01-02"),
        ("ex_dividend_date.lte", "2024-12-31"),
        ("ticker", "QQQ"),
    )
    assert dividends.sanitized_source_reference == (
        "https://api.massive.com/stocks/v1/dividends"
    )
    assert dividends.response_size_limit_bytes == 2 * 1024 * 1024
    assert splits.path == "/stocks/v1/splits"
    assert (
        splits.query_parameters
        == splits.request_parameters
        == (
            ("execution_date.gte", "2024-01-02"),
            ("execution_date.lte", "2024-12-31"),
            ("limit", "5000"),
            ("sort", "execution_date.asc"),
            ("ticker", "QQQ"),
        )
    )
    assert splits.requested_scope == (
        ("execution_date.gte", "2024-01-02"),
        ("execution_date.lte", "2024-12-31"),
        ("ticker", "QQQ"),
    )
    assert splits.sanitized_source_reference == (
        "https://api.massive.com/stocks/v1/splits"
    )
    assert splits.response_size_limit_bytes == 2 * 1024 * 1024


def test_spy_plan_uses_same_specification_with_its_semantic_symbol() -> None:
    plan = instrument_plan(BENCHMARK)

    assert plan.instrument.venue == "ARCX"
    assert dict(plan.requests[0].request_parameters)["ticker"] == "SPY"
    assert dict(plan.requests[1].requested_scope)["ticker"] == "SPY"
    assert "/SPY/" in plan.requests[0].path


def test_symbol_is_percent_encoded_only_in_path_and_reference() -> None:
    instrument = DailyMarketDataInstrument(
        instrument_id="synthetic:special",
        symbol="A/B C%",
        venue="TEST",
    )

    plan = instrument_plan(instrument)

    assert "/A%2FB%20C%25/" in plan.requests[0].path
    assert "/A%2FB%20C%25/" in plan.requests[0].sanitized_source_reference
    assert dict(plan.requests[0].request_parameters)["ticker"] == "A/B C%"
    assert dict(plan.requests[1].query_parameters)["ticker"] == "A/B C%"


@pytest.mark.parametrize(
    "symbol", ("A/B", "A?B", "A#B", "A%B", "A B", "A+B", "A&B", "A=B", "A密B")
)
def test_symbols_cannot_inject_path_query_or_host_authority(symbol: str) -> None:
    instrument = DailyMarketDataInstrument(
        instrument_id=f"synthetic:{symbol}",
        symbol=symbol,
        venue="TEST",
    )
    plan = instrument_plan(instrument)
    bars, dividends, splits = plan.requests
    encoded = quote(symbol, safe="")

    assert bars.path == (f"/v2/aggs/ticker/{encoded}/range/1/day/2024-01-02/2024-12-31")
    assert bars.path.startswith("/")
    assert not bars.path.startswith("//")
    assert urlsplit(bars.sanitized_source_reference).netloc == "api.massive.com"
    assert urlsplit(bars.sanitized_source_reference).query == ""
    assert dict(bars.request_parameters)["ticker"] == symbol
    assert dict(dividends.query_parameters)["ticker"] == symbol
    assert dict(splits.query_parameters)["ticker"] == symbol
    assert "apiKey" not in urlencode(dividends.query_parameters)


class DateSubclass(date):
    pass


@pytest.mark.parametrize(
    ("start", "end"),
    (
        (datetime(2024, 1, 2), END),
        (START, datetime(2024, 12, 31)),
        (True, END),
        (START, False),
        ("2024-01-02", END),
        (START, 20241231),
        (DateSubclass(2024, 1, 2), END),
        (START, DateSubclass(2024, 12, 31)),
    ),
)
def test_planning_rejects_non_exact_dates(start: object, end: object) -> None:
    with pytest.raises(MassiveDailyMarketDataAcquisitionError, match="exact date"):
        plan_massive_daily_market_data_acquisition(
            instrument=ASSET,
            start_date=start,  # type: ignore[arg-type]
            end_date=end,  # type: ignore[arg-type]
            acquisition_batch_id=BATCH_ID,
        )


def test_planning_range_is_inclusive_and_bounded_to_366_days() -> None:
    accepted = instrument_plan(start=date(2024, 1, 1), end=date(2024, 12, 31))
    assert (accepted.end_date - accepted.start_date).days == 365

    with pytest.raises(MassiveDailyMarketDataAcquisitionError, match="366"):
        instrument_plan(start=date(2024, 1, 1), end=date(2025, 1, 1))


def test_planning_rejects_reversed_range() -> None:
    with pytest.raises(MassiveDailyMarketDataAcquisitionError, match="end_date"):
        instrument_plan(start=END, end=START)


@pytest.mark.parametrize("batch_id", ("", "   ", " batch ", None, 123, "x" * 129))
def test_planning_rejects_invalid_batch_id(batch_id: object) -> None:
    with pytest.raises(MassiveDailyMarketDataAcquisitionError, match="batch_id"):
        plan_massive_daily_market_data_acquisition(
            instrument=ASSET,
            start_date=START,
            end_date=END,
            acquisition_batch_id=batch_id,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("batch_id", ("authorization-batch", "Bearer batch"))
def test_sensitive_batch_marker_is_rejected_during_credential_free_planning(
    batch_id: str,
) -> None:
    with pytest.raises(MassiveDailyMarketDataAcquisitionError, match="marker"):
        instrument_plan(batch_id=batch_id)


def test_unencodable_symbol_fails_with_a_deterministic_safe_error() -> None:
    instrument = DailyMarketDataInstrument.model_construct(
        instrument_id="synthetic:invalid-unicode",
        symbol="invalid-\ud800-symbol",
        venue="TEST",
    )

    with pytest.raises(MassiveDailyMarketDataAcquisitionError) as exc_info:
        instrument_plan(instrument)

    assert "invalid" in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


@pytest.mark.parametrize(
    "mutation",
    (
        lambda request: replace(request, path="/changed"),
        lambda request: replace(request, query_parameters=(("sort", "desc"),)),
        lambda request: replace(request, request_parameters=(("ticker", "QQQ"),)),
        lambda request: replace(request, requested_scope=(("ticker", "QQQ"),)),
        lambda request: replace(
            request, sanitized_source_reference="https://api.massive.com/changed"
        ),
        lambda request: replace(request, response_size_limit_bytes=1),
    ),
)
def test_tampered_plan_is_rejected_before_network(mutation) -> None:
    plan = instrument_plan(ASSET)
    requests = (mutation(plan.requests[0]), *plan.requests[1:])
    tampered = replace(plan, requests=requests)
    transport = FakeTransport()

    with pytest.raises(MassiveDailyMarketDataAcquisitionError, match="canonical"):
        acquire_pair(asset_plan=tampered, transport=transport)

    assert transport.calls == []


def test_both_plans_are_validated_before_first_request() -> None:
    benchmark = instrument_plan(BENCHMARK)
    tampered = replace(
        benchmark,
        requests=(replace(benchmark.requests[2], path="/changed"),),
    )
    transport = FakeTransport()

    with pytest.raises(MassiveDailyMarketDataAcquisitionError):
        acquire_pair(benchmark_plan=tampered, transport=transport)

    assert transport.calls == []


@pytest.mark.parametrize(
    "requests_factory",
    (
        lambda requests: (
            replace(requests[0], query_parameters=(("sort", "desc"),)),
            *requests[1:],
        ),
        lambda requests: (
            requests[0],
            requests[1],
            replace(requests[2], response_size_limit_bytes=1),
        ),
        lambda requests: requests[:2],
        lambda requests: (requests[0], requests[0], requests[2]),
        lambda requests: (requests[1], requests[0], requests[2]),
    ),
)
def test_every_benchmark_request_shape_is_checked_before_request_one(
    requests_factory,
) -> None:
    benchmark = instrument_plan(BENCHMARK)
    object.__setattr__(benchmark, "requests", requests_factory(benchmark.requests))
    transport = FakeTransport()

    with pytest.raises(MassiveDailyMarketDataAcquisitionError):
        acquire_pair(benchmark_plan=benchmark, transport=transport)

    assert transport.calls == []


def test_hostile_plan_and_nested_request_subclasses_fail_before_network() -> None:
    class PlanSubclass(type(instrument_plan())):
        pass

    class RequestSubclass(MassiveDailyMarketDataAcquisitionRequest):
        pass

    canonical = instrument_plan(BENCHMARK)
    plan_subclass = PlanSubclass(
        instrument=canonical.instrument,
        start_date=canonical.start_date,
        end_date=canonical.end_date,
        acquisition_batch_id=canonical.acquisition_batch_id,
        requests=canonical.requests,
    )
    request_subclass = RequestSubclass(**canonical.requests[0].__dict__)
    nested_subclass = replace(
        canonical,
        requests=(request_subclass, *canonical.requests[1:]),
    )

    for malformed in (plan_subclass, nested_subclass):
        transport = FakeTransport()
        with pytest.raises(MassiveDailyMarketDataAcquisitionError):
            acquire_pair(benchmark_plan=malformed, transport=transport)
        assert transport.calls == []


def test_batch_string_subclass_is_rejected_before_network() -> None:
    class StringSubclass(str):
        pass

    benchmark = instrument_plan(BENCHMARK)
    object.__setattr__(benchmark, "acquisition_batch_id", StringSubclass(BATCH_ID))
    transport = FakeTransport()

    with pytest.raises(MassiveDailyMarketDataAcquisitionError, match="batch_id"):
        acquire_pair(benchmark_plan=benchmark, transport=transport)

    assert transport.calls == []


def test_dynamic_instrument_authority_is_captured_once_before_rederivation() -> None:
    reads: dict[str, int] = {}

    class DynamicInstrument(DailyMarketDataInstrument):
        def __getattribute__(self, name: str):
            if name in {"instrument_id", "symbol", "venue"}:
                reads[name] = reads.get(name, 0) + 1
                if reads[name] > 1:
                    return f"spoofed-{name}"
            return super().__getattribute__(name)

    dynamic = DynamicInstrument(
        instrument_id=ASSET.instrument_id,
        symbol=ASSET.symbol,
        venue=ASSET.venue,
    )
    canonical = instrument_plan(ASSET)
    supplied = replace(canonical, instrument=dynamic)

    pair = acquire_pair(asset_plan=supplied)

    assert pair.asset.capture_manifest.instrument_id == ASSET.instrument_id
    assert reads == {"instrument_id": 1, "symbol": 1, "venue": 1}


def test_plan_and_request_authority_fields_are_each_captured_once(monkeypatch) -> None:
    asset = instrument_plan(ASSET)
    benchmark = instrument_plan(BENCHMARK)
    target_plan_id = id(benchmark)
    target_request_id = id(benchmark.requests[0])
    plan_reads: dict[str, int] = {}
    request_reads: dict[str, int] = {}
    plan_fields = {
        "instrument",
        "start_date",
        "end_date",
        "acquisition_batch_id",
        "requests",
    }
    request_fields = {
        "role",
        "path",
        "query_parameters",
        "request_parameters",
        "requested_scope",
        "sanitized_source_reference",
        "response_size_limit_bytes",
    }

    def plan_getattribute(self, name: str):
        if id(self) == target_plan_id and name in plan_fields:
            plan_reads[name] = plan_reads.get(name, 0) + 1
            if plan_reads[name] > 1:
                raise AssertionError(f"plan field reread: {name}")
        return object.__getattribute__(self, name)

    def request_getattribute(self, name: str):
        if id(self) == target_request_id and name in request_fields:
            request_reads[name] = request_reads.get(name, 0) + 1
            if request_reads[name] > 1:
                raise AssertionError(f"request field reread: {name}")
        return object.__getattribute__(self, name)

    monkeypatch.setattr(
        MassiveDailyMarketDataInstrumentAcquisitionPlan,
        "__getattribute__",
        plan_getattribute,
    )
    monkeypatch.setattr(
        MassiveDailyMarketDataAcquisitionRequest,
        "__getattribute__",
        request_getattribute,
    )

    pair = acquire_pair(asset_plan=asset, benchmark_plan=benchmark)

    assert pair.benchmark.capture_id
    assert plan_reads == {name: 1 for name in plan_fields}
    assert request_reads == {name: 1 for name in request_fields}


@pytest.mark.parametrize(
    "benchmark_plan",
    (
        instrument_plan(BENCHMARK, batch_id="different-batch"),
        instrument_plan(BENCHMARK, start=date(2024, 1, 3)),
        instrument_plan(
            DailyMarketDataInstrument(
                instrument_id=ASSET.instrument_id,
                symbol="SPY",
                venue="ARCX",
            )
        ),
        instrument_plan(
            DailyMarketDataInstrument(
                instrument_id="us-equity:other",
                symbol=ASSET.symbol,
                venue="ARCX",
            )
        ),
    ),
)
def test_pair_authority_failures_make_zero_requests(benchmark_plan) -> None:
    transport = FakeTransport()
    with pytest.raises(MassiveDailyMarketDataAcquisitionError):
        acquire_pair(benchmark_plan=benchmark_plan, transport=transport)
    assert transport.calls == []


@pytest.mark.parametrize(
    "value",
    (
        "",
        " key",
        "key ",
        "key\rvalue",
        "key\nvalue",
        "key\0value",
        "key\x1fvalue",
        123,
    ),
)
def test_credential_validation(value: object) -> None:
    with pytest.raises(MassiveDailyMarketDataAcquisitionError) as exc_info:
        MassiveApiCredential(value)  # type: ignore[arg-type]
    assert str(value) not in str(exc_info.value) or value == ""


def test_credential_rendering_and_identity_equality_are_secret_safe() -> None:
    first = MassiveApiCredential(CREDENTIAL_VALUE)
    second = MassiveApiCredential(CREDENTIAL_VALUE)

    assert repr(first) == "MassiveApiCredential(<redacted>)"
    assert str(first) == "MassiveApiCredential(<redacted>)"
    assert CREDENTIAL_VALUE not in repr(first)
    assert first != second


@pytest.mark.parametrize(
    "serialize",
    (
        lambda value: pickle.dumps(value),
        lambda value: value.__reduce__(),
        lambda value: value.__reduce_ex__(4),
        lambda value: value.__getstate__(),
    ),
)
def test_credential_cannot_be_serialized(serialize) -> None:
    credential = MassiveApiCredential(CREDENTIAL_VALUE)

    with pytest.raises(TypeError) as exc_info:
        serialize(credential)

    assert CREDENTIAL_VALUE not in str(exc_info.value)
    assert CREDENTIAL_VALUE not in repr(exc_info.value)


def test_credential_rejects_normal_attribute_mutation() -> None:
    credential = MassiveApiCredential(CREDENTIAL_VALUE)

    with pytest.raises(AttributeError):
        credential._value = "changed"  # type: ignore[misc]

    assert str(credential) == "MassiveApiCredential(<redacted>)"


def test_credential_rejects_invalid_utf8_authority_without_echo() -> None:
    value = "credential-with-surrogate-\ud800"

    with pytest.raises(MassiveDailyMarketDataAcquisitionError) as exc_info:
        MassiveApiCredential(value)

    assert "surrogate" not in str(exc_info.value)
    assert value not in str(exc_info.value)


def test_operational_reprs_do_not_expose_secret_bearing_values() -> None:
    instrument = DailyMarketDataInstrument(
        instrument_id=f"instrument-{CREDENTIAL_VALUE}",
        symbol=f"symbol-{CREDENTIAL_VALUE}",
        venue="TEST",
    )
    plan = instrument_plan(instrument)
    response = MassiveDailyMarketDataHttpResponse(
        status_code=200,
        headers=(("X-Secret", CREDENTIAL_VALUE),),
        body=CREDENTIAL_VALUE.encode(),
    )

    assert CREDENTIAL_VALUE not in repr(plan)
    assert CREDENTIAL_VALUE not in repr(plan.requests[0])
    assert CREDENTIAL_VALUE not in repr(response)

    pair = acquire_pair()
    assert CREDENTIAL_VALUE not in repr(pair)


def test_public_acquisition_inputs_expose_no_hash_size_or_capture_id_authority() -> (
    None
):
    request_fields = {
        field.name for field in fields(MassiveDailyMarketDataAcquisitionRequest)
    }
    plan_fields = {
        field.name for field in fields(MassiveDailyMarketDataInstrumentAcquisitionPlan)
    }

    assert request_fields.isdisjoint(
        {"content_hash", "content_sha256", "content_size", "size_bytes"}
    )
    assert plan_fields.isdisjoint({"capture_id", "content_hash", "size_bytes"})


def test_executor_uses_a_snapshot_of_the_once_captured_credential() -> None:
    original = MassiveApiCredential(CREDENTIAL_VALUE)
    received_values: list[str] = []
    received_ids: list[int] = []

    class MutatingTransport(FakeTransport):
        def get(self, *, request, credential):
            object.__setattr__(original, "_value", "changed-after-boundary")
            received_values.append(credential._value)
            received_ids.append(id(credential))
            object.__setattr__(credential, "_value", "changed-inside-transport")
            return super().get(request=request, credential=credential)

    acquire_pair(credential=original, transport=MutatingTransport())

    assert received_values == [CREDENTIAL_VALUE] * 6
    assert len(set(received_ids)) == 6
    assert original._value == "changed-after-boundary"


def test_credential_authority_is_read_once_at_execution_boundary(monkeypatch) -> None:
    credential = MassiveApiCredential(CREDENTIAL_VALUE)
    reads = 0

    def dynamic_getattribute(self, name: str):
        nonlocal reads
        if self is credential and name == "_value":
            reads += 1
            if reads > 1:
                return "changed-after-validation"
        return object.__getattribute__(self, name)

    monkeypatch.setattr(
        MassiveApiCredential,
        "__getattribute__",
        dynamic_getattribute,
    )

    pair = acquire_pair(credential=credential)

    assert pair.asset.capture_id
    assert reads == 1


@pytest.mark.parametrize("field", ("instrument_id", "symbol"))
def test_credential_in_instrument_authority_fails_before_network(field: str) -> None:
    values = {"instrument_id": "us-equity:safe", "symbol": "SAFE", "venue": "XNAS"}
    values[field] = f"prefix-{CREDENTIAL_VALUE}-suffix"
    plan = instrument_plan(DailyMarketDataInstrument(**values))
    transport = FakeTransport()

    with pytest.raises(MassiveDailyMarketDataAcquisitionError) as exc_info:
        acquire_pair(asset_plan=plan, transport=transport)

    assert CREDENTIAL_VALUE not in str(exc_info.value)
    assert transport.calls == []


def test_credential_in_batch_id_fails_before_network() -> None:
    asset = instrument_plan(ASSET, batch_id=CREDENTIAL_VALUE)
    benchmark = instrument_plan(BENCHMARK, batch_id=CREDENTIAL_VALUE)
    transport = FakeTransport()

    with pytest.raises(MassiveDailyMarketDataAcquisitionError) as exc_info:
        acquire_pair(asset_plan=asset, benchmark_plan=benchmark, transport=transport)

    assert CREDENTIAL_VALUE not in str(exc_info.value)
    assert transport.calls == []


def test_secret_bearing_tampered_plan_metadata_fails_without_echo() -> None:
    asset = instrument_plan(ASSET)
    altered = replace(
        asset.requests[0],
        sanitized_source_reference=(
            f"https://api.massive.com/x?apiKey={CREDENTIAL_VALUE}"
        ),
    )
    tampered = replace(asset, requests=(altered, *asset.requests[1:]))
    transport = FakeTransport()

    with pytest.raises(MassiveDailyMarketDataAcquisitionError) as exc_info:
        acquire_pair(asset_plan=tampered, transport=transport)

    assert CREDENTIAL_VALUE not in str(exc_info.value)
    assert CREDENTIAL_VALUE not in repr(exc_info.value)
    assert exc_info.value.__context__ is None
    assert transport.calls == []


def test_credential_echo_in_exact_response_bytes_fails_without_rewriting() -> None:
    def response_with_secret(request, call_number):
        body = response_body(
            request.role,
            dict(request.request_parameters)["ticker"],
            f"request-{call_number}",
            extra={"echo": CREDENTIAL_VALUE},
        )
        return http_response(body)

    transport = FakeTransport(response_with_secret)
    with pytest.raises(MassiveDailyMarketDataResponseError) as exc_info:
        acquire_pair(transport=transport)

    assert CREDENTIAL_VALUE not in str(exc_info.value)
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "body_factory",
    (
        lambda secret: secret.encode() + b'{"status":"OK","request_id":"x"}',
        lambda secret: b'{"status":"OK","request_id":"x"}' + secret.encode(),
        lambda secret: (
            b'{"status":"OK","request_id":"x","echo":"' + secret.encode() + b'"}'
        ),
        lambda secret: secret.encode(),
    ),
)
def test_exact_credential_bytes_are_rejected_at_every_body_position(
    body_factory,
) -> None:
    body = body_factory(CREDENTIAL_VALUE)
    transport = FakeTransport(lambda _request, _call: http_response(body))

    with pytest.raises(MassiveDailyMarketDataResponseError) as exc_info:
        acquire_pair(transport=transport)

    assert CREDENTIAL_VALUE not in str(exc_info.value)
    assert len(transport.calls) == 1


def test_non_ascii_credential_bytes_are_rejected_exactly() -> None:
    credential_value = "massive-test-密钥-安全-sentinel"
    credential = MassiveApiCredential(credential_value)
    body = response_body(
        DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
        "QQQ",
        "request-1",
        extra={"echo": credential_value},
    )

    with pytest.raises(MassiveDailyMarketDataResponseError) as exc_info:
        acquire_pair(
            credential=credential,
            transport=FakeTransport(lambda _request, _call: http_response(body)),
        )

    assert credential_value not in str(exc_info.value)


def test_credential_body_scan_is_exact_and_does_not_infer_case_variants() -> None:
    credential_value = "CaseSensitive-Massive-Key-Z9"

    def factory(request, call_number):
        body = response_body(
            request.role,
            dict(request.request_parameters)["ticker"],
            f"request-{call_number}",
            extra={"different_case": credential_value.lower()},
        )
        return http_response(body)

    pair = acquire_pair(
        credential=MassiveApiCredential(credential_value),
        transport=FakeTransport(factory),
    )

    assert pair.asset.capture_id


@pytest.mark.parametrize(
    "unsafe_message",
    (
        CREDENTIAL_VALUE,
        f"Authorization: Bearer {CREDENTIAL_VALUE}",
        f"https://api.massive.com/x?apiKey={CREDENTIAL_VALUE}",
        f"{{'Authorization': 'Bearer {CREDENTIAL_VALUE}'}}",
    ),
)
def test_untrusted_transport_exception_is_fully_discarded(
    unsafe_message: str,
) -> None:
    transport = FakeTransport(
        fail_at=1,
        failure=RuntimeError(unsafe_message),
    )
    with pytest.raises(MassiveDailyMarketDataTransportError) as exc_info:
        acquire_pair(transport=transport)

    assert CREDENTIAL_VALUE not in str(exc_info.value)
    assert CREDENTIAL_VALUE not in repr(exc_info.value)
    assert "Authorization" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert CREDENTIAL_VALUE not in "".join(traceback.format_exception(exc_info.value))


def test_untrusted_injected_transport_cannot_forge_an_internal_safe_error() -> None:
    transport = FakeTransport(
        fail_at=1,
        failure=MassiveDailyMarketDataTransportError(SECRET_SENTINEL),
    )

    with pytest.raises(MassiveDailyMarketDataTransportError) as exc_info:
        acquire_pair(transport=transport)

    assert str(exc_info.value) == (
        "Massive transport failed for BAR_RESPONSE at "
        "/v2/aggs/ticker/QQQ/range/1/day/2024-01-02/2024-12-31"
    )
    assert SECRET_SENTINEL not in str(exc_info.value)
    assert CREDENTIAL_VALUE not in repr(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_falsey_injected_transport_and_clock_are_used() -> None:
    class FalseyTransport(FakeTransport):
        def __bool__(self) -> bool:
            return False

    class FalseyClock(CountingClock):
        def __bool__(self) -> bool:
            return False

    transport = FalseyTransport()
    clock = FalseyClock((ASSET_OBSERVED_AT, BENCHMARK_OBSERVED_AT))

    pair = acquire_pair(transport=transport, clock=clock)  # type: ignore[arg-type]

    assert len(transport.calls) == 6
    assert clock.calls == 2
    assert pair.asset.capture_manifest.capture_observed_at == ASSET_OBSERVED_AT


def test_tampered_credential_storage_is_revalidated_before_network() -> None:
    credential = MassiveApiCredential(CREDENTIAL_VALUE)
    object.__setattr__(credential, "_value", "unsafe\nvalue")
    transport = FakeTransport()

    with pytest.raises(
        MassiveDailyMarketDataAcquisitionError, match="authority"
    ) as exc_info:
        acquire_pair(credential=credential, transport=transport)

    assert transport.calls == []
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_untrusted_clock_exception_is_sanitized_without_cause() -> None:
    def unsafe_clock() -> datetime:
        raise RuntimeError(f"Bearer {CREDENTIAL_VALUE}")

    with pytest.raises(MassiveDailyMarketDataAcquisitionError) as exc_info:
        acquire_pair(clock=unsafe_clock)

    assert CREDENTIAL_VALUE not in str(exc_info.value)
    assert CREDENTIAL_VALUE not in repr(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert CREDENTIAL_VALUE not in "".join(traceback.format_exception(exc_info.value))


def test_success_preserves_exact_response_bytes_and_planner_hash_authority() -> None:
    exact_bodies: list[bytes] = []

    def response_factory(request, call_number):
        canonical = response_body(
            request.role,
            dict(request.request_parameters)["ticker"],
            f"raw-{call_number}",
        )
        body = b" \r\n" + canonical.rstrip(b"\n") + b"\r\n"
        exact_bodies.append(body)
        return http_response(body)

    pair = acquire_pair(transport=FakeTransport(response_factory))

    for plan, offset in ((pair.asset, 0), (pair.benchmark, 3)):
        for index, role in enumerate(ROLE_ORDER):
            exact = member_bytes(plan, role)
            assert exact is exact_bodies[offset + index]
            metadata = next(
                member
                for member in plan.capture_manifest.members
                if member.role is role
            )
            assert metadata.content_sha256 == sha256_bytes(exact)
            assert metadata.size_bytes == len(exact)


@pytest.mark.parametrize(
    "status",
    (300, 301, 302, 303, 307, 308, 399, 400, 401, 403, 404, 408, 429, 500, 502, 503),
)
def test_non_200_status_fails_without_exposing_body(status: int) -> None:
    failed_body = f"provider error {CREDENTIAL_VALUE}".encode()
    transport = FakeTransport(
        lambda _request, _call: http_response(failed_body, status=status)
    )

    with pytest.raises(MassiveDailyMarketDataResponseError) as exc_info:
        acquire_pair(transport=transport)

    assert str(status) in str(exc_info.value)
    assert CREDENTIAL_VALUE not in str(exc_info.value)
    assert failed_body.decode() not in str(exc_info.value)


def test_redirect_location_is_not_followed_or_persisted() -> None:
    transport = FakeTransport(
        lambda _request, _call: MassiveDailyMarketDataHttpResponse(
            status_code=302,
            headers=(
                ("Content-Type", "application/json"),
                ("Location", "https://attacker.invalid/credential-target"),
            ),
            body=b'{"status":"OK","request_id":"redirect"}',
        )
    )

    with pytest.raises(MassiveDailyMarketDataResponseError, match="302"):
        acquire_pair(transport=transport)

    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "headers",
    (
        (),
        (("Content-Type", "text/html"),),
        (("Content-Type", "text/json"),),
        (("Content-Type", ""),),
        (("Content-Type", "application/json, application/json"),),
        (("Content-Type", "application/json;"),),
        (("Content-Type", "application/json; charset"),),
        (("Content-Type", "application/json; =utf-8"),),
        (("Content-Type", "application/json; charset=bad\nvalue"),),
        (("Content-Type", "application/json"), ("content-type", "application/json")),
        (("Content-Type", "application/json"), ("Content-Encoding", "gzip")),
        (("Content-Type", "application/json"), ("Content-Encoding", "br")),
        (("Content-Type", "application/json"), ("Content-Encoding", "deflate")),
        (
            ("Content-Type", "application/json"),
            ("Content-Encoding", "identity,gzip"),
        ),
        (
            ("Content-Type", "application/json"),
            ("Content-Encoding", "identity"),
            ("content-encoding", "IDENTITY"),
        ),
        (("Content-Type", "application/json"), ("Content-Length", "01")),
        (("Content-Type", "application/json"), ("Content-Length", "+1")),
        (("Content-Type", "application/json"), ("Content-Length", " 1")),
        (("Content-Type", "application/json"), ("Content-Length", "1 ")),
        (("Content-Type", "application/json"), ("Content-Length", "-1")),
        (("Content-Type", "application/json"), ("Content-Length", "1.0")),
        (("Content-Type", "application/json"), ("Content-Length", "1e2")),
        (("Content-Type", "application/json"), ("Content-Length", "9" * 10000)),
        (
            ("Content-Type", "application/json"),
            ("Content-Length", "2"),
            ("content-length", "2"),
        ),
    ),
)
def test_ambiguous_or_unsupported_authority_headers_fail(headers) -> None:
    request = instrument_plan().requests[0]
    body = response_body(request.role, "QQQ", "request-1")
    transport = FakeTransport(
        lambda _request, _call: http_response(body, headers=headers)
    )

    with pytest.raises(MassiveDailyMarketDataResponseError):
        acquire_pair(transport=transport)


@pytest.mark.parametrize(
    "content_type",
    (
        "application/json",
        "APPLICATION/JSON",
        "Application/Json; charset=utf-8",
        "application/json ; charset=utf-8",
        'application/json; charset="utf-8"',
    ),
)
def test_supported_json_content_types_are_normalized(content_type: str) -> None:
    def factory(request, call_number):
        body = response_body(
            request.role,
            dict(request.request_parameters)["ticker"],
            f"request-{call_number}",
        )
        return http_response(body, headers=(("Content-Type", content_type),))

    pair = acquire_pair(transport=FakeTransport(factory))
    assert all(
        member.media_type == "application/json"
        for member in pair.asset.capture_manifest.members
    )


def test_identity_content_encoding_is_accepted() -> None:
    def factory(request, call_number):
        body = response_body(
            request.role,
            dict(request.request_parameters)["ticker"],
            f"request-{call_number}",
        )
        return http_response(
            body,
            headers=(
                ("Content-Type", "application/json"),
                ("Content-Encoding", "IDENTITY"),
            ),
        )

    assert acquire_pair(transport=FakeTransport(factory)).asset.capture_id


def test_declared_content_length_must_match_exact_body() -> None:
    request = instrument_plan().requests[0]
    body = response_body(request.role, "QQQ", "request-1")
    transport = FakeTransport(
        lambda _request, _call: http_response(
            body,
            headers=(
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body) + 1)),
            ),
        )
    )
    with pytest.raises(MassiveDailyMarketDataResponseError, match="length"):
        acquire_pair(transport=transport)


@pytest.mark.parametrize("declared_length", ("0", "1"))
def test_declared_short_or_zero_length_cannot_hide_injected_body(
    declared_length: str,
) -> None:
    request = instrument_plan().requests[0]
    body = response_body(request.role, "QQQ", "request-1")
    transport = FakeTransport(
        lambda _request, _call: http_response(
            body,
            headers=(
                ("Content-Type", "application/json"),
                ("Content-Length", declared_length),
            ),
        )
    )

    with pytest.raises(MassiveDailyMarketDataResponseError, match="length"):
        acquire_pair(transport=transport)


class IntSubclass(int):
    pass


@pytest.mark.parametrize(
    "response",
    (
        MassiveDailyMarketDataHttpResponse(
            status_code=True,
            headers=(("Content-Type", "application/json"),),
            body=b'{"status":"OK","request_id":"x"}',
        ),
        MassiveDailyMarketDataHttpResponse(
            status_code=200,
            headers=(("Content-Type", "application/json"),),
            body=type("BytesSubclass", (bytes,), {})(
                b'{"status":"OK","request_id":"x"}'
            ),
        ),
        MassiveDailyMarketDataHttpResponse(
            status_code=200,
            headers=(
                (type("StrSubclass", (str,), {})("Content-Type"), "application/json"),
            ),
            body=b'{"status":"OK","request_id":"x"}',
        ),
        MassiveDailyMarketDataHttpResponse(
            status_code=IntSubclass(200),
            headers=(("Content-Type", "application/json"),),
            body=b'{"status":"OK","request_id":"x"}',
        ),
        MassiveDailyMarketDataHttpResponse(
            status_code=200,
            headers=[("Content-Type", "application/json")],  # type: ignore[arg-type]
            body=b'{"status":"OK","request_id":"x"}',
        ),
        MassiveDailyMarketDataHttpResponse(
            status_code=200,
            headers=(("Content-Type", "application/json", "extra"),),  # type: ignore[arg-type]
            body=b'{"status":"OK","request_id":"x"}',
        ),
        MassiveDailyMarketDataHttpResponse(
            status_code=200,
            headers=(("Content-Type", 1),),  # type: ignore[arg-type]
            body=b'{"status":"OK","request_id":"x"}',
        ),
    ),
)
def test_untrusted_response_runtime_subclasses_fail_closed(response) -> None:
    with pytest.raises(MassiveDailyMarketDataResponseError):
        acquire_pair(transport=FakeTransport(lambda _request, _call: response))


def test_response_proxy_is_rejected_without_reading_dynamic_fields() -> None:
    reads: list[str] = []

    class ResponseProxy:
        def __getattribute__(self, name: str):
            if name in {"status_code", "headers", "body"}:
                reads.append(name)
            return super().__getattribute__(name)

        status_code = 200
        headers = (("Content-Type", "application/json"),)
        body = b'{"status":"OK","request_id":"x"}'

    with pytest.raises(MassiveDailyMarketDataResponseError):
        acquire_pair(transport=FakeTransport(lambda _request, _call: ResponseProxy()))

    assert reads == []


def test_exact_response_fields_are_each_captured_once(monkeypatch) -> None:
    reads: dict[tuple[int, str], int] = {}
    responses: list[MassiveDailyMarketDataHttpResponse] = []

    def counting_getattribute(self, name: str):
        if name in {"status_code", "headers", "body"}:
            key = (id(self), name)
            reads[key] = reads.get(key, 0) + 1
            if reads[key] > 1:
                raise AssertionError(f"response field reread: {name}")
        return object.__getattribute__(self, name)

    monkeypatch.setattr(
        MassiveDailyMarketDataHttpResponse,
        "__getattribute__",
        counting_getattribute,
    )

    def retaining_factory(request, call_number):
        response = valid_response(request, call_number)
        responses.append(response)
        return response

    pair = acquire_pair(transport=FakeTransport(retaining_factory))

    assert pair.asset.capture_id
    assert len(responses) == 6
    assert len(reads) == 18
    assert set(reads.values()) == {1}


@pytest.mark.parametrize(
    "body",
    (
        b"",
        b"\xff",
        b"not-json",
        b"[]",
        b'{"status":"OK","status":"OK","request_id":"x"}',
        b'{"status":"OK","request_id":"x","request_id":"y"}',
        b'{"status":"OK","request_id":"x","next_url":null,"next_url":null}',
        b'{"status":"OK","request_id":"x","value":NaN}',
        b'{"status":"OK","request_id":"x","value":Infinity}',
        b'{"status":"ERROR","request_id":"x"}',
        b'{"status":"OK"}',
        b'{"status":"OK","request_id":true}',
        b'{"status":"OK","request_id":""}',
        b'{"status":"OK","request_id":" x "}',
        b'{"status":"OK","request_id":"x","next_url":null}',
        b'{"status":"OK","request_id":"x","next_url":""}',
        b'{"status":"OK","request_id":"x","next_url":false}',
        b'{"status":"OK","request_id":"x","next_url":0}',
        b'{"status":"OK","request_id":"x","next_url":[]}',
        b'{"status":"OK","request_id":"x","next_url":{}}',
        b'{"status":"OK","request_id":"x","next_url":"https://api.massive.com/x"}',
    ),
)
def test_malformed_operational_envelopes_fail_closed(body: bytes) -> None:
    transport = FakeTransport(lambda _request, _call: http_response(body))
    with pytest.raises(MassiveDailyMarketDataResponseError):
        acquire_pair(transport=transport)


def test_malformed_json_body_is_discarded_from_exception_context() -> None:
    unsafe_body_text = "unsafe-provider-body-sentinel"
    body = f'{{"value":"{unsafe_body_text}"'.encode()

    with pytest.raises(MassiveDailyMarketDataResponseError) as exc_info:
        acquire_pair(
            transport=FakeTransport(lambda _request, _call: http_response(body))
        )

    rendered = "".join(traceback.format_exception(exc_info.value))
    assert unsafe_body_text not in str(exc_info.value)
    assert unsafe_body_text not in rendered
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_integer_request_id_is_canonicalized_and_economic_rows_are_not_inspected() -> (
    None
):
    def factory(request, call_number):
        body = response_body(
            request.role,
            dict(request.request_parameters)["ticker"],
            1000 + call_number,
            extra={"results": ["not-an-economic-row"]},
        )
        return http_response(body)

    pair = acquire_pair(transport=FakeTransport(factory))
    assert tuple(
        member.api_request_id for member in pair.asset.capture_manifest.members
    ) == (
        "1001",
        "1002",
        "1003",
    )
    verified = verify_daily_market_data_source_capture(pair.asset.as_file_map())
    with pytest.raises(MassiveResponseValidationError):
        adapt_massive_daily_market_data_source_capture(
            source_capture=verified,
            context=MassiveDailyMarketDataAdapterContext(
                instrument=ASSET,
                currency="USD",
            ),
        )


def test_numeric_request_id_cannot_persist_numeric_credential() -> None:
    credential_value = "1001"

    def factory(request, call_number):
        body = response_body(
            request.role,
            dict(request.request_parameters)["ticker"],
            1000 + call_number,
        )
        return http_response(body)

    with pytest.raises(MassiveDailyMarketDataResponseError) as exc_info:
        acquire_pair(
            credential=MassiveApiCredential(credential_value),
            transport=FakeTransport(factory),
        )

    assert credential_value not in str(exc_info.value)


def test_very_short_credential_still_uses_exact_body_rejection() -> None:
    credential_value = "Z"
    body = b'Z{"status":"OK","request_id":"x"}'

    with pytest.raises(MassiveDailyMarketDataResponseError):
        acquire_pair(
            credential=MassiveApiCredential(credential_value),
            transport=FakeTransport(lambda _request, _call: http_response(body)),
        )


@pytest.mark.parametrize(
    ("role_index", "limit"),
    ((0, 4 * 1024 * 1024), (1, 2 * 1024 * 1024), (2, 2 * 1024 * 1024)),
)
def test_exact_role_size_boundary_reaches_envelope_validation(
    role_index: int, limit: int
) -> None:
    target_role = ROLE_ORDER[role_index]

    def factory(request, call_number):
        if request.role is target_role:
            body = b"{" + b" " * (limit - 1)
            return http_response(body, headers=(("Content-Type", "application/json"),))
        return valid_response(request, call_number)

    with pytest.raises(MassiveDailyMarketDataResponseError, match="strict JSON"):
        acquire_pair(transport=FakeTransport(factory))


@pytest.mark.parametrize(
    ("role_index", "limit"),
    ((0, 4 * 1024 * 1024), (1, 2 * 1024 * 1024), (2, 2 * 1024 * 1024)),
)
def test_one_byte_over_role_limit_fails_before_envelope_parse(
    role_index: int, limit: int
) -> None:
    target_role = ROLE_ORDER[role_index]

    def factory(request, call_number):
        if request.role is target_role:
            return http_response(
                b"x" * (limit + 1), headers=(("Content-Type", "application/json"),)
            )
        return valid_response(request, call_number)

    with pytest.raises(MassiveDailyMarketDataResponseError, match="byte limit"):
        acquire_pair(transport=FakeTransport(factory))


def test_instrument_aggregate_limit_applies_to_exact_accepted_bodies(
    monkeypatch,
) -> None:
    monkeypatch.setattr(acquisition_module, "_INSTRUMENT_RESPONSE_SIZE_LIMIT_BYTES", 1)
    transport = FakeTransport()
    clock = CountingClock((ASSET_OBSERVED_AT, BENCHMARK_OBSERVED_AT))

    with pytest.raises(MassiveDailyMarketDataResponseError, match="8 MiB"):
        acquire_pair(transport=transport, clock=clock)  # type: ignore[arg-type]

    assert len(transport.calls) == 1
    assert clock.calls == 0


def test_pair_aggregate_limit_returns_no_partial_pair(monkeypatch) -> None:
    monkeypatch.setattr(acquisition_module, "_PAIR_RESPONSE_SIZE_LIMIT_BYTES", 1)
    transport = FakeTransport()
    clock = CountingClock((ASSET_OBSERVED_AT, BENCHMARK_OBSERVED_AT))

    with pytest.raises(MassiveDailyMarketDataResponseError, match="16 MiB") as exc_info:
        acquire_pair(transport=transport, clock=clock)  # type: ignore[arg-type]

    assert len(transport.calls) == 6
    assert clock.calls == 2
    assert not hasattr(exc_info.value, "asset")
    assert not hasattr(exc_info.value, "benchmark")


def test_success_calls_clock_once_after_each_complete_instrument() -> None:
    clock = CountingClock((ASSET_OBSERVED_AT, BENCHMARK_OBSERVED_AT))
    transport = FakeTransport()

    pair = acquire_pair(transport=transport, clock=clock)  # type: ignore[arg-type]

    assert clock.calls == 2
    assert pair.asset.capture_manifest.capture_observed_at == ASSET_OBSERVED_AT
    assert pair.benchmark.capture_manifest.capture_observed_at == BENCHMARK_OBSERVED_AT
    assert BENCHMARK_OBSERVED_AT - ASSET_OBSERVED_AT == timedelta(hours=7)


@pytest.mark.parametrize("failure_at", (1, 2, 3))
def test_clock_is_not_called_before_instrument_responses_complete(
    failure_at: int,
) -> None:
    clock = CountingClock((ASSET_OBSERVED_AT, BENCHMARK_OBSERVED_AT))
    with pytest.raises(MassiveDailyMarketDataTransportError):
        acquire_pair(
            transport=FakeTransport(fail_at=failure_at),
            clock=clock,  # type: ignore[arg-type]
        )
    assert clock.calls == 0


@pytest.mark.parametrize(
    "clock_value",
    (
        datetime(2026, 8, 20, 16, 0),
        datetime(2026, 8, 20, 16, 0, tzinfo=timezone(timedelta(hours=1))),
        "2026-08-20T16:00:00Z",
    ),
)
def test_clock_requires_exact_utc_datetime(clock_value: object) -> None:
    clock = CountingClock((clock_value, BENCHMARK_OBSERVED_AT))
    with pytest.raises(MassiveDailyMarketDataAcquisitionError, match="UTC datetime"):
        acquire_pair(clock=clock)  # type: ignore[arg-type]
    assert clock.calls == 1


class DatetimeSubclass(datetime):
    pass


def test_clock_rejects_datetime_subclass() -> None:
    clock = CountingClock((DatetimeSubclass(2026, 8, 20, tzinfo=UTC),))
    with pytest.raises(MassiveDailyMarketDataAcquisitionError, match="UTC datetime"):
        acquire_pair(clock=clock)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("failure_at", "expected_clock_calls"),
    ((1, 0), (2, 0), (3, 0), (4, 1), (5, 1), (6, 1)),
)
def test_failure_stops_exact_six_request_sequence_without_retry(
    failure_at: int,
    expected_clock_calls: int,
) -> None:
    transport = FakeTransport(fail_at=failure_at)
    clock = CountingClock((ASSET_OBSERVED_AT, BENCHMARK_OBSERVED_AT))
    with pytest.raises(MassiveDailyMarketDataTransportError) as exc_info:
        acquire_pair(transport=transport, clock=clock)  # type: ignore[arg-type]
    assert len(transport.calls) == failure_at
    assert [request.role for request in transport.calls] == [
        *ROLE_ORDER,
        *ROLE_ORDER,
    ][:failure_at]
    assert clock.calls == expected_clock_calls
    assert not hasattr(exc_info.value, "asset")
    assert not hasattr(exc_info.value, "partial_plan")


def test_success_uses_exact_sequential_asset_then_benchmark_order() -> None:
    transport = FakeTransport()
    pair = acquire_pair(transport=transport)

    assert [
        dict(request.request_parameters)["ticker"] for request in transport.calls
    ] == [
        "QQQ",
        "QQQ",
        "QQQ",
        "SPY",
        "SPY",
        "SPY",
    ]
    assert [request.role for request in transport.calls] == [*ROLE_ORDER, *ROLE_ORDER]
    assert pair.asset.capture_manifest.acquisition_batch_id == BATCH_ID
    assert pair.benchmark.capture_manifest.acquisition_batch_id == BATCH_ID
    assert pair.asset.capture_id != pair.benchmark.capture_id


def test_source_capture_planner_failure_is_safe_and_returns_no_partial_plan(
    monkeypatch,
) -> None:
    def unsafe_planner(**kwargs):
        raise RuntimeError(f"planner leaked {CREDENTIAL_VALUE}")

    monkeypatch.setattr(
        acquisition_module,
        "plan_daily_market_data_source_capture",
        unsafe_planner,
    )
    transport = FakeTransport()
    clock = CountingClock((ASSET_OBSERVED_AT, BENCHMARK_OBSERVED_AT))

    with pytest.raises(MassiveDailyMarketDataAcquisitionError) as exc_info:
        acquire_pair(transport=transport, clock=clock)  # type: ignore[arg-type]

    assert len(transport.calls) == 3
    assert clock.calls == 1
    assert CREDENTIAL_VALUE not in str(exc_info.value)
    assert CREDENTIAL_VALUE not in repr(exc_info.value)
    assert CREDENTIAL_VALUE not in "".join(traceback.format_exception(exc_info.value))
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert not hasattr(exc_info.value, "asset")


def test_plans_verify_adapt_and_pass_existing_pair_vintage_validation() -> None:
    pair = acquire_pair()
    verified_asset = verify_daily_market_data_source_capture(pair.asset.as_file_map())
    verified_benchmark = verify_daily_market_data_source_capture(
        pair.benchmark.as_file_map()
    )
    adapted_asset = adapt_massive_daily_market_data_source_capture(
        source_capture=verified_asset,
        context=MassiveDailyMarketDataAdapterContext(
            instrument=ASSET,
            currency="USD",
        ),
    )
    adapted_benchmark = adapt_massive_daily_market_data_source_capture(
        source_capture=verified_benchmark,
        context=MassiveDailyMarketDataAdapterContext(
            instrument=BENCHMARK,
            currency="USD",
        ),
    )

    validate_massive_daily_market_data_capture_pair_compatibility(
        asset=adapted_asset,
        benchmark=adapted_benchmark,
    )
    assert adapted_asset.source_capture.member_bytes[
        DailyMarketDataSourceCaptureRole.BAR_RESPONSE
    ] is member_bytes(pair.asset, DailyMarketDataSourceCaptureRole.BAR_RESPONSE)
    assert verified_asset.ca_source_manifest.members[0].content_sha256 == (
        pair.asset.capture_manifest.members[1].content_sha256
    )
    assert verified_asset.ca_source_manifest.members[1].content_sha256 == (
        pair.asset.capture_manifest.members[2].content_sha256
    )
    assert pair.asset.capture_manifest.limitations == tuple(
        sorted(
            (
                "historical Massive evidence uses latest-known semantics and is not "
                "point-in-time evidence",
                "pagination following is intentionally unsupported; each captured "
                "endpoint must complete in one provider page",
                "expected exchange sessions are validated independently downstream "
                "and are not inferred from provider responses",
            )
        )
    )
    assert all(
        member.limitations == () for member in pair.asset.capture_manifest.members
    )
    assert adapted_asset.instrument.venue == "XNAS"
    assert adapted_benchmark.instrument.venue == "ARCX"


class StubSocket:
    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def settimeout(self, value: float) -> None:
        self.timeouts.append(value)


class StubHttpResponse:
    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        headers: tuple[tuple[str, str], ...] | None = None,
    ) -> None:
        self.status = status
        self.headers = headers or (
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
        )
        self.body = body
        self.offset = 0
        self.read_sizes: list[int] = []
        self.closed = False

    def getheaders(self):
        return self.headers

    def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        chunk = self.body[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


class StubHttpsConnection:
    instances: list[StubHttpsConnection] = []
    next_response: StubHttpResponse

    def __init__(self, host, *, timeout, context) -> None:
        self.host = host
        self.timeout = timeout
        self.context = context
        self.sock = StubSocket()
        self.connected = False
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        self.timeout_at_request: float | None = None
        self.timeout_at_getresponse: float | None = None
        self.closed = False
        self.response = type(self).next_response
        type(self).instances.append(self)

    def connect(self) -> None:
        self.connected = True

    def request(self, method: str, target: str, *, headers: dict[str, str]) -> None:
        self.timeout_at_request = self.sock.timeouts[-1]
        self.requests.append((method, target, headers))

    def getresponse(self) -> StubHttpResponse:
        self.timeout_at_getresponse = self.sock.timeouts[-1]
        return self.response

    def close(self) -> None:
        self.closed = True


def install_stub_connection(
    monkeypatch,
    response: StubHttpResponse,
    connection_type: type[StubHttpsConnection] = StubHttpsConnection,
):
    connection_type.instances = []
    connection_type.next_response = response
    context = object()
    monkeypatch.setattr(acquisition_module, "HTTPSConnection", connection_type)
    monkeypatch.setattr(
        acquisition_module.ssl, "create_default_context", lambda: context
    )
    return context


def assert_safe_body_failure(
    error: MassiveDailyMarketDataTransportError,
    expected_stage: str,
) -> None:
    expected = (
        f"Massive HTTPS response body {expected_stage} for BAR_RESPONSE at "
        "/v2/aggs/ticker/QQQ/range/1/day/2024-01-02/2024-12-31"
    )
    rendered = "".join(traceback.format_exception(error))

    assert str(error) == expected
    assert SECRET_SENTINEL not in str(error)
    assert SECRET_SENTINEL not in repr(error)
    assert SECRET_SENTINEL not in rendered
    assert CREDENTIAL_VALUE not in str(error)
    assert CREDENTIAL_VALUE not in repr(error)
    assert CREDENTIAL_VALUE not in rendered
    assert "arbitrary external exception message" not in str(error)
    assert "arbitrary external exception message" not in repr(error)
    assert "arbitrary external exception message" not in rendered
    assert error.__cause__ is None
    assert error.__context__ is None


def test_default_transport_uses_fixed_tls_host_headers_and_deterministic_get(
    monkeypatch,
) -> None:
    request = instrument_plan().requests[0]
    body = response_body(request.role, "QQQ", "wire-request")
    response = StubHttpResponse(body)
    context = install_stub_connection(monkeypatch, response)
    transport = acquisition_module._StdlibMassiveDailyMarketDataHttpTransport(
        CREDENTIAL_VALUE
    )

    actual = transport.get(
        request=request,
        credential=MassiveApiCredential("different-holder-cannot-change-authorization"),
    )

    connection = StubHttpsConnection.instances[0]
    assert connection.host == "api.massive.com"
    assert connection.timeout == 5.0
    assert connection.context is context
    assert connection.connected is True
    assert connection.requests == [
        (
            "GET",
            (
                "/v2/aggs/ticker/QQQ/range/1/day/2024-01-02/2024-12-31"
                "?adjusted=false&limit=50000&sort=asc"
            ),
            {
                "Authorization": f"Bearer {CREDENTIAL_VALUE}",
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "Connection": "close",
            },
        )
    ]
    assert "apiKey" not in connection.requests[0][1]
    assert actual.body is body
    assert response.closed is True
    assert connection.closed is True
    assert connection.sock.timeouts
    assert all(timeout <= 15.0 for timeout in connection.sock.timeouts)
    assert connection.timeout_at_request == 15.0
    assert connection.timeout_at_getresponse == 15.0


def test_stdlib_request_mechanics_do_not_add_duplicate_accept_encoding() -> None:
    class RecordingHttpConnection(HTTPConnection):
        def __init__(self) -> None:
            super().__init__("api.massive.com")
            self.putrequest_call: tuple[str, str, bool, bool] | None = None
            self.header_calls: list[tuple[str, tuple[str | bytes, ...]]] = []

        def putrequest(
            self,
            method: str,
            url: str,
            skip_host: bool = False,
            skip_accept_encoding: bool = False,
        ) -> None:
            self.putrequest_call = (method, url, skip_host, skip_accept_encoding)

        def putheader(self, header: str, *values: str | bytes) -> None:
            self.header_calls.append((header, values))

        def endheaders(
            self,
            message_body: bytes | None = None,
            *,
            encode_chunked: bool = False,
        ) -> None:
            assert message_body is None
            assert encode_chunked is False

    connection = RecordingHttpConnection()
    connection.request(
        "GET",
        "/v2/aggs/ticker/QQQ/range/1/day/2024-01-02/2024-12-31",
        headers={
            "Authorization": f"Bearer {CREDENTIAL_VALUE}",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Connection": "close",
        },
    )

    assert connection.putrequest_call == (
        "GET",
        "/v2/aggs/ticker/QQQ/range/1/day/2024-01-02/2024-12-31",
        False,
        True,
    )
    header_names = [name.casefold() for name, _values in connection.header_calls]
    assert header_names.count("authorization") == 1
    assert header_names.count("accept-encoding") == 1


def test_default_transport_rejects_content_length_over_cap_before_body_read(
    monkeypatch,
) -> None:
    request = instrument_plan().requests[0]
    response = StubHttpResponse(
        b"unread",
        headers=(
            ("Content-Type", "application/json"),
            ("Content-Length", str(request.response_size_limit_bytes + 1)),
        ),
    )
    install_stub_connection(monkeypatch, response)

    with pytest.raises(MassiveDailyMarketDataResponseError, match="exceeds"):
        acquisition_module._StdlibMassiveDailyMarketDataHttpTransport(
            CREDENTIAL_VALUE
        ).get(
            request=request,
            credential=MassiveApiCredential(CREDENTIAL_VALUE),
        )

    assert response.read_sizes == []
    assert response.closed is True
    assert StubHttpsConnection.instances[0].closed is True


def test_default_transport_accepts_exact_cap_and_uses_bounded_reads(
    monkeypatch,
) -> None:
    canonical = instrument_plan().requests[0]
    request = replace(canonical, response_size_limit_bytes=8)
    body = b"12345678"
    response = StubHttpResponse(body)
    install_stub_connection(monkeypatch, response)

    actual = acquisition_module._StdlibMassiveDailyMarketDataHttpTransport(
        CREDENTIAL_VALUE
    ).get(
        request=request,
        credential=MassiveApiCredential(CREDENTIAL_VALUE),
    )

    assert actual.body == body
    assert response.read_sizes == [9, 1]


def test_default_transport_rejects_short_body_against_declared_length(
    monkeypatch,
) -> None:
    request = instrument_plan().requests[0]
    response = StubHttpResponse(
        b"short",
        headers=(
            ("Content-Type", "application/json"),
            ("Content-Length", "6"),
        ),
    )
    install_stub_connection(monkeypatch, response)

    with pytest.raises(MassiveDailyMarketDataResponseError) as exc_info:
        acquisition_module._StdlibMassiveDailyMarketDataHttpTransport(
            CREDENTIAL_VALUE
        ).get(
            request=request,
            credential=MassiveApiCredential(CREDENTIAL_VALUE),
        )

    assert str(exc_info.value) == (
        "Massive response body length does not match Content-Length"
    )


@pytest.mark.parametrize("declared_length", ("0", "4"))
def test_default_transport_rejects_body_longer_than_declared_length(
    monkeypatch,
    declared_length: str,
) -> None:
    request = instrument_plan().requests[0]
    response = StubHttpResponse(
        b"12345",
        headers=(
            ("Content-Type", "application/json"),
            ("Content-Length", declared_length),
        ),
    )
    install_stub_connection(monkeypatch, response)

    with pytest.raises(MassiveDailyMarketDataResponseError, match="Content-Length"):
        acquisition_module._StdlibMassiveDailyMarketDataHttpTransport(
            CREDENTIAL_VALUE
        ).get(
            request=request,
            credential=MassiveApiCredential(CREDENTIAL_VALUE),
        )


def test_default_transport_uses_fixed_64_kib_streaming_chunks(monkeypatch) -> None:
    canonical = instrument_plan().requests[0]
    request = replace(canonical, response_size_limit_bytes=128 * 1024)
    body = b"x" * (64 * 1024 + 10)
    response = StubHttpResponse(body)
    install_stub_connection(monkeypatch, response)

    actual = acquisition_module._StdlibMassiveDailyMarketDataHttpTransport(
        CREDENTIAL_VALUE
    ).get(
        request=request,
        credential=MassiveApiCredential(CREDENTIAL_VALUE),
    )

    assert actual.body == body
    assert response.read_sizes[0] == 64 * 1024
    assert all(size <= 64 * 1024 for size in response.read_sizes)


def test_default_transport_streaming_stops_at_one_byte_over_cap(monkeypatch) -> None:
    canonical = instrument_plan().requests[0]
    request = replace(canonical, response_size_limit_bytes=8)
    response = StubHttpResponse(
        b"123456789more",
        headers=(("Content-Type", "application/json"),),
    )
    install_stub_connection(monkeypatch, response)

    with pytest.raises(MassiveDailyMarketDataResponseError) as exc_info:
        acquisition_module._StdlibMassiveDailyMarketDataHttpTransport(
            CREDENTIAL_VALUE
        ).get(
            request=request,
            credential=MassiveApiCredential(CREDENTIAL_VALUE),
        )

    assert str(exc_info.value) == ("Massive HTTPS response exceeds the role byte limit")
    assert response.read_sizes == [9]
    assert response.offset == 9


def test_default_transport_preserves_deterministic_chunk_type_failure(
    monkeypatch,
) -> None:
    class InvalidChunkResponse(StubHttpResponse):
        def read(self, size: int) -> bytes:
            self.read_sizes.append(size)
            return bytearray(b"not-exact-bytes")  # type: ignore[return-value]

    request = instrument_plan().requests[0]
    response = InvalidChunkResponse(response_body(request.role, "QQQ", "request"))
    install_stub_connection(monkeypatch, response)

    with pytest.raises(MassiveDailyMarketDataResponseError) as exc_info:
        acquisition_module._StdlibMassiveDailyMarketDataHttpTransport(
            CREDENTIAL_VALUE
        ).get(
            request=request,
            credential=MassiveApiCredential(CREDENTIAL_VALUE),
        )

    assert str(exc_info.value) == ("Massive HTTPS response chunks must be exact bytes")
    assert "body read failed" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert response.closed is True
    assert StubHttpsConnection.instances[0].closed is True


def test_default_transport_overall_deadline_fails_and_closes(monkeypatch) -> None:
    request = instrument_plan().requests[0]
    response = StubHttpResponse(response_body(request.role, "QQQ", "request"))
    install_stub_connection(monkeypatch, response)
    moments = iter((0.0, 30.0))
    monkeypatch.setattr(acquisition_module, "monotonic", lambda: next(moments))

    with pytest.raises(MassiveDailyMarketDataTransportError, match="deadline"):
        acquisition_module._StdlibMassiveDailyMarketDataHttpTransport(
            CREDENTIAL_VALUE
        ).get(
            request=request,
            credential=MassiveApiCredential(CREDENTIAL_VALUE),
        )

    assert StubHttpsConnection.instances[0].connected is False
    assert StubHttpsConnection.instances[0].closed is True


def test_default_transport_rechecks_deadline_after_response_headers(
    monkeypatch,
) -> None:
    request = instrument_plan().requests[0]
    response = StubHttpResponse(response_body(request.role, "QQQ", "request"))
    install_stub_connection(monkeypatch, response)
    moments = iter((0.0, 1.0, 2.0, 3.0, 31.0))
    monkeypatch.setattr(acquisition_module, "monotonic", lambda: next(moments))

    with pytest.raises(MassiveDailyMarketDataTransportError, match="deadline"):
        acquisition_module._StdlibMassiveDailyMarketDataHttpTransport(
            CREDENTIAL_VALUE
        ).get(
            request=request,
            credential=MassiveApiCredential(CREDENTIAL_VALUE),
        )

    assert response.read_sizes == []
    assert response.closed is True
    assert StubHttpsConnection.instances[0].closed is True


@pytest.mark.parametrize(
    ("moments", "expected"),
    (
        (
            (0.0, 1.0, 2.0, 3.0, 4.0, 31.0),
            "Massive HTTPS request exceeded the 30-second deadline",
        ),
        (
            (0.0, 1.0, 2.0, 3.0, 4.0, 3.0),
            "Massive HTTPS monotonic clock moved backwards",
        ),
    ),
)
def test_body_timeout_setup_preserves_deterministic_deadline_errors(
    monkeypatch,
    moments: tuple[float, ...],
    expected: str,
) -> None:
    request = instrument_plan().requests[0]
    response = StubHttpResponse(response_body(request.role, "QQQ", "request"))
    install_stub_connection(monkeypatch, response)
    observed = iter(moments)
    monkeypatch.setattr(acquisition_module, "monotonic", lambda: next(observed))

    with pytest.raises(MassiveDailyMarketDataTransportError) as exc_info:
        acquisition_module._StdlibMassiveDailyMarketDataHttpTransport(
            CREDENTIAL_VALUE
        ).get(
            request=request,
            credential=MassiveApiCredential(CREDENTIAL_VALUE),
        )

    assert str(exc_info.value) == expected
    assert "timeout setup failed" not in str(exc_info.value)
    assert "read timed out" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert response.read_sizes == []
    assert response.closed is True
    assert StubHttpsConnection.instances[0].closed is True


def test_default_transport_rechecks_deadline_after_end_of_body(monkeypatch) -> None:
    request = instrument_plan().requests[0]
    response = StubHttpResponse(
        b"",
        headers=(
            ("Content-Type", "application/json"),
            ("Content-Length", "0"),
        ),
    )
    install_stub_connection(monkeypatch, response)
    moments = iter((0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 31.0))
    monkeypatch.setattr(acquisition_module, "monotonic", lambda: next(moments))

    with pytest.raises(MassiveDailyMarketDataTransportError, match="deadline"):
        acquisition_module._StdlibMassiveDailyMarketDataHttpTransport(
            CREDENTIAL_VALUE
        ).get(
            request=request,
            credential=MassiveApiCredential(CREDENTIAL_VALUE),
        )

    assert len(response.read_sizes) == 1
    assert response.closed is True
    assert StubHttpsConnection.instances[0].closed is True


@pytest.mark.parametrize("value", (float("nan"), float("inf"), float("-inf"), 0, "0"))
def test_default_transport_rejects_invalid_monotonic_authority_before_connect(
    monkeypatch,
    value: object,
) -> None:
    monkeypatch.setattr(acquisition_module, "monotonic", lambda: value)
    request = instrument_plan().requests[0]

    with pytest.raises(MassiveDailyMarketDataTransportError, match="monotonic"):
        acquisition_module._StdlibMassiveDailyMarketDataHttpTransport(
            CREDENTIAL_VALUE
        ).get(
            request=request,
            credential=MassiveApiCredential(CREDENTIAL_VALUE),
        )


def test_default_transport_rejects_backwards_monotonic_clock(monkeypatch) -> None:
    request = instrument_plan().requests[0]
    response = StubHttpResponse(response_body(request.role, "QQQ", "request"))
    install_stub_connection(monkeypatch, response)
    moments = iter((10.0, 9.0))
    monkeypatch.setattr(acquisition_module, "monotonic", lambda: next(moments))

    with pytest.raises(MassiveDailyMarketDataTransportError, match="backwards"):
        acquisition_module._StdlibMassiveDailyMarketDataHttpTransport(
            CREDENTIAL_VALUE
        ).get(
            request=request,
            credential=MassiveApiCredential(CREDENTIAL_VALUE),
        )

    assert StubHttpsConnection.instances[0].requests == []
    assert StubHttpsConnection.instances[0].closed is True


def test_default_transport_discards_unsafe_monotonic_exception(monkeypatch) -> None:
    def unsafe_monotonic() -> float:
        raise RuntimeError(f"unsafe {CREDENTIAL_VALUE}")

    monkeypatch.setattr(acquisition_module, "monotonic", unsafe_monotonic)
    request = instrument_plan().requests[0]

    with pytest.raises(MassiveDailyMarketDataTransportError) as exc_info:
        acquisition_module._StdlibMassiveDailyMarketDataHttpTransport(
            CREDENTIAL_VALUE
        ).get(
            request=request,
            credential=MassiveApiCredential(CREDENTIAL_VALUE),
        )

    assert CREDENTIAL_VALUE not in str(exc_info.value)
    assert CREDENTIAL_VALUE not in "".join(traceback.format_exception(exc_info.value))
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_default_transport_sanitizes_connection_failure(monkeypatch) -> None:
    class FailingConnection(StubHttpsConnection):
        def connect(self) -> None:
            raise OSError(SECRET_SENTINEL)

    request = instrument_plan().requests[0]
    response = StubHttpResponse(b"unused")
    FailingConnection.instances = []
    FailingConnection.next_response = response
    monkeypatch.setattr(acquisition_module, "HTTPSConnection", FailingConnection)
    monkeypatch.setattr(
        acquisition_module.ssl,
        "create_default_context",
        lambda: object(),
    )

    with pytest.raises(MassiveDailyMarketDataTransportError) as exc_info:
        acquisition_module._StdlibMassiveDailyMarketDataHttpTransport(
            CREDENTIAL_VALUE
        ).get(
            request=request,
            credential=MassiveApiCredential(CREDENTIAL_VALUE),
        )

    expected = (
        "Massive HTTPS connect failed for BAR_RESPONSE at "
        "/v2/aggs/ticker/QQQ/range/1/day/2024-01-02/2024-12-31"
    )
    assert str(exc_info.value) == expected
    assert SECRET_SENTINEL not in str(exc_info.value)
    assert SECRET_SENTINEL not in repr(exc_info.value)
    assert CREDENTIAL_VALUE not in str(exc_info.value)
    assert CREDENTIAL_VALUE not in repr(exc_info.value)
    assert "arbitrary external exception message" not in str(exc_info.value)
    rendered = "".join(traceback.format_exception(exc_info.value))
    assert SECRET_SENTINEL not in rendered
    assert CREDENTIAL_VALUE not in rendered
    assert "arbitrary external exception message" not in rendered
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert FailingConnection.instances[0].closed is True


def test_default_transport_sanitizes_request_send_failure(monkeypatch) -> None:
    class FailingRequestConnection(StubHttpsConnection):
        def request(self, method: str, target: str, *, headers: dict[str, str]) -> None:
            raise OSError(SECRET_SENTINEL)

    request = instrument_plan().requests[0]
    response = StubHttpResponse(b"unused")
    FailingRequestConnection.instances = []
    FailingRequestConnection.next_response = response
    monkeypatch.setattr(acquisition_module, "HTTPSConnection", FailingRequestConnection)
    monkeypatch.setattr(
        acquisition_module.ssl,
        "create_default_context",
        lambda: object(),
    )

    with pytest.raises(MassiveDailyMarketDataTransportError) as exc_info:
        acquisition_module._StdlibMassiveDailyMarketDataHttpTransport(
            CREDENTIAL_VALUE
        ).get(
            request=request,
            credential=MassiveApiCredential(CREDENTIAL_VALUE),
        )

    expected = (
        "Massive HTTPS request send failed for BAR_RESPONSE at "
        "/v2/aggs/ticker/QQQ/range/1/day/2024-01-02/2024-12-31"
    )
    assert str(exc_info.value) == expected
    assert SECRET_SENTINEL not in str(exc_info.value)
    assert SECRET_SENTINEL not in repr(exc_info.value)
    assert CREDENTIAL_VALUE not in str(exc_info.value)
    assert CREDENTIAL_VALUE not in repr(exc_info.value)
    assert "arbitrary external exception message" not in str(exc_info.value)
    rendered = "".join(traceback.format_exception(exc_info.value))
    assert SECRET_SENTINEL not in rendered
    assert CREDENTIAL_VALUE not in rendered
    assert "arbitrary external exception message" not in rendered
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert FailingRequestConnection.instances[0].connected is True
    assert FailingRequestConnection.instances[0].closed is True


def test_internal_stage_diagnostic_survives_the_acquisition_wrapper(
    monkeypatch,
) -> None:
    class FailingRequestConnection(StubHttpsConnection):
        def request(self, method: str, target: str, *, headers: dict[str, str]) -> None:
            raise OSError(SECRET_SENTINEL)

    response = StubHttpResponse(b"unused")
    FailingRequestConnection.instances = []
    FailingRequestConnection.next_response = response
    monkeypatch.setattr(acquisition_module, "HTTPSConnection", FailingRequestConnection)
    monkeypatch.setattr(
        acquisition_module.ssl,
        "create_default_context",
        lambda: object(),
    )

    with pytest.raises(MassiveDailyMarketDataTransportError) as exc_info:
        acquire_and_plan_massive_daily_market_data_source_capture_pair(
            asset_plan=instrument_plan(ASSET),
            benchmark_plan=instrument_plan(BENCHMARK),
            credential=MassiveApiCredential(CREDENTIAL_VALUE),
            transport=None,
        )

    assert str(exc_info.value) == (
        "Massive HTTPS request send failed for BAR_RESPONSE at "
        "/v2/aggs/ticker/QQQ/range/1/day/2024-01-02/2024-12-31"
    )
    assert SECRET_SENTINEL not in str(exc_info.value)
    assert CREDENTIAL_VALUE not in repr(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert len(FailingRequestConnection.instances) == 1


def test_default_transport_sanitizes_response_header_failure(monkeypatch) -> None:
    class FailingHeaderConnection(StubHttpsConnection):
        def getresponse(self) -> StubHttpResponse:
            self.timeout_at_getresponse = self.sock.timeouts[-1]
            raise OSError(SECRET_SENTINEL)

    request = instrument_plan().requests[0]
    response = StubHttpResponse(b"unused")
    FailingHeaderConnection.instances = []
    FailingHeaderConnection.next_response = response
    monkeypatch.setattr(acquisition_module, "HTTPSConnection", FailingHeaderConnection)
    monkeypatch.setattr(
        acquisition_module.ssl,
        "create_default_context",
        lambda: object(),
    )

    with pytest.raises(MassiveDailyMarketDataTransportError) as exc_info:
        acquisition_module._StdlibMassiveDailyMarketDataHttpTransport(
            CREDENTIAL_VALUE
        ).get(
            request=request,
            credential=MassiveApiCredential(CREDENTIAL_VALUE),
        )

    connection = FailingHeaderConnection.instances[0]
    expected = (
        "Massive HTTPS response headers failed for BAR_RESPONSE at "
        "/v2/aggs/ticker/QQQ/range/1/day/2024-01-02/2024-12-31"
    )
    assert str(exc_info.value) == expected
    assert SECRET_SENTINEL not in str(exc_info.value)
    assert SECRET_SENTINEL not in repr(exc_info.value)
    assert CREDENTIAL_VALUE not in str(exc_info.value)
    assert CREDENTIAL_VALUE not in repr(exc_info.value)
    assert "arbitrary external exception message" not in str(exc_info.value)
    rendered = "".join(traceback.format_exception(exc_info.value))
    assert SECRET_SENTINEL not in rendered
    assert CREDENTIAL_VALUE not in rendered
    assert "arbitrary external exception message" not in rendered
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert connection.connected is True
    assert len(connection.requests) == 1
    assert connection.timeout_at_getresponse == 15.0
    assert connection.closed is True


def test_default_transport_sanitizes_body_timeout_setup_failure(monkeypatch) -> None:
    class FailingBodyTimeoutSocket(StubSocket):
        def settimeout(self, value: float) -> None:
            self.timeouts.append(value)
            if len(self.timeouts) == 3:
                raise RuntimeError(SECRET_SENTINEL)

    class FailingBodyTimeoutConnection(StubHttpsConnection):
        def __init__(self, host, *, timeout, context) -> None:
            super().__init__(host, timeout=timeout, context=context)
            self.sock = FailingBodyTimeoutSocket()

    request = instrument_plan().requests[0]
    body = response_body(request.role, "QQQ", "request")
    response = StubHttpResponse(body)
    install_stub_connection(monkeypatch, response, FailingBodyTimeoutConnection)

    with pytest.raises(MassiveDailyMarketDataTransportError) as exc_info:
        acquisition_module._StdlibMassiveDailyMarketDataHttpTransport(
            CREDENTIAL_VALUE
        ).get(
            request=request,
            credential=MassiveApiCredential(CREDENTIAL_VALUE),
        )

    assert_safe_body_failure(exc_info.value, "timeout setup failed")
    assert response.read_sizes == []
    assert response.closed is True
    assert len(FailingBodyTimeoutConnection.instances) == 1
    connection = FailingBodyTimeoutConnection.instances[0]
    assert connection.sock.timeouts == [15.0, 15.0, 15.0]
    assert connection.closed is True


def test_default_transport_sanitizes_read_timeout_and_closes(monkeypatch) -> None:
    class TimeoutResponse(StubHttpResponse):
        def read(self, size: int) -> bytes:
            self.read_sizes.append(size)
            raise TimeoutError(SECRET_SENTINEL)

    request = instrument_plan().requests[0]
    body = response_body(request.role, "QQQ", "request")
    response = TimeoutResponse(body)
    install_stub_connection(monkeypatch, response)

    with pytest.raises(MassiveDailyMarketDataTransportError) as exc_info:
        acquisition_module._StdlibMassiveDailyMarketDataHttpTransport(
            CREDENTIAL_VALUE
        ).get(
            request=request,
            credential=MassiveApiCredential(CREDENTIAL_VALUE),
        )

    assert_safe_body_failure(exc_info.value, "read timed out")
    assert response.read_sizes == [64 * 1024]
    assert response.closed is True
    assert len(StubHttpsConnection.instances) == 1
    assert StubHttpsConnection.instances[0].closed is True


@pytest.mark.parametrize(
    ("failure_factory", "expected_stage"),
    (
        (lambda: ssl.SSLEOFError(SECRET_SENTINEL), "TLS EOF failed"),
        (lambda: ssl.SSLError(SECRET_SENTINEL), "TLS read failed"),
        (
            lambda: IncompleteRead(SECRET_SENTINEL.encode("utf-8")),
            "incomplete",
        ),
        (
            lambda: ConnectionResetError(SECRET_SENTINEL),
            "connection read failed",
        ),
        (lambda: OSError(SECRET_SENTINEL), "read failed"),
        (lambda: RuntimeError(SECRET_SENTINEL), "read failed"),
    ),
)
def test_default_transport_classifies_other_body_read_failures_without_leakage(
    monkeypatch,
    failure_factory,
    expected_stage: str,
) -> None:
    class FailingReadResponse(StubHttpResponse):
        def read(self, size: int) -> bytes:
            self.read_sizes.append(size)
            raise failure_factory()

    request = instrument_plan().requests[0]
    body = response_body(request.role, "QQQ", "request")
    response = FailingReadResponse(body)
    install_stub_connection(monkeypatch, response)

    with pytest.raises(MassiveDailyMarketDataTransportError) as exc_info:
        acquisition_module._StdlibMassiveDailyMarketDataHttpTransport(
            CREDENTIAL_VALUE
        ).get(
            request=request,
            credential=MassiveApiCredential(CREDENTIAL_VALUE),
        )

    assert_safe_body_failure(exc_info.value, expected_stage)
    assert response.read_sizes == [64 * 1024]
    assert response.closed is True
    assert len(StubHttpsConnection.instances) == 1
    assert StubHttpsConnection.instances[0].closed is True


@pytest.mark.parametrize("status", (401, 403, 429))
def test_default_transport_preserves_non_200_as_normal_response_diagnostic(
    monkeypatch,
    status: int,
) -> None:
    request = instrument_plan().requests[0]
    raw_body = SECRET_SENTINEL.encode()
    response = StubHttpResponse(
        raw_body,
        status=status,
        headers=(("X-Unsafe", SECRET_SENTINEL),),
    )
    install_stub_connection(monkeypatch, response)
    transport = acquisition_module._StdlibMassiveDailyMarketDataHttpTransport(
        CREDENTIAL_VALUE
    )

    actual = transport.get(
        request=request,
        credential=MassiveApiCredential(CREDENTIAL_VALUE),
    )

    with pytest.raises(
        MassiveDailyMarketDataResponseError,
        match=rf"^Massive returned HTTP {status} for BAR_RESPONSE$",
    ) as exc_info:
        acquisition_module._validate_response(
            response=actual,
            request=request,
            secret=CREDENTIAL_VALUE,
        )

    assert actual.status_code == status
    assert actual.body == b""
    assert "response headers failed" not in str(exc_info.value)
    assert "response body" not in str(exc_info.value)
    assert SECRET_SENTINEL not in str(exc_info.value)
    assert SECRET_SENTINEL not in repr(exc_info.value)
    assert CREDENTIAL_VALUE not in str(exc_info.value)
    assert CREDENTIAL_VALUE not in repr(exc_info.value)
    assert response.read_sizes == []
    assert response.closed is True
    assert StubHttpsConnection.instances[0].closed is True


def test_default_transport_cleanup_failures_cannot_replace_primary_failure(
    monkeypatch,
) -> None:
    class FailingCleanupResponse(StubHttpResponse):
        def read(self, size: int) -> bytes:
            raise TimeoutError(SECRET_SENTINEL)

        def close(self) -> None:
            raise RuntimeError("unsafe response cleanup detail")

    class FailingCleanupConnection(StubHttpsConnection):
        def close(self) -> None:
            raise RuntimeError("unsafe connection cleanup detail")

    request = instrument_plan().requests[0]
    body = response_body(request.role, "QQQ", "request")
    response = FailingCleanupResponse(body)
    FailingCleanupConnection.instances = []
    FailingCleanupConnection.next_response = response
    monkeypatch.setattr(acquisition_module, "HTTPSConnection", FailingCleanupConnection)
    monkeypatch.setattr(
        acquisition_module.ssl,
        "create_default_context",
        lambda: object(),
    )

    with pytest.raises(MassiveDailyMarketDataTransportError) as exc_info:
        acquisition_module._StdlibMassiveDailyMarketDataHttpTransport(
            CREDENTIAL_VALUE
        ).get(
            request=request,
            credential=MassiveApiCredential(CREDENTIAL_VALUE),
        )

    assert_safe_body_failure(exc_info.value, "read timed out")
    rendered = "".join(traceback.format_exception(exc_info.value))
    assert "cleanup detail" not in rendered


def test_import_scope_excludes_closed_boundaries() -> None:
    source = acquisition_module.__file__
    assert source is not None
    text = open(source, encoding="utf-8").read()  # noqa: PTH123
    assert "expected_sessions" not in text
    assert "publish_local" not in text
    assert "backtest" not in text
    assert "os.environ" not in text
    assert "apiKey" not in text
    assert "next_url" in text


def test_fresh_process_import_has_no_network_tls_clock_or_heavy_side_effects() -> None:
    script = """
import datetime
import http.client
import socket
import ssl
import sys

calls = []

class ForbiddenHttpsConnection:
    def __init__(self, *args, **kwargs):
        calls.append(("https", args, kwargs))
        raise AssertionError("HTTPSConnection constructed during import")

def forbidden(*args, **kwargs):
    calls.append(("network-or-tls", args, kwargs))
    raise AssertionError("network/TLS operation during import")

http.client.HTTPSConnection = ForbiddenHttpsConnection
socket.create_connection = forbidden
ssl.create_default_context = forbidden

import research_sdk.daily_market_data_acquisition

assert calls == []
assert "exchange_calendars" not in sys.modules
assert "pandas" not in sys.modules
assert "numpy" not in sys.modules
assert not any(name.startswith("backtest_engine") for name in sys.modules)
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
