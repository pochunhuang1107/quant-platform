from __future__ import annotations

import pytest

from live_postgres_safety import (
    QUANT_RUN_LIVE_DB_TESTS_ENV_VAR,
    QUANT_TEST_DATABASE_URL_ENV_VAR,
    UnsafePostgresTestUrl,
    get_quant_test_database_url,
    should_run_live_db_tests,
    validate_safe_postgres_test_url,
)

SAFE_LOCAL_URL = (
    "postgresql+psycopg://quant_test:quant_test@localhost:5432/quant_platform_test"
)


def test_safe_local_postgres_test_url_is_allowed() -> None:
    assert validate_safe_postgres_test_url(SAFE_LOCAL_URL) == SAFE_LOCAL_URL


def test_quant_test_database_url_missing_returns_none_without_reading_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(QUANT_TEST_DATABASE_URL_ENV_VAR, raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:secret@production.example/prod",
    )

    assert get_quant_test_database_url() is None


def test_live_db_flag_requires_explicit_one() -> None:
    assert should_run_live_db_tests({QUANT_RUN_LIVE_DB_TESTS_ENV_VAR: "1"})
    assert not should_run_live_db_tests({})
    assert not should_run_live_db_tests({QUANT_RUN_LIVE_DB_TESTS_ENV_VAR: "true"})
    assert not should_run_live_db_tests({QUANT_RUN_LIVE_DB_TESTS_ENV_VAR: "0"})


@pytest.mark.parametrize(
    "database_url",
    [
        "sqlite:///quant_platform_test.db",
        "postgresql://quant_test:quant_test@localhost:5432/quant_platform_test",
        "postgresql+asyncpg://quant_test:quant_test@localhost/quant_platform_test",
    ],
)
def test_rejects_non_psycopg_postgres_driver(database_url: str) -> None:
    assert_rejects_without_leaking_url(database_url)


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+psycopg://quant_test:quant_test@production-db/quant_test",
        "postgresql+psycopg://quant_test:quant_test@db.example.com/quant_test",
        "postgresql+psycopg://quant_test:quant_test@10.0.0.5/quant_test",
    ],
)
def test_rejects_non_local_hosts(database_url: str) -> None:
    assert_rejects_without_leaking_url(database_url)


@pytest.mark.parametrize(
    "database_name",
    [
        "prod",
        "production",
        "main",
        "live",
        "primary",
        "production_test",
    ],
)
def test_rejects_production_looking_database_names(database_name: str) -> None:
    database_url = (
        f"postgresql+psycopg://quant_test:quant_test@localhost:5432/{database_name}"
    )

    assert_rejects_without_leaking_url(database_url)


@pytest.mark.parametrize(
    "username",
    [
        "postgres",
        "admin",
        "root",
        "production_user",
        "prod_test_user",
    ],
)
def test_rejects_privileged_or_production_looking_usernames(username: str) -> None:
    database_url = (
        f"postgresql+psycopg://{username}:secret-password@localhost:5432/"
        "quant_platform_test"
    )

    assert_rejects_without_leaking_url(database_url)


def test_rejects_database_name_without_test() -> None:
    database_url = (
        "postgresql+psycopg://quant_user:secret-password@localhost:5432/research"
    )

    assert_rejects_without_leaking_url(database_url)


def test_rejects_unparseable_url_without_leaking_value() -> None:
    database_url = "not a database url with secret-password"

    assert_rejects_without_leaking_url(database_url)


def test_rejection_message_does_not_include_password_or_full_url() -> None:
    database_url = "postgresql+psycopg://postgres:secret-password@localhost:5432/prod"

    with pytest.raises(UnsafePostgresTestUrl) as exc_info:
        validate_safe_postgres_test_url(database_url)

    message = str(exc_info.value)
    assert "secret-password" not in message
    assert database_url not in message
    assert "postgres:secret-password" not in message


def assert_rejects_without_leaking_url(database_url: str) -> None:
    with pytest.raises(UnsafePostgresTestUrl) as exc_info:
        validate_safe_postgres_test_url(database_url)

    message = str(exc_info.value)
    assert database_url not in message
    assert "secret-password" not in message
