# Quant Platform

Enterprise-grade multi-asset quant research platform.

## Mission

Build a reproducible, agent-assisted quant research operating system with:

- Experiment tracking
- Data snapshots
- Strategy versioning
- Run artifacts
- Research notes
- Semantic memory
- Knowledge graph later
- Approval-gated paper/live trading later

## Current Phase

Phase 1A: Reproducibility Foundation Complete.

The repository now supports deterministic synthetic ETF experiment recording:
a fixture-only QQQ buy-and-hold baseline with SPY as a gross benchmark can
produce deterministic local artifacts, map them to immutable research-ledger
records, and record the completed experiment through the PostgreSQL-backed
ledger boundary.

Phase 1B is next: the research workflow layer for deterministic report cards,
persisted human-reviewed research notes, compatible-run comparison, curated ETF
data policy, versioned strategies, and controlled experiment sets.

The repository is not ready for production data research, paper trading, or
live trading.

## Documentation Map

- [Architecture](docs/architecture.md): structure, responsibilities, and research lifecycle.
- [Roadmap](docs/roadmap.md): roadmap index and versioning policy.
- [Roadmap v0.2](docs/roadmap-v0.2.md): current Phase 1A status and Phase 1B sequence.
- [Agent Rules](docs/agent-rules.md): agent scope, approval records, secrets policy, and PR expectations.
- [Experiment Ledger](docs/experiment-ledger.md): ledger fields, artifacts, status lifecycle, and review metadata.
- [Experiment Ledger DB Plan](docs/experiment-ledger-db-plan.md): planned Postgres/Alembic persistence design for the experiment ledger metadata layer.
- [Persistence Setup](docs/persistence-setup.md): minimal SQLAlchemy/Alembic setup and local migration command guidance.
- [Persistence Repository Plan](docs/persistence-repository-plan.md): canonical contract hashing policy and future repository/write-path boundary.
- [Data Contracts](docs/data-contracts.md): snapshot manifests, point-in-time fields, and research output contracts.
- [Contract Map](docs/contract-map.md): current Phase 1 contract models, schemas, fixtures, relationships, validation level, and deferred behavior.
- [Trading Risk Policy](docs/trading-risk-policy.md): approval gates, prohibited work, and risk checks.

## Next Milestone

Begin Phase 1B by adding deterministic report cards and a persisted
human-reviewed `ResearchNote` workflow for one completed backtest, as described
in `docs/roadmap-v0.2.md`.

## Development Commands

This project uses Python 3.13, uv, pytest, ruff, and mypy.

```bash
uv sync
uv run ruff format --check .
uv run ruff check .
uv run mypy packages/research-sdk/src
uv run python -m research_sdk.contracts.json_schema --output-dir packages/research-sdk/schema --check
uv run pytest
```

## Key Rule

No live trading automation until paper trading, validation, risk limits, and human approval gates exist.
