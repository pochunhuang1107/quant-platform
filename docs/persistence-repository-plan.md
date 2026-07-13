# Persistence Repository Plan

## Purpose

PR 15 adds canonical identity primitives for future persistence write paths. It
does not add repositories, row mapping helpers, database writes, a DB driver,
live Postgres tests, SQLite persistence tests, or application integration.

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
future row-mapping support, but it is still not artifact content hashing and it
does not read or verify files.

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

The following remain deferred after PR 15:

- repository protocols;
- row mapping helpers;
- SQLAlchemy repository implementations;
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
