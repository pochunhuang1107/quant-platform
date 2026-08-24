from __future__ import annotations

import importlib.util
import io
import json
import os
import socket
import ssl
import subprocess
import sys
import textwrap
import traceback
from dataclasses import replace
from pathlib import Path

import pytest

import research_sdk.daily_market_data_acquisition.massive as acquisition_module
import research_sdk.daily_market_data_acquisition.massive_real_e2e as e2e_module
from research_sdk.daily_market_data_acquisition import (
    MASSIVE_AWS_SECRETS_MANAGER_SOURCE_KIND,
    MASSIVE_REAL_E2E_ACQUISITION_CONFIRMATION,
    MASSIVE_REAL_E2E_ENTITLEMENT_CONFIRMATION,
    MassiveApiCredential,
    MassiveAwsSecretsManagerCredentialSource,
    MassiveDailyMarketDataHttpResponse,
    MassiveDailyMarketDataRealE2EConfig,
    MassiveDailyMarketDataRealE2EError,
    build_massive_daily_market_data_real_e2e_preflight,
)
from test_massive_daily_market_data_real_e2e import (
    AWS_REGION,
    AWS_SECRET_ID,
    AWS_SECRET_JSON_KEY,
    AWS_SECRET_VERSION_STAGE,
    BATCH_ID,
    CREATED_BY,
    EXPECTED_COMMIT,
    LICENSE_NOTES,
    REPOSITORY_ROOT,
    SECRET,
    FakeTransport,
    SequenceClock,
    prepare,
    valid_response,
)

SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "s3c3c6_massive_real_e2e.py"


@pytest.fixture(autouse=True)
def forbid_real_network(monkeypatch) -> None:
    def forbidden_network(*_args, **_kwargs):
        pytest.fail("S3c3c6a CLI tests must never use DNS, sockets, or TLS")

    class ForbiddenHttpsConnection:
        def __init__(self, *args, **kwargs) -> None:
            pytest.fail("S3c3c6a CLI tests must never construct HTTPSConnection")

    monkeypatch.setattr(
        acquisition_module,
        "HTTPSConnection",
        ForbiddenHttpsConnection,
    )
    monkeypatch.setattr(socket, "getaddrinfo", forbidden_network)
    monkeypatch.setattr(socket, "create_connection", forbidden_network)
    monkeypatch.setattr(ssl, "create_default_context", forbidden_network)
    monkeypatch.setattr(e2e_module, "_validate_git_gate", lambda **_kwargs: None)


@pytest.fixture
def cli_module():
    name = "test_s3c3c6_massive_real_e2e_script"
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    try:
        yield module
    finally:
        sys.modules.pop(name, None)


def arguments(mode: str, root: Path, *, fingerprint: str | None = None):
    values = [
        mode,
        "--expected-commit",
        EXPECTED_COMMIT,
        "--batch-id",
        BATCH_ID,
        "--data-root",
        str(root),
        "--created-by",
        CREATED_BY,
        "--license-notes",
        LICENSE_NOTES,
        "--credential-source",
        MASSIVE_AWS_SECRETS_MANAGER_SOURCE_KIND,
        "--aws-region",
        AWS_REGION,
        "--aws-secret-id",
        AWS_SECRET_ID,
        "--aws-secret-json-key",
        AWS_SECRET_JSON_KEY,
        "--aws-secret-version-stage",
        AWS_SECRET_VERSION_STAGE,
    ]
    if fingerprint is not None:
        values.extend(("--approval-fingerprint", fingerprint))
    return values


def credential_source() -> MassiveAwsSecretsManagerCredentialSource:
    return MassiveAwsSecretsManagerCredentialSource(
        source_kind=MASSIVE_AWS_SECRETS_MANAGER_SOURCE_KIND,
        region=AWS_REGION,
        secret_id=AWS_SECRET_ID,
        json_key=AWS_SECRET_JSON_KEY,
        version_stage=AWS_SECRET_VERSION_STAGE,
    )


def authority(root: Path):
    return build_massive_daily_market_data_real_e2e_preflight(
        config=MassiveDailyMarketDataRealE2EConfig(
            expected_repository_commit=EXPECTED_COMMIT,
            acquisition_batch_id=BATCH_ID,
            data_root=root,
            created_by=CREATED_BY,
            license_notes=LICENSE_NOTES,
            credential_source=credential_source(),
        ),
        repository_root=REPOSITORY_ROOT,
    )


def test_preflight_command_never_prompts_or_uses_transport(
    tmp_path,
    cli_module,
) -> None:
    output = io.StringIO()

    result = cli_module.run(
        arguments("preflight", tmp_path),
        input_fn=lambda _prompt: pytest.fail("preflight requested confirmation"),
        credential_loader=lambda _source: pytest.fail("preflight requested credential"),
        transport=FakeTransport(fail_at=1),
        stdout=output,
        stderr=io.StringIO(),
    )

    assert result == 0
    assert "CREDENTIAL STATUS: NOT REQUESTED" in output.getvalue()
    assert "CREDENTIAL SOURCE: aws-secrets-manager" in output.getvalue()
    assert "AWS REGION: us-west-2" in output.getvalue()
    assert "AWS SECRET ID: massive/api-key" in output.getvalue()
    assert "AWS SECRET JSON KEY: api_key" in output.getvalue()
    assert "AWS SECRET VERSION STAGE: AWSCURRENT" in output.getvalue()
    assert "AWS SECRETS MANAGER STATUS: NOT CONTACTED" in output.getvalue()
    assert "NO NETWORK REQUEST HAS OCCURRED" in output.getvalue()
    assert tuple(tmp_path.iterdir()) == ()


def test_wrong_fingerprint_fails_before_confirmation_or_prompt(
    tmp_path,
    cli_module,
) -> None:
    prompted = False

    def prompt(_text):
        nonlocal prompted
        prompted = True
        return "unexpected"

    error = io.StringIO()
    result = cli_module.run(
        arguments("execute", tmp_path, fingerprint=f"sha256:{'0' * 64}"),
        input_fn=prompt,
        credential_loader=prompt,
        transport=FakeTransport(),
        stdout=io.StringIO(),
        stderr=error,
    )

    assert result == 1
    assert not prompted
    assert "fingerprint" in error.getvalue()
    assert tuple(tmp_path.iterdir()) == ()


def test_failed_initial_recheck_prevents_credential_retrieval(
    tmp_path,
    cli_module,
    monkeypatch,
) -> None:
    reviewed = authority(tmp_path)
    original_build = cli_module.build_massive_daily_market_data_real_e2e_preflight
    calls = 0
    loader_calls = 0

    def build(**kwargs):
        nonlocal calls
        calls += 1
        value = original_build(**kwargs)
        if calls == 2:
            return replace(value, approval_fingerprint=f"sha256:{'0' * 64}")
        return value

    def loader(_source):
        nonlocal loader_calls
        loader_calls += 1
        return MassiveApiCredential(SECRET)

    monkeypatch.setattr(
        cli_module,
        "build_massive_daily_market_data_real_e2e_preflight",
        build,
    )
    result = cli_module.run(
        arguments(
            "execute",
            tmp_path,
            fingerprint=reviewed.approval_fingerprint,
        ),
        input_fn=lambda _prompt: pytest.fail("initial recheck requested confirmation"),
        credential_loader=loader,
        transport=FakeTransport(),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert result == 1
    assert loader_calls == 0
    assert tuple(tmp_path.iterdir()) == ()


def test_safe_http_401_bar_reason_reaches_cli_without_secret_or_body(
    tmp_path,
    cli_module,
) -> None:
    reviewed = authority(tmp_path)
    answers = iter(
        (
            MASSIVE_REAL_E2E_ENTITLEMENT_CONFIRMATION,
            MASSIVE_REAL_E2E_ACQUISITION_CONFIRMATION,
        )
    )
    raw_body = f"provider body Authorization: Bearer {SECRET}".encode()

    def unauthorized_bar(request, call_number):
        if call_number == 1:
            return MassiveDailyMarketDataHttpResponse(
                status_code=401,
                headers=(("Content-Type", "text/plain"),),
                body=raw_body,
            )
        return valid_response(request, call_number)

    transport = FakeTransport(response_factory=unauthorized_bar)
    output = io.StringIO()
    error = io.StringIO()

    result = cli_module.run(
        arguments(
            "execute",
            tmp_path,
            fingerprint=reviewed.approval_fingerprint,
        ),
        input_fn=lambda _prompt: next(answers),
        credential_loader=lambda _source: MassiveApiCredential(SECRET),
        transport=transport,
        clock=SequenceClock(),
        stdout=output,
        stderr=error,
    )

    assert result == 1
    assert len(transport.calls) == 1
    assert "reason: Massive returned HTTP 401 for BAR_RESPONSE" in error.getvalue()
    assert raw_body.decode() not in error.getvalue()
    assert "Authorization" not in error.getvalue()
    assert SECRET not in error.getvalue()
    assert SECRET not in output.getvalue()
    assert tuple(tmp_path.iterdir()) == ()


@pytest.mark.parametrize(
    "answers",
    (
        ("wrong",),
        (MASSIVE_REAL_E2E_ENTITLEMENT_CONFIRMATION, "wrong"),
    ),
)
def test_confirmation_mismatch_fails_before_credential_and_network(
    tmp_path,
    cli_module,
    answers,
) -> None:
    reviewed = authority(tmp_path)
    answer_iterator = iter(answers)
    credential_loaded = False

    def credential(_source):
        nonlocal credential_loaded
        credential_loaded = True
        return MassiveApiCredential(SECRET)

    result = cli_module.run(
        arguments(
            "execute",
            tmp_path,
            fingerprint=reviewed.approval_fingerprint,
        ),
        input_fn=lambda _prompt: next(answer_iterator),
        credential_loader=credential,
        transport=FakeTransport(),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert result == 1
    assert not credential_loaded
    assert tuple(tmp_path.iterdir()) == ()


def test_credential_retrieval_occurs_after_both_confirmations_and_final_recheck(
    tmp_path,
    cli_module,
    monkeypatch,
) -> None:
    reviewed = authority(tmp_path)
    events: list[str] = []
    answers = iter(
        (
            MASSIVE_REAL_E2E_ENTITLEMENT_CONFIRMATION,
            MASSIVE_REAL_E2E_ACQUISITION_CONFIRMATION,
        )
    )

    def input_fn(_prompt):
        events.append("confirmation")
        return next(answers)

    original_build = cli_module.build_massive_daily_market_data_real_e2e_preflight

    def build(**kwargs):
        events.append("recheck")
        return original_build(**kwargs)

    def credential(_source):
        events.append("credential")
        return MassiveApiCredential(SECRET)

    def stop_after_prompt(**_kwargs):
        events.append("prepare")
        raise MassiveDailyMarketDataRealE2EError("synthetic stop")

    monkeypatch.setattr(
        cli_module,
        "prepare_massive_daily_market_data_real_e2e",
        stop_after_prompt,
    )
    monkeypatch.setattr(
        cli_module,
        "build_massive_daily_market_data_real_e2e_preflight",
        build,
    )
    result = cli_module.run(
        arguments(
            "execute",
            tmp_path,
            fingerprint=reviewed.approval_fingerprint,
        ),
        input_fn=input_fn,
        credential_loader=credential,
        transport=FakeTransport(),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert result == 1
    assert events == [
        "recheck",
        "recheck",
        "confirmation",
        "confirmation",
        "recheck",
        "credential",
        "prepare",
    ]


def test_final_pre_secret_recheck_failure_prevents_retrieval_and_network(
    tmp_path,
    cli_module,
) -> None:
    reviewed = authority(tmp_path)
    transport = FakeTransport()
    answers = iter(
        (
            MASSIVE_REAL_E2E_ENTITLEMENT_CONFIRMATION,
            MASSIVE_REAL_E2E_ACQUISITION_CONFIRMATION,
        )
    )

    loader_calls = 0

    def input_fn(_prompt):
        answer = next(answers)
        if answer == MASSIVE_REAL_E2E_ACQUISITION_CONFIRMATION:
            managed = tmp_path / "daily-market-data-source-captures"
            target = tmp_path / "hostile-managed-target"
            target.mkdir()
            managed.symlink_to(target, target_is_directory=True)
        return answer

    def loader(_source):
        nonlocal loader_calls
        loader_calls += 1
        return MassiveApiCredential(SECRET)

    result = cli_module.run(
        arguments(
            "execute",
            tmp_path,
            fingerprint=reviewed.approval_fingerprint,
        ),
        input_fn=input_fn,
        credential_loader=loader,
        transport=transport,
        clock=SequenceClock(),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert result == 1
    assert loader_calls == 0
    assert transport.calls == []


def test_aws_cli_command_authority_is_exact_and_bounded(cli_module) -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps({AWS_SECRET_JSON_KEY: SECRET}) + "\n",
            stderr=f"ignored hostile stderr {SECRET}",
        )

    credential = cli_module._load_massive_credential_from_aws_secrets_manager(
        credential_source(),
        command_runner=runner,
    )

    assert type(credential) is MassiveApiCredential
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == (
        "aws",
        "secretsmanager",
        "get-secret-value",
        "--region",
        "us-west-2",
        "--secret-id",
        "massive/api-key",
        "--version-stage",
        "AWSCURRENT",
        "--query",
        "SecretString",
        "--output",
        "text",
        "--no-cli-pager",
        "--cli-connect-timeout",
        "5",
        "--cli-read-timeout",
        "15",
    )
    assert kwargs["check"] is False
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "strict"
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 25
    environment = kwargs["env"]
    assert type(environment) is dict
    assert environment["AWS_MAX_ATTEMPTS"] == "1"
    assert environment["AWS_RETRY_MODE"] == "standard"
    assert environment["AWS_PAGER"] == ""
    assert environment["AWS_CLI_AUTO_PROMPT"] == "off"
    assert environment["AWS_IGNORE_CONFIGURED_ENDPOINT_URLS"] == "true"
    assert SECRET not in argv
    assert "api.massive.com" not in argv
    assert repr(credential) == "MassiveApiCredential(<redacted>)"


def test_hostile_aws_environment_cannot_override_endpoint_retry_or_interaction(
    cli_module,
    monkeypatch,
) -> None:
    hostile_endpoint = "https://hostile.invalid"
    monkeypatch.setenv("AWS_ENDPOINT_URL", hostile_endpoint)
    monkeypatch.setenv("AWS_ENDPOINT_URL_SECRETS_MANAGER", hostile_endpoint)
    monkeypatch.setenv("AWS_MAX_ATTEMPTS", "99")
    monkeypatch.setenv("AWS_RETRY_MODE", "adaptive")
    monkeypatch.setenv("AWS_PAGER", "hostile-pager")
    monkeypatch.setenv("AWS_CLI_AUTO_PROMPT", "on")
    monkeypatch.setenv("AWS_IGNORE_CONFIGURED_ENDPOINT_URLS", "false")
    monkeypatch.setenv("AWS_CONFIG_FILE", "/synthetic/hostile-aws-config")
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps({AWS_SECRET_JSON_KEY: SECRET}) + "\n",
            stderr="",
        )

    cli_module._load_massive_credential_from_aws_secrets_manager(
        credential_source(),
        command_runner=runner,
    )

    assert len(calls) == 1
    argv, kwargs = calls[0]
    environment = kwargs["env"]
    assert type(environment) is dict
    assert "--endpoint-url" not in argv
    assert "AWS_ENDPOINT_URL" not in environment
    assert "AWS_ENDPOINT_URL_SECRETS_MANAGER" not in environment
    assert environment["AWS_IGNORE_CONFIGURED_ENDPOINT_URLS"] == "true"
    assert environment["AWS_MAX_ATTEMPTS"] == "1"
    assert environment["AWS_RETRY_MODE"] == "standard"
    assert environment["AWS_PAGER"] == ""
    assert environment["AWS_CLI_AUTO_PROMPT"] == "off"
    assert environment["AWS_CONFIG_FILE"] == "/synthetic/hostile-aws-config"
    assert hostile_endpoint not in argv


@pytest.mark.parametrize(
    ("case", "expected_stage"),
    (
        ("missing-executable", "AWS Secrets Manager executable"),
        ("timeout", "AWS Secrets Manager retrieval"),
        ("unicode-output", "AWS Secrets Manager retrieval"),
        ("nonzero", "AWS Secrets Manager retrieval"),
        ("invalid-output-type", "AWS Secrets Manager retrieval"),
        ("invalid-json", "AWS Secrets Manager SecretString JSON"),
        ("non-object", "AWS Secrets Manager SecretString JSON"),
        ("missing-field", "AWS Secrets Manager credential field"),
        ("non-string-field", "AWS Secrets Manager credential field"),
        ("invalid-credential", "runtime credential validation"),
        ("control-invalid-credential", "runtime credential validation"),
    ),
)
def test_aws_retrieval_failures_are_fixed_and_exception_safe(
    cli_module,
    case,
    expected_stage,
) -> None:
    def runner(argv, **_kwargs):
        if case == "missing-executable":
            raise FileNotFoundError(f"missing executable {SECRET}")
        if case == "timeout":
            raise subprocess.TimeoutExpired(argv, 25, stderr=f"timeout {SECRET}")
        if case == "unicode-output":
            raise UnicodeError(f"invalid UTF-8 output {SECRET}")
        if case == "nonzero":
            return subprocess.CompletedProcess(
                argv,
                255,
                stdout=f"hostile stdout {SECRET}",
                stderr=f"hostile stderr {SECRET}",
            )
        if case == "invalid-output-type":
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=f'{{"api_key":"{SECRET}"}}\n'.encode(),
                stderr=b"invalid UTF-8-like output",
            )
        payload: object
        if case == "invalid-json":
            stdout = f"not JSON {SECRET}\n"
        elif case == "non-object":
            stdout = json.dumps([SECRET]) + "\n"
        elif case == "missing-field":
            stdout = json.dumps({"other": SECRET}) + "\n"
        elif case == "non-string-field":
            stdout = json.dumps({AWS_SECRET_JSON_KEY: [SECRET]}) + "\n"
        elif case == "invalid-credential":
            payload = {AWS_SECRET_JSON_KEY: f" {SECRET}"}
            stdout = json.dumps(payload) + "\n"
        else:
            payload = {AWS_SECRET_JSON_KEY: f"{SECRET}\ncontrol"}
            stdout = json.dumps(payload) + "\n"
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=stdout,
            stderr=f"hostile stderr {SECRET}",
        )

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        cli_module._load_massive_credential_from_aws_secrets_manager(
            credential_source(),
            command_runner=runner,
        )

    rendered_traceback = "".join(traceback.format_exception(caught.value))
    assert caught.value.stage == expected_stage
    assert SECRET not in str(caught.value)
    assert SECRET not in repr(caught.value)
    assert SECRET not in rendered_traceback
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    "stdout",
    (
        '{"api_key":"synthetic"}',
        '{"api_key":"synthetic"}\r\n',
        '{"api_key":"synthetic"}\nextra\n',
        '{"api_key":"first","api_key":"second"}\n',
        '{"api_key":"synthetic","value":NaN}\n',
    ),
)
def test_aws_stdout_requires_one_strict_json_text_record(
    cli_module,
    stdout,
) -> None:
    def runner(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        cli_module._load_massive_credential_from_aws_secrets_manager(
            credential_source(),
            command_runner=runner,
        )

    assert caught.value.stage in {
        "AWS Secrets Manager retrieval",
        "AWS Secrets Manager SecretString JSON",
    }
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_injected_loader_cannot_forge_trusted_aws_diagnostics(cli_module) -> None:
    def forged(_source):
        raise MassiveDailyMarketDataRealE2EError(
            f"AWS Secrets Manager executable {SECRET}"
        )

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        cli_module._retrieve_credential(credential_source(), forged)

    assert caught.value.stage == "AWS Secrets Manager retrieval"
    assert SECRET not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_only_internal_loader_can_preserve_fixed_aws_stage(
    cli_module,
    monkeypatch,
) -> None:
    def internal(_source):
        raise MassiveDailyMarketDataRealE2EError("AWS Secrets Manager executable")

    monkeypatch.setattr(
        cli_module,
        "_load_massive_credential_from_aws_secrets_manager",
        internal,
    )

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        cli_module._retrieve_credential(credential_source(), None)

    assert caught.value.stage == "AWS Secrets Manager executable"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_successful_execute_loads_once_before_first_massive_request(
    tmp_path,
    cli_module,
    monkeypatch,
) -> None:
    reviewed = authority(tmp_path)
    answers = iter(
        (
            MASSIVE_REAL_E2E_ENTITLEMENT_CONFIRMATION,
            MASSIVE_REAL_E2E_ACQUISITION_CONFIRMATION,
        )
    )
    events: list[str] = []
    loader_calls = 0

    def loader(source):
        nonlocal loader_calls
        loader_calls += 1
        events.append("credential-retrieval")
        assert source == credential_source()
        assert tuple(tmp_path.iterdir()) == ()
        return MassiveApiCredential(SECRET)

    def response(request, call_number):
        events.append(f"massive-request-{call_number}")
        return valid_response(request, call_number)

    transport = FakeTransport(response_factory=response)
    monkeypatch.chdir(REPOSITORY_ROOT)

    result = cli_module.run(
        arguments(
            "execute",
            tmp_path,
            fingerprint=reviewed.approval_fingerprint,
        ),
        input_fn=lambda _prompt: next(answers),
        credential_loader=loader,
        transport=transport,
        clock=SequenceClock(),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert result == 0
    assert loader_calls == 1
    assert len(transport.calls) == 6
    assert events[0] == "credential-retrieval"
    assert events[1:] == [f"massive-request-{index}" for index in range(1, 7)]


def test_hostile_injected_aws_failure_reaches_no_operator_stream_or_data_root(
    tmp_path,
    cli_module,
) -> None:
    reviewed = authority(tmp_path)
    answers = iter(
        (
            MASSIVE_REAL_E2E_ENTITLEMENT_CONFIRMATION,
            MASSIVE_REAL_E2E_ACQUISITION_CONFIRMATION,
        )
    )
    output = io.StringIO()
    error = io.StringIO()

    def loader(_source):
        raise ValueError(f"hostile AWS stdout/stderr Authorization {SECRET}")

    result = cli_module.run(
        arguments(
            "execute",
            tmp_path,
            fingerprint=reviewed.approval_fingerprint,
        ),
        input_fn=lambda _prompt: next(answers),
        credential_loader=loader,
        transport=FakeTransport(),
        stdout=output,
        stderr=error,
    )

    assert result == 1
    assert "AWS Secrets Manager retrieval" in error.getvalue()
    assert SECRET not in output.getvalue()
    assert SECRET not in error.getvalue()
    assert "hostile AWS" not in error.getvalue()
    assert tuple(tmp_path.iterdir()) == ()


def test_production_cli_has_no_secret_prompt_or_secret_bearing_option(
    cli_module,
) -> None:
    source = SCRIPT_PATH.read_text()
    parser_help = cli_module.build_parser().format_help()

    assert "getpass" not in source
    assert "Massive API key:" not in source
    assert "--api-key" not in source
    assert "--api-key-file" not in source
    assert "--api-key-env" not in source
    assert "--secret-value" not in source
    assert "--credential-source" in source
    assert "Massive API key:" not in parser_help


def test_prepublication_s3d2a_occurs_before_snapshot_publication(
    tmp_path,
    cli_module,
    monkeypatch,
) -> None:
    prepared = prepare(tmp_path)
    original_pair = cli_module.prepare_daily_market_data_snapshot_pair_v2
    calls = 0

    def pair(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            assert not (tmp_path / "daily-market-data").exists()
        else:
            assert (tmp_path / "daily-market-data").is_dir()
        return original_pair(**kwargs)

    monkeypatch.setattr(
        cli_module,
        "prepare_daily_market_data_snapshot_pair_v2",
        pair,
    )

    success = cli_module.complete_massive_daily_market_data_real_e2e(prepared)

    assert calls == 2
    assert success.asset_snapshot_publication.path.is_dir()
    assert success.benchmark_snapshot_publication.path.is_dir()
    assert len(success.pair.run_session_dates) == 252


def test_hostile_pair_result_cannot_spoof_prepublication_success(
    tmp_path,
    cli_module,
    monkeypatch,
) -> None:
    prepared = prepare(tmp_path)

    class HostilePair:
        def __eq__(self, _other) -> bool:
            return True

    monkeypatch.setattr(
        cli_module,
        "prepare_daily_market_data_snapshot_pair_v2",
        lambda **_kwargs: HostilePair(),
    )
    monkeypatch.setattr(
        cli_module,
        "publish_local_daily_market_data_snapshot_v2",
        lambda **_kwargs: pytest.fail("hostile pair reached snapshot publication"),
    )

    with pytest.raises(MassiveDailyMarketDataRealE2EError):
        cli_module.complete_massive_daily_market_data_real_e2e(prepared)

    assert not (tmp_path / "daily-market-data").exists()


def test_prepublication_s3d2a_failure_publishes_zero_snapshots(
    tmp_path,
    cli_module,
    monkeypatch,
) -> None:
    prepared = prepare(tmp_path)
    monkeypatch.setattr(
        cli_module,
        "prepare_daily_market_data_snapshot_pair_v2",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError(f"unsafe {SECRET}")),
    )

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        cli_module.complete_massive_daily_market_data_real_e2e(prepared)

    assert not (tmp_path / "daily-market-data").exists()
    assert SECRET not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_final_s3d2a_uses_exact_readback_mappings(
    tmp_path,
    cli_module,
    monkeypatch,
) -> None:
    prepared = prepare(tmp_path)
    original_pair = cli_module.prepare_daily_market_data_snapshot_pair_v2
    calls: list[dict[str, object]] = []

    def pair(**kwargs):
        calls.append(kwargs)
        return original_pair(**kwargs)

    monkeypatch.setattr(
        cli_module,
        "prepare_daily_market_data_snapshot_pair_v2",
        pair,
    )
    success = cli_module.complete_massive_daily_market_data_real_e2e(prepared)

    assert len(calls) == 2
    assert calls[0] == {
        "asset_files": prepared.asset_snapshot_plan.as_file_map(),
        "benchmark_files": prepared.benchmark_snapshot_plan.as_file_map(),
        "research_profile": prepared.preflight.research_profile,
        "start_date": e2e_module.MASSIVE_REAL_E2E_START_DATE,
        "end_date": e2e_module.MASSIVE_REAL_E2E_END_DATE,
    }
    assert calls[1]["asset_files"] is success.asset_snapshot_readback.files
    assert calls[1]["benchmark_files"] is success.benchmark_snapshot_readback.files
    assert calls[1]["research_profile"] is success.prepared.preflight.research_profile
    assert calls[1]["start_date"] == e2e_module.MASSIVE_REAL_E2E_START_DATE
    assert calls[1]["end_date"] == e2e_module.MASSIVE_REAL_E2E_END_DATE


@pytest.mark.parametrize("fail_at", (1, 2))
def test_snapshot_publication_failure_reports_only_prior_durable_snapshot(
    tmp_path,
    cli_module,
    monkeypatch,
    fail_at,
) -> None:
    prepared = prepare(tmp_path)
    original = cli_module.publish_local_daily_market_data_snapshot_v2
    calls = 0

    def publish(**kwargs):
        nonlocal calls
        calls += 1
        if calls == fail_at:
            raise OSError(f"unsafe {SECRET}")
        return original(**kwargs)

    monkeypatch.setattr(
        cli_module,
        "publish_local_daily_market_data_snapshot_v2",
        publish,
    )

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        cli_module.complete_massive_daily_market_data_real_e2e(prepared)

    assert len(caught.value.durable_artifacts) == 2 + fail_at - 1
    if fail_at == 1:
        assert not (tmp_path / "daily-market-data").exists()
    else:
        snapshots = tuple((tmp_path / "daily-market-data").iterdir())
        assert len(snapshots) == 2  # one immutable snapshot plus .staging
        assert any("QQQ snapshot" in item for item in caught.value.durable_artifacts)
    assert SECRET not in str(caught.value)


@pytest.mark.parametrize("fail_at", (1, 2))
def test_snapshot_readback_failure_reports_only_durable_snapshots(
    tmp_path,
    cli_module,
    monkeypatch,
    fail_at,
) -> None:
    prepared = prepare(tmp_path)
    original = cli_module.load_local_daily_market_data_snapshot_v2
    calls = 0

    def load(**kwargs):
        nonlocal calls
        calls += 1
        if calls == fail_at:
            raise OSError(f"unsafe {SECRET}")
        return original(**kwargs)

    monkeypatch.setattr(
        cli_module,
        "load_local_daily_market_data_snapshot_v2",
        load,
    )

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        cli_module.complete_massive_daily_market_data_real_e2e(prepared)

    assert len(caught.value.durable_artifacts) == 2 + fail_at
    assert SECRET not in str(caught.value)


def test_final_s3d2a_failure_retains_both_snapshots_and_reports_unaccepted_pair(
    tmp_path,
    cli_module,
    monkeypatch,
) -> None:
    prepared = prepare(tmp_path)
    original = cli_module.prepare_daily_market_data_snapshot_pair_v2
    calls = 0

    def pair(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("readback rejected")
        return original(**kwargs)

    monkeypatch.setattr(
        cli_module,
        "prepare_daily_market_data_snapshot_pair_v2",
        pair,
    )

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        cli_module.complete_massive_daily_market_data_real_e2e(prepared)

    snapshots = tuple((tmp_path / "daily-market-data").iterdir())
    assert len(snapshots) == 3  # two immutable snapshots plus .staging
    assert len(caught.value.durable_artifacts) == 4
    assert "final readback S3d2a" in str(caught.value)


def test_final_pair_authority_detects_exact_type_deterministic_divergence(
    tmp_path,
    cli_module,
    monkeypatch,
) -> None:
    prepared = prepare(tmp_path)
    original = cli_module.prepare_daily_market_data_snapshot_pair_v2
    calls = 0

    def pair(**kwargs):
        nonlocal calls
        calls += 1
        result = original(**kwargs)
        if calls == 2:
            return result.model_copy(update={"profile_hash": f"sha256:{'0' * 64}"})
        return result

    monkeypatch.setattr(
        cli_module,
        "prepare_daily_market_data_snapshot_pair_v2",
        pair,
    )

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        cli_module.complete_massive_daily_market_data_real_e2e(prepared)

    assert "deterministic equality" in str(caught.value)
    assert len(caught.value.durable_artifacts) == 4


def test_prepared_validation_failure_precedes_snapshot_publication(
    tmp_path,
    cli_module,
    monkeypatch,
) -> None:
    prepared = prepare(tmp_path)
    hostile = replace(
        prepared,
        asset_snapshot_plan=prepared.benchmark_snapshot_plan,
    )
    monkeypatch.setattr(
        cli_module,
        "publish_local_daily_market_data_snapshot_v2",
        lambda **_kwargs: pytest.fail("invalid Prepared reached publication"),
    )

    with pytest.raises(MassiveDailyMarketDataRealE2EError):
        cli_module.complete_massive_daily_market_data_real_e2e(hostile)

    assert not (tmp_path / "daily-market-data").exists()


def test_idempotent_reexecution_reports_existing_immutable_evidence(
    tmp_path,
    cli_module,
) -> None:
    first_prepared = prepare(tmp_path)
    first = cli_module.complete_massive_daily_market_data_real_e2e(first_prepared)
    second_prepared = prepare(tmp_path)
    second = cli_module.complete_massive_daily_market_data_real_e2e(second_prepared)

    assert first_prepared.asset_source_publication.status.value == "CREATED"
    assert first_prepared.benchmark_source_publication.status.value == "CREATED"
    assert second_prepared.asset_source_publication.status.value == "ALREADY_PRESENT"
    assert second_prepared.benchmark_source_publication.status.value == (
        "ALREADY_PRESENT"
    )
    assert first.asset_snapshot_publication.status.value == "CREATED"
    assert first.benchmark_snapshot_publication.status.value == "CREATED"
    assert second.asset_snapshot_publication.status.value == "ALREADY_PRESENT"
    assert second.benchmark_snapshot_publication.status.value == "ALREADY_PRESENT"


def test_full_fake_execute_command_and_safe_success_report(
    tmp_path,
    cli_module,
    monkeypatch,
) -> None:
    reviewed = authority(tmp_path)
    answers = iter(
        (
            MASSIVE_REAL_E2E_ENTITLEMENT_CONFIRMATION,
            MASSIVE_REAL_E2E_ACQUISITION_CONFIRMATION,
        )
    )
    output = io.StringIO()
    error = io.StringIO()
    monkeypatch.chdir(REPOSITORY_ROOT)

    result = cli_module.run(
        arguments(
            "execute",
            tmp_path,
            fingerprint=reviewed.approval_fingerprint,
        ),
        input_fn=lambda _prompt: next(answers),
        credential_loader=lambda _source: MassiveApiCredential(SECRET),
        transport=FakeTransport(),
        clock=SequenceClock(),
        stdout=output,
        stderr=error,
    )

    assert result == 0
    assert error.getvalue() == ""
    report = output.getvalue()
    assert "FINAL S3d2a: PASS" in report
    assert "sessions=252" in report
    assert "instrument-us-etf-qqq-xnas; symbol=QQQ; venue=XNAS" in report
    assert "instrument-us-etf-spy-arcx; symbol=SPY; venue=ARCX" in report
    assert "QQQ BARS: count=252" in report
    assert "SPY BARS: count=252" in report
    assert "QQQ KNOWN LIMITATIONS:" in report
    assert "SPY KNOWN LIMITATIONS:" in report
    assert "PAPER/LIVE TRADING NOT APPROVED" in report
    assert SECRET not in report
    for file in tmp_path.rglob("*"):
        if file.is_file():
            assert SECRET.encode() not in file.read_bytes()


def test_script_is_the_only_backtest_composition_boundary(cli_module) -> None:
    core_source = Path(e2e_module.__file__).read_text()
    script_source = SCRIPT_PATH.read_text()

    assert "backtest_engine" not in core_source
    assert "from backtest_engine.snapshot_pair import" in script_source
    assert script_source.index("prepublication_pair =") < script_source.index(
        "asset_publication = _stage_value("
    )
    assert script_source.index("del credential") < script_source.index(
        "success = complete_massive_daily_market_data_real_e2e(prepared)"
    )


def test_fresh_process_imports_are_guarded_against_network_and_effects(
    tmp_path,
) -> None:
    guard = tmp_path / "guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(
        textwrap.dedent(
            """
            import http.client
            import pathlib
            import socket
            import ssl
            import subprocess

            def blocked(*args, **kwargs):
                raise RuntimeError("blocked import-time effect")

            socket.getaddrinfo = blocked
            socket.gethostbyname = blocked
            socket.gethostbyname_ex = blocked
            socket.getnameinfo = blocked
            socket.create_connection = blocked
            socket.socket = blocked
            ssl.create_default_context = blocked
            http.client.HTTPSConnection = blocked
            subprocess.run = blocked
            pathlib.Path.mkdir = blocked
            pathlib.Path.touch = blocked
            pathlib.Path.write_bytes = blocked
            pathlib.Path.write_text = blocked
            """
        ),
        encoding="utf-8",
    )
    source_paths = (
        guard,
        REPOSITORY_ROOT / "packages" / "research-sdk" / "src",
        REPOSITORY_ROOT / "packages" / "backtest-engine" / "src",
        REPOSITORY_ROOT,
    )
    code = textwrap.dedent(
        f"""
        import importlib.util
        import sys
        import research_sdk.daily_market_data_acquisition
        import research_sdk.daily_market_data_acquisition.massive_real_e2e

        script_path = {str(SCRIPT_PATH)!r}
        spec = importlib.util.spec_from_file_location("guarded_cli", script_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["guarded_cli"] = module
        spec.loader.exec_module(module)
        print("IMPORTS_OK")
        """
    )

    completed = subprocess.run(
        (sys.executable, "-c", code),
        cwd=REPOSITORY_ROOT,
        env={
            "PYTHONPATH": os.pathsep.join(str(path) for path in source_paths),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "IMPORTS_OK\n"
