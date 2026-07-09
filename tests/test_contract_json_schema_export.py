import json
from pathlib import Path

from research_sdk.contracts import (
    ArtifactFormat,
    ArtifactKind,
    ArtifactStatus,
    AssetClass,
    DataAdjustmentPolicy,
    DataSnapshotKind,
    DataSnapshotStatus,
    DataSourceType,
    DecisionOutcome,
    EvidenceStrength,
    ExperimentRunStatus,
    FailureLabel,
    HashAlgorithm,
    HypothesisStatus,
    ResearchNoteStatus,
    ResearchNoteType,
    ReviewRole,
    ReviewStatus,
    TemporalCoverage,
)
from research_sdk.contracts.json_schema import (
    SCHEMA_EXPORTS,
    generate_schema_files,
    write_schema_files,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "packages" / "research-sdk" / "schema"


def load_schema(filename: str) -> dict[str, object]:
    return json.loads((SCHEMA_DIR / filename).read_text(encoding="utf-8"))


def test_schema_export_allowlist_contains_expected_files_only() -> None:
    assert set(SCHEMA_EXPORTS) == {
        "versioned_contract.schema.json",
        "review_metadata.schema.json",
        "experiment_run_record.schema.json",
        "run_artifact_manifest.schema.json",
        "data_snapshot_manifest.schema.json",
        "research_note.schema.json",
    }


def test_schema_export_output_is_deterministic_across_directories(
    tmp_path: Path,
) -> None:
    first_output_dir = tmp_path / "first"
    second_output_dir = tmp_path / "second"

    write_schema_files(first_output_dir)
    write_schema_files(second_output_dir)

    first_files = {
        path.name: path.read_bytes() for path in sorted(first_output_dir.iterdir())
    }
    second_files = {
        path.name: path.read_bytes() for path in sorted(second_output_dir.iterdir())
    }

    assert first_files == second_files


def test_committed_schema_files_match_freshly_generated_output() -> None:
    for filename, expected_content in generate_schema_files().items():
        schema_path = SCHEMA_DIR / filename

        assert schema_path.read_text(encoding="utf-8") == expected_content


def test_versioned_contract_schema_contains_expected_fields() -> None:
    schema = load_schema("versioned_contract.schema.json")
    schema_version_def = schema["$defs"]["SchemaVersion"]  # type: ignore[index]

    assert "schema_version" in schema["properties"]  # type: ignore[operator]
    assert schema["required"] == ["schema_version"]
    assert (
        schema_version_def["pattern"]  # type: ignore[index]
        == r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
    )
    assert schema["additionalProperties"] is False


def test_review_metadata_schema_contains_expected_fields() -> None:
    schema = load_schema("review_metadata.schema.json")

    assert set(schema["properties"]) == {  # type: ignore[arg-type]
        "review_status",
        "reviewer_id",
        "review_role",
        "reviewed_at",
        "decision",
        "approval_scope",
        "approval_expires_at",
        "linked_pr",
        "review_notes_uri",
        "risk_approval_required",
    }
    assert set(schema["required"]) == {"review_status", "risk_approval_required"}  # type: ignore[arg-type]
    assert schema["additionalProperties"] is False


def test_review_metadata_schema_contains_documented_review_enums() -> None:
    schema = load_schema("review_metadata.schema.json")
    schema_defs = schema["$defs"]  # type: ignore[index]

    assert set(schema_defs["ReviewStatus"]["enum"]) == {  # type: ignore[index]
        status.value for status in ReviewStatus
    }
    assert set(schema_defs["ReviewRole"]["enum"]) == {  # type: ignore[index]
        role.value for role in ReviewRole
    }


def test_experiment_run_record_schema_contains_expected_fields() -> None:
    schema = load_schema("experiment_run_record.schema.json")

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {  # type: ignore[arg-type]
        "run_id",
        "experiment_id",
        "schema_version",
        "created_at",
        "created_by",
        "status",
        "status_updated_at",
        "status_updated_by",
        "strategy_id",
        "strategy_version",
        "git_commit_sha",
        "repo_dirty",
        "asset_class",
        "asset_universe",
        "time_range",
        "frequency",
        "benchmark",
        "data_snapshot_id",
        "config_uri",
        "config_hash",
        "artifact_uri",
        "artifact_manifest_uri",
        "artifact_manifest_hash",
        "cost_model",
        "slippage_model",
        "lookback",
        "lag_assumptions",
        "leakage_review",
        "environment",
        "dependency_lock_hash",
        "execution_command",
        "engine_version",
        "random_seed",
        "parameter_hash",
        "metrics_summary",
        "review",
    }


def test_experiment_run_record_schema_contains_contract_definitions() -> None:
    schema = load_schema("experiment_run_record.schema.json")
    schema_defs = schema["$defs"]  # type: ignore[index]

    assert set(schema_defs["ExperimentRunStatus"]["enum"]) == {  # type: ignore[index]
        status.value for status in ExperimentRunStatus
    }
    assert set(schema_defs["FailureLabel"]["enum"]) == {  # type: ignore[index]
        label.value for label in FailureLabel
    }
    assert set(schema_defs["AssetClass"]["enum"]) == {  # type: ignore[index]
        asset_class.value for asset_class in AssetClass
    }
    assert "ReviewMetadata" in schema_defs
    assert "AssetUniverseReference" in schema_defs
    assert "BenchmarkReference" in schema_defs
    assert "RunEnvironment" in schema_defs
    assert "RandomSeedMetadata" in schema_defs
    assert "TimeRange" in schema_defs


def test_run_artifact_manifest_schema_contains_expected_fields() -> None:
    schema = load_schema("run_artifact_manifest.schema.json")

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {  # type: ignore[arg-type]
        "run_id",
        "experiment_id",
        "schema_version",
        "artifact_root_uri",
        "created_at",
        "required_artifacts_complete",
        "artifacts",
    }


def test_run_artifact_manifest_schema_contains_contract_definitions() -> None:
    schema = load_schema("run_artifact_manifest.schema.json")
    schema_defs = schema["$defs"]  # type: ignore[index]

    assert set(schema_defs["ArtifactKind"]["enum"]) == {  # type: ignore[index]
        kind.value for kind in ArtifactKind
    }
    assert set(schema_defs["ArtifactFormat"]["enum"]) == {  # type: ignore[index]
        artifact_format.value for artifact_format in ArtifactFormat
    }
    assert set(schema_defs["HashAlgorithm"]["enum"]) == {  # type: ignore[index]
        algorithm.value for algorithm in HashAlgorithm
    }
    assert set(schema_defs["ArtifactStatus"]["enum"]) == {  # type: ignore[index]
        status.value for status in ArtifactStatus
    }
    assert "RunArtifactEntry" in schema_defs
    assert "SchemaVersion" in schema_defs


def test_data_snapshot_manifest_schema_contains_expected_fields() -> None:
    schema = load_schema("data_snapshot_manifest.schema.json")

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {  # type: ignore[arg-type]
        "snapshot_id",
        "schema_version",
        "snapshot_kind",
        "status",
        "created_at",
        "created_by",
        "asset_class",
        "asset_universe",
        "time_range",
        "frequency",
        "data_root_uri",
        "source_dataset",
        "source_version",
        "source_type",
        "temporal_coverage",
        "as_of",
        "available_at",
        "ingestion_completed_at",
        "adjustment_policy",
        "calendar",
        "timezone",
        "universe_membership_policy",
        "corporate_action_policy",
        "survivorship_policy",
        "delisting_policy",
        "hash_algorithm",
        "content_hash",
        "row_count",
        "known_limitations",
    }


def test_data_snapshot_manifest_schema_contains_contract_definitions() -> None:
    schema = load_schema("data_snapshot_manifest.schema.json")
    schema_defs = schema["$defs"]  # type: ignore[index]

    assert set(schema_defs["DataSnapshotKind"]["enum"]) == {  # type: ignore[index]
        kind.value for kind in DataSnapshotKind
    }
    assert set(schema_defs["DataSourceType"]["enum"]) == {  # type: ignore[index]
        source_type.value for source_type in DataSourceType
    }
    assert set(schema_defs["DataAdjustmentPolicy"]["enum"]) == {  # type: ignore[index]
        policy.value for policy in DataAdjustmentPolicy
    }
    assert set(schema_defs["TemporalCoverage"]["enum"]) == {  # type: ignore[index]
        coverage.value for coverage in TemporalCoverage
    }
    assert set(schema_defs["DataSnapshotStatus"]["enum"]) == {  # type: ignore[index]
        status.value for status in DataSnapshotStatus
    }
    assert set(schema_defs["AssetClass"]["enum"]) == {  # type: ignore[index]
        asset_class.value for asset_class in AssetClass
    }
    assert set(schema_defs["HashAlgorithm"]["enum"]) == {  # type: ignore[index]
        algorithm.value for algorithm in HashAlgorithm
    }
    assert "AssetUniverseReference" in schema_defs
    assert "TimeRange" in schema_defs
    assert "SchemaVersion" in schema_defs


def test_research_note_schema_contains_expected_fields() -> None:
    schema = load_schema("research_note.schema.json")

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {  # type: ignore[arg-type]
        "note_id",
        "schema_version",
        "note_type",
        "status",
        "created_at",
        "created_by",
        "updated_at",
        "updated_by",
        "title",
        "hypothesis",
        "motivation",
        "methodology",
        "benchmark_summary",
        "cost_assumptions",
        "slippage_assumptions",
        "lookback",
        "lag_assumptions",
        "leakage_review",
        "results_summary",
        "interpretation",
        "risks",
        "failure_modes",
        "validation_plan",
        "limitations",
        "next_steps",
        "evidence_strength",
        "decision",
        "review",
    }


def test_research_note_schema_contains_contract_definitions() -> None:
    schema = load_schema("research_note.schema.json")
    schema_defs = schema["$defs"]  # type: ignore[index]

    assert set(schema_defs["ResearchNoteType"]["enum"]) == {  # type: ignore[index]
        note_type.value for note_type in ResearchNoteType
    }
    assert set(schema_defs["ResearchNoteStatus"]["enum"]) == {  # type: ignore[index]
        status.value for status in ResearchNoteStatus
    }
    assert set(schema_defs["HypothesisStatus"]["enum"]) == {  # type: ignore[index]
        status.value for status in HypothesisStatus
    }
    assert set(schema_defs["EvidenceStrength"]["enum"]) == {  # type: ignore[index]
        strength.value for strength in EvidenceStrength
    }
    assert set(schema_defs["DecisionOutcome"]["enum"]) == {  # type: ignore[index]
        outcome.value for outcome in DecisionOutcome
    }
    assert "ResearchHypothesis" in schema_defs
    assert "ResearchNoteReferences" in schema_defs
    assert "ResearchDecision" in schema_defs
    assert "ReviewMetadata" in schema_defs
