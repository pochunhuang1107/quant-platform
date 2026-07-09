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
- `packages/backtest-engine`: future deterministic backtest execution.
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
- The platform must support multiple asset classes without embedding a preferred broker, exchange, or data vendor in Phase 0.
- Agents can implement and test but cannot approve financial conclusions, risk exceptions, paper trading, or live trading.
- Formal approval can only be granted by Po-Chun Huang for now.

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
