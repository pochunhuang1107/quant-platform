from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Never

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import NullPool

from live_postgres_safety import (
    QUANT_RUN_LIVE_DB_TESTS_ENV_VAR,
    QUANT_TEST_DATABASE_URL_ENV_VAR,
    UnsafePostgresTestUrl,
    get_quant_test_database_url,
    should_run_live_db_tests,
    validate_safe_postgres_test_url,
)
from research_sdk.contracts import ResearchNote, ReviewMetadata, RunArtifactManifest
from research_sdk.persistence.errors import ContractHashConflictError
from research_sdk.persistence.hashing import contract_sha256
from research_sdk.persistence.mappers import ReviewSubjectType
from research_sdk.persistence.results import (
    PersistenceDisposition,
    PersistenceWriteResult,
)
from research_sdk.persistence.sqlalchemy_repository import (
    SqlAlchemyExperimentLedgerRepository,
)
from research_sdk.persistence.tables import research_notes

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "contracts"
TRANSACTION_REQUIRED_MESSAGE = (
    "repository write requires an active caller-owned transaction"
)
SCOPE_MESSAGE = "repository execution is outside PR 35 research-note scope"


class _ResearchNoteRepository(SqlAlchemyExperimentLedgerRepository):
    __slots__ = ()

    def record_run_artifact_manifest(
        self,
        *,
        manifest_id: str,
        manifest: RunArtifactManifest,
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


@pytest.fixture(scope="module")
def database_url() -> str:
    return _require_live_database_url()


@pytest.fixture(scope="module")
def migrated_engine(database_url: str) -> Engine:
    alembic_config = Config(str(ALEMBIC_INI))
    alembic_config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(alembic_config, "head")

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def research_note() -> ResearchNote:
    return _research_note_with(note_id="note-pr35-live-vertical-slice")


@pytest.mark.live_db
def test_record_research_note_requires_active_transaction(
    migrated_engine: Engine,
) -> None:
    note = _research_note_with(note_id="note-pr35-live-transaction-required")

    with migrated_engine.connect() as connection:
        repository = _ResearchNoteRepository(connection)

        assert connection.in_transaction() is False
        with pytest.raises(RuntimeError, match=TRANSACTION_REQUIRED_MESSAGE):
            repository.record_research_note(note)
        assert connection.in_transaction() is False

    assert _count_research_notes(migrated_engine, note.note_id) == 0


@pytest.mark.live_db
def test_record_research_note_created_replayed_conflict_and_rollback(
    migrated_engine: Engine,
    research_note: ResearchNote,
) -> None:
    original_title = research_note.title
    conflicting_title = f"{original_title} conflict"
    conflicting_note = research_note.model_copy(update={"title": conflicting_title})
    original_hash = contract_sha256(research_note)
    conflicting_hash = contract_sha256(conflicting_note)
    linked_uri = next(iter(research_note.references.artifact_uris), None)

    assert conflicting_note.note_id == research_note.note_id
    assert conflicting_note.title != original_title
    assert conflicting_hash != original_hash

    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            repository = _ResearchNoteRepository(connection)

            created = repository.record_research_note(research_note)
            assert created.disposition is PersistenceDisposition.CREATED
            assert created.record.table_name == "research_notes"
            assert created.record.primary_key == {"note_id": research_note.note_id}
            assert created.record.contract_hash == original_hash
            assert created.record.inserted_at is not None
            assert created.record.inserted_at.tzinfo is not None
            assert created.record.inserted_at.utcoffset() is not None
            assert created.aggregate_entry_count is None
            assert (
                _count_research_notes_in_connection(
                    connection,
                    research_note.note_id,
                )
                == 1
            )

            original_inserted_at = created.record.inserted_at
            original_raw_contract = _stored_raw_contract(
                connection,
                research_note.note_id,
            )
            original_stored_updated_at = _stored_updated_at(
                connection,
                research_note.note_id,
            )
            assert original_stored_updated_at == research_note.updated_at
            assert _stored_inserted_at(connection, research_note.note_id) == (
                original_inserted_at
            )

            replayed = repository.record_research_note(research_note)
            assert replayed.disposition is PersistenceDisposition.REPLAYED
            assert replayed.record.primary_key == {"note_id": research_note.note_id}
            assert replayed.record.contract_hash == original_hash
            assert replayed.record.inserted_at == original_inserted_at
            assert replayed.aggregate_entry_count is None
            assert (
                _count_research_notes_in_connection(
                    connection,
                    research_note.note_id,
                )
                == 1
            )
            assert _stored_raw_contract(connection, research_note.note_id) == (
                original_raw_contract
            )
            assert _stored_updated_at(connection, research_note.note_id) == (
                original_stored_updated_at
            )

            with pytest.raises(ContractHashConflictError) as exc_info:
                repository.record_research_note(conflicting_note)

            error = exc_info.value
            assert error.context.table_name == "research_notes"
            assert error.context.operation == "record_research_note"
            assert error.context.logical_identity == {"note_id": research_note.note_id}
            assert error.context.constraint_name == "pk_research_notes"
            assert error.context.existing_hash_prefix == original_hash[:12]
            assert error.context.attempted_hash_prefix == conflicting_hash[:12]
            assert original_hash not in str(error)
            assert conflicting_hash not in str(error)
            assert original_title not in str(error)
            assert conflicting_title not in str(error)
            assert "raw_contract" not in str(error)
            if linked_uri is not None:
                assert linked_uri not in str(error)
            assert connection.in_transaction() is True
            assert (
                _count_research_notes_in_connection(
                    connection,
                    research_note.note_id,
                )
                == 1
            )
            assert _stored_contract_hash(connection, research_note.note_id) == (
                original_hash
            )
            assert _stored_raw_contract(connection, research_note.note_id) == (
                original_raw_contract
            )
            assert _stored_inserted_at(connection, research_note.note_id) == (
                original_inserted_at
            )
            assert _stored_updated_at(connection, research_note.note_id) == (
                original_stored_updated_at
            )
        finally:
            transaction.rollback()

    assert _count_research_notes(migrated_engine, research_note.note_id) == 0


def _require_live_database_url() -> str:
    if not should_run_live_db_tests():
        pytest.skip(f"set {QUANT_RUN_LIVE_DB_TESTS_ENV_VAR}=1 to run live DB tests")

    database_url = get_quant_test_database_url()
    if database_url is None:
        pytest.skip(f"{QUANT_TEST_DATABASE_URL_ENV_VAR} is not set")

    try:
        return validate_safe_postgres_test_url(database_url)
    except UnsafePostgresTestUrl as exc:
        _fail_without_traceback(str(exc))


def _fail_without_traceback(message: str) -> Never:
    pytest.fail(message, pytrace=False)


def _load_research_note_payload() -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / "research_note.json").read_text(encoding="utf-8"))


def _research_note_with(*, note_id: str) -> ResearchNote:
    note = ResearchNote.model_validate(_load_research_note_payload())
    return note.model_copy(update={"note_id": note_id})


def _count_research_notes(engine: Engine, note_id: str) -> int:
    with engine.connect() as connection:
        with connection.begin():
            return _count_research_notes_in_connection(connection, note_id)


def _count_research_notes_in_connection(
    connection: Connection,
    note_id: str,
) -> int:
    statement = (
        select(func.count())
        .select_from(research_notes)
        .where(research_notes.c.note_id == note_id)
    )
    return connection.execute(statement).scalar_one()


def _stored_contract_hash(connection: Connection, note_id: str) -> str:
    statement = select(research_notes.c.contract_hash).where(
        research_notes.c.note_id == note_id
    )
    return connection.execute(statement).scalar_one()


def _stored_raw_contract(connection: Connection, note_id: str) -> dict[str, Any]:
    statement = select(research_notes.c.raw_contract).where(
        research_notes.c.note_id == note_id
    )
    return connection.execute(statement).scalar_one()


def _stored_inserted_at(connection: Connection, note_id: str) -> object:
    statement = select(research_notes.c.inserted_at).where(
        research_notes.c.note_id == note_id
    )
    return connection.execute(statement).scalar_one()


def _stored_updated_at(connection: Connection, note_id: str) -> datetime:
    statement = select(research_notes.c.updated_at).where(
        research_notes.c.note_id == note_id
    )
    return connection.execute(statement).scalar_one()
