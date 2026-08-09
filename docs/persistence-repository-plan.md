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

PR 27 adds the pure successful-write result vocabulary. It introduces
`PersistenceDisposition`, `PersistedRecordMetadata`, and
`PersistenceWriteResult` value objects and updates repository protocol return
types to expose disposition explicitly. It adds no repository skeleton,
repository implementation, SQLAlchemy execution, `ON CONFLICT` behavior,
migration, table metadata change, transaction implementation, live insert test,
artifact verification, error taxonomy, dependency, or application/backtest
integration.

PR 28 adds the pure persistence-domain error taxonomy. It introduces
`PersistenceErrorContext`, `PersistenceError`, `PersistenceConflictError`,
`ContractHashConflictError`, `NaturalKeyConflictError`,
`UnsupportedVersioningConflictError`, `DuplicateReviewEventError`, and
`AggregateIntegrityError` as deterministic domain interface types. It adds no
repository skeleton, repository implementation, SQLAlchemy execution,
`ON CONFLICT` behavior, database-driver exception translation, retry behavior,
logging behavior, migration, table metadata change, transaction
implementation, live DB behavior, dependency, or application/backtest
integration.

PR 29 upgrades the existing public statement builders to produce inert targeted
PostgreSQL insert-attempt statement shapes for hash-backed top-level records.
It keeps the public builder names unchanged and adds no parallel public
builders. Replay-candidate statements target only named primary-key constraints
with `ON CONFLICT ON CONSTRAINT <primary-key> DO NOTHING RETURNING ...`.
Review events and artifact entries remain strict inserts. PR 29 still adds no
SQL execution, repository implementation, existing-row lookup, hash comparison,
constraint exception translation, transaction behavior, artifact entry
verification, repair behavior, live DB insert tests, migrations, metadata
changes, constraints, dependencies, workflows, Docker Compose changes, or
application/backtest integration.

PR 30 adds the pure exact constraint-name translation boundary. It maps only
approved stable constraint names to existing persistence-domain conflict error
instances and returns `None` for unknown constraints. It does not accept raw
database exceptions, inspect SQLAlchemy or `psycopg` diagnostics, inspect
SQLSTATE, inspect `orig` or `diag`, implement exception chaining, execute SQL,
add repository behavior, add retry behavior, or change migrations, metadata,
constraints, dependencies, Docker Compose, CI workflows, live DB behavior, or
application/backtest integration.

PR 31 adds a narrow adapter for an already-caught SQLAlchemy `IntegrityError`.
The adapter accepts `IntegrityError` only, recognizes only PostgreSQL unique
violation SQLSTATE `23505`, reads SQLSTATE only from `error.orig.sqlstate`, and
reads the constraint name only from `error.orig.diag.constraint_name`. It
delegates the exact nonblank constraint name unchanged to the PR 30
`translate_constraint_violation(...)` function. It has no `diag.sqlstate`,
`pgcode`, SQLAlchemy `error.code`, message, SQL, params, detail, or hint
fallback. Unknown constraints, non-unique integrity violations, and missing or
malformed diagnostics remain untranslated. PR 31 adds no production `psycopg`
import, raises no translated error, implements no exception chaining, executes
no SQL, owns no transaction or rollback behavior, adds no retry behavior, and
changes no migrations, metadata, constraints, dependencies, Docker Compose, CI
workflows, live DB behavior, or application/backtest integration.

PR 32 adds the abstract, non-executing SQLAlchemy repository skeleton. The
public class is
`research_sdk.persistence.sqlalchemy_repository.SqlAlchemyExperimentLedgerRepository`,
and it is also exported from `research_sdk.persistence`. The class accepts one
injected SQLAlchemy `Connection` in its constructor, stores the exact supplied
object in protected `_connection`, declares `__slots__ = ("_connection",)`, and
defines all five methods with exact `ExperimentLedgerRepository` method
signatures. It is abstract and cannot be directly instantiated. It uses
structural typing rather than explicitly inheriting the protocol. PR 32 adds no
concrete method behavior, SQL execution, `Connection.execute`, statement-builder
calls, result construction, `CREATED` or `REPLAYED` classification, replay
`SELECT`, hash comparison, exception catching, error translation calls,
translated exception raising or chaining, transaction creation, commit,
rollback, close or dispose behavior, `Engine`, `Session`, DB URL handling,
retry, logging, artifact aggregate writes, or aggregate verification.

PR 33 adds the experiment-run-only repository execution vertical slice. It
makes `record_experiment_run(run)` concrete while keeping
`record_data_snapshot_manifest()`, `record_run_artifact_manifest()`,
`record_research_note()`, and `append_review_event()` abstract, so the class
remains non-instantiable as a complete production repository. The method
requires an active caller-owned transaction before hashing, statement
construction, or SQL execution. It reuses the existing experiment-run insert
builder and a new experiment-run replay `SELECT` builder, executes through the
injected `Connection`, builds `CREATED` only from `INSERT RETURNING`, and
builds `REPLAYED` only when the stored `run_id` has the same canonical
`contract_sha256()` value. Same `run_id` with a different canonical hash raises
`ContractHashConflictError`; a suppressed replay candidate that cannot be
loaded raises `ReplayLookupError`. The repository does not begin, commit, roll
back, close, dispose, update, overwrite, retry, log, catch `IntegrityError`,
call constraint translators, expose raw contracts, or expose SQL. Snapshot,
note, review-event, and artifact aggregate execution, repository-boundary
exception chaining, and concurrency tests remain future work.

PR 34 adds the data-snapshot-only repository execution vertical slice. It makes
`record_data_snapshot_manifest(snapshot)` concrete while
`record_experiment_run(run)` remains concrete and
`record_run_artifact_manifest()`, `record_research_note()`, and
`append_review_event()` remain abstract, so the repository class remains
abstract. The data-snapshot method reuses the active caller-owned transaction
guard, executes the existing data-snapshot insert builder, builds `CREATED`
from PostgreSQL `RETURNING`, performs a replay `SELECT` by `snapshot_id`,
compares canonical hashes with `contract_sha256()`, returns `REPLAYED` only
for exact `snapshot_id` and hash matches, raises `ContractHashConflictError`
for the same `snapshot_id` with a different hash, and raises
`ReplayLookupError` if a suppressed replay candidate cannot be loaded. It does
not update, overwrite, repair, catch `IntegrityError`, call translators, or
verify external datasets, filesystem paths, S3 objects, vendor APIs, parquet
contents, checksums, row counts, file counts, sizes, availability times, or
leakage assumptions. PR 34 also adds live disposable PostgreSQL coverage for
the snapshot path and expands the existing CI persistence smoke job. Research
note, review-event, and artifact aggregate execution remain future work.

PR 35 adds the research-note-only repository execution vertical slice. It makes
`record_research_note(note)` concrete while `record_experiment_run(run)` and
`record_data_snapshot_manifest(snapshot)` remain concrete and
`record_run_artifact_manifest()` and `append_review_event()` remain abstract, so
the repository class remains abstract. The research-note method reuses the
active caller-owned transaction guard, executes the existing research-note
insert builder, builds `CREATED` from PostgreSQL `RETURNING`, performs a replay
`SELECT` by `note_id`, compares canonical hashes with `contract_sha256()`,
returns `REPLAYED` only for exact `note_id` and hash matches, raises
`ContractHashConflictError` for the same `note_id` with a different hash, and
raises `ReplayLookupError` if a suppressed replay candidate cannot be loaded.
Research notes are immutable insert-only records: `updated_at` and
`updated_by` are contract payload fields, while `inserted_at` is database
persistence metadata. Corrections require a new `note_id` and may use
contract-level `parent_note_id` or `supersedes_note_id` fields, but PR 35 does
not enforce lineage existence, traverse lineage, detect cycles, convert
conflicts into supersession, update, overwrite, catch `IntegrityError`, call
translators, or add generic execution orchestration. PR 35 also adds live
disposable PostgreSQL coverage for the note path and expands the existing CI
persistence smoke job. Review-event and artifact aggregate execution remain
future work.

PR 36 adds the review-event-only repository execution vertical slice. It makes
`append_review_event(...)` concrete while `record_experiment_run()`,
`record_data_snapshot_manifest()`, and `record_research_note()` remain concrete
and `record_run_artifact_manifest()` remains abstract, so the repository class
remains abstract. The review-event method requires an active caller-owned
transaction before statement construction, executes the existing strict
`build_review_event_insert(...)` statement through the injected `Connection`,
builds only `CREATED` from PostgreSQL `RETURNING review_event_id, inserted_at`,
and returns `contract_hash=None` because review events have no event hash or
standalone `ReviewEvent` contract. Duplicate `review_event_id` values always
raise `DuplicateReviewEventError` through the approved SQLAlchemy
`IntegrityError` diagnostic adapter and exact `pk_review_events` constraint
translation. The method does not compare payloads, select existing rows, return
`REPLAYED`, validate subject existence, branch by subject type, update, delete,
own transaction lifecycle, retry, log, or add generic repository orchestration.
Unknown or unapproved `IntegrityError` values are re-raised unchanged. PR 36
also adds live disposable PostgreSQL coverage for created, rollback, identical
duplicate, and changed-payload duplicate behavior and expands the existing CI
persistence smoke job. Artifact aggregate execution remains future work.

PR 37 adds the artifact-manifest aggregate repository execution vertical slice
and completes the concrete SQLAlchemy repository surface. It makes
`record_run_artifact_manifest(...)` concrete, removes the ABC/abstractmethod
machinery from `SqlAlchemyExperimentLedgerRepository`, and keeps structural
typing through `ExperimentLedgerRepository`. The method requires an active
caller-owned transaction before mapping, hashing, statement construction, or
SQL execution. It executes the existing grouped artifact insert builder:
targeted parent `run_artifact_manifests` insert first, then strict
`run_artifact_entries` inserts only when the parent was newly created.
`CREATED` returns the parent `manifest_id`, PostgreSQL `contract_hash`,
PostgreSQL `inserted_at`, and `aggregate_entry_count` equal to the complete
projected entry count.

For replay, PR 37 adds explicit parent and entry replay `SELECT` builders. A
same `manifest_id` replay first verifies the stored canonical manifest hash,
then verifies the stored parent `run_id` projection, and then verifies the
complete stored entry projection against
`run_artifact_manifest_to_rows(...)`, keyed by `artifact_id` and excluding entry
`inserted_at`. Exact replay returns `REPLAYED` with the original parent
`inserted_at` and the verified complete entry count. Same `manifest_id` with a
different canonical manifest hash raises `ContractHashConflictError`. Different
`manifest_id` with the same `run_id` raises
`UnsupportedVersioningConflictError` through the approved SQLAlchemy
`IntegrityError` adapter and `uq_run_artifact_manifests_run_id` translation,
regardless of whether the hash matches. Matching parent hash with a changed
stored parent `run_id`, missing entry, extra entry, or changed entry projection
raises `AggregateIntegrityError`. PR 37 does
not repair, partially upsert, independently persist entries, mutate replayed
entries, verify files, verify artifact content hashes, access object storage,
add application/backtest integration, add migrations, add constraints, or add
concurrency tests. The existing CI Postgres persistence smoke job is expanded
to include the artifact aggregate live repository test.

B1b1 adds durable deterministic `ResearchReportCard` persistence. It introduces
the `research_report_cards` table with `report_card_id` as the natural
deterministic evidence primary key, normalized source/query columns,
`raw_contract`, and `contract_hash = contract_sha256(report_card)` as a
lowercase 64-character SHA-256 hex digest over the entire canonical contract.
The repository adds `record_research_report_card(report_card)` and
`get_research_report_card(report_card_id)`. Writes verify the generic
report-card identity and source coherence before SQL execution, return
`CREATED` for first insert, return `REPLAYED` only for the same
`report_card_id` and same whole-contract hash, and raise
`ContractHashConflictError` for the same ID with changed canonical content.
Source coherence loads the referenced persisted run, data snapshot, benchmark
snapshot, and artifact manifest inside the caller-owned transaction; validates
their `raw_contract`, `contract_hash`, and normalized columns before trusting
them; and then requires report-card lineage, scope, assumptions, metrics,
limitations, and artifact evidence to agree with those durable source
contracts. Foreign-key existence alone is not sufficient evidence integrity.
Caller/source mismatches raise `ResearchReportCardSourceCoherenceError`.
Corrupt durable source anchors raise `PersistenceCorruptionError` and are not
repaired. Readback validates `raw_contract`, recomputes `contract_hash`,
verifies primary-key agreement, reruns generic identity verification, checks
normalized columns against the validated payload, and reruns source-coherence
validation before returning a card.

Generic report-card identity verification now lives in
`research_sdk.report_card_identity` and does not import persistence,
experiment-recording, SQLAlchemy, psycopg, or `backtest_engine`. The
backtest-engine deterministic ETF verifier keeps the
`deterministic-etf-report-card-v1` policy allowlist and delegates generic ID
recomputation to the SDK helper. B1b1 does not add ResearchNote contract
changes, ResearchNote/report-card linkage, a finalized interpretation service,
review-event changes, comparison queries, APIs, workers, real ETF data, paper
trading, live trading, or CI trigger de-duplication.

The persistence primitive boundaries now include:

- `canonical_contract_json(contract)`
- `contract_sha256(contract)`
- `canonical_json_sha256(payload)`
- `PersistenceDisposition`
- `PersistedRecordMetadata`
- `PersistenceWriteResult`
- `PersistenceErrorContext`
- `PersistenceError`
- `PersistenceConflictError`
- `ContractHashConflictError`
- `ReplayLookupError`
- `NaturalKeyConflictError`
- `UnsupportedVersioningConflictError`
- `DuplicateReviewEventError`
- `AggregateIntegrityError`
- `PersistenceCorruptionError`
- `ResearchReportCardSourceCoherenceError`
- `translate_constraint_violation(constraint_name=..., context=...)`
- `translate_sqlalchemy_integrity_error(error=..., context=...)`
- `validate_research_report_card_sources(connection, report_card)`
- `SqlAlchemyExperimentLedgerRepository(connection)`
- `build_experiment_run_replay_select(run_id=...)`
- `build_data_snapshot_manifest_replay_select(snapshot_id=...)`
- `build_run_artifact_manifest_replay_select(manifest_id=...)`
- `build_run_artifact_entries_replay_select(manifest_id=...)`
- `build_research_note_replay_select(note_id=...)`
- `build_research_report_card_replay_select(report_card_id=...)`
- `build_research_report_card_read_select(report_card_id=...)`

These primitives define how validated contract payloads become stable
`contract_hash` values for audit and idempotency metadata, how future
repository writes will report successful created or replayed outcomes, and how
deterministic domain failures are classified from approved exact constraint
names and narrow SQLAlchemy/driver diagnostics without exposing raw payloads,
SQL, params, or database configuration.

## Validation Boundary

Pydantic contracts remain the validation boundary. Future repositories must
accept validated contract objects such as `ExperimentRunRecord`,
`DataSnapshotManifest`, `RunArtifactManifest`, `ResearchNote`, and
`ReviewMetadata`. The report-card repository path also accepts
`ResearchReportCard`. Repositories must not accept raw dictionaries as trusted
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

Because `ResearchReportCard` rows are durable and readback verifies
`contract_sha256(report_card)`, schema changes that alter canonical
`model_dump(mode="json")` output must not be introduced under the same
`schema_version` without an explicit migration or version-aware deserialization
policy. Adding a defaulted field under the same schema version can make old
durable rows appear corrupt even when the original row was valid.

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
`ExperimentLedgerRepository` protocol. PR 27 updates the protocol return type
to `PersistenceWriteResult`, while keeping `PersistedRecordMetadata` importable
from the protocol module for compatibility. The protocol is explicit per
current contract/table boundary:

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

`PersistedRecordMetadata` describes the durable record with `table_name`,
`primary_key`, optional `contract_hash`, and optional `inserted_at`.
`contract_hash` is optional because `review_events` currently has no
`event_hash` or `contract_hash`. `inserted_at` is optional because no
repository execution exists yet; future created results should use the
DB-generated timestamp for the inserted row, and future replayed results should
use the original timestamp of the stored row. Future DB timestamps are expected
to be timezone-aware UTC. Python must never generate `inserted_at` for
persistence results.

`PersistenceWriteResult` describes the successful write-operation outcome with
`disposition`, `record`, and optional `aggregate_entry_count`. It is the common
return type for all repository protocol methods. It is not an error surface, a
retry surface, a SQL execution surface, or a transaction surface.

`PersistenceDisposition` has only `CREATED` and `REPLAYED`. `CREATED` means the
operation inserted the durable row or aggregate. `REPLAYED` means the operation
accepted an exact existing row or aggregate without inserting, updating, or
mutating stored state. Conflict, rejection, and failure are not successful
dispositions and must be represented by future domain exceptions rather than by
successful results. Do not replace the disposition enum with a boolean such as
`created`.

`aggregate_entry_count` is meaningful for artifact-manifest aggregate results
only. For `CREATED`, it represents the complete entry set persisted atomically
with the manifest. For `REPLAYED`, it represents the complete stored entry set
verified during replay. It must never mean attempted entry count, partial
inserts, affected DB rows, SQLAlchemy rowcount, or a successfully processed
subset. No aggregate verification or database IO is implemented by the result
model.

Under the current policy, `append_review_event()` may use the common
`PersistenceWriteResult` return type, but future review-event implementations
should return only `CREATED` until a standalone hashable `ReviewEvent` contract
supports replay semantics.

Result models expose only safe record identity and operation metadata. They do
not expose raw contracts, raw reviews, secrets, credentials, database URLs,
SQL, statement objects, exceptions, retry state, or raw payloads.

The protocols do not import SQLAlchemy, Alembic, table metadata, database
helpers, row mapper functions, hashing helpers, filesystem helpers, storage
SDKs, or vendor SDKs. They are synchronous only; async protocols, exceptions,
session/unit-of-work abstractions, lifecycle enforcement, idempotency
enforcement, append-only enforcement, and approval/trading behavior remain
future design work.

## SQLAlchemy Repository Skeleton Boundary

PR 32 adds `SqlAlchemyExperimentLedgerRepository` in
`research_sdk.persistence.sqlalchemy_repository`. This is the first public
SQLAlchemy-oriented repository type boundary, not a repository implementation.

The constructor is:

```python
SqlAlchemyExperimentLedgerRepository(connection: Connection)
```

The constructor requires a single SQLAlchemy `Connection`, stores that exact
object in protected `_connection`, and does not validate it by calling methods
on it during construction. There is no public connection property, setter,
lifecycle method, factory, transaction argument, optional connection, `Engine`,
`Session`, or DB URL.

The class declares the same five public repository methods as
`ExperimentLedgerRepository`:

- `record_experiment_run(run)`;
- `record_data_snapshot_manifest(snapshot)`;
- `record_run_artifact_manifest(manifest_id=..., manifest=...)`;
- `record_research_note(note)`;
- `append_review_event(review_event_id=..., subject_type=..., subject_id=..., review=...)`.

`record_experiment_run()` is concrete as of PR 33,
`record_data_snapshot_manifest()` is concrete as of PR 34,
`record_research_note()` is concrete as of PR 35, and `append_review_event()`
is concrete as of PR 36. `record_run_artifact_manifest()` is concrete as of
PR 37, and the repository is directly instantiable. All five methods have the
same parameter names, ordering, keyword-only behavior, validated contract annotations,
`ReviewSubjectType | str` behavior, and `PersistenceWriteResult` return
annotation as the protocol.
The class intentionally does not inherit `ExperimentLedgerRepository`;
structural typing remains the boundary, and tests verify protocol conformance
and signature parity.

`__slots__ = ("_connection",)` limits the production state surface to the
protected connection reference. PR 33 adds a private active-transaction guard
that calls only `self._connection.in_transaction()` and raises
`RuntimeError("repository write requires an active caller-owned transaction")`
when no caller-owned transaction is active. It does not add context-manager
behavior, `begin`, `commit`, `rollback`, `close`, `dispose`, `connect`, retry,
or logging methods.

After PR 37 all five repository methods execute their approved vertical slices.
The repository still starts no transactions, commits nothing, rolls nothing
back, and does not close or dispose caller-owned resources. Caller-owned
transaction policy is unchanged. Artifact aggregate execution is explicit to
the final entity path rather than a generic repository framework.

## Statement Builder Boundary

PR 18 adds `research_sdk.persistence.statements` as the SQLAlchemy Core
statement-building boundary. The module accepts validated Pydantic contracts,
calls the existing row mappers internally, and binds the resulting row
dictionaries to the current SQLAlchemy Core table metadata.

The public builders are explicit per current table boundary:

- `build_experiment_run_insert(run)`;
- `build_experiment_run_replay_select(run_id=...)`;
- `build_data_snapshot_manifest_insert(snapshot)`;
- `build_data_snapshot_manifest_replay_select(snapshot_id=...)`;
- `build_run_artifact_manifest_inserts(manifest_id=..., manifest=...)`;
- `build_research_note_insert(note)`;
- `build_research_note_replay_select(note_id=...)`;
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

PR 29 changes only the compiled statement shape for the existing builders:

| Builder / statement | Conflict target | `DO NOTHING` | `RETURNING` | Non-target conflicts |
| --- | --- | --- | --- | --- |
| experiment run | `pk_experiment_runs` | yes | `run_id`, `contract_hash`, `inserted_at` | unsuppressed |
| data snapshot | `pk_data_snapshot_manifests` | yes | `snapshot_id`, `contract_hash`, `inserted_at` | unsuppressed |
| research note | `pk_research_notes` | yes | `note_id`, `contract_hash`, `inserted_at` | unsuppressed |
| artifact manifest | `pk_run_artifact_manifests` | yes | `manifest_id`, `contract_hash`, `inserted_at` | unsuppressed |
| artifact entry | none | no | none | unsuppressed |
| review event | none | no | `review_event_id`, `inserted_at` | unsuppressed |

Replay-candidate top-level statements use PostgreSQL
`ON CONFLICT ON CONSTRAINT <primary-key> DO NOTHING` and safe `RETURNING`
columns only. They do not use untargeted `DO NOTHING`, `DO UPDATE`,
`index_elements`, natural-key constraints, or secondary unique constraints.
The artifact-manifest statement targets only `pk_run_artifact_manifests`; a
collision on `uq_run_artifact_manifests_run_id` remains visible for future
repository execution and can be translated by the PR 30 exact constraint-name
translator to `UnsupportedVersioningConflictError` after a future adapter
extracts that constraint name.

Review events remain strict inserts with `RETURNING review_event_id,
inserted_at`. Duplicate `review_event_id` is not suppressed. Artifact entries
remain strict inserts with no `RETURNING` and no independent replay behavior.

The returned `Insert` objects are not write paths. They are inert SQLAlchemy
objects until a future repository explicitly executes them. Statements do not
return or classify `CREATED` or `REPLAYED` by themselves, do not select
existing rows, do not compare hashes, do not translate constraint exceptions,
do not own transactions, do not verify artifact entries, and do not repair
partial aggregate state.

The statement module may import SQLAlchemy table metadata because it is the SQL
binding boundary. It must not import repository protocols, database URL
helpers, engine/session/connection helpers, Alembic, DB drivers, filesystem
helpers, storage SDKs, vendor SDKs, or approval/trading workflow code.

## Repository Execution Semantics

PR 19 intentionally does not add a repository implementation, database
execution path, DB driver, live Postgres test harness, SQLite persistence test,
FastAPI integration, backtest integration, experiment run writer, session
abstraction, or unit-of-work abstraction. It records the execution semantics
required before any future write implementation is added. PR 32 later adds only
the abstract repository skeleton and does not change these execution semantics.
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

`PersistedRecordMetadata` remains a safe durable-record descriptor:
`table_name`, `primary_key`, optional `contract_hash`, and optional
DB-generated `inserted_at`. Created/replayed outcome and artifact aggregate
entry count belong to `PersistenceWriteResult`. Affected row counts and other
execution metadata remain deferred because they require real DB execution
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
| `run_artifact_manifests` | Primary identity: `manifest_id`. Natural aggregate identity for the initial platform: `run_id`. | Same `manifest_id`, same `contract_hash`, same stored parent `run_id`, and matching complete entry projection is replay. | Same `manifest_id` and different `contract_hash` is conflict. Different `manifest_id` for the same `run_id` is conflict, regardless of whether the hash matches. Same `run_id` and same `contract_hash` under another `manifest_id` is duplicate alias, not replay. Same `run_id` and different `contract_hash` is unsupported manifest versioning and must reject. | Initial policy permits exactly one artifact-manifest aggregate per `run_id`. Multiple manifest versions are not permitted until an explicit version or supersession model is approved. |
| `run_artifact_entries` | `(manifest_id, artifact_id)`, only inside the parent aggregate. | Entries have no independent replay path. Parent replay requires the same manifest hash and the exact complete projected entry set. | Missing entries, extra entries, or differing entry values indicate aggregate integrity failure. | Entries must never be written independently. No automatic repair, partial upsert, best-effort entry insertion, or independent entry mutation is allowed. |
| `research_report_cards` | `report_card_id`, derived from B1a natural evidence identity inputs. | Same `report_card_id` and same `contract_hash` is replay after identity and source-coherence validation. Readback additionally validates `raw_contract`, identity recomputation, normalized column agreement, and source coherence. | Same `report_card_id` and different `contract_hash` is conflict. Caller/source mismatch is `ResearchReportCardSourceCoherenceError`. Corrupt stored report-card or source payload/hash/column mismatch is `PersistenceCorruptionError` on readback. | `report_card_id` intentionally excludes metrics and other non-identity fields, so persistence must compare whole-contract `contract_hash`. Foreign-key existence alone is not sufficient; the card must match the persisted run, snapshots, and artifact manifest. Report cards are immutable factual evidence and are not embedded into `ResearchNote` in B1b1. |
| `research_notes` | `note_id` | Same `note_id` and same `contract_hash` is replay. | Same `note_id` and different `contract_hash` is conflict. | Persisted note versions are immutable. `updated_at` and `updated_by` are values inside one immutable note version; they are not authorization to mutate the stored row. Revisions require a new `note_id` using `parent_note_id` or `supersedes_note_id`. No silent note editing is allowed. |
| `review_events` | `review_event_id` | No idempotent replay claim exists for now. | Duplicate `review_event_id` always rejects for now. | Events remain append-only. Do not compare `raw_review` directly to infer replay. A future standalone `ReviewEvent` contract with `schema_version` and `event_hash` is required before replay semantics can be approved. `ReviewMetadata` is audit/review metadata and is not trading or risk authorization. |

PR 26 makes the artifact-manifest one-manifest-per-run policy concurrency-safe
at the database layer by enforcing `UNIQUE(run_id)` through
`uq_run_artifact_manifests_run_id`. `manifest_id` remains the primary key, and
`run_id` is the enforced natural aggregate identity. The former
`UNIQUE(run_id, contract_hash)` constraint is removed as redundant, and the
former non-unique `ix_run_artifact_manifests_run_id` index is removed because
the unique constraint provides the `run_id` index path. Duplicate existing
`run_id` rows cause migration failure; no automatic cleanup, merge, repair,
deletion, or data rewriting is performed.

Artifact-manifest execution is still not approved. PR 29 adds only the inert
targeted manifest insert statement shape. Repository and insert execution
remain blocked on database/constraint exception translation, repository
skeleton and implementation, aggregate replay/integrity tests, live
insert/replay/conflict tests, and application/backtest integration.

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

Artifact-manifest writes use transaction-scoped PostgreSQL advisory locks to
coordinate the primary `manifest_id` identity and the natural `run_id`
identity before the existing targeted parent insert executes. The repository
acquires locks only inside the caller-owned transaction, first for
`manifest_id` and then for `run_id`, using deterministic SHA-256-derived
namespaced signed-bigint keys. Manifest keys use a non-negative signed-bigint
keyspace, while run keys use a negative signed-bigint keyspace, so
cross-namespace equality is impossible by construction. Same-namespace hash
collisions may conservatively serialize unrelated artifact writes, but they do
not change replay, conflict, or aggregate verification semantics. The fixed
`manifest_id`, then `run_id` order prevents a crossed-key advisory-lock cycle.
Locks remain held until the caller commits or rolls back. Long caller-owned
transactions can therefore block competing artifact-manifest writes; timeout
and retry policy remain caller or service concerns.

Future execution must avoid:

- pre-read as the only concurrency mechanism;
- last-write-wins behavior;
- `ON CONFLICT DO UPDATE`;
- broad untargeted `ON CONFLICT DO NOTHING` that can hide which constraint
  fired.

### Future PostgreSQL Execution Algorithm

This algorithm remains a future recommendation only. PR 29 implements the inert
targeted statement shape, but it does not execute the statements or classify
outcomes:

1. Execute the targeted top-level insert.
2. A returned row means insertion occurred.
3. A future repository builds `CREATED` from the returned safe metadata.
4. No returned row means a targeted primary-key replay candidate.
5. Select the existing row by logical identity inside the same caller-owned
   transaction.
6. Equal canonical hash means `REPLAYED`.
7. Different canonical hash raises `ContractHashConflictError`.
8. Non-target unique failure is translated by exact constraint identity.
9. Artifact replay additionally verifies the stored parent `run_id` projection
   and complete stored entry projection.
10. Missing, extra, or differing entries cause `AggregateIntegrityError`.

The manifest-level `ON CONFLICT` clause alone does not make artifact aggregate
persistence safe. Future entry insertion should occur only after a newly
inserted manifest. Future replay must verify existing entries and must not
insert missing entries, repair partial state, or silently accept mismatched
aggregate projections.

The artifact advisory locks do not add repository-owned retries, savepoints,
transaction begin/commit/rollback behavior, broad untargeted conflict
suppression, `ON CONFLICT DO UPDATE`, repair, update, or entry mutation.

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

### Result and Disposition Model

PR 27 implements the pure successful-write result model before repository
execution. The model is a typed, frozen value-object boundary only:

- `PersistenceDisposition.CREATED`;
- `PersistenceDisposition.REPLAYED`;
- `PersistedRecordMetadata(table_name, primary_key, contract_hash, inserted_at)`;
- `PersistenceWriteResult(disposition, record, aggregate_entry_count)`.

Only successful outcomes belong in `PersistenceDisposition`. Conflicts,
rejections, failures, duplicate review events, natural-key collisions, aggregate
integrity failures, and unsupported artifact-manifest versioning are domain
exceptions, not successful result values.

`PersistedRecordMetadata` describes the durable record. `PersistenceWriteResult`
describes the outcome of a successful write operation. `inserted_at` is
DB-generated and optional until execution exists: `CREATED` uses the inserted
row timestamp, and `REPLAYED` uses the original stored-row timestamp. Python
must not use `datetime.now()` or any other clock to populate this field.

`aggregate_entry_count` represents the complete artifact entry set associated
with an artifact-manifest aggregate. It does not represent attempted inserts,
partial inserts, affected rows, SQLAlchemy rowcount, or a processed subset. No
artifact aggregate verification is implemented in PR 27.

PR 27 adds no repository execution, no SQL or `ON CONFLICT` behavior, no
transaction implementation, and no live insert, replay, or conflict testing.

### Persistence Error Taxonomy

PR 28 implements the pure domain exception vocabulary before repository
execution. The hierarchy is:

```text
PersistenceError
├── PersistenceConflictError
│   ├── ContractHashConflictError
│   ├── NaturalKeyConflictError
│   │   └── UnsupportedVersioningConflictError
│   └── DuplicateReviewEventError
└── AggregateIntegrityError
```

`PersistenceError` is the root catch point for deterministic
persistence-domain failures. It does not automatically wrap infrastructure,
connection, timeout, pool, serialization, deadlock, or other transient database
failures. Those remain outside the taxonomy until a separate translation and
retry policy is approved.

`PersistenceConflictError` is the base for deterministic conflicts with
existing durable state or uniqueness policy. `ContractHashConflictError`
represents the same logical identity with a different canonical contract hash.
Exact same identity plus same hash remains `PersistenceDisposition.REPLAYED`
and is not an error.

`NaturalKeyConflictError` represents a write that collides with a natural or
non-primary uniqueness rule, including duplicate-alias behavior.
`UnsupportedVersioningConflictError` specializes that case for a second
artifact manifest under one `run_id` while artifact-manifest versioning and
supersession are unsupported. A future classification candidate is
`uq_run_artifact_manifests_run_id`, but PR 28 implements no constraint mapping.

`DuplicateReviewEventError` represents a duplicate `review_event_id`. It
subclasses `PersistenceConflictError` directly because review events currently
have no approved replay behavior and `review_event_id` is the event identity,
not a separate natural alias.

`AggregateIntegrityError` represents missing, extra, differing, or partial
artifact aggregate state. It is not necessarily a caller identity conflict, so
it subclasses `PersistenceError` directly. It requires investigation and does
not authorize repair, overwrite, partial upsert, blind retry, or automatic
aggregate verification.

All domain errors accept only `PersistenceErrorContext`. The context fields are
`table_name`, `operation`, `logical_identity`, optional `constraint_name`,
optional `existing_hash_prefix`, and optional `attempted_hash_prefix`.
`table_name` and `operation` must not be blank, and `logical_identity` must not
be empty. Hash prefixes, when present, must be one to twelve lowercase
hexadecimal characters; full 64-character hashes are rejected.

Error messages are generated deterministically from the concrete class name and
safe context fields. `logical_identity` entries are sorted by key before
formatting so equivalent mappings produce the same message. Error contexts and
messages must not contain raw contracts, raw reviews, complete payloads, full
hashes, credentials, passwords, secrets, SQL, statement objects, database URLs,
driver exception text, retry state, or logging state. Callers cannot supply
arbitrary free-form messages or detail mappings.

No SQLAlchemy, Alembic, `psycopg`, DB-driver, or database exception type escapes
through these domain interfaces. PR 28 adds no database exception translation,
repository execution, SQL execution, retry implementation, logging
implementation, or live DB behavior.

PR 30 adds pure exact constraint-name classification for the currently approved
stable constraints:

| Constraint | Domain error |
| --- | --- |
| `pk_review_events` | `DuplicateReviewEventError` |
| `uq_run_artifact_manifests_run_id` | `UnsupportedVersioningConflictError` |

The translator is `translate_constraint_violation(constraint_name=...,
context=...)`. It accepts an exact constraint name and a safe
`PersistenceErrorContext`, not a database exception, SQLSTATE, SQL statement,
constraint object, connection, session, engine, driver diagnostic, arbitrary
message, or retry record. Matching is exact only. Unknown constraints remain
untranslated by returning `None`; there is no prefix-based `pk_*` or `uq_*`
classification and no generic unique-constraint mapping.

If the supplied context has no `constraint_name`, the translator immutably
populates an equivalent copied context before constructing the error. If the
context already has the same `constraint_name`, that exact context object is
reused. If the context has a different `constraint_name`, translation rejects
with a deterministic `ValueError` rather than overriding inconsistent
diagnostics.

The translator returns a domain error instance or `None`; it does not raise the
translated error. A future repository adapter may use it after extracting an
approved constraint name from a raw database exception:

```python
translated = translate_constraint_violation(
    constraint_name=constraint_name,
    context=context,
)
if translated is not None:
    raise translated from database_error
raise
```

PR 31 adds the narrow adapter that may produce the `constraint_name` input for
this pure translator. It translates only an already-caught SQLAlchemy
`IntegrityError`, only when `error.orig.sqlstate` is exactly `23505`, and only
when `error.orig.diag.constraint_name` is a nonblank string. It delegates that
exact string unchanged to `translate_constraint_violation(...)`.

The PR 31 adapter does not import `psycopg` in production code. It does not read
`error.orig.diag.sqlstate`, `error.orig.pgcode`, SQLAlchemy `error.code`,
exception messages, SQL statements, parameters, driver detail, or hints.
Unknown constraints, non-unique integrity violations, and missing diagnostics
remain untranslated by returning `None`. The adapter does not raise the
translated domain error, chain exceptions, execute SQL, create or roll back a
transaction, implement repository behavior, or retry.

Future repository code may use the adapter like this:

```python
try:
    ...
except IntegrityError as database_error:
    translated = translate_sqlalchemy_integrity_error(
        error=database_error,
        context=context,
    )
    if translated is not None:
        raise translated from database_error
    raise
```

PR 31 does not implement that block. PR 36 implements the block only inside
`append_review_event(...)`, where duplicate primary-key violations on
`review_events` translate to `DuplicateReviewEventError` with explicit
exception chaining. Unknown or unapproved `IntegrityError` values are re-raised
unchanged with bare `raise`. Repository-boundary exception catching for
artifact-manifest natural-key conflicts and any broader database failure
classification remain future work.

Future repository classification should follow this policy:

- Existing logical identity plus same canonical hash returns
  `PersistenceWriteResult(REPLAYED)`, not an error.
- Existing logical identity plus different canonical hash raises
  `ContractHashConflictError`. This requires a replay `SELECT` and canonical
  hash comparison; it is not inferred from a constraint name.
- New primary identity plus a non-primary uniqueness collision raises
  `NaturalKeyConflictError`.
- `uq_run_artifact_manifests_run_id` maps to
  `UnsupportedVersioningConflictError`.
- Duplicate `review_event_id` raises `DuplicateReviewEventError`.
- Matching manifest hash but mismatched stored entry projection raises
  `AggregateIntegrityError`. This requires complete aggregate projection
  verification; it is not inferred from a constraint name.
- SQLAlchemy/psycopg transient operational failures are not generically
  converted to conflict errors.

### Retry Policy

- Exact replay is not an error; it is reported as `REPLAYED`.
- Contract hash conflict is non-retryable without caller, code, or human
  correction.
- Natural-key conflict is non-retryable unless identity or policy is corrected.
- Unsupported artifact-manifest version conflict is non-retryable until the
  attempted write changes or versioning is approved.
- Duplicate `review_event_id` is rejected and non-idempotent until event hashing
  exists.
- Aggregate integrity failure requires investigation and must not trigger blind
  retry or automatic repair.
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
- `UNIQUE(run_id)` on `run_artifact_manifests`;
- current checks and query indexes.

The following remain missing or unresolved before future execution:

- `ReviewEvent` `schema_version` and `event_hash` for replay;
- aggregate completeness enforcement;
- domain conflict/error mapping;
- correction/supersession model;
- possible future cross-contract foreign keys after ordering/backfill design.

Artifact-manifest versioning remains intentionally unsupported. Do not add
`manifest_version`, `supersedes_manifest_id`, current/active flags, lifecycle
states, soft deletes, or mutable replacement without a separate review of
logical identity, uniqueness constraints, lineage, replay semantics,
supersession, backfill/migration behavior, and API behavior.

Do not add these in PR 25:

- unique constraints;
- migrations;
- global `contract_hash` uniqueness;
- lifecycle DB constraints;
- polymorphic review-event foreign keys;
- event hash columns.

### Approval Gates Before Execution

Separate approval is required before:

- repository-boundary exception catching and translated exception chaining;
- live insert tests;
- artifact-manifest versioning or supersession migration;
- standalone `ReviewEvent` contract;
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
- write artifact manifest and entry rows atomically in the approved aggregate
  repository path;
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

## Completed Experiment Recording Boundary

The completed-experiment recording boundary adds a narrow application-layer
orchestrator in `research_sdk.experiment_recording`. It accepts already
validated `DataSnapshotManifest`, `ExperimentRunRecord`, caller-supplied
artifact `manifest_id`, and `RunArtifactManifest` objects for one terminal
completed research execution. It validates cross-contract references and
completed-artifact metadata before opening the injected transaction context.

The service uses a `Callable[[], ContextManager[Connection]]`, such as
`engine.begin`, to own the outer transaction as the repository caller. It then
constructs the SQLAlchemy repository from the yielded connection and writes the
data snapshot manifest, experiment run, and artifact manifest aggregate in that
order. Repositories still do not begin, commit, roll back, retry, savepoint,
update, or repair state.

Successful completed-experiment recording preserves individual component
dispositions and permits only these combinations: all three records created,
snapshot replayed with run and artifact created, or all three records replayed.
Any other combination is treated as incomplete pre-existing
completed-experiment state, raises an application-level coherence error, and
lets the transaction context roll back.

This boundary does not add backtest engines, strategy code, run-ID generation,
git or environment inspection, dependency-lock hashing, artifact writing,
artifact storage validation, failed-run persistence, research notes,
API/worker/UI behavior, migrations, schema changes, constraints, indexes, CI
changes, broker integration, paper trading, or live trading.

The deterministic backtest-to-ledger integration adds the first narrow
completed-backtest vertical path. Backtest execution and local artifact writing
still happen outside the database transaction. A pure mapper in
`backtest_engine` verifies the original synthetic fixture bytes, verifies the
generated artifact bundle read-only, constructs the data snapshot manifest,
experiment run, caller-owned manifest identity, and artifact manifest as
immutable ledger records. It imports only stable contracts and executing the
mapper does not load SQLAlchemy, psycopg, `research_sdk.persistence`, or
`research_sdk.experiment_recording`.

Persistence remains delegated to the completed-experiment service. The
application caller constructs `CompletedExperimentRecordBundle` from the pure
mapped records and calls `record_completed_experiment` with a caller-owned
transaction factory. The repository write order stays data snapshot,
experiment run, artifact manifest. Exact replay, existing-snapshot plus new
run/artifact, contract conflicts, aggregate conflicts, and transaction rollback
behavior all use the existing repository taxonomy. The integration adds no
repository-owned retry, timeout, savepoint, repair, cleanup, relocation,
update, failed-run persistence, worker/API entrypoint, or generic workflow
framework.

Live PostgreSQL coverage adds a focused completed-backtest recording module to
the existing explicit persistence smoke file list. The tests generate artifacts
under temporary directories, map and verify records, construct the completed
bundle, and then record through `record_completed_experiment` before inspecting
durable state through separate connections where needed. They also document
that artifact directories can remain after database failures because cleanup is
caller-owned policy, not repository behavior.

## Deferred Scope

The following remain deferred after the completed-experiment recording boundary:

- sessions or unit-of-work abstractions except as future design;
- runtime DB driver dependencies and async drivers such as `asyncpg`;
- additional live Postgres repository/write-path tests outside approved slices;
- SQLite persistence tests, because JSONB/Postgres behavior differs;
- standalone review-event idempotency, replay, hash comparison, and `ON CONFLICT`
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
