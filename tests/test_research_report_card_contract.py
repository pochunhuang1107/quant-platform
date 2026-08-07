from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from backtest_engine import canonical_json_bytes
from research_sdk.contracts import (
    ArtifactFormat,
    ArtifactKind,
    ArtifactStatus,
    AssetClass,
    AssetUniverseReference,
    DataAdjustmentPolicy,
    RandomSeedMetadata,
    ReportCardMetrics,
    ReportCardUseRestriction,
    ResearchReportCard,
    TemporalCoverage,
)
from research_sdk.contracts.artifacts import REQUIRED_ARTIFACT_SPECS


def valid_report_card_data() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "report_card_id": f"report-card-{'a' * 64}",
        "derivation_policy_version": "deterministic-etf-report-card-v1",
        "source_run_id": f"run-{'b' * 64}",
        "experiment_id": "exp-fixture-qqq-buy-hold",
        "lineage": {
            "strategy_id": "strategies/etfs/qqq_buy_and_hold",
            "strategy_version": "0.1.0",
            "engine_version": "backtest-engine-deterministic-etf-0.1.0",
            "git_commit_sha": "9d18ce75a48beb65a2c633bcd80b440ebbabff20",
            "data_snapshot_id": "synthetic-etf-snapshot-20260206",
            "benchmark_snapshot_id": "synthetic-etf-snapshot-20260206",
            "data_snapshot_content_hash": f"sha256:{'6' * 64}",
            "benchmark_snapshot_content_hash": f"sha256:{'6' * 64}",
            "artifact_manifest_id": f"manifest-{'b' * 64}",
            "config_hash": f"sha256:{'1' * 64}",
            "parameter_hash": f"sha256:{'2' * 64}",
            "artifact_manifest_hash": f"sha256:{'3' * 64}",
        },
        "research_scope": {
            "asset_class": "etfs",
            "asset_universe": {"symbols": ("QQQ",), "as_of": None},
            "benchmark_id": "SPY-gross-normalized",
            "frequency": "daily",
            "start_date": "2026-01-29",
            "end_date": "2026-02-05",
            "observation_count": 6,
            "source_run_status": "completed",
        },
        "assumptions": {
            "cost_model": "QQQ commission is 1 basis points on executed notional",
            "slippage_model": "QQQ buy slippage is 2 basis points",
            "lookback": "no lookback; unconditional initial allocation",
            "lag_assumptions": "no future observation is used",
            "leakage_review": "synthetic fixture-only data",
            "random_seed": {
                "seed": None,
                "rationale": "deterministic no-randomness baseline",
            },
            "adjustment_policy": "raw",
            "temporal_coverage": "point_in_time",
            "corporate_action_policy": "no corporate actions are modeled",
            "survivorship_policy": "not applicable to the fixed synthetic fixture",
            "universe_membership_policy": "fixed synthetic QQQ/SPY membership",
            "calendar": "supplied-fixture-sessions-only",
            "timezone": "America/New_York",
        },
        "metrics": {
            "total_return": "0.049650280020",
            "benchmark_total_return": "0.025000000000",
            "excess_return": "0.024650280020",
            "maximum_drawdown": "-0.009797188585",
            "realized_commission": "9.991998",
            "realized_slippage": "19.980000",
            "ending_equity": "104965.028002",
            "number_of_trades": 1,
            "observation_count": 6,
        },
        "evidence": {
            "artifact_root_uri": f"file:///tmp/run-{'b' * 64}",
            "artifact_manifest_uri": (
                f"file:///tmp/run-{'b' * 64}/artifact_manifest.json"
            ),
            "required_artifacts_complete": True,
            "artifacts": required_evidence_entries(),
        },
        "limitations": {
            "source_snapshot_known_limitations": ("synthetic fixture-only data",)
        },
        "use_restrictions": (
            "research_generated_synthetic_data",
            "infrastructure_validation_only",
            "no_investment_performance_claim",
        ),
    }


def required_evidence_entries() -> tuple[dict[str, Any], ...]:
    root = f"file:///tmp/run-{'b' * 64}"
    entries: list[dict[str, Any]] = []
    for index, (kind, (filename, artifact_format)) in enumerate(
        REQUIRED_ARTIFACT_SPECS.items(),
        start=1,
    ):
        entries.append(
            {
                "artifact_id": kind.value,
                "artifact_kind": kind.value,
                "filename": filename,
                "uri": f"{root}/{filename}",
                "format": artifact_format.value,
                "status": "produced",
                "content_hash": f"sha256:{index:064x}",
                "size_bytes": 100 + index,
                "row_count": None,
                "validator_version": "validator-0.1.0",
            }
        )
    return tuple(entries)


def test_research_report_card_accepts_valid_contract() -> None:
    report_card = ResearchReportCard.model_validate(valid_report_card_data())

    assert report_card.report_card_id == f"report-card-{'a' * 64}"
    assert report_card.research_scope.asset_class is AssetClass.ETFS
    assert report_card.research_scope.asset_universe == AssetUniverseReference(
        symbols=("QQQ",),
        as_of=None,
    )
    assert report_card.assumptions.random_seed == RandomSeedMetadata(
        seed=None,
        rationale="deterministic no-randomness baseline",
    )
    assert report_card.assumptions.adjustment_policy is DataAdjustmentPolicy.RAW
    assert report_card.assumptions.temporal_coverage is TemporalCoverage.POINT_IN_TIME
    assert report_card.metrics == ReportCardMetrics.model_validate(
        valid_report_card_data()["metrics"]
    )


def test_research_report_card_rejects_unknown_top_level_fields() -> None:
    data = valid_report_card_data()
    data["broker_approval"] = "not allowed"

    with pytest.raises(ValidationError):
        ResearchReportCard.model_validate(data)


def test_research_report_card_round_trips_json() -> None:
    report_card = ResearchReportCard.model_validate(valid_report_card_data())

    round_tripped = ResearchReportCard.model_validate_json(
        report_card.model_dump_json()
    )

    assert round_tripped.model_dump(mode="json") == report_card.model_dump(mode="json")


@pytest.mark.parametrize(
    "report_card_id",
    [
        "card-" + ("a" * 64),
        "report-card-" + ("a" * 63),
        "report-card-" + ("A" * 64),
        "report-card-" + ("g" * 64),
    ],
)
def test_research_report_card_rejects_invalid_report_card_id(
    report_card_id: str,
) -> None:
    data = valid_report_card_data()
    data["report_card_id"] = report_card_id

    with pytest.raises(ValidationError, match="report_card_id"):
        ResearchReportCard.model_validate(data)


def test_research_report_card_rejects_missing_limitations() -> None:
    data = valid_report_card_data()
    data["limitations"] = {"source_snapshot_known_limitations": ()}

    with pytest.raises(ValidationError):
        ResearchReportCard.model_validate(data)


def test_research_report_card_rejects_missing_use_restrictions() -> None:
    data = valid_report_card_data()
    data["use_restrictions"] = ()

    with pytest.raises(ValidationError):
        ResearchReportCard.model_validate(data)


@pytest.mark.parametrize(
    ("metric_name", "metric_value"),
    [
        ("total_return", "0.1"),
        ("realized_commission", "9.9919980"),
        ("total_return", "00.100000000000"),
        ("total_return", "+0.100000000000"),
        ("total_return", "1E-12"),
        ("total_return", "NaN"),
        ("total_return", "Infinity"),
        ("total_return", "-0.000000000000"),
        ("benchmark_total_return", "-0.000000000000"),
        ("excess_return", "-0.000000000000"),
        ("maximum_drawdown", "-0.000000000000"),
        ("realized_commission", "-0.000000"),
        ("realized_slippage", "-0.000000"),
        ("ending_equity", "-0.000000"),
        ("realized_commission", "-0.000001"),
        ("realized_slippage", "-0.000001"),
        ("ending_equity", "-1.000000"),
        ("maximum_drawdown", "0.000000000001"),
    ],
)
def test_research_report_card_metric_values_must_be_fixed_point_finite_strings(
    metric_name: str,
    metric_value: str,
) -> None:
    data = valid_report_card_data()
    data["metrics"][metric_name] = metric_value

    with pytest.raises(ValidationError):
        ResearchReportCard.model_validate(data)


@pytest.mark.parametrize(
    "hash_field",
    [
        "data_snapshot_content_hash",
        "benchmark_snapshot_content_hash",
        "config_hash",
        "parameter_hash",
        "artifact_manifest_hash",
    ],
)
def test_research_report_card_lineage_hashes_require_full_sha256(
    hash_field: str,
) -> None:
    data = valid_report_card_data()
    data["lineage"][hash_field] = "sha256:short"

    with pytest.raises(ValidationError, match="sha256"):
        ResearchReportCard.model_validate(data)


def test_research_report_card_rejects_non_completed_scope_status() -> None:
    data = valid_report_card_data()
    data["research_scope"]["source_run_status"] = "failed"

    with pytest.raises(ValidationError, match="completed"):
        ResearchReportCard.model_validate(data)


def test_research_report_card_rejects_scope_metric_observation_mismatch() -> None:
    data = valid_report_card_data()
    data["metrics"]["observation_count"] = 7

    with pytest.raises(ValidationError, match="observation_count"):
        ResearchReportCard.model_validate(data)


def test_research_report_card_rejects_duplicate_restrictions() -> None:
    data = valid_report_card_data()
    data["use_restrictions"] = (
        "infrastructure_validation_only",
        "infrastructure_validation_only",
    )

    with pytest.raises(ValidationError, match="use_restrictions"):
        ResearchReportCard.model_validate(data)


def test_research_report_card_evidence_normalizes_order() -> None:
    report_card = ResearchReportCard.model_validate(valid_report_card_data())

    assert [entry.filename for entry in report_card.evidence.artifacts] == [
        filename
        for _kind, (filename, _artifact_format) in sorted(
            REQUIRED_ARTIFACT_SPECS.items(),
            key=lambda item: (item[0].value, item[1][0], item[0].value),
        )
    ]
    assert report_card.evidence.artifacts[0].artifact_kind is ArtifactKind.CONFIG
    assert report_card.evidence.artifacts[0].format is ArtifactFormat.JSON
    assert report_card.evidence.artifacts[0].status is ArtifactStatus.PRODUCED


def test_research_report_card_evidence_and_restriction_order_have_canonical_json() -> (
    None
):
    first_data = valid_report_card_data()
    second_data = valid_report_card_data()
    second_data["evidence"]["artifacts"] = tuple(
        reversed(second_data["evidence"]["artifacts"])
    )
    second_data["use_restrictions"] = tuple(reversed(second_data["use_restrictions"]))

    first = ResearchReportCard.model_validate(first_data)
    second = ResearchReportCard.model_validate(second_data)

    assert first == second
    assert canonical_json_bytes(first) == canonical_json_bytes(second)


def test_research_report_card_evidence_rejects_duplicate_artifact_ids() -> None:
    data = valid_report_card_data()
    data["evidence"]["artifacts"] = (
        deepcopy(data["evidence"]["artifacts"][0]),
        deepcopy(data["evidence"]["artifacts"][0]),
    )

    with pytest.raises(ValidationError, match="artifact_id"):
        ResearchReportCard.model_validate(data)


def test_research_report_card_accepts_all_required_artifact_entries() -> None:
    report_card = ResearchReportCard.model_validate(valid_report_card_data())

    assert {entry.artifact_kind for entry in report_card.evidence.artifacts} == set(
        REQUIRED_ARTIFACT_SPECS
    )
    assert len(report_card.evidence.artifacts) == len(REQUIRED_ARTIFACT_SPECS)


@pytest.mark.parametrize("missing_kind", tuple(REQUIRED_ARTIFACT_SPECS))
def test_research_report_card_rejects_each_missing_required_artifact(
    missing_kind: ArtifactKind,
) -> None:
    data = valid_report_card_data()
    data["evidence"]["artifacts"] = tuple(
        entry
        for entry in data["evidence"]["artifacts"]
        if entry["artifact_kind"] != missing_kind.value
    )

    with pytest.raises(ValidationError, match="missing required artifact"):
        ResearchReportCard.model_validate(data)


def test_research_report_card_rejects_duplicate_required_kind() -> None:
    data = valid_report_card_data()
    first = deepcopy(data["evidence"]["artifacts"][0])
    duplicate = deepcopy(data["evidence"]["artifacts"][0])
    duplicate["artifact_id"] = "duplicate-config"
    duplicate["filename"] = "duplicate-config.json"
    duplicate["uri"] = f"{data['evidence']['artifact_root_uri']}/duplicate-config.json"
    data["evidence"]["artifacts"] = (
        first,
        duplicate,
        *data["evidence"]["artifacts"][1:],
    )

    with pytest.raises(ValidationError, match="required artifact kinds"):
        ResearchReportCard.model_validate(data)


def test_research_report_card_rejects_wrong_required_filename() -> None:
    data = valid_report_card_data()
    changed = deepcopy(data["evidence"]["artifacts"][0])
    changed["filename"] = "wrong-config.json"
    changed["uri"] = f"{data['evidence']['artifact_root_uri']}/wrong-config.json"
    data["evidence"]["artifacts"] = (changed, *data["evidence"]["artifacts"][1:])

    with pytest.raises(ValidationError, match="filename"):
        ResearchReportCard.model_validate(data)


def test_research_report_card_rejects_wrong_required_format() -> None:
    data = valid_report_card_data()
    changed = deepcopy(data["evidence"]["artifacts"][0])
    changed["format"] = "markdown"
    data["evidence"]["artifacts"] = (changed, *data["evidence"]["artifacts"][1:])

    with pytest.raises(ValidationError, match="format"):
        ResearchReportCard.model_validate(data)


def test_research_report_card_rejects_non_produced_required_entry() -> None:
    data = valid_report_card_data()
    changed = deepcopy(data["evidence"]["artifacts"][0])
    changed["status"] = "missing"
    data["evidence"]["artifacts"] = (changed, *data["evidence"]["artifacts"][1:])

    with pytest.raises(ValidationError, match="produced"):
        ResearchReportCard.model_validate(data)


def test_research_report_card_rejects_malformed_artifact_content_hash() -> None:
    data = valid_report_card_data()
    changed = deepcopy(data["evidence"]["artifacts"][0])
    changed["content_hash"] = "sha256:short"
    data["evidence"]["artifacts"] = (changed, *data["evidence"]["artifacts"][1:])

    with pytest.raises(ValidationError, match="content_hash"):
        ResearchReportCard.model_validate(data)


def test_research_report_card_rejects_required_entry_uri_outside_root() -> None:
    data = valid_report_card_data()
    changed = deepcopy(data["evidence"]["artifacts"][0])
    changed["uri"] = "file:///tmp/outside/config.json"
    data["evidence"]["artifacts"] = (changed, *data["evidence"]["artifacts"][1:])

    with pytest.raises(ValidationError, match="URI"):
        ResearchReportCard.model_validate(data)


def test_research_report_card_accepts_distinct_optional_artifact_entry() -> None:
    data = valid_report_card_data()
    optional = {
        "artifact_id": "diagnostic-extra",
        "artifact_kind": "diagnostic",
        "filename": "diagnostic-extra.json",
        "uri": f"{data['evidence']['artifact_root_uri']}/diagnostic-extra.json",
        "format": "json",
        "status": "produced",
        "content_hash": f"sha256:{'a' * 64}",
        "size_bytes": 10,
        "row_count": None,
        "validator_version": "validator-0.1.0",
    }
    data["evidence"]["artifacts"] = (*data["evidence"]["artifacts"], optional)

    report_card = ResearchReportCard.model_validate(data)

    assert any(
        entry.artifact_kind is ArtifactKind.DIAGNOSTIC
        for entry in report_card.evidence.artifacts
    )


def test_research_report_card_rejects_incomplete_evidence() -> None:
    data = valid_report_card_data()
    data["evidence"]["required_artifacts_complete"] = False

    with pytest.raises(ValidationError, match="required_artifacts_complete"):
        ResearchReportCard.model_validate(data)


def test_report_card_use_restriction_enum_contains_current_slice_restrictions() -> None:
    assert {restriction.value for restriction in ReportCardUseRestriction} == {
        "research_generated_synthetic_data",
        "infrastructure_validation_only",
        "no_investment_performance_claim",
        "not_production_data_research",
        "not_paper_trading_evidence",
        "not_live_trading_evidence",
    }


def test_report_card_schema_is_exported() -> None:
    schema = ResearchReportCard.model_json_schema(mode="validation")

    assert schema["additionalProperties"] is False
    assert "ReportCardLineage" in schema["$defs"]
    assert "ReportCardUseRestriction" in schema["$defs"]
