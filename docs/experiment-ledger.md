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

## Deterministic Backtest Artifact Bundle

The first Phase 1 backtest-engine slice generates a complete local artifact
bundle for one deterministic QQQ buy-and-hold baseline with SPY as a gross
benchmark. The input data is a small version-controlled synthetic fixture only;
it is not historical market data, not a production data source, and not a basis
for performance claims.

Execution semantics are fixed: one unconditional QQQ buy is submitted on the
first aligned fixture date and filled at that session's open plus 2 basis
points of buy slippage. Commission is 1 basis point of executed QQQ notional.
The engine buys the largest integer quantity whose slipped notional plus
commission fits within `100000` initial capital, retains remaining cash, values
the strategy at each aligned close, and does not liquidate at the end. The SPY
benchmark is normalized from the first aligned SPY open, permits fractional
benchmark units, and is gross of costs and slippage. The buy decision does not
use same-day close, future prices, indicators, or prior performance.

The engine uses `Decimal` values and `ROUND_HALF_EVEN` quantization. Monetary
values are serialized at `0.000001` precision and return/ratio values at
`0.000000000001` precision. Decimal values are serialized as canonical strings,
never JSON floats.

Monthly returns use only supplied fixture sessions. The engine selects the
final available strategy equity observation in each calendar month, reports the
first month as `month_end_equity / initial_capital - 1`, and reports every
later month as `current_month_end_equity / previous_month_end_equity - 1`.
Months are serialized as `YYYY-MM`; no trading calendar is inferred and no
annualization is performed.

The run identity is content-addressed from execution inputs and lineage only:
resolved configuration, fixture byte hash, data and benchmark snapshot
identities, strategy identity and version, engine version, injected Git and
environment metadata, dependency-lock hash, execution-command identity, and the
explicit no-randomness marker. Output metrics, returns, generated artifact
hashes, artifact root URI, generated timestamps, runtime duration, and
wall-clock timestamps are excluded. The public `run_id` is `run-` plus the full
64-character lowercase SHA-256 digest, so equivalent inputs produce the same
identity and nondeterministic output changes can later surface as ledger
contract conflicts.

The artifact writer creates real local files for all required artifact kinds:
`config.json`, `metrics.json`, `trade_log.parquet`, `signal_log.parquet`,
`daily_equity.parquet`, `drawdown_series.parquet`,
`monthly_returns.parquet`, `regime_breakdown.json`,
`failure_analysis.md`, and `research_note.md`. `artifact_manifest.json` is
written last and is not included as its own artifact entry. JSON uses sorted
keys, compact separators, UTF-8, no NaN/Infinity, and one trailing newline.
Markdown uses UTF-8, LF line endings, deterministic section order, and one
final newline. Parquet files use explicit PyArrow schemas, stable row ordering,
uncompressed output, disabled dictionary encoding and statistics, and no pandas
metadata.

Payload artifact bytes are independent of the physical artifact root. The
manifest contains actual `file://` URIs, so manifest bytes and
`artifact_manifest_hash` are root-dependent by design. A future exact ledger
replay must therefore reuse the canonical artifact root; changing the root for
the same `run_id` is expected to become a contract conflict rather than a
silent relocation.

The deterministic backtest-to-ledger integration maps the completed engine
result and generated artifact bundle to immutable ledger records for the
application boundary. The mapper reloads the original synthetic fixture bytes,
verifies that fixture, result, data snapshot, and benchmark snapshot identities
match, verifies generated artifact files and `artifact_manifest.json`
read-only, and returns `DataSnapshotManifest`, `ExperimentRunRecord`,
caller-owned `manifest_id`, and `RunArtifactManifest`. It imports only stable
contracts and does not load SQLAlchemy, psycopg, `research_sdk.persistence`, or
`research_sdk.experiment_recording`.

The mapper accepts caller-supplied `ReviewMetadata` and stores it unchanged in
the run contract. The first-slice tests use pending review metadata with
`risk_approval_required=true`; this is not trading authorization or risk
approval execution.

Backtest execution and artifact writing happen before the database
transaction. The application caller wraps the mapper's records in
`CompletedExperimentRecordBundle` and records that bundle through
`record_completed_experiment`, which atomically persists the data snapshot,
experiment run, and artifact manifest aggregate in one caller-owned
transaction. The live integration test proves the complete vertical path while
keeping the mapper dependency boundary pure. Exact replay reuses the same
canonical artifact root and returns all three replay dispositions. Reusing the
same snapshot with changed execution lineage can replay the snapshot while
creating a new run and artifact manifest. Snapshot, run, or artifact contract
conflicts propagate and roll back the transaction; the integration does not
retry, repair, update, relocate, or perform last-write-wins behavior.

Artifact directories may remain if a failure occurs after artifact generation
but before a database commit. The integration does not automatically delete or
repair those directories. Failed-run ledger persistence remains deferred. The
backtest engine core still does not import persistence repositories, open
database transactions, inspect Git, read lockfiles, collect environment
metadata, write failed-run records, or interact with API, worker, broker,
paper-trading, or live-trading code.

## Deterministic Research Report Cards

Phase 1B introduces `ResearchReportCard` as deterministic report-card evidence.
The contract is schema-exported from `research_sdk.contracts` and is distinct
from both the generated `research_note.md` artifact and the persisted
`ResearchNote` interpretation contract.

For the current deterministic ETF baseline, the pure builder is
`backtest_engine.report_cards.build_deterministic_etf_report_card`. It accepts
an `ExperimentRunRecord`, data and benchmark `DataSnapshotManifest` records, a
caller-owned artifact `manifest_id`, and a `RunArtifactManifest`. The builder
requires completed run and snapshot status, complete produced required
artifacts, coherent run/snapshot/benchmark identities, the approved metric set,
and the supported QQQ/SPY daily baseline. It performs no filesystem, object
storage, database, repository, transaction, network, wall-clock, or random
operation.

The `deterministic-etf-report-card-v1` policy is intentionally narrower than a
generic benchmark model: it requires one shared research-generated synthetic
QQQ/SPY market-data snapshot for both the researched QQQ data and the SPY
benchmark reference. The snapshot must be RAW and POINT_IN_TIME under the
fixture-only semantics.

The report-card ID is `report-card-` plus a full lowercase SHA-256 digest over
canonical JSON containing the source `run_id`, report-card schema version,
derivation-policy version, data and benchmark snapshot content hashes, config
hash, parameter hash, and artifact manifest hash. The ID excludes review
metadata, note content, generated prose, runtime duration, current environment,
and local paths. Artifact-root-dependent information can affect the ID only
through the recorded artifact manifest hash.

The builder binds the supplied manifest contract to the run by canonicalizing
the `RunArtifactManifest`, computing `sha256:<hex>` over those bytes, and
requiring equality with `ExperimentRunRecord.artifact_manifest_hash`. It also
requires `manifest_id` to be `manifest-` plus the source run digest, requires
the run and manifest artifact root/manifest URIs to agree, requires the CONFIG
artifact evidence hash to equal `ExperimentRunRecord.config_hash`, and requires
each required artifact URI to equal `artifact_root_uri/filename`. The
`ResearchReportCard` contract itself requires every required artifact kind
exactly once with the expected filename, format, produced status, full SHA-256
content hash, and nonnegative size.

Metric strings are canonical: twelve fractional digits for total return,
benchmark total return, excess return, and maximum drawdown; six fractional
digits for realized commission, realized slippage, and ending equity. Negative
zero is rejected. Evidence entries are deterministically ordered by artifact
kind, filename, and artifact ID. Use restrictions are normalized as set-like
metadata sorted by enum value.

`ReportCardLineage` stores both data and benchmark snapshot content hashes.
They are equal under `deterministic-etf-report-card-v1` because the policy uses
one shared synthetic QQQ/SPY snapshot, but both fields remain explicit lineage.
The pure identity verifier in `research_sdk.report_card_identity` recomputes
`report_card_id` from durable report-card fields and performs no I/O or
persistence work. The deterministic ETF verifier in `backtest_engine` keeps the
v1 policy allowlist and delegates generic recomputation to the SDK helper.

Report cards are durably persisted in the `research_report_cards` table after
completed-experiment recording. The table stores normalized query fields,
`raw_contract`, and `contract_hash = contract_sha256(report_card)`, a lowercase
64-character SHA-256 hex digest over the entire canonical contract. Exact
replay returns `REPLAYED` only when both the natural `report_card_id` and the
whole-contract hash match. Same ID with different canonical content raises
`ContractHashConflictError`; persisted report-card rows are not overwritten.
Generic identity verification proves the report-card ID is internally derived
from the card's durable identity inputs. Persistence then separately validates
that the card faithfully summarizes the referenced persisted run, data
snapshot, benchmark snapshot, and artifact manifest. Foreign-key existence
alone is not sufficient evidence integrity. The repository verifies the source
contracts and their stored hashes before trusting them, then rejects caller
mismatches such as altered metrics, unrelated snapshots, or substituted
artifact evidence; corrupted stored source anchors raise persistence
corruption.

Because report cards are now durable, `ResearchReportCard` schema changes that
alter canonical `model_dump(mode="json")` output must not be introduced under
the same `schema_version` without an explicit migration or version-aware
deserialization policy.

The completed artifact bundle is not mutated. ResearchNote/report-card linkage
and a finalized human-reviewed `ResearchNote` workflow remain planned
follow-up work.

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
