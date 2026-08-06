# Roadmap Index

This is the roadmap index for the quant platform. Versioned roadmap documents
are the source of truth for phase gates and sequencing.

## Current Roadmap Version

Current proposed roadmap version:

- [Quant Research Platform Roadmap v0.2](roadmap-v0.2.md)

Roadmap v0.2 becomes the current repository roadmap only after human approval
and merge. Roadmap v0.1 remains preserved below as the historical baseline.

## Current Milestone

Phase 1A - Reproducibility Foundation Complete.

Implemented through merge commit:

`52b2e030af584460ef49ce75b2e6f570d16eb3ec`

## Next Milestone

Phase 1B - Research Workflow Layer.

The next milestone turns reproducible experiment infrastructure into
deterministic evidence, human-reviewed findings, valid comparisons, and
controlled experiment sets. The repository is not ready for production data
research, paper trading, or live trading.

## Source-Of-Truth And Versioning Policy

- Roadmap v0.1 is the historical baseline and is retained below.
- Roadmap v0.2 is the proposed current roadmap for this branch.
- Future roadmap revisions must be versioned and include a change log.
- README and this index should point to the current approved version.
- Versioned roadmap phase criteria override scattered planning notes elsewhere
  in the repository.

## Historical Roadmap v0.1

The following content is preserved from the original roadmap v0.1 for history.

Historical source-of-truth statement: roadmap v0.1 was the canonical phase gate
document for the quant platform when Phase 0 was current.

Historical current phase statement:

Phase 0: agent-ready foundation.

## Required Scaffold Paths

Phase 0 requires these directories to exist in the repository. Empty directories
must include a placeholder `.gitkeep` or a local `README.md` so the scaffold is
tracked.

- `apps/api`
- `apps/web`
- `apps/worker`
- `apps/mcp-server`
- `packages/research-sdk`
- `packages/data-engine`
- `packages/feature-store`
- `packages/backtest-engine`
- `packages/portfolio-engine`
- `packages/execution-engine`
- `packages/agent-tools`
- `strategies/equities`
- `strategies/etfs`
- `strategies/futures`
- `strategies/fx`
- `strategies/crypto`
- `strategies/indices`
- `strategies/options`
- `strategies/intraday`
- `research/hypotheses`
- `research/notebooks`
- `research/reports`
- `infra/db`
- `infra/docker`
- `infra/terraform`
- `docs`

## Required Docs

Phase 0 requires these docs:

- `README.md`
- `AGENTS.md`
- `CLAUDE.md`
- `docs/architecture.md`
- `docs/agent-rules.md`
- `docs/experiment-ledger.md`
- `docs/data-contracts.md`
- `docs/trading-risk-policy.md`
- `docs/roadmap.md`

## Phase 0 Exit Criteria

Phase 0 is complete only when all items below are true:

- Required scaffold paths exist and empty paths have `.gitkeep` or `README.md` placeholders.
- Required docs exist and are linked from `README.md`.
- `CLAUDE.md` points to `AGENTS.md` instead of duplicating rules.
- Architecture docs distinguish existing structure from planned responsibilities.
- Research lifecycle is documented from hypothesis through review decision.
- Experiment ledger minimum fields, artifact contract, status lifecycle, review metadata, and correction rules are documented.
- Data contracts include snapshot manifests, point-in-time fields, and corporate action, rollover, delisting, and survivorship rules.
- Trading risk policy states that Phase 0 and Phase 1 cannot add broker integration, live trading implementation, paper trading execution, account-specific config, or unattended execution paths.
- Secrets policy covers `.env` files, notebooks, logs, artifacts, CI variables, OAuth tokens, cloud tokens, vendor tokens, and broker credentials.
- Formal approval policy states only Po-Chun Huang can approve exceptions for now.
- Large parameter sweep threshold is documented.
- No application code is required for Phase 0 completion.
- No live trading, broker integration, credentials, vendor-specific assumptions, or cloud-specific assumptions are introduced.

## Phase 1 Entry Decisions

Before Phase 1 implementation begins, document these choices:

- Python version.
- Package manager and lockfile format.
- Test command and CI entrypoint.
- Location for JSON/Pydantic contract definitions.
- Location for artifact validators.
- Initial strategy PR checklist location.
- Whether scaffold placeholders are `.gitkeep` files or local `README.md` files.

## Phase 1 Exit Criteria

Phase 1 is complete only when all items below are true:

- Local development environment can install dependencies from a lockfile.
- Minimum environment capture is recorded for backtests: Python version and lockfile hash.
- CI runs repeatable tests for docs checks, contract validation, and artifact validation.
- JSON/Pydantic contracts exist before database migrations.
- Postgres/Alembic ledger migrations are added after JSON/Pydantic contracts stabilize.
- Experiment ledger validator checks required fields, status values, correction links, and review metadata.
- Artifact validator checks required files, manifest hashes, file sizes, row counts, and schema versions.
- Data contract validator checks required fields, timestamp semantics, keys, units, currencies, and point-in-time fields.
- A minimal deterministic baseline backtest writes a full artifact bundle and ledger record.
- Any strategy result includes benchmark, costs, slippage, data snapshot, leakage review, failure modes, and validation plan.
- No broker integration, live trading implementation, paper trading execution, account-specific config, credentials, or vendor-specific dependency is added.

## Later Phases

- Paper trading requires explicit approval by Po-Chun Huang and Risk Reviewer approval.
- Live trading remains out of scope until a later roadmap update explicitly adds it with risk, security, and operational controls.
