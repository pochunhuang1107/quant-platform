# Persistence Repository Plan

## Purpose

PR 15 added canonical identity primitives for future persistence write paths.
PR 16 adds pure row mapping helpers that project validated contracts into
DB-shaped row dictionaries. These helpers still do not add repositories,
database writes, a DB driver, live Postgres tests, SQLite persistence tests, or
application integration.

PR 17 adds repository protocol interfaces and a minimal result type. These
protocols define the future write boundary shape only. They do not implement
writes, build SQLAlchemy insert statements, connect to a database, add a DB
driver, or introduce live Postgres or SQLite persistence tests.

PR 18 adds SQLAlchemy Core insert statement builders. These builders create
inert `Insert` objects by binding mapper-produced rows to the current table
metadata. They still do not execute statements, implement repositories, connect
to a database, add a DB driver, or introduce live Postgres or SQLite
persistence tests.

PR 19 is documentation-only. It hardens repository execution semantics before
any repository skeleton, SQLAlchemy repository implementation, database write
execution, DB driver, live Postgres test harness, SQLite persistence test, or
application integration exists.

PR 20 is documentation-only. It defines the future live Postgres test harness
boundary before adding a DB driver, Docker Compose service, CI Postgres service,
or executable live DB tests. That harness design does not change repository
execution status: repository skeletons, SQLAlchemy repository implementations,
database write paths, statement execution, DB drivers, live Postgres tests,
SQLite persistence tests, FastAPI/backtest integration, and experiment run
writing from backtests remain deferred.

The immediate boundary is contract hashing:

- `canonical_contract_json(contract)`
- `contract_sha256(contract)`
- `canonical_json_sha256(payload)`

These helpers define how validated contract payloads become stable
`contract_hash` values for audit and idempotency metadata.

## Validation Boundary

Pydantic contracts remain the validation boundary. Future repositories must
accept validated contract objects such as `ExperimentRunRecord`,
`DataSnapshotManifest`, `RunArtifactManifest`, `ResearchNote`, and
`ReviewMetadata`. Repositories must not accept raw dictionaries as trusted
contract input or hide validation rules that belong in Pydantic contracts.

When repositories are added later, they should compute `contract_hash`
internally with `contract_sha256()`. Callers should not provide trusted
`contract_hash` values because caller-provided hashes can drift from the raw
validated contract payload actually stored by the database layer.

## Hash Policy

`contract_hash` is computed from compact canonical JSON produced from
`contract.model_dump(mode="json")` with stable key ordering. The hash includes
all contract fields in that JSON payload, including `schema_version` when the
contract has one. `schema_version` is part of contract identity because the
same logical values under a different schema version may have different
interpretation.

`contract_hash` excludes database-generated fields such as `inserted_at`
because those fields are not part of the Pydantic contract payload.

`contract_hash` is audit and idempotency metadata only. It is not artifact
content hash verification, data file verification, parquet inspection, storage
IO, object existence checking, or evidence that an external URI is reachable.
Artifact `content_hash` fields remain declared contract metadata. The
database/repository layer must not verify artifact files.

`canonical_json_sha256(payload)` is a low-level deterministic helper for
JSON-compatible mappings. It exists for direct dict-order determinism tests and
row-mapping support, but it is still not artifact content hashing and it does
not read or verify files.

## Row Mapping Boundary

PR 16 adds pure row mapping helpers in `research_sdk.persistence.mappers`.
These helpers are the column projection boundary between validated Pydantic
contracts and the current persistence tables. They return row dictionaries
whose keys match the current table columns except for `inserted_at`, which is
omitted because it is filled by the database.

The mappers accept validated `ExperimentRunRecord`, `DataSnapshotManifest`,
`RunArtifactManifest`, `ResearchNote`, and `ReviewMetadata` objects. They
compute `contract_hash` internally with `contract_sha256()` for contract-backed
rows and store the full validated contract payload as `raw_contract` using
`contract.model_dump(mode="json")`. Review event rows store `raw_review` from
`review.model_dump(mode="json")`; they do not add `event_hash` or
`schema_version` because there is no standalone review event contract yet.

The artifact manifest mapper requires a caller-provided `manifest_id` because
the current `RunArtifactManifest` contract does not contain one. ID generation
policy belongs to future application or repository code. The review event
mapper likewise requires caller-provided `review_event_id`, `subject_type`, and
`subject_id`. The mapper validates `subject_type` against the current
persistence-local review subject values, because that field is supplied outside
the current contracts.

Row mappers are not repositories. They do not import SQLAlchemy table metadata,
build insert statements, execute writes, create sessions, connect to a
database, read files, inspect storage, verify artifact hashes, enforce
lifecycle transitions, or perform review/trading approval behavior.

## Repository Protocol Boundary

PR 17 adds `research_sdk.persistence.protocols` with an aggregate
`ExperimentLedgerRepository` protocol and `PersistedRecordMetadata` result
dataclass. The protocol is explicit per current contract/table boundary:

- `record_experiment_run(run)`;
- `record_data_snapshot_manifest(snapshot)`;
- `record_run_artifact_manifest(manifest_id=..., manifest=...)`;
- `record_research_note(note)`;
- `append_review_event(review_event_id=..., subject_type=..., subject_id=..., review=...)`.

The `record_*` naming communicates ledger intent without implying upsert,
idempotency, or SQL insert behavior before implementation semantics are
designed. `append_review_event` remains explicit because `review_events` is
append-only-oriented metadata.

The protocol accepts validated Pydantic contract objects only. It does not
accept raw dictionaries, caller-provided `contract_hash` values, sessions, unit
of work objects, table objects, insert statements, database connections, or
storage handles. Future implementations should compute `contract_hash`
internally with the existing hashing and row mapping boundary.

`manifest_id` remains caller-provided for `RunArtifactManifest` persistence
because the current contract does not contain that ID. `review_event_id`,
`subject_type`, and `subject_id` remain caller-provided for
`ReviewMetadata` persistence because there is no standalone `ReviewEvent`
contract.

`PersistedRecordMetadata` contains `table_name`, `primary_key`, and optional
`contract_hash`. `contract_hash` is optional because `review_events` currently
has no `event_hash` or `contract_hash`. Database-generated `inserted_at`,
created/idempotent flags, row counts, and artifact entry counts are deferred
until a repository implementation and DB-returned state exist.

The protocols do not import SQLAlchemy, Alembic, table metadata, database
helpers, row mapper functions, hashing helpers, filesystem helpers, storage
SDKs, or vendor SDKs. They are synchronous only; async protocols, exceptions,
session/unit-of-work abstractions, lifecycle enforcement, idempotency
enforcement, append-only enforcement, and approval/trading behavior remain
future design work.

## Statement Builder Boundary

PR 18 adds `research_sdk.persistence.statements` as the SQLAlchemy Core
statement-building boundary. The module accepts validated Pydantic contracts,
calls the existing row mappers internally, and binds the resulting row
dictionaries to the current SQLAlchemy Core table metadata.

The public builders are explicit per current table boundary:

- `build_experiment_run_insert(run)`;
- `build_data_snapshot_manifest_insert(snapshot)`;
- `build_run_artifact_manifest_inserts(manifest_id=..., manifest=...)`;
- `build_research_note_insert(note)`;
- `build_review_event_insert(review_event_id=..., subject_type=..., subject_id=..., review=...)`.

`build_run_artifact_manifest_inserts()` returns a frozen grouped dataclass with
one manifest `Insert` and one entry `Insert` per artifact entry. `manifest_id`
remains caller-provided because `RunArtifactManifest` does not contain that
identifier. `review_event_id`, `subject_type`, and `subject_id` remain
caller-provided for `ReviewMetadata` because there is no standalone
`ReviewEvent` contract. The mapper path validates `subject_type`.

Statement builders do not accept raw row dictionaries as public input and do
not accept caller-provided `contract_hash` values. The mappers compute
`contract_hash` from validated contracts where current tables store one.

The returned `Insert` objects are not write paths. They are inert SQLAlchemy
objects until a future repository explicitly executes them. PR 18 does not
choose idempotency, upsert, `ON CONFLICT`, duplicate handling, correction,
append-only, lifecycle, or session/unit-of-work semantics.

The statement module may import SQLAlchemy table metadata because it is the SQL
binding boundary. It must not import repository protocols, database URL
helpers, engine/session/connection helpers, Alembic, DB drivers, filesystem
helpers, storage SDKs, vendor SDKs, or approval/trading workflow code.

## Repository Execution Semantics

PR 19 intentionally does not add a repository skeleton, repository
implementation, database execution path, DB driver, live Postgres test harness,
SQLite persistence test, FastAPI integration, backtest integration, experiment
run writer, session abstraction, or unit-of-work abstraction. It records the
execution semantics required before any future write implementation is added.

Future repository implementations should accept an injected SQLAlchemy
`Connection`. They should not accept an `Engine`, `Session`, DB URL, raw row
dictionary, raw SQLAlchemy statement, storage handle, or caller-provided
`contract_hash`. They should not create engines, look up database URLs, or own
database configuration. Repository methods should continue to accept validated
Pydantic contracts, plus caller-provided identifiers only where current
contracts do not contain them, such as `manifest_id`, `review_event_id`,
`subject_type`, and `subject_id`.

Transaction scope should be caller-owned. Repository implementations should not
silently create, commit, or roll back transactions. Future application or
service layers should decide transaction boundaries and call repositories
inside an already-managed connection and transaction context.

Future repository methods should call the existing statement builders. The
statement builders remain the SQL construction boundary, and repository
implementations should not duplicate mapper projection logic or expose raw row
dictionaries as public input.

Artifact manifest persistence must be atomic across one
`run_artifact_manifests` row and all corresponding `run_artifact_entries` rows.
Those statements must execute in one caller-owned transaction. Partial artifact
manifest persistence is invalid. Repository code must not perform artifact file
IO, object storage IO, file existence checks, or artifact `content_hash`
verification.

The target duplicate policy is documented but not implemented in PR 19. The
same primary key plus the same `contract_hash` may be idempotent in a future
write path. The same primary key plus a different `contract_hash` should reject
unless the caller uses an explicit correction or supersession flow. Silent
overwrite is prohibited. Generic `INSERT` execution without an approved
conflict policy is not enough. `ON CONFLICT`, upsert behavior, duplicate
handling, and the choice between pre-read checks, `ON CONFLICT`, or
service-layer replay workflows remain deferred.

`review_events` remain append-only by `review_event_id`. They currently have no
`event_hash`, `contract_hash`, or `schema_version`. Idempotent replay for
review events remains deferred until event identity is designed. A duplicate
`review_event_id` should reject by primary key for now. `ReviewMetadata`
persistence must not imply trading approval, risk authorization, paper trading
approval, or live trading approval. A standalone `ReviewEvent` contract remains
a future consideration.

`PersistedRecordMetadata` remains minimal: `table_name`, `primary_key`, and
optional `contract_hash`. Database-generated `inserted_at`, created flags,
idempotent flags, affected row counts, artifact entry counts, and other
DB-returned metadata remain deferred because they require real DB execution
semantics and likely DB-returned state.

Lifecycle transition enforcement remains future service-layer work.
Completed-run append-only enforcement remains future service-layer or
repository-design work. Correction and supersession enforcement remain future
service-layer work. Repository writes must not become hidden trading approval,
risk approval, paper trading, or live trading gates.

Do not add fake or mock `Connection` execution tests yet. Such tests can prove
statement calls and ordering, but they cannot validate Postgres JSONB behavior,
server defaults, uniqueness behavior, transaction rollback, or conflict
semantics. Avoid false confidence. A live Postgres test harness should be added
only after DB driver and execution semantics are approved. SQLite persistence
tests remain avoided because JSONB and Postgres behavior differ.

PR 20 documents that the first future executable live harness should be
migration-only. Future live DB migration tests may run Alembic `upgrade head`
against disposable Postgres and inspect catalog state, but they are not
repository tests. They must not insert contract fixtures, execute statement
builders, execute repository writes, test idempotency or conflict behavior, test
correction or lifecycle behavior, or imply that a DB write path exists.

## Future Repository Responsibilities

Future repositories should:

- accept validated Pydantic contract objects;
- compute `contract_hash` internally;
- accept an injected SQLAlchemy `Connection`;
- operate inside caller-owned transaction scope;
- call existing statement builders for SQL construction;
- store raw validated contract JSON for audit and replay;
- keep artifact and data hashes as declared metadata only;
- write artifact manifest and entry rows atomically when execution is approved;
- avoid file IO, object storage IO, vendor calls, and hash verification;
- avoid accepting `Engine`, `Session`, DB URLs, raw rows, raw statements,
  storage handles, or caller-provided `contract_hash` values;
- avoid becoming an approval gate for research or trading decisions.

Future duplicate handling should follow this policy:

- the same primary key plus the same `contract_hash` may be idempotent;
- the same primary key plus a different `contract_hash` should reject unless an
  explicit correction or supersession path is used;
- silent overwrite is prohibited.

Completed-run append-only rules and lifecycle transition rules remain future
service-layer validation. They should not be hidden inside low-level row
mapping helpers or generic repository upserts.

Review approvals are metadata only. Repository code must not treat
`ReviewMetadata` as trading authorization, risk approval execution, paper
trading approval, or live trading approval.

## Deferred Scope

The following remain deferred after PR 20:

- repository skeletons;
- SQLAlchemy repository implementations;
- database write paths;
- statement execution;
- sessions or unit-of-work abstractions except as future design;
- DB driver dependencies such as `psycopg` or `asyncpg`;
- live Postgres tests;
- SQLite persistence tests, because JSONB/Postgres behavior differs;
- idempotency, upsert, duplicate handling, and `ON CONFLICT` behavior;
- lifecycle, correction, and append-only enforcement;
- FastAPI endpoints;
- backtest integration;
- artifact IO or storage IO;
- data ingestion or vendor API calls;
- file existence checks or artifact content hash verification;
- markdown/report rendering;
- UI, search, indexing, embeddings, semantic memory, knowledge graph, LLM
  summarization, or agent workflow execution;
- broker integration, paper trading, or live trading.
