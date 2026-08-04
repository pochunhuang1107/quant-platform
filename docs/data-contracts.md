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

## Synthetic Daily ETF Fixture Contract

The first deterministic backtest-engine slice uses
`tests/fixtures/backtest_engine/synthetic_daily_etf_bars.json`. This file is
version-controlled, deterministic, offline, fixture-only, and explicitly not
historical market data or a production market-data source. It contains no
splits or dividends and cannot support performance claims.

The fixture contains dataset-level metadata:

- `snapshot_id`
- fixture/source version
- `timezone`
- `currency`
- `adjustment_policy`, fixed to `none`
- `logical_available_at`
- `source_dataset`
- `bars`

Each daily bar contains only:

- `symbol`
- `trading_date`
- `open`
- `high`
- `low`
- `close`
- `volume`

Prices are parsed from JSON strings into `Decimal`; binary floating point is
not used for prices, accounting, or metrics. The QQQ buy-and-hold baseline
requires exactly QQQ and SPY, filters the requested inclusive start/end range
deterministically, sorts by `trading_date` then `symbol`, rejects duplicate
symbol/date rows, rejects unexpected symbols, requires QQQ and SPY to have the
same date set in the requested window, and requires at least two aligned
observations. It performs no calendar inference beyond supplied fixture dates
and never silently inner-joins or drops missing sessions.

Validation requires positive open, high, low, and close values; `high >=
max(open, close)`; `low <= min(open, close)`; nonnegative volume; and a data
snapshot identity matching the resolved backtest configuration. There is no
adjusted close field in this fixture, no corporate-action handling, no intraday
logic, and no production vendor dependency.

The first backtest-to-ledger integration records a `DataSnapshotManifest` for
the actual version-controlled JSON fixture bytes. It does not reconstruct a new
canonical in-memory dataset snapshot. The mapper requires all four snapshot
identities to be identical before contract construction: the fixture
`snapshot_id`, the completed result `input_snapshot_id`, the resolved
configuration `data_snapshot_id`, and the resolved configuration
`benchmark_snapshot_id`.

The fixture-local `adjustment_policy` value `none` maps to ledger
`DataAdjustmentPolicy.RAW`. The snapshot notes explicitly state that the prices
are unadjusted synthetic raw fixture values with no splits or dividends.
`TemporalCoverage.POINT_IN_TIME` refers only to the synthetic fixture's logical
availability timestamp and is not a historical vendor point-in-time claim.

The integration keeps hash meanings separate:

- `run_id` is `run-` plus the full execution-input SHA-256 digest.
- `parameter_hash` is `sha256:` plus the canonical resolved-configuration
  hash.
- `config_hash` is the SHA-256 byte hash of generated `config.json`.
- `artifact_manifest_hash` is the SHA-256 byte hash of generated
  `artifact_manifest.json`, whose bytes include root-dependent `file://` URIs.
- `DataSnapshotManifest.content_hash` is the SHA-256 byte hash of the
  version-controlled synthetic fixture JSON.

The backtest mapper returns immutable ledger records built from stable
contracts only. The application boundary constructs the
`CompletedExperimentRecordBundle` and calls the completed-experiment recording
service. Executing the mapper itself does not load SQLAlchemy, psycopg,
`research_sdk.persistence`, or `research_sdk.experiment_recording`.

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

For the first deterministic ETF baseline, portfolio artifacts use a narrower
fixture-only schema: strategy equity, retained cash, integer QQQ quantity, QQQ
close, gross SPY benchmark equity, SPY close, drawdown, and month-end return
series. Monthly returns select the final available strategy equity observation
in each calendar month from the supplied fixture sessions. The first reported
month is `month_end_equity / initial_capital - 1`; later months are
`current_month_end_equity / previous_month_end_equity - 1`. The month key is
serialized as `YYYY-MM`; no trading calendar is inferred and no annualization
is performed. Annualized return, volatility, Sharpe, Sortino, beta, alpha, and
risk-free-rate handling are deferred until calendar and annualization policies
are formalized.

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
