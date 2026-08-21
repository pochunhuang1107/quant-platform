from __future__ import annotations

import importlib.util
import io
import os
import socket
import ssl
import subprocess
import sys
import textwrap
import warnings
from dataclasses import replace
from pathlib import Path

import pytest

import research_sdk.daily_market_data_acquisition.massive as acquisition_module
import research_sdk.daily_market_data_acquisition.massive_real_e2e as e2e_module
from research_sdk.daily_market_data_acquisition import (
    MASSIVE_REAL_E2E_ACQUISITION_CONFIRMATION,
    MASSIVE_REAL_E2E_ENTITLEMENT_CONFIRMATION,
    MassiveDailyMarketDataHttpResponse,
    MassiveDailyMarketDataRealE2EConfig,
    MassiveDailyMarketDataRealE2EError,
    build_massive_daily_market_data_real_e2e_preflight,
)
from test_massive_daily_market_data_real_e2e import (
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
    ]
    if fingerprint is not None:
        values.extend(("--approval-fingerprint", fingerprint))
    return values


def authority(root: Path):
    return build_massive_daily_market_data_real_e2e_preflight(
        config=MassiveDailyMarketDataRealE2EConfig(
            expected_repository_commit=EXPECTED_COMMIT,
            acquisition_batch_id=BATCH_ID,
            data_root=root,
            created_by=CREATED_BY,
            license_notes=LICENSE_NOTES,
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
        credential_prompt=lambda _prompt: pytest.fail("preflight requested credential"),
        transport=FakeTransport(fail_at=1),
        stdout=output,
        stderr=io.StringIO(),
    )

    assert result == 0
    assert "CREDENTIAL STATUS: NOT REQUESTED" in output.getvalue()
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
        credential_prompt=prompt,
        transport=FakeTransport(),
        stdout=io.StringIO(),
        stderr=error,
    )

    assert result == 1
    assert not prompted
    assert "fingerprint" in error.getvalue()
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
        credential_prompt=lambda _prompt: SECRET,
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
    credential_prompted = False

    def credential(_prompt):
        nonlocal credential_prompted
        credential_prompted = True
        return SECRET

    result = cli_module.run(
        arguments(
            "execute",
            tmp_path,
            fingerprint=reviewed.approval_fingerprint,
        ),
        input_fn=lambda _prompt: next(answer_iterator),
        credential_prompt=credential,
        transport=FakeTransport(),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert result == 1
    assert not credential_prompted
    assert tuple(tmp_path.iterdir()) == ()


def test_credential_prompt_occurs_after_both_confirmations(
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

    def credential(_prompt):
        events.append("credential")
        return SECRET

    def stop_after_prompt(**_kwargs):
        events.append("prepare")
        raise MassiveDailyMarketDataRealE2EError("synthetic stop")

    monkeypatch.setattr(
        cli_module,
        "prepare_massive_daily_market_data_real_e2e",
        stop_after_prompt,
    )
    result = cli_module.run(
        arguments(
            "execute",
            tmp_path,
            fingerprint=reviewed.approval_fingerprint,
        ),
        input_fn=input_fn,
        credential_prompt=credential,
        transport=FakeTransport(),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert result == 1
    assert events == ["confirmation", "confirmation", "credential", "prepare"]


def test_getpass_warning_fails_safely(cli_module) -> None:
    def warning_prompt(_prompt):
        warnings.warn("would echo", cli_module.getpass.GetPassWarning)
        return SECRET

    with pytest.raises(MassiveDailyMarketDataRealE2EError):
        cli_module._prompt_credential(warning_prompt)


@pytest.mark.parametrize(
    "failure",
    (
        EOFError(f"unsafe {SECRET}"),
        KeyboardInterrupt(),
        ValueError(f"unsafe {SECRET}"),
    ),
)
def test_credential_prompt_failures_are_sanitized_without_context(
    cli_module,
    failure,
) -> None:
    def prompt(_prompt):
        raise failure

    with pytest.raises(MassiveDailyMarketDataRealE2EError) as caught:
        cli_module._prompt_credential(prompt)

    assert SECRET not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_default_prompt_requires_interactive_terminal(cli_module, monkeypatch) -> None:
    class NonInteractive(io.StringIO):
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr(cli_module.sys, "stdin", NonInteractive())
    monkeypatch.setattr(cli_module.sys, "stderr", NonInteractive())

    with pytest.raises(MassiveDailyMarketDataRealE2EError):
        cli_module._prompt_credential(None)


def test_final_root_recheck_after_credential_prevents_network(
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

    def prompt(_prompt):
        managed = tmp_path / "daily-market-data-source-captures"
        target = tmp_path / "hostile-managed-target"
        target.mkdir()
        managed.symlink_to(target, target_is_directory=True)
        return SECRET

    result = cli_module.run(
        arguments(
            "execute",
            tmp_path,
            fingerprint=reviewed.approval_fingerprint,
        ),
        input_fn=lambda _prompt: next(answers),
        credential_prompt=prompt,
        transport=transport,
        clock=SequenceClock(),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert result == 1
    assert transport.calls == []


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
        credential_prompt=lambda _prompt: SECRET,
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
