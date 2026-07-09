from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from research_sdk.contracts import (
    ArtifactFormat,
    ArtifactKind,
    ArtifactStatus,
    HashAlgorithm,
    RunArtifactManifest,
)


def valid_entry_data(
    artifact_kind: str,
    filename: str,
    artifact_format: str,
    *,
    artifact_id: str | None = None,
    status: str = "produced",
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "artifact_id": artifact_id or artifact_kind,
        "artifact_kind": artifact_kind,
        "uri": f"artifacts/run-20260709-001/{filename}",
        "filename": filename,
        "format": artifact_format,
        "status": status,
    }
    if status == "produced":
        entry.update(
            {
                "hash_algorithm": "sha256",
                "content_hash": f"sha256:{artifact_kind}",
                "size_bytes": 128,
                "created_at": datetime(2026, 7, 9, 9, 5, 0, tzinfo=UTC),
                "validator_version": "artifact-validator-placeholder-0.1.0",
            }
        )
    return entry


def required_entry_data() -> list[dict[str, Any]]:
    return [
        valid_entry_data("config", "config.json", "json"),
        valid_entry_data("metrics", "metrics.json", "json"),
        valid_entry_data("trade_log", "trade_log.parquet", "parquet"),
        valid_entry_data("signal_log", "signal_log.parquet", "parquet"),
        valid_entry_data("daily_equity", "daily_equity.parquet", "parquet"),
        valid_entry_data("drawdown_series", "drawdown_series.parquet", "parquet"),
        valid_entry_data("monthly_returns", "monthly_returns.parquet", "parquet"),
        valid_entry_data("regime_breakdown", "regime_breakdown.json", "json"),
        valid_entry_data("failure_analysis", "failure_analysis.md", "markdown"),
        valid_entry_data("research_note", "research_note.md", "markdown"),
    ]


def valid_manifest_data() -> dict[str, Any]:
    return {
        "run_id": "run-20260709-001",
        "experiment_id": "exp-momentum-baseline",
        "schema_version": "1.0.0",
        "artifact_root_uri": "artifacts/run-20260709-001",
        "created_at": datetime(2026, 7, 9, 9, 0, 0, tzinfo=UTC),
        "required_artifacts_complete": True,
        "artifacts": required_entry_data(),
    }


def test_run_artifact_manifest_accepts_complete_valid_manifest() -> None:
    manifest = RunArtifactManifest(**valid_manifest_data())

    assert manifest.run_id == "run-20260709-001"
    assert manifest.required_artifacts_complete is True
    assert len(manifest.artifacts) == 10
    assert manifest.artifacts[0].artifact_kind is ArtifactKind.CONFIG
    assert manifest.artifacts[0].status is ArtifactStatus.PRODUCED


def test_artifact_kind_contains_documented_values() -> None:
    assert {kind.value for kind in ArtifactKind} == {
        "config",
        "metrics",
        "trade_log",
        "signal_log",
        "daily_equity",
        "drawdown_series",
        "monthly_returns",
        "regime_breakdown",
        "failure_analysis",
        "research_note",
        "chart",
        "log",
        "diagnostic",
        "other",
    }


def test_artifact_format_contains_documented_values() -> None:
    assert {artifact_format.value for artifact_format in ArtifactFormat} == {
        "json",
        "parquet",
        "markdown",
        "png",
        "svg",
        "html",
        "csv",
        "text",
    }


def test_hash_algorithm_contains_documented_values() -> None:
    assert {algorithm.value for algorithm in HashAlgorithm} == {"sha256"}


def test_artifact_status_contains_documented_values() -> None:
    assert {status.value for status in ArtifactStatus} == {
        "produced",
        "missing",
        "failed",
        "skipped",
    }


def test_run_artifact_manifest_normalizes_utc_datetimes() -> None:
    data = valid_manifest_data()
    data["created_at"] = datetime(
        2026,
        7,
        9,
        2,
        0,
        0,
        tzinfo=timezone(timedelta(hours=-7)),
    )
    data["artifacts"][0]["created_at"] = datetime(
        2026,
        7,
        9,
        2,
        5,
        0,
        tzinfo=timezone(timedelta(hours=-7)),
    )

    manifest = RunArtifactManifest(**data)

    assert manifest.created_at == datetime(2026, 7, 9, 9, 0, 0, tzinfo=UTC)
    assert manifest.artifacts[0].created_at == datetime(
        2026,
        7,
        9,
        9,
        5,
        0,
        tzinfo=UTC,
    )


@pytest.mark.parametrize(
    "field_path",
    [
        ("created_at",),
        ("artifacts", 0, "created_at"),
    ],
)
def test_run_artifact_manifest_rejects_naive_datetimes(
    field_path: tuple[str | int, ...],
) -> None:
    data = valid_manifest_data()
    target: Any = data
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = datetime(2026, 7, 9, 9, 0, 0)

    with pytest.raises(ValidationError):
        RunArtifactManifest(**data)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("artifact_kind", "broker_statement"),
        ("format", "xlsx"),
        ("hash_algorithm", "md5"),
        ("status", "verified"),
    ],
)
def test_run_artifact_manifest_rejects_invalid_artifact_enums(
    field_name: str,
    value: str,
) -> None:
    data = valid_manifest_data()
    data["artifacts"][0][field_name] = value

    with pytest.raises(ValidationError):
        RunArtifactManifest(**data)


def test_run_artifact_manifest_rejects_unknown_extra_fields() -> None:
    data = valid_manifest_data()
    data["artifacts"][0]["broker_account"] = "not-allowed"

    with pytest.raises(ValidationError):
        RunArtifactManifest(**data)


def test_run_artifact_manifest_rejects_empty_artifacts_tuple() -> None:
    data = valid_manifest_data()
    data["artifacts"] = ()

    with pytest.raises(ValidationError):
        RunArtifactManifest(**data)


def test_run_artifact_manifest_rejects_missing_required_artifact_kinds() -> None:
    data = valid_manifest_data()
    data["artifacts"] = [
        artifact
        for artifact in data["artifacts"]
        if artifact["artifact_kind"] != "research_note"
    ]

    with pytest.raises(ValidationError, match="missing required artifact kinds"):
        RunArtifactManifest(**data)


def test_run_artifact_manifest_rejects_duplicate_required_artifact_kinds() -> None:
    data = valid_manifest_data()
    replacement = deepcopy(data["artifacts"][1])
    replacement["artifact_id"] = "duplicate-metrics"
    replacement["artifact_kind"] = "config"
    replacement["filename"] = "config.json"
    data["artifacts"][1] = replacement

    with pytest.raises(ValidationError, match="duplicate required artifact kind"):
        RunArtifactManifest(**data)


def test_run_artifact_manifest_rejects_duplicate_artifact_id() -> None:
    data = valid_manifest_data()
    data["artifacts"][1]["artifact_id"] = data["artifacts"][0]["artifact_id"]

    with pytest.raises(ValidationError, match="artifact_id values must be unique"):
        RunArtifactManifest(**data)


@pytest.mark.parametrize(
    "field_name",
    [
        "hash_algorithm",
        "content_hash",
        "size_bytes",
        "created_at",
    ],
)
def test_produced_artifact_requires_integrity_metadata(field_name: str) -> None:
    data = valid_manifest_data()
    data["artifacts"][0][field_name] = None

    with pytest.raises(ValidationError, match="produced artifacts require"):
        RunArtifactManifest(**data)


def test_run_artifact_manifest_accepts_incomplete_required_artifacts() -> None:
    data = valid_manifest_data()
    data["required_artifacts_complete"] = False
    data["artifacts"][0] = valid_entry_data(
        "config",
        "config.json",
        "json",
        status="missing",
    )

    manifest = RunArtifactManifest(**data)

    assert manifest.required_artifacts_complete is False
    assert manifest.artifacts[0].status is ArtifactStatus.MISSING


def test_run_artifact_manifest_rejects_complete_flag_when_required_missing() -> None:
    data = valid_manifest_data()
    data["artifacts"][0] = valid_entry_data(
        "config",
        "config.json",
        "json",
        status="missing",
    )

    with pytest.raises(
        ValidationError,
        match="required_artifacts_complete must match",
    ):
        RunArtifactManifest(**data)


def test_run_artifact_manifest_rejects_incomplete_flag_when_required_produced() -> None:
    data = valid_manifest_data()
    data["required_artifacts_complete"] = False

    with pytest.raises(
        ValidationError,
        match="required_artifacts_complete must match",
    ):
        RunArtifactManifest(**data)


def test_run_artifact_manifest_accepts_repeated_optional_chart_artifacts() -> None:
    data = valid_manifest_data()
    data["artifacts"].extend(
        [
            valid_entry_data(
                "chart",
                "charts/equity_curve.png",
                "png",
                artifact_id="chart-equity-curve",
            ),
            valid_entry_data(
                "chart",
                "charts/drawdown.png",
                "png",
                artifact_id="chart-drawdown",
            ),
        ]
    )

    manifest = RunArtifactManifest(**data)

    assert [artifact.artifact_kind for artifact in manifest.artifacts].count(
        ArtifactKind.CHART
    ) == 2


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("size_bytes", -1),
        ("row_count", -1),
    ],
)
def test_run_artifact_manifest_rejects_negative_counts(
    field_name: str,
    value: int,
) -> None:
    data = valid_manifest_data()
    data["artifacts"][0][field_name] = value

    with pytest.raises(ValidationError):
        RunArtifactManifest(**data)


def test_run_artifact_manifest_rejects_mismatched_required_filename() -> None:
    data = valid_manifest_data()
    data["artifacts"][0]["filename"] = "settings.json"

    with pytest.raises(ValidationError, match="requires filename config.json"):
        RunArtifactManifest(**data)


def test_run_artifact_manifest_rejects_mismatched_required_format() -> None:
    data = valid_manifest_data()
    data["artifacts"][0]["format"] = "csv"

    with pytest.raises(ValidationError, match="requires format json"):
        RunArtifactManifest(**data)


def test_run_artifact_manifest_rejects_manifest_as_artifact_entry() -> None:
    data = valid_manifest_data()
    data["artifacts"].append(
        valid_entry_data(
            "other",
            "artifact_manifest.json",
            "json",
            artifact_id="manifest-self-entry",
        )
    )

    with pytest.raises(ValidationError, match="artifact_manifest.json"):
        RunArtifactManifest(**data)


def test_run_artifact_manifest_has_no_artifact_io_or_hash_behavior() -> None:
    manifest = RunArtifactManifest(**valid_manifest_data())

    assert not hasattr(manifest, "validate_files")
    assert not hasattr(manifest, "verify_hashes")
    assert not hasattr(manifest, "write_artifacts")
