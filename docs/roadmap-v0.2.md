# Quant Research Platform Roadmap v0.2

## Status

- Baseline merge commit: `52b2e030af584460ef49ce75b2e6f570d16eb3ec`.
- Document status: proposed current roadmap for human approval and merge.
- Date: 2026-08-05.
- Relationship to v0.1: v0.2 revises sequencing based on the implemented
  repository state while preserving the strategic principles of v0.1.
- S3c3c status: the bounded real QQQ/SPY 2024 validation completed, and the
  human owner accepted formal run-008. Trusted snapshot-v2 execution-input
  bundles now exist, so S3d2b is unblocked. The evidence remains
  `LATEST_KNOWN`; paper and live trading remain unapproved. See
  `docs/validation/s3c3c-qqq-spy-2024.md`.

Roadmap v0.1 remains the historical baseline. This version does not erase prior
decisions; it records what the repository has actually implemented and splits
Phase 1 into a completed reproducibility foundation and a remaining research
workflow layer.

## Change Log From v0.1

- Reproducibility foundation implemented through Phase 1A.
- Actual package and contract boundaries established under
  `packages/research-sdk/src/research_sdk` and
  `packages/backtest-engine/src/backtest_engine`.
- PostgreSQL experiment-ledger persistence completed with Alembic migrations
  under `infra/db/migrations/versions`.
- Deterministic synthetic ETF vertical slice completed for one fixture-only QQQ
  buy-and-hold baseline with SPY as a gross benchmark.
- API, UI, semantic memory, knowledge graph, real-data research, paper trading,
  and live trading remain deferred.
- Phase 1 is split into:
  - Phase 1A - Reproducibility Foundation Complete.
  - Phase 1B - Research Workflow Layer.

## Current Architecture Inventory

Implemented research contract package:

- `packages/research-sdk/src/research_sdk/contracts`

Implemented contract names:

- `DataSnapshotManifest`
- `ExperimentRunRecord`
- `RunArtifactManifest`
- `RunArtifactEntry`
- `ResearchNote`
- `ReviewMetadata` for structured review state and attribution

Append-only review-event persistence is implemented separately. There is no
standalone `ReviewEvent` contract in the current contract package, and
`ReviewMetadata` does not implement approval-workflow authority. The human owner
remains the approval authority.

Implemented persistence package:

- `packages/research-sdk/src/research_sdk/persistence`

Implemented repository boundary:

- `SqlAlchemyExperimentLedgerRepository`

Implemented completed-experiment recording service:

- `packages/research-sdk/src/research_sdk/experiment_recording`
- `CompletedExperimentRecordBundle`
- `record_completed_experiment`

Implemented deterministic backtest package:

- `packages/backtest-engine/src/backtest_engine`
- `ResolvedBacktestConfig`
- `ExecutionMetadata`
- `CompletedBacktestResult`
- `GeneratedArtifactBundle`

Implemented backtest-to-ledger mapping boundary:

- `packages/backtest-engine/src/backtest_engine/ledger_mapping.py`
- `CompletedBacktestLedgerRecords`
- `map_completed_backtest_to_ledger_records`

Implemented database tables:

- `experiment_runs`
- `data_snapshot_manifests`
- `run_artifact_manifests`
- `run_artifact_entries`
- `research_notes`
- `review_events`

Implemented migration path:

- `infra/db/migrations/versions`

Hosted live PostgreSQL coverage is configured in `.github/workflows/ci.yml` and
includes migration smoke tests, repository persistence smoke tests, concurrency
validation, and the completed deterministic backtest recording path.

The current deterministic artifact set is:

- `config.json`
- `metrics.json`
- `trade_log.parquet`
- `signal_log.parquet`
- `daily_equity.parquet`
- `drawdown_series.parquet`
- `monthly_returns.parquet`
- `regime_breakdown.json`
- `failure_analysis.md`
- `research_note.md`
- `artifact_manifest.json`

`research_note.md` is currently a generated run artifact. It is not the same
thing as a persisted `ResearchNote` contract.

## Phase 1A Completion Statement

Phase 1A - Reproducibility Foundation Complete is implemented through merge
commit `52b2e030af584460ef49ce75b2e6f570d16eb3ec`.

Phase 1A includes:

- immutable research contracts
- canonical hashing
- data snapshot manifests
- experiment run records
- artifact manifests
- `ResearchNote` contract, structured `ReviewMetadata`, and append-only
  review-event persistence
- PostgreSQL migrations
- append-only repository persistence
- replay and conflict behavior
- concurrency validation
- completed-experiment atomic recording
- deterministic synthetic ETF backtest baseline
- deterministic artifact generation
- pure backtest-to-ledger mapping
- hosted PostgreSQL vertical integration

Phase 1A does not imply production data readiness, strategy research readiness,
portfolio readiness, paper-trading readiness, live-trading readiness, or
autonomous financial decision authority.

## Phase 1B Objective

Phase 1B turns reproducible experiment infrastructure into a disciplined
research workflow that produces deterministic evidence, human-reviewed
findings, valid comparisons, and controlled experiment sets.

## Evidence Versus Interpretation

### Deterministic Research Report Card

A deterministic research report card is automatically derived from:

- run contract
- data snapshot
- benchmark
- metrics
- cost assumptions
- slippage assumptions
- leakage assumptions
- artifact manifest
- failure and limitation metadata

The report card contains authoritative experiment facts.

### ResearchNote

A `ResearchNote` contains:

- hypothesis
- interpretation
- finding
- limitations
- failure modes
- review state
- decision
- next step

A `ResearchNote` is human-reviewed research interpretation. LLM-generated prose
must not become the authoritative record without deterministic source fields
and human review.

`ResearchNote` persistence is not required to be atomic with experiment
completion. Interpretation and review may occur after the completed run
commits, so the research note should be treated as a separate append-only
follow-up record.

## Revised Implementation Sequence

1. Roadmap v0.2 and status reconciliation.
2. Deterministic report card plus persisted `ResearchNote` workflow for one
   completed backtest.
3. Read-only compatible-run query and comparison service.
4. First curated daily ETF snapshot policy and first real versioned strategy.
5. Controlled batch of 5-10 approved experiments.
6. Expand toward 20-50 reproducible ETF/stock experiments.
7. Feature registry and semantic research memory.
8. Knowledge graph and agentic research workflow.
9. Paper trading only after validation, risk limits, reconciliation, and human
   approval gates.
10. Live trading remains outside the near-term roadmap.

A generic batch runner should not precede real strategy and data policy.

## Next Three Implementation Slices

### Slice 1: Deterministic Report Card And ResearchNote

Acceptance criteria:

- deterministic report-card identity
- explicit source run ID
- benchmark and cost summary
- leakage assumptions
- limitations and failure modes
- human review metadata
- deterministic `ResearchNote` identity policy
- replay and conflict behavior
- no authoritative unreviewed LLM prose

### Slice 2: Compatible-Run Comparison/Query

Acceptance criteria:

- read-only behavior
- completed runs only
- common frequency
- compatible date range
- compatible benchmark
- compatible snapshot policy
- compatible cost and slippage assumptions
- artifact completeness
- review-state visibility
- no ranking solely by return
- no Sharpe, CAGR, or volatility until calendar and annualization policy exists

### Slice 3: Real ETF Research Readiness

Acceptance criteria:

- curated snapshot lineage
- corporate-action and adjustment policy
- survivorship and universe policy
- versioned strategy definition
- parameter definition
- benchmark policy
- experiment identity
- validation and out-of-sample design
- failure modes
- human approval for large sweeps

## Deferred Scope

The architecture remains multi-asset-capable, but the following work remains
deferred:

- API and UI
- worker orchestration
- broad portfolio engine
- feature registry
- semantic memory
- knowledge graph
- ML
- HFT
- derivatives and intraday support
- broker integration
- paper trading
- live trading

Phase 1B should not implement premature multi-asset breadth before the ETF
research workflow is disciplined and reviewable.

## Governance Gates

- The human owner remains the product owner, research director, and risk
  approver.
- Agents do not make autonomous financial decisions.
- No live trading is allowed without paper validation, risk limits,
  reconciliation, and explicit human approval gates.
- No strategy promotion is allowed without benchmarks, costs, failure modes,
  validation, and next-step criteria.
- Large experiment sweeps require human approval.
- Reproducibility and leakage prevention take priority over model complexity.

## Source-Of-Truth Policy

- Roadmap v0.1 remains the historical baseline.
- Roadmap v0.2 becomes the current repository roadmap only after human approval
  and merge.
- Future roadmap revisions must be versioned and include a change log.
- `README.md` and `docs/roadmap.md` point to the current approved roadmap
  version.
- Roadmaps should use stable implementation baselines such as merge commits and
  should avoid volatile test counts.
