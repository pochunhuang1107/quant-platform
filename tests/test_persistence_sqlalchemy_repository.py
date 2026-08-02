from __future__ import annotations

import ast
import inspect
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast, get_type_hints

import pytest
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

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
from research_sdk.persistence.protocols import ExperimentLedgerRepository
from research_sdk.persistence.sqlalchemy_repository import (
    SqlAlchemyExperimentLedgerRepository,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "contracts"

EXPECTED_REPOSITORY_METHODS = {
    "record_experiment_run",
    "record_data_snapshot_manifest",
    "record_run_artifact_manifest",
    "record_research_note",
    "append_review_event",
}

EXPECTED_ABSTRACT_METHODS: set[str] = set()

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
    "research_sdk.persistence.tables",
    "research_sdk.persistence.database",
    "research_sdk.persistence.constraint_translation",
}

PROHIBITED_OPERATIONAL_SYMBOLS = {
    "create_engine",
    "Engine",
    "Session",
    "get_database_url",
    "DATABASE_URL",
    "translate_constraint_violation",
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


class _FakeDiagnostic:
    constraint_name = "unknown_review_event_constraint"


class _FakeOrig(Exception):
    sqlstate = "23505"
    diag = _FakeDiagnostic()


class _FailingConnection:
    __slots__ = ("_error",)

    def __init__(self, error: IntegrityError) -> None:
        self._error = error

    def in_transaction(self) -> bool:
        return True

    def execute(self, statement: object) -> object:
        raise self._error


def load_fixture(filename: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / filename).read_text(encoding="utf-8"))


@pytest.fixture
def connection_sentinel() -> Connection:
    return cast(Connection, object())


@pytest.fixture
def repository(connection_sentinel: Connection) -> SqlAlchemyExperimentLedgerRepository:
    return SqlAlchemyExperimentLedgerRepository(connection_sentinel)


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


def test_sqlalchemy_repository_is_directly_instantiable() -> None:
    connection = cast(Connection, object())

    repository = SqlAlchemyExperimentLedgerRepository(connection)

    assert inspect.isabstract(SqlAlchemyExperimentLedgerRepository) is False
    assert (
        getattr(SqlAlchemyExperimentLedgerRepository, "__abstractmethods__", set())
        == EXPECTED_ABSTRACT_METHODS
    )
    assert repository._connection is connection
    assert not getattr(
        SqlAlchemyExperimentLedgerRepository.record_experiment_run,
        "__isabstractmethod__",
        False,
    )
    assert not getattr(
        SqlAlchemyExperimentLedgerRepository.record_data_snapshot_manifest,
        "__isabstractmethod__",
        False,
    )
    assert not getattr(
        SqlAlchemyExperimentLedgerRepository.record_research_note,
        "__isabstractmethod__",
        False,
    )
    assert not getattr(
        SqlAlchemyExperimentLedgerRepository.append_review_event,
        "__isabstractmethod__",
        False,
    )
    assert not getattr(
        SqlAlchemyExperimentLedgerRepository.record_run_artifact_manifest,
        "__isabstractmethod__",
        False,
    )


def test_constructor_stores_exact_injected_connection(
    repository: SqlAlchemyExperimentLedgerRepository,
    connection_sentinel: Connection,
) -> None:
    assert repository._connection is connection_sentinel
    assert type(repository).__init__ is SqlAlchemyExperimentLedgerRepository.__init__
    assert SqlAlchemyExperimentLedgerRepository.__slots__ == ("_connection",)
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


def test_repository_structurally_conforms_to_repository_protocol(
    repository: SqlAlchemyExperimentLedgerRepository,
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


def test_direct_module_and_package_exports_are_canonical() -> None:
    assert sqlalchemy_repository.SqlAlchemyExperimentLedgerRepository is (
        SqlAlchemyExperimentLedgerRepository
    )
    assert persistence.SqlAlchemyExperimentLedgerRepository is (
        SqlAlchemyExperimentLedgerRepository
    )
    assert sqlalchemy_repository.__all__ == ["SqlAlchemyExperimentLedgerRepository"]

    for private_name in (
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

    allowed_calls = {
        "ContractHashConflictError",
        "AggregateIntegrityError",
        "PersistedRecordMetadata",
        "PersistenceErrorContext",
        "PersistenceWriteResult",
        "ReplayLookupError",
        "_hash_backed_write_result",
        "build_data_snapshot_manifest_insert",
        "build_data_snapshot_manifest_replay_select",
        "build_experiment_run_insert",
        "build_experiment_run_replay_select",
        "build_research_note_insert",
        "build_research_note_replay_select",
        "build_review_event_insert",
        "build_run_artifact_entries_replay_select",
        "build_run_artifact_manifest_inserts",
        "build_run_artifact_manifest_replay_select",
        "contract_sha256",
        "execute",
        "in_transaction",
        "mappings",
        "one",
        "one_or_none",
        "NotImplementedError",
        "RuntimeError",
        "translate_sqlalchemy_integrity_error",
    }

    assert PROHIBITED_OPERATIONAL_SYMBOLS.isdisjoint(called_names - allowed_calls)
    assert PROHIBITED_OPERATIONAL_SYMBOLS.isdisjoint(assigned_names)
    assert PROHIBITED_OPERATIONAL_SYMBOLS.isdisjoint(class_members)


def test_source_constructs_only_approved_persistence_results_or_dispositions() -> None:
    tree = _production_ast()
    called_names = _called_names(tree)
    attribute_pairs = _attribute_pairs(tree)

    assert (
        "PersistenceDisposition",
        "CREATED",
    ) in attribute_pairs
    assert (
        "PersistenceDisposition",
        "REPLAYED",
    ) in attribute_pairs
    assert "PersistenceWriteResult" in called_names
    assert "PersistedRecordMetadata" in called_names


def test_record_run_artifact_manifest_requires_transaction_before_work() -> None:
    method_node = _method_node(
        _production_ast(),
        "SqlAlchemyExperimentLedgerRepository",
        "record_run_artifact_manifest",
    )
    first_statement = method_node.body[0]

    assert isinstance(first_statement, ast.Expr)
    assert isinstance(first_statement.value, ast.Call)
    assert isinstance(first_statement.value.func, ast.Attribute)
    assert first_statement.value.func.attr == "_require_active_transaction"
    assert isinstance(first_statement.value.func.value, ast.Name)
    assert first_statement.value.func.value.id == "self"


def test_source_catches_only_integrity_error_with_bare_unknown_reraise() -> None:
    tree = _production_ast()
    repository_handler_names = _caught_exception_names_in_repository_methods(tree)

    assert repository_handler_names == {"IntegrityError"}
    assert _has_bare_raise_in_exception_handler(
        _repository_methods_ast(tree),
        handler_name="IntegrityError",
    )
    assert _has_raise_from_in_exception_handler(
        _repository_methods_ast(tree),
        handler_name="IntegrityError",
        raised_name="translated",
        cause_name="error",
    )


def test_source_private_projection_comparison_catches_safe_normalization_errors() -> (
    None
):
    tree = _production_ast()
    helper_node = _function_node(tree, "_artifact_entry_projections_match")

    assert _caught_exception_names(helper_node) == {
        "KeyError",
        "TypeError",
        "ValueError",
    }


def test_source_contains_no_repository_transaction_lifecycle_calls() -> None:
    called_names = _called_names(_production_ast())

    for prohibited_call in (
        "begin",
        "begin_nested",
        "commit",
        "rollback",
        "close",
        "dispose",
        "connect",
    ):
        assert prohibited_call not in called_names


def test_source_keeps_review_events_out_of_replay_and_hash_paths() -> None:
    source = inspect.getsource(sqlalchemy_repository)
    append_source = inspect.getsource(
        SqlAlchemyExperimentLedgerRepository.append_review_event
    )

    assert "build_review_event_replay_select" not in source
    assert "review_events.c" not in source
    assert "contract_sha256(review" not in append_source
    assert "_hash_backed_write_result" not in append_source
    assert "PersistenceDisposition.REPLAYED" not in append_source


def test_artifact_manifest_reraises_untranslated_parent_integrity_error(
    run_artifact_manifest: RunArtifactManifest,
) -> None:
    original_error = IntegrityError(
        "INSERT INTO run_artifact_manifests",
        {"manifest_id": "manifest-untranslated"},
        _FakeOrig(),
    )
    repository = SqlAlchemyExperimentLedgerRepository(
        cast(Connection, _FailingConnection(original_error))
    )

    with pytest.raises(IntegrityError) as exc_info:
        repository.record_run_artifact_manifest(
            manifest_id="manifest-untranslated",
            manifest=run_artifact_manifest,
        )

    assert exc_info.value is original_error


def test_artifact_entry_projection_normalizes_equivalent_aware_timestamps() -> None:
    expected = _artifact_entry_projection_row(
        created_at="2026-07-09T10:05:00+01:00",
    )
    stored = _artifact_entry_projection_row(
        created_at=datetime(2026, 7, 9, 9, 5, 0, tzinfo=UTC),
    )

    assert sqlalchemy_repository._artifact_entry_projections_match(
        expected_entries=(expected,),
        stored_entries=(stored,),
    )


@pytest.mark.parametrize(
    "created_at",
    [
        "not-a-valid-datetime",
        "2026-07-09T09:05:00",
        datetime(2026, 7, 9, 9, 5, 0),
    ],
)
def test_artifact_entry_projection_rejects_invalid_created_at_without_leaking(
    created_at: object,
) -> None:
    expected = _artifact_entry_projection_row(created_at="2026-07-09T09:05:00Z")
    stored = _artifact_entry_projection_row(created_at=created_at)

    assert (
        sqlalchemy_repository._artifact_entry_projections_match(
            expected_entries=(expected,),
            stored_entries=(stored,),
        )
        is False
    )


def test_append_review_event_reraises_untranslated_integrity_error(
    review_metadata: ReviewMetadata,
) -> None:
    original_error = IntegrityError(
        "INSERT INTO review_events",
        {"review_event_id": "review-event-untranslated"},
        _FakeOrig(),
    )
    repository = SqlAlchemyExperimentLedgerRepository(
        cast(Connection, _FailingConnection(original_error))
    )

    with pytest.raises(IntegrityError) as exc_info:
        repository.append_review_event(
            review_event_id="review-event-untranslated",
            subject_type="experiment_run",
            subject_id="run-untranslated",
            review=review_metadata,
        )

    assert exc_info.value is original_error


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


def _slotted_state(
    repository: SqlAlchemyExperimentLedgerRepository,
) -> dict[str, object]:
    return {
        slot: getattr(repository, slot)
        for slot in SqlAlchemyExperimentLedgerRepository.__slots__
    }


def _artifact_entry_projection_row(*, created_at: object) -> dict[str, object]:
    return {
        "manifest_id": "manifest-unit",
        "artifact_id": "config",
        "run_id": "run-unit",
        "artifact_kind": "config",
        "uri": "artifacts/run-unit/config.json",
        "filename": "config.json",
        "format": "json",
        "status": "produced",
        "hash_algorithm": "sha256",
        "content_hash": "sha256:config",
        "size_bytes": 128,
        "row_count": None,
        "created_at": created_at,
        "validator_version": "artifact-validator-placeholder-0.1.0",
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


def _method_node(
    tree: ast.AST,
    class_name: str,
    method_name: str,
) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method_name:
                    return child
    raise AssertionError(f"{class_name}.{method_name} not found")


def _function_node(tree: ast.AST, function_name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return node
    raise AssertionError(f"{function_name} not found")


def _repository_methods_ast(tree: ast.AST) -> ast.Module:
    method_nodes: list[ast.stmt] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ClassDef)
            and node.name == "SqlAlchemyExperimentLedgerRepository"
        ):
            method_nodes.extend(
                child
                for child in node.body
                if isinstance(child, ast.FunctionDef) and not child.name.startswith("_")
            )
            break

    return ast.Module(body=method_nodes, type_ignores=[])


def _caught_exception_names_in_repository_methods(tree: ast.AST) -> set[str]:
    return _caught_exception_names(_repository_methods_ast(tree))


def _attribute_pairs(tree: ast.AST) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            pairs.add((node.value.id, node.attr))
    return pairs


def _caught_exception_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler) or node.type is None:
            continue
        if isinstance(node.type, ast.Name):
            names.add(node.type.id)
        elif isinstance(node.type, ast.Tuple):
            names.update(
                element.id
                for element in node.type.elts
                if isinstance(element, ast.Name)
            )
    return names


def _has_bare_raise_in_exception_handler(
    tree: ast.AST,
    handler_name: str,
) -> bool:
    return any(
        isinstance(statement, ast.Raise) and statement.exc is None
        for handler in _exception_handlers(tree, handler_name)
        for statement in ast.walk(handler)
    )


def _has_raise_from_in_exception_handler(
    tree: ast.AST,
    *,
    handler_name: str,
    raised_name: str,
    cause_name: str,
) -> bool:
    for handler in _exception_handlers(tree, handler_name):
        for statement in ast.walk(handler):
            if (
                isinstance(statement, ast.Raise)
                and isinstance(statement.exc, ast.Name)
                and isinstance(statement.cause, ast.Name)
                and statement.exc.id == raised_name
                and statement.cause.id == cause_name
            ):
                return True
    return False


def _exception_handlers(
    tree: ast.AST,
    handler_name: str,
) -> tuple[ast.ExceptHandler, ...]:
    handlers: list[ast.ExceptHandler] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ExceptHandler)
            and isinstance(node.type, ast.Name)
            and node.type.id == handler_name
        ):
            handlers.append(node)
    return tuple(handlers)
