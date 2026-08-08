"""Persisted-source coherence validation for research report cards."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from typing import Any, cast

from pydantic import BaseModel
from sqlalchemy import Table, select
from sqlalchemy.engine import Connection

from research_sdk.contracts import (
    DataSnapshotManifest,
    ExperimentRunRecord,
    ResearchReportCard,
    RunArtifactManifest,
)
from research_sdk.contracts.artifacts import REQUIRED_ARTIFACT_SPECS
from research_sdk.contracts.enums import (
    ArtifactKind,
    DataSnapshotStatus,
    ExperimentRunStatus,
)
from research_sdk.persistence.errors import (
    PersistenceCorruptionError,
    PersistenceErrorContext,
    ResearchReportCardSourceCoherenceError,
)
from research_sdk.persistence.hashing import contract_sha256
from research_sdk.persistence.mappers import (
    data_snapshot_manifest_to_row,
    experiment_run_to_row,
    run_artifact_manifest_to_rows,
)
from research_sdk.persistence.tables import (
    data_snapshot_manifests,
    experiment_runs,
    run_artifact_manifests,
)

_APPROVED_REPORT_CARD_METRIC_KEYS = frozenset(
    {
        "total_return",
        "benchmark_total_return",
        "excess_return",
        "maximum_drawdown",
        "realized_commission",
        "realized_slippage",
        "ending_equity",
        "number_of_trades",
        "observation_count",
    }
)


def validate_research_report_card_sources(
    *,
    connection: Connection,
    report_card: ResearchReportCard,
) -> None:
    """Verify that a report card faithfully summarizes persisted source rows."""

    run = _load_experiment_run(connection=connection, report_card=report_card)
    data_snapshot = _load_data_snapshot(connection=connection, report_card=report_card)
    benchmark_snapshot = _load_benchmark_snapshot(
        connection=connection,
        report_card=report_card,
    )
    artifact_manifest = _load_artifact_manifest(
        connection=connection,
        report_card=report_card,
    )

    _validate_run_coherence(report_card=report_card, run=run)
    _validate_data_snapshot_coherence(
        report_card=report_card,
        data_snapshot=data_snapshot,
    )
    _validate_benchmark_snapshot_coherence(
        report_card=report_card,
        benchmark_snapshot=benchmark_snapshot,
    )
    _validate_artifact_manifest_coherence(
        report_card=report_card,
        run=run,
        artifact_manifest=artifact_manifest,
    )


def _load_experiment_run(
    *,
    connection: Connection,
    report_card: ResearchReportCard,
) -> ExperimentRunRecord:
    row = _load_required_row(
        connection=connection,
        table=experiment_runs,
        identity_column_name="run_id",
        identity_value=report_card.source_run_id,
        report_card=report_card,
    )
    return _validate_stored_contract(
        row=row,
        contract_type=ExperimentRunRecord,
        table_name="experiment_runs",
        identity_column_name="run_id",
        identity_value=report_card.source_run_id,
        expected_row=experiment_run_to_row,
        report_card=report_card,
    )


def _load_data_snapshot(
    *,
    connection: Connection,
    report_card: ResearchReportCard,
) -> DataSnapshotManifest:
    snapshot_id = report_card.lineage.data_snapshot_id
    row = _load_required_row(
        connection=connection,
        table=data_snapshot_manifests,
        identity_column_name="snapshot_id",
        identity_value=snapshot_id,
        report_card=report_card,
    )
    return _validate_stored_contract(
        row=row,
        contract_type=DataSnapshotManifest,
        table_name="data_snapshot_manifests",
        identity_column_name="snapshot_id",
        identity_value=snapshot_id,
        expected_row=data_snapshot_manifest_to_row,
        report_card=report_card,
    )


def _load_benchmark_snapshot(
    *,
    connection: Connection,
    report_card: ResearchReportCard,
) -> DataSnapshotManifest:
    snapshot_id = report_card.lineage.benchmark_snapshot_id
    row = _load_required_row(
        connection=connection,
        table=data_snapshot_manifests,
        identity_column_name="snapshot_id",
        identity_value=snapshot_id,
        report_card=report_card,
    )
    return _validate_stored_contract(
        row=row,
        contract_type=DataSnapshotManifest,
        table_name="data_snapshot_manifests",
        identity_column_name="snapshot_id",
        identity_value=snapshot_id,
        expected_row=data_snapshot_manifest_to_row,
        report_card=report_card,
    )


def _load_artifact_manifest(
    *,
    connection: Connection,
    report_card: ResearchReportCard,
) -> RunArtifactManifest:
    manifest_id = report_card.lineage.artifact_manifest_id
    row = _load_required_row(
        connection=connection,
        table=run_artifact_manifests,
        identity_column_name="manifest_id",
        identity_value=manifest_id,
        report_card=report_card,
    )
    return _validate_stored_contract(
        row=row,
        contract_type=RunArtifactManifest,
        table_name="run_artifact_manifests",
        identity_column_name="manifest_id",
        identity_value=manifest_id,
        expected_row=lambda contract: (
            run_artifact_manifest_to_rows(
                manifest_id=manifest_id,
                manifest=contract,
            ).manifest
        ),
        report_card=report_card,
    )


def _load_required_row(
    *,
    connection: Connection,
    table: Table,
    identity_column_name: str,
    identity_value: str,
    report_card: ResearchReportCard,
) -> Mapping[str, Any]:
    result = connection.execute(
        select(table).where(table.c[identity_column_name] == identity_value)
    )
    row = result.mappings().one_or_none()
    if row is None:
        _raise_source_coherence_error(report_card)
    return cast("Mapping[str, Any]", row)


def _validate_stored_contract[ContractT: BaseModel](
    *,
    row: Mapping[str, Any],
    contract_type: type[ContractT],
    table_name: str,
    identity_column_name: str,
    identity_value: str,
    expected_row: Callable[[ContractT], Mapping[str, Any]],
    report_card: ResearchReportCard,
) -> ContractT:
    try:
        contract = contract_type.model_validate(row["raw_contract"])
        if row["contract_hash"] != contract_sha256(contract):
            _raise_source_corruption_error(report_card, table_name=table_name)
        if (
            hasattr(contract, identity_column_name)
            and getattr(contract, identity_column_name) != identity_value
        ):
            _raise_source_corruption_error(report_card, table_name=table_name)
        if row[identity_column_name] != identity_value:
            _raise_source_corruption_error(report_card, table_name=table_name)

        expected = expected_row(contract)
        for column_name, expected_value in expected.items():
            if column_name in {"contract_hash", "raw_contract"}:
                continue
            if not _stored_values_match(row[column_name], expected_value):
                _raise_source_corruption_error(report_card, table_name=table_name)
    except PersistenceCorruptionError:
        raise
    except Exception as exc:
        raise PersistenceCorruptionError(
            _context(report_card=report_card, table_name=table_name)
        ) from exc
    return contract


def _validate_run_coherence(
    *,
    report_card: ResearchReportCard,
    run: ExperimentRunRecord,
) -> None:
    lineage = report_card.lineage
    scope = report_card.research_scope
    assumptions = report_card.assumptions

    _require_coherent(report_card.source_run_id == run.run_id, report_card)
    _require_coherent(report_card.experiment_id == run.experiment_id, report_card)
    _require_coherent(lineage.strategy_id == run.strategy_id, report_card)
    _require_coherent(lineage.strategy_version == run.strategy_version, report_card)
    _require_coherent(lineage.engine_version == run.engine_version, report_card)
    _require_coherent(lineage.git_commit_sha == run.git_commit_sha, report_card)
    _require_coherent(lineage.data_snapshot_id == run.data_snapshot_id, report_card)
    _require_coherent(
        lineage.benchmark_snapshot_id == run.benchmark.snapshot_id,
        report_card,
    )
    _require_coherent(lineage.config_hash == run.config_hash, report_card)
    _require_coherent(lineage.parameter_hash == run.parameter_hash, report_card)
    _require_coherent(
        lineage.artifact_manifest_hash == run.artifact_manifest_hash,
        report_card,
    )
    _require_coherent(run.status is ExperimentRunStatus.COMPLETED, report_card)
    _require_coherent(not run.artifacts_incomplete, report_card)
    _require_coherent(scope.asset_class == run.asset_class, report_card)
    _require_coherent(scope.asset_universe == run.asset_universe, report_card)
    _require_coherent(scope.benchmark_id == run.benchmark.benchmark_id, report_card)
    _require_coherent(scope.frequency == run.frequency, report_card)
    _require_coherent(scope.start_date == run.time_range.start_date, report_card)
    _require_coherent(scope.end_date == run.time_range.end_date, report_card)
    _require_coherent(scope.source_run_status == run.status, report_card)
    _require_coherent(assumptions.cost_model == run.cost_model, report_card)
    _require_coherent(assumptions.slippage_model == run.slippage_model, report_card)
    _require_coherent(assumptions.lookback == run.lookback, report_card)
    _require_coherent(assumptions.lag_assumptions == run.lag_assumptions, report_card)
    _require_coherent(assumptions.leakage_review == run.leakage_review, report_card)
    _require_coherent(assumptions.random_seed == run.random_seed, report_card)
    _validate_metrics_coherence(report_card=report_card, run=run)


def _validate_metrics_coherence(
    *,
    report_card: ResearchReportCard,
    run: ExperimentRunRecord,
) -> None:
    _require_coherent(
        set(run.metrics_summary) == _APPROVED_REPORT_CARD_METRIC_KEYS,
        report_card,
    )
    report_card_metrics = report_card.metrics.model_dump(mode="json")
    _require_coherent(
        set(report_card_metrics) == _APPROVED_REPORT_CARD_METRIC_KEYS,
        report_card,
    )
    for metric_name in sorted(_APPROVED_REPORT_CARD_METRIC_KEYS):
        _require_coherent(
            report_card_metrics[metric_name] == run.metrics_summary[metric_name],
            report_card,
        )


def _validate_data_snapshot_coherence(
    *,
    report_card: ResearchReportCard,
    data_snapshot: DataSnapshotManifest,
) -> None:
    lineage = report_card.lineage
    scope = report_card.research_scope
    assumptions = report_card.assumptions

    _require_coherent(
        lineage.data_snapshot_id == data_snapshot.snapshot_id, report_card
    )
    _require_coherent(data_snapshot.status is DataSnapshotStatus.COMPLETED, report_card)
    _require_coherent(
        lineage.data_snapshot_content_hash == data_snapshot.content_hash,
        report_card,
    )
    _require_coherent(scope.asset_class == data_snapshot.asset_class, report_card)
    _require_coherent(scope.frequency == data_snapshot.frequency, report_card)
    _require_date_range_covered(
        report_card=report_card,
        start_date=data_snapshot.time_range.start_date,
        end_date=data_snapshot.time_range.end_date,
    )
    _require_coherent(
        assumptions.adjustment_policy == data_snapshot.adjustment_policy,
        report_card,
    )
    _require_coherent(
        assumptions.temporal_coverage == data_snapshot.temporal_coverage,
        report_card,
    )
    _require_coherent(
        assumptions.corporate_action_policy == data_snapshot.corporate_action_policy,
        report_card,
    )
    _require_coherent(
        assumptions.survivorship_policy == data_snapshot.survivorship_policy,
        report_card,
    )
    _require_coherent(
        assumptions.universe_membership_policy
        == data_snapshot.universe_membership_policy,
        report_card,
    )
    _require_coherent(assumptions.calendar == data_snapshot.calendar, report_card)
    _require_coherent(assumptions.timezone == data_snapshot.timezone, report_card)
    _require_coherent(
        report_card.limitations.source_snapshot_known_limitations
        == data_snapshot.known_limitations,
        report_card,
    )


def _validate_benchmark_snapshot_coherence(
    *,
    report_card: ResearchReportCard,
    benchmark_snapshot: DataSnapshotManifest,
) -> None:
    lineage = report_card.lineage
    scope = report_card.research_scope

    _require_coherent(
        lineage.benchmark_snapshot_id == benchmark_snapshot.snapshot_id,
        report_card,
    )
    _require_coherent(
        benchmark_snapshot.status is DataSnapshotStatus.COMPLETED,
        report_card,
    )
    _require_coherent(
        lineage.benchmark_snapshot_content_hash == benchmark_snapshot.content_hash,
        report_card,
    )
    _require_coherent(scope.asset_class == benchmark_snapshot.asset_class, report_card)
    _require_coherent(scope.frequency == benchmark_snapshot.frequency, report_card)
    _require_date_range_covered(
        report_card=report_card,
        start_date=benchmark_snapshot.time_range.start_date,
        end_date=benchmark_snapshot.time_range.end_date,
    )


def _validate_artifact_manifest_coherence(
    *,
    report_card: ResearchReportCard,
    run: ExperimentRunRecord,
    artifact_manifest: RunArtifactManifest,
) -> None:
    lineage = report_card.lineage
    evidence = report_card.evidence

    _require_coherent(
        artifact_manifest.run_id == report_card.source_run_id, report_card
    )
    _require_coherent(
        artifact_manifest.experiment_id == report_card.experiment_id,
        report_card,
    )
    _require_coherent(
        artifact_manifest.artifact_root_uri == evidence.artifact_root_uri,
        report_card,
    )
    _require_coherent(artifact_manifest.required_artifacts_complete, report_card)
    _require_coherent(
        evidence.artifact_manifest_uri == run.artifact_manifest_uri,
        report_card,
    )
    _require_coherent(evidence.artifact_root_uri == run.artifact_uri, report_card)
    _require_coherent(
        lineage.artifact_manifest_hash == run.artifact_manifest_hash,
        report_card,
    )

    manifest_required_by_kind = {
        artifact.artifact_kind: artifact
        for artifact in artifact_manifest.artifacts
        if artifact.artifact_kind in REQUIRED_ARTIFACT_SPECS
    }
    report_entries_by_kind = {
        entry.artifact_kind: entry
        for entry in evidence.artifacts
        if entry.artifact_kind in REQUIRED_ARTIFACT_SPECS
    }
    _require_coherent(
        set(report_entries_by_kind) == set(REQUIRED_ARTIFACT_SPECS),
        report_card,
    )
    _require_coherent(
        set(manifest_required_by_kind) == set(REQUIRED_ARTIFACT_SPECS),
        report_card,
    )

    for artifact_kind in sorted(REQUIRED_ARTIFACT_SPECS, key=lambda kind: kind.value):
        report_entry = report_entries_by_kind[artifact_kind]
        manifest_entry = manifest_required_by_kind[artifact_kind]
        _require_coherent(
            report_entry.artifact_id == manifest_entry.artifact_id, report_card
        )
        _require_coherent(
            report_entry.artifact_kind == manifest_entry.artifact_kind, report_card
        )
        _require_coherent(report_entry.filename == manifest_entry.filename, report_card)
        _require_coherent(report_entry.uri == manifest_entry.uri, report_card)
        _require_coherent(report_entry.format == manifest_entry.format, report_card)
        _require_coherent(report_entry.status == manifest_entry.status, report_card)
        _require_coherent(
            report_entry.content_hash == manifest_entry.content_hash, report_card
        )
        _require_coherent(
            report_entry.size_bytes == manifest_entry.size_bytes, report_card
        )
        _require_coherent(
            report_entry.row_count == manifest_entry.row_count, report_card
        )
        _require_coherent(
            report_entry.validator_version == manifest_entry.validator_version,
            report_card,
        )

    config_entry = report_entries_by_kind[ArtifactKind.CONFIG]
    _require_coherent(config_entry.content_hash == run.config_hash, report_card)


def _require_date_range_covered(
    *,
    report_card: ResearchReportCard,
    start_date: date,
    end_date: date,
) -> None:
    scope = report_card.research_scope
    _require_coherent(start_date <= scope.start_date, report_card)
    _require_coherent(scope.end_date <= end_date, report_card)


def _require_coherent(condition: bool, report_card: ResearchReportCard) -> None:
    if not condition:
        _raise_source_coherence_error(report_card)


def _stored_values_match(stored_value: Any, expected_value: Any) -> bool:
    return bool(_normalize_stored_value(stored_value) == expected_value)


def _normalize_stored_value(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("stored datetime must be timezone-aware")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return value


def _raise_source_coherence_error(report_card: ResearchReportCard) -> None:
    raise ResearchReportCardSourceCoherenceError(
        _context(report_card=report_card, table_name="research_report_cards")
    )


def _raise_source_corruption_error(
    report_card: ResearchReportCard,
    *,
    table_name: str,
) -> None:
    raise PersistenceCorruptionError(
        _context(report_card=report_card, table_name=table_name)
    )


def _context(
    *,
    report_card: ResearchReportCard,
    table_name: str,
) -> PersistenceErrorContext:
    return PersistenceErrorContext(
        table_name=table_name,
        operation="validate_research_report_card_sources",
        logical_identity={"report_card_id": report_card.report_card_id},
    )


__all__ = ["validate_research_report_card_sources"]
