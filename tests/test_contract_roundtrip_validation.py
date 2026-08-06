import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from research_sdk.contracts import (
    BaseContractModel,
    DataSnapshotManifest,
    ExperimentRunRecord,
    ResearchNote,
    ResearchReportCard,
    ReviewMetadata,
    RunArtifactManifest,
    VersionedContract,
)
from research_sdk.contracts.enums import FailureLabel
from research_sdk.contracts.json_schema import SCHEMA_EXPORTS

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "contracts"
SCHEMA_DIR = REPO_ROOT / "packages" / "research-sdk" / "schema"


@dataclass(frozen=True)
class RoundtripCase:
    model: type[BaseContractModel]
    schema_filename: str
    fixture_filename: str


ROUNDTRIP_CASES = (
    RoundtripCase(
        VersionedContract,
        "versioned_contract.schema.json",
        "versioned_contract.json",
    ),
    RoundtripCase(
        ReviewMetadata,
        "review_metadata.schema.json",
        "review_metadata.json",
    ),
    RoundtripCase(
        ExperimentRunRecord,
        "experiment_run_record.schema.json",
        "experiment_run_record.json",
    ),
    RoundtripCase(
        RunArtifactManifest,
        "run_artifact_manifest.schema.json",
        "run_artifact_manifest.json",
    ),
    RoundtripCase(
        DataSnapshotManifest,
        "data_snapshot_manifest.schema.json",
        "data_snapshot_manifest.json",
    ),
    RoundtripCase(
        ResearchReportCard,
        "research_report_card.schema.json",
        "research_report_card.json",
    ),
    RoundtripCase(
        ResearchNote,
        "research_note.schema.json",
        "research_note.json",
    ),
)

ROUNDTRIP_CASE_IDS = [case.model.__name__ for case in ROUNDTRIP_CASES]


def load_fixture(case: RoundtripCase) -> dict[str, Any]:
    fixture_path = FIXTURE_DIR / case.fixture_filename
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def get_path(value: Any, path: tuple[str | int, ...]) -> Any:
    for key in path:
        value = value[key]
    return value


def test_roundtrip_contract_matrix_matches_schema_exports() -> None:
    schema_filenames = {case.schema_filename for case in ROUNDTRIP_CASES}
    fixture_filenames = {case.fixture_filename for case in ROUNDTRIP_CASES}
    committed_fixture_filenames = {
        fixture_path.name for fixture_path in FIXTURE_DIR.glob("*.json")
    }

    assert schema_filenames == set(SCHEMA_EXPORTS)
    assert fixture_filenames == committed_fixture_filenames

    for case in ROUNDTRIP_CASES:
        assert SCHEMA_EXPORTS[case.schema_filename] is case.model
        assert (FIXTURE_DIR / case.fixture_filename).is_file()


@pytest.mark.parametrize("case", ROUNDTRIP_CASES, ids=ROUNDTRIP_CASE_IDS)
def test_contract_examples_instantiate_and_roundtrip_json(
    case: RoundtripCase,
) -> None:
    payload = load_fixture(case)

    instance = case.model.model_validate(payload)
    serialized = instance.model_dump_json()
    roundtripped = case.model.model_validate_json(serialized)

    assert roundtripped.model_dump(mode="json") == instance.model_dump(mode="json")


@pytest.mark.parametrize("case", ROUNDTRIP_CASES, ids=ROUNDTRIP_CASE_IDS)
def test_contract_examples_reject_unknown_top_level_fields(
    case: RoundtripCase,
) -> None:
    payload = load_fixture(case)
    payload["unexpected_field"] = "not allowed"

    with pytest.raises(ValidationError):
        case.model.model_validate(payload)


@pytest.mark.parametrize(
    ("case", "expected_timestamps"),
    [
        (
            ROUNDTRIP_CASES[1],
            {
                ("reviewed_at",): "2026-07-09T09:00:00Z",
            },
        ),
        (
            ROUNDTRIP_CASES[2],
            {
                ("created_at",): "2026-07-09T09:00:00Z",
                ("status_updated_at",): "2026-07-09T09:30:00Z",
                ("asset_universe", "as_of"): "2026-07-09T08:55:00Z",
                ("review", "reviewed_at"): "2026-07-09T09:35:00Z",
            },
        ),
        (
            ROUNDTRIP_CASES[3],
            {
                ("created_at",): "2026-07-09T09:00:00Z",
                ("artifacts", 0, "created_at"): "2026-07-09T09:05:00Z",
            },
        ),
        (
            ROUNDTRIP_CASES[4],
            {
                ("created_at",): "2026-07-09T09:00:00Z",
                ("asset_universe", "as_of"): "2026-07-09T08:25:00Z",
                ("as_of",): "2026-07-09T08:30:00Z",
                ("source_observed_at",): "2026-07-09T08:40:00Z",
                ("ingestion_completed_at",): "2026-07-09T08:50:00Z",
                ("available_at",): "2026-07-09T08:55:00Z",
            },
        ),
        (
            ROUNDTRIP_CASES[5],
            {},
        ),
        (
            ROUNDTRIP_CASES[6],
            {
                ("created_at",): "2026-07-09T09:00:00Z",
                ("updated_at",): "2026-07-09T09:30:00Z",
                ("review", "reviewed_at"): "2026-07-09T09:35:00Z",
            },
        ),
    ],
    ids=[
        "ReviewMetadata",
        "ExperimentRunRecord",
        "RunArtifactManifest",
        "DataSnapshotManifest",
        "ResearchReportCard",
        "ResearchNote",
    ],
)
def test_contract_examples_normalize_utc_datetime_output(
    case: RoundtripCase,
    expected_timestamps: dict[tuple[str | int, ...], str],
) -> None:
    instance = case.model.model_validate(load_fixture(case))
    dumped = instance.model_dump(mode="json")

    for field_path, expected_value in expected_timestamps.items():
        assert get_path(dumped, field_path) == expected_value


def test_contract_examples_normalize_json_arrays_to_tuples() -> None:
    experiment = ExperimentRunRecord.model_validate(load_fixture(ROUNDTRIP_CASES[2]))
    artifacts = RunArtifactManifest.model_validate(load_fixture(ROUNDTRIP_CASES[3]))
    snapshot = DataSnapshotManifest.model_validate(load_fixture(ROUNDTRIP_CASES[4]))
    report_card = ResearchReportCard.model_validate(load_fixture(ROUNDTRIP_CASES[5]))
    note = ResearchNote.model_validate(load_fixture(ROUNDTRIP_CASES[6]))

    assert experiment.asset_universe.symbols == ("AAPL", "MSFT")
    assert isinstance(experiment.asset_universe.symbols, tuple)
    assert experiment.failure_labels == (FailureLabel.EXECUTION_ERROR,)
    assert isinstance(experiment.failure_labels, tuple)

    assert len(artifacts.artifacts) == 10
    assert isinstance(artifacts.artifacts, tuple)

    assert snapshot.known_limitations == ("none known",)
    assert isinstance(snapshot.known_limitations, tuple)

    assert report_card.use_restrictions[0].value == "infrastructure_validation_only"
    assert isinstance(report_card.evidence.artifacts, tuple)

    assert note.risks == ("overfitting",)
    assert isinstance(note.risks, tuple)
    assert note.failure_modes == ("momentum reverses in volatile regimes",)
    assert isinstance(note.failure_modes, tuple)
    assert note.references.run_ids == ("run-20260709-001",)
    assert isinstance(note.references.run_ids, tuple)
    assert note.tags == ("momentum", "baseline")
    assert isinstance(note.tags, tuple)


def test_committed_schema_files_still_match_exports() -> None:
    for case in ROUNDTRIP_CASES:
        assert (SCHEMA_DIR / case.schema_filename).is_file()
