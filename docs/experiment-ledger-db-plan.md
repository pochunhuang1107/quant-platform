# Experiment Ledger DB Plan

## Purpose And Scope

This is the Phase 1 DB implementation plan for the experiment ledger. It is
planning and documentation only.

The plan maps the existing Pydantic and JSON-schema contracts to future
Postgres tables for the experiment ledger metadata layer. It defines table
boundaries, planned relational projections, JSONB usage, idempotency rules,
audit expectations, indexing, future migration sequencing, and later DB test
coverage.

This PR does not create migrations, dependencies, SQLAlchemy models, Alembic
setup, DB connections, APIs, write paths, or persistence code.

## Non-Goals

This plan does not implement:

- Actual migrations.
- SQLAlchemy models.
- Alembic setup.
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
| `RunArtifactManifest` | `run_artifact_manifests` | `manifest_id` | `run_id`, `experiment_id`, `schema_version`, `artifact_root_uri`, `created_at`, `required_artifacts_complete`, `artifact_manifest_hash` or `contract_hash` | Yes | Use a generated/surrogate `manifest_id` plus a unique `run_id` and `artifact_manifest_hash` or `run_id` and `contract_hash`. `run_id` alone is not enough because corrections, re-runs, or manifest regeneration may produce multiple manifest records for the same run lineage. |
| `RunArtifactEntry` | `run_artifact_entries` | `artifact_entry_id` or composite `manifest_id`, `artifact_id` | `manifest_id`, `run_id`, `artifact_id`, `artifact_kind`, `uri`, `filename`, `format`, `status`, `content_hash`, `row_count`, `validator_version` | No | Relational child table planned immediately because artifact kind, status, URI, and hash queries will be common. |
| `ResearchNote` | `research_notes` | `note_id` | `schema_version`, `note_type`, `status`, `created_at`, `updated_at`, `title`, `hypothesis_status`, `evidence_strength`, `decision_outcome`, `parent_note_id`, `supersedes_note_id`, review summary fields, `contract_hash` | Yes | Structured research note metadata and raw validated note contract. Markdown rendering and search are out of scope. |
| `ReviewMetadata` | Latest review fields on parent records plus `review_events` | `review_event_id` for events | `subject_type`, `subject_id`, `schema_version`, `review_status`, `reviewer_id`, `review_role`, `reviewed_at`, `decision`, `approval_scope`, `linked_pr`, `risk_approval_required` | `raw_review` JSONB on events | Parent tables carry latest review summary fields for fast filtering. `review_events` stores append-only history. |
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
- `artifact_manifest_hash` or `contract_hash`.
- `raw_contract JSONB`.
- `inserted_at`.

### run_artifact_entries

Likely columns:

- `artifact_entry_id` primary key or composite `manifest_id` and `artifact_id`.
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

### research_notes

Likely columns:

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

Likely columns:

- `review_event_id` primary key.
- `subject_type`.
- `subject_id`.
- `schema_version`.
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

## Idempotency And Insert/Update Rules

Insert paths should require prior Pydantic contract validation. After
validation, the write path should canonicalize the contract payload and compute
`contract_hash`.

The same primary key plus the same `contract_hash` should be idempotent. The
same primary key plus a different `contract_hash` should be rejected unless the
caller uses an explicit correction or supersession path.

Mutable operational fields should be minimal. Status and review updates should
produce `review_events` or another audit record when they change review or
lifecycle metadata. Write paths must avoid silent overwrites.

## Immutability, Corrections, Supersession, And Audit Rules

Completed runs are append-only. Corrections create new run IDs linked through
`parent_run_id`. Supersession uses `supersedes_run_id`, and prior record status
changes must be auditable.

Review events are append-only. Research notes can use `parent_note_id` and
`supersedes_note_id` to model corrections or replacement notes.

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
- `run_artifact_manifests(run_id)`.
- `run_artifact_entries(run_id, artifact_kind)`.
- `run_artifact_entries(status)`.
- `research_notes(status, updated_at)`.
- `review_events(subject_type, subject_id, inserted_at)`.

Avoid broad JSONB GIN indexes in the first migration unless a concrete query
requires them.

## Planned Migration Sequence

This sequence is planned only:

1. Add Alembic setup and the SQLAlchemy dependency in a dedicated migration PR.
2. Create initial metadata tables:
   - `experiment_runs`.
   - `data_snapshot_manifests`.
   - `run_artifact_manifests`.
   - `run_artifact_entries`.
   - `research_notes`.
   - `review_events`.
3. Add basic constraints and text check constraints for enum-like fields.
4. Add stable non-blocking foreign keys where appropriate.
5. Add indexes.
6. Add migration tests.
7. Add contract fixture persistence tests.
8. Add repository/write-path code only in a later PR after migrations are reviewed.
9. Require Pydantic contract validation before persistence.

## Future SQLAlchemy/Alembic Integration Steps

Add dependencies in a separate PR. Add the Alembic environment and migration
directory in the same dedicated persistence setup work or in a narrowly scoped
follow-up.

Add DB model definitions only if intentionally scoped. Keep the DB layer
separate from backtest execution. Add a local Postgres/devcontainer story later
if needed, without introducing vendor, broker, credential, or cloud-specific
assumptions.

No APIs or run writers should be added until persistence primitives pass tests.

## Future DB Test Strategy

When DB work begins, plan tests for:

- Migration upgrade/downgrade smoke tests.
- Schema creation tests.
- Insert fixture for each top-level contract.
- Idempotent re-insert with the same hash.
- Rejecting the same ID with a different `contract_hash` unless using a
  correction path.
- Querying by common indexes.
- `review_events` append-only behavior.
- `run_artifact_entries` projection from manifest.
- No artifact file existence checks.
- No hash verification side effects.
- No broker, live trading, or paper trading behavior.

## Validation Commands

For this docs-only PR, run:

```bash
git diff --check
uv run ruff format --check .
uv run ruff check .
uv run mypy packages/research-sdk/src
uv run python -m research_sdk.contracts.json_schema --output-dir packages/research-sdk/schema --check
uv run pytest tests/test_contract_roundtrip_validation.py tests/test_contract_json_schema_export.py
uv run pytest
```

If `uv` is unavailable on `PATH`, use `python -m uv` as the equivalent command
prefix.
