"""Alembic environment for quant platform persistence migrations."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import research_sdk.persistence.tables  # noqa: F401
from research_sdk.persistence.database import get_database_url
from research_sdk.persistence.metadata import metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata

ALEMBIC_PLACEHOLDER_DATABASE_URL = "driver://user:pass@localhost/dbname"


def _database_url() -> str:
    """Read the migration database URL without logging the secret value."""

    configured_url = (config.get_main_option("sqlalchemy.url") or "").strip()
    if configured_url and configured_url != ALEMBIC_PLACEHOLDER_DATABASE_URL:
        return configured_url

    return get_database_url()


def run_migrations_offline() -> None:
    """Run migrations in offline mode."""

    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode."""

    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
