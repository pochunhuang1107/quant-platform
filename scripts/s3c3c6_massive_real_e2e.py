#!/usr/bin/env python3
"""Human-gated S3c3c6 Massive QQQ/SPY real-E2E operator command.

Network-capable code is not authorization to contact Massive.  The execute
path requires a separately reviewed operational fingerprint, two exact human
confirmations, and a fingerprint-bound AWS Secrets Manager source before
invoking the S3c3c5 acquisition boundary.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TextIO

from backtest_engine.snapshot_pair import (
    DailyMarketDataSnapshotPairV2,
    prepare_daily_market_data_snapshot_pair_v2,
)
from research_sdk.daily_market_data_acquisition import (
    MASSIVE_AWS_SECRETS_MANAGER_SOURCE_KIND,
    MASSIVE_REAL_E2E_ACQUISITION_CONFIRMATION,
    MASSIVE_REAL_E2E_END_DATE,
    MASSIVE_REAL_E2E_ENTITLEMENT_CONFIRMATION,
    MASSIVE_REAL_E2E_OPERATOR_VERSION,
    MASSIVE_REAL_E2E_START_DATE,
    MassiveApiCredential,
    MassiveAwsSecretsManagerCredentialSource,
    MassiveDailyMarketDataHttpTransport,
    MassiveDailyMarketDataRealE2EConfig,
    MassiveDailyMarketDataRealE2EError,
    MassiveDailyMarketDataRealE2EPrepared,
    build_massive_daily_market_data_real_e2e_preflight,
    prepare_massive_daily_market_data_real_e2e,
    render_massive_daily_market_data_real_e2e_preflight,
    validate_massive_daily_market_data_real_e2e_prepared,
)
from research_sdk.daily_market_data_storage import (
    LocalDailyMarketDataSnapshotPublicationV2,
    LocalDailyMarketDataSnapshotReadbackV2,
    load_local_daily_market_data_snapshot_v2,
    publish_local_daily_market_data_snapshot_v2,
)

_FAILED = object()
_AWS_CLI_CONNECT_TIMEOUT_SECONDS = "5"
_AWS_CLI_READ_TIMEOUT_SECONDS = "15"
_AWS_CLI_PROCESS_TIMEOUT_SECONDS = 25
_TRUSTED_CREDENTIAL_LOADER_STAGES = frozenset(
    {
        "AWS Secrets Manager executable",
        "AWS Secrets Manager retrieval",
        "AWS Secrets Manager SecretString JSON",
        "AWS Secrets Manager credential field",
        "runtime credential validation",
    }
)


@dataclass(frozen=True)
class MassiveDailyMarketDataRealE2ESuccess:
    """Operator-visible success facts; not a new durable research identity."""

    prepared: MassiveDailyMarketDataRealE2EPrepared
    asset_snapshot_publication: LocalDailyMarketDataSnapshotPublicationV2
    benchmark_snapshot_publication: LocalDailyMarketDataSnapshotPublicationV2
    asset_snapshot_readback: LocalDailyMarketDataSnapshotReadbackV2
    benchmark_snapshot_readback: LocalDailyMarketDataSnapshotReadbackV2
    pair: DailyMarketDataSnapshotPairV2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Human-gated Massive QQQ/SPY real-E2E operator command",
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)
    for mode in ("preflight", "execute"):
        command = subparsers.add_parser(mode)
        command.add_argument("--expected-commit", required=True)
        command.add_argument("--batch-id", required=True)
        command.add_argument("--data-root", required=True, type=Path)
        command.add_argument("--created-by", required=True)
        command.add_argument("--license-notes", required=True)
        command.add_argument("--credential-source", required=True)
        command.add_argument("--aws-region", required=True)
        command.add_argument("--aws-secret-id", required=True)
        command.add_argument("--aws-secret-json-key", required=True)
        command.add_argument("--aws-secret-version-stage", required=True)
        if mode == "execute":
            command.add_argument("--approval-fingerprint", required=True)
    return parser


def run(
    argv: Sequence[str] | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    credential_loader: (
        Callable[[MassiveAwsSecretsManagerCredentialSource], MassiveApiCredential]
        | None
    ) = None,
    transport: MassiveDailyMarketDataHttpTransport | None = None,
    clock: Callable[[], datetime] | None = None,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Run one preflight or explicitly authorized execute command."""

    args = build_parser().parse_args(argv)
    credential_source = MassiveAwsSecretsManagerCredentialSource(
        source_kind=args.credential_source,
        region=args.aws_region,
        secret_id=args.aws_secret_id,
        json_key=args.aws_secret_json_key,
        version_stage=args.aws_secret_version_stage,
    )
    config = MassiveDailyMarketDataRealE2EConfig(
        expected_repository_commit=args.expected_commit,
        acquisition_batch_id=args.batch_id,
        data_root=args.data_root,
        created_by=args.created_by,
        license_notes=args.license_notes,
        credential_source=credential_source,
    )
    repository_root = Path.cwd()
    try:
        preflight = build_massive_daily_market_data_real_e2e_preflight(
            config=config,
            repository_root=repository_root,
        )
        stdout.write(render_massive_daily_market_data_real_e2e_preflight(preflight))
        if args.mode == "preflight":
            return 0
        approved_fingerprint = args.approval_fingerprint
        if approved_fingerprint != preflight.approval_fingerprint:
            raise MassiveDailyMarketDataRealE2EError("operator approval fingerprint")

        rechecked = build_massive_daily_market_data_real_e2e_preflight(
            config=config,
            repository_root=repository_root,
        )
        if rechecked.approval_fingerprint != approved_fingerprint:
            raise MassiveDailyMarketDataRealE2EError(
                "immediate pre-authorization Git/root recheck"
            )
        _require_confirmation(
            input_fn,
            MASSIVE_REAL_E2E_ENTITLEMENT_CONFIRMATION,
            "endpoint/retention confirmation",
        )
        _require_confirmation(
            input_fn,
            MASSIVE_REAL_E2E_ACQUISITION_CONFIRMATION,
            "acquisition confirmation",
        )
        final_recheck = build_massive_daily_market_data_real_e2e_preflight(
            config=config,
            repository_root=repository_root,
        )
        if final_recheck.approval_fingerprint != approved_fingerprint:
            raise MassiveDailyMarketDataRealE2EError(
                "final pre-secret Git/root/fingerprint recheck"
            )
        credential = _retrieve_credential(
            final_recheck.config.credential_source,
            credential_loader,
        )
        prepared = prepare_massive_daily_market_data_real_e2e(
            preflight=final_recheck,
            approved_fingerprint=approved_fingerprint,
            credential=credential,
            transport=transport,
            clock=clock,
        )
        del credential
        success = complete_massive_daily_market_data_real_e2e(prepared)
        stdout.write(render_success(success))
        return 0
    except MassiveDailyMarketDataRealE2EError as exc:
        stderr.write(f"ERROR: {exc}\n")
        return 1


def complete_massive_daily_market_data_real_e2e(
    prepared: MassiveDailyMarketDataRealE2EPrepared,
) -> MassiveDailyMarketDataRealE2ESuccess:
    """Run prepublication S3d2a, then publish/read back and rerun S3d2a."""

    canonical = validate_massive_daily_market_data_real_e2e_prepared(prepared)
    durable_sources = (
        _source_artifact("QQQ", canonical.asset_source_publication),
        _source_artifact("SPY", canonical.benchmark_source_publication),
    )
    prepublication_pair = _stage_value(
        _attempt(
            lambda: prepare_daily_market_data_snapshot_pair_v2(
                asset_files=canonical.asset_snapshot_plan.as_file_map(),
                benchmark_files=canonical.benchmark_snapshot_plan.as_file_map(),
                research_profile=canonical.preflight.research_profile,
                start_date=MASSIVE_REAL_E2E_START_DATE,
                end_date=MASSIVE_REAL_E2E_END_DATE,
            )
        ),
        "prepublication S3d2a pair preparation",
        durable_artifacts=durable_sources,
    )
    prepublication_pair_authority = _pair_result_authority(
        prepublication_pair,
        "prepublication S3d2a result authority",
        durable_artifacts=durable_sources,
    )
    root = canonical.preflight.config.data_root
    asset_publication = _stage_value(
        _attempt(
            lambda: publish_local_daily_market_data_snapshot_v2(
                snapshot_root=root,
                plan=canonical.asset_snapshot_plan,
            )
        ),
        "QQQ snapshot-v2 publication",
        durable_artifacts=durable_sources,
    )
    asset_artifact = _snapshot_artifact("QQQ", asset_publication)
    asset_readback = _stage_value(
        _attempt(
            lambda: load_local_daily_market_data_snapshot_v2(
                snapshot_root=root,
                snapshot_id=asset_publication.snapshot_id,
            )
        ),
        "QQQ snapshot-v2 readback",
        durable_artifacts=(*durable_sources, asset_artifact),
    )
    benchmark_publication = _stage_value(
        _attempt(
            lambda: publish_local_daily_market_data_snapshot_v2(
                snapshot_root=root,
                plan=canonical.benchmark_snapshot_plan,
            )
        ),
        "SPY snapshot-v2 publication",
        durable_artifacts=(*durable_sources, asset_artifact),
    )
    benchmark_artifact = _snapshot_artifact("SPY", benchmark_publication)
    durable_all = (*durable_sources, asset_artifact, benchmark_artifact)
    benchmark_readback = _stage_value(
        _attempt(
            lambda: load_local_daily_market_data_snapshot_v2(
                snapshot_root=root,
                snapshot_id=benchmark_publication.snapshot_id,
            )
        ),
        "SPY snapshot-v2 readback",
        durable_artifacts=durable_all,
    )
    final_pair = _stage_value(
        _attempt(
            lambda: prepare_daily_market_data_snapshot_pair_v2(
                asset_files=asset_readback.files,
                benchmark_files=benchmark_readback.files,
                research_profile=canonical.preflight.research_profile,
                start_date=MASSIVE_REAL_E2E_START_DATE,
                end_date=MASSIVE_REAL_E2E_END_DATE,
            )
        ),
        "final readback S3d2a pair preparation",
        durable_artifacts=durable_all,
    )
    final_pair_authority = _pair_result_authority(
        final_pair,
        "final S3d2a result authority",
        durable_artifacts=durable_all,
    )
    if prepublication_pair_authority != final_pair_authority:
        raise MassiveDailyMarketDataRealE2EError(
            "prepublication/readback S3d2a deterministic equality",
            durable_artifacts=durable_all,
        )
    return MassiveDailyMarketDataRealE2ESuccess(
        prepared=canonical,
        asset_snapshot_publication=asset_publication,
        benchmark_snapshot_publication=benchmark_publication,
        asset_snapshot_readback=asset_readback,
        benchmark_snapshot_readback=benchmark_readback,
        pair=final_pair,
    )


def render_success(success: MassiveDailyMarketDataRealE2ESuccess) -> str:
    """Render only verified operational and evidence facts."""

    prepared = success.prepared
    preflight = prepared.preflight
    asset_verified = success.asset_snapshot_readback.verified
    benchmark_verified = success.benchmark_snapshot_readback.verified
    asset_observed_at = (
        prepared.asset_source_capture.capture_manifest.capture_observed_at
    )
    benchmark_observed_at = (
        prepared.benchmark_source_capture.capture_manifest.capture_observed_at
    )
    lines = [
        "MASSIVE REAL-E2E EVIDENCE COMPLETE",
        f"REPOSITORY COMMIT: {preflight.config.expected_repository_commit}",
        f"OPERATOR TOOL VERSION: {MASSIVE_REAL_E2E_OPERATOR_VERSION}",
        (f"OPERATIONAL APPROVAL FINGERPRINT: {preflight.approval_fingerprint}"),
        f"BATCH ID: {preflight.config.acquisition_batch_id}",
        _instrument_summary("QQQ", preflight.asset_plan.instrument),
        _instrument_summary("SPY", preflight.benchmark_plan.instrument),
        _source_publication_summary("QQQ", prepared.asset_source_publication),
        _source_publication_summary("SPY", prepared.benchmark_source_publication),
        _snapshot_publication_summary("QQQ", success.asset_snapshot_publication),
        _snapshot_publication_summary("SPY", success.benchmark_snapshot_publication),
        (
            "SOURCE OBSERVATION TIMES: "
            f"QQQ={asset_observed_at.isoformat()}; "
            f"SPY={benchmark_observed_at.isoformat()}"
        ),
        (
            "REQUESTED RANGE: "
            f"{MASSIVE_REAL_E2E_START_DATE.isoformat()}.."
            f"{MASSIVE_REAL_E2E_END_DATE.isoformat()}"
        ),
        (
            "EXPECTED SESSIONS: "
            f"{preflight.expected_sessions.session_source_id} / "
            f"{preflight.expected_sessions.session_source_version} / "
            f"count={len(preflight.expected_sessions.session_dates)} / "
            f"hash={preflight.expected_sessions_hash}"
        ),
        f"POLICY: {preflight.policy.policy_id} / {preflight.policy_hash}",
        (
            "PROFILE: "
            f"{preflight.research_profile.profile_id} / "
            f"{preflight.research_profile_hash}"
        ),
        _quality_summary("QQQ", asset_verified),
        _quality_summary("SPY", benchmark_verified),
        f"QQQ BARS: count={asset_verified.quality_report.observed_session_count}",
        (f"SPY BARS: count={benchmark_verified.quality_report.observed_session_count}"),
        _corporate_action_summary("QQQ", asset_verified),
        _corporate_action_summary("SPY", benchmark_verified),
        (
            "FINAL S3d2a: PASS; "
            f"sessions={len(success.pair.run_session_dates)}; "
            f"range={success.pair.start_date.isoformat()}.."
            f"{success.pair.end_date.isoformat()}; "
            f"profile_hash={success.pair.profile_hash}; "
            "availability_policy=next_expected_session"
        ),
        _limitations_summary("QQQ", asset_verified),
        _limitations_summary("SPY", benchmark_verified),
        "PAPER/LIVE TRADING NOT APPROVED",
    ]
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class _Attempt[T]:
    succeeded: bool
    value: T | object


def _attempt[T](operation: Callable[[], T]) -> _Attempt[T]:
    try:
        return _Attempt(succeeded=True, value=operation())
    except Exception:
        return _Attempt(succeeded=False, value=_FAILED)


def _stage_value[T](
    attempted: _Attempt[T],
    stage: str,
    *,
    durable_artifacts: tuple[str, ...],
) -> T:
    if not attempted.succeeded or attempted.value is _FAILED:
        raise MassiveDailyMarketDataRealE2EError(
            stage,
            durable_artifacts=durable_artifacts,
        ) from None
    return attempted.value  # type: ignore[return-value]


def _require_confirmation(
    input_fn: Callable[[str], str],
    expected: str,
    stage: str,
) -> None:
    value = _stage_value(
        _attempt(lambda: input_fn(f'Type exactly "{expected}": ')),
        stage,
        durable_artifacts=(),
    )
    if type(value) is not str or value != expected:
        raise MassiveDailyMarketDataRealE2EError(stage)


def _retrieve_credential(
    source: MassiveAwsSecretsManagerCredentialSource,
    credential_loader: (
        Callable[[MassiveAwsSecretsManagerCredentialSource], MassiveApiCredential]
        | None
    ),
) -> MassiveApiCredential:
    trusted_internal_loader = credential_loader is None
    loader = (
        _load_massive_credential_from_aws_secrets_manager
        if credential_loader is None
        else credential_loader
    )
    succeeded = False
    value: object = _FAILED
    safe_stage: str | None = None
    try:
        value = loader(source)
        succeeded = True
    except MassiveDailyMarketDataRealE2EError as error:
        if (
            trusted_internal_loader
            and type(error) is MassiveDailyMarketDataRealE2EError
            and type(error.stage) is str
            and error.stage in _TRUSTED_CREDENTIAL_LOADER_STAGES
            and error.durable_artifacts == ()
        ):
            safe_stage = error.stage
    except (Exception, KeyboardInterrupt):
        pass
    if succeeded and type(value) is MassiveApiCredential:
        return value
    if safe_stage is not None:
        raise MassiveDailyMarketDataRealE2EError(safe_stage) from None
    stage = (
        "runtime credential validation"
        if succeeded
        else "AWS Secrets Manager retrieval"
    )
    raise MassiveDailyMarketDataRealE2EError(stage) from None


def _load_massive_credential_from_aws_secrets_manager(
    source: MassiveAwsSecretsManagerCredentialSource,
    *,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> MassiveApiCredential:
    if (
        type(source) is not MassiveAwsSecretsManagerCredentialSource
        or source.source_kind != MASSIVE_AWS_SECRETS_MANAGER_SOURCE_KIND
    ):
        raise MassiveDailyMarketDataRealE2EError(
            "AWS Secrets Manager retrieval"
        ) from None
    argv = (
        "aws",
        "secretsmanager",
        "get-secret-value",
        "--region",
        source.region,
        "--secret-id",
        source.secret_id,
        "--version-stage",
        source.version_stage,
        "--query",
        "SecretString",
        "--output",
        "text",
        "--no-cli-pager",
        "--cli-connect-timeout",
        _AWS_CLI_CONNECT_TIMEOUT_SECONDS,
        "--cli-read-timeout",
        _AWS_CLI_READ_TIMEOUT_SECONDS,
    )
    environment = os.environ.copy()
    environment.pop("AWS_ENDPOINT_URL", None)
    environment.pop("AWS_ENDPOINT_URL_SECRETS_MANAGER", None)
    environment.update(
        {
            "AWS_MAX_ATTEMPTS": "1",
            "AWS_RETRY_MODE": "standard",
            "AWS_PAGER": "",
            "AWS_CLI_AUTO_PROMPT": "off",
            "AWS_IGNORE_CONFIGURED_ENDPOINT_URLS": "true",
        }
    )
    runner = subprocess.run if command_runner is None else command_runner
    completed: object = _FAILED
    missing_executable = False
    try:
        completed = runner(
            argv,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            shell=False,
            timeout=_AWS_CLI_PROCESS_TIMEOUT_SECONDS,
            env=environment,
        )
    except FileNotFoundError:
        missing_executable = True
    except (Exception, KeyboardInterrupt):
        pass
    del environment
    if missing_executable:
        raise MassiveDailyMarketDataRealE2EError(
            "AWS Secrets Manager executable"
        ) from None
    if (
        type(completed) is not subprocess.CompletedProcess
        or type(completed.returncode) is not int
        or completed.returncode != 0
        or type(completed.stdout) is not str
    ):
        raise MassiveDailyMarketDataRealE2EError(
            "AWS Secrets Manager retrieval"
        ) from None
    raw_stdout = completed.stdout
    del completed
    if (
        not raw_stdout.endswith("\n")
        or raw_stdout.count("\n") != 1
        or "\r" in raw_stdout
    ):
        del raw_stdout
        raise MassiveDailyMarketDataRealE2EError(
            "AWS Secrets Manager retrieval"
        ) from None
    secret_string = raw_stdout[:-1]
    del raw_stdout
    parsed: object = _FAILED
    try:
        parsed = json.loads(
            secret_string,
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_json_constant,
        )
    except (TypeError, ValueError):
        pass
    del secret_string
    if type(parsed) is not dict:
        raise MassiveDailyMarketDataRealE2EError(
            "AWS Secrets Manager SecretString JSON"
        ) from None
    credential_value = parsed.get(source.json_key, _FAILED)
    del parsed
    if type(credential_value) is not str:
        del credential_value
        raise MassiveDailyMarketDataRealE2EError(
            "AWS Secrets Manager credential field"
        ) from None
    credential: object = _FAILED
    try:
        credential = MassiveApiCredential(credential_value)
    except Exception:
        pass
    del credential_value
    if type(credential) is not MassiveApiCredential:
        raise MassiveDailyMarketDataRealE2EError(
            "runtime credential validation"
        ) from None
    return credential


def _strict_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON object key")
        value[key] = item
    return value


def _reject_json_constant(_value: str) -> object:
    raise ValueError("non-finite JSON value")


def _pair_result_authority(
    pair: DailyMarketDataSnapshotPairV2,
    stage: str,
    *,
    durable_artifacts: tuple[str, ...],
) -> str:
    if type(pair) is not DailyMarketDataSnapshotPairV2:
        raise MassiveDailyMarketDataRealE2EError(
            stage,
            durable_artifacts=durable_artifacts,
        )
    return _stage_value(
        _attempt(
            lambda: json.dumps(
                pair.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        ),
        stage,
        durable_artifacts=durable_artifacts,
    )


def _source_artifact(label, publication) -> str:
    return f"{label} source capture {publication.capture_id} at {publication.path}"


def _snapshot_artifact(label, publication) -> str:
    return f"{label} snapshot {publication.snapshot_id} at {publication.path}"


def _source_publication_summary(label, publication) -> str:
    return (
        f"{label} SOURCE CAPTURE: id={publication.capture_id}; "
        f"path={publication.path}; status={publication.status.value}"
    )


def _instrument_summary(label, instrument) -> str:
    return (
        f"{label} INSTRUMENT: instrument_id={instrument.instrument_id}; "
        f"symbol={instrument.symbol}; venue={instrument.venue}"
    )


def _snapshot_publication_summary(label, publication) -> str:
    return (
        f"{label} SNAPSHOT: id={publication.snapshot_id}; "
        f"path={publication.path}; status={publication.status.value}"
    )


def _quality_summary(label, verified) -> str:
    quality = verified.quality_report
    return (
        f"{label} QUALITY: status={quality.status.value}; "
        f"expected={quality.expected_session_count}; "
        f"observed={quality.observed_session_count}; "
        f"missing={len(quality.missing_session_dates)}; "
        f"unexpected={len(quality.unexpected_session_dates)}; "
        f"duplicates={quality.duplicate_row_count}; "
        f"zero_volume={len(quality.zero_volume_dates)}"
    )


def _corporate_action_summary(label, verified) -> str:
    evidence = verified.corporate_action_evidence
    return (
        f"{label} CORPORATE ACTIONS: events={len(evidence.events)}; "
        f"completeness={evidence.completeness.value}"
    )


def _limitations_summary(label, verified) -> str:
    return f"{label} KNOWN LIMITATIONS: " + " | ".join(
        verified.bar_provenance.known_limitations
    )


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
