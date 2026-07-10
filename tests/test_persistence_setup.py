from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData

from research_sdk.persistence import database
from research_sdk.persistence.metadata import metadata

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
BASELINE_REVISION = "0001_persistence_baseline"


def test_persistence_metadata_is_empty_sqlalchemy_metadata() -> None:
    assert isinstance(metadata, MetaData)
    assert metadata.tables == {}


def test_persistence_metadata_has_stable_naming_convention() -> None:
    assert metadata.naming_convention == {
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }


def test_get_database_url_returns_environment_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/db")

    assert database.get_database_url() == "postgresql://example.invalid/db"


@pytest.mark.parametrize("database_url", [None, "", "   "])
def test_get_database_url_raises_when_missing_or_empty(
    monkeypatch: pytest.MonkeyPatch,
    database_url: str | None,
) -> None:
    if database_url is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", database_url)

    with pytest.raises(RuntimeError, match="DATABASE_URL must be set"):
        database.get_database_url()


def test_alembic_config_points_to_migration_directory() -> None:
    config = Config(str(ALEMBIC_INI))

    assert config.get_main_option("script_location") == "infra/db/migrations"


def test_alembic_script_directory_has_empty_baseline_head() -> None:
    config = Config(str(ALEMBIC_INI))
    script = ScriptDirectory.from_config(config)

    heads = script.get_heads()
    assert heads == [BASELINE_REVISION]

    baseline = script.get_revision(BASELINE_REVISION)
    assert baseline is not None
    assert baseline.down_revision is None
