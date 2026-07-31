from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
MIGRATION_PATH = (
    REPO_ROOT
    / "infra"
    / "db"
    / "migrations"
    / "versions"
    / "0005_artifact_manifest_run_identity.py"
)
RESEARCH_REVIEW_REVISION = "0004_research_review_tables"
ARTIFACT_MANIFEST_RUN_IDENTITY_REVISION = "0005_artifact_run_identity"

PROHIBITED_SCOPE_TERMS = {
    "alter_column",
    "create_table",
    "drop_table",
    "add_column",
    "drop_column",
    "manifest_version",
    "supersedes_manifest_id",
    "current",
    "active",
    "soft_delete",
    "delete(",
    "update(",
    "execute(",
    "repository",
    "insert",
    "on_conflict",
    "create_engine",
    "session",
    "reviewevent",
    "foreign_key",
    "run_artifact_entries",
    "experiment_runs",
    "broker",
    "paper_trade",
    "live_trade",
}


class RecordingOp:
    def __init__(self) -> None:
        self.operations: list[tuple[Any, ...]] = []

    def create_unique_constraint(
        self,
        constraint_name: str,
        table_name: str,
        columns: list[str],
        **kwargs: Any,
    ) -> None:
        self.operations.append(
            ("create_unique_constraint", constraint_name, table_name, tuple(columns))
        )

    def drop_constraint(
        self,
        constraint_name: str,
        table_name: str,
        **kwargs: Any,
    ) -> None:
        self.operations.append(
            (
                "drop_constraint",
                constraint_name,
                table_name,
                kwargs.get("type_"),
            )
        )

    def create_index(
        self,
        index_name: str,
        table_name: str,
        columns: list[str],
        **kwargs: Any,
    ) -> None:
        self.operations.append(("create_index", index_name, table_name, tuple(columns)))

    def drop_index(self, index_name: str, **kwargs: Any) -> None:
        self.operations.append(("drop_index", index_name, kwargs.get("table_name")))


def load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "artifact_manifest_run_identity_migration",
        MIGRATION_PATH,
    )
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_artifact_manifest_run_identity_revision_metadata() -> None:
    module = load_migration_module()

    assert module.revision == ARTIFACT_MANIFEST_RUN_IDENTITY_REVISION
    assert module.down_revision == RESEARCH_REVIEW_REVISION


def test_alembic_script_directory_has_artifact_manifest_run_identity_head() -> None:
    config = Config(str(ALEMBIC_INI))
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == [ARTIFACT_MANIFEST_RUN_IDENTITY_REVISION]

    revision = script.get_revision(ARTIFACT_MANIFEST_RUN_IDENTITY_REVISION)
    assert revision is not None
    assert revision.down_revision == RESEARCH_REVIEW_REVISION


def test_artifact_manifest_run_identity_upgrade_order(monkeypatch: Any) -> None:
    module = load_migration_module()
    recorder = RecordingOp()
    monkeypatch.setattr(module, "op", recorder)

    module.upgrade()

    assert recorder.operations == [
        (
            "create_unique_constraint",
            "uq_run_artifact_manifests_run_id",
            "run_artifact_manifests",
            ("run_id",),
        ),
        (
            "drop_constraint",
            "uq_run_artifact_manifests_run_id_contract_hash",
            "run_artifact_manifests",
            "unique",
        ),
        (
            "drop_index",
            "ix_run_artifact_manifests_run_id",
            "run_artifact_manifests",
        ),
    ]


def test_artifact_manifest_run_identity_downgrade_order(monkeypatch: Any) -> None:
    module = load_migration_module()
    recorder = RecordingOp()
    monkeypatch.setattr(module, "op", recorder)

    module.downgrade()

    assert recorder.operations == [
        (
            "create_unique_constraint",
            "uq_run_artifact_manifests_run_id_contract_hash",
            "run_artifact_manifests",
            ("run_id", "contract_hash"),
        ),
        (
            "create_index",
            "ix_run_artifact_manifests_run_id",
            "run_artifact_manifests",
            ("run_id",),
        ),
        (
            "drop_constraint",
            "uq_run_artifact_manifests_run_id",
            "run_artifact_manifests",
            "unique",
        ),
    ]


def test_artifact_manifest_run_identity_migration_excludes_deferred_scope() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8").lower()

    for prohibited_term in PROHIBITED_SCOPE_TERMS:
        assert prohibited_term not in source
