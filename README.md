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

Phase 0: Agent-ready foundation.

## Documentation Map

- [Architecture](docs/architecture.md): structure, responsibilities, and research lifecycle.
- [Roadmap](docs/roadmap.md): canonical Phase 0 and Phase 1 gates.
- [Agent Rules](docs/agent-rules.md): agent scope, approval records, secrets policy, and PR expectations.
- [Experiment Ledger](docs/experiment-ledger.md): ledger fields, artifacts, status lifecycle, and review metadata.
- [Experiment Ledger DB Plan](docs/experiment-ledger-db-plan.md): planned Postgres/Alembic persistence design for the experiment ledger metadata layer.
- [Persistence Setup](docs/persistence-setup.md): minimal SQLAlchemy/Alembic setup and local migration command guidance.
- [Data Contracts](docs/data-contracts.md): snapshot manifests, point-in-time fields, and research output contracts.
- [Contract Map](docs/contract-map.md): current Phase 1 contract models, schemas, fixtures, relationships, validation level, and deferred behavior.
- [Trading Risk Policy](docs/trading-risk-policy.md): approval gates, prohibited work, and risk checks.

## Next Milestone

Complete Phase 0 by making the documented scaffold, docs, safety rules, ledger
contract, data contracts, and risk policy satisfy the measurable checklist in
`docs/roadmap.md`.

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
