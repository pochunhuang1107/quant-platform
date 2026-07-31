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
    REPO_ROOT
    / "infra"
    / "db"
    / "migrations"
    / "versions"
    / "0002_ledger_anchor_tables.py"
)
BASELINE_REVISION = "0001_persistence_baseline"
LEDGER_ANCHOR_REVISION = "0002_ledger_anchor_tables"
ARTIFACT_REVISION = "0003_artifact_tables"
RESEARCH_REVIEW_REVISION = "0004_research_review_tables"
ARTIFACT_MANIFEST_RUN_IDENTITY_REVISION = "0005_artifact_run_identity"

APPROVED_TABLES = {
    "experiment_runs",
    "data_snapshot_manifests",
}
DEFERRED_TABLES = {
    "run_artifact_manifests",
    "run_artifact_entries",
    "research_notes",
    "review_events",
}
APPROVED_INDEXES = {
    "ix_experiment_runs_status_created_at",
    "ix_experiment_runs_strategy_id_created_at",
    "ix_experiment_runs_experiment_id_created_at",
    "ix_experiment_runs_data_snapshot_id",
    "ix_experiment_runs_parent_run_id",
    "ix_experiment_runs_supersedes_run_id",
    "ix_data_snapshot_manifests_snapshot_kind_status_created_at",
    "ix_data_snapshot_manifests_asset_source_created_at",
}


class RecordingOp:
    def __init__(self) -> None:
        self.created_tables: list[tuple[str, tuple[Any, ...]]] = []
        self.created_indexes: list[tuple[str, str, tuple[str, ...]]] = []
        self.dropped_indexes: list[tuple[str, str | None]] = []
        self.dropped_tables: list[str] = []
        self.created_foreign_keys: list[tuple[Any, ...]] = []

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

    def create_foreign_key(self, *args: Any, **kwargs: Any) -> None:
        self.created_foreign_keys.append(args)


def load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "ledger_anchor_table_migration",
        MIGRATION_PATH,
    )
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_alembic_script_directory_contains_ledger_anchor_revision() -> None:
    config = Config(str(ALEMBIC_INI))
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == [ARTIFACT_MANIFEST_RUN_IDENTITY_REVISION]

    ledger_anchor = script.get_revision(LEDGER_ANCHOR_REVISION)
    assert ledger_anchor is not None
    assert ledger_anchor.down_revision == BASELINE_REVISION

    artifact_tables = script.get_revision(ARTIFACT_REVISION)
    assert artifact_tables is not None
    assert artifact_tables.down_revision == LEDGER_ANCHOR_REVISION

    research_review_tables = script.get_revision(RESEARCH_REVIEW_REVISION)
    assert research_review_tables is not None
    assert research_review_tables.down_revision == ARTIFACT_REVISION

    artifact_manifest_run_identity = script.get_revision(
        ARTIFACT_MANIFEST_RUN_IDENTITY_REVISION
    )
    assert artifact_manifest_run_identity is not None
    assert artifact_manifest_run_identity.down_revision == RESEARCH_REVIEW_REVISION


def test_ledger_anchor_migration_upgrade_scope(monkeypatch: Any) -> None:
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

    assert created_table_names == APPROVED_TABLES
    assert created_table_names.isdisjoint(DEFERRED_TABLES)
    assert created_index_names == APPROVED_INDEXES
    assert recorder.created_foreign_keys == []

    for _table_name, elements in recorder.created_tables:
        for element in elements:
            assert not isinstance(element, ForeignKeyConstraint)
            if isinstance(element, Column):
                assert element.foreign_keys == set()


def test_ledger_anchor_migration_downgrade_scope(monkeypatch: Any) -> None:
    module = load_migration_module()
    recorder = RecordingOp()
    monkeypatch.setattr(module, "op", recorder)

    module.downgrade()

    dropped_index_names = {
        index_name for index_name, _table in recorder.dropped_indexes
    }

    assert dropped_index_names == APPROVED_INDEXES
    assert set(recorder.dropped_tables) == APPROVED_TABLES
    assert set(recorder.dropped_tables).isdisjoint(DEFERRED_TABLES)
    assert recorder.created_foreign_keys == []
