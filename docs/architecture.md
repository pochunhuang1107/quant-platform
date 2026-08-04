# Architecture

## Current Phase

Phase 0 establishes the repository, documentation, and contracts required before
research code is added. The platform is intended to become an enterprise-grade,
multi-asset quant research system with reproducible experiments, audited
artifacts, and human approval gates before any paper or live trading.

## Existing Structure

The repository currently contains the Phase 0 scaffold for applications,
packages, strategies, research, infrastructure, and documentation. Phase 0 exit
requires each empty scaffold path to be tracked with `.gitkeep` or a local
`README.md`, as defined in `docs/roadmap.md`.

## Planned Responsibilities

- `apps/api`: future service API for research metadata and platform workflows.
- `apps/web`: future web UI for experiment review, reports, and approvals.
- `apps/worker`: future asynchronous jobs for data validation, backtests, and reports.
- `apps/mcp-server`: future agent-facing tool surface for controlled platform access.
- `packages/research-sdk`: future shared research APIs and typed contracts.
- `packages/data-engine`: future data ingestion, validation, and snapshot logic.
- `packages/feature-store`: future feature definitions and point-in-time materialization.
- `packages/backtest-engine`: deterministic research-engine execution. The
  first Phase 1 slice is an importable, offline daily ETF baseline engine using
  synthetic fixture-only QQQ and SPY bars, explicit costs and slippage, Decimal
  accounting, deterministic identity, and local artifact generation. It does
  not own SQLAlchemy, Postgres, experiment-ledger transactions, API workflows,
  paper trading, live trading, broker integrations, or performance claims.
- `packages/portfolio-engine`: future portfolio construction and risk calculations.
- `packages/execution-engine`: reserved and inactive until later phases; no paper trading execution, live trading implementation, broker integration, or account-specific configuration is allowed in Phase 0 or Phase 1.
- `packages/agent-tools`: future safe automation helpers for agents.
- `strategies/*`: future strategy families by asset class or horizon.
- `research/hypotheses`: written research hypotheses before implementation.
- `research/notebooks`: exploratory notebooks; not authoritative experiment records.
- `research/reports`: reviewed research outputs and summaries.
- `infra/db`: future database schema and migrations.
- `infra/docker`: future local development containers.
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
8. Report: write `research_note.md` and supporting failure analysis.
9. Review decision: record human review metadata and accepted, rejected, invalid, or superseded status.

Notebooks are exploratory. Notebook-derived charts or tables cannot be cited as
accepted results unless reproduced by versioned code with a ledger `run_id` and
artifact manifest.

## Minimal Phase 0 Implementation Plan

1. Keep the scaffold above and document ownership boundaries for each directory.
2. Define the experiment ledger schema before any backtest writes results.
3. Define the required run artifact contract and validation expectations.
4. Define data contracts for market data, signals, trades, and portfolio outputs.
5. Define agent rules and trading risk policy, including explicit prohibition of live trading implementation.
6. Add development environment and CI only after the docs are stable enough to test.
7. Add lightweight tests for schemas and artifact validation in Phase 1.
8. Use JSON/Pydantic contracts first in Phase 1; add Postgres/Alembic migrations after those contracts stabilize.

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
- The platform must support multiple asset classes without embedding a preferred broker, exchange, or data vendor in Phase 0.
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

## Phase 0 Acceptance Criteria

- Canonical acceptance criteria are defined in `docs/roadmap.md`.
- Repository scaffold exists for apps, packages, strategies, research, infra, and docs, with placeholders for empty tracked paths.
- Required docs exist and describe architecture, agent rules, experiment ledger, data contracts, and trading risk policy.
- No application code, broker integration, credentials, or data vendor dependency is introduced.
- Phase 1 work can begin from documented contracts without guessing core artifact names or approval rules.

## Phase 1 Acceptance Criteria

- Local development environment and CI run repeatable tests.
- JSON/Pydantic contracts are implemented before Postgres/Alembic migrations.
- Backtest artifact validator checks the required files and minimum fields.
- A simple baseline backtest can write the complete artifact bundle and ledger entry.
- Tests cover ledger validation, artifact validation, and basic data contract checks.
- Documentation records lookback, lag, input data, leakage assumptions, costs, slippage, benchmark, failure modes, and validation plan for any strategy result.
- No live trading or broker integration is added.
