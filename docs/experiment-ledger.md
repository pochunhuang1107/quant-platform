# Experiment Ledger

The experiment ledger is the authoritative record of research runs. Notebooks,
charts, and ad hoc summaries are supporting materials only.

## Purpose

The ledger must make each accepted backtest reproducible and reviewable by
recording the code version, configuration, data snapshot, assumptions, metrics,
artifacts, and review status.

## Minimum Ledger Record

Each run should have one immutable ledger record with:

- `run_id`: unique identifier.
- `schema_version`: ledger schema version used to validate the record.
- `created_at`: UTC timestamp.
- `created_by`: human or agent identity.
- `status`: created, running, completed, under_review, accepted, rejected, failed, invalid, or superseded.
- `status_updated_at`: UTC timestamp for the latest status change.
- `status_updated_by`: identity responsible for the latest status change.
- `strategy_id`: stable strategy name or path.
- `strategy_version`: code version, commit SHA, or package version.
- `repo_dirty`: whether uncommitted repository changes were present.
- `asset_universe`: symbols or universe identifier used by the run.
- `asset_class`: equities, ETFs, futures, FX, crypto, indices, options, or mixed.
- `time_range`: inclusive start and end dates.
- `frequency`: bar or decision frequency.
- `benchmark`: benchmark identifier and rationale.
- `benchmark_snapshot_id`: point-in-time benchmark data snapshot.
- `config_uri`: pointer to `config.json`.
- `config_hash`: hash of `config.json`.
- `artifact_uri`: directory containing required run artifacts.
- `artifact_manifest_uri`: pointer to `artifact_manifest.json`.
- `artifact_manifest_hash`: hash of `artifact_manifest.json`.
- `data_snapshot_id`: point-in-time data snapshot identifier.
- `feature_snapshot_id`: feature snapshot identifier, when applicable.
- `cost_model`: transaction cost assumptions.
- `slippage_model`: slippage assumptions.
- `lookback`: historical window used by the strategy or features.
- `lag_assumptions`: data availability and execution lag assumptions.
- `leakage_review`: summary of point-in-time and survivorship controls.
- `environment`: Python version and lockfile hash at minimum.
- `dependency_lock_hash`: hash of the dependency lockfile.
- `execution_command`: command or entrypoint used to run the backtest.
- `engine_version`: backtest engine version or package identifier.
- `random_seed`: seed used by stochastic components, or `null` with rationale.
- `parameter_hash`: hash of resolved run parameters.
- `metrics_summary`: key metrics copied from `metrics.json`.
- `parent_run_id`: prior related run, when applicable.
- `supersedes_run_id`: prior run replaced by this run, when applicable.
- `review`: structured review metadata.

## Required Run Artifacts

Each backtest run should eventually produce:

- `config.json`
- `artifact_manifest.json`
- `metrics.json`
- `trade_log.parquet`
- `signal_log.parquet`
- `daily_equity.parquet`
- `drawdown_series.parquet`
- `monthly_returns.parquet`
- `regime_breakdown.json`
- `failure_analysis.md`
- `research_note.md`

## Artifact Manifest

`artifact_manifest.json` records artifact integrity. Each artifact entry should
include:

- `path`
- `artifact_type`
- `schema_version`
- `sha256`
- `file_size_bytes`
- `row_count`, when applicable.
- `created_at`
- `validator_version`

The manifest itself is referenced by `artifact_manifest_uri` and protected by
`artifact_manifest_hash` in the ledger record.

## Status Lifecycle

Allowed statuses:

- `created`: record was initialized.
- `running`: execution is in progress.
- `completed`: execution finished and artifacts were produced.
- `under_review`: run is awaiting review.
- `accepted`: run is accepted as a reproducible research result.
- `rejected`: run was reviewed and not accepted.
- `failed`: execution failed before producing a complete accepted result.
- `invalid`: record or artifacts failed validation.
- `superseded`: run was replaced by a later run.

Normal transition:

`created -> running -> completed -> under_review -> accepted/rejected`

Terminal statuses are `accepted`, `rejected`, `failed`, `invalid`, and
`superseded`. Only Po-Chun Huang can approve `accepted` status for now. Agents
may propose status updates but cannot approve financial conclusions.

## Structured Review Metadata

The `review` object should include:

- `review_status`: pending, approved, rejected, or changes_requested.
- `reviewer_id`: reviewer identity.
- `review_role`: human_owner, risk_reviewer, or agent_reviewer.
- `reviewed_at`: UTC timestamp, when reviewed.
- `decision`: concise decision.
- `approval_scope`: exact scope approved, if any.
- `approval_expires_at`: expiration timestamp, if relevant.
- `linked_pr`: PR or issue reference, when applicable.
- `review_notes_uri`: pointer to durable review notes.
- `risk_approval_required`: whether Risk Reviewer approval is required before paper trading.

## Immutability Rules

- A completed run record is append-only.
- Corrections create a new ledger record with `parent_run_id` referencing the prior `run_id`.
- Superseding runs set `supersedes_run_id` and the prior run may move to `superseded`.
- Failed runs may be recorded when they provide useful failure analysis.
- Failed runs should still record config, code version, data snapshot if available, failure reason, logs URI if available, and whether artifacts are incomplete by design.
- Artifact files should not be overwritten after ledger registration.
- Historical records must remain readable after schema upgrades.

## Completed Experiment Recording Boundary

The Phase 1 completed-experiment recording boundary accepts already validated
ledger contracts for one terminal research execution:

- `DataSnapshotManifest`.
- `ExperimentRunRecord`.
- caller-supplied artifact `manifest_id`.
- `RunArtifactManifest`.

The boundary validates cross-contract consistency before opening a database
transaction. The experiment run must be exactly `completed`, must not carry
failure metadata, and must not mark artifacts incomplete. The run must reference
the supplied data snapshot, the artifact manifest must reference the same
`run_id` and `experiment_id`, `artifact_uri` must equal the manifest
`artifact_root_uri`, and `artifact_manifest_uri` must point to
`artifact_manifest.json` under that root. The run's
`artifact_manifest_hash` must be present as caller-supplied metadata.

The boundary requires the supplied artifact manifest to declare a complete
produced artifact set. It relies on the existing `RunArtifactManifest` contract
for required artifact kinds, required filenames and formats, unique artifact
identities, and completeness consistency. It does not generate run IDs, inspect
git state, collect environment metadata, write artifact files, check filesystem
or object-storage existence, inspect Parquet schemas, verify artifact bytes, or
hash a serialized manifest file.

Recording uses one injected transaction context and writes, in order, the data
snapshot manifest, experiment run, and artifact manifest aggregate. Successful
recording permits only all-created, existing-snapshot plus new run/artifact, or
all-replayed outcomes. Other disposition combinations are rejected as incomplete
pre-existing completed-experiment state and are not repaired automatically.

## Schema Evolution

- Ledger schemas use explicit `schema_version` values.
- Validators use explicit versions and record `validator_version` in artifact manifests.
- Schema changes require migration notes.
- Phase 1 starts with JSON/Pydantic contracts.
- Postgres/Alembic migrations are added only after JSON/Pydantic contracts stabilize.

See [Contract Map](contract-map.md) for the current Python model, JSON schema,
fixture, and validation matrix.

See [Experiment Ledger DB Plan](experiment-ledger-db-plan.md) for the planned
Postgres table mapping and migration sequence.

## Phase 0 Acceptance Criteria

- Ledger purpose, minimum fields, artifact list, artifact manifest, status lifecycle, review metadata, correction rules, and immutability rules are documented.
- The schema avoids vendor, broker, and production credential assumptions.

## Phase 1 Acceptance Criteria

- JSON/Pydantic ledger contracts exist before database migrations.
- Tests validate required ledger fields, allowed status values, correction links, artifact manifest metadata, and review metadata.
- A baseline backtest writes a ledger record and complete artifact bundle.
