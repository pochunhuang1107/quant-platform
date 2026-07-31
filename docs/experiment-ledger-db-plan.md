# Experiment Ledger DB Plan

## Purpose And Scope

This is the Phase 1 DB implementation plan for the experiment ledger.

The plan maps the existing Pydantic and JSON-schema contracts to future
Postgres tables for the experiment ledger metadata layer. It defines table
boundaries, planned relational projections, JSONB usage, idempotency rules,
audit expectations, indexing, future migration sequencing, and later DB test
coverage.

PR 12 is the first actual ledger table migration. It implements the
`experiment_runs` and `data_snapshot_manifests` anchor tables using SQLAlchemy
Core metadata and a hand-written Alembic migration.

PR 13 adds the artifact metadata layer:

- `run_artifact_manifests`.
- `run_artifact_entries`.

The artifact table migration stores manifest metadata, artifact entry
projections, declared hashes, and raw validated manifest contracts. It does not
perform artifact file IO, object storage IO, file existence checks, or hash
verification. At the end of PR 13, research notes and review events were still
deferred.

PR 14 adds the research and review metadata layer:

- `research_notes`.
- `review_events`.

The research/review migration stores projected research note metadata, raw
validated `ResearchNote` contract JSON, and generic review/audit metadata based
on `ReviewMetadata`. It does not render markdown, generate reports, enforce
approval workflows, authorize trading, add search/indexing, add embeddings, or
introduce write paths.

PR 15 adds canonical contract hashing. PR 16 adds pure row mapping helpers that
define the column projection boundary from validated contracts to DB-shaped row
dictionaries before repositories are introduced. The mappers do not execute DB
writes, build insert statements, connect to a database, verify external
artifacts, or enforce lifecycle/idempotency policy.

PR 17 adds repository protocols, PR 18 adds inert SQLAlchemy Core insert
statement builders, PR 19 documents repository execution semantics, PR 20
documents the live Postgres test harness boundary, and PR 21 implements the
first local opt-in live Postgres migration harness. PR 21 adds a dev-only sync
`psycopg` v3 driver, pytest marker registration, URL safety tests, and a live
Alembic `upgrade head` plus catalog inspection smoke test. It adds no schema,
table, migration revision, repository skeleton, repository implementation,
database write path, insert execution, SQLite persistence test, workflow,
Docker Compose service, devcontainer, or application integration.

PR 22 is documentation-only. It reviews the PR 21 harness and adds the local
live Postgres migration harness runbook in
[Persistence Setup](persistence-setup.md). The review found no required
safety-code or test change. PR 22 adds no schema, table, migration revision,
code, test, dependency, workflow, Docker Compose service, devcontainer,
repository skeleton, repository implementation, insert execution, SQLite
persistence test, or application integration.

PR 23 is the approved local Docker Compose expansion gate. It adds
`infra/db/docker-compose.yml` for an optional local disposable Postgres service
and updates documentation for using that service with the existing live
migration smoke harness. PR 23 adds no schema, table, migration revision, code,
test, dependency, workflow, CI Postgres service, devcontainer, repository
skeleton, repository implementation, insert execution, SQLite persistence test,
or application integration.

PR 24 is the isolated CI Postgres migration gate. It records the successful
local Compose validation with `postgres:17.10` and adds a separate GitHub
Actions `postgres-migrations` job named `Postgres migration smoke`. The CI job
uses a disposable `postgres:17.10` service container and runs only the existing
live migration smoke test. It is independent from the normal tooling CI job,
uses test-only hard-coded local credentials, uses no secrets, does not set
`DATABASE_URL`, and does not run Docker Compose. PR 24 adds no schema, table,
migration revision, package code, dependency, lockfile, test code, Docker
Compose configuration, repository skeleton, repository implementation, insert
execution, SQLite persistence test, FastAPI/backtest integration, or experiment
run writer.

PR 25 is documentation-only. It defines the idempotency, replay, uniqueness,
concurrency, retry, and conflict policy in
[Persistence Repository Plan](persistence-repository-plan.md), but it adds no
code, tests, migrations, schema/table definitions, contracts, generated schemas,
dependencies, workflows, Docker Compose, package exports, repository
implementation, or execution paths.

PR 26 enforces artifact-manifest run identity at the database layer. It adds
`0005_artifact_run_identity`, creates
`uq_run_artifact_manifests_run_id`, drops the older
`uq_run_artifact_manifests_run_id_contract_hash`, and removes the redundant
non-unique `ix_run_artifact_manifests_run_id` index because the unique
constraint provides the `run_id` index path. `manifest_id` remains the primary
key, and `run_id` is now the enforced natural aggregate identity. PR 26 adds no
artifact-manifest versioning, supersession, repository execution, insert
execution, `ON CONFLICT` behavior, data cleanup, contract changes, generated
schema changes, dependency changes, workflow changes, Docker Compose changes,
or application/backtest integration.

PR 27 adds the pure persistence result/disposition interface gate. It defines
successful write result value objects for `CREATED` and `REPLAYED` outcomes and
updates repository protocol return types, but it does not change migrations,
tables, SQLAlchemy metadata, constraints, DB services, live migration behavior,
repository implementations, SQL execution, `ON CONFLICT` behavior, transaction
behavior, live insert/replay/conflict tests, dependencies, workflows, Docker
Compose, or application/backtest integration.

PR 28 adds the pure persistence-domain error taxonomy interface gate. It
defines deterministic domain exception and context types for conflicts and
aggregate integrity failures, but it does not change migrations, tables,
SQLAlchemy metadata, constraints, indexes, DB services, Docker Compose, CI
workflows, live migration behavior, contracts, generated schemas,
dependencies, repository implementations, SQL execution, `ON CONFLICT`
behavior, database-driver exception translation, retry behavior, logging
behavior, or application/backtest integration.

PR 29 adds the inert targeted PostgreSQL statement-shape gate. It upgrades the
existing public statement builders for hash-backed top-level records to compile
`INSERT ... ON CONFLICT ON CONSTRAINT <primary-key> DO NOTHING RETURNING ...`
for the approved primary-key replay targets only. Review events and artifact
entries remain strict inserts, with review events returning only
`review_event_id` and `inserted_at`. PR 29 changes no migrations, tables,
SQLAlchemy metadata, constraints, indexes, DB services, Docker Compose, CI
workflows, live migration behavior, contracts, generated schemas,
dependencies, repository implementations, SQL execution, replay lookups, hash
comparison, transaction behavior, database exception translation, aggregate
verification, retry behavior, logging behavior, or application/backtest
integration.

PR 30 adds the pure exact constraint-name translation gate. It maps only
approved stable constraint-name strings to existing persistence-domain conflict
errors and returns `None` for unknown constraints. It completes constraint-name
classification only; SQLAlchemy/psycopg exception extraction, driver diagnostic
inspection, SQLSTATE handling, exception chaining at the repository boundary,
repository skeletons, repository implementations, SQL execution, replay
`SELECT`, hash comparison, transaction behavior, aggregate verification, live
insert/replay/conflict tests, and application/backtest integration remain
future gates. PR 30 changes no migrations, tables, SQLAlchemy metadata,
constraints, indexes, DB services, Docker Compose, CI workflows, live migration
behavior, contracts, generated schemas, dependencies, or application/backtest
integration.

## Non-Goals

The ledger persistence scope still does not implement:

- ORM models.
- DB connection code.
- Repositories/DAOs.
- API endpoints.
- Backtest engine integration.
- Experiment run writing.
- Artifact IO.
- Data ingestion.
- Vendor API calls.
- Storage IO.
- File existence checks.
- Hash verification.
- UI/editor.
- Embeddings.
- Semantic memory.
- Knowledge graph.
- Search/indexing implementation.
- LLM summarization.
- Agent workflow execution.
- Broker integration.
- Live trading.
- Paper trading execution.
- Credentials, vendor-specific assumptions, or cloud-specific assumptions.

## Storage Boundaries

The DB is a metadata ledger, not object storage.

The DB stores run metadata, data snapshot metadata, artifact manifest metadata,
artifact entry projections, research note metadata, review events, references,
lifecycle status, projected query columns, and raw validated contract JSON.

As of PR 14, run metadata, data snapshot metadata, artifact manifest metadata,
artifact entry projections, research note metadata, and generic review/audit
events have physical tables.

Artifact files, parquet/csv contents, logs, charts, market data, raw datasets,
and large result payloads remain outside the DB. The DB stores URIs and declared
hashes, but it does not verify files, verify artifact hashes, inspect parquet
contents, read storage backends, or check object/file existence. Those checks
belong in artifact validators, storage services, or later application layers.

Data snapshots are referenced by snapshot ID, path metadata, source metadata,
and declared content metadata. The ledger DB records those references for audit
and reproducibility; it does not ingest, scan, or store the underlying data.

## Contract-To-Table Map

| Contract | Planned table | Primary key | Important projected columns | raw_contract JSONB | Notes |
| --- | --- | --- | --- | --- | --- |
| `ExperimentRunRecord` | `experiment_runs` | `run_id` | `experiment_id`, `schema_version`, `status`, `created_at`, `strategy_id`, `asset_class`, `data_snapshot_id`, `artifact_manifest_uri`, `parent_run_id`, `supersedes_run_id`, review summary fields, `contract_hash` | Yes | Authoritative metadata row for a research run. Completed runs are append-only; corrections create new runs. |
| `DataSnapshotManifest` | `data_snapshot_manifests` | `snapshot_id` | `schema_version`, `snapshot_kind`, `status`, `asset_class`, `source_dataset`, `source_version`, `source_type`, `temporal_coverage`, `as_of`, `available_at`, `row_count`, `contract_hash` | Yes | Metadata pointer to point-in-time data snapshots. Raw data remains outside DB. |
| `RunArtifactManifest` | `run_artifact_manifests` | `manifest_id` | `run_id`, `experiment_id`, `schema_version`, `artifact_root_uri`, `created_at`, `required_artifacts_complete`, `contract_hash` | Yes | Implemented in PR 13. `manifest_id` is generated by future application code. `RunArtifactManifest` does not currently have an `artifact_manifest_hash` field, so the table uses `contract_hash` for manifest payload audit and idempotency. |
| `RunArtifactEntry` | `run_artifact_entries` | composite `manifest_id`, `artifact_id` | `manifest_id`, `run_id`, `artifact_id`, `artifact_kind`, `uri`, `filename`, `format`, `status`, `content_hash`, `row_count`, `validator_version` | No | Implemented in PR 13 as relational projections from `RunArtifactManifest.artifacts`. The full entry payload remains available through the parent manifest `raw_contract`. |
| `ResearchNote` | `research_notes` | `note_id` | `schema_version`, `note_type`, `status`, `created_at`, `updated_at`, `title`, `hypothesis_status`, `evidence_strength`, `decision_outcome`, `parent_note_id`, `supersedes_note_id`, review summary fields, `contract_hash` | Yes | Structured research note metadata and raw validated note contract. Markdown rendering and search are out of scope. |
| `ReviewMetadata` | Latest review fields on parent records plus `review_events` | `review_event_id` for events | `subject_type`, `subject_id`, `review_status`, `reviewer_id`, `review_role`, `reviewed_at`, `decision`, `approval_scope`, `linked_pr`, `risk_approval_required` | `raw_review` JSONB on events | Parent tables carry latest review summary fields for fast filtering. `review_events` stores append-only-oriented history. PR 14 does not add a standalone `ReviewEvent` contract. |
| `VersionedContract` | None | None | `schema_version` on schema-backed tables | No standalone payload | No standalone DB table is planned. `schema_version TEXT NOT NULL` appears on schema-backed tables. |

## Planned Table Summaries

### experiment_runs

Likely columns:

- `run_id` primary key.
- `experiment_id`.
- `schema_version`.
- `status`.
- `created_at`.
- `created_by`.
- `status_updated_at`.
- `status_updated_by`.
- `strategy_id`.
- `strategy_version`.
- `git_commit_sha`.
- `repo_dirty`.
- `asset_class`.
- `frequency`.
- `data_snapshot_id`.
- `feature_snapshot_id`.
- `artifact_uri`.
- `artifact_manifest_uri`.
- `artifact_manifest_hash`.
- `parent_run_id`.
- `supersedes_run_id`.
- `review_status`.
- `reviewer_id`.
- `review_role`.
- `reviewed_at`.
- `risk_approval_required`.
- `contract_hash`.
- `raw_contract JSONB`.
- `inserted_at`.

### data_snapshot_manifests

Likely columns:

- `snapshot_id` primary key.
- `schema_version`.
- `snapshot_kind`.
- `status`.
- `created_at`.
- `created_by`.
- `asset_class`.
- `frequency`.
- `data_root_uri`.
- `source_dataset`.
- `source_version`.
- `source_type`.
- `vendor_name` nullable.
- `temporal_coverage`.
- `as_of`.
- `available_at`.
- `ingestion_completed_at`.
- `adjustment_policy`.
- `calendar`.
- `timezone`.
- `row_count`.
- `file_count`.
- `size_bytes`.
- `contract_hash`.
- `raw_contract JSONB`.
- `inserted_at`.

### run_artifact_manifests

Likely columns:

- `manifest_id` primary key.
- `run_id`.
- `experiment_id`.
- `schema_version`.
- `artifact_root_uri`.
- `created_at`.
- `required_artifacts_complete`.
- `contract_hash`.
- `raw_contract JSONB`.
- `inserted_at`.

PR 13 adds a unique constraint on `run_id` and `contract_hash`. It does not make
`contract_hash` globally unique and does not add an `artifact_manifest_hash`
column because that field is not present in the current `RunArtifactManifest`
contract.

### run_artifact_entries

Likely columns:

- `manifest_id`.
- `run_id`.
- `artifact_id`.
- `artifact_kind`.
- `uri`.
- `filename`.
- `format`.
- `status`.
- `hash_algorithm`.
- `content_hash`.
- `size_bytes`.
- `row_count`.
- `created_at`.
- `validator_version`.
- `inserted_at`.

PR 13 uses composite primary key `manifest_id` and `artifact_id`, matching the
current contract rule that artifact IDs are unique within a manifest.

### research_notes

Implemented in PR 14.

Columns:

- `note_id` primary key.
- `schema_version`.
- `note_type`.
- `status`.
- `created_at`.
- `created_by`.
- `updated_at`.
- `updated_by`.
- `title`.
- `hypothesis_status`.
- `evidence_strength`.
- `decision_outcome`.
- `parent_note_id`.
- `supersedes_note_id`.
- `review_status`.
- `reviewer_id`.
- `review_role`.
- `reviewed_at`.
- `risk_approval_required`.
- `contract_hash`.
- `raw_contract JSONB`.
- `inserted_at`.

### review_events

Implemented in PR 14.

Columns:

- `review_event_id` primary key.
- `subject_type`.
- `subject_id`.
- `review_status`.
- `reviewer_id`.
- `review_role`.
- `reviewed_at`.
- `decision`.
- `approval_scope`.
- `approval_expires_at`.
- `linked_pr`.
- `review_notes_uri`.
- `risk_approval_required`.
- `raw_review JSONB`.
- `inserted_at`.

PR 14 uses `subject_type`, `subject_id`, and `raw_review` naming. It does not
use `entity_type`, `entity_id`, or `raw_event`.

`event_hash` is deferred because there is no standalone `ReviewEvent` contract
or canonical event wrapper yet. `schema_version` on `review_events` is also
deferred because `ReviewMetadata` is schema-backed but is not a
`VersionedContract`.

## Relational Columns Vs JSONB Policy

Use relational columns for stable IDs, lifecycle states, timestamps, common
filters, references, review summary fields, artifact entry fields likely to be
queried, `contract_hash`, and `schema_version`.

Use JSONB for the full `raw_contract`, nested contract payloads,
forward-compatible metadata, `asset_universe`, `benchmark`, `environment`,
`random_seed`, `metrics_summary`, failure labels, note references, note tags,
note body metadata, snapshot policies, and known limitations.

The relational columns are query projections of validated contracts. The JSONB
payload is the durable raw validated contract record used for replay, audit, and
schema evolution.

## Schema Version And Contract Hash Policy

`schema_version` is stored as `TEXT NOT NULL` on each schema-backed table. No
`schema_versions` or `contract_schema_registry` table is planned for the first
migration. A schema registry can be added later if compatibility checks or
schema migration workflows require it.

`contract_hash` is derived from canonicalized `raw_contract` after Pydantic
validation. It supports idempotency, replay, and audit by identifying whether a
stored contract payload matches the payload being inserted.

`contract_hash` does not verify external artifacts, data snapshots, parquet
files, csv files, logs, charts, or storage objects. Artifact and data file hash
verification belongs outside the DB layer.

As of PR 15, canonical contract hashing is implemented before repositories or
write paths. The hash is computed from compact canonical JSON produced from a
validated Pydantic contract object's `model_dump(mode="json")` payload with
stable key ordering. `schema_version` is included when present because it is
part of contract identity. Database-generated fields such as `inserted_at` are
excluded because they are not part of the validated contract payload.

As of PR 16, row mapping helpers compute `contract_hash` internally and project
all current table columns except `inserted_at`. They store `raw_contract` from
`contract.model_dump(mode="json")` and `raw_review` from
`review.model_dump(mode="json")`. These helpers are pure, non-executing
projections; they are not a DB write path.

As of PR 17, repository protocols define the future write boundary shape with
explicit methods for current ledger contracts and review events. These
protocols are non-executing, do not change table schemas, do not import
SQLAlchemy table metadata, and do not add insert builders, repositories, DB
writes, sessions, DB drivers, live Postgres tests, or SQLite persistence tests.
Lifecycle, idempotency, correction, append-only, and session/unit-of-work rules
remain future design work.

As of PR 18, SQLAlchemy Core statement builders define the inert SQL statement
boundary. They bind mapper-produced rows to the current table metadata and
return non-executing `Insert` objects. They do not change table schema, execute
database writes, create engines/sessions/connections, add DB drivers, or choose
lifecycle, idempotency, correction, append-only, `ON CONFLICT`, or
session/unit-of-work rules.

As of PR 19, repository execution semantics are documented before code.
Repository skeletons, SQLAlchemy repository implementations, database writes,
statement execution, DB drivers, live Postgres tests, SQLite persistence tests,
FastAPI/backtest integration, and experiment run writing from backtests remain
deferred. Future implementation should use an injected SQLAlchemy `Connection`
and caller-owned transaction scope, but repository execution is intentionally
blocked until conflict semantics and a test harness are approved.

As of PR 25, the idempotency, replay, and conflict policy is documented before
execution code. Hash-backed entities may replay only when logical identity and
canonical hash match. The same identity with a different hash rejects.
`review_events` duplicate IDs reject until a standalone hashable `ReviewEvent`
contract exists. As of PR 26, artifact-manifest `run_id` uniqueness is enforced
by the database, resolving the PR 25 artifact identity schema blocker.
As of PR 27, successful write result/disposition modeling is implemented as
pure value objects. As of PR 28, the pure domain error taxonomy is implemented.
As of PR 29, targeted PostgreSQL insert-attempt statement shapes are
implemented without execution. As of PR 30, pure exact constraint-name
classification is implemented without driver exception extraction.
Artifact-manifest execution remains blocked on SQLAlchemy/psycopg exception
extraction, constraint-name extraction from driver diagnostics, exception
chaining at the repository boundary, repository skeleton and implementation,
SQL execution, replay `SELECT` and hash comparison, caller-owned transaction
behavior, aggregate replay/integrity verification, live insert/replay/conflict
tests, and application/backtest integration.

See [Persistence Repository Plan](persistence-repository-plan.md) for the
repository boundary, hashing API, future write-path responsibilities, and the
authoritative idempotency, replay, and conflict policy.

## Idempotency And Insert/Update Rules

Insert paths should require prior Pydantic contract validation. After
validation, the write path should canonicalize the contract payload and compute
`contract_hash`. Future repositories should compute this internally and must not
accept caller-provided `contract_hash` values.

The same primary key plus the same `contract_hash` may be idempotent in a future
write path. The same primary key plus a different `contract_hash` should be
rejected unless the caller uses an explicit correction or supersession path.
Silent overwrite is prohibited. Generic `INSERT` execution without an approved
conflict policy is not enough. `ON CONFLICT`, upsert behavior, duplicate
handling, and the choice between pre-read checks, `ON CONFLICT`, or
service-layer replay workflows remain deferred.

PR 25 makes that deferred policy explicit without implementing it. Initial write
paths are insert-only. Hash-backed entities may replay only when logical
identity and canonical hash match. The same identity with a different canonical
hash must reject. New primary keys that collide with non-primary uniqueness or
policy-level natural identity are natural-key conflicts or duplicate aliases,
not replay.

For `run_artifact_manifests`, the initial policy permits exactly one artifact
manifest aggregate per `run_id`. PR 26 enforces this policy with
`UNIQUE(run_id)` through `uq_run_artifact_manifests_run_id`. The prior
`UNIQUE(run_id, contract_hash)` constraint is removed because it is redundant
once `run_id` is unique, and the prior non-unique `run_id` index is removed
because the unique constraint supplies the `run_id` index path. If duplicate
`run_id` rows already exist, PostgreSQL constraint creation fails safely; the
migration does not delete, merge, repair, rewrite, or silently deduplicate data.
Artifact-manifest versioning and supersession remain unsupported and require a
separate contract, schema, replay, lineage, API, and migration design before
they can be introduced.

Mutable operational fields should be minimal. Status and review updates should
produce `review_events` or another audit record when they change review or
lifecycle metadata. Write paths must avoid silent overwrites.

## Immutability, Corrections, Supersession, And Audit Rules

Completed runs are append-only. Corrections create new run IDs linked through
`parent_run_id`. Supersession uses `supersedes_run_id`, and prior record status
changes must be auditable.

Review events are append-only. Research notes can use `parent_note_id` and
`supersedes_note_id` to model corrections or replacement notes.

`review_events` are append-only by `review_event_id` for now. They currently
have no `event_hash`, `contract_hash`, or `schema_version`, so idempotent replay
for review events remains deferred until event identity is designed. A duplicate
`review_event_id` should reject by primary key. A standalone `ReviewEvent`
contract remains a future consideration.

Artifact manifests are immutable once recorded. Corrections should insert new
manifest records instead of mutating prior manifest payloads. Data snapshot
manifests should be immutable after `completed` status except through an
explicit future correction or supersession process.

The first DB migration should use basic constraints only. Lifecycle transition
enforcement should be handled by future application/service validation instead
of complex DB transition logic.

## Review Metadata Model

Parent tables may carry latest review summary fields for fast filtering:
`review_status`, `reviewer_id`, `review_role`, `reviewed_at`, and
`risk_approval_required`.

`review_events` stores append-only review history for experiment runs, research
notes, and any later reviewable subject type. Event rows should include the
review metadata fields plus `raw_review JSONB`.

`ReviewMetadata` remains metadata only. Review records do not authorize trading
or financial decisions. Human approval gates remain outside this DB plan, and
paper/live trading authorization is out of scope for Phase 1.

PR 14 keeps review events generic and minimal. The allowed subject types are
`experiment_run`, `research_note`, `data_snapshot_manifest`, and
`run_artifact_manifest`. Lifecycle transition rules, reviewer identity
verification, and human approval gate enforcement remain future service-layer
concerns.

## Minimal Phase 1 Indexes

Planned indexes:

- `experiment_runs(status, created_at)`.
- `experiment_runs(strategy_id, created_at)`.
- `experiment_runs(experiment_id, created_at)`.
- `experiment_runs(data_snapshot_id)`.
- `experiment_runs(parent_run_id)`.
- `experiment_runs(supersedes_run_id)`.
- `data_snapshot_manifests(snapshot_kind, status, created_at)`.
- `data_snapshot_manifests(asset_class, source_dataset, created_at)`.
- `run_artifact_manifests(run_id)` through the unique constraint backing index.
- `run_artifact_entries(run_id, artifact_kind)`.
- `run_artifact_entries(status)`.
- `research_notes(status, updated_at)`.
- `review_events(subject_type, subject_id, inserted_at)`.

Avoid broad JSONB GIN indexes in the first migration unless a concrete query
requires them.

PR 13 originally adds the artifact indexes:

- `run_artifact_manifests(run_id)`.
- `run_artifact_manifests(experiment_id, created_at)`.
- `run_artifact_entries(run_id, artifact_kind)`.
- `run_artifact_entries(status)`.
- `run_artifact_entries(manifest_id)`.

PR 26 removes the non-unique `run_artifact_manifests(run_id)` index because
`uq_run_artifact_manifests_run_id` supplies the final `run_id` index path. The
artifact table design intentionally does not add a `content_hash` index until a
concrete lookup workflow requires it.

PR 14 adds the research/review indexes:

- `research_notes(status, updated_at)`.
- `research_notes(note_type, created_at)`.
- `research_notes(review_status, updated_at)`.
- `research_notes(decision_outcome, updated_at)`.
- `research_notes(parent_note_id)`.
- `research_notes(supersedes_note_id)`.
- `review_events(subject_type, subject_id, inserted_at)`.
- `review_events(reviewer_id, inserted_at)`.
- `review_events(review_status, inserted_at)`.

## Planned Migration Sequence

This sequence is partially implemented and current through PR 30:

1. Add Alembic setup and the SQLAlchemy dependency in a dedicated setup PR.
   See [Persistence Setup](persistence-setup.md) for the minimal tooling,
   `DATABASE_URL` handling, and empty baseline revision. That setup creates no
   ledger tables.
2. Add the first ledger anchor table migration:
   - `experiment_runs`.
   - `data_snapshot_manifests`.
3. Add basic constraints and text check constraints for enum-like fields on
   those anchor tables.
4. Add anchor-table indexes and migration structure tests without requiring a
   live Postgres instance.
5. Add the artifact table migration:
   - `run_artifact_manifests`.
   - `run_artifact_entries`.
6. Add the research and review metadata migration:
   - `research_notes`.
   - `review_events`.
7. Add canonical contract hashing helpers.
8. Add pure row mapping helpers for current table projections.
9. Add repository protocols that define the future write boundary shape without
   implementation or execution behavior.
10. Add SQLAlchemy Core insert statement builders that return inert `Insert`
   objects without execution behavior.
11. Add repository execution semantics documentation before implementation:
   - future repositories should accept an injected SQLAlchemy `Connection`;
   - transaction scope should be caller-owned;
   - repository methods should call existing statement builders;
   - artifact manifest rows and entry rows must be atomic when writes exist;
   - idempotency, duplicate handling, `ON CONFLICT`, correction, lifecycle,
     session/unit-of-work, and DB-returned metadata remain deferred;
   - DB drivers, live Postgres tests, and SQLite persistence tests remain
     deferred.
12. Add live Postgres test harness boundary documentation before adding a driver
    or executable live DB tests:
   - future live DB tests should use `QUANT_TEST_DATABASE_URL`, not
     `DATABASE_URL`;
   - future tests should be local opt-in before CI;
   - the DB driver, Docker Compose, CI Postgres service, and live tests remain
     deferred;
   - the first future executable harness should be migration-only.
13. Add the first local opt-in live Postgres migration harness:
   - dev-only sync `psycopg[binary]>=3,<4`;
   - pytest `live_db` marker;
   - `QUANT_RUN_LIVE_DB_TESTS=1` plus `QUANT_TEST_DATABASE_URL` opt-in;
   - URL safety validation for local disposable test databases;
   - Alembic `upgrade head` only;
   - catalog inspection for version state, expected tables, JSONB columns,
     primary keys, unique constraints, check constraints, indexes, and the
     artifact-entry foreign key.
14. Add a documentation-only runbook and review checklist for the local live
   Postgres migration harness. This keeps the harness migration-only and records
   that the PR 21 review found no required safety-code or test change.
15. Add optional local Docker Compose infrastructure for a disposable Postgres
   instance under `infra/db/docker-compose.yml`:
   - keep it local-only and outside the repo root;
   - use it only with the existing double opt-in live migration harness;
   - do not add app services, migration runners, admin UIs, CI services,
     dependencies, package code, migrations, or test changes.
16. Add an isolated CI Postgres migration smoke job:
   - use a GitHub Actions service container, not Docker Compose;
   - keep the normal tooling CI job unchanged and independent from Postgres;
   - use `postgres:17.10` with the disposable `quant_platform_test` database;
   - run only the existing `live_db` Alembic upgrade-head/catalog inspection
     test;
   - do not use secrets, `DATABASE_URL`, external databases, insert execution,
     repository writes, package changes, dependency changes, migration changes,
     or schema changes.
17. Add documentation-only idempotency, replay, uniqueness, concurrency, retry,
   and conflict policy before execution code:
   - hash-backed entities may replay only when logical identity and canonical
     hash match;
   - same logical identity plus different canonical hash rejects;
   - `review_events` duplicate IDs reject until a standalone hashable
     `ReviewEvent` contract exists;
   - artifact-manifest `run_id` uniqueness is enforced as of PR 26;
   - artifact-manifest versioning and supersession remain unsupported and
     require separate approval before introduction;
   - insert execution, `ON CONFLICT` code, repository skeletons and
     implementations, aggregate replay/integrity logic, live
     insert/replay/conflict tests, application integration, and error taxonomy
     code remain deferred.
18. Add pure persistence-domain error taxonomy code:
   - define safe typed exception/context interfaces for deterministic
     conflicts and aggregate integrity failures;
   - keep successful `CREATED` and `REPLAYED` results separate from failures;
   - add no SQLAlchemy execution, `ON CONFLICT` behavior, repository code,
     database exception translation, retry behavior, logging behavior,
     migrations, metadata changes, live DB behavior, dependencies, Compose
     changes, workflows, contracts, or schemas.
19. Add inert targeted PostgreSQL insert-attempt statement shapes:
   - keep existing public statement builder names;
   - target only approved primary-key constraints for replay-candidate
     hash-backed top-level records;
   - add safe `RETURNING` columns for replay candidates;
   - keep review events strict with `RETURNING review_event_id, inserted_at`;
   - keep artifact entries strict without `RETURNING`;
   - add no SQL execution, replay `SELECT`, hash comparison, constraint
     translation, repository implementation, transaction behavior, aggregate
     verification, migrations, metadata changes, live DB behavior,
     dependencies, workflows, contracts, or schemas.
20. Add pure exact constraint-name translation:
   - map only `pk_review_events` to `DuplicateReviewEventError`;
   - map only `uq_run_artifact_manifests_run_id` to
     `UnsupportedVersioningConflictError`;
   - return `None` for unknown constraints;
   - add no raw database exception handling, SQLAlchemy/psycopg exception
     extraction, SQLSTATE handling, `orig`/`diag` inspection, exception
     chaining, SQL execution, replay `SELECT`, hash comparison, repository
     implementation, transaction behavior, aggregate verification, migrations,
     metadata changes, live DB behavior, dependencies, workflows, contracts, or
     schemas.
21. Add stable non-blocking cross-contract foreign keys later where appropriate.
22. Add contract fixture persistence tests later.
23. Add repository/write-path code only in a later PR after semantics, conflict
   behavior, schema requirements, SQLAlchemy/psycopg exception extraction,
   repository-boundary exception chaining, and test harness design are
   approved.
24. Require Pydantic contract validation before persistence.

PR 12 intentionally adds no foreign keys. Contract references are declarative
today, and insertion ordering, backfill behavior, and lifecycle rules are not
designed yet. Foreign keys can be added later once those write-path rules are
explicit.

PR 13 adds exactly one foreign key:
`run_artifact_entries.manifest_id -> run_artifact_manifests.manifest_id`. This
FK is internal to the artifact manifest projection and both tables are created
in the same migration. PR 13 still defers cross-contract foreign keys to
`experiment_runs`, including `run_artifact_manifests.run_id` and
`run_artifact_entries.run_id`, until write ordering, correction, replay, and
backfill behavior are designed.

PR 14 adds no foreign keys. Cross-contract foreign keys remain deferred until
write ordering, correction, replay, and backfill behavior are designed.
Research note self-links are also not enforced as FKs because
`parent_note_id` and `supersedes_note_id` may reference notes created out of
order during imports or historical backfills. `review_events` is polymorphic by
`subject_type` and `subject_id`, so FK enforcement is not practical in this
migration.

PR 25 adds no constraints. It records that the current artifact-manifest
constraints are insufficient for one-manifest-per-run execution because
`UNIQUE(run_id, contract_hash)` does not prevent the same `run_id` from being
stored with a different manifest hash.

PR 26 adds the `0005_artifact_run_identity` revision. The migration
creates `uq_run_artifact_manifests_run_id`, drops
`uq_run_artifact_manifests_run_id_contract_hash`, and drops
`ix_run_artifact_manifests_run_id`. This resolves the artifact identity schema
blocker without adding manifest versions, `manifest_version`,
`supersedes_manifest_id`, current/active flags, lifecycle states, soft deletes,
mutable replacement, repository code, SQL execution, `ON CONFLICT` builders,
fixture persistence, live insert/conflict tests, result models, error classes,
cross-contract foreign keys, contract/schema changes, or app/backtest
integration.

PR 28 adds no migration revision and changes no database shape. Migrations,
tables, SQLAlchemy metadata, constraints, indexes, DB services, Docker Compose,
CI workflows, live migration behavior, contracts, generated schemas, and
dependencies remain unchanged.

PR 29 also adds no migration revision and changes no database shape.
Migrations, tables, SQLAlchemy metadata, constraints, indexes, DB services,
Docker Compose, CI workflows, live migration behavior, contracts, generated
schemas, and dependencies remain unchanged.

## Future SQLAlchemy/Alembic Integration Steps

The dedicated persistence setup PR added dependencies, the Alembic environment,
the migration directory, SQLAlchemy Core metadata, and an empty baseline only.
PR 12 adds the first actual SQLAlchemy Core table definitions and the
`0002_ledger_anchor_tables` Alembic revision for the run and data snapshot
anchors. PR 13 adds the `0003_artifact_tables` Alembic revision for artifact
manifest metadata and artifact entry projections. PR 14 adds the
`0004_research_review_tables` Alembic revision for research note metadata and
generic review/audit events. PR 19 adds no schema, table, migration, or
metadata changes. PR 20 adds no schema, table, migration, metadata, code, test,
dependency, workflow, Docker Compose, or devcontainer changes. PR 22 adds no
schema, table, migration, metadata, code, test, dependency, workflow, Docker
Compose, devcontainer, package export, or lockfile changes. PR 23 adds only
optional local disposable Postgres Compose infrastructure and docs; it changes
no migrations, tests, package code, dependencies, workflows, CI services,
repository boundaries, package exports, or lockfiles. PR 24 adds only an
isolated GitHub Actions Postgres migration smoke job and documentation; it
changes no migrations, tests, package code, dependencies, Docker Compose
configuration, repository boundaries, package exports, or lockfiles. PR 25 adds
only idempotency, replay, uniqueness, concurrency, retry, and conflict policy
documentation; it changes no code, tests, migrations, schema/table definitions,
contracts, generated schemas, dependencies, workflows, Docker Compose, package
exports, repository implementation, or execution paths.
PR 26 adds only the artifact-manifest run identity migration and matching
metadata/catalog documentation and tests; it changes no contracts, generated
schemas, mappers, hashing, protocols, statements, dependencies, workflows,
Docker Compose configuration, repository implementation, insert execution, or
application integration. PR 27 adds only pure persistence result/disposition
types, protocol return-type updates, tests, and documentation; it changes no
migrations, table metadata, constraints, DB services, live migration behavior,
contracts, generated schemas, dependencies, workflows, Docker Compose
configuration, repository implementation, insert execution, or application
integration.
PR 28 adds only pure persistence-domain error/context types, package exports,
tests, and documentation; it changes no migrations, table metadata,
constraints, indexes, DB services, live migration behavior, contracts,
generated schemas, dependencies, workflows, Docker Compose configuration,
repository implementation, insert execution, database exception translation,
retry behavior, logging behavior, or application integration.
PR 29 adds only inert targeted PostgreSQL statement shapes, tests, and
documentation; it changes no migrations, table metadata, constraints, indexes,
DB services, live migration behavior, contracts, generated schemas,
dependencies, workflows, Docker Compose configuration, repository
implementation, insert execution, replay `SELECT`, hash comparison, transaction
behavior, database exception translation, aggregate verification, retry
behavior, logging behavior, or application integration.
PR 30 adds only pure exact constraint-name translation, tests, package export,
and documentation; it changes no migrations, tables, SQLAlchemy metadata,
constraints, indexes, DB services, Docker Compose configuration, CI workflows,
live migration behavior, contracts, generated schemas, dependencies, repository
implementation, insert execution, replay `SELECT`, hash comparison, transaction
behavior, SQLAlchemy/psycopg exception extraction, SQLSTATE handling, exception
chaining, aggregate verification, retry behavior, logging behavior, or
application integration.

Add DB model definitions only if intentionally scoped. Keep the DB layer
separate from backtest execution. Add a local Postgres/devcontainer story later
if needed, without introducing vendor, broker, credential, or cloud-specific
assumptions.

No APIs or run writers should be added until persistence primitives pass tests.
Lifecycle transition checks, idempotency enforcement, correction handling, and
append-only policy remain future service or repository responsibilities. The
row mapping helpers only shape validated data into projected rows. The
statement builders only turn those rows into non-executing SQLAlchemy Core
`Insert` objects for future repositories to execute deliberately. Repository
execution remains intentionally blocked until idempotency, duplicate handling,
transaction behavior, correction semantics, artifact-manifest versioning where
needed, database/constraint exception translation, and the live DB test harness
are approved.

The PR 21 live Postgres harness keeps write-path execution deferred. The live
test is local opt-in and migration-only: it runs Alembic `upgrade head` against
a disposable local Postgres database and then inspects PostgreSQL catalogs. The
harness verifies the Alembic version table/state, table existence, `JSONB`
columns, primary keys, important unique constraints, check constraints, indexes,
and the `run_artifact_entries.manifest_id` foreign key to
`run_artifact_manifests`.

The harness does not insert data, execute statement builders, execute
repository writes, test idempotency or conflict behavior, test correction or
lifecycle behavior, use SQLite as a substitute, require CI secrets, add a CI
Postgres service, run FastAPI/backtest integration, or write experiment runs
from backtests. Downgrade testing remains deferred.

PR 23 adds optional local Docker Compose infrastructure for that harness, but it
does not change the harness behavior. The live migration test remains
migration-only and double opt-in through `QUANT_RUN_LIVE_DB_TESTS=1` and
`QUANT_TEST_DATABASE_URL`.

Before PR 24, the PR 23 Compose path was manually validated with Docker:
`postgres:17.10` pulled successfully, the container started, the live migration
smoke test passed with `1 passed`, and `docker compose down -v` removed the
container, network, and named volume so no persistent local test DB state
remained.

PR 24 adds CI Postgres only for migration validation. The CI job uses a
GitHub Actions `postgres:17.10` service container with
`quant_platform_test`/`quant_test` test-only values, maps the service to
localhost for the existing URL safety helper, and runs only
`uv run pytest -m live_db tests/test_live_postgres_migrations.py`. The normal
tooling CI job remains unchanged and does not depend on Postgres. The CI
migration smoke remains Alembic upgrade-head and catalog-inspection only.

After PR 30, the artifact-manifest identity schema blocker is resolved, the
successful-write result vocabulary exists, the pure domain error taxonomy
exists, targeted PostgreSQL insert-attempt statement shapes exist, and pure
exact constraint-name classification exists. The next expansion gates remain
SQLAlchemy/psycopg exception extraction, constraint-name extraction from driver
diagnostics, exception chaining at the repository boundary, repository
skeleton, repository implementation, SQL execution, replay `SELECT`, hash
comparison, caller-owned transaction behavior, aggregate replay/integrity
verification, live insert/replay/conflict tests, application/backtest
integration, and SQLite persistence policy if it is ever reconsidered. Each
gate requires separate approval before it changes code, tests, dependencies,
workflows, infrastructure, or migrations.

## Future DB Test Strategy

When DB work begins, plan tests for:

- Migration upgrade smoke tests against live Postgres.
- Catalog inspection for table creation, `JSONB` columns, primary keys,
  important unique constraints, check constraints, indexes, and the
  artifact-entry foreign key.
- Later downgrade smoke tests, only after downgrade policy is approved.
- Later insert fixture tests for each top-level contract, only after repository
  or insert execution semantics are approved.
- Later idempotent re-insert with the same hash, only after duplicate/conflict
  behavior is approved.
- Later rejection of the same ID with a different `contract_hash` unless using
  a correction path, only after correction semantics are approved.
- Later querying by common indexes.
- Later `review_events` append-only behavior.
- Later `run_artifact_entries` projection from manifest.
- No artifact file existence checks.
- No hash verification side effects.
- No broker, live trading, or paper trading behavior.

Do not add fake or mock `Connection` execution tests before repository execution
is approved. They can prove statement calls and ordering, but they cannot
validate Postgres JSONB behavior, server defaults, uniqueness behavior,
transaction rollback, or conflict semantics. SQLite persistence tests remain
avoided because JSONB and Postgres behavior differ. Live Postgres tests should
start only when DB driver and execution scope are approved. Live migration tests
are not repository tests and must not execute statement builders or write
contract fixtures.

## Validation Commands

For persistence statement-builder changes, run:

```bash
git diff --check
uv run ruff format --check .
uv run ruff check .
uv run mypy packages/research-sdk/src
uv run python -m research_sdk.contracts.json_schema --output-dir packages/research-sdk/schema --check
uv run alembic -c alembic.ini heads
uv run alembic -c alembic.ini history
uv run pytest tests/test_live_postgres_url_safety.py
uv run pytest tests/test_persistence_hashing.py tests/test_persistence_mappers.py tests/test_persistence_protocols.py tests/test_persistence_statements.py
uv run pytest
```

If `uv` is unavailable on `PATH`, use `python -m uv` as the equivalent command
prefix.
