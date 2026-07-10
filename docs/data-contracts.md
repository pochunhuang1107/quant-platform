# Data Contracts

Data contracts define the minimum fields and assumptions needed for reproducible
research. They intentionally avoid choosing a data vendor, broker, or storage
backend in Phase 0.

See [Contract Map](contract-map.md) for the current schema-backed contracts and
fixture coverage.

## General Rules

- All timestamps are timezone-aware and stored in UTC unless a contract explicitly states otherwise.
- Every dataset must include a snapshot identifier and creation timestamp.
- Point-in-time behavior must be documented for all market, fundamental, derived, and reference data.
- Missing data handling must be explicit.
- Corporate action, rollover, and survivorship assumptions must be documented when relevant.
- Research outputs must identify lookback windows, lag assumptions, and leakage controls.

## Data Snapshot Manifest

Every data snapshot should have a manifest with:

- `snapshot_id`
- `created_at`
- `source_dataset`
- `source_version`
- `ingestion_time`
- `time_range`
- `schema_version`
- `row_count`
- `content_hash`
- `adjustment_policy`
- `calendar`
- `universe_membership_policy`
- `known_limitations`

Snapshot identifiers alone are not sufficient for accepted research. Accepted
results must reference a manifest that supports audit and reproduction.

## Point-In-Time Fields

Datasets that can revise, arrive late, or become available after their effective
date must include point-in-time metadata:

- `as_of_timestamp`: timestamp at which the record is viewed.
- `effective_timestamp`: timestamp or date the record describes.
- `release_timestamp`: timestamp the information was released by the source, when known.
- `available_timestamp`: timestamp the platform assumes the data became usable.
- `revision_id`: revision identifier or null with documented reason.

Signals and features may use only records whose `available_timestamp` is earlier
than or equal to the signal timestamp after the documented lag.

## Market Bar Contract

Minimum fields:

- `symbol`
- `timestamp`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `asset_class`
- `currency`
- `source_dataset`
- `snapshot_id`
- `adjustment_policy`
- `as_of_timestamp`, when revisions or late corrections are possible.
- `available_timestamp`, when different from `timestamp`.
- `revision_id`, when applicable.

Validation expectations:

- `high >= low`
- `open`, `high`, `low`, and `close` are non-negative where applicable.
- Timestamps are unique per `symbol`, `timestamp`, and bar frequency.
- Adjustment policy is explicit: raw, split-adjusted, total-return, continuous, or other documented policy.

## Corporate Actions, Rolls, And Survivorship

- Restatements: retain revision metadata and document whether the run uses first-available or latest-known data.
- Delistings: document whether delisted assets remain in the universe and how terminal prices are handled.
- Corporate actions: document split, dividend, merger, and symbol-change adjustment policy.
- Futures rolls: document roll schedule, roll trigger, price adjustment method, and contract selection rule.
- Survivorship: universe membership must be point-in-time or explicitly labeled as survivorship-biased.

## Signal Log Contract

Minimum fields:

- `run_id`
- `symbol`
- `timestamp`
- `signal_name`
- `signal_value`
- `target_weight` or `target_position`
- `lookback`
- `lag`
- `feature_snapshot_id`
- `as_of_timestamp`
- `available_timestamp`
- `revision_id`, when applicable.

Signals must be generated only from data available at the signal timestamp after
the documented lag.

## Trade Log Contract

Minimum fields:

- `run_id`
- `symbol`
- `timestamp`
- `side`
- `quantity`
- `price`
- `notional`
- `fees`
- `slippage`
- `currency`
- `order_type_assumption`
- `fill_price_convention`
- `cost_model`
- `slippage_model`

Trade logs represent simulated fills in Phase 0 and Phase 1. They must not imply
broker connectivity or live execution.

## Portfolio Output Contract

Minimum files:

- `daily_equity.parquet`: date, equity, cash, gross_exposure, net_exposure.
- `drawdown_series.parquet`: date, equity, drawdown.
- `monthly_returns.parquet`: month, return.
- `metrics.json`: returns, volatility, Sharpe or similar risk-adjusted metric, drawdown, turnover, benchmark comparison, benchmark snapshot, cost model, slippage model, fill convention, and fee assumptions.
- `regime_breakdown.json`: documented regime labels and performance by regime.

## Research Note Contract

`research_note.md` must include:

- Hypothesis.
- Universe and benchmark.
- Time range and frequency.
- Input data and snapshot identifiers.
- Lookback and lag assumptions.
- Leakage and survivorship review.
- Cost and slippage assumptions.
- Fill-price convention and fee assumptions.
- Expected behavior.
- Failure modes.
- Validation plan, including baseline comparator, train/test or in/out-of-sample split, sensitivity checks, parameter sweep scope, and known failure regimes.
- Summary of results and limitations.

## Phase 0 Acceptance Criteria

- Minimum data, signal, trade, portfolio, and research note contracts are documented.
- Snapshot manifests and point-in-time fields are documented.
- Field-level completeness requirements cover required fields, timestamp semantics, units, currencies, keys, and minimum validation expectations.
- Contracts do not depend on a named vendor, broker, or credential.

## Phase 1 Acceptance Criteria

- Contract validators exist for required artifacts and minimum fields.
- Tests cover missing fields, invalid timestamps, and incomplete artifact bundles.
- Baseline backtest outputs conform to these contracts.
