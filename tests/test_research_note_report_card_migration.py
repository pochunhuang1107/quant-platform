from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

from sqlalchemy import ForeignKeyConstraint, PrimaryKeyConstraint

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    REPO_ROOT
    / "infra"
    / "db"
    / "migrations"
    / "versions"
    / "0007_research_note_report_cards.py"
)
RESEARCH_REPORT_CARD_REVISION = "0006_research_report_cards"
RESEARCH_NOTE_REPORT_CARD_REVISION = "0007_research_note_report_cards"


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
        self.dropped_indexes.append((index_name, kwargs.get("table_name")))

    def drop_table(self, table_name: str) -> None:
        self.dropped_tables.append(table_name)


def test_research_note_report_card_revision_metadata() -> None:
    module = _load_migration_module()

    assert module.revision == RESEARCH_NOTE_REPORT_CARD_REVISION
    assert module.down_revision == RESEARCH_REPORT_CARD_REVISION


def test_research_note_report_card_migration_upgrade_scope(
    monkeypatch: Any,
) -> None:
    module = _load_migration_module()
    recorder = RecordingOp()
    monkeypatch.setattr(module, "op", recorder)

    module.upgrade()

    assert [table_name for table_name, _elements in recorder.created_tables] == [
        "research_note_report_cards"
    ]
    assert recorder.created_indexes == [
        (
            "ix_research_note_report_cards_report_card_id",
            "research_note_report_cards",
            ("report_card_id",),
        )
    ]

    elements = recorder.created_tables[0][1]
    primary_keys = [
        element for element in elements if isinstance(element, PrimaryKeyConstraint)
    ]
    assert len(primary_keys) == 1
    assert primary_keys[0].name == "pk_research_note_report_cards"
    assert tuple(primary_keys[0]._pending_colargs) == ("note_id", "report_card_id")

    foreign_keys = {
        element.name: (
            tuple(element.column_keys),
            tuple(fk.target_fullname for fk in element.elements),
            tuple(element.ondelete or "" for _fk in element.elements),
        )
        for element in elements
        if isinstance(element, ForeignKeyConstraint)
    }
    assert foreign_keys == {
        "fk_note_report_cards_note_id": (
            ("note_id",),
            ("research_notes.note_id",),
            ("",),
        ),
        "fk_note_report_cards_report_card_id": (
            ("report_card_id",),
            ("research_report_cards.report_card_id",),
            ("",),
        ),
    }
    assert all(len(name) < 63 for name in foreign_keys)


def test_research_note_report_card_migration_downgrade_scope(
    monkeypatch: Any,
) -> None:
    module = _load_migration_module()
    recorder = RecordingOp()
    monkeypatch.setattr(module, "op", recorder)

    module.downgrade()

    assert recorder.dropped_indexes == [
        (
            "ix_research_note_report_cards_report_card_id",
            "research_note_report_cards",
        )
    ]
    assert recorder.dropped_tables == ["research_note_report_cards"]


def _load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "research_note_report_card_migration",
        MIGRATION_PATH,
    )
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
