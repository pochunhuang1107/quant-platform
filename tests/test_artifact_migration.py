from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Column, ForeignKeyConstraint

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
MIGRATION_PATH = (
    REPO_ROOT / "infra" / "db" / "migrations" / "versions" / "0003_artifact_tables.py"
)
LEDGER_ANCHOR_REVISION = "0002_ledger_anchor_tables"
ARTIFACT_REVISION = "0003_artifact_tables"
RESEARCH_REVIEW_REVISION = "0004_research_review_tables"

APPROVED_TABLES = {
    "run_artifact_manifests",
    "run_artifact_entries",
}
DEFERRED_TABLES = {
    "research_notes",
    "review_events",
}
APPROVED_INDEXES = {
    "ix_run_artifact_manifests_run_id",
    "ix_run_artifact_manifests_experiment_id_created_at",
    "ix_run_artifact_entries_run_id_artifact_kind",
    "ix_run_artifact_entries_status",
    "ix_run_artifact_entries_manifest_id",
}
APPROVED_FOREIGN_KEYS = {
    "fk_run_artifact_entries_manifest_id_run_artifact_manifests": (
        ("manifest_id",),
        ("run_artifact_manifests.manifest_id",),
    )
}


class RecordingOp:
    def __init__(self) -> None:
        self.created_tables: list[tuple[str, tuple[Any, ...]]] = []
        self.created_indexes: list[tuple[str, str, tuple[str, ...]]] = []
        self.dropped_indexes: list[tuple[str, str | None]] = []
        self.dropped_tables: list[str] = []

    def create_table(self, table_name: str, *elements: Any, **kwargs: Any) -> None:
        self.created_tables.append((table_name, elements))

    def create_index(
        self,
        index_name: str,
        table_name: str,
        columns: list[str],
        **kwargs: Any,
    ) -> None:
        self.created_indexes.append((index_name, table_name, tuple(columns)))

    def drop_index(self, index_name: str, **kwargs: Any) -> None:
        table_name = kwargs.get("table_name")
        self.dropped_indexes.append((index_name, table_name))

    def drop_table(self, table_name: str) -> None:
        self.dropped_tables.append(table_name)


def load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "artifact_table_migration",
        MIGRATION_PATH,
    )
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def artifact_foreign_keys(
    created_tables: list[tuple[str, tuple[Any, ...]]],
) -> dict[str, tuple[tuple[str, ...], tuple[str, ...]]]:
    foreign_keys: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}

    for _table_name, elements in created_tables:
        for element in elements:
            if isinstance(element, ForeignKeyConstraint):
                assert element.name is not None
                foreign_keys[element.name] = (
                    tuple(element.column_keys),
                    tuple(
                        fk_element.target_fullname for fk_element in element.elements
                    ),
                )

    return foreign_keys


def test_alembic_script_directory_has_single_artifact_table_head() -> None:
    config = Config(str(ALEMBIC_INI))
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == [RESEARCH_REVIEW_REVISION]

    artifact_revision = script.get_revision(ARTIFACT_REVISION)
    assert artifact_revision is not None
    assert artifact_revision.down_revision == LEDGER_ANCHOR_REVISION

    research_review_revision = script.get_revision(RESEARCH_REVIEW_REVISION)
    assert research_review_revision is not None
    assert research_review_revision.down_revision == ARTIFACT_REVISION


def test_artifact_migration_upgrade_scope(monkeypatch: Any) -> None:
    module = load_migration_module()
    recorder = RecordingOp()
    monkeypatch.setattr(module, "op", recorder)

    module.upgrade()

    created_table_names = {
        table_name for table_name, _elements in recorder.created_tables
    }
    created_index_names = {
        index_name for index_name, _table_name, _columns in recorder.created_indexes
    }

    assert [table_name for table_name, _elements in recorder.created_tables] == [
        "run_artifact_manifests",
        "run_artifact_entries",
    ]
    assert created_table_names == APPROVED_TABLES
    assert created_table_names.isdisjoint(DEFERRED_TABLES)
    assert created_index_names == APPROVED_INDEXES

    created_foreign_keys = artifact_foreign_keys(recorder.created_tables)
    assert created_foreign_keys == APPROVED_FOREIGN_KEYS

    for _table_name, elements in recorder.created_tables:
        for element in elements:
            if isinstance(element, Column):
                assert all(
                    foreign_key.column.table.name != "experiment_runs"
                    for foreign_key in element.foreign_keys
                )
            if isinstance(element, ForeignKeyConstraint):
                assert all(
                    not fk_element.target_fullname.startswith("experiment_runs.")
                    for fk_element in element.elements
                )


def test_artifact_migration_downgrade_scope(monkeypatch: Any) -> None:
    module = load_migration_module()
    recorder = RecordingOp()
    monkeypatch.setattr(module, "op", recorder)

    module.downgrade()

    dropped_index_names = {
        index_name for index_name, _table in recorder.dropped_indexes
    }

    assert dropped_index_names == APPROVED_INDEXES
    assert recorder.dropped_tables == [
        "run_artifact_entries",
        "run_artifact_manifests",
    ]
    assert set(recorder.dropped_tables) == APPROVED_TABLES
    assert set(recorder.dropped_tables).isdisjoint(DEFERRED_TABLES)
