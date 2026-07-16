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

## Future Repository Responsibilities

Future repositories should:

- accept validated Pydantic contract objects;
- compute `contract_hash` internally;
- project stable query columns from validated contract objects;
- store raw validated contract JSON for audit and replay;
- keep artifact and data hashes as declared metadata only;
- avoid file IO, object storage IO, vendor calls, and hash verification;
- avoid becoming an approval gate for research or trading decisions.

Future duplicate handling should follow this policy:

- the same primary key plus the same `contract_hash` can be idempotent;
- the same primary key plus a different `contract_hash` should reject unless an
  explicit correction or supersession path is used.

Completed-run append-only rules and lifecycle transition rules remain future
service-layer validation. They should not be hidden inside low-level row
mapping helpers or generic repository upserts.

Review approvals are metadata only. Repository code must not treat
`ReviewMetadata` as trading authorization, risk approval execution, paper
trading approval, or live trading approval.

## Deferred Scope

The following remain deferred after PR 17:

- SQLAlchemy repository implementations;
- SQLAlchemy insert builders;
- database write paths;
- session or unit-of-work abstractions;
- DB driver dependencies such as `psycopg` or `asyncpg`;
- live Postgres tests;
- SQLite persistence tests, because JSONB/Postgres behavior differs;
- FastAPI endpoints;
- backtest integration;
- artifact IO or storage IO;
- data ingestion or vendor API calls;
- file existence checks or artifact content hash verification;
- markdown/report rendering;
- UI, search, indexing, embeddings, semantic memory, knowledge graph, LLM
  summarization, or agent workflow execution;
- broker integration, paper trading, or live trading.
