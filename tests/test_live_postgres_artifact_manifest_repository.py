from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Never

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, func, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from live_postgres_safety import (
    QUANT_RUN_LIVE_DB_TESTS_ENV_VAR,
    QUANT_TEST_DATABASE_URL_ENV_VAR,
    UnsafePostgresTestUrl,
    get_quant_test_database_url,
    should_run_live_db_tests,
    validate_safe_postgres_test_url,
)
from research_sdk.contracts import RunArtifactManifest
from research_sdk.persistence.errors import (
    AggregateIntegrityError,
    ContractHashConflictError,
    UnsupportedVersioningConflictError,
)
from research_sdk.persistence.hashing import contract_sha256
from research_sdk.persistence.mappers import run_artifact_manifest_to_rows
from research_sdk.persistence.results import PersistenceDisposition
from research_sdk.persistence.sqlalchemy_repository import (
    SqlAlchemyExperimentLedgerRepository,
)
from research_sdk.persistence.tables import (
    run_artifact_entries,
    run_artifact_manifests,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "contracts"
TRANSACTION_REQUIRED_MESSAGE = (
    "repository write requires an active caller-owned transaction"
)


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
def run_artifact_manifest() -> RunArtifactManifest:
    return _run_artifact_manifest_with(run_id="run-pr37-live-vertical-slice")


@pytest.mark.live_db
def test_record_run_artifact_manifest_requires_active_transaction(
    migrated_engine: Engine,
) -> None:
    manifest_id = "manifest-pr37-transaction-required"
    manifest = _run_artifact_manifest_with(run_id="run-pr37-transaction-required")

    with migrated_engine.connect() as connection:
        repository = SqlAlchemyExperimentLedgerRepository(connection)

        assert connection.in_transaction() is False
        with pytest.raises(RuntimeError, match=TRANSACTION_REQUIRED_MESSAGE):
            repository.record_run_artifact_manifest(
                manifest_id=manifest_id,
                manifest=manifest,
            )
        assert connection.in_transaction() is False

    assert _count_manifest_rows(migrated_engine, manifest_id) == 0
    assert _count_entry_rows(migrated_engine, manifest_id) == 0


@pytest.mark.live_db
def test_record_run_artifact_manifest_created_and_caller_rollback(
    migrated_engine: Engine,
    run_artifact_manifest: RunArtifactManifest,
) -> None:
    manifest_id = "manifest-pr37-created"
    expected_hash = contract_sha256(run_artifact_manifest)
    expected_rows = run_artifact_manifest_to_rows(
        manifest_id=manifest_id,
        manifest=run_artifact_manifest,
    )

    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            repository = SqlAlchemyExperimentLedgerRepository(connection)

            created = repository.record_run_artifact_manifest(
                manifest_id=manifest_id,
                manifest=run_artifact_manifest,
            )

            assert created.disposition is PersistenceDisposition.CREATED
            assert created.record.table_name == "run_artifact_manifests"
            assert created.record.primary_key == {"manifest_id": manifest_id}
            assert created.record.contract_hash == expected_hash
            assert created.record.inserted_at is not None
            assert created.record.inserted_at.tzinfo is not None
            assert created.record.inserted_at.utcoffset() is not None
            assert created.aggregate_entry_count == len(run_artifact_manifest.artifacts)
            assert _count_manifest_rows_in_connection(connection, manifest_id) == 1
            assert _count_entry_rows_in_connection(connection, manifest_id) == (
                len(run_artifact_manifest.artifacts)
            )

            stored_parent = _stored_manifest_row(connection, manifest_id)
            assert stored_parent["manifest_id"] == manifest_id
            assert stored_parent["run_id"] == run_artifact_manifest.run_id
            assert stored_parent["contract_hash"] == expected_hash
            assert stored_parent["raw_contract"] == (
                run_artifact_manifest.model_dump(mode="json")
            )
            assert _stored_entry_projection(connection, manifest_id) == (
                _expected_entry_projection(expected_rows.entries)
            )
        finally:
            transaction.rollback()

    assert _count_manifest_rows(migrated_engine, manifest_id) == 0
    assert _count_entry_rows(migrated_engine, manifest_id) == 0


@pytest.mark.live_db
def test_record_run_artifact_manifest_exact_replay_preserves_aggregate(
    migrated_engine: Engine,
    run_artifact_manifest: RunArtifactManifest,
) -> None:
    manifest_id = "manifest-pr37-replayed"
    expected_hash = contract_sha256(run_artifact_manifest)

    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            repository = SqlAlchemyExperimentLedgerRepository(connection)
            created = repository.record_run_artifact_manifest(
                manifest_id=manifest_id,
                manifest=run_artifact_manifest,
            )
            original_parent = _stored_manifest_row(connection, manifest_id)
            original_entries = _stored_entry_rows(connection, manifest_id)

            replayed = repository.record_run_artifact_manifest(
                manifest_id=manifest_id,
                manifest=run_artifact_manifest,
            )

            assert replayed.disposition is PersistenceDisposition.REPLAYED
            assert replayed.record.primary_key == {"manifest_id": manifest_id}
            assert replayed.record.contract_hash == expected_hash
            assert replayed.record.inserted_at == created.record.inserted_at
            assert replayed.aggregate_entry_count == len(original_entries)
            assert _count_manifest_rows_in_connection(connection, manifest_id) == 1
            assert _stored_manifest_row(connection, manifest_id) == original_parent
            assert _stored_entry_rows(connection, manifest_id) == original_entries
        finally:
            transaction.rollback()

    assert _count_manifest_rows(migrated_engine, manifest_id) == 0
    assert _count_entry_rows(migrated_engine, manifest_id) == 0


@pytest.mark.live_db
def test_record_run_artifact_manifest_same_id_different_hash_conflicts(
    migrated_engine: Engine,
    run_artifact_manifest: RunArtifactManifest,
) -> None:
    manifest_id = "manifest-pr37-hash-conflict"
    changed_root = "artifacts/run-pr37-live-vertical-slice-conflict"
    conflicting_manifest = _manifest_with_updates(
        run_artifact_manifest,
        artifact_root_uri=changed_root,
    )
    original_hash = contract_sha256(run_artifact_manifest)
    conflicting_hash = contract_sha256(conflicting_manifest)

    assert conflicting_manifest.run_id == run_artifact_manifest.run_id
    assert conflicting_hash != original_hash

    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            repository = SqlAlchemyExperimentLedgerRepository(connection)
            repository.record_run_artifact_manifest(
                manifest_id=manifest_id,
                manifest=run_artifact_manifest,
            )
            original_parent = _stored_manifest_row(connection, manifest_id)
            original_entries = _stored_entry_rows(connection, manifest_id)

            with pytest.raises(ContractHashConflictError) as exc_info:
                repository.record_run_artifact_manifest(
                    manifest_id=manifest_id,
                    manifest=conflicting_manifest,
                )

            error = exc_info.value
            assert error.context.table_name == "run_artifact_manifests"
            assert error.context.operation == "record_run_artifact_manifest"
            assert error.context.logical_identity == {"manifest_id": manifest_id}
            assert error.context.constraint_name == "pk_run_artifact_manifests"
            assert error.context.existing_hash_prefix == original_hash[:12]
            assert error.context.attempted_hash_prefix == conflicting_hash[:12]
            assert original_hash not in str(error)
            assert conflicting_hash not in str(error)
            assert changed_root not in str(error)
            assert "raw_contract" not in str(error)
            assert connection.in_transaction() is True
            assert _stored_manifest_row(connection, manifest_id) == original_parent
            assert _stored_entry_rows(connection, manifest_id) == original_entries
        finally:
            transaction.rollback()


@pytest.mark.live_db
def test_record_run_artifact_manifest_same_run_id_alias_conflicts(
    migrated_engine: Engine,
    run_artifact_manifest: RunArtifactManifest,
) -> None:
    manifest_id = "manifest-pr37-natural-conflict-original"
    alias_manifest_id = "manifest-pr37-natural-conflict-alias"

    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            repository = SqlAlchemyExperimentLedgerRepository(connection)
            repository.record_run_artifact_manifest(
                manifest_id=manifest_id,
                manifest=run_artifact_manifest,
            )
            original_parent = _stored_manifest_row(connection, manifest_id)
            original_entries = _stored_entry_rows(connection, manifest_id)

            with pytest.raises(UnsupportedVersioningConflictError) as exc_info:
                with connection.begin_nested():
                    repository.record_run_artifact_manifest(
                        manifest_id=alias_manifest_id,
                        manifest=run_artifact_manifest,
                    )

            error = exc_info.value
            assert error.context.table_name == "run_artifact_manifests"
            assert error.context.operation == "record_run_artifact_manifest"
            assert error.context.logical_identity == {
                "manifest_id": alias_manifest_id,
                "run_id": run_artifact_manifest.run_id,
            }
            assert error.context.constraint_name == "uq_run_artifact_manifests_run_id"
            assert error.context.existing_hash_prefix is None
            assert (
                error.context.attempted_hash_prefix
                == (contract_sha256(run_artifact_manifest)[:12])
            )
            assert isinstance(error.__cause__, IntegrityError)
            assert connection.in_transaction() is True
            assert _stored_manifest_row(connection, manifest_id) == original_parent
            assert _stored_entry_rows(connection, manifest_id) == original_entries
            assert (
                _count_manifest_rows_in_connection(connection, alias_manifest_id) == 0
            )
            assert _count_entry_rows_in_connection(connection, alias_manifest_id) == 0
        finally:
            transaction.rollback()


@pytest.mark.live_db
def test_record_run_artifact_manifest_changed_contract_same_run_id_conflicts(
    migrated_engine: Engine,
    run_artifact_manifest: RunArtifactManifest,
) -> None:
    manifest_id = "manifest-pr37-changed-natural-conflict-original"
    alias_manifest_id = "manifest-pr37-changed-natural-conflict-alias"
    changed_manifest = _manifest_with_updates(
        run_artifact_manifest,
        artifact_root_uri="artifacts/run-pr37-live-vertical-slice-versioning",
    )

    assert changed_manifest.run_id == run_artifact_manifest.run_id
    assert contract_sha256(changed_manifest) != contract_sha256(run_artifact_manifest)

    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            repository = SqlAlchemyExperimentLedgerRepository(connection)
            repository.record_run_artifact_manifest(
                manifest_id=manifest_id,
                manifest=run_artifact_manifest,
            )
            original_parent = _stored_manifest_row(connection, manifest_id)
            original_entries = _stored_entry_rows(connection, manifest_id)

            with pytest.raises(UnsupportedVersioningConflictError) as exc_info:
                with connection.begin_nested():
                    repository.record_run_artifact_manifest(
                        manifest_id=alias_manifest_id,
                        manifest=changed_manifest,
                    )

            assert type(exc_info.value) is UnsupportedVersioningConflictError
            assert not isinstance(exc_info.value, ContractHashConflictError)
            assert exc_info.value.context.constraint_name == (
                "uq_run_artifact_manifests_run_id"
            )
            assert connection.in_transaction() is True
            assert _stored_manifest_row(connection, manifest_id) == original_parent
            assert _stored_entry_rows(connection, manifest_id) == original_entries
        finally:
            transaction.rollback()


@pytest.mark.live_db
def test_record_run_artifact_manifest_replay_detects_parent_run_id_corruption(
    migrated_engine: Engine,
    run_artifact_manifest: RunArtifactManifest,
) -> None:
    manifest_id = "manifest-pr37-parent-run-id-corruption"
    corrupted_run_id = "run-pr37-corrupted-parent"

    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            repository = SqlAlchemyExperimentLedgerRepository(connection)
            repository.record_run_artifact_manifest(
                manifest_id=manifest_id,
                manifest=run_artifact_manifest,
            )
            original_entries = _stored_entry_rows(connection, manifest_id)
            connection.execute(
                update(run_artifact_manifests)
                .where(run_artifact_manifests.c.manifest_id == manifest_id)
                .values(run_id=corrupted_run_id)
            )
            corrupted_parent = _stored_manifest_row(connection, manifest_id)

            with pytest.raises(AggregateIntegrityError) as exc_info:
                repository.record_run_artifact_manifest(
                    manifest_id=manifest_id,
                    manifest=run_artifact_manifest,
                )

            error = exc_info.value
            assert error.context.table_name == "run_artifact_manifests"
            assert error.context.operation == "record_run_artifact_manifest"
            assert error.context.logical_identity == {"manifest_id": manifest_id}
            assert error.context.constraint_name is None
            assert error.context.existing_hash_prefix is None
            assert error.context.attempted_hash_prefix is None
            assert corrupted_run_id not in str(error)
            assert run_artifact_manifest.run_id not in str(error)
            assert "raw_contract" not in str(error)
            assert connection.in_transaction() is True
            assert _stored_manifest_row(connection, manifest_id) == corrupted_parent
            assert _stored_entry_rows(connection, manifest_id) == original_entries
        finally:
            transaction.rollback()

    assert _count_manifest_rows(migrated_engine, manifest_id) == 0
    assert _count_entry_rows(migrated_engine, manifest_id) == 0


@pytest.mark.live_db
def test_record_run_artifact_manifest_replay_detects_missing_entry(
    migrated_engine: Engine,
    run_artifact_manifest: RunArtifactManifest,
) -> None:
    manifest_id = "manifest-pr37-missing-entry"
    missing_artifact_id = run_artifact_manifest.artifacts[0].artifact_id

    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            repository = SqlAlchemyExperimentLedgerRepository(connection)
            repository.record_run_artifact_manifest(
                manifest_id=manifest_id,
                manifest=run_artifact_manifest,
            )
            connection.execute(
                delete(run_artifact_entries).where(
                    run_artifact_entries.c.manifest_id == manifest_id,
                    run_artifact_entries.c.artifact_id == missing_artifact_id,
                )
            )

            _assert_aggregate_integrity_failure(
                repository=repository,
                manifest_id=manifest_id,
                manifest=run_artifact_manifest,
            )
            assert _count_entry_rows_in_connection(connection, manifest_id) == (
                len(run_artifact_manifest.artifacts) - 1
            )
            assert (
                _count_entry_rows_in_connection(
                    connection,
                    manifest_id,
                    artifact_id=missing_artifact_id,
                )
                == 0
            )
            assert connection.in_transaction() is True
        finally:
            transaction.rollback()


@pytest.mark.live_db
def test_record_run_artifact_manifest_replay_detects_extra_entry(
    migrated_engine: Engine,
    run_artifact_manifest: RunArtifactManifest,
) -> None:
    manifest_id = "manifest-pr37-extra-entry"
    extra_artifact_id = "extra-diagnostic"

    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            repository = SqlAlchemyExperimentLedgerRepository(connection)
            repository.record_run_artifact_manifest(
                manifest_id=manifest_id,
                manifest=run_artifact_manifest,
            )
            rows = run_artifact_manifest_to_rows(
                manifest_id=manifest_id,
                manifest=run_artifact_manifest,
            )
            extra_entry = {
                **rows.entries[0],
                "artifact_id": extra_artifact_id,
                "artifact_kind": "diagnostic",
                "filename": "diagnostic.txt",
                "format": "text",
                "uri": "artifacts/run-pr37-live-vertical-slice/diagnostic.txt",
                "content_hash": "sha256:diagnostic",
            }
            connection.execute(insert(run_artifact_entries).values(extra_entry))

            _assert_aggregate_integrity_failure(
                repository=repository,
                manifest_id=manifest_id,
                manifest=run_artifact_manifest,
            )
            assert _count_entry_rows_in_connection(connection, manifest_id) == (
                len(run_artifact_manifest.artifacts) + 1
            )
            assert (
                _count_entry_rows_in_connection(
                    connection,
                    manifest_id,
                    artifact_id=extra_artifact_id,
                )
                == 1
            )
            assert connection.in_transaction() is True
        finally:
            transaction.rollback()


@pytest.mark.live_db
def test_record_run_artifact_manifest_replay_detects_changed_entry_field(
    migrated_engine: Engine,
    run_artifact_manifest: RunArtifactManifest,
) -> None:
    manifest_id = "manifest-pr37-changed-entry"
    changed_artifact_id = run_artifact_manifest.artifacts[0].artifact_id
    changed_filename = "changed-config.json"

    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            repository = SqlAlchemyExperimentLedgerRepository(connection)
            repository.record_run_artifact_manifest(
                manifest_id=manifest_id,
                manifest=run_artifact_manifest,
            )
            connection.execute(
                update(run_artifact_entries)
                .where(
                    run_artifact_entries.c.manifest_id == manifest_id,
                    run_artifact_entries.c.artifact_id == changed_artifact_id,
                )
                .values(filename=changed_filename)
            )

            _assert_aggregate_integrity_failure(
                repository=repository,
                manifest_id=manifest_id,
                manifest=run_artifact_manifest,
            )
            assert (
                _stored_entry_field(
                    connection,
                    manifest_id=manifest_id,
                    artifact_id=changed_artifact_id,
                    column_name="filename",
                )
                == changed_filename
            )
            assert connection.in_transaction() is True
        finally:
            transaction.rollback()


def _assert_aggregate_integrity_failure(
    *,
    repository: SqlAlchemyExperimentLedgerRepository,
    manifest_id: str,
    manifest: RunArtifactManifest,
) -> None:
    with pytest.raises(AggregateIntegrityError) as exc_info:
        repository.record_run_artifact_manifest(
            manifest_id=manifest_id,
            manifest=manifest,
        )

    error = exc_info.value
    assert error.context.table_name == "run_artifact_entries"
    assert error.context.operation == "record_run_artifact_manifest"
    assert error.context.logical_identity == {
        "manifest_id": manifest_id,
        "run_id": manifest.run_id,
    }
    assert error.context.constraint_name is None
    assert error.context.existing_hash_prefix is None
    assert error.context.attempted_hash_prefix is None

    message = str(error)
    assert "raw_contract" not in message
    for artifact in manifest.artifacts:
        assert artifact.artifact_id not in message
        assert artifact.uri not in message
        assert artifact.filename not in message
        if artifact.content_hash is not None:
            assert artifact.content_hash not in message


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


def _load_artifact_manifest_payload() -> dict[str, Any]:
    return json.loads(
        (FIXTURE_DIR / "run_artifact_manifest.json").read_text(encoding="utf-8")
    )


def _run_artifact_manifest_with(*, run_id: str) -> RunArtifactManifest:
    payload = _load_artifact_manifest_payload()
    payload["run_id"] = run_id
    payload["artifact_root_uri"] = f"artifacts/{run_id}"
    for artifact in payload["artifacts"]:
        artifact["uri"] = f"artifacts/{run_id}/{artifact['filename']}"
    return RunArtifactManifest.model_validate(payload)


def _manifest_with_updates(
    manifest: RunArtifactManifest,
    **updates: object,
) -> RunArtifactManifest:
    payload = manifest.model_dump(mode="json")
    payload.update(updates)
    return RunArtifactManifest.model_validate(payload)


def _count_manifest_rows(engine: Engine, manifest_id: str) -> int:
    with engine.connect() as connection:
        with connection.begin():
            return _count_manifest_rows_in_connection(connection, manifest_id)


def _count_manifest_rows_in_connection(
    connection: Connection,
    manifest_id: str,
) -> int:
    statement = (
        select(func.count())
        .select_from(run_artifact_manifests)
        .where(run_artifact_manifests.c.manifest_id == manifest_id)
    )
    return connection.execute(statement).scalar_one()


def _count_entry_rows(
    engine: Engine,
    manifest_id: str,
    *,
    artifact_id: str | None = None,
) -> int:
    with engine.connect() as connection:
        with connection.begin():
            return _count_entry_rows_in_connection(
                connection,
                manifest_id,
                artifact_id=artifact_id,
            )


def _count_entry_rows_in_connection(
    connection: Connection,
    manifest_id: str,
    *,
    artifact_id: str | None = None,
) -> int:
    statement = (
        select(func.count())
        .select_from(run_artifact_entries)
        .where(run_artifact_entries.c.manifest_id == manifest_id)
    )
    if artifact_id is not None:
        statement = statement.where(run_artifact_entries.c.artifact_id == artifact_id)
    return connection.execute(statement).scalar_one()


def _stored_manifest_row(
    connection: Connection,
    manifest_id: str,
) -> dict[str, Any]:
    statement = select(run_artifact_manifests).where(
        run_artifact_manifests.c.manifest_id == manifest_id
    )
    return dict(connection.execute(statement).mappings().one())


def _stored_entry_rows(
    connection: Connection,
    manifest_id: str,
) -> tuple[dict[str, Any], ...]:
    statement = (
        select(run_artifact_entries)
        .where(run_artifact_entries.c.manifest_id == manifest_id)
        .order_by(run_artifact_entries.c.artifact_id)
    )
    return tuple(dict(row) for row in connection.execute(statement).mappings())


def _stored_entry_projection(
    connection: Connection,
    manifest_id: str,
) -> tuple[dict[str, Any], ...]:
    rows = _stored_entry_rows(connection, manifest_id)
    return tuple(
        {
            key: _normalize_entry_value(key, value)
            for key, value in row.items()
            if key != "inserted_at"
        }
        for row in rows
    )


def _expected_entry_projection(
    entries: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    return tuple(sorted(entries, key=lambda entry: entry["artifact_id"]))


def _stored_entry_field(
    connection: Connection,
    *,
    manifest_id: str,
    artifact_id: str,
    column_name: str,
) -> object:
    statement = select(run_artifact_entries.c[column_name]).where(
        run_artifact_entries.c.manifest_id == manifest_id,
        run_artifact_entries.c.artifact_id == artifact_id,
    )
    return connection.execute(statement).scalar_one()


def _normalize_entry_value(column_name: str, value: object) -> object:
    if column_name != "created_at" or value is None:
        return value
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return value
