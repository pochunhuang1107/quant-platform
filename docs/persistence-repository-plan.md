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

PR 21 adds the first local opt-in live Postgres migration harness. It adds a
dev-only sync `psycopg` v3 driver, `live_db` marker registration, URL safety
tests, and an Alembic `upgrade head` plus catalog inspection smoke test. This is
not repository coverage. It does not add repository skeletons, repository
implementations, DB write paths, statement execution, contract fixture insert
tests, idempotency/conflict tests, SQLite persistence tests, FastAPI/backtest
integration, or experiment run writing from backtests.

PR 22 is documentation-only. It adds the local live Postgres migration harness
runbook in [Persistence Setup](persistence-setup.md) and records that the PR 21
harness review found no required safety-code or test change. It does not add or
change repository code, repository skeletons, DB execution, tests, dependencies,
workflows, Docker Compose, devcontainer configuration, schemas, migrations,
contracts, package exports, or lockfiles.

PR 23 adds optional local Docker Compose infrastructure for disposable Postgres
under `infra/db/docker-compose.yml` and documentation for using it with the
existing migration smoke harness. This does not change repository boundaries:
Compose does not add repository skeletons, repository implementations, insert
execution, statement builder execution, contract fixture inserts, DB write
paths, SQLite persistence tests, FastAPI/backtest integration, CI Postgres, or
application runtime services.

PR 24 adds an isolated GitHub Actions Postgres migration smoke job. This does
not change repository boundaries: the CI job runs only the existing Alembic
upgrade-head and catalog-inspection live migration test against a disposable
service container. It does not execute statement builders, insert contract
fixtures, execute repository writes, add repository skeletons, add repository
implementations, choose transaction semantics, choose duplicate/conflict
behavior, add SQLite persistence tests, or integrate with FastAPI/backtests.

PR 25 is documentation-only. It defines the approved idempotency, replay,
uniqueness, concurrency, retry, and conflict policy before any persistence
execution code exists. It does not add or change package code, package exports,
tests, migrations, schema/table definitions, contracts, generated schemas,
dependencies, workflows, Docker Compose, repository skeletons, repository
implementations, SQLAlchemy execution, `ON CONFLICT` builders, insert execution,
fixture persistence, live insert/conflict tests, FastAPI/backtest integration,
artifact or object-storage IO, data ingestion, broker integration, paper
trading, live trading, credentials, or secrets.

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
PR 21 adds only a migration smoke harness, and PR 23 adds only optional local
Postgres Compose infrastructure for that harness. PR 24 adds only an isolated
CI service-container job that runs that same migration smoke harness.
Repository execution remains deferred.

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

PR 21 implements the first executable live harness as migration-only. Live DB
migration tests may run Alembic `upgrade head` against disposable local Postgres
and inspect catalog state, but they are not repository tests. They must not
insert contract fixtures, execute statement builders, execute repository writes,
test idempotency or conflict behavior, test correction or lifecycle behavior, or
imply that a DB write path exists.

See the local live Postgres migration harness runbook in
[Persistence Setup](persistence-setup.md) for the exact command, safety
checklist, troubleshooting notes, and expansion gates. The runbook does not
change the repository boundary: live migration tests remain separate from
repository execution, statement builders remain inert, and repository
implementation remains deferred.

The local Docker Compose service documented there is only infrastructure for a
disposable Postgres instance used by the same migration smoke harness. Compose
does not make live migration tests repository tests, does not approve statement
execution, and does not change transaction, idempotency, duplicate, correction,
or lifecycle semantics.

The PR 24 GitHub Actions Postgres job is also only infrastructure for the same
migration smoke harness. It uses an isolated disposable CI service container and
does not make live migration tests repository tests, does not approve statement
execution, and does not change transaction, idempotency, duplicate, correction,
or lifecycle semantics.

## Idempotency, Replay, and Conflict Policy

PR 25 is documentation-only. It defines the policy that must be approved before
any persistence execution code is introduced, but it does not implement database
execution, repository code, `ON CONFLICT` builders, insert tests, live conflict
tests, migrations, contracts, package exports, or application integration.

### Definitions

Logical identity is the durable entity identity used to determine whether an
attempted write addresses an existing record.

Exact replay means the attempted write has the same logical identity and the
same canonical contract payload/hash as an already-persisted record.

Idempotent replay is an accepted exact replay that returns a replay disposition
without inserting, updating, or mutating stored state.

Duplicate alias means a different supplied primary identity attempts to
represent an already-recorded natural or logical entity.

Hash conflict means the attempted write has the same logical identity as an
existing record but a different canonical contract hash.

Primary-key conflict means a collision on the entity's database primary key.

Natural-key conflict means a collision on a non-primary uniqueness rule or
policy-level natural identity.

Correction means a future explicit flow that records a corrected replacement
while preserving the original record.

Supersession means a future explicit relationship where a new immutable record
replaces an older immutable version.

Lifecycle update means an explicit state transition outside the initial
insert-only persistence path.

Append-only event means an event record that is never silently updated or
overwritten.

### Global Invariants

- Same logical identity plus same canonical hash is an idempotent replay, but
  only when the stored entity supports hash verification.
- Same logical identity plus different canonical hash is a conflict and must
  reject.
- Different logical identity plus same canonical hash is generally allowed
  unless a table-specific natural-key or alias policy forbids it.
- A new primary key plus a conflicting natural or unique key is a natural-key
  conflict or duplicate alias, not replay.
- The initial persistence path is insert-only.
- The initial persistence path must never update, overwrite, repair, merge,
  mutate, perform lifecycle transitions, or silently replace stored state.
- Corrections and supersessions require explicit future flows using new
  identities and explicit relationships.

### Canonical Payload Rules

- Canonical hashes come only from the existing `contract_sha256()` helper.
- Callers must never provide a trusted `contract_hash`.
- `raw_contract` and `raw_review` originate from `model_dump(mode="json")`.
- `inserted_at` is DB-generated and excluded from canonical payloads.
- `schema_version` remains part of the hash when present.
- Repository implementations must not reproduce or fork canonicalization logic.
- Raw payloads must not appear in conflict logs or exceptions.

### Per-Entity Policy Matrix

| Entity/table | Logical identity | Replay behavior | Conflict behavior | Boundary notes |
| --- | --- | --- | --- | --- |
| `experiment_runs` | `run_id` | Same `run_id` and same `contract_hash` is replay. | Same `run_id` and different `contract_hash` is conflict. | `experiment_id` is reference/context, not replay identity. Persisted run records are immutable in the initial path. Status transitions remain outside the initial persistence path. |
| `data_snapshot_manifests` | `snapshot_id` | Same `snapshot_id` and same `contract_hash` is replay. | Same `snapshot_id` and different `contract_hash` is conflict. | Initial persisted manifests are immutable. Snapshot replacement or correction requires a future explicit flow. |
| `run_artifact_manifests` | Primary identity: `manifest_id`. Natural aggregate identity for the initial platform: `run_id`. | Same `manifest_id`, same `contract_hash`, and matching complete entry projection is replay. | Same `manifest_id` and different `contract_hash` is conflict. Different `manifest_id` for the same `run_id` is conflict, regardless of whether the hash matches. Same `run_id` and same `contract_hash` under another `manifest_id` is duplicate alias, not replay. Same `run_id` and different `contract_hash` is unsupported manifest versioning and must reject. | Initial policy permits exactly one artifact-manifest aggregate per `run_id`. Multiple manifest versions are not permitted until an explicit version or supersession model is approved. |
| `run_artifact_entries` | `(manifest_id, artifact_id)`, only inside the parent aggregate. | Entries have no independent replay path. Parent replay requires the same manifest hash and the exact complete projected entry set. | Missing entries, extra entries, or differing entry values indicate aggregate integrity failure. | Entries must never be written independently. No automatic repair, partial upsert, best-effort entry insertion, or independent entry mutation is allowed. |
| `research_notes` | `note_id` | Same `note_id` and same `contract_hash` is replay. | Same `note_id` and different `contract_hash` is conflict. | Persisted note versions are immutable. `updated_at` and `updated_by` are values inside one immutable note version; they are not authorization to mutate the stored row. Revisions require a new `note_id` using `parent_note_id` or `supersedes_note_id`. No silent note editing is allowed. |
| `review_events` | `review_event_id` | No idempotent replay claim exists for now. | Duplicate `review_event_id` always rejects for now. | Events remain append-only. Do not compare `raw_review` directly to infer replay. A future standalone `ReviewEvent` contract with `schema_version` and `event_hash` is required before replay semantics can be approved. `ReviewMetadata` is audit/review metadata and is not trading or risk authorization. |

Current artifact-manifest constraints are not sufficient for execution approval.
`UNIQUE(run_id, contract_hash)` prevents one duplicate-alias case: a different
`manifest_id` cannot reuse the exact same manifest hash for the same `run_id`.
The current schema still permits the same `run_id` with different manifest
hashes. Therefore one-manifest-per-run is currently a repository/service policy
and is not concurrency-safe through DB constraints alone. Artifact-manifest
execution must not be approved until either a later migration adds appropriate
`run_id` uniqueness or an explicit manifest version/supersession model is
approved. PR 25 does not modify migrations.

### Artifact Aggregate Atomicity

Artifact manifest persistence must be atomic across the parent
`run_artifact_manifests` row and all projected `run_artifact_entries` rows.
Those rows must be written in one caller-owned transaction when execution is
approved. Entries must never be written independently.

Replay requires the same manifest hash and the exact complete projected entry
set. Missing entries, extra entries, or differing entry values indicate
aggregate integrity failure. Partial aggregate state should be treated as
corruption or interrupted external transaction state, not as replay. The initial
implementation must not automatically repair partial state, perform partial
upserts, or make best-effort entry insertions.

### Concurrency Policy

For concurrent identical hash-backed writes, one insert may succeed and the
other must deterministically resolve as replay. Neither write may overwrite or
mutate stored state.

For concurrent conflicting writes, one insert may succeed first and the other
must deterministically receive a conflict. Last-write-wins behavior, silent
updates, and silent replacement are prohibited.

Future execution must avoid:

- pre-read as the only concurrency mechanism;
- last-write-wins behavior;
- `ON CONFLICT DO UPDATE`;
- broad untargeted `ON CONFLICT DO NOTHING` that can hide which constraint
  fired.

### Future PostgreSQL Execution Algorithm

This algorithm is a future recommendation only and is not implemented in PR 25:

1. Accept a validated contract through the repository protocol.
2. Produce rows through existing mapper and statement-builder boundaries.
3. Execute targeted `INSERT ... ON CONFLICT ON CONSTRAINT <primary-key> DO
   NOTHING RETURNING ...`.
4. If a row is returned, disposition is `CREATED`.
5. If no row is returned, select the existing row by logical identity inside the
   same caller-owned transaction.
6. Compare the stored `contract_hash`.
7. Same hash means `REPLAYED`.
8. Different hash raises a contract-hash conflict.
9. Translate non-primary unique constraint failures separately as natural-key
   conflict or duplicate alias.
10. Never use `ON CONFLICT DO UPDATE` in the initial write path.

This algorithm is not sufficient for one-manifest-per-run concurrency because
the current schema lacks unique `run_id` enforcement on
`run_artifact_manifests`. Artifact manifests require a schema/versioning
decision before execution.

### Transaction Ownership

- Repository implementations receive an injected SQLAlchemy `Connection`.
- Caller owns transaction scope.
- Repositories do not create, commit, or roll back transactions.
- Repositories may raise; callers decide rollback.
- Artifact manifests and entries use one caller-owned transaction.
- Repositories do not own an `Engine`.
- Repositories do not own a `Session`.
- Repositories do not own DB URL lookup or configuration.
- Repositories do not create hidden nested transactions.
- No unit-of-work abstraction exists yet.

### Future Result and Disposition Requirements

`PersistedRecordMetadata` remains unchanged in PR 25. Before execution is
implemented, a result model or protocol-compatible extension must define:

- disposition: `CREATED` or `REPLAYED`;
- table/entity name;
- primary/logical identity;
- contract hash where applicable;
- `inserted_at` if returned by the DB;
- row count where meaningful;
- aggregate entry count for artifact manifests.

Result surfaces must not expose raw contracts, raw reviews, credentials, full DB
URLs, or sensitive payloads. PR 25 does not implement this result model.

### Future Error Taxonomy

Future implementations should define domain errors before repository execution.
Conceptual errors include:

- `PersistenceConflictError`;
- `ContractHashConflictError`;
- `NaturalKeyConflictError`;
- `AggregateIntegrityError`;
- `DuplicateReviewEventError`;
- `UnsupportedVersioningConflict`, or an equivalent concept, for a second
  artifact manifest under one `run_id` before versioning exists.

Safe error details include table/entity name, logical identity, operation type,
constraint name when available, and short hash prefixes.

Unsafe error details include full payloads, passwords, credentials, secrets, and
full database URLs.

This PR does not lock the exact Python class hierarchy. Error names and
inheritance remain subject to approval before implementation.

### Retry Policy

- Exact replay is safely retryable.
- Contract hash conflict is non-retryable without caller, code, or human
  correction.
- Natural-key conflict is non-retryable unless identity or policy is corrected.
- Unsupported artifact-manifest version conflict is non-retryable.
- Duplicate `review_event_id` is rejected and non-idempotent until event hashing
  exists.
- Transient database errors may be retried only by caller/service policy.
- Repository methods must not hide retry loops.

### Audit and Logging Policy

Future execution may log:

- operation type;
- entity/table;
- safe logical identity;
- `CREATED`, `REPLAYED`, or `REJECTED`;
- short hash prefix where applicable;
- caller-supplied correlation or transaction ID.

Future execution must not log:

- raw payload;
- raw contract or review JSON;
- credentials;
- secrets;
- full DB URL;
- financial decision semantics;
- trading authorization semantics.

### Lifecycle and Correction Boundaries

The following remain outside the initial idempotent insert path:

- experiment-run status transitions;
- note edits;
- review or approval changes;
- correction;
- supersession;
- artifact replacement or versioning;
- snapshot replacement;
- deletes;
- mutable updates;
- trading or risk authorization.

### Current DB Constraint Assessment

Current constraints are sufficient for the existing migration-only foundation:

- current primary keys;
- `contract_hash` columns on hash-backed parent tables;
- `JSONB` payload columns;
- artifact-entry foreign key;
- `UNIQUE(run_id, contract_hash)`;
- current checks and query indexes.

The following remain missing or unresolved before future execution:

- unique one-manifest-per-run enforcement or explicit artifact manifest
  versioning;
- `ReviewEvent` `schema_version` and `event_hash` for replay;
- aggregate completeness enforcement;
- future result/disposition model;
- domain conflict/error mapping;
- correction/supersession model;
- possible future cross-contract foreign keys after ordering/backfill design.

Do not add these in PR 25:

- unique constraints;
- migrations;
- global `contract_hash` uniqueness;
- lifecycle DB constraints;
- polymorphic review-event foreign keys;
- event hash columns.

### Approval Gates Before Execution

Separate approval is required before:

- result/disposition model code;
- error taxonomy code;
- `ON CONFLICT` statement builders;
- live insert tests;
- artifact-manifest uniqueness/versioning migration;
- standalone `ReviewEvent` contract;
- repository skeleton;
- repository implementation;
- transaction execution;
- fixture persistence;
- idempotency/conflict integration tests;
- correction/lifecycle flows;
- application/backtest integration.

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

- the detailed idempotency, replay, and conflict policy above is authoritative;
- hash-backed entities may replay only when logical identity and canonical hash
  match;
- conflicting identities, hashes, natural keys, and aggregate state must reject;
- silent overwrite is prohibited.

Completed-run append-only rules and lifecycle transition rules remain future
service-layer validation. They should not be hidden inside low-level row
mapping helpers or generic repository upserts.

Review approvals are metadata only. Repository code must not treat
`ReviewMetadata` as trading authorization, risk approval execution, paper
trading approval, or live trading approval.

## Deferred Scope

The following remain deferred after PR 25:

- repository skeletons;
- SQLAlchemy repository implementations;
- database write paths;
- statement execution;
- sessions or unit-of-work abstractions except as future design;
- runtime DB driver dependencies and async drivers such as `asyncpg`;
- live Postgres repository/write-path tests;
- SQLite persistence tests, because JSONB/Postgres behavior differs;
- idempotency, replay, duplicate handling, conflict handling, and `ON CONFLICT`
  implementation;
- lifecycle, correction, supersession, and append-only enforcement;
- FastAPI endpoints;
- backtest integration;
- artifact IO or storage IO;
- data ingestion or vendor API calls;
- file existence checks or artifact content hash verification;
- markdown/report rendering;
- UI, search, indexing, embeddings, semantic memory, knowledge graph, LLM
  summarization, or agent workflow execution;
- broker integration, paper trading, or live trading.
