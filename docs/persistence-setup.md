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

PR 21 adds dev-only `psycopg[binary]>=3,<4` for local opt-in live Postgres
migration smoke tests. The driver is not a runtime dependency, and normal
contract consumers still do not need a DB driver. Persistence remains
synchronous. `asyncpg`, `psycopg2`, and runtime DB driver dependencies remain
out of scope.

PR 23 adds `infra/db/docker-compose.yml` as optional local-only disposable
Postgres infrastructure for the existing migration smoke harness. It does not
add or change Python dependencies, lockfiles, package code, tests, migrations,
workflows, CI services, repository code, or application runtime services.

PR 24 adds an isolated GitHub Actions Postgres migration smoke job that runs
the existing live migration harness against a disposable CI service container.
It does not add or change Python dependencies, lockfiles, package code, tests,
migrations, Docker Compose configuration, repository code, statement execution,
or application runtime services.

PR 25 is documentation-only. It defines the idempotency, replay, conflict, and
retry policy in [Persistence Repository Plan](persistence-repository-plan.md).
It does not add or change dependencies, lockfiles, package code, tests,
migrations, Docker Compose configuration, repository code, statement execution,
or application runtime services.

PR 27 adds pure persistence result/disposition value objects and updates
repository protocol return types. See
[Persistence Repository Plan](persistence-repository-plan.md) for the
authoritative result semantics. These result types do not add or change
dependencies, lockfiles, migrations, table metadata, Docker Compose
configuration, DB services, repository code, statement execution, inserts,
replay lookups, conflict handling, transaction behavior, or application runtime
services.

PR 28 adds pure persistence-domain error/context types. See
[Persistence Repository Plan](persistence-repository-plan.md) for the
authoritative hierarchy, safe context fields, deterministic message semantics,
and retry-policy boundary. These error classes do not add or change
dependencies, lockfiles, migrations, table metadata, constraints, indexes,
Docker Compose configuration, CI workflows, DB services, repository code,
statement execution, inserts, replay lookups, database-driver exception
translation, retry behavior, logging behavior, transaction ownership, or
application runtime services.

PR 29 adds inert targeted PostgreSQL statement shapes to the existing statement
builders. See [Persistence Repository Plan](persistence-repository-plan.md) for
the authoritative statement semantics. The builders compile PostgreSQL SQL
only; they do not execute SQL, introduce runtime insert/replay/conflict
behavior, own connections or transactions, translate constraint exceptions, or
change local Compose and CI Postgres migration-only behavior.

PR 30 adds pure exact-name constraint classification. See
[Persistence Repository Plan](persistence-repository-plan.md) for the
authoritative mapping. The translator accepts a stable constraint-name string
and safe persistence error context only. It does not connect to PostgreSQL,
inspect database exceptions, inspect SQLSTATE or driver diagnostics, execute
SQL, alter transaction ownership, or change local Compose and CI Postgres
migration-only behavior.

PR 31 adds a narrow SQLAlchemy `IntegrityError` diagnostic adapter. See
[Persistence Repository Plan](persistence-repository-plan.md) for the
authoritative policy. The adapter receives an already-caught `IntegrityError`,
executes no SQL, creates no `Engine`, `Connection`, `Session`, or transaction,
performs no rollback, and raises or chains no exceptions. Local Compose and CI
Postgres remain migration-only and are not insert, replay, conflict, or
repository execution coverage.

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

Programmatic Alembic runs may explicitly override `sqlalchemy.url` in an
`alembic.config.Config` object. PR 21 uses that path for the local live migration
smoke test so the test can use `QUANT_TEST_DATABASE_URL` without changing the
manual `DATABASE_URL` migration command.

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

## Persistence Hashing Boundary

PR 15 adds canonical contract hashing as the next persistence primitive after
the table migrations. The hashing helpers compute deterministic canonical JSON
and SHA-256 `contract_hash` values from validated Pydantic contract objects.
They are used for future audit and idempotency metadata only.

The PR 15 hashing step did not add repositories, DAOs, row mapping helpers, DB
write paths, sessions, unit-of-work abstractions, FastAPI endpoints, backtest
integration, artifact IO, storage IO, file existence checks, artifact content
hash verification, a DB driver, SQLite persistence tests, or live Postgres
tests.

See [Persistence Repository Plan](persistence-repository-plan.md) for the
canonical hash policy and future repository boundary.

## Persistence Row Mapping Boundary

PR 16 adds pure row mapping helpers after the hashing boundary. These helpers
accept validated Pydantic contracts and return DB-shaped row dictionaries for
the current ledger tables. They compute `contract_hash` internally, store
`raw_contract` or `raw_review` JSON-compatible payloads, and omit
`inserted_at` because it is database-generated.

This row mapping step still does not add repositories, SQLAlchemy insert
builders, DB write paths, sessions, unit-of-work abstractions, FastAPI
endpoints, backtest integration, artifact IO, storage IO, file existence
checks, artifact content hash verification, a DB driver, SQLite persistence
tests, or live Postgres tests.

## Persistence Repository Protocol Boundary

PR 17 adds the protocol boundary after row mapping. It introduces an aggregate
`ExperimentLedgerRepository` protocol and `PersistedRecordMetadata` durable
record metadata for future ledger write repositories. PR 27 adds the
`PersistenceWriteResult` wrapper and successful `PersistenceDisposition`
vocabulary.

This protocol step still does not add repository implementations, SQLAlchemy
insert builders, DB write paths, sessions, unit-of-work abstractions, DB driver
dependencies, SQLite persistence tests, live Postgres tests, FastAPI endpoints,
backtest integration, artifact IO, storage IO, file existence checks, artifact
content hash verification, or approval/trading behavior.

## Persistence Statement Builder Boundary

PR 18 adds SQLAlchemy Core insert statement builders after the protocol
boundary. These builders accept validated contracts, call the existing row
mappers, and bind mapper-produced rows to the current SQLAlchemy Core tables.
They return inert `Insert` objects only.

PR 29 upgrades those existing builders to compile the approved PostgreSQL
statement shapes: targeted primary-key `ON CONFLICT DO NOTHING RETURNING` for
hash-backed replay candidates, strict artifact-entry inserts, and strict
review-event inserts with safe `RETURNING`. These statements remain
non-executing SQL objects.

This statement-builder step still does not add repository implementations, DB
write paths, statement execution, sessions, unit-of-work abstractions, DB
driver dependencies, SQLite persistence tests, live Postgres tests, FastAPI
endpoints, backtest integration, artifact IO, storage IO, file existence
checks, artifact content hash verification, or approval/trading behavior.

## Repository Execution Semantics Boundary

PR 19 is documentation-only. It documents repository execution semantics before
any repository skeleton, SQLAlchemy repository implementation, statement
execution, database write path, DB driver, live Postgres test harness, SQLite
persistence test, FastAPI integration, backtest integration, or experiment run
writer exists.

Future repository implementation should use an injected SQLAlchemy `Connection`
and caller-owned transaction scope. It should not accept an `Engine`, `Session`,
DB URL, raw rows, raw SQLAlchemy statements, storage handles, or
caller-provided `contract_hash`. It should not create engines, own database URL
lookup, silently create or commit transactions, duplicate mapper projection
logic, or bypass the existing statement builders.

Runtime and repository DB driver dependencies remain deferred. PR 21 adds
dev-only `psycopg` for the local migration smoke harness only; it does not
approve repository execution or write paths. `asyncpg` remains avoided because
the current persistence protocols and planned repository boundary are
synchronous. SQLite persistence tests remain avoided because JSONB and Postgres
behavior differ. Repository execution also remains separate from broker
integration, paper trading, live trading, approval workflow execution, artifact
IO, and artifact `content_hash` verification.

PR 25 documents the policy for future idempotent replay, duplicate rejection,
conflict handling, transaction ownership, result/disposition requirements, and
error mapping. The policy remains documentation-only. PR 27 adds the pure
result/disposition value objects without repository execution. PR 28 adds pure
domain error/context types without repository execution, SQL execution,
constraint inspection, SQLAlchemy/psycopg exception translation, retry
behavior, logging behavior, or transaction ownership changes. PR 30 adds pure
exact-name classification for approved constraint names only. PR 31 adds narrow
SQLAlchemy `IntegrityError` diagnostic extraction for PostgreSQL unique
violations only. These boundaries still do not execute SQL, catch exceptions at
the repository boundary, raise translated errors, chain exceptions, perform
rollback, or implement repository behavior. Live insert/replay/conflict tests
remain deferred until repository-boundary exception chaining and repository
execution are separately approved for implementation. Artifact-manifest
execution is blocked until the remaining execution gates are approved.

## Live Postgres Test Harness Boundary

PR 20 documented the boundary before executable live DB tests. PR 21 implements
the first local opt-in live Postgres migration harness. It adds a dev-only sync
`psycopg` v3 driver and a pytest `live_db` marker, but it does not add Docker
Compose, a CI Postgres service, repository code, statement execution, insert
tests, or application integration.

Live DB tests use `QUANT_TEST_DATABASE_URL`, not `DATABASE_URL`. They also
require `QUANT_RUN_LIVE_DB_TESTS=1`, so default pytest remains non-live even if
a developer shell happens to have `QUANT_TEST_DATABASE_URL` set. The tests skip
when either opt-in value is absent, fail clearly when a provided URL is unsafe,
and must never log credentials or the full DB URL.

Live DB tests refuse unsafe URLs:

- non-Postgres URLs;
- production-looking hosts;
- production-looking database names;
- production-looking users.

By default, live tests should allow only local/test hosts such as `localhost`,
`127.0.0.1`, and `::1`. They should require database names containing `test`,
preferably `quant_platform_test`, and require disposable database or schema
access only. CI secrets must not be required.

The `live_db` marker is registered in `pyproject.toml`. Live Postgres tests are
local opt-in only. A CI Postgres service remains deferred. Docker Compose also
remains deferred. If a local Compose service is approved later, prefer
`infra/db/docker-compose.yml` over a root `compose.yml` so Postgres does not
look like a default project runtime requirement.

The first executable live harness is migration-only:

- run Alembic `upgrade head` against live Postgres;
- verify the Alembic version table/state;
- verify table existence;
- verify PostgreSQL `JSONB` columns;
- verify primary keys;
- verify important unique constraints;
- verify check constraints;
- verify indexes;
- verify the artifact-entry foreign key.

The first live harness does not insert data, execute statement builders, execute
repository writes, test idempotency or conflict behavior, test correction or
lifecycle behavior, run FastAPI/backtest integration, or write experiment runs
from backtests. Downgrade testing remains deferred.

SQLite persistence tests remain avoided because current schemas use
PostgreSQL-specific `JSONB` and constraints. SQLite must not be used as a
substitute for persistence correctness.

Statement builders remain inert only. Live DB migration tests must not become
repository tests or insert execution tests. Repository skeletons, repository
implementations, DB writes, insert execution, FastAPI/backtest integration,
experiment run writing from backtests, broker behavior, paper trading, and live
trading remain deferred.

The PR 25 policy does not change the live harness boundary. Local Compose and CI
Postgres harnesses remain migration-only. They do not execute inserts, statement
builders, repositories, fixture persistence, replay logic, or conflict handling.

## Local Live Postgres Migration Harness Runbook

PR 22 is documentation-only. It reviews the PR 21 local opt-in live Postgres
migration harness and records its operating runbook. No concrete PR 21
safety/test gap was found during review, so PR 22 does not change code, tests,
dependencies, migrations, table definitions, workflows, Docker Compose,
devcontainers, contracts, schemas, row mappers, hashing helpers, protocols,
statement builders, repository code, or live DB test code.

### Purpose

The harness is a local disposable Postgres migration smoke test only. It
validates that Alembic can apply the current metadata ledger migrations to
Postgres and that the resulting catalog shape matches the expected Phase 1
schema.

It does not validate repository writes, statement execution, strategy execution,
backtest execution, FastAPI integration, artifact IO, experiment run writing,
broker behavior, paper trading, or live trading.

### Required Env Vars

The live migration test requires both explicit opt-in values:

- `QUANT_RUN_LIVE_DB_TESTS=1`.
- `QUANT_TEST_DATABASE_URL`.

Default pytest remains non-live. The live test skips when either env var is
absent. The live migration test must use `QUANT_TEST_DATABASE_URL` and must not
read `DATABASE_URL`. Manual Alembic commands continue to use `DATABASE_URL` as
documented above.

URL safety helpers are test-only. They live under `tests/` and are not package
code or a runtime persistence API.

### Safe Example URL

Use a disposable local test database, for example:

```text
postgresql+psycopg://quant_test:quant_test@127.0.0.1:5432/quant_platform_test
```

## Local Docker Compose Postgres

PR 23 adds an optional local Docker Compose file for developers who want a
repo-provided disposable Postgres instance for the existing live migration smoke
harness.

This Compose file is optional local infrastructure only. It is not a project
runtime, app stack, CI service, production DB, shared DB, cloud DB, vendor DB,
or broker-related service. It does not run migrations automatically, run app
code, run repository writes, enable insert execution, enable statement builder
execution, or enable paper/live trading.

The Compose service uses `postgres:17.10`, creates the local database
`quant_platform_test`, and creates the local user `quant_test` with password
`quant_test`. The password is intentionally trivial because the database is
local and disposable. Do not reuse it anywhere else.

Start the local Postgres service from the repository root:

```bash
docker compose -f infra/db/docker-compose.yml up -d
```

Inspect the service:

```bash
docker compose -f infra/db/docker-compose.yml ps
```

Run the existing local opt-in migration smoke test:

```bash
QUANT_RUN_LIVE_DB_TESTS=1 QUANT_TEST_DATABASE_URL='postgresql+psycopg://quant_test:quant_test@127.0.0.1:5432/quant_platform_test' python -m uv run pytest -m live_db tests/test_live_postgres_migrations.py
```

Use the `python -m uv` form because `uv` may not be on `PATH`.

Stop the service and remove the disposable database volume:

```bash
docker compose -f infra/db/docker-compose.yml down -v
```

Use `docker compose down -v` whenever the local migration state becomes
confusing or the disposable DB should be recreated.

Default pytest remains non-live. The live DB test remains double opt-in and
requires both `QUANT_RUN_LIVE_DB_TESTS=1` and `QUANT_TEST_DATABASE_URL`.
`QUANT_TEST_DATABASE_URL` must be passed at command time and must not be checked
into a file. Do not paste real credentials into docs, issues, PRs, logs, or
screenshots. Do not point `QUANT_TEST_DATABASE_URL` at a production, shared,
cloud, vendor, or externally hosted DB.

The Compose file binds Postgres only to `127.0.0.1:5432`. If a local Postgres
server already uses port `5432`, change the host-side port in
`infra/db/docker-compose.yml`, for example:

```yaml
ports:
  - "127.0.0.1:15432:5432"
```

Then update the test URL port:

```text
postgresql+psycopg://quant_test:quant_test@127.0.0.1:15432/quant_platform_test
```

### Local Compose Validation Record

Before PR 24, the local Compose path was validated manually with Docker:

- `postgres:17.10` pulled successfully.
- The local Postgres container started successfully.
- The live migration smoke test passed with `1 passed`.
- `docker compose -f infra/db/docker-compose.yml down -v` removed the
  container, network, and named volume.
- No persistent local test DB state remained after teardown.

### Exact Command

Run the live migration smoke test with both opt-in env vars:

```bash
QUANT_RUN_LIVE_DB_TESTS=1 QUANT_TEST_DATABASE_URL='postgresql+psycopg://quant_test:quant_test@127.0.0.1:5432/quant_platform_test' python -m uv run pytest -m live_db tests/test_live_postgres_migrations.py
```

### Expected Default Behavior

Normal test and safety-check behavior should stay non-live:

```bash
python -m uv run pytest
python -m uv run pytest -m live_db tests/test_live_postgres_migrations.py
python -m uv run pytest tests/test_live_postgres_url_safety.py
```

Expected outcomes:

- `python -m uv run pytest` should pass with the live DB test skipped.
- `python -m uv run pytest -m live_db tests/test_live_postgres_migrations.py`
  should skip when opt-in env vars are absent.
- URL safety tests should run without a database.

### What The Live Test Checks

The live migration test checks:

- Alembic `upgrade head`.
- Alembic version table/state.
- Expected tables.
- PostgreSQL `JSONB` columns.
- Primary keys.
- Key unique constraints.
- Check constraints.
- Indexes.
- `run_artifact_entries.manifest_id` foreign key to
  `run_artifact_manifests`.

### What The Live Test Does Not Check

The live migration test does not check:

- Data inserts.
- Statement builder execution.
- Repository writes.
- Contract fixture inserts.
- Idempotency.
- `ON CONFLICT` or upsert behavior.
- Duplicate behavior.
- Correction or lifecycle behavior.
- FastAPI/backtest integration.
- Experiment run writing from backtests.
- Broker, paper trading, or live trading.

## CI Postgres Migration Smoke

PR 24 adds a separate GitHub Actions job named `postgres-migrations` with the
display name `Postgres migration smoke`. This job is isolated from the existing
fast `tooling` job and does not make normal unit CI depend on Postgres.

CI uses a GitHub Actions service container, not Docker Compose. Docker Compose
remains optional local infrastructure only. The CI service uses the same
`postgres:17.10` image and the same disposable test database shape:

- `POSTGRES_DB=quant_platform_test`.
- `POSTGRES_USER=quant_test`.
- `POSTGRES_PASSWORD=quant_test`.

The CI job sets only test-specific live harness variables:

- `QUANT_RUN_LIVE_DB_TESTS=1`.
- `QUANT_TEST_DATABASE_URL` pointing at the localhost-mapped disposable service
  database.

The CI job does not set `DATABASE_URL`, does not use GitHub secrets, and must
not echo the full test URL or credentials. The hard-coded test credentials are
acceptable only because the database is an isolated disposable service
container created for the job.

The CI job runs only:

```bash
uv run pytest -m live_db tests/test_live_postgres_migrations.py
```

It does not rerun the full test suite, linting, type checking, or schema export
checks. Those remain owned by the existing `tooling` job. Both local Compose
and CI use the same migration-only test path: Alembic `upgrade head` followed
by PostgreSQL catalog inspection.

The CI migration smoke job does not check or execute:

- Data inserts.
- Statement builder execution.
- Repository writes.
- Contract fixture inserts.
- Replay logic.
- Conflict handling.
- Idempotency.
- `ON CONFLICT` or upsert behavior.
- Duplicate behavior.
- Correction or lifecycle behavior.
- FastAPI/backtest integration.
- Backtest execution or experiment-run writing from backtests.
- Artifact IO or object storage IO.
- Broker, paper trading, or live trading.

Default local `pytest` remains non-live. The local live DB test still skips
unless both `QUANT_RUN_LIVE_DB_TESTS=1` and `QUANT_TEST_DATABASE_URL` are set.

### Safety Checklist Before Running

Before running the live migration smoke test:

- Use `localhost`, `127.0.0.1`, or `::1` only.
- Use a disposable local test database.
- Confirm the database name contains `test`.
- Prefer `quant_platform_test`.
- Do not use a production, shared, vendor, cloud, or externally hosted DB.
- Do not use privileged users such as `postgres`, `root`, `admin`, or `prod`.
- Do not commit or log secrets.
- Do not paste real credentials into docs, issues, PRs, logs, or screenshots.
- Confirm the database can be discarded and recreated.

### Troubleshooting

- `uv` is not on `PATH`: use `python -m uv`.
- `psycopg` is missing: run `python -m uv sync --locked`.
- URL refused by safety helper: use `postgresql+psycopg`, a local host, a
  database name containing `test`, and a non-privileged/non-production-looking
  user.
- Postgres is not running: start a disposable local Postgres service, optionally
  with `docker compose -f infra/db/docker-compose.yml up -d`.
- Database does not exist: create the disposable local test database outside the
  repo before running the harness, or use the provided Compose service.
- Permission denied: grant the local test user permission to create tables,
  indexes, constraints, and the Alembic version table in the disposable DB.
- Alembic version mismatch: confirm the test database is disposable and either
  already at the current head or safe to recreate.
- Database already migrated: this is acceptable if the version is current and
  catalog assertions pass; recreate the disposable DB with
  `docker compose -f infra/db/docker-compose.yml down -v` when in doubt.
- Connection refused: verify host, port, local server status, and credentials.
- `JSONB` or catalog assertion failure: inspect the migration history and table
  definitions before expanding the harness; do not paper over catalog failures
  with insert or repository tests.

### Review Gates Before Expansion

After local Docker Compose:

- Keep `infra/db/docker-compose.yml` local-only and optional.
- Do not add a root Compose file unless separately approved.
- Keep production, cloud, broker, credential, app-runtime, migration-runner, and
  admin-UI assumptions out of Compose.
- Keep cleanup and disposable DB expectations documented.

After CI Postgres:

- Keep the CI database coverage migration-only and isolated.
- Keep the existing `tooling` job independent from Postgres.
- Avoid CI secrets and external database dependencies.
- Do not run Docker Compose in CI.
- Treat branch protection changes as a separate repository setting decision.

Before insert execution tests:

- Approve that executing SQLAlchemy statements is in scope.
- Define transaction ownership and rollback behavior.
- Keep contract fixture inserts separate from repository semantics.
- Keep artifact IO and content hash verification out of DB tests.
- Treat the PR 31 adapter as classification of an already-caught exception
  only; it does not approve repository exception catching or live conflict
  tests.

Before repository implementation:

- Approve repository skeletons and implementations explicitly.
- Keep repositories on injected SQLAlchemy `Connection` objects.
- Keep transaction scope caller-owned.
- Require repositories to call existing statement builders.
- Do not add `Engine`, `Session`, DB URL, or storage-handle ownership.

Before idempotency/`ON CONFLICT` behavior:

- Keep the PR 25 policy as the authoritative documentation baseline.
- Treat PR 26 artifact-manifest `run_id` uniqueness as the approved database
  identity foundation.
- Approve any artifact-manifest version/supersession behavior separately.
- Treat PR 27 result/disposition value objects as the approved successful-write
  result vocabulary.
- Treat PR 28 error/context types as the approved domain error vocabulary.
- Approve database/constraint exception translation and conflict mapping code.
- Approve live insert/replay/conflict tests separately.
- Avoid silent overwrites.

Before any backtest/FastAPI integration:

- Approve application integration separately.
- Keep experiment run writing from backtests deferred until the ledger write
  path is approved.
- Preserve benchmark, costs, slippage, lookback, lag, leakage, and artifact
  contract documentation requirements.
- Keep broker, paper trading, and live trading out of scope.

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

Local opt-in live migration smoke test command:

```bash
QUANT_RUN_LIVE_DB_TESTS=1 QUANT_TEST_DATABASE_URL='postgresql+psycopg://quant_test:quant_test@127.0.0.1:5432/quant_platform_test' python -m uv run pytest -m live_db tests/test_live_postgres_migrations.py
```

This command requires a disposable local Postgres database. Do not use a
production, shared, vendor, or cloud database. The test runs Alembic
`upgrade head` and inspects catalog metadata only. It does not insert contract
fixtures, execute statement builders, execute repositories, create or drop
databases, create or drop schemas, or clean up user-provided database objects.

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
uv run pytest tests/test_live_postgres_url_safety.py
uv run pytest tests/test_persistence_setup.py
uv run pytest tests/test_persistence_hashing.py tests/test_persistence_mappers.py tests/test_persistence_protocols.py tests/test_persistence_statements.py
uv run pytest
```

If `uv` is unavailable on `PATH`, use `python -m uv` as the equivalent command
prefix.

## Next Persistence PR

After PR 31, future persistence PRs should keep table design, constraints,
indexes, semantics, and tests reviewable. Local Compose and CI Postgres remain
migration-only; targeted statement shapes, result types, error types, pure
constraint-name classification, and narrow SQLAlchemy `IntegrityError`
diagnostic translation do not cause inserts, replay lookups, repository-boundary
exception catching, translated exception chaining, retry behavior, transaction
behavior, or repository execution.
Future PRs should still avoid repository implementations, DB write paths, API
endpoints, backtest integration, artifact IO, data ingestion, broker
integration, live trading, and paper trading execution unless separately
approved. Live insert/replay/conflict tests remain deferred until
repository-boundary exception chaining and repository execution are separately
approved.
