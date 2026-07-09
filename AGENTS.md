# Agent Rules for Quant Platform

This repository is for building an enterprise-grade multi-asset quant research platform.

## Human / Agent Operating Model

The human owner is the product owner, research director, and risk approver.
Agents implement, test, document, summarize, and propose. Agents do not approve financial conclusions or live trading.

## Hard Safety Rules

1. Never modify live trading or broker-integration code without explicit human approval.
2. Never commit secrets, API keys, broker credentials, production credentials, private keys, or tokens.
3. Never add a strategy result without benchmark comparison and cost/slippage assumptions.
4. Never add a feature without documenting lookback, lag, input data, and leakage assumptions.
5. Every backtest must write to the experiment ledger once the ledger exists.
6. Every code change must include or update tests where applicable.
7. Every strategy PR must include expected behavior, failure modes, and validation plan.
8. Large parameter sweeps require human approval.
9. The Risk Reviewer role must review any strategy before paper trading.
10. Prefer simple, testable baselines before complex ML or HFT.

## Near-Term Priority

Build Phase 0 and Phase 1:

- Repo structure
- Documentation
- Development environment
- Experiment ledger schema
- Backtest artifact contract
- Tests and CI

Do not prioritize live trading, complex ML, options execution, or HFT yet.

## Required Run Artifact Contract

Each backtest run should eventually produce:

- config.json
- metrics.json
- trade_log.parquet
- signal_log.parquet
- daily_equity.parquet
- drawdown_series.parquet
- monthly_returns.parquet
- regime_breakdown.json
- failure_analysis.md
- research_note.md

## Definition of Good Work

A good PR is small, tested, documented, and easy to review.
