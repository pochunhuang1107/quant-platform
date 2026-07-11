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

This setup PR did not add `experiment_runs`, `data_snapshot_manifests`,
`run_artifact_manifests`, `run_artifact_entries`, `research_notes`, or
`review_events`. Later migrations add those tables incrementally.

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

At the end of the ledger anchor revision, research note and review event tables
were still deferred to later migrations. Cross-contract foreign keys are also
deferred because current contract references are declarative and
insertion/backfill lifecycle rules have not been designed yet.

## Artifact Table Revision

The migration after the ledger anchor table revision is `0003_artifact_tables`.
It adds the artifact metadata layer:

- `run_artifact_manifests`.
- `run_artifact_entries`.

The artifact revision stores manifest metadata, artifact entry projections,
declared hashes, and the validated manifest payload as `raw_contract JSONB`.
Artifact files, parquet/csv contents, logs, charts, and raw market data remain
outside the database. The database records declared metadata only; it does not
perform artifact IO, object storage IO, file existence checks, or hash
verification.

`run_artifact_entries.manifest_id` has a foreign key to
`run_artifact_manifests.manifest_id` because entries are an internal projection
of the same artifact manifest contract. Cross-contract foreign keys to
`experiment_runs` remain deferred until write ordering, correction, replay, and
backfill behavior are designed.

The artifact revision still does not add repositories, DAOs, DB write paths,
FastAPI endpoints, backtest integration, artifact IO, storage IO, hash
verification, a DB driver, or live Postgres tests.

## Research And Review Table Revision

The migration after the artifact table revision is
`0004_research_review_tables`. It adds the research/review metadata layer:

- `research_notes`.
- `review_events`.

`research_notes` stores projected metadata from the validated `ResearchNote`
contract plus `raw_contract JSONB` and `contract_hash`. `review_events` stores
generic review/audit metadata based on `ReviewMetadata` using `subject_type`,
`subject_id`, and `raw_review JSONB`.

Review events are metadata records only. They do not authorize trading, enforce
human approval gates, verify reviewer identity, or implement lifecycle
transitions.

The research/review revision adds no foreign keys. Cross-contract FKs remain
deferred until write ordering, correction, replay, and backfill behavior are
designed. Research note self-links can arrive out of order during imports or
historical backfills, and `review_events` is polymorphic by `subject_type` and
`subject_id`.

The revision still does not add repositories, DAOs, DB write paths, FastAPI
endpoints, backtest integration, artifact IO, data ingestion, storage IO, file
existence checks, hash verification, markdown rendering, report rendering,
search/indexing, JSONB GIN indexes, embeddings, semantic memory, knowledge
graph behavior, LLM summarization, agent workflow execution, broker
integration, live trading, paper trading, a DB driver, or live Postgres tests.

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
