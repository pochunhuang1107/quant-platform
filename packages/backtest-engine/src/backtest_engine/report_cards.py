"""Build deterministic report-card evidence for the ETF baseline."""

from __future__ import annotations

from decimal import Decimal
from typing import Final, NoReturn

from backtest_engine.identity import (
    RUN_ID_PREFIX,
    SHA256_HEX_LENGTH,
    canonical_json_bytes,
    file_sha256_bytes,
)
from research_sdk.contracts import (
    ArtifactKind,
    ArtifactStatus,
    AssetClass,
    DataAdjustmentPolicy,
    DataSnapshotKind,
    DataSnapshotManifest,
    DataSnapshotStatus,
    DataSourceType,
    ExperimentRunRecord,
    ExperimentRunStatus,
    ReportCardArtifactEvidenceEntry,
    ReportCardAssumptions,
    ReportCardEvidence,
    ReportCardLimitations,
    ReportCardLineage,
    ReportCardMetrics,
    ReportCardResearchScope,
    ReportCardUseRestriction,
    ResearchReportCard,
    RunArtifactEntry,
    RunArtifactManifest,
    TemporalCoverage,
)
from research_sdk.contracts.artifacts import REQUIRED_ARTIFACT_SPECS
from research_sdk.contracts.schema import RESEARCH_SDK_CONTRACT_SCHEMA_VERSION
from research_sdk.report_card_identity import (
    derive_research_report_card_id_from_fields,
)

REPORT_CARD_DERIVATION_POLICY_VERSION: Final = "deterministic-etf-report-card-v1"
SUPPORTED_STRATEGY_ID: Final = "strategies/etfs/qqq_buy_and_hold"
SUPPORTED_BENCHMARK_ID: Final = "SPY-gross-normalized"
SUPPORTED_FREQUENCY: Final = "daily"
SUPPORTED_SYMBOLS: Final = ("QQQ",)
SUPPORTED_SNAPSHOT_SYMBOLS: Final = ("QQQ", "SPY")

DECIMAL_METRIC_KEYS: Final = (
    "total_return",
    "benchmark_total_return",
    "excess_return",
    "maximum_drawdown",
    "realized_commission",
    "realized_slippage",
    "ending_equity",
)
COUNT_METRIC_KEYS: Final = ("number_of_trades", "observation_count")
APPROVED_METRIC_KEYS: Final = DECIMAL_METRIC_KEYS + COUNT_METRIC_KEYS
RATIO_METRIC_KEYS: Final = (
    "total_return",
    "benchmark_total_return",
    "excess_return",
    "maximum_drawdown",
)
MONEY_METRIC_KEYS: Final = (
    "realized_commission",
    "realized_slippage",
    "ending_equity",
)
SHA256_CONTENT_HASH_LENGTH: Final = len("sha256:") + SHA256_HEX_LENGTH

DETERMINISTIC_ETF_USE_RESTRICTIONS: Final = (
    ReportCardUseRestriction.RESEARCH_GENERATED_SYNTHETIC_DATA,
    ReportCardUseRestriction.INFRASTRUCTURE_VALIDATION_ONLY,
    ReportCardUseRestriction.NO_INVESTMENT_PERFORMANCE_CLAIM,
    ReportCardUseRestriction.NOT_PRODUCTION_DATA_RESEARCH,
    ReportCardUseRestriction.NOT_PAPER_TRADING_EVIDENCE,
    ReportCardUseRestriction.NOT_LIVE_TRADING_EVIDENCE,
)


class DeterministicETFReportCardError(ValueError):
    """Raised when deterministic ETF report-card inputs are invalid."""


def build_deterministic_etf_report_card(
    *,
    run: ExperimentRunRecord,
    data_snapshot: DataSnapshotManifest,
    benchmark_snapshot: DataSnapshotManifest,
    artifact_manifest_id: str,
    artifact_manifest: RunArtifactManifest,
) -> ResearchReportCard:
    """Build deterministic evidence for one completed ETF baseline run."""

    _validate_supported_inputs(
        run=run,
        data_snapshot=data_snapshot,
        benchmark_snapshot=benchmark_snapshot,
        artifact_manifest_id=artifact_manifest_id,
        artifact_manifest=artifact_manifest,
    )
    _validate_manifest_matches_run(run=run, artifact_manifest=artifact_manifest)
    metrics = _build_metrics(run)
    evidence = _build_evidence(run=run, artifact_manifest=artifact_manifest)
    report_card_id = _derive_report_card_id(
        run=run,
        data_snapshot=data_snapshot,
        benchmark_snapshot=benchmark_snapshot,
    )

    report_card = ResearchReportCard(
        schema_version=RESEARCH_SDK_CONTRACT_SCHEMA_VERSION,
        report_card_id=report_card_id,
        derivation_policy_version=REPORT_CARD_DERIVATION_POLICY_VERSION,
        source_run_id=run.run_id,
        experiment_id=run.experiment_id,
        lineage=ReportCardLineage(
            strategy_id=run.strategy_id,
            strategy_version=run.strategy_version,
            engine_version=run.engine_version,
            git_commit_sha=run.git_commit_sha,
            data_snapshot_id=run.data_snapshot_id,
            benchmark_snapshot_id=run.benchmark.snapshot_id,
            data_snapshot_content_hash=data_snapshot.content_hash,
            benchmark_snapshot_content_hash=benchmark_snapshot.content_hash,
            artifact_manifest_id=artifact_manifest_id,
            config_hash=run.config_hash,
            parameter_hash=run.parameter_hash,
            artifact_manifest_hash=run.artifact_manifest_hash,
        ),
        research_scope=ReportCardResearchScope(
            asset_class=run.asset_class,
            asset_universe=run.asset_universe,
            benchmark_id=run.benchmark.benchmark_id,
            frequency=run.frequency,
            start_date=run.time_range.start_date,
            end_date=run.time_range.end_date,
            observation_count=metrics.observation_count,
            source_run_status=run.status,
        ),
        assumptions=ReportCardAssumptions(
            cost_model=run.cost_model,
            slippage_model=run.slippage_model,
            lookback=run.lookback,
            lag_assumptions=run.lag_assumptions,
            leakage_review=run.leakage_review,
            random_seed=run.random_seed,
            adjustment_policy=data_snapshot.adjustment_policy,
            temporal_coverage=data_snapshot.temporal_coverage,
            corporate_action_policy=data_snapshot.corporate_action_policy,
            survivorship_policy=data_snapshot.survivorship_policy,
            universe_membership_policy=data_snapshot.universe_membership_policy,
            calendar=data_snapshot.calendar,
            timezone=data_snapshot.timezone,
        ),
        metrics=metrics,
        evidence=evidence,
        limitations=ReportCardLimitations(
            source_snapshot_known_limitations=data_snapshot.known_limitations
        ),
        use_restrictions=DETERMINISTIC_ETF_USE_RESTRICTIONS,
    )
    verify_deterministic_etf_report_card_identity(report_card)
    return report_card


def derive_deterministic_etf_report_card_id(
    *,
    run: ExperimentRunRecord,
    data_snapshot: DataSnapshotManifest,
    benchmark_snapshot: DataSnapshotManifest,
) -> str:
    """Return the deterministic report-card identity for immutable sources."""

    return _derive_report_card_id(
        run=run,
        data_snapshot=data_snapshot,
        benchmark_snapshot=benchmark_snapshot,
    )


def verify_deterministic_etf_report_card_identity(
    report_card: ResearchReportCard,
) -> None:
    """Verify a deterministic ETF report-card ID from durable card fields."""

    try:
        _validate_report_card_id(report_card.report_card_id)
        _validate_run_id(report_card.source_run_id)
        if (
            report_card.derivation_policy_version
            != REPORT_CARD_DERIVATION_POLICY_VERSION
        ):
            _report_card_error("unsupported report-card derivation policy")
        _validate_sha256_content_hash(
            report_card.lineage.data_snapshot_content_hash,
            "lineage.data_snapshot_content_hash",
        )
        _validate_sha256_content_hash(
            report_card.lineage.benchmark_snapshot_content_hash,
            "lineage.benchmark_snapshot_content_hash",
        )
        _validate_sha256_content_hash(
            report_card.lineage.config_hash,
            "lineage.config_hash",
        )
        _validate_sha256_content_hash(
            report_card.lineage.parameter_hash,
            "lineage.parameter_hash",
        )
        _validate_sha256_content_hash(
            report_card.lineage.artifact_manifest_hash,
            "lineage.artifact_manifest_hash",
        )
        expected = _derive_report_card_id_from_fields(
            source_run_id=report_card.source_run_id,
            schema_version=report_card.schema_version,
            derivation_policy_version=report_card.derivation_policy_version,
            data_snapshot_content_hash=(report_card.lineage.data_snapshot_content_hash),
            benchmark_snapshot_content_hash=(
                report_card.lineage.benchmark_snapshot_content_hash
            ),
            config_hash=report_card.lineage.config_hash,
            parameter_hash=report_card.lineage.parameter_hash,
            artifact_manifest_hash=report_card.lineage.artifact_manifest_hash,
        )
    except DeterministicETFReportCardError:
        raise
    except Exception as exc:
        raise DeterministicETFReportCardError(
            "report-card identity could not be verified"
        ) from exc
    if report_card.report_card_id != expected:
        _report_card_error("report-card identity is stale or inconsistent")


def _validate_supported_inputs(
    *,
    run: ExperimentRunRecord,
    data_snapshot: DataSnapshotManifest,
    benchmark_snapshot: DataSnapshotManifest,
    artifact_manifest_id: str,
    artifact_manifest: RunArtifactManifest,
) -> None:
    _validate_run_id(run.run_id)
    _validate_manifest_id(run_id=run.run_id, artifact_manifest_id=artifact_manifest_id)
    _validate_identity_hashes(
        run=run,
        data_snapshot=data_snapshot,
        benchmark_snapshot=benchmark_snapshot,
    )
    if run.status is not ExperimentRunStatus.COMPLETED:
        _report_card_error("report cards require completed experiment runs")
    if run.artifacts_incomplete:
        _report_card_error("report cards require complete run artifacts")
    if data_snapshot.status is not DataSnapshotStatus.COMPLETED:
        _report_card_error("data snapshot must be completed")
    if benchmark_snapshot.status is not DataSnapshotStatus.COMPLETED:
        _report_card_error("benchmark snapshot must be completed")
    if data_snapshot != benchmark_snapshot:
        _report_card_error(
            "deterministic ETF report-card v1 requires one shared synthetic "
            "QQQ/SPY data and benchmark snapshot"
        )
    if run.data_snapshot_id != data_snapshot.snapshot_id:
        _report_card_error("run data_snapshot_id must match data snapshot")
    if run.benchmark.snapshot_id != benchmark_snapshot.snapshot_id:
        _report_card_error("run benchmark snapshot_id must match benchmark snapshot")
    if data_snapshot.snapshot_id != run.benchmark.snapshot_id:
        _report_card_error("data snapshot must match run benchmark snapshot")
    if data_snapshot.source_type is not DataSourceType.RESEARCH_GENERATED:
        _report_card_error("data snapshot source_type must be research_generated")
    if data_snapshot.snapshot_kind is not DataSnapshotKind.MARKET_DATA:
        _report_card_error("data snapshot kind must be market_data")
    if data_snapshot.adjustment_policy is not DataAdjustmentPolicy.RAW:
        _report_card_error("data snapshot adjustment_policy must be raw")
    if data_snapshot.temporal_coverage is not TemporalCoverage.POINT_IN_TIME:
        _report_card_error("data snapshot temporal_coverage must be point_in_time")
    if artifact_manifest.run_id != run.run_id:
        _report_card_error("artifact manifest run_id must match run")
    if artifact_manifest.experiment_id != run.experiment_id:
        _report_card_error("artifact manifest experiment_id must match run")
    if not artifact_manifest.required_artifacts_complete:
        _report_card_error("artifact manifest must have complete required artifacts")
    if artifact_manifest.artifact_root_uri != run.artifact_uri:
        _report_card_error("artifact manifest root URI must match run artifact URI")
    expected_manifest_uri = (
        f"{artifact_manifest.artifact_root_uri}/artifact_manifest.json"
    )
    if run.artifact_manifest_uri != expected_manifest_uri:
        _report_card_error("run artifact_manifest_uri must match manifest root")
    if run.asset_class is not AssetClass.ETFS:
        _report_card_error("only ETF runs are supported by this report-card builder")
    if data_snapshot.asset_class is not run.asset_class:
        _report_card_error("data snapshot asset_class must match run")
    if benchmark_snapshot.asset_class is not run.asset_class:
        _report_card_error("benchmark snapshot asset_class must match run")
    if run.frequency != SUPPORTED_FREQUENCY:
        _report_card_error("only daily frequency is supported")
    if data_snapshot.frequency != run.frequency:
        _report_card_error("data snapshot frequency must match run")
    if benchmark_snapshot.frequency != run.frequency:
        _report_card_error("benchmark snapshot frequency must match run")
    if run.time_range.start_date < data_snapshot.time_range.start_date:
        _report_card_error("run start_date must be within data snapshot")
    if run.time_range.end_date > data_snapshot.time_range.end_date:
        _report_card_error("run end_date must be within data snapshot")
    if run.time_range.start_date < benchmark_snapshot.time_range.start_date:
        _report_card_error("run start_date must be within benchmark snapshot")
    if run.time_range.end_date > benchmark_snapshot.time_range.end_date:
        _report_card_error("run end_date must be within benchmark snapshot")
    if run.strategy_id != SUPPORTED_STRATEGY_ID:
        _report_card_error("unsupported strategy_id for deterministic ETF report card")
    if run.benchmark.benchmark_id != SUPPORTED_BENCHMARK_ID:
        _report_card_error("unsupported benchmark for deterministic ETF report card")
    if run.asset_universe.symbols != SUPPORTED_SYMBOLS:
        _report_card_error("deterministic ETF report card requires QQQ run symbol")
    if data_snapshot.asset_universe.symbols != SUPPORTED_SNAPSHOT_SYMBOLS:
        _report_card_error("data snapshot must contain QQQ and SPY")
    if benchmark_snapshot.asset_universe.symbols != SUPPORTED_SNAPSHOT_SYMBOLS:
        _report_card_error("benchmark snapshot must contain QQQ and SPY")
    _validate_required_artifacts(
        run=run,
        artifact_manifest=artifact_manifest,
        artifact_root_uri=artifact_manifest.artifact_root_uri,
    )


def _validate_required_artifacts(
    *,
    run: ExperimentRunRecord,
    artifact_manifest: RunArtifactManifest,
    artifact_root_uri: str,
) -> None:
    entries_by_kind = {
        entry.artifact_kind: entry
        for entry in artifact_manifest.artifacts
        if entry.artifact_kind in REQUIRED_ARTIFACT_SPECS
    }
    if set(entries_by_kind) != set(REQUIRED_ARTIFACT_SPECS):
        _report_card_error("artifact manifest must contain every required artifact")
    for kind, (filename, artifact_format) in REQUIRED_ARTIFACT_SPECS.items():
        entry = entries_by_kind[kind]
        if entry.filename != filename:
            _report_card_error("required artifact filename mismatch")
        if entry.uri != f"{artifact_root_uri}/{entry.filename}":
            _report_card_error("required artifact URI must match manifest root")
        if entry.format is not artifact_format:
            _report_card_error("required artifact format mismatch")
        if entry.status is not ArtifactStatus.PRODUCED:
            _report_card_error("required artifacts must be produced")
        if entry.content_hash is None or entry.size_bytes is None:
            _report_card_error("required artifacts need hash and size evidence")
        if kind is ArtifactKind.CONFIG and entry.content_hash != run.config_hash:
            _report_card_error("config artifact hash must match run config_hash")


def _build_metrics(run: ExperimentRunRecord) -> ReportCardMetrics:
    metric_keys = set(run.metrics_summary)
    if metric_keys != set(APPROVED_METRIC_KEYS):
        _report_card_error("run metrics_summary must contain exactly approved metrics")

    metric_values: dict[str, str | int] = {}
    for key in DECIMAL_METRIC_KEYS:
        value = run.metrics_summary[key]
        if not isinstance(value, str):
            _report_card_error(f"{key} must be a decimal string")
        _validate_decimal_metric(value, key)
        metric_values[key] = value
    for key in COUNT_METRIC_KEYS:
        value = run.metrics_summary[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            _report_card_error(f"{key} must be a nonnegative integer")
        metric_values[key] = value

    return ReportCardMetrics.model_validate(metric_values)


def _validate_decimal_metric(value: str, key: str) -> None:
    scale = 12 if key in RATIO_METRIC_KEYS else 6
    if not _has_canonical_decimal_shape(value=value, scale=scale):
        _report_card_error(f"{key} must use canonical fixed-point scale {scale}")
    try:
        parsed = Decimal(value)
    except Exception as exc:
        raise DeterministicETFReportCardError(
            f"{key} must be a finite fixed-point decimal string"
        ) from exc
    if not parsed.is_finite():
        _report_card_error(f"{key} must be a finite fixed-point decimal string")
    if value.startswith("-") and parsed == 0:
        _report_card_error(f"{key} must not use negative zero")
    if key in {"realized_commission", "realized_slippage", "ending_equity"}:
        if parsed < 0:
            _report_card_error(f"{key} must be nonnegative")
    if key == "maximum_drawdown" and parsed > 0:
        _report_card_error("maximum_drawdown must be less than or equal to zero")


def _has_canonical_decimal_shape(*, value: str, scale: int) -> bool:
    if "e" in value.lower() or value.startswith("+"):
        return False
    signless = value.removeprefix("-")
    integer, separator, fraction = signless.partition(".")
    if separator != "." or len(fraction) != scale:
        return False
    if not integer or not fraction.isdigit():
        return False
    if integer != "0" and integer.startswith("0"):
        return False
    return integer.isdigit()


def _build_evidence(
    *,
    run: ExperimentRunRecord,
    artifact_manifest: RunArtifactManifest,
) -> ReportCardEvidence:
    required_entries = [
        entry
        for entry in artifact_manifest.artifacts
        if entry.artifact_kind in REQUIRED_ARTIFACT_SPECS
    ]
    return ReportCardEvidence(
        artifact_root_uri=run.artifact_uri,
        artifact_manifest_uri=run.artifact_manifest_uri,
        required_artifacts_complete=artifact_manifest.required_artifacts_complete,
        artifacts=tuple(_evidence_entry(entry) for entry in required_entries),
    )


def _evidence_entry(entry: RunArtifactEntry) -> ReportCardArtifactEvidenceEntry:
    if entry.content_hash is None or entry.size_bytes is None:
        _report_card_error("produced artifact evidence requires hash and size")
    return ReportCardArtifactEvidenceEntry(
        artifact_id=entry.artifact_id,
        artifact_kind=entry.artifact_kind,
        filename=entry.filename,
        uri=entry.uri,
        format=entry.format,
        status=entry.status,
        content_hash=entry.content_hash,
        size_bytes=entry.size_bytes,
        row_count=entry.row_count,
        validator_version=entry.validator_version,
    )


def _derive_report_card_id(
    *,
    run: ExperimentRunRecord,
    data_snapshot: DataSnapshotManifest,
    benchmark_snapshot: DataSnapshotManifest,
) -> str:
    _validate_identity_sources(
        run=run,
        data_snapshot=data_snapshot,
        benchmark_snapshot=benchmark_snapshot,
    )
    return _derive_report_card_id_from_fields(
        source_run_id=run.run_id,
        schema_version=RESEARCH_SDK_CONTRACT_SCHEMA_VERSION,
        derivation_policy_version=REPORT_CARD_DERIVATION_POLICY_VERSION,
        data_snapshot_content_hash=data_snapshot.content_hash,
        benchmark_snapshot_content_hash=benchmark_snapshot.content_hash,
        config_hash=run.config_hash,
        parameter_hash=run.parameter_hash,
        artifact_manifest_hash=run.artifact_manifest_hash,
    )


def _derive_report_card_id_from_fields(
    *,
    source_run_id: str,
    schema_version: str,
    derivation_policy_version: str,
    data_snapshot_content_hash: str,
    benchmark_snapshot_content_hash: str,
    config_hash: str,
    parameter_hash: str,
    artifact_manifest_hash: str,
) -> str:
    return derive_research_report_card_id_from_fields(
        source_run_id=source_run_id,
        schema_version=schema_version,
        derivation_policy_version=derivation_policy_version,
        data_snapshot_content_hash=data_snapshot_content_hash,
        benchmark_snapshot_content_hash=benchmark_snapshot_content_hash,
        config_hash=config_hash,
        parameter_hash=parameter_hash,
        artifact_manifest_hash=artifact_manifest_hash,
    )


def _validate_identity_sources(
    *,
    run: ExperimentRunRecord,
    data_snapshot: DataSnapshotManifest,
    benchmark_snapshot: DataSnapshotManifest,
) -> None:
    _validate_run_id(run.run_id)
    _validate_identity_hashes(
        run=run,
        data_snapshot=data_snapshot,
        benchmark_snapshot=benchmark_snapshot,
    )
    if run.status is not ExperimentRunStatus.COMPLETED:
        _report_card_error("report-card identity requires completed experiment runs")
    if data_snapshot != benchmark_snapshot:
        _report_card_error(
            "deterministic ETF report-card v1 identity requires one shared snapshot"
        )
    if data_snapshot.snapshot_id != run.data_snapshot_id:
        _report_card_error("data snapshot must match run data_snapshot_id")
    if data_snapshot.snapshot_id != run.benchmark.snapshot_id:
        _report_card_error("data snapshot must match run benchmark snapshot_id")


def _validate_manifest_matches_run(
    *,
    run: ExperimentRunRecord,
    artifact_manifest: RunArtifactManifest,
) -> None:
    try:
        manifest_bytes = canonical_json_bytes(artifact_manifest)
        manifest_hash = f"sha256:{file_sha256_bytes(manifest_bytes)}"
    except Exception as exc:
        raise DeterministicETFReportCardError(
            "artifact manifest could not be serialized for report-card validation"
        ) from exc
    if manifest_hash != run.artifact_manifest_hash:
        _report_card_error(
            "artifact manifest hash must match run artifact_manifest_hash"
        )


def _validate_run_id(run_id: str) -> None:
    if not run_id.startswith(RUN_ID_PREFIX):
        _report_card_error("run_id must use the run- prefix")
    digest = run_id.removeprefix(RUN_ID_PREFIX)
    if len(digest) != SHA256_HEX_LENGTH:
        _report_card_error("run_id must contain a full SHA-256 digest")
    if digest.lower() != digest or not all(
        character in "0123456789abcdef" for character in digest
    ):
        _report_card_error("run_id digest must be lowercase hexadecimal")


def _validate_report_card_id(report_card_id: str) -> None:
    if not report_card_id.startswith("report-card-"):
        _report_card_error("report_card_id must use the report-card- prefix")
    digest = report_card_id.removeprefix("report-card-")
    if len(digest) != SHA256_HEX_LENGTH:
        _report_card_error("report_card_id must contain a full SHA-256 digest")
    if digest.lower() != digest or not all(
        character in "0123456789abcdef" for character in digest
    ):
        _report_card_error("report_card_id digest must be lowercase hexadecimal")


def _validate_manifest_id(*, run_id: str, artifact_manifest_id: str) -> None:
    expected = f"manifest-{run_id.removeprefix(RUN_ID_PREFIX)}"
    if artifact_manifest_id != expected:
        _report_card_error("artifact_manifest_id must be derived from run_id")


def _validate_identity_hashes(
    *,
    run: ExperimentRunRecord,
    data_snapshot: DataSnapshotManifest,
    benchmark_snapshot: DataSnapshotManifest,
) -> None:
    _validate_sha256_content_hash(
        data_snapshot.content_hash,
        "data_snapshot.content_hash",
    )
    _validate_sha256_content_hash(
        benchmark_snapshot.content_hash,
        "benchmark_snapshot.content_hash",
    )
    _validate_sha256_content_hash(run.config_hash, "run.config_hash")
    _validate_sha256_content_hash(run.parameter_hash, "run.parameter_hash")
    _validate_sha256_content_hash(
        run.artifact_manifest_hash,
        "run.artifact_manifest_hash",
    )


def _validate_sha256_content_hash(value: str, field_name: str) -> None:
    if len(value) != SHA256_CONTENT_HASH_LENGTH or not value.startswith("sha256:"):
        _report_card_error(f"{field_name} must use sha256:<64 lowercase hex>")
    digest = value.removeprefix("sha256:")
    if len(digest) != SHA256_HEX_LENGTH:
        _report_card_error(f"{field_name} must use sha256:<64 lowercase hex>")
    if digest.lower() != digest or not all(
        character in "0123456789abcdef" for character in digest
    ):
        _report_card_error(f"{field_name} must use sha256:<64 lowercase hex>")


def _report_card_error(message: str) -> NoReturn:
    raise DeterministicETFReportCardError(message)


__all__ = [
    "APPROVED_METRIC_KEYS",
    "DETERMINISTIC_ETF_USE_RESTRICTIONS",
    "REPORT_CARD_DERIVATION_POLICY_VERSION",
    "DeterministicETFReportCardError",
    "build_deterministic_etf_report_card",
    "derive_deterministic_etf_report_card_id",
    "verify_deterministic_etf_report_card_identity",
]
