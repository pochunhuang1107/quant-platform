from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Final

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

QUANT_RUN_LIVE_DB_TESTS_ENV_VAR: Final = "QUANT_RUN_LIVE_DB_TESTS"
QUANT_TEST_DATABASE_URL_ENV_VAR: Final = "QUANT_TEST_DATABASE_URL"

ALLOWED_DRIVERNAME: Final = "postgresql+psycopg"
ALLOWED_HOSTS: Final = frozenset({"localhost", "127.0.0.1", "::1"})
FORBIDDEN_DATABASE_TERMS: Final = frozenset(
    {"prod", "production", "main", "primary", "live"}
)
FORBIDDEN_USERNAME_TERMS: Final = frozenset(
    {"prod", "production", "root", "admin", "postgres"}
)


class UnsafePostgresTestUrl(ValueError):
    """Raised when QUANT_TEST_DATABASE_URL is unsafe for local live tests."""


def should_run_live_db_tests(
    environ: Mapping[str, str] = os.environ,
) -> bool:
    """Return whether the explicit live DB opt-in flag is enabled."""

    return environ.get(QUANT_RUN_LIVE_DB_TESTS_ENV_VAR, "").strip() == "1"


def get_quant_test_database_url(
    environ: Mapping[str, str] = os.environ,
) -> str | None:
    """Return QUANT_TEST_DATABASE_URL without reading DATABASE_URL."""

    database_url = environ.get(QUANT_TEST_DATABASE_URL_ENV_VAR, "").strip()
    if not database_url:
        return None
    return database_url


def validate_safe_postgres_test_url(database_url: str) -> str:
    """Refuse non-local or production-looking Postgres test URLs."""

    try:
        parsed_url = make_url(database_url)
    except ArgumentError as exc:
        raise UnsafePostgresTestUrl(
            f"{QUANT_TEST_DATABASE_URL_ENV_VAR} must be a parseable local "
            "Postgres test URL."
        ) from exc

    if parsed_url.drivername != ALLOWED_DRIVERNAME:
        raise UnsafePostgresTestUrl(
            f"{QUANT_TEST_DATABASE_URL_ENV_VAR} must use driver {ALLOWED_DRIVERNAME}."
        )

    if parsed_url.host not in ALLOWED_HOSTS:
        raise UnsafePostgresTestUrl(
            f"{QUANT_TEST_DATABASE_URL_ENV_VAR} host must be a local test host."
        )

    database_name = parsed_url.database or ""
    database_name_lower = database_name.casefold()
    if "test" not in database_name_lower:
        raise UnsafePostgresTestUrl(
            f"{QUANT_TEST_DATABASE_URL_ENV_VAR} database name must contain test."
        )
    if _contains_forbidden_term(database_name_lower, FORBIDDEN_DATABASE_TERMS):
        raise UnsafePostgresTestUrl(
            f"{QUANT_TEST_DATABASE_URL_ENV_VAR} database name looks unsafe."
        )

    username = parsed_url.username or ""
    username_lower = username.casefold()
    if _contains_forbidden_term(username_lower, FORBIDDEN_USERNAME_TERMS):
        raise UnsafePostgresTestUrl(
            f"{QUANT_TEST_DATABASE_URL_ENV_VAR} username looks unsafe."
        )

    return database_url


def _contains_forbidden_term(value: str, forbidden_terms: frozenset[str]) -> bool:
    return any(term in value for term in forbidden_terms)
