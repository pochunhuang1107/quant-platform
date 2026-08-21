"""Operator-gated Massive daily-market-data real-E2E preparation.

This module implements the credential-free approval authority and the first
phase of the future human-operated real-data workflow.  It intentionally stops
after immutable source-capture readback and verified snapshot-v2 planning.
Snapshot publication and S3d2a pair preparation remain the responsibility of
the cross-package operator command.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

from research_sdk.contracts.daily_market_data import (
    DailyMarketDataInstrument,
    DailyMarketDataPolicy,
    DistributionTreatment,
)
from research_sdk.contracts.daily_market_data_economics import (
    DailyMarketDataBarAvailabilityPolicy,
    DailyMarketDataCorporateActionEventType,
    DailyMarketDataCorporateActionEvidenceCompleteness,
    DailyMarketDataResearchProfile,
)
from research_sdk.contracts.daily_market_data_snapshots import (
    DailyMarketDataExpectedSessions,
)
from research_sdk.contracts.enums import (
    AssetClass,
    DataAdjustmentPolicy,
    TemporalCoverage,
)
from research_sdk.contracts.schema import RESEARCH_SDK_CONTRACT_SCHEMA_VERSION
from research_sdk.daily_market_data import (
    US_EQUITY_DAILY_SESSION_CALENDAR,
    US_EQUITY_DAILY_SESSION_SOURCE_ID,
    US_EQUITY_DAILY_SESSION_SOURCE_VERSION,
    US_EQUITY_DAILY_SESSION_TIMEZONE,
    derive_daily_market_data_expected_sessions_hash,
    derive_daily_market_data_policy_hash,
    derive_daily_market_data_research_profile_hash,
    derive_us_equity_daily_expected_sessions,
    validate_daily_market_data_snapshot_profile_compatibility,
)
from research_sdk.daily_market_data_acquisition.massive import (
    _BAR_RESPONSE_SIZE_LIMIT_BYTES,
    _CONNECT_TIMEOUT_SECONDS,
    _CORPORATE_ACTION_RESPONSE_SIZE_LIMIT_BYTES,
    _INSTRUMENT_RESPONSE_SIZE_LIMIT_BYTES,
    _MASSIVE_API_HOST,
    _MAX_DATE_SPAN_DAYS,
    _OVERALL_REQUEST_DEADLINE_SECONDS,
    _PAIR_RESPONSE_SIZE_LIMIT_BYTES,
    _READ_CHUNK_SIZE_BYTES,
    _READ_INACTIVITY_TIMEOUT_SECONDS,
    MassiveApiCredential,
    MassiveDailyMarketDataAcquisitionError,
    MassiveDailyMarketDataHttpTransport,
    MassiveDailyMarketDataInstrumentAcquisitionPlan,
    MassiveDailyMarketDataResponseError,
    MassiveDailyMarketDataTransportError,
    PlannedMassiveDailyMarketDataSourceCapturePair,
    _capture_credential,
    acquire_and_plan_massive_daily_market_data_source_capture_pair,
    plan_massive_daily_market_data_acquisition,
)
from research_sdk.daily_market_data_adapters.massive import (
    MASSIVE_PROVIDER,
    MASSIVE_SOURCE_FAMILY,
    AdaptedMassiveDailyMarketData,
    MassiveDailyMarketDataAdapterContext,
    adapt_massive_daily_market_data_source_capture,
)
from research_sdk.daily_market_data_adapters.massive_snapshot_v2 import (
    MassiveDailyMarketDataSnapshotBridgeContext,
    plan_massive_daily_market_data_snapshot_v2,
    validate_massive_daily_market_data_capture_pair_compatibility,
)
from research_sdk.daily_market_data_source_capture.local import (
    LocalDailyMarketDataSourceCapturePublication,
    LocalDailyMarketDataSourceCapturePublicationStatus,
    load_local_daily_market_data_source_capture,
    publish_local_daily_market_data_source_capture,
)
from research_sdk.daily_market_data_source_capture.verification import (
    VerifiedDailyMarketDataSourceCapture,
    verify_daily_market_data_source_capture,
)
from research_sdk.daily_market_data_storage.planning_v2 import (
    DailyMarketDataSnapshotPlanV2,
)
from research_sdk.daily_market_data_storage.verification_v2 import (
    VerifiedDailyMarketDataSnapshotV2,
    verify_daily_market_data_snapshot_bundle_v2,
)

MASSIVE_REAL_E2E_OPERATOR_VERSION: Final[str] = "massive-real-e2e-operator-v1"
MASSIVE_REAL_E2E_APPROVAL_DOMAIN: Final[str] = (
    "massive-real-e2e-operational-approval-v1"
)
MASSIVE_REAL_E2E_FIXED_HOST: Final[str] = _MASSIVE_API_HOST
MASSIVE_REAL_E2E_CURRENCY: Final[str] = "USD"
MASSIVE_REAL_E2E_START_DATE: Final[date] = date(2024, 1, 2)
MASSIVE_REAL_E2E_END_DATE: Final[date] = date(2024, 12, 31)
MASSIVE_REAL_E2E_EXPECTED_SESSION_COUNT: Final[int] = 252
MASSIVE_REAL_E2E_EXPECTED_SESSION_HASH: Final[str] = (
    "sha256:2914d0d978fdc1e9f8aad436d1acbfc10dc1022b74e080565e13d6aab9295068"
)
MASSIVE_REAL_E2E_POLICY_HASH: Final[str] = (
    "sha256:e25dd8e0659834ef5a94f3a5ae50e1f8301307f99bf30b9c746ac0e223e37fcb"
)
MASSIVE_REAL_E2E_RESEARCH_PROFILE_HASH: Final[str] = (
    "sha256:3f0945bac4b4faa3d228805d367ae8dd0e009db8e241e02299e8c7663c64a7ed"
)
MASSIVE_REAL_E2E_ENTITLEMENT_CONFIRMATION: Final[str] = (
    "I CONFIRM MASSIVE ENDPOINT ACCESS AND PRIVATE R&D LOCAL RETENTION"
)
MASSIVE_REAL_E2E_ACQUISITION_CONFIRMATION: Final[str] = (
    "ACQUIRE MASSIVE QQQ SPY 2024-01-02 2024-12-31"
)

_SOURCE_CAPTURE_MANAGED_DIRECTORY = "daily-market-data-source-captures"
_SNAPSHOT_MANAGED_DIRECTORY = "daily-market-data"
_SHA1_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_APPROVAL_FINGERPRINT_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_FAILED = object()

_CONTEXT_LIMITATIONS: Final[tuple[str, ...]] = (
    "XNYS is a common daily research-session policy and is not listing-venue authority",
    "this real-data validation does not approve paper trading or live trading",
)


class MassiveDailyMarketDataRealE2EError(ValueError):
    """Fail-closed operational error for the S3c3c6 real-E2E gate."""

    def __init__(
        self,
        stage: str,
        *,
        durable_artifacts: tuple[str, ...] = (),
    ) -> None:
        self.stage = stage
        self.durable_artifacts = durable_artifacts
        detail = f"Massive real-E2E stage failed: {stage}"
        if durable_artifacts:
            detail = f"{detail}; durable artifacts: {', '.join(durable_artifacts)}"
        super().__init__(detail)


@dataclass(frozen=True)
class MassiveDailyMarketDataRealE2EConfig:
    """Explicit non-secret authority for one operator-reviewed run."""

    expected_repository_commit: str
    acquisition_batch_id: str
    data_root: Path
    created_by: str
    license_notes: str


@dataclass(frozen=True)
class MassiveDailyMarketDataRealE2EPreflight:
    """Credential-free operation authority reviewed before execution."""

    config: MassiveDailyMarketDataRealE2EConfig
    repository_root: Path
    source_capture_managed_directory: Path
    snapshot_managed_directory: Path
    asset_plan: MassiveDailyMarketDataInstrumentAcquisitionPlan
    benchmark_plan: MassiveDailyMarketDataInstrumentAcquisitionPlan
    expected_sessions: DailyMarketDataExpectedSessions
    expected_sessions_hash: str
    policy: DailyMarketDataPolicy
    policy_hash: str
    research_profile: DailyMarketDataResearchProfile
    research_profile_hash: str
    approval_fingerprint: str


@dataclass(frozen=True)
class MassiveDailyMarketDataRealE2EPrepared:
    """Source-durable, snapshot-planned boundary before S3d2a/publication."""

    preflight: MassiveDailyMarketDataRealE2EPreflight
    asset_source_publication: LocalDailyMarketDataSourceCapturePublication
    benchmark_source_publication: LocalDailyMarketDataSourceCapturePublication
    asset_source_capture: VerifiedDailyMarketDataSourceCapture
    benchmark_source_capture: VerifiedDailyMarketDataSourceCapture
    ingestion_completed_at: datetime
    available_at: datetime
    created_at: datetime
    asset_snapshot_plan: DailyMarketDataSnapshotPlanV2
    benchmark_snapshot_plan: DailyMarketDataSnapshotPlanV2
    asset_verified_snapshot: VerifiedDailyMarketDataSnapshotV2
    benchmark_verified_snapshot: VerifiedDailyMarketDataSnapshotV2


@dataclass(frozen=True)
class _GitState:
    repository_root: Path
    branch: str
    head: str
    main: str
    origin_main: str
    clean: bool


@dataclass(frozen=True)
class _Attempt[T]:
    succeeded: bool
    value: T | object


@dataclass(frozen=True)
class _AcquisitionAttempt:
    succeeded: bool
    value: PlannedMassiveDailyMarketDataSourceCapturePair | object
    safe_reason: str | None


def build_massive_daily_market_data_real_e2e_preflight(
    *,
    config: MassiveDailyMarketDataRealE2EConfig,
    repository_root: Path,
) -> MassiveDailyMarketDataRealE2EPreflight:
    """Build the exact credential-free operator approval authority."""

    captured_config = _capture_config(config)
    captured_repository_root = _validate_repository_root(repository_root)
    _validate_git_gate(
        repository_root=captured_repository_root,
        expected_commit=captured_config.expected_repository_commit,
    )
    resolved_data_root = _validate_external_data_root(
        captured_config.data_root,
        repository_root=captured_repository_root,
    )
    canonical_config = MassiveDailyMarketDataRealE2EConfig(
        expected_repository_commit=captured_config.expected_repository_commit,
        acquisition_batch_id=captured_config.acquisition_batch_id,
        data_root=resolved_data_root,
        created_by=captured_config.created_by,
        license_notes=captured_config.license_notes,
    )
    source_directory = resolved_data_root / _SOURCE_CAPTURE_MANAGED_DIRECTORY
    snapshot_directory = resolved_data_root / _SNAPSHOT_MANAGED_DIRECTORY
    _validate_managed_location(source_directory, "source-capture managed directory")
    _validate_managed_location(snapshot_directory, "snapshot managed directory")

    asset_plan = _stage_value(
        _attempt(
            lambda: plan_massive_daily_market_data_acquisition(
                instrument=_build_asset_instrument(),
                start_date=MASSIVE_REAL_E2E_START_DATE,
                end_date=MASSIVE_REAL_E2E_END_DATE,
                acquisition_batch_id=canonical_config.acquisition_batch_id,
            )
        ),
        "QQQ acquisition-plan authority",
    )
    benchmark_plan = _stage_value(
        _attempt(
            lambda: plan_massive_daily_market_data_acquisition(
                instrument=_build_benchmark_instrument(),
                start_date=MASSIVE_REAL_E2E_START_DATE,
                end_date=MASSIVE_REAL_E2E_END_DATE,
                acquisition_batch_id=canonical_config.acquisition_batch_id,
            )
        ),
        "SPY acquisition-plan authority",
    )
    expected_sessions = _stage_value(
        _attempt(
            lambda: derive_us_equity_daily_expected_sessions(
                start_date=MASSIVE_REAL_E2E_START_DATE,
                end_date=MASSIVE_REAL_E2E_END_DATE,
            )
        ),
        "expected-session derivation",
    )
    expected_sessions_hash = _stage_value(
        _attempt(
            lambda: derive_daily_market_data_expected_sessions_hash(expected_sessions)
        ),
        "expected-session hash authority",
    )
    _validate_expected_sessions(expected_sessions, expected_sessions_hash)
    policy = _stage_value(_attempt(_build_policy), "snapshot policy authority")
    policy_hash = _stage_value(
        _attempt(lambda: derive_daily_market_data_policy_hash(policy)),
        "snapshot policy hash authority",
    )
    if policy_hash != MASSIVE_REAL_E2E_POLICY_HASH:
        raise MassiveDailyMarketDataRealE2EError("snapshot policy hash authority")
    profile = _stage_value(
        _attempt(_build_research_profile),
        "research profile authority",
    )
    profile_hash = _stage_value(
        _attempt(lambda: derive_daily_market_data_research_profile_hash(profile)),
        "research profile hash authority",
    )
    if profile_hash != MASSIVE_REAL_E2E_RESEARCH_PROFILE_HASH:
        raise MassiveDailyMarketDataRealE2EError("research profile hash authority")

    fingerprint_payload = _approval_payload(
        config=canonical_config,
        repository_root=captured_repository_root,
        source_directory=source_directory,
        snapshot_directory=snapshot_directory,
        asset_plan=asset_plan,
        benchmark_plan=benchmark_plan,
        expected_sessions=expected_sessions,
        expected_sessions_hash=expected_sessions_hash,
        policy=policy,
        policy_hash=policy_hash,
        research_profile=profile,
        research_profile_hash=profile_hash,
    )
    fingerprint = _approval_fingerprint(fingerprint_payload)
    return MassiveDailyMarketDataRealE2EPreflight(
        config=canonical_config,
        repository_root=captured_repository_root,
        source_capture_managed_directory=source_directory,
        snapshot_managed_directory=snapshot_directory,
        asset_plan=asset_plan,
        benchmark_plan=benchmark_plan,
        expected_sessions=expected_sessions,
        expected_sessions_hash=expected_sessions_hash,
        policy=policy,
        policy_hash=policy_hash,
        research_profile=profile,
        research_profile_hash=profile_hash,
        approval_fingerprint=fingerprint,
    )


def prepare_massive_daily_market_data_real_e2e(
    *,
    preflight: MassiveDailyMarketDataRealE2EPreflight,
    approved_fingerprint: str,
    credential: MassiveApiCredential,
    transport: MassiveDailyMarketDataHttpTransport | None = None,
    clock: Callable[[], datetime] | None = None,
) -> MassiveDailyMarketDataRealE2EPrepared:
    """Acquire fakeable evidence and stop before snapshot-v2 publication."""

    canonical_preflight = _rebuild_preflight(preflight)
    fingerprint = _require_fingerprint(approved_fingerprint)
    if fingerprint != canonical_preflight.approval_fingerprint:
        raise MassiveDailyMarketDataRealE2EError("operational approval fingerprint")
    effective_clock = _utc_now if clock is None else clock
    acquired = _attempt_acquisition(
        preflight=canonical_preflight,
        credential=credential,
        transport=transport,
        clock=effective_clock,
    )
    del credential
    pair = _acquisition_stage_value(acquired)

    asset_verified = _stage_value(
        _attempt(
            lambda: verify_daily_market_data_source_capture(pair.asset.as_file_map())
        ),
        "in-memory QQQ source-capture verification",
    )
    benchmark_verified = _stage_value(
        _attempt(
            lambda: verify_daily_market_data_source_capture(
                pair.benchmark.as_file_map()
            )
        ),
        "in-memory SPY source-capture verification",
    )
    asset_adapted = _adapt(
        asset_verified,
        canonical_preflight.asset_plan.instrument,
        "in-memory QQQ Massive adaptation",
    )
    benchmark_adapted = _adapt(
        benchmark_verified,
        canonical_preflight.benchmark_plan.instrument,
        "in-memory SPY Massive adaptation",
    )
    _stage_none(
        _attempt(
            lambda: validate_massive_daily_market_data_capture_pair_compatibility(
                asset=asset_adapted,
                benchmark=benchmark_adapted,
            )
        ),
        "in-memory Massive pair compatibility",
    )
    _stage_none(
        _attempt(lambda: _revalidate_downstream_authority(canonical_preflight)),
        "downstream authority revalidation",
    )
    ingestion_completed_at = _read_clock(
        effective_clock,
        "ingestion_completed_at clock",
    )
    _require_capture_before(
        asset_verified,
        ingestion_completed_at,
        "QQQ capture chronology",
    )
    _require_capture_before(
        benchmark_verified,
        ingestion_completed_at,
        "SPY capture chronology",
    )

    asset_publication = _stage_value(
        _attempt(
            lambda: publish_local_daily_market_data_source_capture(
                source_capture_root=canonical_preflight.config.data_root,
                plan=pair.asset,
            )
        ),
        "QQQ source-capture publication",
    )
    asset_artifact = _source_artifact("QQQ", asset_publication)
    asset_readback = _stage_value(
        _attempt(
            lambda: load_local_daily_market_data_source_capture(
                source_capture_root=canonical_preflight.config.data_root,
                capture_id=asset_publication.capture_id,
            )
        ),
        "QQQ source-capture readback",
        durable_artifacts=(asset_artifact,),
    )
    benchmark_publication = _stage_value(
        _attempt(
            lambda: publish_local_daily_market_data_source_capture(
                source_capture_root=canonical_preflight.config.data_root,
                plan=pair.benchmark,
            )
        ),
        "SPY source-capture publication",
        durable_artifacts=(asset_artifact,),
    )
    benchmark_artifact = _source_artifact("SPY", benchmark_publication)
    durable_sources = (asset_artifact, benchmark_artifact)
    benchmark_readback = _stage_value(
        _attempt(
            lambda: load_local_daily_market_data_source_capture(
                source_capture_root=canonical_preflight.config.data_root,
                capture_id=benchmark_publication.capture_id,
            )
        ),
        "SPY source-capture readback",
        durable_artifacts=durable_sources,
    )

    durable_asset_adapted = _adapt(
        asset_readback,
        canonical_preflight.asset_plan.instrument,
        "readback QQQ Massive adaptation",
        durable_artifacts=durable_sources,
    )
    durable_benchmark_adapted = _adapt(
        benchmark_readback,
        canonical_preflight.benchmark_plan.instrument,
        "readback SPY Massive adaptation",
        durable_artifacts=durable_sources,
    )
    _stage_none(
        _attempt(
            lambda: validate_massive_daily_market_data_capture_pair_compatibility(
                asset=durable_asset_adapted,
                benchmark=durable_benchmark_adapted,
            )
        ),
        "readback Massive pair compatibility",
        durable_artifacts=durable_sources,
    )
    available_at = _read_clock(
        effective_clock,
        "available_at clock",
        durable_artifacts=durable_sources,
    )
    if ingestion_completed_at > available_at:
        raise MassiveDailyMarketDataRealE2EError(
            "available_at chronology",
            durable_artifacts=durable_sources,
        )
    created_at = _read_clock(
        effective_clock,
        "created_at clock",
        durable_artifacts=durable_sources,
    )
    if available_at > created_at:
        raise MassiveDailyMarketDataRealE2EError(
            "created_at chronology",
            durable_artifacts=durable_sources,
        )
    bridge_context = MassiveDailyMarketDataSnapshotBridgeContext(
        ingestion_completed_at=ingestion_completed_at,
        available_at=available_at,
        created_at=created_at,
        created_by=canonical_preflight.config.created_by,
        license_notes=canonical_preflight.config.license_notes,
        known_limitations=_CONTEXT_LIMITATIONS,
    )
    asset_snapshot_plan = _stage_value(
        _attempt(
            lambda: plan_massive_daily_market_data_snapshot_v2(
                adapted=durable_asset_adapted,
                policy=canonical_preflight.policy,
                expected_sessions=canonical_preflight.expected_sessions,
                context=bridge_context,
            )
        ),
        "QQQ snapshot-v2 planning",
        durable_artifacts=durable_sources,
    )
    benchmark_snapshot_plan = _stage_value(
        _attempt(
            lambda: plan_massive_daily_market_data_snapshot_v2(
                adapted=durable_benchmark_adapted,
                policy=canonical_preflight.policy,
                expected_sessions=canonical_preflight.expected_sessions,
                context=bridge_context,
            )
        ),
        "SPY snapshot-v2 planning",
        durable_artifacts=durable_sources,
    )
    asset_snapshot = _stage_value(
        _attempt(
            lambda: verify_daily_market_data_snapshot_bundle_v2(
                asset_snapshot_plan.as_file_map()
            )
        ),
        "QQQ snapshot-v2 pure verification",
        durable_artifacts=durable_sources,
    )
    benchmark_snapshot = _stage_value(
        _attempt(
            lambda: verify_daily_market_data_snapshot_bundle_v2(
                benchmark_snapshot_plan.as_file_map()
            )
        ),
        "SPY snapshot-v2 pure verification",
        durable_artifacts=durable_sources,
    )
    _stage_value(
        _attempt(
            lambda: validate_daily_market_data_snapshot_profile_compatibility(
                verified_snapshot=asset_snapshot,
                research_profile=canonical_preflight.research_profile,
            )
        ),
        "QQQ research-profile compatibility",
        durable_artifacts=durable_sources,
    )
    _stage_value(
        _attempt(
            lambda: validate_daily_market_data_snapshot_profile_compatibility(
                verified_snapshot=benchmark_snapshot,
                research_profile=canonical_preflight.research_profile,
            )
        ),
        "SPY research-profile compatibility",
        durable_artifacts=durable_sources,
    )
    return MassiveDailyMarketDataRealE2EPrepared(
        preflight=canonical_preflight,
        asset_source_publication=asset_publication,
        benchmark_source_publication=benchmark_publication,
        asset_source_capture=asset_readback,
        benchmark_source_capture=benchmark_readback,
        ingestion_completed_at=ingestion_completed_at,
        available_at=available_at,
        created_at=created_at,
        asset_snapshot_plan=asset_snapshot_plan,
        benchmark_snapshot_plan=benchmark_snapshot_plan,
        asset_verified_snapshot=asset_snapshot,
        benchmark_verified_snapshot=benchmark_snapshot,
    )


def validate_massive_daily_market_data_real_e2e_prepared(
    prepared: MassiveDailyMarketDataRealE2EPrepared,
) -> MassiveDailyMarketDataRealE2EPrepared:
    """Revalidate the public prepared boundary before cross-package use."""

    if type(prepared) is not MassiveDailyMarketDataRealE2EPrepared:
        raise MassiveDailyMarketDataRealE2EError("prepared object authority")
    values = (
        prepared.preflight,
        prepared.asset_source_publication,
        prepared.benchmark_source_publication,
        prepared.asset_source_capture,
        prepared.benchmark_source_capture,
        prepared.ingestion_completed_at,
        prepared.available_at,
        prepared.created_at,
        prepared.asset_snapshot_plan,
        prepared.benchmark_snapshot_plan,
    )
    (
        preflight,
        asset_publication,
        benchmark_publication,
        asset_capture,
        benchmark_capture,
        ingestion_completed_at,
        available_at,
        created_at,
        asset_plan,
        benchmark_plan,
    ) = values
    canonical_preflight = _rebuild_preflight(preflight)
    canonical_asset_publication, canonical_asset_capture = _stage_value(
        _attempt(
            lambda: _canonicalize_source_publication(
                asset_publication,
                canonical_preflight,
                "QQQ",
            )
        ),
        "prepared QQQ source-capture authority",
    )
    asset_artifact = _source_artifact("QQQ", canonical_asset_publication)
    canonical_benchmark_publication, canonical_benchmark_capture = _stage_value(
        _attempt(
            lambda: _canonicalize_source_publication(
                benchmark_publication,
                canonical_preflight,
                "SPY",
            )
        ),
        "prepared SPY source-capture authority",
        durable_artifacts=(asset_artifact,),
    )
    benchmark_artifact = _source_artifact("SPY", canonical_benchmark_publication)
    durable_sources = (asset_artifact, benchmark_artifact)
    if type(asset_capture) is not VerifiedDailyMarketDataSourceCapture:
        raise MassiveDailyMarketDataRealE2EError(
            "prepared QQQ capture authority",
            durable_artifacts=durable_sources,
        )
    if type(benchmark_capture) is not VerifiedDailyMarketDataSourceCapture:
        raise MassiveDailyMarketDataRealE2EError(
            "prepared SPY capture authority",
            durable_artifacts=durable_sources,
        )
    supplied_asset_capture_id = asset_capture.capture_id
    supplied_benchmark_capture_id = benchmark_capture.capture_id
    if type(supplied_asset_capture_id) is not str:
        raise MassiveDailyMarketDataRealE2EError(
            "prepared QQQ capture identity",
            durable_artifacts=durable_sources,
        )
    if type(supplied_benchmark_capture_id) is not str:
        raise MassiveDailyMarketDataRealE2EError(
            "prepared SPY capture identity",
            durable_artifacts=durable_sources,
        )
    if canonical_asset_capture.capture_id != supplied_asset_capture_id:
        raise MassiveDailyMarketDataRealE2EError(
            "prepared QQQ capture identity",
            durable_artifacts=durable_sources,
        )
    if canonical_benchmark_capture.capture_id != supplied_benchmark_capture_id:
        raise MassiveDailyMarketDataRealE2EError(
            "prepared SPY capture identity",
            durable_artifacts=durable_sources,
        )
    _require_exact_utc(
        ingestion_completed_at,
        "prepared ingestion_completed_at",
        durable_artifacts=durable_sources,
    )
    _require_exact_utc(
        available_at,
        "prepared available_at",
        durable_artifacts=durable_sources,
    )
    _require_exact_utc(
        created_at,
        "prepared created_at",
        durable_artifacts=durable_sources,
    )
    if not ingestion_completed_at <= available_at <= created_at:
        raise MassiveDailyMarketDataRealE2EError(
            "prepared chronology",
            durable_artifacts=durable_sources,
        )
    if type(asset_plan) is not DailyMarketDataSnapshotPlanV2:
        raise MassiveDailyMarketDataRealE2EError(
            "prepared QQQ snapshot plan",
            durable_artifacts=durable_sources,
        )
    if type(benchmark_plan) is not DailyMarketDataSnapshotPlanV2:
        raise MassiveDailyMarketDataRealE2EError(
            "prepared SPY snapshot plan",
            durable_artifacts=durable_sources,
        )
    canonical_asset_adapted = _adapt(
        canonical_asset_capture,
        canonical_preflight.asset_plan.instrument,
        "prepared QQQ readback adaptation",
        durable_artifacts=durable_sources,
    )
    canonical_benchmark_adapted = _adapt(
        canonical_benchmark_capture,
        canonical_preflight.benchmark_plan.instrument,
        "prepared SPY readback adaptation",
        durable_artifacts=durable_sources,
    )
    _stage_none(
        _attempt(
            lambda: validate_massive_daily_market_data_capture_pair_compatibility(
                asset=canonical_asset_adapted,
                benchmark=canonical_benchmark_adapted,
            )
        ),
        "prepared readback pair compatibility",
        durable_artifacts=durable_sources,
    )
    canonical_context = MassiveDailyMarketDataSnapshotBridgeContext(
        ingestion_completed_at=ingestion_completed_at,
        available_at=available_at,
        created_at=created_at,
        created_by=canonical_preflight.config.created_by,
        license_notes=canonical_preflight.config.license_notes,
        known_limitations=_CONTEXT_LIMITATIONS,
    )
    canonical_asset_plan = _stage_value(
        _attempt(
            lambda: plan_massive_daily_market_data_snapshot_v2(
                adapted=canonical_asset_adapted,
                policy=canonical_preflight.policy,
                expected_sessions=canonical_preflight.expected_sessions,
                context=canonical_context,
            )
        ),
        "prepared QQQ snapshot rederivation",
        durable_artifacts=durable_sources,
    )
    canonical_benchmark_plan = _stage_value(
        _attempt(
            lambda: plan_massive_daily_market_data_snapshot_v2(
                adapted=canonical_benchmark_adapted,
                policy=canonical_preflight.policy,
                expected_sessions=canonical_preflight.expected_sessions,
                context=canonical_context,
            )
        ),
        "prepared SPY snapshot rederivation",
        durable_artifacts=durable_sources,
    )
    supplied_asset_files = _stage_value(
        _attempt(asset_plan.as_file_map),
        "prepared QQQ supplied snapshot files",
        durable_artifacts=durable_sources,
    )
    supplied_benchmark_files = _stage_value(
        _attempt(benchmark_plan.as_file_map),
        "prepared SPY supplied snapshot files",
        durable_artifacts=durable_sources,
    )
    canonical_asset_files = _stage_value(
        _attempt(canonical_asset_plan.as_file_map),
        "prepared QQQ canonical snapshot files",
        durable_artifacts=durable_sources,
    )
    canonical_benchmark_files = _stage_value(
        _attempt(canonical_benchmark_plan.as_file_map),
        "prepared SPY canonical snapshot files",
        durable_artifacts=durable_sources,
    )
    supplied_asset_file_authority = _capture_snapshot_file_map(
        supplied_asset_files,
        "prepared QQQ supplied snapshot files",
        durable_artifacts=durable_sources,
    )
    supplied_benchmark_file_authority = _capture_snapshot_file_map(
        supplied_benchmark_files,
        "prepared SPY supplied snapshot files",
        durable_artifacts=durable_sources,
    )
    canonical_asset_file_authority = _capture_snapshot_file_map(
        canonical_asset_files,
        "prepared QQQ canonical snapshot files",
        durable_artifacts=durable_sources,
    )
    canonical_benchmark_file_authority = _capture_snapshot_file_map(
        canonical_benchmark_files,
        "prepared SPY canonical snapshot files",
        durable_artifacts=durable_sources,
    )
    if supplied_asset_file_authority != canonical_asset_file_authority:
        raise MassiveDailyMarketDataRealE2EError(
            "prepared QQQ snapshot authority",
            durable_artifacts=durable_sources,
        )
    if supplied_benchmark_file_authority != canonical_benchmark_file_authority:
        raise MassiveDailyMarketDataRealE2EError(
            "prepared SPY snapshot authority",
            durable_artifacts=durable_sources,
        )
    verified_asset = _stage_value(
        _attempt(
            lambda: verify_daily_market_data_snapshot_bundle_v2(canonical_asset_files)
        ),
        "prepared QQQ snapshot verification",
        durable_artifacts=durable_sources,
    )
    verified_benchmark = _stage_value(
        _attempt(
            lambda: verify_daily_market_data_snapshot_bundle_v2(
                canonical_benchmark_files
            )
        ),
        "prepared SPY snapshot verification",
        durable_artifacts=durable_sources,
    )
    _stage_value(
        _attempt(
            lambda: validate_daily_market_data_snapshot_profile_compatibility(
                verified_snapshot=verified_asset,
                research_profile=canonical_preflight.research_profile,
            )
        ),
        "prepared QQQ profile compatibility",
        durable_artifacts=durable_sources,
    )
    _stage_value(
        _attempt(
            lambda: validate_daily_market_data_snapshot_profile_compatibility(
                verified_snapshot=verified_benchmark,
                research_profile=canonical_preflight.research_profile,
            )
        ),
        "prepared SPY profile compatibility",
        durable_artifacts=durable_sources,
    )
    return MassiveDailyMarketDataRealE2EPrepared(
        preflight=canonical_preflight,
        asset_source_publication=canonical_asset_publication,
        benchmark_source_publication=canonical_benchmark_publication,
        asset_source_capture=canonical_asset_capture,
        benchmark_source_capture=canonical_benchmark_capture,
        ingestion_completed_at=ingestion_completed_at,
        available_at=available_at,
        created_at=created_at,
        asset_snapshot_plan=canonical_asset_plan,
        benchmark_snapshot_plan=canonical_benchmark_plan,
        asset_verified_snapshot=verified_asset,
        benchmark_verified_snapshot=verified_benchmark,
    )


def render_massive_daily_market_data_real_e2e_preflight(
    preflight: MassiveDailyMarketDataRealE2EPreflight,
) -> str:
    """Render a deterministic, credential-free operator review summary."""

    canonical = _rebuild_preflight(preflight)
    lines = [
        "MODE: PREFLIGHT ONLY",
        f"EXPECTED REPOSITORY COMMIT: {canonical.config.expected_repository_commit}",
        "VERIFIED GIT STATE: main == HEAD == main == origin/main; clean",
        "PROVIDER: Massive",
        f"HOST: {MASSIVE_REAL_E2E_FIXED_HOST}",
        (
            "NETWORK: HTTPS GET only; Authorization Bearer header only; "
            "redirects not followed"
        ),
        "CREDENTIAL STATUS: NOT REQUESTED",
        _instrument_summary("ASSET", canonical.asset_plan.instrument),
        _instrument_summary("BENCHMARK", canonical.benchmark_plan.instrument),
        f"CURRENCY: {MASSIVE_REAL_E2E_CURRENCY}",
        (
            "RANGE: "
            f"{MASSIVE_REAL_E2E_START_DATE.isoformat()}.."
            f"{MASSIVE_REAL_E2E_END_DATE.isoformat()}"
        ),
        (
            "EXPECTED SESSIONS: "
            f"{canonical.expected_sessions.session_source_id} / "
            f"{canonical.expected_sessions.session_source_version} / "
            f"count={len(canonical.expected_sessions.session_dates)} / "
            f"hash={canonical.expected_sessions_hash}"
        ),
        f"BATCH ID: {canonical.config.acquisition_batch_id}",
        f"DATA ROOT: {canonical.config.data_root}",
        f"SOURCE CAPTURE DIRECTORY: {canonical.source_capture_managed_directory}",
        f"SNAPSHOT DIRECTORY: {canonical.snapshot_managed_directory}",
        (
            "RESPONSE LIMITS: bars=4194304; dividends=2097152; "
            "splits=2097152; instrument=8388608; pair=16777216; "
            "read-chunk=65536"
        ),
        (
            "TIMEOUTS: connect<=5s; read-inactivity<=15s; "
            "application-acceptance-deadline=30s/request"
        ),
        (
            "DNS CAVEAT: stdlib DNS is not hard-interruptible; evidence that "
            "completes after the acceptance deadline is rejected"
        ),
        (
            "RETRY/REDIRECT/PAGINATION: no automatic retries; no redirect "
            "following; next_url must be absent"
        ),
        f"POLICY: {canonical.policy.policy_id} / {canonical.policy_hash}",
        (
            "PROFILE: "
            f"{canonical.research_profile.profile_id} / "
            f"{canonical.research_profile_hash}"
        ),
        f"CREATED BY: {canonical.config.created_by}",
        f"LICENSE NOTES: {canonical.config.license_notes}",
        f"CONTEXT LIMITATIONS: {' | '.join(_CONTEXT_LIMITATIONS)}",
        f"CONFIRMATION 1: {MASSIVE_REAL_E2E_ENTITLEMENT_CONFIRMATION}",
        f"CONFIRMATION 2: {MASSIVE_REAL_E2E_ACQUISITION_CONFIRMATION}",
    ]
    for side, plan in (
        ("ASSET", canonical.asset_plan),
        ("BENCHMARK", canonical.benchmark_plan),
    ):
        for request in plan.requests:
            lines.append(
                "REQUEST: "
                f"{side} {request.role.value} GET {request.path} "
                f"query={json.dumps(request.query_parameters, separators=(',', ':'))} "
                "request_parameters="
                f"{json.dumps(request.request_parameters, separators=(',', ':'))} "
                "requested_scope="
                f"{json.dumps(request.requested_scope, separators=(',', ':'))} "
                f"source_reference={request.sanitized_source_reference} "
                f"limit_bytes={request.response_size_limit_bytes}"
            )
    lines.extend(
        (
            (f"OPERATIONAL APPROVAL FINGERPRINT: {canonical.approval_fingerprint}"),
            "NO NETWORK REQUEST HAS OCCURRED",
        )
    )
    return "\n".join(lines) + "\n"


def _build_policy() -> DailyMarketDataPolicy:
    return DailyMarketDataPolicy(
        schema_version=RESEARCH_SDK_CONTRACT_SCHEMA_VERSION,
        policy_id="daily-market-data-etf-execution-v1",
        asset_class=AssetClass.ETFS,
        frequency="daily",
        calendar=US_EQUITY_DAILY_SESSION_CALENDAR,
        timezone=US_EQUITY_DAILY_SESSION_TIMEZONE,
        adjustment_policy=DataAdjustmentPolicy.RAW,
        distribution_treatment=DistributionTreatment.EXPLICIT_CASH,
        corporate_action_policy="raw OHLCV plus explicit corporate-action evidence",
        universe_membership_policy="static explicit instrument universe",
        survivorship_policy="static named instrument; no survivorship-free claim",
        delisting_policy="unsupported for ETF S3a; fail closed if encountered",
        canonicalization_version="daily-market-data-canonical-v1",
        quality_policy_version="daily-market-data-quality-v1",
    )


def _build_asset_instrument() -> DailyMarketDataInstrument:
    return DailyMarketDataInstrument(
        instrument_id="instrument-us-etf-qqq-xnas",
        symbol="QQQ",
        venue="XNAS",
    )


def _build_benchmark_instrument() -> DailyMarketDataInstrument:
    return DailyMarketDataInstrument(
        instrument_id="instrument-us-etf-spy-arcx",
        symbol="SPY",
        venue="ARCX",
    )


def _build_research_profile() -> DailyMarketDataResearchProfile:
    return DailyMarketDataResearchProfile(
        schema_version=RESEARCH_SDK_CONTRACT_SCHEMA_VERSION,
        profile_id="daily-etf-latest-known-us-equity-v1",
        profile_policy_version="daily-etf-latest-known-us-equity-profile-v1",
        asset_class=AssetClass.ETFS,
        frequency="daily",
        required_currency=MASSIVE_REAL_E2E_CURRENCY,
        permitted_temporal_coverage=(TemporalCoverage.LATEST_KNOWN,),
        adjustment_policy=DataAdjustmentPolicy.RAW,
        distribution_treatment=DistributionTreatment.EXPLICIT_CASH,
        daily_bar_availability_policy=(
            DailyMarketDataBarAvailabilityPolicy.NEXT_EXPECTED_SESSION
        ),
        allowed_corporate_action_completeness=(
            DailyMarketDataCorporateActionEvidenceCompleteness.CHECKED_EVENTS_CAPTURED,
            DailyMarketDataCorporateActionEvidenceCompleteness.CHECKED_NO_EVENTS,
        ),
        supported_corporate_action_event_types=(
            DailyMarketDataCorporateActionEventType.CASH_DISTRIBUTION,
            DailyMarketDataCorporateActionEventType.SPLIT,
        ),
        unsupported_events_allowed=False,
        corporate_action_coverage_requirement=(
            "corporate-action evidence coverage must cover the full expected "
            "bar-session coverage"
        ),
        calendar=US_EQUITY_DAILY_SESSION_CALENDAR,
        timezone=US_EQUITY_DAILY_SESSION_TIMEZONE,
        session_source_id=US_EQUITY_DAILY_SESSION_SOURCE_ID,
        session_source_version=US_EQUITY_DAILY_SESSION_SOURCE_VERSION,
        universe_membership_policy="static explicit instrument universe",
        survivorship_policy="static named instrument; no survivorship-free claim",
        delisting_policy="unsupported for ETF S3a; fail closed if encountered",
    )


def _build_operational_network_policy() -> dict[str, object]:
    return {
        "scheme": "https",
        "method": "GET",
        "authentication": "Authorization: Bearer <runtime credential>",
        "maximum_inclusive_calendar_days": _MAX_DATE_SPAN_DAYS + 1,
        "role_response_size_limits_bytes": {
            "bar_response": _BAR_RESPONSE_SIZE_LIMIT_BYTES,
            "dividend_response": _CORPORATE_ACTION_RESPONSE_SIZE_LIMIT_BYTES,
            "split_response": _CORPORATE_ACTION_RESPONSE_SIZE_LIMIT_BYTES,
        },
        "instrument_response_size_limit_bytes": _INSTRUMENT_RESPONSE_SIZE_LIMIT_BYTES,
        "pair_response_size_limit_bytes": _PAIR_RESPONSE_SIZE_LIMIT_BYTES,
        "response_read_chunk_size_bytes": _READ_CHUNK_SIZE_BYTES,
        "connect_timeout_seconds": _CONNECT_TIMEOUT_SECONDS,
        "read_inactivity_timeout_seconds": _READ_INACTIVITY_TIMEOUT_SECONDS,
        "application_acceptance_deadline_seconds": (_OVERALL_REQUEST_DEADLINE_SECONDS),
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


def _capture_config(
    config: MassiveDailyMarketDataRealE2EConfig,
) -> MassiveDailyMarketDataRealE2EConfig:
    if type(config) is not MassiveDailyMarketDataRealE2EConfig:
        raise MassiveDailyMarketDataRealE2EError("configuration authority")
    commit = config.expected_repository_commit
    batch_id = config.acquisition_batch_id
    data_root = config.data_root
    created_by = config.created_by
    license_notes = config.license_notes
    if type(commit) is not str or _SHA1_PATTERN.fullmatch(commit) is None:
        raise MassiveDailyMarketDataRealE2EError("expected repository commit")
    _require_nonblank(batch_id, "acquisition batch ID")
    if type(data_root) is not type(Path.cwd()):
        raise MassiveDailyMarketDataRealE2EError("data root Path authority")
    _require_nonblank(created_by, "created_by")
    _require_nonblank(license_notes, "license notes")
    return MassiveDailyMarketDataRealE2EConfig(
        expected_repository_commit=commit,
        acquisition_batch_id=batch_id,
        data_root=data_root,
        created_by=created_by,
        license_notes=license_notes,
    )


def _require_nonblank(value: object, field: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise MassiveDailyMarketDataRealE2EError(field)
    _require_display_safe(value, field)
    return value


def _require_display_safe(value: str, field: str) -> None:
    if any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in value
    ):
        raise MassiveDailyMarketDataRealE2EError(field)


def _validate_repository_root(repository_root: Path) -> Path:
    if type(repository_root) is not type(Path.cwd()):
        raise MassiveDailyMarketDataRealE2EError("repository root Path authority")
    if not repository_root.is_absolute() or repository_root.is_symlink():
        raise MassiveDailyMarketDataRealE2EError("repository root path safety")
    resolved: object = _FAILED
    try:
        resolved = repository_root.resolve(strict=True)
    except OSError:
        pass
    if type(resolved) is not type(Path.cwd()) or not resolved.is_dir():
        raise MassiveDailyMarketDataRealE2EError("repository root resolution")
    _require_display_safe(str(resolved), "repository root display authority")
    return resolved


def _validate_external_data_root(data_root: Path, *, repository_root: Path) -> Path:
    if not data_root.is_absolute() or data_root.is_symlink():
        raise MassiveDailyMarketDataRealE2EError("external data root path safety")
    resolved: object = _FAILED
    try:
        resolved = data_root.resolve(strict=True)
    except OSError:
        pass
    if type(resolved) is not type(Path.cwd()) or not resolved.is_dir():
        raise MassiveDailyMarketDataRealE2EError("external data root resolution")
    _require_display_safe(str(resolved), "external data root display authority")
    if (
        resolved == repository_root
        or resolved.is_relative_to(repository_root)
        or repository_root.is_relative_to(resolved)
    ):
        raise MassiveDailyMarketDataRealE2EError(
            "external data root must be separate from the repository hierarchy"
        )
    if not os.access(resolved, os.R_OK | os.W_OK | os.X_OK):
        raise MassiveDailyMarketDataRealE2EError("external data root access")
    return resolved


def _validate_managed_location(path: Path, context: str) -> None:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise MassiveDailyMarketDataRealE2EError(context)


def _capture_git_state(repository_root: Path) -> _GitState:
    shown_root = _git(repository_root, "rev-parse", "--show-toplevel")
    branch = _git(repository_root, "branch", "--show-current")
    head = _git(repository_root, "rev-parse", "HEAD")
    main = _git(repository_root, "rev-parse", "main")
    origin_main = _git(repository_root, "rev-parse", "origin/main")
    porcelain = _git(repository_root, "status", "--porcelain=v1")
    root: object = _FAILED
    try:
        root = Path(shown_root).resolve(strict=True)
    except OSError:
        pass
    if type(root) is not type(Path.cwd()):
        raise MassiveDailyMarketDataRealE2EError("Git repository root authority")
    return _GitState(
        repository_root=root,
        branch=branch,
        head=head,
        main=main,
        origin_main=origin_main,
        clean=porcelain == "",
    )


def _git(repository_root: Path, *arguments: str) -> str:
    completed: object = _FAILED
    try:
        completed = subprocess.run(
            ("git", "-C", str(repository_root), *arguments),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            shell=False,
        )
    except (OSError, UnicodeError):
        pass
    if type(completed) is not subprocess.CompletedProcess:
        raise MassiveDailyMarketDataRealE2EError("read-only Git command")
    if type(completed.returncode) is not int or completed.returncode != 0:
        raise MassiveDailyMarketDataRealE2EError("read-only Git command")
    if type(completed.stdout) is not str:
        raise MassiveDailyMarketDataRealE2EError("read-only Git output")
    if completed.stdout.endswith("\n"):
        return completed.stdout[:-1]
    return completed.stdout


def _validate_git_gate(*, repository_root: Path, expected_commit: str) -> None:
    git_state = _capture_git_state(repository_root)
    if git_state.repository_root != repository_root:
        raise MassiveDailyMarketDataRealE2EError("Git checkout authority")
    if git_state.branch != "main":
        raise MassiveDailyMarketDataRealE2EError("Git branch must be main")
    if not git_state.clean:
        raise MassiveDailyMarketDataRealE2EError("Git worktree must be clean")
    if not (
        git_state.head == git_state.main == git_state.origin_main == expected_commit
    ):
        raise MassiveDailyMarketDataRealE2EError("Git commit authority")


def _validate_expected_sessions(
    expected_sessions: DailyMarketDataExpectedSessions,
    expected_hash: str,
) -> None:
    if type(expected_sessions) is not DailyMarketDataExpectedSessions:
        raise MassiveDailyMarketDataRealE2EError("expected-session authority")
    sessions = expected_sessions.session_dates
    if (
        type(sessions) is not tuple
        or any(type(session) is not date for session in sessions)
        or len(sessions) != MASSIVE_REAL_E2E_EXPECTED_SESSION_COUNT
        or sessions[0] != MASSIVE_REAL_E2E_START_DATE
        or sessions[-1] != MASSIVE_REAL_E2E_END_DATE
        or type(expected_sessions.session_source_id) is not str
        or expected_sessions.session_source_id != US_EQUITY_DAILY_SESSION_SOURCE_ID
        or type(expected_sessions.session_source_version) is not str
        or expected_sessions.session_source_version
        != US_EQUITY_DAILY_SESSION_SOURCE_VERSION
        or type(expected_sessions.calendar) is not str
        or expected_sessions.calendar != US_EQUITY_DAILY_SESSION_CALENDAR
        or type(expected_sessions.timezone) is not str
        or expected_sessions.timezone != US_EQUITY_DAILY_SESSION_TIMEZONE
        or type(expected_hash) is not str
        or expected_hash != MASSIVE_REAL_E2E_EXPECTED_SESSION_HASH
    ):
        raise MassiveDailyMarketDataRealE2EError("expected-session authority")


def _approval_payload(
    *,
    config: MassiveDailyMarketDataRealE2EConfig,
    repository_root: Path,
    source_directory: Path,
    snapshot_directory: Path,
    asset_plan: MassiveDailyMarketDataInstrumentAcquisitionPlan,
    benchmark_plan: MassiveDailyMarketDataInstrumentAcquisitionPlan,
    expected_sessions: DailyMarketDataExpectedSessions,
    expected_sessions_hash: str,
    policy: DailyMarketDataPolicy,
    policy_hash: str,
    research_profile: DailyMarketDataResearchProfile,
    research_profile_hash: str,
) -> dict[str, Any]:
    return {
        "domain": MASSIVE_REAL_E2E_APPROVAL_DOMAIN,
        "operator_version": MASSIVE_REAL_E2E_OPERATOR_VERSION,
        "expected_repository_commit": config.expected_repository_commit,
        "repository_root": str(repository_root),
        "provider": MASSIVE_PROVIDER,
        "source_family": MASSIVE_SOURCE_FAMILY,
        "fixed_host": MASSIVE_REAL_E2E_FIXED_HOST,
        "currency": MASSIVE_REAL_E2E_CURRENCY,
        "start_date": MASSIVE_REAL_E2E_START_DATE.isoformat(),
        "end_date": MASSIVE_REAL_E2E_END_DATE.isoformat(),
        "asset_plan": _plan_payload(asset_plan),
        "benchmark_plan": _plan_payload(benchmark_plan),
        "network_policy": _build_operational_network_policy(),
        "acquisition_batch_id": config.acquisition_batch_id,
        "expected_sessions": expected_sessions.model_dump(mode="json"),
        "expected_sessions_hash": expected_sessions_hash,
        "data_root": str(config.data_root),
        "source_capture_managed_directory": str(source_directory),
        "snapshot_managed_directory": str(snapshot_directory),
        "policy": policy.model_dump(mode="json"),
        "policy_hash": policy_hash,
        "research_profile": research_profile.model_dump(mode="json"),
        "research_profile_hash": research_profile_hash,
        "created_by": config.created_by,
        "license_notes": config.license_notes,
        "context_limitations": _CONTEXT_LIMITATIONS,
        "confirmation_phrases": (
            MASSIVE_REAL_E2E_ENTITLEMENT_CONFIRMATION,
            MASSIVE_REAL_E2E_ACQUISITION_CONFIRMATION,
        ),
    }


def _plan_payload(
    plan: MassiveDailyMarketDataInstrumentAcquisitionPlan,
) -> dict[str, Any]:
    return {
        "instrument": plan.instrument.model_dump(mode="json"),
        "start_date": plan.start_date.isoformat(),
        "end_date": plan.end_date.isoformat(),
        "acquisition_batch_id": plan.acquisition_batch_id,
        "requests": tuple(
            {
                "role": request.role.value,
                "path": request.path,
                "query_parameters": request.query_parameters,
                "request_parameters": request.request_parameters,
                "requested_scope": request.requested_scope,
                "sanitized_source_reference": request.sanitized_source_reference,
                "response_size_limit_bytes": request.response_size_limit_bytes,
            }
            for request in plan.requests
        ),
    }


def _approval_fingerprint(payload: Mapping[str, Any]) -> str:
    rendered = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    encoded = f"{rendered}\n".encode("utf-8", errors="strict")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _rebuild_preflight(
    preflight: MassiveDailyMarketDataRealE2EPreflight,
) -> MassiveDailyMarketDataRealE2EPreflight:
    if type(preflight) is not MassiveDailyMarketDataRealE2EPreflight:
        raise MassiveDailyMarketDataRealE2EError("preflight object authority")
    config = preflight.config
    repository_root = preflight.repository_root
    supplied_fingerprint = preflight.approval_fingerprint
    canonical = build_massive_daily_market_data_real_e2e_preflight(
        config=config,
        repository_root=repository_root,
    )
    if (
        type(supplied_fingerprint) is not str
        or supplied_fingerprint != canonical.approval_fingerprint
    ):
        raise MassiveDailyMarketDataRealE2EError("preflight fingerprint authority")
    return canonical


def _require_fingerprint(value: object) -> str:
    if type(value) is not str or _APPROVAL_FINGERPRINT_PATTERN.fullmatch(value) is None:
        raise MassiveDailyMarketDataRealE2EError("approved fingerprint syntax")
    return value


def _revalidate_downstream_authority(
    preflight: MassiveDailyMarketDataRealE2EPreflight,
) -> None:
    sessions = derive_us_equity_daily_expected_sessions(
        start_date=MASSIVE_REAL_E2E_START_DATE,
        end_date=MASSIVE_REAL_E2E_END_DATE,
    )
    sessions_hash = derive_daily_market_data_expected_sessions_hash(sessions)
    _validate_expected_sessions(sessions, sessions_hash)
    if sessions != preflight.expected_sessions:
        raise MassiveDailyMarketDataRealE2EError("rederived expected sessions")
    if preflight.policy != _build_policy():
        raise MassiveDailyMarketDataRealE2EError("rederived policy authority")
    if preflight.research_profile != _build_research_profile():
        raise MassiveDailyMarketDataRealE2EError("rederived research profile authority")
    policy_hash = derive_daily_market_data_policy_hash(preflight.policy)
    if not (policy_hash == preflight.policy_hash == MASSIVE_REAL_E2E_POLICY_HASH):
        raise MassiveDailyMarketDataRealE2EError("rederived policy hash")
    profile_hash = derive_daily_market_data_research_profile_hash(
        preflight.research_profile
    )
    if not (
        profile_hash
        == preflight.research_profile_hash
        == MASSIVE_REAL_E2E_RESEARCH_PROFILE_HASH
    ):
        raise MassiveDailyMarketDataRealE2EError("rederived research profile hash")


def _attempt_acquisition(
    *,
    preflight: MassiveDailyMarketDataRealE2EPreflight,
    credential: MassiveApiCredential,
    transport: MassiveDailyMarketDataHttpTransport | None,
    clock: Callable[[], datetime],
) -> _AcquisitionAttempt:
    secret: str | None = None
    try:
        secret = _stage_value(
            _attempt(lambda: _capture_credential(credential)),
            "runtime credential authority",
        )
        _require_credential_absent_from_preflight(secret, preflight)
        execution_credential = _stage_value(
            _attempt_credential_isolation(secret),
            "runtime credential isolation",
        )
        value = acquire_and_plan_massive_daily_market_data_source_capture_pair(
            asset_plan=preflight.asset_plan,
            benchmark_plan=preflight.benchmark_plan,
            credential=execution_credential,
            transport=transport,
            clock=clock,
        )
    except MassiveDailyMarketDataAcquisitionError as error:
        safe_reason = _capture_safe_acquisition_reason(error)
        if safe_reason is not None and secret is not None and secret in safe_reason:
            safe_reason = None
        result = _AcquisitionAttempt(
            succeeded=False,
            value=_FAILED,
            safe_reason=safe_reason,
        )
    except Exception:
        result = _AcquisitionAttempt(
            succeeded=False,
            value=_FAILED,
            safe_reason=None,
        )
    else:
        result = _AcquisitionAttempt(succeeded=True, value=value, safe_reason=None)
    del secret
    return result


def _capture_safe_acquisition_reason(
    error: MassiveDailyMarketDataAcquisitionError,
) -> str | None:
    if type(error) not in {
        MassiveDailyMarketDataAcquisitionError,
        MassiveDailyMarketDataResponseError,
        MassiveDailyMarketDataTransportError,
    }:
        return None
    arguments = error.args
    if (
        type(arguments) is not tuple
        or len(arguments) != 1
        or type(arguments[0]) is not str
    ):
        return None
    return arguments[0]


def _acquisition_stage_value(
    attempted: _AcquisitionAttempt,
) -> PlannedMassiveDailyMarketDataSourceCapturePair:
    if attempted.succeeded and type(attempted.value) is (
        PlannedMassiveDailyMarketDataSourceCapturePair
    ):
        return attempted.value
    stage = "Massive six-request acquisition"
    if attempted.safe_reason is not None:
        stage = f"{stage} (reason: {attempted.safe_reason})"
    raise MassiveDailyMarketDataRealE2EError(stage) from None


def _attempt_credential_isolation(secret: str) -> _Attempt[MassiveApiCredential]:
    return _attempt(lambda: MassiveApiCredential(secret))


def _require_credential_absent_from_preflight(
    secret: str,
    preflight: MassiveDailyMarketDataRealE2EPreflight,
) -> None:
    payload = _approval_payload(
        config=preflight.config,
        repository_root=preflight.repository_root,
        source_directory=preflight.source_capture_managed_directory,
        snapshot_directory=preflight.snapshot_managed_directory,
        asset_plan=preflight.asset_plan,
        benchmark_plan=preflight.benchmark_plan,
        expected_sessions=preflight.expected_sessions,
        expected_sessions_hash=preflight.expected_sessions_hash,
        policy=preflight.policy,
        policy_hash=preflight.policy_hash,
        research_profile=preflight.research_profile,
        research_profile_hash=preflight.research_profile_hash,
    )
    rendered = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    if secret in rendered:
        raise MassiveDailyMarketDataRealE2EError(
            "credential must not appear in approved persistent operation facts"
        )


def _capture_snapshot_file_map(
    files: object,
    stage: str,
    *,
    durable_artifacts: tuple[str, ...] = (),
) -> tuple[tuple[str, bytes], ...]:
    if type(files) is not dict:
        raise MassiveDailyMarketDataRealE2EError(
            stage,
            durable_artifacts=durable_artifacts,
        )
    captured: list[tuple[str, bytes]] = []
    for relative_path, content in files.items():
        if type(relative_path) is not str or type(content) is not bytes:
            raise MassiveDailyMarketDataRealE2EError(
                stage,
                durable_artifacts=durable_artifacts,
            )
        captured.append((relative_path, content))
    return tuple(sorted(captured))


def _adapt(
    capture: VerifiedDailyMarketDataSourceCapture,
    instrument: DailyMarketDataInstrument,
    stage: str,
    *,
    durable_artifacts: tuple[str, ...] = (),
) -> AdaptedMassiveDailyMarketData:
    return _stage_value(
        _attempt(
            lambda: adapt_massive_daily_market_data_source_capture(
                source_capture=capture,
                context=MassiveDailyMarketDataAdapterContext(
                    instrument=instrument,
                    currency=MASSIVE_REAL_E2E_CURRENCY,
                ),
            )
        ),
        stage,
        durable_artifacts=durable_artifacts,
    )


def _attempt[T](operation: Callable[[], T]) -> _Attempt[T]:
    try:
        return _Attempt(succeeded=True, value=operation())
    except Exception:
        return _Attempt(succeeded=False, value=_FAILED)


def _stage_value[T](
    attempted: _Attempt[T],
    stage: str,
    *,
    durable_artifacts: tuple[str, ...] = (),
) -> T:
    if not attempted.succeeded or attempted.value is _FAILED:
        raise MassiveDailyMarketDataRealE2EError(
            stage,
            durable_artifacts=durable_artifacts,
        ) from None
    return attempted.value  # type: ignore[return-value]


def _stage_none(
    attempted: _Attempt[None],
    stage: str,
    *,
    durable_artifacts: tuple[str, ...] = (),
) -> None:
    _stage_value(attempted, stage, durable_artifacts=durable_artifacts)


def _read_clock(
    clock: Callable[[], datetime],
    stage: str,
    *,
    durable_artifacts: tuple[str, ...] = (),
) -> datetime:
    value = _stage_value(
        _attempt(clock),
        stage,
        durable_artifacts=durable_artifacts,
    )
    return _require_exact_utc(value, stage, durable_artifacts=durable_artifacts)


def _require_exact_utc(
    value: object,
    stage: str,
    *,
    durable_artifacts: tuple[str, ...] = (),
) -> datetime:
    if type(value) is not datetime or value.tzinfo is not UTC:
        raise MassiveDailyMarketDataRealE2EError(
            stage,
            durable_artifacts=durable_artifacts,
        )
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise MassiveDailyMarketDataRealE2EError(
            stage,
            durable_artifacts=durable_artifacts,
        )
    return value


def _require_capture_before(
    capture: VerifiedDailyMarketDataSourceCapture,
    timestamp: datetime,
    stage: str,
) -> None:
    if capture.capture_manifest.capture_observed_at > timestamp:
        raise MassiveDailyMarketDataRealE2EError(stage)


def _source_artifact(
    label: str,
    publication: LocalDailyMarketDataSourceCapturePublication,
) -> str:
    return f"{label} source capture {publication.capture_id} at {publication.path}"


def _canonicalize_source_publication(
    publication: LocalDailyMarketDataSourceCapturePublication,
    preflight: MassiveDailyMarketDataRealE2EPreflight,
    label: str,
) -> tuple[
    LocalDailyMarketDataSourceCapturePublication,
    VerifiedDailyMarketDataSourceCapture,
]:
    if type(publication) is not LocalDailyMarketDataSourceCapturePublication:
        raise MassiveDailyMarketDataRealE2EError(
            f"prepared {label} publication authority"
        )
    capture_id = publication.capture_id
    path = publication.path
    status = publication.status
    if type(capture_id) is not str or type(path) is not type(Path.cwd()):
        raise MassiveDailyMarketDataRealE2EError(f"prepared {label} publication fields")
    if type(status) is not LocalDailyMarketDataSourceCapturePublicationStatus:
        raise MassiveDailyMarketDataRealE2EError(f"prepared {label} publication status")
    expected_path = preflight.source_capture_managed_directory / capture_id
    resolved: object = _FAILED
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        pass
    if type(resolved) is not type(Path.cwd()) or resolved != expected_path:
        raise MassiveDailyMarketDataRealE2EError(f"prepared {label} publication path")
    loaded = _stage_value(
        _attempt(
            lambda: load_local_daily_market_data_source_capture(
                source_capture_root=preflight.config.data_root,
                capture_id=capture_id,
            )
        ),
        f"prepared {label} source-capture readback",
    )
    return (
        LocalDailyMarketDataSourceCapturePublication(
            capture_id=capture_id,
            path=resolved,
            status=status,
            verified=loaded,
        ),
        loaded,
    )


def _instrument_summary(label: str, instrument: DailyMarketDataInstrument) -> str:
    return (
        f"{label}: instrument_id={instrument.instrument_id}; "
        f"symbol={instrument.symbol}; venue={instrument.venue}"
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "MASSIVE_REAL_E2E_ACQUISITION_CONFIRMATION",
    "MASSIVE_REAL_E2E_APPROVAL_DOMAIN",
    "MASSIVE_REAL_E2E_CURRENCY",
    "MASSIVE_REAL_E2E_END_DATE",
    "MASSIVE_REAL_E2E_ENTITLEMENT_CONFIRMATION",
    "MASSIVE_REAL_E2E_EXPECTED_SESSION_COUNT",
    "MASSIVE_REAL_E2E_EXPECTED_SESSION_HASH",
    "MASSIVE_REAL_E2E_FIXED_HOST",
    "MASSIVE_REAL_E2E_OPERATOR_VERSION",
    "MASSIVE_REAL_E2E_POLICY_HASH",
    "MASSIVE_REAL_E2E_RESEARCH_PROFILE_HASH",
    "MASSIVE_REAL_E2E_START_DATE",
    "MassiveDailyMarketDataRealE2EConfig",
    "MassiveDailyMarketDataRealE2EError",
    "MassiveDailyMarketDataRealE2EPreflight",
    "MassiveDailyMarketDataRealE2EPrepared",
    "build_massive_daily_market_data_real_e2e_preflight",
    "prepare_massive_daily_market_data_real_e2e",
    "render_massive_daily_market_data_real_e2e_preflight",
    "validate_massive_daily_market_data_real_e2e_prepared",
]
