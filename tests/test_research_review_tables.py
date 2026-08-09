from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKeyConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import CreateIndex, CreateTable

from research_sdk.persistence.metadata import metadata
from research_sdk.persistence.tables import (
    LEDGER_TABLES,
    REPORT_CARD_TABLES,
    RESEARCH_REVIEW_TABLES,
    research_notes,
    research_report_cards,
    review_events,
)

EXPECTED_TABLE_NAMES = {
    "experiment_runs",
    "data_snapshot_manifests",
    "run_artifact_manifests",
    "run_artifact_entries",
    "research_report_cards",
    "research_notes",
    "review_events",
}

EXPECTED_RESEARCH_NOTE_COLUMNS = {
    "note_id",
    "schema_version",
    "note_type",
    "status",
    "created_at",
    "created_by",
    "updated_at",
    "updated_by",
    "title",
    "hypothesis_status",
    "evidence_strength",
    "decision_outcome",
    "parent_note_id",
    "supersedes_note_id",
    "review_status",
    "reviewer_id",
    "review_role",
    "reviewed_at",
    "risk_approval_required",
    "contract_hash",
    "raw_contract",
    "inserted_at",
}

EXPECTED_REVIEW_EVENT_COLUMNS = {
    "review_event_id",
    "subject_type",
    "subject_id",
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
    "raw_review",
    "inserted_at",
}

NULLABLE_RESEARCH_NOTE_COLUMNS = {
    "parent_note_id",
    "supersedes_note_id",
    "reviewer_id",
    "review_role",
    "reviewed_at",
}

NULLABLE_REVIEW_EVENT_COLUMNS = {
    "reviewer_id",
    "review_role",
    "reviewed_at",
    "decision",
    "approval_scope",
    "approval_expires_at",
    "linked_pr",
    "review_notes_uri",
}

EXPECTED_RESEARCH_NOTE_CHECKS = {
    "ck_research_notes_parent_note_id_not_self",
    "ck_research_notes_supersedes_note_id_not_self",
    "ck_research_notes_note_type_values",
    "ck_research_notes_status_values",
    "ck_research_notes_hypothesis_status_values",
    "ck_research_notes_evidence_strength_values",
    "ck_research_notes_decision_outcome_values",
    "ck_research_notes_review_status_values",
    "ck_research_notes_review_role_values",
}

EXPECTED_REVIEW_EVENT_CHECKS = {
    "ck_review_events_subject_type_values",
    "ck_review_events_review_status_values",
    "ck_review_events_review_role_values",
}

EXPECTED_REPORT_CARD_FOREIGN_KEYS = {
    "fk_report_cards_source_run_id": (
        ("source_run_id",),
        "experiment_runs",
        ("run_id",),
    ),
    "fk_report_cards_data_snapshot_id": (
        ("data_snapshot_id",),
        "data_snapshot_manifests",
        ("snapshot_id",),
    ),
    "fk_report_cards_benchmark_snapshot_id": (
        ("benchmark_snapshot_id",),
        "data_snapshot_manifests",
        ("snapshot_id",),
    ),
    "fk_report_cards_artifact_manifest_id": (
        ("artifact_manifest_id",),
        "run_artifact_manifests",
        ("manifest_id",),
    ),
}

EXPECTED_INDEXES = {
    "research_notes": {
        "ix_research_notes_status_updated_at": ("status", "updated_at"),
        "ix_research_notes_note_type_created_at": ("note_type", "created_at"),
        "ix_research_notes_review_status_updated_at": (
            "review_status",
            "updated_at",
        ),
        "ix_research_notes_decision_outcome_updated_at": (
            "decision_outcome",
            "updated_at",
        ),
        "ix_research_notes_parent_note_id": ("parent_note_id",),
        "ix_research_notes_supersedes_note_id": ("supersedes_note_id",),
    },
    "review_events": {
        "ix_review_events_subject_type_subject_id_inserted_at": (
            "subject_type",
            "subject_id",
            "inserted_at",
        ),
        "ix_review_events_reviewer_id_inserted_at": (
            "reviewer_id",
            "inserted_at",
        ),
        "ix_review_events_review_status_inserted_at": (
            "review_status",
            "inserted_at",
        ),
    },
}


def test_metadata_contains_current_approved_ledger_tables_only() -> None:
    assert set(metadata.tables) == EXPECTED_TABLE_NAMES
    assert REPORT_CARD_TABLES == (research_report_cards,)
    assert RESEARCH_REVIEW_TABLES == (
        research_notes,
        review_events,
    )
    assert LEDGER_TABLES[-2:] == RESEARCH_REVIEW_TABLES
    assert LEDGER_TABLES[-3] is research_report_cards


def test_research_review_tables_have_expected_columns() -> None:
    assert set(research_notes.c.keys()) == EXPECTED_RESEARCH_NOTE_COLUMNS
    assert set(review_events.c.keys()) == EXPECTED_REVIEW_EVENT_COLUMNS


def test_research_review_table_nullability_matches_scope() -> None:
    for column in research_notes.c:
        expected_nullable = column.name in NULLABLE_RESEARCH_NOTE_COLUMNS
        assert column.nullable is expected_nullable

    for column in review_events.c:
        expected_nullable = column.name in NULLABLE_REVIEW_EVENT_COLUMNS
        assert column.nullable is expected_nullable


def test_research_review_table_primary_keys_match_contract_ids() -> None:
    assert [column.name for column in research_notes.primary_key] == ["note_id"]
    assert [column.name for column in review_events.primary_key] == ["review_event_id"]


def test_research_review_json_columns_use_postgresql_jsonb() -> None:
    assert isinstance(research_notes.c.raw_contract.type, JSONB)
    assert isinstance(review_events.c.raw_review.type, JSONB)


def test_research_review_inserted_at_columns_have_server_defaults() -> None:
    assert research_notes.c.inserted_at.server_default is not None
    assert review_events.c.inserted_at.server_default is not None


def test_research_review_check_constraints_are_named() -> None:
    research_note_checks = {
        constraint.name
        for constraint in research_notes.constraints
        if isinstance(constraint, CheckConstraint)
    }
    review_event_checks = {
        constraint.name
        for constraint in review_events.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert research_note_checks == EXPECTED_RESEARCH_NOTE_CHECKS
    assert review_event_checks == EXPECTED_REVIEW_EVENT_CHECKS


def test_research_review_indexes_are_named_and_target_expected_columns() -> None:
    for table in RESEARCH_REVIEW_TABLES:
        actual_indexes = {
            index.name: tuple(column.name for column in index.columns)
            for index in table.indexes
        }

        assert actual_indexes == EXPECTED_INDEXES[table.name]


def test_research_review_tables_have_no_foreign_keys() -> None:
    assert list(research_notes.foreign_key_constraints) == []
    assert list(review_events.foreign_key_constraints) == []
    assert all(column.foreign_keys == set() for column in research_notes.c)
    assert all(column.foreign_keys == set() for column in review_events.c)


def test_research_report_card_foreign_keys_target_current_tables() -> None:
    actual_foreign_keys = {
        constraint.name: (
            tuple(element.parent.name for element in constraint.elements),
            next(iter(constraint.elements)).column.table.name,
            tuple(element.column.name for element in constraint.elements),
        )
        for constraint in research_report_cards.foreign_key_constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }

    assert actual_foreign_keys == EXPECTED_REPORT_CARD_FOREIGN_KEYS


def test_research_review_tables_compile_for_postgresql_without_connection() -> None:
    dialect = postgresql.dialect()

    for table in RESEARCH_REVIEW_TABLES:
        compiled_table = str(CreateTable(table).compile(dialect=dialect))
        assert f"CREATE TABLE {table.name}" in compiled_table
        assert "JSONB" in compiled_table

        for index in table.indexes:
            compiled_index = str(CreateIndex(index).compile(dialect=dialect))
            assert f"CREATE INDEX {index.name}" in compiled_index


def test_research_report_card_table_compiles_for_postgresql_without_connection() -> (
    None
):
    dialect = postgresql.dialect()

    compiled_table = str(CreateTable(research_report_cards).compile(dialect=dialect))
    assert "CREATE TABLE research_report_cards" in compiled_table

    for constraint in research_report_cards.constraints:
        assert constraint.name is not None
        assert len(constraint.name) <= dialect.max_identifier_length

    for index in research_report_cards.indexes:
        assert index.name is not None
        assert len(index.name) <= dialect.max_identifier_length
        compiled_index = str(CreateIndex(index).compile(dialect=dialect))
        assert f"CREATE INDEX {index.name}" in compiled_index
