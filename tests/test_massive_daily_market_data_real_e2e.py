from __future__ import annotations

import inspect
import json
import socket
import ssl
import subprocess
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

import research_sdk.daily_market_data_acquisition.massive as acquisition_module
import research_sdk.daily_market_data_acquisition.massive_real_e2e as e2e_module
from research_sdk.daily_market_data import (
    DailyMarketDataSnapshotProfileCompatibilityError,
    derive_daily_market_data_expected_sessions_hash,
    derive_daily_market_data_policy_hash,
    derive_daily_market_data_research_profile_hash,
    derive_us_equity_daily_expected_sessions,
    validate_daily_market_data_snapshot_profile_compatibility,
)
from research_sdk.daily_market_data_acquisition import (
    MASSIVE_AWS_SECRETS_MANAGER_SOURCE_KIND,
    MASSIVE_REAL_E2E_APPROVAL_DOMAIN,
    MASSIVE_REAL_E2E_EXPECTED_SESSION_HASH,
    MASSIVE_REAL_E2E_OPERATOR_VERSION,
    MASSIVE_REAL_E2E_POLICY_HASH,
    MASSIVE_REAL_E2E_RESEARCH_PROFILE_HASH,
    MassiveApiCredential,
    MassiveAwsSecretsManagerCredentialSource,
    MassiveDailyMarketDataAcquisitionError,
    MassiveDailyMarketDataAcquisitionRequest,
    MassiveDailyMarketDataHttpResponse,
    MassiveDailyMarketDataRealE2EConfig,
    MassiveDailyMarketDataRealE2EError,
    build_massive_daily_market_data_real_e2e_preflight,
    prepare_massive_daily_market_data_real_e2e,
    render_massive_daily_market_data_real_e2e_preflight,
    validate_massive_daily_market_data_real_e2e_prepared,
)
from research_sdk.daily_market_data_source_capture import (
    DailyMarketDataSourceCaptureRole,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_COMMIT = "1" * 40
BATCH_ID = "massive-qqq-spy-2024-01-02-to-2024-12-31-run-001"
CREATED_BY = "operator:synthetic-test"
LICENSE_NOTES = "synthetic test subscription notes; no usage approval asserted"
SECRET = "synthetic-only-massive-key-Z9"
AWS_REGION = "us-west-2"
AWS_SECRET_ID = "massive/api-key"
AWS_SECRET_JSON_KEY = "api_key"
AWS_SECRET_VERSION_STAGE = "AWSCURRENT"
ASSET_OBSERVED_AT = datetime(2026, 8, 20, 16, 0, tzinfo=UTC)
BENCHMARK_OBSERVED_AT = datetime(2026, 8, 20, 17, 0, tzinfo=UTC)
INGESTION_COMPLETED_AT = datetime(2026, 8, 20, 18, 0, tzinfo=UTC)
AVAILABLE_AT = datetime(2026, 8, 20, 19, 0, tzinfo=UTC)
CREATED_AT = datetime(2026, 8, 20, 20, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def forbid_real_network(monkeypatch) -> None:
    def forbidden_network(*_args, **_kwargs):
        pytest.fail("S3c3c6a tests must never use DNS, sockets, or TLS")

    class ForbiddenHttpsConnection:
        def __init__(self, *args, **kwargs) -> None:
            pytest.fail("S3c3c6a tests must never construct HTTPSConnection")

    monkeypatch.setattr(
        acquisition_module,
        "HTTPSConnection",
        ForbiddenHttpsConnection,
    )
    monkeypatch.setattr(socket, "getaddrinfo", forbidden_network)
    monkeypatch.setattr(socket, "create_connection", forbidden_network)
    monkeypatch.setattr(ssl, "create_default_context", forbidden_network)


@pytest.fixture
def bypass_git_gate(monkeypatch) -> None:
    monkeypatch.setattr(e2e_module, "_validate_git_gate", lambda **_kwargs: None)


class FakeTransport:
    def __init__(
        self,
        *,
        fail_at: int | None = None,
        response_factory: Callable[
            [MassiveDailyMarketDataAcquisitionRequest, int],
            MassiveDailyMarketDataHttpResponse,
        ]
        | None = None,
    ) -> None:
        self.calls: list[MassiveDailyMarketDataAcquisitionRequest] = []
        self.fail_at = fail_at
        self.response_factory = response_factory or valid_response

    def get(self, *, request, credential):
        self.calls.append(request)
        if self.fail_at == len(self.calls):
            raise TimeoutError(f"unsafe {SECRET}")
        return self.response_factory(request, len(self.calls))


class SequenceClock:
    def __init__(self, values: tuple[object, ...] = ()) -> None:
        self.values = values or (
            ASSET_OBSERVED_AT,
            BENCHMARK_OBSERVED_AT,
            INGESTION_COMPLETED_AT,
            AVAILABLE_AT,
            CREATED_AT,
        )
        self.calls = 0

    def __call__(self):
        value = self.values[self.calls]
        self.calls += 1
        return value


def config(data_root: Path, **overrides: object):
    data: dict[str, object] = {
        "expected_repository_commit": EXPECTED_COMMIT,
        "acquisition_batch_id": BATCH_ID,
        "data_root": data_root,
        "created_by": CREATED_BY,
        "license_notes": LICENSE_NOTES,
        "credential_source": MassiveAwsSecretsManagerCredentialSource(
            source_kind=MASSIVE_AWS_SECRETS_MANAGER_SOURCE_KIND,
            region=AWS_REGION,
            secret_id=AWS_SECRET_ID,
            json_key=AWS_SECRET_JSON_KEY,
            version_stage=AWS_SECRET_VERSION_STAGE,
        ),
    }
    data.update(overrides)
    return MassiveDailyMarketDataRealE2EConfig(**data)  # type: ignore[arg-type]


def preflight(data_root: Path):
    return build_massive_daily_market_data_real_e2e_preflight(
        config=config(data_root),
        repository_root=REPOSITORY_ROOT,
    )


def prepare(
    data_root: Path,
    *,
    transport: FakeTransport | None = None,
    clock: SequenceClock | None = None,
):
    authority = preflight(data_root)
    return prepare_massive_daily_market_data_real_e2e(
        preflight=authority,
        approved_fingerprint=authority.approval_fingerprint,
        credential=MassiveApiCredential(SECRET),
        transport=FakeTransport() if transport is None else transport,
        clock=SequenceClock() if clock is None else clock,
    )


def valid_response(request, call_number):
    symbol = dict(request.request_parameters)["ticker"]
    body = response_body(request.role, symbol, f"fake-request-{call_number}")
    return MassiveDailyMarketDataHttpResponse(
        status_code=200,
        headers=(
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ),
        body=body,
    )


def response_body(role, symbol, request_id):
    if role is DailyMarketDataSourceCaptureRole.BAR_RESPONSE:
        sessions = derive_us_equity_daily_expected_sessions(
            start_date=date(2024, 1, 2),
            end_date=date(2024, 12, 31),
        ).session_dates
        base = 100 if symbol == "QQQ" else 200
        results = [
            {
                "c": base + 1,
                "h": base + 2,
                "l": base - 1,
                "o": base,
                "t": int(
                    datetime.combine(session, time(12), tzinfo=UTC).timestamp() * 1000
                ),
                "v": 1000 + index,
            }
            for index, session in enumerate(sessions)
        ]
        payload: dict[str, object] = {
            "adjusted": False,
            "queryCount": len(results),
            "request_id": request_id,
            "results": results,
            "resultsCount": len(results),
            "status": "OK",
            "ticker": symbol,
        }
    else:
        payload = {"request_id": request_id, "results": [], "status": "OK"}
    return (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode()


def test_preflight_freezes_approved_authorities(tmp_path, bypass_git_gate) -> None:
    authority = preflight(tmp_path)

    assert authority.asset_plan.instrument.model_dump(mode="json") == {
        "instrument_id": "instrument-us-etf-qqq-xnas",
        "symbol": "QQQ",
        "venue": "XNAS",
    }
    assert authority.benchmark_plan.instrument.model_dump(mode="json") == {
        "instrument_id": "instrument-us-etf-spy-arcx",
        "symbol": "SPY",
        "venue": "ARCX",
    }
    assert authority.policy_hash == MASSIVE_REAL_E2E_POLICY_HASH
    assert authority.research_profile_hash == MASSIVE_REAL_E2E_RESEARCH_PROFILE_HASH
    assert authority.expected_sessions_hash == MASSIVE_REAL_E2E_EXPECTED_SESSION_HASH
    assert len(authority.expected_sessions.session_dates) == 252
    assert authority.expected_sessions.session_dates[0] == date(2024, 1, 2)
    assert authority.expected_sessions.session_dates[-1] == date(2024, 12, 31)
    assert derive_daily_market_data_policy_hash(authority.policy) == (
        MASSIVE_REAL_E2E_POLICY_HASH
    )
    assert (
        derive_daily_market_data_research_profile_hash(authority.research_profile)
        == MASSIVE_REAL_E2E_RESEARCH_PROFILE_HASH
    )
    assert (
        derive_daily_market_data_expected_sessions_hash(authority.expected_sessions)
        == MASSIVE_REAL_E2E_EXPECTED_SESSION_HASH
    )
    assert authority.config.credential_source == (
        MassiveAwsSecretsManagerCredentialSource(
            source_kind="aws-secrets-manager",
            region="us-west-2",
            secret_id="massive/api-key",
            json_key="api_key",
            version_stage="AWSCURRENT",
        )
    )


def test_rejected_profile_source_version_and_hash_are_never_accepted(
    tmp_path,
    bypass_git_gate,
) -> None:
    authority = preflight(tmp_path)
    rejected = authority.research_profile.model_copy(
        update={
            "session_source_version": (
                "exchange-calendars-4.13.2+us-equity-regular-session-dates-v1"
            )
        }
    )

    assert authority.research_profile.session_source_version == (
        "exchange_calendars-4.13.2+us-equity-regular-session-dates-v1"
    )
    assert derive_daily_market_data_research_profile_hash(rejected) == (
        "sha256:c5204ba053f6b074a47fade955fd7bc1133a10cef35a8203d852ce87d530d17d"
    )
    assert derive_daily_market_data_research_profile_hash(rejected) != (
        authority.research_profile_hash
    )
    source = Path(e2e_module.__file__).read_text()
    assert (
        "c5204ba053f6b074a47fade955fd7bc1133a10cef35a8203d852ce87d530d17d" not in source
    )
    assert (
        "5181823807e32dfc6c8a67a775f3355b807ce89b848bb2935e7442f030d5f708" not in source
    )


def test_expected_session_metadata_cannot_be_spoofed_by_a_frozen_hash(
    tmp_path,
    bypass_git_gate,
) -> None:
    authority = preflight(tmp_path)
    altered = authority.expected_sessions.model_copy(
        update={"session_source_version": "hostile-source-version"}
    )

    with pytest.raises(MassiveDailyMarketDataRealE2EError):
        e2e_module._validate_expected_sessions(
            altered,
            MASSIVE_REAL_E2E_EXPECTED_SESSION_HASH,
        )


def test_rejected_profile_source_version_fails_snapshot_compatibility(
    tmp_path,
    bypass_git_gate,
) -> None:
    prepared = prepare(tmp_path)
    rejected = prepared.preflight.research_profile.model_copy(
        update={
            "session_source_version": (
                "exchange-calendars-4.13.2+us-equity-regular-session-dates-v1"
            )
        }
    )

    with pytest.raises(DailyMarketDataSnapshotProfileCompatibilityError):
        validate_daily_market_data_snapshot_profile_compatibility(
            verified_snapshot=prepared.asset_verified_snapshot,
            research_profile=rejected,
        )


def test_profile_source_version_is_fingerprint_authority(
    tmp_path,
    bypass_git_gate,
) -> None:
    authority = preflight(tmp_path)
    approved_payload = e2e_module._approval_payload(
        config=authority.config,
        repository_root=authority.repository_root,
        source_directory=authority.source_capture_managed_directory,
        snapshot_directory=authority.snapshot_managed_directory,
        asset_plan=authority.asset_plan,
        benchmark_plan=authority.benchmark_plan,
        expected_sessions=authority.expected_sessions,
        expected_sessions_hash=authority.expected_sessions_hash,
        policy=authority.policy,
        policy_hash=authority.policy_hash,
        research_profile=authority.research_profile,
        research_profile_hash=authority.research_profile_hash,
    )
    rejected_profile = authority.research_profile.model_copy(
        update={
            "session_source_version": (
                "exchange-calendars-4.13.2+us-equity-regular-session-dates-v1"
            )
        }
    )
    rejected_payload = dict(approved_payload)
    rejected_payload["research_profile"] = rejected_profile.model_dump(mode="json")
    rejected_payload["research_profile_hash"] = (
        derive_daily_market_data_research_profile_hash(rejected_profile)
    )

    assert e2e_module._approval_fingerprint(rejected_payload) != (
        authority.approval_fingerprint
    )


def test_preflight_is_credential_free_and_does_not_mutate_root(
    tmp_path,
    bypass_git_gate,
    monkeypatch,
) -> None:
    before = tuple(tmp_path.iterdir())
    monkeypatch.setattr(
        e2e_module,
        "acquire_and_plan_massive_daily_market_data_source_capture_pair",
        lambda **_kwargs: pytest.fail("preflight called acquisition"),
    )
    monkeypatch.setattr(
        e2e_module,
        "publish_local_daily_market_data_source_capture",
        lambda **_kwargs: pytest.fail("preflight called publication"),
    )

    authority = preflight(tmp_path)

    assert tuple(tmp_path.iterdir()) == before
    assert "credential" not in authority.__dataclass_fields__
    assert SECRET not in authority.approval_fingerprint


def test_preflight_summary_is_complete_and_credential_free(
    tmp_path,
    bypass_git_gate,
) -> None:
    summary = render_massive_daily_market_data_real_e2e_preflight(preflight(tmp_path))

    assert summary.count("REQUEST: ") == 6
    assert "MODE: PREFLIGHT ONLY" in summary
    assert "CREDENTIAL STATUS: NOT REQUESTED" in summary
    assert "CREDENTIAL SOURCE: aws-secrets-manager" in summary
    assert "AWS REGION: us-west-2" in summary
    assert "AWS SECRET ID: massive/api-key" in summary
    assert "AWS SECRET JSON KEY: api_key" in summary
    assert "AWS SECRET VERSION STAGE: AWSCURRENT" in summary
    assert "AWS SECRETS MANAGER STATUS: NOT CONTACTED" in summary
    assert "NO NETWORK REQUEST HAS OCCURRED" in summary
    assert "instrument-us-etf-qqq-xnas" in summary
    assert "instrument-us-etf-spy-arcx" in summary
    assert MASSIVE_REAL_E2E_RESEARCH_PROFILE_HASH in summary
    assert "NETWORK: HTTPS GET only; Authorization Bearer header only" in summary
    assert "read-chunk=65536" in summary
    assert "DNS CAVEAT:" in summary
    assert "request_parameters=" in summary
    assert "requested_scope=" in summary
    assert "source_reference=https://api.massive.com/" in summary
    for request_line in (
        line for line in summary.splitlines() if line.startswith("REQUEST: ")
    ):
        source_reference = request_line.split("source_reference=", 1)[1].split(" ", 1)[
            0
        ]
        assert "?" not in source_reference
    assert SECRET not in summary
    assert "daily-market-data-source-capture-v1-" not in summary
    assert "daily-market-data-snapshot-v2-" not in summary


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("expected_repository_commit", "2" * 40),
        ("acquisition_batch_id", f"{BATCH_ID}-changed"),
        ("created_by", "operator:changed"),
        ("license_notes", "changed explicit notes"),
    ),
)
def test_fingerprint_changes_for_config_authority(
    tmp_path,
    bypass_git_gate,
    field,
    value,
) -> None:
    original = preflight(tmp_path)
    changed = build_massive_daily_market_data_real_e2e_preflight(
        config=config(tmp_path, **{field: value}),
        repository_root=REPOSITORY_ROOT,
    )

    assert changed.approval_fingerprint != original.approval_fingerprint


def test_fingerprint_changes_for_resolved_data_root(
    tmp_path,
    bypass_git_gate,
) -> None:
    other = tmp_path.parent / f"{tmp_path.name}-other"
    other.mkdir()

    assert (
        preflight(tmp_path).approval_fingerprint
        != preflight(other).approval_fingerprint
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("region", "us-east-1"),
        ("secret_id", "massive/alternate-api-key"),
        ("json_key", "alternate_api_key"),
        ("version_stage", "AWSPREVIOUS"),
    ),
)
def test_fingerprint_changes_for_credential_source_authority(
    tmp_path,
    bypass_git_gate,
    field,
    value,
) -> None:
    original = preflight(tmp_path)
    changed_source = replace(
        original.config.credential_source,
        **{field: value},
    )
    changed = build_massive_daily_market_data_real_e2e_preflight(
        config=config(tmp_path, credential_source=changed_source),
        repository_root=REPOSITORY_ROOT,
    )

    assert changed.approval_fingerprint != original.approval_fingerprint


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("source_kind", "other"),
        ("region", " us-west-2"),
        ("region", "--profile"),
        ("secret_id", "massive/api-key\nunsafe"),
        ("secret_id", "--endpoint-url"),
        ("json_key", ""),
        ("version_stage", "AWSCURRENT\u202e"),
        ("version_stage", "--debug"),
    ),
)
def test_credential_source_rejects_noncanonical_or_unsupported_authority(
    tmp_path,
    bypass_git_gate,
    field,
    value,
) -> None:
    source = replace(config(tmp_path).credential_source, **{field: value})

    with pytest.raises(MassiveDailyMarketDataRealE2EError):
        build_massive_daily_market_data_real_e2e_preflight(
            config=config(tmp_path, credential_source=source),
            repository_root=REPOSITORY_ROOT,
        )


def test_credential_source_requires_exact_runtime_type(
    tmp_path,
    bypass_git_gate,
) -> None:
    class CredentialSourceSubclass(MassiveAwsSecretsManagerCredentialSource):
        pass

    source = CredentialSourceSubclass(
        source_kind=MASSIVE_AWS_SECRETS_MANAGER_SOURCE_KIND,
        region=AWS_REGION,
        secret_id=AWS_SECRET_ID,
        json_key=AWS_SECRET_JSON_KEY,
        version_stage=AWS_SECRET_VERSION_STAGE,
    )

    with pytest.raises(MassiveDailyMarketDataRealE2EError):
        build_massive_daily_market_data_real_e2e_preflight(
            config=config(tmp_path, credential_source=source),
            repository_root=REPOSITORY_ROOT,
        )


def test_fingerprint_payload_is_canonical_complete_and_runtime_secret_free(
    tmp_path,
    bypass_git_gate,
) -> None:
    authority = preflight(tmp_path)
    payload = e2e_module._approval_payload(
        config=authority.config,
        repository_root=authority.repository_root,
        source_directory=authority.source_capture_managed_directory,
        snapshot_directory=authority.snapshot_managed_directory,
        asset_plan=authority.asset_plan,
        benchmark_plan=authority.benchmark_plan,
        expected_sessions=authority.expected_sessions,
        expected_sessions_hash=authority.expected_sessions_hash,
        policy=authority.policy,
        policy_hash=authority.policy_hash,
        research_profile=authority.research_profile,
        research_profile_hash=authority.research_profile_hash,
    )

    assert set(payload) == {
        "domain",
        "operator_version",
        "expected_repository_commit",
        "repository_root",
        "provider",
        "source_family",
        "fixed_host",
        "currency",
        "start_date",
        "end_date",
        "asset_plan",
        "benchmark_plan",
        "network_policy",
        "credential_source",
        "acquisition_batch_id",
        "expected_sessions",
        "expected_sessions_hash",
        "data_root",
        "source_capture_managed_directory",
        "snapshot_managed_directory",
        "policy",
        "policy_hash",
        "research_profile",
        "research_profile_hash",
        "created_by",
        "license_notes",
        "context_limitations",
        "confirmation_phrases",
    }
    assert payload["credential_source"] == {
        "source_kind": "aws-secrets-manager",
        "region": "us-west-2",
        "secret_id": "massive/api-key",
        "json_key": "api_key",
        "version_stage": "AWSCURRENT",
    }
    network_policy = payload["network_policy"]
    assert network_policy == {
        "scheme": "https",
        "method": "GET",
        "authentication": "Authorization: Bearer <runtime credential>",
        "maximum_inclusive_calendar_days": 366,
        "role_response_size_limits_bytes": {
            "bar_response": acquisition_module._BAR_RESPONSE_SIZE_LIMIT_BYTES,
            "dividend_response": (
                acquisition_module._CORPORATE_ACTION_RESPONSE_SIZE_LIMIT_BYTES
            ),
            "split_response": (
                acquisition_module._CORPORATE_ACTION_RESPONSE_SIZE_LIMIT_BYTES
            ),
        },
        "instrument_response_size_limit_bytes": (
            acquisition_module._INSTRUMENT_RESPONSE_SIZE_LIMIT_BYTES
        ),
        "pair_response_size_limit_bytes": (
            acquisition_module._PAIR_RESPONSE_SIZE_LIMIT_BYTES
        ),
        "response_read_chunk_size_bytes": acquisition_module._READ_CHUNK_SIZE_BYTES,
        "connect_timeout_seconds": acquisition_module._CONNECT_TIMEOUT_SECONDS,
        "read_inactivity_timeout_seconds": (
            acquisition_module._READ_INACTIVITY_TIMEOUT_SECONDS
        ),
        "application_acceptance_deadline_seconds": (
            acquisition_module._OVERALL_REQUEST_DEADLINE_SECONDS
        ),
        "automatic_retries": False,
        "redirect_following": False,
        "pagination_following": False,
        "request_order": (
            "asset:bar_response",
            "asset:dividend_response",
            "asset:split_response",
            "benchmark:bar_response",
            "benchmark:dividend_response",
            "benchmark:split_response",
        ),
    }
    rendered = json.dumps(payload, sort_keys=True)
    for excluded in (
        SECRET,
        "Authorization: Bearer synthetic",
        "capture_observed_at",
        "ingestion_completed_at",
        "available_at",
        "created_at",
        "api_request_id",
        "capture_id",
        "snapshot_id",
    ):
        assert excluded not in rendered
    reversed_payload = dict(reversed(tuple(payload.items())))
    assert e2e_module._approval_fingerprint(reversed_payload) == (
        authority.approval_fingerprint
    )
    changed_payload = dict(payload)
    changed_asset = dict(changed_payload["asset_plan"])
    changed_asset["requests"] = tuple(reversed(changed_asset["requests"]))
    changed_payload["asset_plan"] = changed_asset
    assert e2e_module._approval_fingerprint(changed_payload) != (
        authority.approval_fingerprint
    )


def test_v2_authority_rejects_historical_v1_fingerprint(
    tmp_path,
    bypass_git_gate,
) -> None:
    authority = preflight(tmp_path)
    payload = e2e_module._approval_payload(
        config=authority.config,
        repository_root=authority.repository_root,
        source_directory=authority.source_capture_managed_directory,
        snapshot_directory=authority.snapshot_managed_directory,
        asset_plan=authority.asset_plan,
        benchmark_plan=authority.benchmark_plan,
        expected_sessions=authority.expected_sessions,
        expected_sessions_hash=authority.expected_sessions_hash,
        policy=authority.policy,
        policy_hash=authority.policy_hash,
        research_profile=authority.research_profile,
        research_profile_hash=authority.research_profile_hash,
    )
    historical = dict(payload)
    historical["domain"] = "massive-real-e2e-operational-approval-v1"
    historical["operator_version"] = "massive-real-e2e-operator-v1"
    historical_fingerprint = e2e_module._approval_fingerprint(historical)
    transport = FakeTransport()

    assert MASSIVE_REAL_E2E_OPERATOR_VERSION == "massive-real-e2e-operator-v2"
    assert MASSIVE_REAL_E2E_APPROVAL_DOMAIN == (
        "massive-real-e2e-operational-approval-v2"
    )
    assert historical_fingerprint != authority.approval_fingerprint
    with pytest.raises(MassiveDailyMarketDataRealE2EError):
        prepare_massive_daily_market_data_real_e2e(
            preflight=authority,
            approved_fingerprint=historical_fingerprint,
            credential=MassiveApiCredential(SECRET),
            transport=transport,
            clock=SequenceClock(),
        )
    assert transport.calls == []


def test_fixed_instrument_builders_do_not_reuse_mutable_contract_instances() -> None:
    asset = e2e_module._build_asset_instrument()
    benchmark = e2e_module._build_benchmark_instrument()
    object.__setattr__(asset, "symbol", "HOSTILE")
    object.__setattr__(benchmark, "venue", "HOSTILE")

    assert e2e_module._build_asset_instrument().model_dump(mode="json") == {
        "instrument_id": "instrument-us-etf-qqq-xnas",
        "symbol": "QQQ",
        "venue": "XNAS",
    }
    assert e2e_module._build_benchmark_instrument().model_dump(mode="json") == {
        "instrument_id": "instrument-us-etf-spy-arcx",
        "symbol": "SPY",
        "venue": "ARCX",
    }


def test_network_policy_builder_returns_fresh_authority_from_s3c3c5_constants() -> None:
    first = e2e_module._build_operational_network_policy()
    first["automatic_retries"] = True
    role_limits = first["role_response_size_limits_bytes"]
    assert type(role_limits) is dict
    role_limits["bar_response"] = 1

    second = e2e_module._build_operational_network_policy()

    assert second["automatic_retries"] is False
    assert second["maximum_inclusive_calendar_days"] == (
        acquisition_module._MAX_DATE_SPAN_DAYS + 1
    )
    assert second["role_response_size_limits_bytes"] == {
        "bar_response": acquisition_module._BAR_RESPONSE_SIZE_LIMIT_BYTES,
        "dividend_response": (
            acquisition_module._CORPORATE_ACTION_RESPONSE_SIZE_LIMIT_BYTES
        ),
        "split_response": (
            acquisition_module._CORPORATE_ACTION_RESPONSE_SIZE_LIMIT_BYTES
        ),
    }


@pytest.mark.parametrize(
    "overrides",
    (
        {"expected_repository_commit": "not-a-sha"},
        {"acquisition_batch_id": " batch"},
        {"acquisition_batch_id": "batch\x1b[31m"},
        {"acquisition_batch_id": "x" * 129},
        {"acquisition_batch_id": "Bearer-not-a-secret"},
        {"created_by": ""},
        {"created_by": "operator\nspoofed"},
        {"license_notes": "   "},
        {"license_notes": "notes\u202espoofed"},
    ),
)
def test_preflight_rejects_invalid_config_before_effects(
    tmp_path,
    bypass_git_gate,
    overrides,
) -> None:
    with pytest.raises(MassiveDailyMarketDataRealE2EError):
        build_massive_daily_market_data_real_e2e_preflight(
            config=config(tmp_path, **overrides),
            repository_root=REPOSITORY_ROOT,
        )
    assert tuple(tmp_path.iterdir()) == ()


def test_preflight_dependency_failures_are_sanitized(
    tmp_path,
    bypass_git_gate,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        e2e_module,
        "plan_massive_daily_market_data_acquisition",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError(f"unsafe {SECRET}")),
    )

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        preflight(tmp_path)

    assert SECRET not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert tuple(tmp_path.iterdir()) == ()


def test_preflight_rejects_relative_missing_symlink_and_repository_roots(
    tmp_path,
    bypass_git_gate,
) -> None:
    missing = tmp_path / "missing"
    symlink = tmp_path.parent / f"{tmp_path.name}-link"
    symlink.symlink_to(tmp_path, target_is_directory=True)
    for root in (
        Path("relative"),
        missing,
        symlink,
        REPOSITORY_ROOT,
        REPOSITORY_ROOT.parent,
    ):
        with pytest.raises(MassiveDailyMarketDataRealE2EError):
            build_massive_daily_market_data_real_e2e_preflight(
                config=config(root),
                repository_root=REPOSITORY_ROOT,
            )


@pytest.mark.parametrize(
    "managed_name", ("daily-market-data-source-captures", "daily-market-data")
)
@pytest.mark.parametrize("kind", ("symlink", "file"))
def test_preflight_rejects_unsafe_existing_managed_locations(
    tmp_path,
    bypass_git_gate,
    managed_name,
    kind,
) -> None:
    managed = tmp_path / managed_name
    if kind == "symlink":
        target = tmp_path / "managed-target"
        target.mkdir()
        managed.symlink_to(target, target_is_directory=True)
    else:
        managed.write_bytes(b"not a directory")

    with pytest.raises(MassiveDailyMarketDataRealE2EError):
        preflight(tmp_path)


def test_preflight_call_graph_has_no_effectful_acquisition_or_publication() -> None:
    source = inspect.getsource(
        e2e_module.build_massive_daily_market_data_real_e2e_preflight
    )

    for forbidden in (
        "MassiveApiCredential",
        "acquire_and_plan_massive",
        "publish_local",
        "load_local",
        "HTTPSConnection",
        "socket",
        "getpass",
        "mkdir",
        "write_",
        "fetch",
    ):
        assert forbidden not in source


@pytest.mark.parametrize(
    "state_override",
    (
        {"branch": "feature"},
        {"clean": False},
        {"head": "2" * 40},
        {"main": "2" * 40},
        {"origin_main": "2" * 40},
        {"repository_root": Path("/")},
    ),
)
def test_git_gate_fails_closed(tmp_path, monkeypatch, state_override) -> None:
    state = e2e_module._GitState(
        repository_root=REPOSITORY_ROOT,
        branch="main",
        head=EXPECTED_COMMIT,
        main=EXPECTED_COMMIT,
        origin_main=EXPECTED_COMMIT,
        clean=True,
    )
    monkeypatch.setattr(
        e2e_module,
        "_capture_git_state",
        lambda _root: replace(state, **state_override),
    )

    with pytest.raises(MassiveDailyMarketDataRealE2EError):
        preflight(tmp_path)
    assert tuple(tmp_path.iterdir()) == ()


def test_git_gate_uses_only_fixed_read_only_commands_and_exact_output(
    monkeypatch,
) -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []
    outputs = iter(
        (
            f"{REPOSITORY_ROOT}\n",
            "main\n",
            f"{EXPECTED_COMMIT}\n",
            f"{EXPECTED_COMMIT}\n",
            f"{EXPECTED_COMMIT}\n",
            "",
        )
    )

    def run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return subprocess.CompletedProcess(arguments, 0, next(outputs), "")

    monkeypatch.setattr(e2e_module.subprocess, "run", run)

    state = e2e_module._capture_git_state(REPOSITORY_ROOT)

    assert state.branch == "main"
    assert [call[0][3:] for call in calls] == [
        ("rev-parse", "--show-toplevel"),
        ("branch", "--show-current"),
        ("rev-parse", "HEAD"),
        ("rev-parse", "main"),
        ("rev-parse", "origin/main"),
        ("status", "--porcelain=v1"),
    ]
    assert all(call[0][:3] == ("git", "-C", str(REPOSITORY_ROOT)) for call in calls)
    assert all(call[1]["shell"] is False for call in calls)


def test_git_output_and_errors_fail_closed_without_unsafe_details(monkeypatch) -> None:
    monkeypatch.setattr(
        e2e_module.subprocess,
        "run",
        lambda arguments, **_kwargs: subprocess.CompletedProcess(
            arguments,
            0,
            f"{EXPECTED_COMMIT}\n\n",
            "",
        ),
    )
    assert e2e_module._git(REPOSITORY_ROOT, "rev-parse", "HEAD") == (
        f"{EXPECTED_COMMIT}\n"
    )

    monkeypatch.setattr(
        e2e_module.subprocess,
        "run",
        lambda arguments, **_kwargs: subprocess.CompletedProcess(
            arguments,
            1,
            "",
            f"unsafe {SECRET}",
        ),
    )

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        e2e_module._git(REPOSITORY_ROOT, "rev-parse", "HEAD")

    assert SECRET not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_prepare_happy_path_stops_before_snapshot_publication(
    tmp_path,
    bypass_git_gate,
) -> None:
    transport = FakeTransport()
    clock = SequenceClock()

    prepared = prepare(tmp_path, transport=transport, clock=clock)

    assert len(transport.calls) == 6
    assert [dict(call.request_parameters)["ticker"] for call in transport.calls] == [
        "QQQ",
        "QQQ",
        "QQQ",
        "SPY",
        "SPY",
        "SPY",
    ]
    assert clock.calls == 5
    assert prepared.ingestion_completed_at == INGESTION_COMPLETED_AT
    assert prepared.available_at == AVAILABLE_AT
    assert prepared.created_at == CREATED_AT
    assert prepared.asset_source_publication.path.is_dir()
    assert prepared.benchmark_source_publication.path.is_dir()
    assert not (tmp_path / "daily-market-data").exists()
    assert prepared.asset_verified_snapshot.snapshot_id == (
        prepared.asset_snapshot_plan.snapshot_id
    )
    assert prepared.benchmark_verified_snapshot.snapshot_id == (
        prepared.benchmark_snapshot_plan.snapshot_id
    )
    assert validate_massive_daily_market_data_real_e2e_prepared(prepared) == prepared
    assert SECRET not in repr(prepared)


def test_falsey_transport_and_clock_are_used_without_default_substitution(
    tmp_path,
    bypass_git_gate,
) -> None:
    class FalseyTransport(FakeTransport):
        def __bool__(self) -> bool:
            return False

    class FalseyClock(SequenceClock):
        def __bool__(self) -> bool:
            return False

    transport = FalseyTransport()
    clock = FalseyClock()

    prepare(tmp_path, transport=transport, clock=clock)

    assert len(transport.calls) == 6
    assert clock.calls == 5


def test_tampered_nested_preflight_values_are_ignored_in_favor_of_rederivation(
    tmp_path,
    bypass_git_gate,
) -> None:
    authority = preflight(tmp_path)
    hostile_request = replace(authority.asset_plan.requests[0], path="//hostile")
    hostile_asset_plan = replace(
        authority.asset_plan,
        requests=(hostile_request, *authority.asset_plan.requests[1:]),
    )
    hostile = replace(authority, asset_plan=hostile_asset_plan)
    transport = FakeTransport()

    prepared = prepare_massive_daily_market_data_real_e2e(
        preflight=hostile,
        approved_fingerprint=authority.approval_fingerprint,
        credential=MassiveApiCredential(SECRET),
        transport=transport,
        clock=SequenceClock(),
    )

    assert transport.calls[0].path == authority.asset_plan.requests[0].path
    assert prepared.preflight.asset_plan == authority.asset_plan


@pytest.mark.parametrize("fail_at", range(1, 7))
def test_request_failures_return_no_prepared_or_durable_state(
    tmp_path,
    bypass_git_gate,
    fail_at,
) -> None:
    transport = FakeTransport(fail_at=fail_at)
    authority = preflight(tmp_path)

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        prepare_massive_daily_market_data_real_e2e(
            preflight=authority,
            approved_fingerprint=authority.approval_fingerprint,
            credential=MassiveApiCredential(SECRET),
            transport=transport,
            clock=SequenceClock(),
        )

    assert len(transport.calls) == fail_at
    assert not tuple(tmp_path.iterdir())
    failed_request = transport.calls[-1]
    assert (
        "reason: Massive transport failed for "
        f"{failed_request.role.value} at {failed_request.path}"
    ) in str(caught.value)
    assert SECRET not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_internal_transport_stage_reason_reaches_s3c3c6_without_publication(
    tmp_path,
    bypass_git_gate,
    monkeypatch,
) -> None:
    class StubSocket:
        def settimeout(self, _value: float) -> None:
            pass

    class FailingRequestConnection:
        instances = 0

        def __init__(self, _host, *, timeout, context) -> None:
            type(self).instances += 1
            self.timeout = timeout
            self.sock = StubSocket()

        def connect(self) -> None:
            pass

        def request(self, _method, _target, *, headers) -> None:
            raise OSError(f"SECRET_SENTINEL Bearer {SECRET}")

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        acquisition_module,
        "HTTPSConnection",
        FailingRequestConnection,
    )
    monkeypatch.setattr(
        acquisition_module.ssl,
        "create_default_context",
        lambda: object(),
    )
    authority = preflight(tmp_path)

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        prepare_massive_daily_market_data_real_e2e(
            preflight=authority,
            approved_fingerprint=authority.approval_fingerprint,
            credential=MassiveApiCredential(SECRET),
            transport=None,
            clock=SequenceClock(),
        )

    assert (
        "reason: Massive HTTPS request send failed for BAR_RESPONSE at "
        "/v2/aggs/ticker/QQQ/range/1/day/2024-01-02/2024-12-31"
    ) in str(caught.value)
    assert "SECRET_SENTINEL" not in str(caught.value)
    assert SECRET not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert FailingRequestConnection.instances == 1
    assert tuple(tmp_path.iterdir()) == ()


def test_safe_http_403_corporate_action_reason_survives_without_body(
    tmp_path,
    bypass_git_gate,
) -> None:
    raw_body = f"unsafe raw body Authorization: Bearer {SECRET}".encode()

    def forbidden_dividend(request, call_number):
        if request.role is DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE:
            return MassiveDailyMarketDataHttpResponse(
                status_code=403,
                headers=(("Content-Type", "text/plain"),),
                body=raw_body,
            )
        return valid_response(request, call_number)

    transport = FakeTransport(response_factory=forbidden_dividend)

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        prepare(tmp_path, transport=transport)

    rendered = str(caught.value)
    assert "reason: Massive returned HTTP 403 for DIVIDEND_RESPONSE" in rendered
    assert len(transport.calls) == 2
    assert raw_body.decode() not in rendered
    assert "Authorization" not in rendered
    assert SECRET not in rendered
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert tuple(tmp_path.iterdir()) == ()


def test_safe_pagination_reason_survives_without_raw_body(
    tmp_path,
    bypass_git_gate,
) -> None:
    raw_marker = "RAW_PROVIDER_BODY_MUST_NOT_SURFACE"

    def paginated(request, _call_number):
        body = json.dumps(
            {
                "next_url": None,
                "request_id": "safe-request-id",
                "results": [raw_marker],
                "status": "OK",
            },
            separators=(",", ":"),
        ).encode()
        return MassiveDailyMarketDataHttpResponse(
            status_code=200,
            headers=(
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body))),
            ),
            body=body,
        )

    transport = FakeTransport(response_factory=paginated)

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        prepare(tmp_path, transport=transport)

    rendered = str(caught.value)
    assert "reason: pagination is unsupported for BAR_RESPONSE" in rendered
    assert raw_marker not in rendered
    assert len(transport.calls) == 1
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert tuple(tmp_path.iterdir()) == ()


def test_safe_response_size_and_content_policy_reasons_survive(
    tmp_path,
    bypass_git_gate,
) -> None:
    def oversized_length(request, _call_number):
        body = b'{"request_id":"safe","status":"OK"}'
        return MassiveDailyMarketDataHttpResponse(
            status_code=200,
            headers=(
                ("Content-Type", "application/json"),
                ("Content-Length", str(request.response_size_limit_bytes + 1)),
            ),
            body=body,
        )

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as size_caught:
        prepare(tmp_path, transport=FakeTransport(response_factory=oversized_length))

    assert "reason: Massive response Content-Length exceeds the role byte limit" in (
        str(size_caught.value)
    )
    assert size_caught.value.__cause__ is None
    assert size_caught.value.__context__ is None
    assert tuple(tmp_path.iterdir()) == ()

    raw_body = f"RAW_BODY Authorization: Bearer {SECRET}".encode()

    def wrong_media(_request, _call_number):
        return MassiveDailyMarketDataHttpResponse(
            status_code=200,
            headers=(
                ("Content-Type", "text/html"),
                ("Content-Length", str(len(raw_body))),
            ),
            body=raw_body,
        )

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as media_caught:
        prepare(tmp_path, transport=FakeTransport(response_factory=wrong_media))

    rendered = str(media_caught.value)
    assert "reason: Massive response Content-Type must be application/json" in rendered
    assert raw_body.decode() not in rendered
    assert "Authorization" not in rendered
    assert SECRET not in rendered
    assert media_caught.value.__cause__ is None
    assert media_caught.value.__context__ is None
    assert tuple(tmp_path.iterdir()) == ()


def test_untrusted_non_acquisition_exception_remains_generic(
    tmp_path,
    bypass_git_gate,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        e2e_module,
        "acquire_and_plan_massive_daily_market_data_source_capture_pair",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError(f"unsafe {SECRET}")),
    )
    authority = preflight(tmp_path)

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        prepare_massive_daily_market_data_real_e2e(
            preflight=authority,
            approved_fingerprint=authority.approval_fingerprint,
            credential=MassiveApiCredential(SECRET),
            transport=FakeTransport(),
            clock=SequenceClock(),
        )

    assert str(caught.value) == (
        "Massive real-E2E stage failed: Massive six-request acquisition"
    )
    assert SECRET not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert tuple(tmp_path.iterdir()) == ()


def test_untrusted_acquisition_error_subclass_remains_generic(
    tmp_path,
    bypass_git_gate,
    monkeypatch,
) -> None:
    class UntrustedAcquisitionError(MassiveDailyMarketDataAcquisitionError):
        pass

    monkeypatch.setattr(
        e2e_module,
        "acquire_and_plan_massive_daily_market_data_source_capture_pair",
        lambda **_kwargs: (_ for _ in ()).throw(
            UntrustedAcquisitionError(f"unsafe {SECRET}")
        ),
    )
    authority = preflight(tmp_path)

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        prepare_massive_daily_market_data_real_e2e(
            preflight=authority,
            approved_fingerprint=authority.approval_fingerprint,
            credential=MassiveApiCredential(SECRET),
            transport=FakeTransport(),
            clock=SequenceClock(),
        )

    assert str(caught.value) == (
        "Massive real-E2E stage failed: Massive six-request acquisition"
    )
    assert SECRET not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert tuple(tmp_path.iterdir()) == ()


def test_exact_acquisition_error_reason_containing_credential_is_suppressed(
    tmp_path,
    bypass_git_gate,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        e2e_module,
        "acquire_and_plan_massive_daily_market_data_source_capture_pair",
        lambda **_kwargs: (_ for _ in ()).throw(
            MassiveDailyMarketDataAcquisitionError(f"unsafe {SECRET}")
        ),
    )
    authority = preflight(tmp_path)

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        prepare_massive_daily_market_data_real_e2e(
            preflight=authority,
            approved_fingerprint=authority.approval_fingerprint,
            credential=MassiveApiCredential(SECRET),
            transport=FakeTransport(),
            clock=SequenceClock(),
        )

    assert str(caught.value) == (
        "Massive real-E2E stage failed: Massive six-request acquisition"
    )
    assert SECRET not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert tuple(tmp_path.iterdir()) == ()


def test_safe_diagnostic_collision_with_short_credential_is_suppressed(
    tmp_path,
    bypass_git_gate,
) -> None:
    short_secret = "401"

    def unauthorized(_request, _call_number):
        return MassiveDailyMarketDataHttpResponse(
            status_code=401,
            headers=(("Content-Type", "application/json"),),
            body=b"",
        )

    authority = preflight(tmp_path)

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        prepare_massive_daily_market_data_real_e2e(
            preflight=authority,
            approved_fingerprint=authority.approval_fingerprint,
            credential=MassiveApiCredential(short_secret),
            transport=FakeTransport(response_factory=unauthorized),
            clock=SequenceClock(),
        )

    assert str(caught.value) == (
        "Massive real-E2E stage failed: Massive six-request acquisition"
    )
    assert short_secret not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert tuple(tmp_path.iterdir()) == ()


def test_clock_exception_exposes_only_s3c3c5_safe_reason(
    tmp_path,
    bypass_git_gate,
) -> None:
    class UnsafeClock:
        def __call__(self):
            raise RuntimeError(f"unsafe {SECRET}")

    transport = FakeTransport()

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        prepare(tmp_path, transport=transport, clock=UnsafeClock())  # type: ignore[arg-type]

    rendered = str(caught.value)
    assert "reason: capture clock failed for QQQ" in rendered
    assert SECRET not in rendered
    assert SECRET not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert len(transport.calls) == 3
    assert tuple(tmp_path.iterdir()) == ()


def test_wrong_fingerprint_fails_before_transport(
    tmp_path,
    bypass_git_gate,
) -> None:
    transport = FakeTransport()
    authority = preflight(tmp_path)

    with pytest.raises(MassiveDailyMarketDataRealE2EError):
        prepare_massive_daily_market_data_real_e2e(
            preflight=authority,
            approved_fingerprint=f"sha256:{'0' * 64}",
            credential=MassiveApiCredential(SECRET),
            transport=transport,
            clock=SequenceClock(),
        )

    assert transport.calls == []
    assert tuple(tmp_path.iterdir()) == ()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("created_by", f"operator:{SECRET}"),
        ("license_notes", f"notes containing {SECRET} exactly"),
        ("acquisition_batch_id", f"batch-{SECRET}"),
    ),
)
def test_runtime_credential_cannot_enter_persistent_preflight_authority(
    tmp_path,
    bypass_git_gate,
    field,
    value,
) -> None:
    reviewed = build_massive_daily_market_data_real_e2e_preflight(
        config=config(tmp_path, **{field: value}),
        repository_root=REPOSITORY_ROOT,
    )
    transport = FakeTransport()

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        prepare_massive_daily_market_data_real_e2e(
            preflight=reviewed,
            approved_fingerprint=reviewed.approval_fingerprint,
            credential=MassiveApiCredential(SECRET),
            transport=transport,
            clock=SequenceClock(),
        )

    assert transport.calls == []
    assert SECRET not in str(caught.value)
    assert tuple(tmp_path.iterdir()) == ()


def test_tampered_preflight_fails_before_transport(
    tmp_path,
    bypass_git_gate,
) -> None:
    authority = preflight(tmp_path)
    tampered = replace(authority, approval_fingerprint=f"sha256:{'0' * 64}")
    transport = FakeTransport()

    with pytest.raises(MassiveDailyMarketDataRealE2EError):
        prepare_massive_daily_market_data_real_e2e(
            preflight=tampered,
            approved_fingerprint=authority.approval_fingerprint,
            credential=MassiveApiCredential(SECRET),
            transport=transport,
            clock=SequenceClock(),
        )
    assert transport.calls == []


def test_both_in_memory_verifications_precede_publication(
    tmp_path,
    bypass_git_gate,
    monkeypatch,
) -> None:
    events: list[str] = []
    original_verify = e2e_module.verify_daily_market_data_source_capture
    original_adapt = e2e_module.adapt_massive_daily_market_data_source_capture
    original_pair = (
        e2e_module.validate_massive_daily_market_data_capture_pair_compatibility
    )
    original_publish = e2e_module.publish_local_daily_market_data_source_capture

    def verify(files):
        events.append("verify")
        return original_verify(files)

    def publish(**kwargs):
        events.append("publish")
        return original_publish(**kwargs)

    def adapt(**kwargs):
        events.append("adapt")
        return original_adapt(**kwargs)

    def pair(**kwargs):
        events.append("pair")
        return original_pair(**kwargs)

    monkeypatch.setattr(e2e_module, "verify_daily_market_data_source_capture", verify)
    monkeypatch.setattr(
        e2e_module,
        "publish_local_daily_market_data_source_capture",
        publish,
    )
    monkeypatch.setattr(
        e2e_module,
        "adapt_massive_daily_market_data_source_capture",
        adapt,
    )
    monkeypatch.setattr(
        e2e_module,
        "validate_massive_daily_market_data_capture_pair_compatibility",
        pair,
    )

    prepare(tmp_path)

    assert events[:5] == ["verify", "verify", "adapt", "adapt", "pair"]
    assert events.index("publish") == 5


@pytest.mark.parametrize("fail_at", (1, 2))
def test_each_in_memory_source_verification_failure_prevents_publication(
    tmp_path,
    bypass_git_gate,
    monkeypatch,
    fail_at,
) -> None:
    original = e2e_module.verify_daily_market_data_source_capture
    calls = 0

    def verify(files):
        nonlocal calls
        calls += 1
        if calls == fail_at:
            raise ValueError(f"unsafe {SECRET}")
        return original(files)

    monkeypatch.setattr(e2e_module, "verify_daily_market_data_source_capture", verify)

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        prepare(tmp_path)

    assert calls == fail_at
    assert tuple(tmp_path.iterdir()) == ()
    assert SECRET not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize("fail_at", (1, 2))
def test_each_in_memory_adapter_failure_prevents_publication(
    tmp_path,
    bypass_git_gate,
    monkeypatch,
    fail_at,
) -> None:
    original = e2e_module.adapt_massive_daily_market_data_source_capture
    calls = 0

    def adapt(**kwargs):
        nonlocal calls
        calls += 1
        if calls == fail_at:
            raise ValueError(f"unsafe {SECRET}")
        return original(**kwargs)

    monkeypatch.setattr(
        e2e_module,
        "adapt_massive_daily_market_data_source_capture",
        adapt,
    )

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        prepare(tmp_path)

    assert calls == fail_at
    assert tuple(tmp_path.iterdir()) == ()
    assert SECRET not in str(caught.value)


def test_expected_session_recheck_failure_prevents_publication(
    tmp_path,
    bypass_git_gate,
    monkeypatch,
) -> None:
    authority = preflight(tmp_path)
    transport = FakeTransport()
    original = e2e_module.derive_us_equity_daily_expected_sessions
    calls = 0

    def derive(**kwargs):
        nonlocal calls
        calls += 1
        sessions = original(**kwargs)
        if calls == 2:
            return sessions.model_copy(
                update={"session_dates": sessions.session_dates[:-1]}
            )
        return sessions

    monkeypatch.setattr(
        e2e_module,
        "derive_us_equity_daily_expected_sessions",
        derive,
    )

    with pytest.raises(MassiveDailyMarketDataRealE2EError):
        prepare_massive_daily_market_data_real_e2e(
            preflight=authority,
            approved_fingerprint=authority.approval_fingerprint,
            credential=MassiveApiCredential(SECRET),
            transport=transport,
            clock=SequenceClock(),
        )

    assert len(transport.calls) == 6
    assert tuple(tmp_path.iterdir()) == ()


def test_profile_hash_recheck_failure_prevents_publication(
    tmp_path,
    bypass_git_gate,
    monkeypatch,
) -> None:
    authority = preflight(tmp_path)
    transport = FakeTransport()
    original = e2e_module.derive_daily_market_data_research_profile_hash
    calls = 0

    def derive(profile):
        nonlocal calls
        calls += 1
        if calls == 2:
            return f"sha256:{'0' * 64}"
        return original(profile)

    monkeypatch.setattr(
        e2e_module,
        "derive_daily_market_data_research_profile_hash",
        derive,
    )

    with pytest.raises(MassiveDailyMarketDataRealE2EError):
        prepare_massive_daily_market_data_real_e2e(
            preflight=authority,
            approved_fingerprint=authority.approval_fingerprint,
            credential=MassiveApiCredential(SECRET),
            transport=transport,
            clock=SequenceClock(),
        )

    assert len(transport.calls) == 6
    assert tuple(tmp_path.iterdir()) == ()


def test_downstream_revalidation_exception_is_secret_safe(
    tmp_path,
    bypass_git_gate,
    monkeypatch,
) -> None:
    authority = preflight(tmp_path)
    transport = FakeTransport()
    original = e2e_module.derive_daily_market_data_research_profile_hash
    calls = 0

    def derive(profile):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError(f"unsafe {SECRET}")
        return original(profile)

    monkeypatch.setattr(
        e2e_module,
        "derive_daily_market_data_research_profile_hash",
        derive,
    )

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        prepare_massive_daily_market_data_real_e2e(
            preflight=authority,
            approved_fingerprint=authority.approval_fingerprint,
            credential=MassiveApiCredential(SECRET),
            transport=transport,
            clock=SequenceClock(),
        )

    assert len(transport.calls) == 6
    assert tuple(tmp_path.iterdir()) == ()
    assert SECRET not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_pair_compatibility_failure_prevents_publication(
    tmp_path,
    bypass_git_gate,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        e2e_module,
        "validate_massive_daily_market_data_capture_pair_compatibility",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("unsafe")),
    )

    with pytest.raises(MassiveDailyMarketDataRealE2EError):
        prepare(tmp_path)
    assert not tuple(tmp_path.iterdir())


def test_adapter_failure_prevents_publication(
    tmp_path,
    bypass_git_gate,
) -> None:
    def invalid_response(request, call_number):
        response = valid_response(request, call_number)
        if request.role is DailyMarketDataSourceCaptureRole.BAR_RESPONSE:
            body = b'{"request_id":"x","results":"bad","status":"OK"}\n'
            return MassiveDailyMarketDataHttpResponse(
                status_code=200,
                headers=(
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(body))),
                ),
                body=body,
            )
        return response

    with pytest.raises(MassiveDailyMarketDataRealE2EError):
        prepare(tmp_path, transport=FakeTransport(response_factory=invalid_response))
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize("fail_at", (1, 2))
def test_source_publication_failure_reports_only_prior_durable_capture(
    tmp_path,
    bypass_git_gate,
    monkeypatch,
    fail_at,
) -> None:
    original = e2e_module.publish_local_daily_market_data_source_capture
    calls = 0

    def publish(**kwargs):
        nonlocal calls
        calls += 1
        if calls == fail_at:
            raise OSError(f"unsafe {SECRET}")
        return original(**kwargs)

    monkeypatch.setattr(
        e2e_module,
        "publish_local_daily_market_data_source_capture",
        publish,
    )

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        prepare(tmp_path)

    assert len(caught.value.durable_artifacts) == fail_at - 1
    if fail_at == 1:
        assert not (tmp_path / "daily-market-data-source-captures").exists()
    else:
        captures = tuple((tmp_path / "daily-market-data-source-captures").iterdir())
        assert len(captures) == 2  # one immutable capture plus .staging
        assert "QQQ source capture" in caught.value.durable_artifacts[0]
    assert SECRET not in str(caught.value)


@pytest.mark.parametrize("fail_at", (1, 2))
def test_source_readback_failure_reports_only_durable_captures(
    tmp_path,
    bypass_git_gate,
    monkeypatch,
    fail_at,
) -> None:
    original = e2e_module.load_local_daily_market_data_source_capture
    calls = 0

    def load(**kwargs):
        nonlocal calls
        calls += 1
        if calls == fail_at:
            raise OSError(f"unsafe {SECRET}")
        return original(**kwargs)

    monkeypatch.setattr(
        e2e_module,
        "load_local_daily_market_data_source_capture",
        load,
    )

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        prepare(tmp_path)

    assert len(caught.value.durable_artifacts) == fail_at
    assert SECRET not in str(caught.value)


def test_bridge_failure_retains_sources_and_returns_no_prepared(
    tmp_path,
    bypass_git_gate,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        e2e_module,
        "plan_massive_daily_market_data_snapshot_v2",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError(f"unsafe {SECRET}")),
    )

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        prepare(tmp_path)

    captures = tuple((tmp_path / "daily-market-data-source-captures").iterdir())
    assert len(captures) == 3  # two immutable captures plus .staging
    assert len(caught.value.durable_artifacts) == 2
    assert SECRET not in str(caught.value)
    assert not (tmp_path / "daily-market-data").exists()


@pytest.mark.parametrize(
    ("target", "stage_fragment"),
    (
        ("verify_daily_market_data_snapshot_bundle_v2", "pure verification"),
        (
            "validate_daily_market_data_snapshot_profile_compatibility",
            "research-profile compatibility",
        ),
    ),
)
@pytest.mark.parametrize("fail_at", (1, 2))
def test_each_snapshot_validation_failure_retains_sources_without_prepared(
    tmp_path,
    bypass_git_gate,
    monkeypatch,
    target,
    stage_fragment,
    fail_at,
) -> None:
    original = getattr(e2e_module, target)
    calls = 0

    def fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == fail_at:
            raise ValueError(f"unsafe {SECRET}")
        return original(*args, **kwargs)

    monkeypatch.setattr(e2e_module, target, fail)

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        prepare(tmp_path)

    assert calls == fail_at
    assert stage_fragment in str(caught.value)
    assert len(caught.value.durable_artifacts) == 2
    assert SECRET not in str(caught.value)
    assert not (tmp_path / "daily-market-data").exists()


@pytest.mark.parametrize(
    "clock_values",
    (
        (
            ASSET_OBSERVED_AT,
            BENCHMARK_OBSERVED_AT,
            datetime(2026, 8, 20, 15, 0, tzinfo=UTC),
            AVAILABLE_AT,
            CREATED_AT,
        ),
        (
            ASSET_OBSERVED_AT,
            BENCHMARK_OBSERVED_AT,
            INGESTION_COMPLETED_AT,
            datetime(2026, 8, 20, 17, 0, tzinfo=UTC),
            CREATED_AT,
        ),
        (
            ASSET_OBSERVED_AT,
            BENCHMARK_OBSERVED_AT,
            INGESTION_COMPLETED_AT,
            AVAILABLE_AT,
            datetime(2026, 8, 20, 18, 30, tzinfo=UTC),
        ),
    ),
)
def test_chronology_fails_closed(
    tmp_path,
    bypass_git_gate,
    clock_values,
) -> None:
    with pytest.raises(MassiveDailyMarketDataRealE2EError):
        prepare(tmp_path, clock=SequenceClock(clock_values))


@pytest.mark.parametrize(
    ("clock_values", "expected_calls", "expected_durable"),
    (
        (
            (
                ASSET_OBSERVED_AT,
                BENCHMARK_OBSERVED_AT,
                datetime(2026, 8, 20, 18, 0),
            ),
            3,
            0,
        ),
        (
            (
                ASSET_OBSERVED_AT,
                BENCHMARK_OBSERVED_AT,
                INGESTION_COMPLETED_AT,
                datetime(
                    2026,
                    8,
                    20,
                    19,
                    0,
                    tzinfo=timezone(timedelta(hours=1)),
                ),
            ),
            4,
            2,
        ),
    ),
)
def test_orchestration_clock_requires_exact_builtin_utc_values(
    tmp_path,
    bypass_git_gate,
    clock_values,
    expected_calls,
    expected_durable,
) -> None:
    clock = SequenceClock(clock_values)

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        prepare(tmp_path, clock=clock)

    assert clock.calls == expected_calls
    assert len(caught.value.durable_artifacts) == expected_durable


def test_orchestration_clock_rejects_datetime_subclass_and_safe_wraps_errors(
    tmp_path,
    bypass_git_gate,
) -> None:
    class DateTimeSubclass(datetime):
        pass

    subclass_value = DateTimeSubclass(2026, 8, 20, 20, 0, tzinfo=UTC)
    clock = SequenceClock(
        (
            ASSET_OBSERVED_AT,
            BENCHMARK_OBSERVED_AT,
            INGESTION_COMPLETED_AT,
            AVAILABLE_AT,
            subclass_value,
        )
    )

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        prepare(tmp_path, clock=clock)

    assert clock.calls == 5
    assert len(caught.value.durable_artifacts) == 2
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None

    class UnsafeClock:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self):
            self.calls += 1
            if self.calls == 3:
                raise RuntimeError(f"unsafe {SECRET}")
            return (ASSET_OBSERVED_AT, BENCHMARK_OBSERVED_AT)[self.calls - 1]

    other_root = tmp_path / "other"
    other_root.mkdir()
    unsafe_clock = UnsafeClock()
    with pytest.raises(MassiveDailyMarketDataRealE2EError) as unsafe_caught:
        prepare(other_root, clock=unsafe_clock)  # type: ignore[arg-type]
    assert unsafe_clock.calls == 3
    assert SECRET not in str(unsafe_caught.value)
    assert unsafe_caught.value.__cause__ is None
    assert unsafe_caught.value.__context__ is None


def test_equal_utc_clock_values_are_valid_chronology(
    tmp_path,
    bypass_git_gate,
) -> None:
    instant = datetime(2026, 8, 20, 16, 0, tzinfo=UTC)
    clock = SequenceClock((instant, instant, instant, instant, instant))

    prepared = prepare(tmp_path, clock=clock)

    assert prepared.ingestion_completed_at == instant
    assert prepared.available_at == instant
    assert prepared.created_at == instant


def test_readback_captures_drive_second_adaptation(
    tmp_path,
    bypass_git_gate,
    monkeypatch,
) -> None:
    seen: list[object] = []
    loaded: list[object] = []
    original = e2e_module.adapt_massive_daily_market_data_source_capture
    original_load = e2e_module.load_local_daily_market_data_source_capture

    def adapt(*, source_capture, context):
        seen.append(source_capture)
        return original(source_capture=source_capture, context=context)

    def load(**kwargs):
        capture = original_load(**kwargs)
        loaded.append(capture)
        return capture

    monkeypatch.setattr(
        e2e_module,
        "adapt_massive_daily_market_data_source_capture",
        adapt,
    )
    monkeypatch.setattr(e2e_module, "load_local_daily_market_data_source_capture", load)

    prepared = prepare(tmp_path)

    assert len(seen) == 4
    assert len(loaded) == 2
    assert seen[2] is loaded[0] is prepared.asset_source_capture
    assert seen[3] is loaded[1] is prepared.benchmark_source_capture
    assert seen[0] is not loaded[0]
    assert seen[1] is not loaded[1]


def test_prepared_contains_no_credential_transport_or_snapshot_publication(
    tmp_path,
    bypass_git_gate,
) -> None:
    prepared = prepare(tmp_path)
    field_names = set(prepared.__dataclass_fields__)

    assert "credential" not in field_names
    assert "transport" not in field_names
    assert "asset_snapshot_publication" not in field_names
    assert "benchmark_snapshot_publication" not in field_names
    assert SECRET not in repr(prepared)


def test_prepared_runtime_subclass_is_rejected(
    tmp_path,
    bypass_git_gate,
) -> None:
    prepared = prepare(tmp_path)

    class PreparedSubclass(type(prepared)):
        pass

    hostile = object.__new__(PreparedSubclass)
    with pytest.raises(MassiveDailyMarketDataRealE2EError):
        validate_massive_daily_market_data_real_e2e_prepared(hostile)


def test_prepared_reloads_canonical_source_publications_and_rejects_tampering(
    tmp_path,
    bypass_git_gate,
) -> None:
    prepared = prepare(tmp_path)
    tampered_publication = replace(
        prepared.asset_source_publication,
        path=tmp_path,
    )
    tampered_path = replace(
        prepared,
        asset_source_publication=tampered_publication,
    )
    swapped_capture = replace(
        prepared,
        asset_source_capture=prepared.benchmark_source_capture,
    )
    swapped_snapshot_plan = replace(
        prepared,
        asset_snapshot_plan=prepared.benchmark_snapshot_plan,
    )

    class HostileString(str):
        def __eq__(self, _other) -> bool:
            return True

    class HostileBytes(bytes):
        def __eq__(self, _other) -> bool:
            return True

    hostile_capture = replace(
        prepared.asset_source_capture,
        capture_id=HostileString(prepared.asset_source_capture.capture_id),
    )
    hostile_file = replace(
        prepared.asset_snapshot_plan.files[0],
        content=HostileBytes(prepared.asset_snapshot_plan.files[0].content),
    )
    hostile_plan = replace(
        prepared.asset_snapshot_plan,
        files=(hostile_file, *prepared.asset_snapshot_plan.files[1:]),
    )

    with pytest.raises(MassiveDailyMarketDataRealE2EError):
        validate_massive_daily_market_data_real_e2e_prepared(tampered_path)
    with pytest.raises(MassiveDailyMarketDataRealE2EError):
        validate_massive_daily_market_data_real_e2e_prepared(swapped_capture)
    with pytest.raises(MassiveDailyMarketDataRealE2EError):
        validate_massive_daily_market_data_real_e2e_prepared(swapped_snapshot_plan)
    with pytest.raises(MassiveDailyMarketDataRealE2EError):
        validate_massive_daily_market_data_real_e2e_prepared(
            replace(prepared, asset_source_capture=hostile_capture)
        )
    with pytest.raises(MassiveDailyMarketDataRealE2EError):
        validate_massive_daily_market_data_real_e2e_prepared(
            replace(prepared, asset_snapshot_plan=hostile_plan)
        )


def test_prepared_validation_is_read_only_and_canonicalizes_ignored_nested_fields(
    tmp_path,
    bypass_git_gate,
    monkeypatch,
) -> None:
    prepared = prepare(tmp_path)
    rejected_profile = prepared.preflight.research_profile.model_copy(
        update={
            "session_source_version": (
                "exchange-calendars-4.13.2+us-equity-regular-session-dates-v1"
            )
        }
    )
    altered = replace(
        prepared,
        preflight=replace(prepared.preflight, research_profile=rejected_profile),
    )
    monkeypatch.setattr(
        e2e_module,
        "acquire_and_plan_massive_daily_market_data_source_capture_pair",
        lambda **_kwargs: pytest.fail("prepared validation acquired"),
    )
    monkeypatch.setattr(
        e2e_module,
        "publish_local_daily_market_data_source_capture",
        lambda **_kwargs: pytest.fail("prepared validation published"),
    )

    canonical = validate_massive_daily_market_data_real_e2e_prepared(altered)

    assert canonical.preflight.research_profile.session_source_version == (
        "exchange_calendars-4.13.2+us-equity-regular-session-dates-v1"
    )
    assert canonical.preflight.research_profile_hash == (
        MASSIVE_REAL_E2E_RESEARCH_PROFILE_HASH
    )


def test_prepared_timestamp_tampering_breaks_snapshot_linkage(
    tmp_path,
    bypass_git_gate,
) -> None:
    prepared = prepare(tmp_path)
    tampered = replace(
        prepared,
        created_at=prepared.created_at + timedelta(seconds=1),
    )

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        validate_massive_daily_market_data_real_e2e_prepared(tampered)

    assert len(caught.value.durable_artifacts) == 2


def test_prepared_revalidation_reports_only_canonically_reloaded_sources(
    tmp_path,
    bypass_git_gate,
    monkeypatch,
) -> None:
    prepared = prepare(tmp_path)
    original = e2e_module.load_local_daily_market_data_source_capture
    calls = 0

    def load(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError(f"unsafe {SECRET}")
        return original(**kwargs)

    monkeypatch.setattr(e2e_module, "load_local_daily_market_data_source_capture", load)

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        validate_massive_daily_market_data_real_e2e_prepared(prepared)

    assert calls == 2
    assert len(caught.value.durable_artifacts) == 1
    assert "QQQ source capture" in caught.value.durable_artifacts[0]
    assert SECRET not in str(caught.value)


def test_research_sdk_core_has_no_backtest_import() -> None:
    source = Path(e2e_module.__file__).read_text()
    assert "backtest_engine" not in source
    assert "prepare_daily_market_data_snapshot_pair_v2" not in source
