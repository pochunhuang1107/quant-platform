from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
from typing import Any, cast, get_type_hints

import pytest
from sqlalchemy.engine import Connection

import research_sdk.persistence as persistence
import research_sdk.persistence.protocols as protocols
import research_sdk.persistence.sqlalchemy_repository as sqlalchemy_repository
from research_sdk.contracts import (
    DataSnapshotManifest,
    ExperimentRunRecord,
    ResearchNote,
    ReviewMetadata,
    RunArtifactManifest,
)
from research_sdk.persistence.mappers import ReviewSubjectType
from research_sdk.persistence.protocols import ExperimentLedgerRepository
from research_sdk.persistence.results import PersistenceWriteResult
from research_sdk.persistence.sqlalchemy_repository import (
    SqlAlchemyExperimentLedgerRepository,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "contracts"
SCOPE_MESSAGE = "repository execution is outside PR 32 scope"

EXPECTED_REPOSITORY_METHODS = {
    "record_experiment_run",
    "record_data_snapshot_manifest",
    "record_run_artifact_manifest",
    "record_research_note",
    "append_review_event",
}

PROHIBITED_PUBLIC_OPERATIONAL_NAMES = {
    "connection",
    "engine",
    "session",
    "transaction",
    "execute",
    "begin",
    "commit",
    "rollback",
    "close",
    "dispose",
    "connect",
}

PROHIBITED_IMPORT_MODULES = {
    "research_sdk.persistence.protocols",
    "research_sdk.persistence.statements",
    "research_sdk.persistence.tables",
    "research_sdk.persistence.database",
    "research_sdk.persistence.errors",
    "research_sdk.persistence.constraint_translation",
    "research_sdk.persistence.driver_exception_translation",
}

PROHIBITED_OPERATIONAL_SYMBOLS = {
    "create_engine",
    "Engine",
    "Session",
    "get_database_url",
    "DATABASE_URL",
    "IntegrityError",
    "translate_sqlalchemy_integrity_error",
    "translate_constraint_violation",
    "build_experiment_run_insert",
    "build_data_snapshot_manifest_insert",
    "build_run_artifact_manifest_inserts",
    "build_research_note_insert",
    "build_review_event_insert",
    "execute",
    "select",
    "insert",
    "update",
    "delete",
    "begin",
    "commit",
    "rollback",
    "close",
    "dispose",
    "connect",
    "psycopg",
    "asyncpg",
    "alembic",
    "retry",
    "logging",
    "boto3",
    "requests",
    "broker",
    "paper trading",
    "live trading",
}

PROHIBITED_RESULT_CONSTRUCTION_NAMES = {
    "PersistenceWriteResult",
    "PersistedRecordMetadata",
}

PROHIBITED_DISPOSITION_ATTRIBUTES = {
    "CREATED",
    "REPLAYED",
}


class _ConcreteRepository(SqlAlchemyExperimentLedgerRepository):
    __slots__ = ()

    def record_experiment_run(
        self,
        run: ExperimentRunRecord,
    ) -> PersistenceWriteResult:
        raise AssertionError(SCOPE_MESSAGE)

    def record_data_snapshot_manifest(
        self,
        snapshot: DataSnapshotManifest,
    ) -> PersistenceWriteResult:
        raise AssertionError(SCOPE_MESSAGE)

    def record_run_artifact_manifest(
        self,
        *,
        manifest_id: str,
        manifest: RunArtifactManifest,
    ) -> PersistenceWriteResult:
        raise AssertionError(SCOPE_MESSAGE)

    def record_research_note(
        self,
        note: ResearchNote,
    ) -> PersistenceWriteResult:
        raise AssertionError(SCOPE_MESSAGE)

    def append_review_event(
        self,
        *,
        review_event_id: str,
        subject_type: ReviewSubjectType | str,
        subject_id: str,
        review: ReviewMetadata,
    ) -> PersistenceWriteResult:
        raise AssertionError(SCOPE_MESSAGE)


def load_fixture(filename: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / filename).read_text(encoding="utf-8"))


@pytest.fixture
def connection_sentinel() -> Connection:
    return cast(Connection, object())


@pytest.fixture
def repository(connection_sentinel: Connection) -> _ConcreteRepository:
    return _ConcreteRepository(connection_sentinel)


@pytest.fixture
def experiment_run() -> ExperimentRunRecord:
    return ExperimentRunRecord.model_validate(
        load_fixture("experiment_run_record.json")
    )


@pytest.fixture
def data_snapshot_manifest() -> DataSnapshotManifest:
    return DataSnapshotManifest.model_validate(
        load_fixture("data_snapshot_manifest.json")
    )


@pytest.fixture
def run_artifact_manifest() -> RunArtifactManifest:
    return RunArtifactManifest.model_validate(
        load_fixture("run_artifact_manifest.json")
    )


@pytest.fixture
def research_note() -> ResearchNote:
    return ResearchNote.model_validate(load_fixture("research_note.json"))


@pytest.fixture
def review_metadata() -> ReviewMetadata:
    return ReviewMetadata.model_validate(load_fixture("review_metadata.json"))


def test_sqlalchemy_repository_is_abstract_boundary() -> None:
    assert inspect.isabstract(SqlAlchemyExperimentLedgerRepository)

    with pytest.raises(TypeError):
        SqlAlchemyExperimentLedgerRepository(cast(Connection, object()))

    assert (
        SqlAlchemyExperimentLedgerRepository.__abstractmethods__
        == EXPECTED_REPOSITORY_METHODS
    )


def test_constructor_stores_exact_injected_connection(
    repository: _ConcreteRepository,
    connection_sentinel: Connection,
) -> None:
    assert repository._connection is connection_sentinel
    assert SqlAlchemyExperimentLedgerRepository.__slots__ == ("_connection",)
    assert _ConcreteRepository.__slots__ == ()
    assert not hasattr(repository, "__dict__")
    assert _slotted_state(repository) == {"_connection": connection_sentinel}


def test_public_lifecycle_and_operational_names_are_absent() -> None:
    class_namespace = {
        name
        for name in vars(SqlAlchemyExperimentLedgerRepository)
        if not name.startswith("_")
    }
    public_api = {
        name
        for name in dir(SqlAlchemyExperimentLedgerRepository)
        if not name.startswith("_")
    }

    assert PROHIBITED_PUBLIC_OPERATIONAL_NAMES.isdisjoint(class_namespace)
    assert PROHIBITED_PUBLIC_OPERATIONAL_NAMES.isdisjoint(public_api)


def test_concrete_subclass_structurally_conforms_to_repository_protocol(
    repository: _ConcreteRepository,
) -> None:
    assert isinstance(repository, ExperimentLedgerRepository)


@pytest.mark.parametrize("method_name", sorted(EXPECTED_REPOSITORY_METHODS))
def test_method_signatures_match_repository_protocol(method_name: str) -> None:
    protocol_method = getattr(ExperimentLedgerRepository, method_name)
    skeleton_method = getattr(SqlAlchemyExperimentLedgerRepository, method_name)

    _assert_signature_shape_matches(
        inspect.signature(skeleton_method),
        inspect.signature(protocol_method),
    )
    _assert_type_hints_match(method_name)


def test_abstract_method_bodies_defensively_raise_not_implemented(
    repository: _ConcreteRepository,
    experiment_run: ExperimentRunRecord,
    data_snapshot_manifest: DataSnapshotManifest,
    run_artifact_manifest: RunArtifactManifest,
    research_note: ResearchNote,
    review_metadata: ReviewMetadata,
) -> None:
    with pytest.raises(NotImplementedError):
        SqlAlchemyExperimentLedgerRepository.record_experiment_run(
            repository,
            experiment_run,
        )
    with pytest.raises(NotImplementedError):
        SqlAlchemyExperimentLedgerRepository.record_data_snapshot_manifest(
            repository,
            data_snapshot_manifest,
        )
    with pytest.raises(NotImplementedError):
        SqlAlchemyExperimentLedgerRepository.record_run_artifact_manifest(
            repository,
            manifest_id="manifest-run-20260709-001",
            manifest=run_artifact_manifest,
        )
    with pytest.raises(NotImplementedError):
        SqlAlchemyExperimentLedgerRepository.record_research_note(
            repository,
            research_note,
        )
    with pytest.raises(NotImplementedError):
        SqlAlchemyExperimentLedgerRepository.append_review_event(
            repository,
            review_event_id="review-event-20260709-001",
            subject_type=ReviewSubjectType.EXPERIMENT_RUN,
            subject_id=experiment_run.run_id,
            review=review_metadata,
        )


def test_concrete_test_subclass_methods_raise_scope_assertion(
    repository: _ConcreteRepository,
    experiment_run: ExperimentRunRecord,
    data_snapshot_manifest: DataSnapshotManifest,
    run_artifact_manifest: RunArtifactManifest,
    research_note: ResearchNote,
    review_metadata: ReviewMetadata,
) -> None:
    with pytest.raises(AssertionError, match=SCOPE_MESSAGE):
        repository.record_experiment_run(experiment_run)
    with pytest.raises(AssertionError, match=SCOPE_MESSAGE):
        repository.record_data_snapshot_manifest(data_snapshot_manifest)
    with pytest.raises(AssertionError, match=SCOPE_MESSAGE):
        repository.record_run_artifact_manifest(
            manifest_id="manifest-run-20260709-001",
            manifest=run_artifact_manifest,
        )
    with pytest.raises(AssertionError, match=SCOPE_MESSAGE):
        repository.record_research_note(research_note)
    with pytest.raises(AssertionError, match=SCOPE_MESSAGE):
        repository.append_review_event(
            review_event_id="review-event-20260709-001",
            subject_type=ReviewSubjectType.EXPERIMENT_RUN,
            subject_id=experiment_run.run_id,
            review=review_metadata,
        )


def test_direct_module_and_package_exports_are_canonical() -> None:
    assert sqlalchemy_repository.SqlAlchemyExperimentLedgerRepository is (
        SqlAlchemyExperimentLedgerRepository
    )
    assert persistence.SqlAlchemyExperimentLedgerRepository is (
        SqlAlchemyExperimentLedgerRepository
    )
    assert sqlalchemy_repository.__all__ == ["SqlAlchemyExperimentLedgerRepository"]

    for private_name in (
        "_ConcreteRepository",
        "_connection",
        "__abstractmethods__",
        "Connection",
    ):
        assert not hasattr(persistence, private_name)


def test_source_import_boundary_excludes_operational_modules_and_symbols() -> None:
    tree = _production_ast()
    imported_modules = _imported_modules(tree)
    imported_names = _imported_names(tree)

    assert PROHIBITED_IMPORT_MODULES.isdisjoint(imported_modules)
    assert PROHIBITED_OPERATIONAL_SYMBOLS.isdisjoint(imported_names)


def test_source_defines_no_operational_calls_assignments_or_class_members() -> None:
    tree = _production_ast()
    called_names = _called_names(tree)
    assigned_names = _assigned_names(tree)
    class_members = _class_member_names(tree, "SqlAlchemyExperimentLedgerRepository")

    allowed_calls = {"abstractmethod", "NotImplementedError"}

    assert PROHIBITED_OPERATIONAL_SYMBOLS.isdisjoint(called_names - allowed_calls)
    assert PROHIBITED_OPERATIONAL_SYMBOLS.isdisjoint(assigned_names)
    assert PROHIBITED_OPERATIONAL_SYMBOLS.isdisjoint(class_members)


def test_source_constructs_no_persistence_results_or_dispositions() -> None:
    tree = _production_ast()
    called_names = _called_names(tree)
    attribute_pairs = _attribute_pairs(tree)

    assert PROHIBITED_RESULT_CONSTRUCTION_NAMES.isdisjoint(called_names)
    assert (
        "PersistenceDisposition",
        "CREATED",
    ) not in attribute_pairs
    assert (
        "PersistenceDisposition",
        "REPLAYED",
    ) not in attribute_pairs
    assert PROHIBITED_DISPOSITION_ATTRIBUTES.isdisjoint(
        {
            attribute
            for value, attribute in attribute_pairs
            if value == "PersistenceDisposition"
        }
    )


def _assert_signature_shape_matches(
    actual: inspect.Signature,
    expected: inspect.Signature,
) -> None:
    actual_parameters = tuple(actual.parameters.values())
    expected_parameters = tuple(expected.parameters.values())

    assert tuple(parameter.name for parameter in actual_parameters) == tuple(
        parameter.name for parameter in expected_parameters
    )
    assert tuple(parameter.kind for parameter in actual_parameters) == tuple(
        parameter.kind for parameter in expected_parameters
    )
    assert tuple(parameter.default for parameter in actual_parameters) == tuple(
        parameter.default for parameter in expected_parameters
    )


def _assert_type_hints_match(method_name: str) -> None:
    actual_hints = get_type_hints(
        getattr(SqlAlchemyExperimentLedgerRepository, method_name),
        globalns=vars(sqlalchemy_repository),
    )
    expected_hints = get_type_hints(
        getattr(ExperimentLedgerRepository, method_name),
        globalns=vars(protocols),
    )

    assert actual_hints == expected_hints


def _slotted_state(repository: _ConcreteRepository) -> dict[str, object]:
    return {
        slot: getattr(repository, slot)
        for slot in SqlAlchemyExperimentLedgerRepository.__slots__
    }


def _production_ast() -> ast.Module:
    return ast.parse(inspect.getsource(sqlalchemy_repository))


def _imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def _imported_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(
                alias.asname or alias.name.rsplit(".", maxsplit=1)[-1]
                for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def _called_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
    return names


def _assigned_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            for target in targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _class_member_names(tree: ast.AST, class_name: str) -> set[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                child.name
                for child in node.body
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
            }
    raise AssertionError(f"{class_name} class not found")


def _attribute_pairs(tree: ast.AST) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            pairs.add((node.value.id, node.attr))
    return pairs
