# Agent Rules

This document mirrors the repository-level operating model in `AGENTS.md` and
adds implementation guidance for Phase 0 and Phase 1. Phase acceptance criteria
live in `docs/roadmap.md`; agents must check that file before Phase 0 or Phase 1
work.

## Roles

- Human owner: product owner, research director, and risk approver.
- Agents: implement, test, document, summarize, and propose.
- Risk Reviewer: required reviewer before any strategy can move toward paper trading.

Agents do not approve financial conclusions, risk exceptions, paper trading, or
live trading.

For now, formal approval can only be granted by Po-Chun Huang.

## Hard Rules

1. Do not modify live trading or broker-integration code without explicit human approval in a later phase.
2. Do not commit secrets, API keys, broker credentials, production credentials, private keys, or tokens.
3. Do not add a strategy result without benchmark comparison and cost/slippage assumptions.
4. Do not add a feature without documenting lookback, lag, input data, and leakage assumptions.
5. Every backtest must write to the experiment ledger once the ledger exists.
6. Every code change must include or update tests where applicable.
7. Every strategy PR must include expected behavior, failure modes, and validation plan.
8. Large parameter sweeps require human approval before execution.
9. Risk Reviewer approval is required before paper trading.
10. Prefer simple, testable baselines before complex ML, HFT, or exotic instruments.

During Phase 0 and Phase 1, approval can authorize design and documentation work
only. It cannot authorize implementation of broker integration, live trading,
paper trading execution, account-specific configuration, or unattended execution
paths.

## Formal Approval Records

Approval cannot be inferred from silence, surrounding conversation, prior
approval, or ambiguous wording. A valid approval record must include:

- Approver: Po-Chun Huang.
- Scope: exact repository area, strategy, run, or action covered.
- Date/time: timestamp of approval.
- Exact action: what is approved and what remains out of scope.
- Location: issue, PR, task note, ledger field, or other durable record.
- Expiration: required when approval is time-limited or run-limited.

Agents must ask again when the requested work exceeds the approval scope.

## Secrets And Credentials

Secrets include API keys, broker credentials, OAuth tokens, cloud tokens, vendor
tokens, private keys, account identifiers, production credentials, paid service
tokens, and any value that grants access to an external system.

Secrets must not be committed or written to:

- `.env` files tracked by git.
- Notebooks.
- Logs.
- Run artifacts.
- Screenshots.
- Fixtures.
- Documentation examples.
- CI configuration or variables stored in the repository.

Use placeholders such as `<API_KEY>` or `<BROKER_ACCOUNT_ID>` in documentation.
Do not add real endpoints, account values, or credential-like examples.

If a secret is exposed:

1. Stop work that could spread the secret.
2. Notify Po-Chun Huang.
3. Identify the file, commit, artifact, log, or note where it appeared.
4. Remove the secret from the repository or artifact location.
5. Rotate or revoke the credential before resuming related work.
6. Record the remediation in the relevant issue, PR, or incident note.

## Parameter Sweeps

A parameter sweep requires approval from Po-Chun Huang before execution if it
meets any of these thresholds:

- More than 100 runs.
- More than 10 minutes estimated runtime.
- Any paid, cloud, or data-vendor cost.

## Agent Tool Security Boundary

Agent-facing tools must be allowlisted, auditable, and scoped to research
workflows. They must not expose broker order placement, credential access,
production mutation, unrestricted shell execution, or unattended external actions
without documented approval gates. During Phase 0 and Phase 1, they must not
expose broker integration, live trading implementation, paper trading execution,
or account-specific configuration.

## Phase 0 Agent Scope

Agents may:

- Create and edit documentation.
- Propose schema and artifact contracts.
- Inspect repository structure.
- Add non-executable scaffolding when requested.

Agents must not:

- Add live trading implementation.
- Add broker credentials or account-specific configuration.
- Assume a specific data vendor, broker, cloud provider, or production environment.
- Claim a strategy is valid for capital allocation.

## Phase 1 Agent Scope

Agents may add tested infrastructure for:

- JSON/Pydantic experiment ledger and data contracts.
- Backtest artifact validation.
- Minimal deterministic baseline backtests.
- CI and local development commands.
- Documentation checks for required research metadata.

Postgres/Alembic migrations come after JSON/Pydantic contracts stabilize.

Any strategy implementation must include expected behavior, benchmark,
cost/slippage assumptions, failure modes, validation plan, and leakage notes.

## Pull Request Standard

A good PR is small, tested, documented, and easy to review. It should state:

- What changed.
- Why it changed.
- Tests run.
- Risk and leakage assumptions affected.
- Any human approvals needed.
