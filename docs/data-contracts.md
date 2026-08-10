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

## Provider-Neutral Daily Market Data

Slice 3 adds provider-neutral daily market-data contracts in
`research_sdk.contracts.daily_market_data`. These contracts do not replace
`DataSnapshotManifest`; they define an additive policy and quality layer that a
future curated snapshot must satisfy before it can be used by experiments.

`DailyMarketDataInstrument` records the platform-facing stable
`instrument_id`, requested/display `symbol`, and normalized listing `venue`.
Provider IDs, FIGI, CUSIP, security-master tables, credentials, and adapter
metadata remain outside this contract.

`CanonicalDailyBar` records structural daily OHLCV facts only:

- `session_date`
- `open`
- `high`
- `low`
- `close`
- `volume`

OHLC values are `Decimal`, finite, and positive. Binary floating point is not
accepted. `volume` must be nonnegative. Validation requires `high >= low`,
`high >= open`, `high >= close`, `low <= open`, and `low <= close`. The bar has
no adjusted close, provider fields, file paths, ingestion timestamps, strategy
state, benchmark state, cost fields, or slippage fields.

`DailyMarketDataPolicy` records the versioned policy for daily market data:
`policy_id`, `asset_class`, `frequency`, `calendar`, `timezone`,
`adjustment_policy`, `distribution_treatment`, `corporate_action_policy`,
`universe_membership_policy`, `survivorship_policy`, `delisting_policy`,
`canonicalization_version`, and `quality_policy_version`. S3a v1 supports only
`AssetClass.ETFS` and `frequency = daily`. It accepts tradable execution OHLC
policies such as `raw` and `split_adjusted`, but rejects `total_return` and
`continuous` as execution-bar policies. Distribution treatment is explicit:
`explicit_cash` means economic distributions must be represented separately as
cash evidence later; `excluded_price_return_only` means the data supports
price-return-only research and must not be confused with total return.

The intended first fully meaningful real research path is raw OHLCV plus
explicit corporate-action/distribution evidence and explicit cash
distributions. S3a documents that direction but does not implement provider
ingestion, split accounting, dividend accounting, benchmark calculation, or
engine execution changes. Unsupported corporate actions in a later selected
window must fail closed until support exists.

`derive_daily_market_data_content_hash(...)` computes a semantic
`sha256:<64 lowercase hex>` hash over only the canonicalization domain/version,
instrument reference, and canonical daily bar records. Caller bar order does not
matter. Equivalent Decimal numeric values such as `100`, `100.0`, and
`100.000000` canonicalize identically. The hash excludes provider name, source
URI, `data_root_uri`, retrieval timestamps, policy ID, quality result, warning
text, file bytes, Parquet metadata, compression settings, strategy, benchmark,
costs, and slippage.

`DailyMarketDataQualityReport` records deterministic facts for one instrument:
policy and version fields, instrument, content hash, expected coverage
start/end, expected and observed session counts, duplicate-row count,
missing/unexpected/duplicate/zero-volume dates, fatal violations, warnings, and
`pass` or `fail` status. It has no `generated_at` field. Direct construction
rejects noncanonical date ordering, duplicate dates, duplicate quality codes,
noncanonical code ordering, nonempty warnings under S3a v1, fatal codes that do
not exactly match their date evidence, status that does not match implied fatal
evidence, invalid coverage date order, and count arithmetic that does not hold.
The count invariant is:

```text
observed_session_count
==
expected_session_count
- len(missing_session_dates)
+ len(unexpected_session_dates)
+ duplicate_row_count
```

`duplicate_row_count` is the sum of extra physical rows beyond the first row for
each duplicated observed session date.

The pure quality service receives explicit `expected_session_dates` from the
caller. They must be nonempty, unique, and actual `date` values. Caller order
may be arbitrary and is canonicalized internally. The service does not add a
calendar library, infer weekdays, call network APIs, read files, use system
locale, use current date, or inspect storage. For ETF daily v1, duplicate
sessions, missing expected sessions, unexpected sessions, and zero-volume
sessions are fatal. It never forward-fills missing bars or synthesizes prices.

`validate_daily_market_data_snapshot_manifest(...)` checks coherence between a
generic `DataSnapshotManifest`, a `DailyMarketDataPolicy`, and a passing
`DailyMarketDataQualityReport` without inspecting external storage. It verifies
manifest kind/status, asset class, frequency, calendar, timezone, adjustment
policy, universe/corporate-action/survivorship/delisting policies, content
hash, row count, manifest `TimeRange` equality with quality expected coverage,
policy linkage, quality status, and exact single-instrument symbol coherence.
For S3a v1, `asset_universe.symbols` must be exactly the one quality-report
symbol, and `row_count` means one observed daily bar row for that instrument.
Multi-instrument curated snapshots are deferred. Current
`AssetUniverseReference` cannot prove stronger stable-ID or venue semantics, so
instrument stable identity remains a daily-market-data policy-layer fact.

Passing quality is necessary but not sufficient for real historical research
authority. Provider provenance, immutable snapshot creation, source licensing,
and storage evidence remain later Slice 3 work. Historical backtests remain
research evidence only and do not imply paper-trading or live-trading authority.

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

## Research Report Card Contract

`ResearchReportCard` is a stable `research_sdk` contract for deterministic
evidence derived from immutable run, snapshot, benchmark, metric, assumption,
and artifact-manifest records. It is common contract data, not a
backtest-engine-private result model and not human interpretation.

The first builder is
`backtest_engine.report_cards.build_deterministic_etf_report_card`. It
supports only the completed deterministic QQQ/SPY infrastructure baseline and
performs no I/O. It summarizes the already-recorded artifact manifest; it does
not read artifact bytes, validate storage, create files, mutate
`artifact_manifest.json`, or add a new artifact to a completed run.

The `deterministic-etf-report-card-v1` policy requires the same synthetic
QQQ/SPY `DataSnapshotManifest` for the researched QQQ data and the SPY gross
benchmark reference. That snapshot must be research-generated market data with
RAW adjustment policy and POINT_IN_TIME temporal coverage. Independent
benchmark snapshots are deferred to a future derivation-policy version.

Report-card IDs use `report-card-` followed by a full lowercase SHA-256 digest
derived from exactly:

- source `run_id`
- `ResearchReportCard` schema version
- derivation-policy version
- data snapshot content hash
- benchmark snapshot content hash
- run config hash
- parameter hash
- artifact manifest hash

The ID excludes review metadata, `ResearchNote` content, generated prose,
wall-clock generation time, runtime duration, current process environment,
local working-directory paths, and artifact-root details except through the
already-recorded artifact manifest hash.

The builder verifies contract-level artifact integrity before summarizing
evidence. It serializes the supplied `RunArtifactManifest` with the same
canonical JSON policy used for `artifact_manifest.json`, computes
`sha256:<hex>`, and requires that hash to match the run's
`artifact_manifest_hash`. It also requires the supplied `manifest_id` to be
`manifest-` plus the source run digest, the run artifact root and manifest URI
to agree with the manifest, the CONFIG artifact evidence hash to equal
`ExperimentRunRecord.config_hash`, and each required artifact entry URI to
equal `artifact_root_uri/filename`. `ReportCardEvidence` itself requires every
artifact kind in `REQUIRED_ARTIFACT_SPECS` exactly once with the expected
filename, format, produced status, full SHA-256 content hash, and nonnegative
byte size.

The deterministic ETF report card records only the approved scalar metric set:
total return, benchmark total return, excess return, maximum drawdown, realized
commission, realized slippage, ending equity, number of trades, and observation
count. Ratio metrics use twelve fractional digits; commission, slippage, and
ending equity use six fractional digits. Negative zero is not a canonical
metric encoding. It carries explicit use restrictions for research-generated
synthetic data, infrastructure validation only, no investment-performance
claim, not production-data research, not paper-trading evidence, and not
live-trading evidence. Use restrictions are normalized by enum value, and
artifact evidence is ordered by artifact kind, filename, and artifact ID.

`ReportCardLineage` stores both data and benchmark snapshot content hashes
alongside config, parameter, and artifact-manifest hashes. The v1 builder
requires the two snapshot hashes to be equal because it supports only one
shared synthetic QQQ/SPY snapshot. The report-card ID can be recomputed from
the durable report-card fields without reading source snapshots or artifacts.

`ResearchReportCard` is durably persisted by `research_sdk` in the dedicated
`research_report_cards` table. Normalized columns copy stable query fields from
the validated contract, while `raw_contract` stores the validated contract
payload. `report_card_id` remains the natural deterministic evidence identity,
and `contract_hash` stores `contract_sha256(report_card)` as a lowercase
64-character SHA-256 hex digest of the entire canonical `ResearchReportCard`
contract. Exact replay requires the same `report_card_id` and `contract_hash`;
the same `report_card_id` with changed canonical content is a persistence
conflict.

Generic report-card identity verification is owned by
`research_sdk.report_card_identity` and does not import persistence,
experiment-recording, SQLAlchemy, psycopg, or `backtest_engine`. The
backtest-engine deterministic ETF verifier keeps the
`deterministic-etf-report-card-v1` policy restriction. Durable persistence adds
a separate source-coherence check: before insert and on readback, the
repository validates the referenced persisted run, data snapshot, benchmark
snapshot, and artifact manifest, then requires the report-card lineage, scope,
assumptions, metrics, limitations, and artifact evidence to agree with those
durable source contracts. Foreign-key existence is not treated as sufficient
evidence integrity.

Because report cards are now durable, `ResearchReportCard` schema changes that
alter canonical `model_dump(mode="json")` output must not be introduced under
the same `schema_version` without an explicit migration or version-aware
deserialization policy.

`research_note.md` remains a generated backtest artifact, while a persisted
`ResearchNote` remains a separate human-reviewed interpretation record. The
`ResearchNote` contract remains unchanged: it has no report-card ID field.
Durable linkage is stored instead in `research_note_report_cards`, a normalized
association table keyed by `(note_id, report_card_id)`.

The finalized single-result workflow derives note IDs with the
`finalized-research-note-v1` policy and ID prefix
`research-note-finalized-v1-`. The `research-note-finalized-v1-*` namespace is
reserved for deterministic `FINALIZED` `EXPERIMENT_RESULT` identities; generic
draft or candidate `ResearchNote` records should use ordinary caller-owned
IDs. The natural ID includes semantic interpretation fields and linked
report-card IDs, while review metadata, timestamps, body markdown, tags, and
database timestamps remain outside natural identity. `contract_hash =
contract_sha256(note)` still protects the complete immutable `ResearchNote`
contract for replay/conflict detection.

Only the finalized interpretation service establishes an authoritative
human-reviewed interpretation. It requires a finalized experiment-result note,
approved embedded review metadata, `HUMAN_OWNER` review role, reviewer ID,
reviewed timestamp, and structured note references that cohere with the
already persisted report card. Generic note persistence may still store drafts
or agent-authored candidates, but those rows are not authoritative. Review
events remain separate audit history and do not authorize finalization. The
workflow does not grant strategy acceptance, risk approval, paper-trading
approval, or live-trading approval.

Supersession targets must already satisfy the same B1b2 authoritative identity
and linkage requirements: finalized-v1 deterministic identity, `HUMAN_OWNER`
approval, valid review chronology, durable linkage to exactly the same report
card, and structured note/report-card evidence-reference coherence. Human
review metadata or deterministic identity alone do not make an arbitrary
caller-owned note ID an authoritative supersession target. Generic
`parent_note_id` lineage remains broader and is not equivalent to replacement
authority.

## Report-Card Comparison Contract

`ResearchReportCardComparison` is a pure C2a value object over two supplied
`ResearchReportCard` contracts. C2a revalidates each supplied card through the
public report-card contract and verifies its deterministic `report_card_id`
before assessing compatibility. Persisted report cards remain the authority for
numeric evidence; comparison does not parse artifacts or trust in-memory
backtest-private objects. A stale or malformed report-card identity is an
input-integrity error, not an `INCOMPATIBLE` assessment.

The compatibility assessment reports `STRICT_COMPATIBLE`,
`CONTEXT_COMPATIBLE`, or `INCOMPATIBLE`. Required context includes contract and
derivation policy, asset class, semantic universe identity and symbols, date
range, frequency, observation count, data snapshot ID/hash, benchmark
ID/snapshot/hash, benchmark total return, cost model, slippage model, lookback,
lag, leakage review, random seed, adjustment policy, temporal coverage,
corporate actions, survivorship, universe membership, calendar, timezone,
engine version, git commit, source limitations, and use restrictions.
`asset_universe.as_of` is not a required v1 equality dimension because current
deterministic mapping may derive it from run execution time.

Observed non-context lineage differences are limited to `strategy_id`,
`strategy_version`, `config_hash`, and `parameter_hash`. They are reported
deterministically but are not interpreted as proof of a one-variable controlled
experiment. In the current deterministic ETF infrastructure,
`parameter_hash` covers the complete resolved backtest config and `config_hash`
covers an even broader config artifact, so opaque hash differences cannot
identify the exact changed parameter.

Metrics-v1 emits only `candidate - baseline` deltas for `total_return`,
`excess_return`, `maximum_drawdown`, and `number_of_trades`. Decimal arithmetic
uses canonical report-card strings, `Decimal`, twelve-place ratio scale, exact
integer count subtraction, no tolerance, and negative-zero normalization.
Direct comparison contract construction validates those arithmetic facts and
rejects compatibility differences whose code, field path, category, or order is
not canonical.
Benchmark total return and observation count are context invariants rather
than performance deltas. Money deltas are deferred until initial capital or
capital basis is structured comparison evidence. Annualized and
risk-adjusted metrics remain deferred until explicit calendar,
annualization, and risk-free-rate policies exist.

The comparison carries deterministic limitations and preserves the exact
report-card use restrictions. Mixed use restrictions are incompatible in v1;
the comparison does not union restrictions and does not rank, select, approve,
or recommend strategies.

The same `report_card_id` must not represent two different full report-card
contracts. Same ID plus exact same contract remains valid for same-card
STRICT-compatible zero-delta checks; same ID plus different content is rejected
as invalid source evidence. C2b adds durable B1b1 readback and source-coherence
validation before invoking C2a; C2a does not itself validate PostgreSQL source
rows or manifest coherence.

## Persisted Report-Card Comparison Query

`ResearchReportCardComparisonQueryResult` is the C2b read-time projection over
an ordered persisted baseline/candidate report-card pair. It always carries the
ordered baseline and candidate report-card IDs, the C2a compatibility
assessment, an optional C2a `ResearchReportCardComparison`, and linked
ResearchNote review-state tuples for each side. `comparison` is present only
when C2a status is `STRICT_COMPATIBLE` or `CONTEXT_COMPATIBLE`; incompatible
pairs retain the assessment but do not contain numeric metric deltas.

`LinkedResearchNoteReviewState` is factual metadata copied from durable
ResearchNote readback. It exposes note identity, note type/status, title,
updated timestamp, evidence strength, structured research decision outcome,
embedded review status, reviewer metadata, review decision text, optional
approval metadata, risk-approval-required metadata, and parent/supersession
IDs. It deliberately excludes interpretation prose, results summary, body
markdown, generated summaries, ranking, authority booleans, current-note
selection, and preferred-note selection.

Review-state tuples are deterministic and must be ordered by ascending
`note_id`. C2b does not silently sort contradictory direct construction or
repository output. Review events remain outside C2b v1; review-state visibility
comes from `ResearchNote.review`. `risk_approval_required` is metadata only and
does not grant risk approval, paper-trading approval, live-trading approval, or
trading authorization.

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
