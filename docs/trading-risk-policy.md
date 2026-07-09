# Trading Risk Policy

This platform is research-first. Phase 0 and Phase 1 must not add live trading
implementation, broker credentials, or unattended execution paths.

For now, formal approval can only be granted by Po-Chun Huang.

## Approval Gates

- Research result: requires benchmark comparison, costs, slippage, leakage notes, and failure analysis.
- Strategy candidate: requires expected behavior, failure modes, validation plan, and reproducible artifacts.
- Paper trading: requires human owner approval and Risk Reviewer approval.
- Live trading: out of scope until explicitly approved in a later phase.

During Phase 0 and Phase 1, approval can authorize design and documentation work
only. It cannot authorize broker integration, live trading implementation, paper
trading execution, account-specific configuration, or unattended execution paths.

## Formal Approval Records

Approval cannot be inferred from silence, prior context, or ambiguous language.
A valid approval record must include:

- Approver: Po-Chun Huang.
- Scope: exact strategy, repository area, run, exception, or action covered.
- Date/time: timestamp of approval.
- Exact action: what is approved and what remains prohibited.
- Location: issue, PR, task note, ledger field, or other durable record.
- Expiration: required when approval is time-limited or run-limited.

## Prohibited In Phase 0 And Phase 1

- Live trading automation.
- Broker API integration.
- Account-specific configuration.
- Production credentials or private keys.
- Claims that a strategy is approved for capital allocation.
- Large parameter sweeps without human approval.
- HFT or latency-sensitive execution work.

## Secrets And Credentials

Secrets include API keys, broker credentials, OAuth tokens, cloud tokens, vendor
tokens, private keys, account identifiers, production credentials, paid service
tokens, and any value that grants access to an external system.

Secrets must not be committed or written to `.env` files tracked by git,
notebooks, logs, run artifacts, screenshots, fixtures, documentation examples,
or CI configuration stored in the repository.

If a secret is exposed, stop work that could spread it, notify Po-Chun Huang,
identify the exposure location, remove the secret, rotate or revoke the
credential, and record the remediation.

## Parameter Sweeps

A parameter sweep requires approval from Po-Chun Huang before execution if it
meets any threshold below:

- More than 100 runs.
- More than 10 minutes estimated runtime.
- Any paid, cloud, or data-vendor cost.

## Required Research Risk Checks

Every strategy result must document:

- Benchmark and benchmark rationale.
- Transaction cost model.
- Slippage model.
- Lookback window.
- Data lag and execution lag.
- Input datasets and snapshot identifiers.
- Leakage and survivorship controls.
- Capacity or liquidity limitations when relevant.
- Failure modes and conditions where the strategy is expected to degrade.

## Human Responsibilities

The human owner approves:

- Financial conclusions.
- Risk exceptions.
- Paper trading.
- Live trading.
- Large parameter sweeps.
- Any broker or execution integration.

Agents may propose these actions but may not approve or execute them.

## Phase 0 Acceptance Criteria

- Risk policy and approval gates are documented.
- Live trading and broker integration are explicitly out of scope.
- No secrets, credentials, or account assumptions are introduced.
- Approval, secret handling, and parameter sweep thresholds are documented.

## Phase 1 Acceptance Criteria

- Strategy PR template or checklist enforces required research risk checks.
- Backtest outputs include cost, slippage, benchmark, leakage, and failure analysis sections.
- Risk Reviewer approval is required before any paper trading work begins.
