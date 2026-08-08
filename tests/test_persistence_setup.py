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
LEDGER_ANCHOR_REVISION = "0002_ledger_anchor_tables"
ARTIFACT_REVISION = "0003_artifact_tables"
RESEARCH_REVIEW_REVISION = "0004_research_review_tables"
ARTIFACT_MANIFEST_RUN_IDENTITY_REVISION = "0005_artifact_run_identity"
RESEARCH_REPORT_CARD_REVISION = "0006_research_report_cards"


def test_persistence_metadata_is_sqlalchemy_metadata() -> None:
    assert isinstance(metadata, MetaData)


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


def test_alembic_script_directory_has_artifact_manifest_run_identity_head() -> None:
    config = Config(str(ALEMBIC_INI))
    script = ScriptDirectory.from_config(config)

    heads = script.get_heads()
    assert heads == [RESEARCH_REPORT_CARD_REVISION]

    baseline = script.get_revision(BASELINE_REVISION)
    assert baseline is not None
    assert baseline.down_revision is None

    ledger_anchor = script.get_revision(LEDGER_ANCHOR_REVISION)
    assert ledger_anchor is not None
    assert ledger_anchor.down_revision == BASELINE_REVISION

    artifact_tables = script.get_revision(ARTIFACT_REVISION)
    assert artifact_tables is not None
    assert artifact_tables.down_revision == LEDGER_ANCHOR_REVISION

    research_review_tables = script.get_revision(RESEARCH_REVIEW_REVISION)
    assert research_review_tables is not None
    assert research_review_tables.down_revision == ARTIFACT_REVISION

    artifact_manifest_run_identity = script.get_revision(
        ARTIFACT_MANIFEST_RUN_IDENTITY_REVISION
    )
    assert artifact_manifest_run_identity is not None
    assert artifact_manifest_run_identity.down_revision == RESEARCH_REVIEW_REVISION

    report_card_revision = script.get_revision(RESEARCH_REPORT_CARD_REVISION)
    assert report_card_revision is not None
    assert report_card_revision.down_revision == ARTIFACT_MANIFEST_RUN_IDENTITY_REVISION
