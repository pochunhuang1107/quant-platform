from __future__ import annotations

import json
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
from research_sdk.contracts import (
    DataSnapshotManifest,
    ResearchNote,
    ReviewMetadata,
    RunArtifactManifest,
)
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
from research_sdk.persistence.tables import data_snapshot_manifests

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "contracts"
TRANSACTION_REQUIRED_MESSAGE = (
    "repository write requires an active caller-owned transaction"
)
SCOPE_MESSAGE = "repository execution is outside PR 34 data-snapshot scope"


class _DataSnapshotRepository(SqlAlchemyExperimentLedgerRepository):
    __slots__ = ()

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
def data_snapshot_manifest() -> DataSnapshotManifest:
    return _data_snapshot_manifest_with(snapshot_id="snapshot-pr34-live-vertical-slice")


@pytest.mark.live_db
def test_record_data_snapshot_manifest_requires_active_transaction(
    migrated_engine: Engine,
) -> None:
    snapshot = _data_snapshot_manifest_with(
        snapshot_id="snapshot-pr34-live-transaction-required"
    )

    with migrated_engine.connect() as connection:
        repository = _DataSnapshotRepository(connection)

        assert connection.in_transaction() is False
        with pytest.raises(RuntimeError, match=TRANSACTION_REQUIRED_MESSAGE):
            repository.record_data_snapshot_manifest(snapshot)
        assert connection.in_transaction() is False

    assert _count_data_snapshot_manifests(migrated_engine, snapshot.snapshot_id) == 0


@pytest.mark.live_db
def test_record_data_snapshot_manifest_created_replayed_conflict_and_rollback(
    migrated_engine: Engine,
    data_snapshot_manifest: DataSnapshotManifest,
) -> None:
    conflicting_snapshot = data_snapshot_manifest.model_copy(
        update={"source_version": "2026-07-10"}
    )
    original_hash = contract_sha256(data_snapshot_manifest)
    conflicting_hash = contract_sha256(conflicting_snapshot)

    assert conflicting_snapshot.snapshot_id == data_snapshot_manifest.snapshot_id
    assert conflicting_hash != original_hash

    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            repository = _DataSnapshotRepository(connection)

            created = repository.record_data_snapshot_manifest(data_snapshot_manifest)
            assert created.disposition is PersistenceDisposition.CREATED
            assert created.record.table_name == "data_snapshot_manifests"
            assert created.record.primary_key == {
                "snapshot_id": data_snapshot_manifest.snapshot_id
            }
            assert created.record.contract_hash == original_hash
            assert created.record.inserted_at is not None
            assert created.record.inserted_at.tzinfo is not None
            assert created.record.inserted_at.utcoffset() is not None
            assert created.aggregate_entry_count is None
            assert (
                _count_data_snapshot_manifests_in_connection(
                    connection,
                    data_snapshot_manifest.snapshot_id,
                )
                == 1
            )

            original_inserted_at = created.record.inserted_at
            original_raw_contract = _stored_raw_contract(
                connection,
                data_snapshot_manifest.snapshot_id,
            )

            replayed = repository.record_data_snapshot_manifest(data_snapshot_manifest)
            assert replayed.disposition is PersistenceDisposition.REPLAYED
            assert replayed.record.primary_key == {
                "snapshot_id": data_snapshot_manifest.snapshot_id
            }
            assert replayed.record.contract_hash == original_hash
            assert replayed.record.inserted_at == original_inserted_at
            assert replayed.aggregate_entry_count is None
            assert (
                _count_data_snapshot_manifests_in_connection(
                    connection,
                    data_snapshot_manifest.snapshot_id,
                )
                == 1
            )
            assert (
                _stored_raw_contract(
                    connection,
                    data_snapshot_manifest.snapshot_id,
                )
                == original_raw_contract
            )

            with pytest.raises(ContractHashConflictError) as exc_info:
                repository.record_data_snapshot_manifest(conflicting_snapshot)

            error = exc_info.value
            assert error.context.table_name == "data_snapshot_manifests"
            assert error.context.operation == "record_data_snapshot_manifest"
            assert error.context.logical_identity == {
                "snapshot_id": data_snapshot_manifest.snapshot_id
            }
            assert error.context.constraint_name == "pk_data_snapshot_manifests"
            assert error.context.existing_hash_prefix == original_hash[:12]
            assert error.context.attempted_hash_prefix == conflicting_hash[:12]
            assert original_hash not in str(error)
            assert conflicting_hash not in str(error)
            assert "raw_contract" not in str(error)
            assert data_snapshot_manifest.data_root_uri not in str(error)
            assert "vendor_name" not in str(error)
            assert connection.in_transaction() is True
            assert (
                _count_data_snapshot_manifests_in_connection(
                    connection,
                    data_snapshot_manifest.snapshot_id,
                )
                == 1
            )
            assert (
                _stored_contract_hash(
                    connection,
                    data_snapshot_manifest.snapshot_id,
                )
                == original_hash
            )
            assert (
                _stored_raw_contract(
                    connection,
                    data_snapshot_manifest.snapshot_id,
                )
                == original_raw_contract
            )
            assert (
                _stored_inserted_at(
                    connection,
                    data_snapshot_manifest.snapshot_id,
                )
                == original_inserted_at
            )
        finally:
            transaction.rollback()

    assert (
        _count_data_snapshot_manifests(
            migrated_engine,
            data_snapshot_manifest.snapshot_id,
        )
        == 0
    )


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


def _load_data_snapshot_payload() -> dict[str, Any]:
    return json.loads(
        (FIXTURE_DIR / "data_snapshot_manifest.json").read_text(encoding="utf-8")
    )


def _data_snapshot_manifest_with(*, snapshot_id: str) -> DataSnapshotManifest:
    snapshot = DataSnapshotManifest.model_validate(_load_data_snapshot_payload())
    return snapshot.model_copy(update={"snapshot_id": snapshot_id})


def _count_data_snapshot_manifests(engine: Engine, snapshot_id: str) -> int:
    with engine.connect() as connection:
        with connection.begin():
            return _count_data_snapshot_manifests_in_connection(
                connection,
                snapshot_id,
            )


def _count_data_snapshot_manifests_in_connection(
    connection: Connection,
    snapshot_id: str,
) -> int:
    statement = (
        select(func.count())
        .select_from(data_snapshot_manifests)
        .where(data_snapshot_manifests.c.snapshot_id == snapshot_id)
    )
    return connection.execute(statement).scalar_one()


def _stored_contract_hash(connection: Connection, snapshot_id: str) -> str:
    statement = select(data_snapshot_manifests.c.contract_hash).where(
        data_snapshot_manifests.c.snapshot_id == snapshot_id
    )
    return connection.execute(statement).scalar_one()


def _stored_raw_contract(connection: Connection, snapshot_id: str) -> dict[str, Any]:
    statement = select(data_snapshot_manifests.c.raw_contract).where(
        data_snapshot_manifests.c.snapshot_id == snapshot_id
    )
    return connection.execute(statement).scalar_one()


def _stored_inserted_at(connection: Connection, snapshot_id: str) -> object:
    statement = select(data_snapshot_manifests.c.inserted_at).where(
        data_snapshot_manifests.c.snapshot_id == snapshot_id
    )
    return connection.execute(statement).scalar_one()
