from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.sql.dml import Insert
from sqlalchemy.sql.selectable import Select

from research_sdk.contracts import (
    ArtifactFormat,
    ArtifactStatus,
    DataSnapshotManifest,
    ExperimentRunRecord,
    HashAlgorithm,
    ReportCardArtifactEvidenceEntry,
    ResearchReportCard,
    RunArtifactEntry,
    RunArtifactManifest,
)
from research_sdk.contracts.enums import ArtifactKind, ExperimentRunStatus
from research_sdk.persistence.errors import (
    PersistenceCorruptionError,
    ResearchReportCardSourceCoherenceError,
)
from research_sdk.persistence.hashing import contract_sha256
from research_sdk.persistence.mappers import (
    data_snapshot_manifest_to_row,
    experiment_run_to_row,
    research_report_card_to_row,
    run_artifact_manifest_to_rows,
)
from research_sdk.persistence.sqlalchemy_repository import (
    SqlAlchemyExperimentLedgerRepository,
)
from research_sdk.report_card_identity import (
    derive_research_report_card_id_from_fields,
)
from test_deterministic_etf_report_card import mapped_records, report_card_from_records


class _FakeResult:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def mappings(self) -> _FakeResult:
        return self

    def one_or_none(self) -> dict[str, Any] | None:
        return self._row


class _FakeConnection:
    def __init__(self, rows: dict[str, dict[str, dict[str, Any]]]) -> None:
        self.rows = rows
        self.inserted_tables: list[str] = []

    def in_transaction(self) -> bool:
        return True

    def execute(self, statement: object) -> _FakeResult:
        if isinstance(statement, Insert):
            self.inserted_tables.append(statement.table.name)
            return _FakeResult(
                {
                    "report_card_id": statement.compile().params["report_card_id"],
                    "contract_hash": statement.compile().params["contract_hash"],
                    "inserted_at": datetime(2026, 8, 8, tzinfo=UTC),
                }
            )
        if isinstance(statement, Select):
            table_name = tuple(statement.get_final_froms())[0].name
            identity_value = next(iter(statement.compile().params.values()))
            return _FakeResult(self.rows.get(table_name, {}).get(identity_value))
        raise AssertionError(f"unexpected statement: {statement!r}")


@pytest.fixture
def source_fixture(tmp_path: Path) -> tuple[Any, ResearchReportCard]:
    records = mapped_records(tmp_path)
    return records, report_card_from_records(records)


@pytest.mark.parametrize(
    "case",
    [
        "changed_total_return",
        "changed_commission",
        "changed_observation_count",
        "wrong_experiment_id",
        "wrong_strategy_id",
        "wrong_strategy_version",
        "wrong_engine_version",
        "wrong_git_commit_sha",
        "wrong_config_hash",
        "wrong_parameter_hash",
        "unrelated_data_snapshot_id",
        "data_snapshot_content_hash_mismatch",
        "unrelated_benchmark_snapshot_id",
        "unrelated_artifact_manifest_id",
        "changed_artifact_evidence",
        "config_evidence_mismatch",
        "non_completed_source_run",
        "artifacts_incomplete_source_run",
    ],
)
def test_record_research_report_card_rejects_source_coherence_mismatch_before_insert(
    source_fixture: tuple[Any, ResearchReportCard],
    case: str,
) -> None:
    records, report_card = source_fixture
    rows = _source_rows(
        run=records.run,
        snapshot=records.snapshot,
        manifest_id=records.manifest_id,
        artifact_manifest=records.artifact_manifest,
    )
    candidate = _mismatched_report_card(
        case=case,
        report_card=report_card,
        records=records,
        rows=rows,
    )
    connection = _FakeConnection(rows)
    repository = SqlAlchemyExperimentLedgerRepository(connection)  # type: ignore[arg-type]

    with pytest.raises(ResearchReportCardSourceCoherenceError):
        repository.record_research_report_card(candidate)

    assert "research_report_cards" not in connection.inserted_tables


@pytest.mark.parametrize(
    ("table_name", "identity_value"),
    [
        ("experiment_runs", "run"),
        ("data_snapshot_manifests", "snapshot"),
        ("run_artifact_manifests", "manifest"),
    ],
)
def test_record_research_report_card_rejects_source_corruption_before_insert(
    source_fixture: tuple[Any, ResearchReportCard],
    table_name: str,
    identity_value: str,
) -> None:
    records, report_card = source_fixture
    rows = _source_rows(
        run=records.run,
        snapshot=records.snapshot,
        manifest_id=records.manifest_id,
        artifact_manifest=records.artifact_manifest,
    )
    identity = {
        "run": records.run.run_id,
        "snapshot": records.snapshot.snapshot_id,
        "manifest": records.manifest_id,
    }[identity_value]
    rows[table_name][identity] = {
        **rows[table_name][identity],
        "contract_hash": "0" * 64,
    }
    connection = _FakeConnection(rows)
    repository = SqlAlchemyExperimentLedgerRepository(connection)  # type: ignore[arg-type]

    with pytest.raises(PersistenceCorruptionError):
        repository.record_research_report_card(report_card)

    assert "research_report_cards" not in connection.inserted_tables


def test_record_research_report_card_rejects_optional_evidence_missing_from_manifest(
    source_fixture: tuple[Any, ResearchReportCard],
) -> None:
    records, report_card = source_fixture
    rows = _source_rows(
        run=records.run,
        snapshot=records.snapshot,
        manifest_id=records.manifest_id,
        artifact_manifest=records.artifact_manifest,
    )
    optional_entry = _optional_manifest_entry(report_card.evidence.artifact_root_uri)
    candidate = _with_evidence_artifacts(
        report_card,
        (
            *report_card.evidence.artifacts,
            _report_card_evidence_entry(optional_entry),
        ),
    )
    connection = _FakeConnection(rows)
    repository = SqlAlchemyExperimentLedgerRepository(connection)  # type: ignore[arg-type]

    with pytest.raises(ResearchReportCardSourceCoherenceError):
        repository.record_research_report_card(candidate)

    assert "research_report_cards" not in connection.inserted_tables


def test_record_research_report_card_rejects_optional_evidence_manifest_mismatch(
    source_fixture: tuple[Any, ResearchReportCard],
) -> None:
    records, report_card = source_fixture
    rows = _source_rows(
        run=records.run,
        snapshot=records.snapshot,
        manifest_id=records.manifest_id,
        artifact_manifest=records.artifact_manifest,
    )
    optional_entry = _optional_manifest_entry(report_card.evidence.artifact_root_uri)
    report_card = _add_optional_manifest_source(
        records=records,
        report_card=report_card,
        rows=rows,
        optional_entry=optional_entry,
    )
    mismatched_evidence = _report_card_evidence_entry(optional_entry).model_copy(
        update={"content_hash": f"sha256:{'b' * 64}"}
    )
    candidate = _with_evidence_artifacts(
        report_card,
        (*report_card.evidence.artifacts, mismatched_evidence),
    )
    connection = _FakeConnection(rows)
    repository = SqlAlchemyExperimentLedgerRepository(connection)  # type: ignore[arg-type]

    with pytest.raises(ResearchReportCardSourceCoherenceError):
        repository.record_research_report_card(candidate)

    assert "research_report_cards" not in connection.inserted_tables


def test_record_research_report_card_accepts_matching_optional_evidence(
    source_fixture: tuple[Any, ResearchReportCard],
) -> None:
    records, report_card = source_fixture
    rows = _source_rows(
        run=records.run,
        snapshot=records.snapshot,
        manifest_id=records.manifest_id,
        artifact_manifest=records.artifact_manifest,
    )
    optional_entry = _optional_manifest_entry(report_card.evidence.artifact_root_uri)
    report_card = _add_optional_manifest_source(
        records=records,
        report_card=report_card,
        rows=rows,
        optional_entry=optional_entry,
    )
    candidate = _with_evidence_artifacts(
        report_card,
        (
            *report_card.evidence.artifacts,
            _report_card_evidence_entry(optional_entry),
        ),
    )
    connection = _FakeConnection(rows)
    repository = SqlAlchemyExperimentLedgerRepository(connection)  # type: ignore[arg-type]

    repository.record_research_report_card(candidate)

    assert connection.inserted_tables == ["research_report_cards"]


def test_record_research_report_card_accepts_optional_manifest_artifact_omission(
    source_fixture: tuple[Any, ResearchReportCard],
) -> None:
    records, report_card = source_fixture
    rows = _source_rows(
        run=records.run,
        snapshot=records.snapshot,
        manifest_id=records.manifest_id,
        artifact_manifest=records.artifact_manifest,
    )
    optional_entry = _optional_manifest_entry(report_card.evidence.artifact_root_uri)
    report_card = _add_optional_manifest_source(
        records=records,
        report_card=report_card,
        rows=rows,
        optional_entry=optional_entry,
    )
    connection = _FakeConnection(rows)
    repository = SqlAlchemyExperimentLedgerRepository(connection)  # type: ignore[arg-type]

    repository.record_research_report_card(report_card)

    assert optional_entry.artifact_id not in {
        entry.artifact_id for entry in report_card.evidence.artifacts
    }
    assert connection.inserted_tables == ["research_report_cards"]


def test_get_research_report_card_reruns_source_coherence_validation(
    source_fixture: tuple[Any, ResearchReportCard],
) -> None:
    records, report_card = source_fixture
    rows = _source_rows(
        run=records.run,
        snapshot=records.snapshot,
        manifest_id=records.manifest_id,
        artifact_manifest=records.artifact_manifest,
    )
    rows["research_report_cards"] = {
        report_card.report_card_id: research_report_card_to_row(report_card)
    }
    rows["experiment_runs"][records.run.run_id] = {
        **rows["experiment_runs"][records.run.run_id],
        "contract_hash": "0" * 64,
    }
    connection = _FakeConnection(rows)
    repository = SqlAlchemyExperimentLedgerRepository(connection)  # type: ignore[arg-type]

    with pytest.raises(PersistenceCorruptionError):
        repository.get_research_report_card(report_card.report_card_id)


def _mismatched_report_card(
    *,
    case: str,
    report_card: ResearchReportCard,
    records: Any,
    rows: dict[str, dict[str, dict[str, Any]]],
) -> ResearchReportCard:
    if case == "changed_total_return":
        return _with_metrics(report_card, total_return="0.000000000000")
    if case == "changed_commission":
        return _with_metrics(report_card, realized_commission="0.000000")
    if case == "changed_observation_count":
        metrics = report_card.metrics.model_copy(update={"observation_count": 5})
        scope = report_card.research_scope.model_copy(update={"observation_count": 5})
        return report_card.model_copy(
            update={"metrics": metrics, "research_scope": scope}
        )
    if case == "wrong_experiment_id":
        return report_card.model_copy(update={"experiment_id": "wrong-experiment"})
    if case == "wrong_strategy_id":
        return _with_lineage(report_card, strategy_id="wrong-strategy")
    if case == "wrong_strategy_version":
        return _with_lineage(report_card, strategy_version="9.9.9")
    if case == "wrong_engine_version":
        return _with_lineage(report_card, engine_version="wrong-engine")
    if case == "wrong_git_commit_sha":
        return _with_lineage(report_card, git_commit_sha="bad-commit")
    if case == "wrong_config_hash":
        return _reidentified(
            _with_lineage(report_card, config_hash=f"sha256:{'9' * 64}")
        )
    if case == "wrong_parameter_hash":
        return _reidentified(
            _with_lineage(report_card, parameter_hash=f"sha256:{'8' * 64}")
        )
    if case == "unrelated_data_snapshot_id":
        unrelated = records.snapshot.model_copy(
            update={"snapshot_id": "synthetic-etf-snapshot-unrelated-data"}
        )
        rows["data_snapshot_manifests"][unrelated.snapshot_id] = (
            data_snapshot_manifest_to_row(unrelated)
        )
        return _with_lineage(report_card, data_snapshot_id=unrelated.snapshot_id)
    if case == "data_snapshot_content_hash_mismatch":
        return _reidentified(
            _with_lineage(
                report_card,
                data_snapshot_content_hash=f"sha256:{'7' * 64}",
            )
        )
    if case == "unrelated_benchmark_snapshot_id":
        unrelated = records.snapshot.model_copy(
            update={"snapshot_id": "synthetic-etf-snapshot-unrelated-benchmark"}
        )
        rows["data_snapshot_manifests"][unrelated.snapshot_id] = (
            data_snapshot_manifest_to_row(unrelated)
        )
        return _with_lineage(report_card, benchmark_snapshot_id=unrelated.snapshot_id)
    if case == "unrelated_artifact_manifest_id":
        unrelated_manifest_id = "manifest-unrelated-source"
        unrelated_manifest = records.artifact_manifest.model_copy(
            update={"run_id": "run-unrelated-source"}
        )
        rows["run_artifact_manifests"][unrelated_manifest_id] = (
            run_artifact_manifest_to_rows(
                manifest_id=unrelated_manifest_id,
                manifest=unrelated_manifest,
            ).manifest
        )
        return _with_lineage(report_card, artifact_manifest_id=unrelated_manifest_id)
    if case == "changed_artifact_evidence":
        entry = next(
            entry
            for entry in report_card.evidence.artifacts
            if entry.artifact_kind is not ArtifactKind.CONFIG
        )
        return _with_evidence_entry(
            report_card,
            entry.artifact_id,
            size_bytes=entry.size_bytes + 1,
        )
    if case == "config_evidence_mismatch":
        config = next(
            entry
            for entry in report_card.evidence.artifacts
            if entry.artifact_kind is ArtifactKind.CONFIG
        )
        return _with_evidence_entry(
            report_card,
            config.artifact_id,
            content_hash=f"sha256:{'6' * 64}",
        )
    if case == "non_completed_source_run":
        changed_run = records.run.model_copy(
            update={"status": ExperimentRunStatus.FAILED}
        )
        rows["experiment_runs"][changed_run.run_id] = experiment_run_to_row(changed_run)
        return report_card
    if case == "artifacts_incomplete_source_run":
        changed_run = records.run.model_copy(update={"artifacts_incomplete": True})
        rows["experiment_runs"][changed_run.run_id] = experiment_run_to_row(changed_run)
        return report_card
    raise AssertionError(f"unhandled case: {case}")


def _source_rows(
    *,
    run: ExperimentRunRecord,
    snapshot: DataSnapshotManifest,
    manifest_id: str,
    artifact_manifest: RunArtifactManifest,
) -> dict[str, dict[str, dict[str, Any]]]:
    return {
        "experiment_runs": {run.run_id: experiment_run_to_row(run)},
        "data_snapshot_manifests": {
            snapshot.snapshot_id: data_snapshot_manifest_to_row(snapshot)
        },
        "run_artifact_manifests": {
            manifest_id: run_artifact_manifest_to_rows(
                manifest_id=manifest_id,
                manifest=artifact_manifest,
            ).manifest
        },
    }


def _with_metrics(
    report_card: ResearchReportCard, **updates: object
) -> ResearchReportCard:
    return report_card.model_copy(
        update={"metrics": report_card.metrics.model_copy(update=updates)}
    )


def _with_lineage(
    report_card: ResearchReportCard, **updates: object
) -> ResearchReportCard:
    return report_card.model_copy(
        update={"lineage": report_card.lineage.model_copy(update=updates)}
    )


def _with_evidence_entry(
    report_card: ResearchReportCard,
    artifact_id: str,
    **updates: object,
) -> ResearchReportCard:
    entries = tuple(
        entry.model_copy(update=updates) if entry.artifact_id == artifact_id else entry
        for entry in report_card.evidence.artifacts
    )
    return report_card.model_copy(
        update={
            "evidence": report_card.evidence.model_copy(update={"artifacts": entries})
        }
    )


def _with_evidence_artifacts(
    report_card: ResearchReportCard,
    artifacts: tuple[ReportCardArtifactEvidenceEntry, ...],
) -> ResearchReportCard:
    return report_card.model_copy(
        update={
            "evidence": report_card.evidence.model_copy(update={"artifacts": artifacts})
        }
    )


def _optional_manifest_entry(artifact_root_uri: str) -> RunArtifactEntry:
    return RunArtifactEntry(
        artifact_id="diagnostic-source-summary",
        artifact_kind=ArtifactKind.DIAGNOSTIC,
        filename="diagnostic-source-summary.json",
        uri=f"{artifact_root_uri}/diagnostic-source-summary.json",
        format=ArtifactFormat.JSON,
        status=ArtifactStatus.PRODUCED,
        hash_algorithm=HashAlgorithm.SHA256,
        content_hash=f"sha256:{'a' * 64}",
        size_bytes=321,
        row_count=7,
        created_at=datetime(2026, 8, 8, tzinfo=UTC),
        validator_version="validator-0.1.0",
    )


def _report_card_evidence_entry(
    artifact: RunArtifactEntry,
) -> ReportCardArtifactEvidenceEntry:
    assert artifact.content_hash is not None
    assert artifact.size_bytes is not None
    return ReportCardArtifactEvidenceEntry(
        artifact_id=artifact.artifact_id,
        artifact_kind=artifact.artifact_kind,
        filename=artifact.filename,
        uri=artifact.uri,
        format=artifact.format,
        status=artifact.status,
        content_hash=artifact.content_hash,
        size_bytes=artifact.size_bytes,
        row_count=artifact.row_count,
        validator_version=artifact.validator_version,
    )


def _add_optional_manifest_source(
    *,
    records: Any,
    report_card: ResearchReportCard,
    rows: dict[str, dict[str, dict[str, Any]]],
    optional_entry: RunArtifactEntry,
) -> ResearchReportCard:
    artifact_manifest = records.artifact_manifest.model_copy(
        update={"artifacts": (*records.artifact_manifest.artifacts, optional_entry)}
    )
    artifact_manifest_hash = f"sha256:{contract_sha256(artifact_manifest)}"
    run = records.run.model_copy(
        update={"artifact_manifest_hash": artifact_manifest_hash}
    )
    rows["experiment_runs"][run.run_id] = experiment_run_to_row(run)
    rows["run_artifact_manifests"][records.manifest_id] = run_artifact_manifest_to_rows(
        manifest_id=records.manifest_id,
        manifest=artifact_manifest,
    ).manifest
    return _reidentified(
        _with_lineage(report_card, artifact_manifest_hash=artifact_manifest_hash)
    )


def _reidentified(report_card: ResearchReportCard) -> ResearchReportCard:
    lineage = report_card.lineage
    report_card_id = derive_research_report_card_id_from_fields(
        source_run_id=report_card.source_run_id,
        schema_version=report_card.schema_version,
        derivation_policy_version=report_card.derivation_policy_version,
        data_snapshot_content_hash=lineage.data_snapshot_content_hash,
        benchmark_snapshot_content_hash=lineage.benchmark_snapshot_content_hash,
        config_hash=lineage.config_hash,
        parameter_hash=lineage.parameter_hash,
        artifact_manifest_hash=lineage.artifact_manifest_hash,
    )
    return report_card.model_copy(update={"report_card_id": report_card_id})


def _same_id_valid_content_change(
    report_card: ResearchReportCard,
) -> ResearchReportCard:
    return report_card.model_copy(
        update={"use_restrictions": report_card.use_restrictions[:-1]}
    )


def test_same_id_non_source_content_change_reaches_insert_path(
    source_fixture: tuple[Any, ResearchReportCard],
) -> None:
    records, report_card = source_fixture
    changed = _same_id_valid_content_change(report_card)
    rows = _source_rows(
        run=records.run,
        snapshot=records.snapshot,
        manifest_id=records.manifest_id,
        artifact_manifest=records.artifact_manifest,
    )
    connection = _FakeConnection(rows)
    repository = SqlAlchemyExperimentLedgerRepository(connection)  # type: ignore[arg-type]

    repository.record_research_report_card(changed)

    assert connection.inserted_tables == ["research_report_cards"]
    assert changed.report_card_id == report_card.report_card_id
    assert contract_sha256(changed) != contract_sha256(report_card)
