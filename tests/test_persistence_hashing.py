from __future__ import annotations

import inspect
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from research_sdk.contracts import (
    BaseContractModel,
    DataSnapshotManifest,
    ExperimentRunRecord,
    ResearchNote,
    ReviewMetadata,
    RunArtifactManifest,
    VersionedContract,
)
from research_sdk.persistence.hashing import (
    canonical_contract_json,
    canonical_json_sha256,
    contract_sha256,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "contracts"


@dataclass(frozen=True)
class ContractFixtureCase:
    model: type[BaseContractModel]
    fixture_filename: str


CONTRACT_FIXTURE_CASES = (
    ContractFixtureCase(VersionedContract, "versioned_contract.json"),
    ContractFixtureCase(ReviewMetadata, "review_metadata.json"),
    ContractFixtureCase(ExperimentRunRecord, "experiment_run_record.json"),
    ContractFixtureCase(RunArtifactManifest, "run_artifact_manifest.json"),
    ContractFixtureCase(DataSnapshotManifest, "data_snapshot_manifest.json"),
    ContractFixtureCase(ResearchNote, "research_note.json"),
)

CONTRACT_FIXTURE_IDS = [case.model.__name__ for case in CONTRACT_FIXTURE_CASES]


def load_fixture(case: ContractFixtureCase) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / case.fixture_filename).read_text(encoding="utf-8"))


def experiment_run() -> ExperimentRunRecord:
    case = ContractFixtureCase(ExperimentRunRecord, "experiment_run_record.json")
    return ExperimentRunRecord.model_validate(load_fixture(case))


def test_canonical_json_sha256_is_independent_of_mapping_insertion_order() -> None:
    first_payload = {
        "schema_version": "1.0.0",
        "nested": {"b": 2, "a": 1},
        "items": [{"z": True, "a": None}],
    }
    second_payload = {
        "items": [{"a": None, "z": True}],
        "nested": {"a": 1, "b": 2},
        "schema_version": "1.0.0",
    }

    assert canonical_json_sha256(first_payload) == canonical_json_sha256(second_payload)


def test_canonical_json_sha256_rejects_non_json_values() -> None:
    with pytest.raises(TypeError):
        canonical_json_sha256({"not_json": object()})


def test_canonical_contract_json_is_deterministic_for_same_contract() -> None:
    contract = experiment_run()

    assert canonical_contract_json(contract) == canonical_contract_json(contract)


def test_contract_sha256_is_deterministic_for_same_logical_contract() -> None:
    first_contract = experiment_run()
    second_contract = ExperimentRunRecord.model_validate(
        first_contract.model_dump(mode="json")
    )

    assert contract_sha256(first_contract) == contract_sha256(second_contract)


def test_contract_sha256_changes_when_meaningful_contract_field_changes() -> None:
    original = experiment_run()
    changed_payload = original.model_dump(mode="json")
    changed_payload["strategy_version"] = "strategy-v2"
    changed = ExperimentRunRecord.model_validate(changed_payload)

    assert contract_sha256(changed) != contract_sha256(original)


def test_contract_sha256_changes_when_schema_version_changes() -> None:
    original = experiment_run()
    changed_payload = original.model_dump(mode="json")
    changed_payload["schema_version"] = "1.0.1"
    changed = ExperimentRunRecord.model_validate(changed_payload)

    assert contract_sha256(changed) != contract_sha256(original)


@pytest.mark.parametrize(
    "case",
    CONTRACT_FIXTURE_CASES,
    ids=CONTRACT_FIXTURE_IDS,
)
def test_db_generated_inserted_at_is_not_in_contract_canonical_json(
    case: ContractFixtureCase,
) -> None:
    contract = case.model.model_validate(load_fixture(case))

    assert "inserted_at" not in canonical_contract_json(contract)


@pytest.mark.parametrize(
    "case",
    CONTRACT_FIXTURE_CASES,
    ids=CONTRACT_FIXTURE_IDS,
)
def test_contract_sha256_works_against_current_contract_fixtures(
    case: ContractFixtureCase,
) -> None:
    contract = case.model.model_validate(load_fixture(case))

    assert re.fullmatch(r"[0-9a-f]{64}", contract_sha256(contract))


def test_canonical_contract_json_output_is_compact_and_key_sorted() -> None:
    case = ContractFixtureCase(ReviewMetadata, "review_metadata.json")
    contract = ReviewMetadata.model_validate(load_fixture(case))

    rendered = canonical_contract_json(contract)

    assert rendered.startswith('{"approval_expires_at":')
    assert ", " not in rendered
    assert ": " not in rendered

    payload = {"b": 2, "a": {"d": 4, "c": 3}, "schema_version": "1.0.0"}
    rendered_payload = _render_canonical_json_for_test(payload)

    assert canonical_json_sha256(payload) == canonical_json_sha256(
        {"schema_version": "1.0.0", "a": {"c": 3, "d": 4}, "b": 2}
    )
    assert rendered_payload.startswith('{"a":')
    assert ", " not in rendered_payload
    assert ": " not in rendered_payload


def _render_canonical_json_for_test(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


@pytest.mark.parametrize(
    "case",
    CONTRACT_FIXTURE_CASES,
    ids=CONTRACT_FIXTURE_IDS,
)
def test_hashing_helpers_do_not_mutate_contract_objects(
    case: ContractFixtureCase,
) -> None:
    contract = case.model.model_validate(load_fixture(case))
    before = contract.model_dump(mode="json")

    canonical_contract_json(contract)
    contract_sha256(contract)

    assert contract.model_dump(mode="json") == before


def test_canonical_json_sha256_does_not_mutate_mapping_payload() -> None:
    payload = {"b": {"d": 4, "c": 3}, "a": [2, 1]}
    before = deepcopy(payload)

    canonical_json_sha256(payload)

    assert payload == before


def test_hashing_helpers_do_not_import_database_or_table_modules() -> None:
    import research_sdk.persistence.hashing as hashing

    module_names = set(vars(hashing))

    assert "sqlalchemy" not in module_names
    assert "get_database_url" not in module_names
    assert "metadata" not in module_names


def test_hashing_module_excludes_db_and_file_io_hooks() -> None:
    import research_sdk.persistence.hashing as hashing

    source = inspect.getsource(hashing)

    for prohibited_term in (
        "sqlalchemy",
        "get_database_url",
        "create_engine",
        "connect(",
        "Path(",
        "open(",
        "read_text(",
        "content_hash",
    ):
        assert prohibited_term not in source
