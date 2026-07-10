# Persistence Setup

## Purpose

This document describes the minimal Phase 1 persistence tooling setup. This PR
prepares SQLAlchemy and Alembic for future experiment ledger persistence work,
but it does not create ledger tables or persistence write paths.

## What This Adds

- SQLAlchemy as the future database schema and migration metadata dependency.
- Alembic as the migration tooling dependency.
- A `research_sdk.persistence` package with SQLAlchemy Core metadata.
- Alembic configuration under `infra/db/migrations/`.
- An empty baseline Alembic revision.
- Tests that inspect metadata and Alembic revision configuration without a live
  database.

## What This Does Not Add

This setup does not add `experiment_runs`, `data_snapshot_manifests`,
`run_artifact_manifests`, `run_artifact_entries`, `research_notes`, or
`review_events`.

It also does not add ORM models, repositories, DAOs, DB write paths, FastAPI
endpoints, backtest integration, artifact IO, data ingestion, vendor API calls,
storage IO, file existence checks, hash verification, UI/editor behavior,
embeddings, semantic memory, knowledge graph behavior, search/indexing, LLM
summarization, agent workflow execution, broker integration, live trading, paper
trading execution, credentials, vendor-specific assumptions, or cloud-specific
assumptions.

## Dependency Decisions

Runtime dependencies include `sqlalchemy>=2,<3` because future migrations and
schema metadata will use SQLAlchemy Core.

Development dependencies include `alembic>=1,<2` because Alembic is migration
tooling and is not needed by basic contract consumers.

No DB driver is added in this PR. `psycopg` and `asyncpg` are deferred until a
future PR intentionally adds connection behavior or live Postgres migration
tests.

## Alembic Layout

Alembic uses this layout:

- `alembic.ini`
- `infra/db/migrations/env.py`
- `infra/db/migrations/script.py.mako`
- `infra/db/migrations/versions/`

The Alembic environment imports `research_sdk.persistence.metadata.metadata` as
`target_metadata`. The metadata object exists for future SQLAlchemy Core tables,
but it intentionally has no tables in this PR.

## Database URL Handling

Online migrations read `DATABASE_URL` from the environment. The repository must
not commit credentials, real DB URLs, vendor-specific URLs, or cloud-specific
assumptions.

Use a local placeholder command shape when running online migrations:

```bash
DATABASE_URL="<postgresql-url>" uv run alembic -c alembic.ini upgrade head
```

The helper that reads `DATABASE_URL` does not create engines, sessions, or
connections by itself, and it does not log the URL value.

## Baseline Revision

The first revision is `0001_persistence_baseline`. It is intentionally empty:
`upgrade()` creates no tables, constraints, or indexes, and `downgrade()` has no
table effects.

This gives future migrations a stable baseline without mixing migration tooling
with the first ledger table design.

## Ledger Anchor Table Revision

The next migration after the empty baseline is
`0002_ledger_anchor_tables`. It adds the first two experiment ledger anchor
tables:

- `experiment_runs`.
- `data_snapshot_manifests`.

The anchor revision keeps persistence metadata-only. It does not add
repositories, DAOs, DB write paths, FastAPI endpoints, backtest integration,
artifact IO, data ingestion, storage IO, file existence checks, hash
verification, broker integration, live trading, paper trading, or a DB driver.

Artifact manifest, artifact entry, research note, and review event tables remain
deferred to later migrations. Foreign keys are also deferred because current
contract references are declarative and insertion/backfill lifecycle rules have
not been designed yet.

## Local Commands

Commands that do not require a live database:

```bash
uv run alembic -c alembic.ini heads
uv run alembic -c alembic.ini history
```

Online migration command shape:

```bash
DATABASE_URL="<postgresql-url>" uv run alembic -c alembic.ini upgrade head
```

## Validation Commands

Run:

```bash
uv lock
uv sync --locked
git diff --check
uv run ruff format --check .
uv run ruff check .
uv run mypy packages/research-sdk/src
uv run python -m research_sdk.contracts.json_schema --output-dir packages/research-sdk/schema --check
uv run alembic -c alembic.ini heads
uv run alembic -c alembic.ini history
uv run pytest tests/test_persistence_setup.py
uv run pytest
```

If `uv` is unavailable on `PATH`, use `python -m uv` as the equivalent command
prefix.

## Next Persistence PR

After PR 12, future persistence PRs should keep table design, constraints,
indexes, and tests reviewable and should still avoid repositories, DB write
paths, API endpoints, backtest integration, artifact IO, data ingestion, broker
integration, live trading, and paper trading execution unless separately
approved.
