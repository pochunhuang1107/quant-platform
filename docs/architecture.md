# Architecture

## Current Phase

Phase 1A - Reproducibility Foundation Complete.

Phase 1B - Research Workflow Layer is next. Current roadmap details live in
`docs/roadmap-v0.2.md`.

The platform remains research-only. It is not ready for production-data
research, paper trading, or live trading.

## Existing Structure

The repository now contains implemented reproducibility infrastructure and
several scaffold-only areas.

Implemented:

- `packages/research-sdk`: immutable contracts, schema exports, persistence
  helpers, PostgreSQL repository writes, and completed-experiment recording.
- `packages/backtest-engine`: deterministic synthetic ETF infrastructure
  baseline, artifact generation, and pure backtest-to-ledger mapping.
- `infra/db`: Alembic migrations and local PostgreSQL support.
- Deterministic synthetic ETF artifacts for the required run artifact set.
- Completed-experiment ledger recording through a caller-owned transaction.
- Hosted CI and PostgreSQL smoke coverage.

Scaffold-only or deferred:

- `apps/api`
- `apps/web`
- `apps/worker`
- `apps/mcp-server`
- `packages/data-engine`
- `packages/feature-store`
- `packages/portfolio-engine`
- `packages/execution-engine`
- `packages/agent-tools`
- strategy families
- production research workflows

## Planned Responsibilities

- `apps/api`: scaffold-only future service API for research metadata and
  platform workflows.
- `apps/web`: scaffold-only future web UI for experiment review, reports, and
  approvals.
- `apps/worker`: scaffold-only future asynchronous jobs for data validation,
  backtests, and reports.
- `apps/mcp-server`: scaffold-only future agent-facing tool surface for
  controlled platform access.
- `packages/research-sdk`: implemented shared contracts, schema export,
  persistence, and completed-experiment recording boundaries. It does not yet
  provide read/query services, report-card persistence, batch orchestration, or
  approval-workflow authority.
- `packages/data-engine`: scaffold-only future data ingestion, validation, and
  snapshot logic.
- `packages/feature-store`: scaffold-only future feature definitions and
  point-in-time materialization.
- `packages/backtest-engine`: partially implemented deterministic
  research-engine execution for the current synthetic ETF infrastructure slice.
  It includes an importable offline QQQ baseline with SPY as a gross benchmark,
  explicit costs and slippage, Decimal accounting, deterministic identity,
  local artifact generation, and pure ledger-record mapping. It does not own
  SQLAlchemy, Postgres, experiment-ledger transactions, API workflows, paper
  trading, live trading, broker integrations, or performance claims.
- `packages/portfolio-engine`: scaffold-only future portfolio construction and
  risk calculations.
- `packages/execution-engine`: reserved and inactive until later phases; no
  paper trading execution, live trading implementation, broker integration, or
  account-specific configuration is allowed in the current roadmap.
- `packages/agent-tools`: scaffold-only future safe automation helpers for
  agents.
- `strategies/*`: scaffold-only future strategy families by asset class or
  horizon.
- `research/hypotheses`: written research hypotheses before implementation.
- `research/notebooks`: exploratory notebooks; not authoritative experiment records.
- `research/reports`: reviewed research outputs and summaries.
- `infra/db`: implemented PostgreSQL ledger migrations, local disposable
  PostgreSQL Compose support, and migration configuration.
- `infra/docker`: future local development containers beyond the current
  database-specific support.
- `infra/terraform`: reserved for later infrastructure definitions.
- `docs`: source of truth for architecture, contracts, risk rules, and operating model.

## Research Lifecycle

Accepted research must follow this lifecycle:

1. Hypothesis: define the research question, asset universe, expected behavior, failure modes, and validation plan.
2. Config: write a reproducible run configuration with benchmark, costs, slippage, lookback, lag, and leakage assumptions.
3. Data snapshot: reference point-in-time input data with a snapshot manifest.
4. Feature snapshot: reference derived features and their availability assumptions when applicable.
5. Backtest: execute deterministic research code with captured Python version, lockfile hash, seed, and run command.
6. Artifacts: write the required artifact bundle and artifact manifest.
7. Ledger: register the run, artifacts, assumptions, review status, and integrity hashes.
8. Report: write deterministic report-card evidence and supporting failure
   analysis. The current `research_note.md` file is a generated run artifact;
   a persisted `ResearchNote` contract is a separate human-reviewed
   interpretation record.
9. Review decision: record human review metadata and accepted, rejected, invalid, or superseded status.

Notebooks are exploratory. Notebook-derived charts or tables cannot be cited as
accepted results unless reproduced by versioned code with a ledger `run_id` and
artifact manifest.

## Historical Phase 0 Foundation

The original Phase 0 objectives established the repository foundation,
scaffold, documentation, ledger contract direction, data contract direction,
agent rules, and trading-risk policy. Historical acceptance details remain
preserved in `docs/roadmap.md`.

Those objectives have been superseded by the Phase 1A/Phase 1B roadmap
structure in `docs/roadmap-v0.2.md`.

## Boundary Decisions

- The platform is research-first. Paper trading and live trading are later phases.
- Notebooks may support exploration, but accepted results must be reproducible from versioned code, config, data snapshots, and run artifacts.
- Backtests must include benchmark comparison, transaction cost assumptions, slippage assumptions, and leakage notes.
- The first deterministic ETF backtest is infrastructure validation only. It
  uses version-controlled synthetic fixture data, not historical market data or
  a production data source, and it must not be used for investment conclusions.
- Backtest engine core models and execution code remain independent of
  persistence repositories and transaction handling. The deterministic ETF
  ledger integration is a separate mapping boundary that verifies fixture and
  artifact bytes read-only, constructs immutable ledger records from stable
  contracts only, and leaves completed-bundle construction and recording to the
  application boundary.
- The platform must support multiple asset classes without embedding a
  preferred broker, exchange, or data vendor in the current roadmap.
- Agents can implement and test but cannot approve financial conclusions, risk exceptions, paper trading, or live trading.
- Formal approval can only be granted by Po-Chun Huang for now.

## Deterministic ETF Baseline

The initial backtest-engine slice runs one unconditional long-only QQQ
buy-and-hold baseline with SPY as a gross benchmark. It validates aligned daily
bars from a small synthetic JSON fixture, buys QQQ once at the first aligned
session open, values the strategy at each aligned close, and does not liquidate
at the end of the period. The order decision does not use same-day close,
future values, indicators, or prior performance.

The baseline uses `Decimal` accounting with explicit `ROUND_HALF_EVEN`
quantization. Monetary values are quantized to `0.000001`; return and ratio
values are quantized to `0.000000000001`. The default assumptions are
`100000` initial capital, 1 basis point commission on executed QQQ notional, 2
basis points buy slippage, integer QQQ shares, retained cash, open execution,
close valuation, and a gross fractional-unit SPY benchmark with no commission
or slippage.

Execution identity is content-addressed from execution inputs and lineage:
resolved configuration, fixture content hash, data and benchmark snapshot
identities, strategy identity and version, engine version, injected Git and
environment metadata, dependency-lock hash, execution command, and the explicit
no-randomness marker. Output metrics, returns, trades, artifact hashes,
artifact root paths, generated timestamps, runtime duration, and wall-clock
timestamps are excluded. Public run IDs use `run-` followed by the full
64-character lowercase SHA-256 digest.

The artifact writer emits the required local payload files under a
caller-supplied artifact root and writes `artifact_manifest.json` last. JSON and
Markdown payload bytes are canonical and deterministic. Parquet payloads use
explicit PyArrow schemas, stable row ordering, no pandas metadata, no
dictionary encoding, no statistics, and uncompressed output. Payload bytes do
not depend on the physical artifact root. The manifest contains actual
`file://` URIs, so manifest bytes and `artifact_manifest_hash` are expected to
depend on the artifact root; writing the same result to the same root remains
byte-for-byte deterministic.

The backtest-to-ledger integration maps one completed deterministic result and
its generated artifact bundle to immutable records containing
`DataSnapshotManifest`, `ExperimentRunRecord`, caller-owned `manifest_id`, and
`RunArtifactManifest`. Backtest execution and artifact writing happen before
any database transaction. The mapper performs only read-only verification: it
reloads the synthetic fixture, checks snapshot identity equality, verifies
payload hashes, sizes, URIs, and the canonical `artifact_manifest.json`, and
rejects dirty execution metadata. It imports only stable contracts from
`research_sdk`, does not load persistence or completed-experiment service
dependencies, and does not write, repair, relocate, or delete artifacts.

Persistence remains owned by `research_sdk.experiment_recording`: the
application caller wraps the pure mapped records in a
`CompletedExperimentRecordBundle` and passes that bundle to
`record_completed_experiment` with a transaction factory such as
`engine.begin`. The data snapshot, experiment run, and artifact manifest
aggregate are recorded atomically in that caller-owned transaction. Exact
replay succeeds only when the same canonical artifact root and contracts are
supplied; a different artifact root for the same `run_id` changes the run
contract and is expected to conflict rather than silently relocate artifacts.

## Deterministic Research Report Cards

`research_sdk.contracts.ResearchReportCard` is the common deterministic
evidence contract for Phase 1B report cards. It is owned by `research_sdk`
because future research engines and asset classes must be able to emit the same
kind of factual evidence summary.

The current builder lives in `packages/backtest-engine` as
`build_deterministic_etf_report_card`. It supports only completed deterministic
QQQ buy-and-hold runs with SPY as the gross benchmark. The builder consumes
already constructed ledger contracts and a caller-owned artifact `manifest_id`;
it performs no filesystem, network, database, repository, transaction, or
current-time work.

The `deterministic-etf-report-card-v1` policy uses one shared synthetic QQQ/SPY
market-data snapshot for both researched data and benchmark data. The builder
does not claim support for independent benchmark snapshots until a future
derivation-policy version adds that behavior.

Report-card identity is derived from the source `run_id`, contract schema
version, derivation-policy version, data and benchmark snapshot content hashes,
run config hash, parameter hash, and artifact manifest hash. The identity is
evidence-derived and does not replace the engine-owned run identity. Human
review metadata, `ResearchNote` content, generated prose, runtime duration,
current process environment, and local working-directory paths are excluded.
Artifact-root-dependent data may affect identity only through the already
recorded `artifact_manifest_hash`.

Before constructing evidence, the builder canonicalizes the supplied
`RunArtifactManifest` contract, hashes those bytes as `sha256:<hex>`, and
requires that value to equal the run's `artifact_manifest_hash`. It also
requires `manifest_id` to be `manifest-` plus the 64-character run digest, the
run and manifest root/manifest URIs to agree, the CONFIG artifact evidence hash
to equal the run's `config_hash`, and each required artifact URI to be
`artifact_root_uri/filename`. The public report-card contract independently
requires every artifact kind in the required artifact set exactly once.

Metric strings use canonical fixed scales: twelve fractional digits for return
and drawdown ratios, and six fractional digits for commissions, slippage, and
ending equity. Negative zero is rejected as a noncanonical metric encoding.
Evidence entries are ordered by artifact kind, filename, and artifact ID. Use
restrictions are treated as set-like metadata and normalized by enum value.

`ReportCardLineage` stores both data and benchmark snapshot content hashes.
They are equal under the v1 shared-snapshot policy, but both are retained so
the report-card ID can be recomputed from durable report-card fields through
the pure identity verifier without reloading source snapshots.

Report cards are not persisted in the database in this slice, and the completed
run artifact bundle is not mutated to add report-card files. A deterministic
report card is factual evidence. A persisted `ResearchNote` is a separate
human-reviewed interpretation. The generated `research_note.md` artifact,
`ResearchReportCard`, and persisted `ResearchNote` are not interchangeable.
Durable report-card persistence and a finalized `ResearchNote` workflow remain
Phase 1B follow-up work.

## Roadmap Alignment

Phase 0 history is preserved in `docs/roadmap.md`. Phase 1A completion and
Phase 1B acceptance criteria are defined in `docs/roadmap-v0.2.md`.

This architecture document describes current boundaries and responsibilities.
It is not the canonical phase-gate document.
