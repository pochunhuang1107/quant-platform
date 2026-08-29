# QQQ SMA Trend-Filter V1 Research Protocol

## Status And Authority

This document is the canonical human-approved research protocol for:

- `strategy_id`: `qqq-sma-trend-filter`
- `strategy_version`: `qqq-sma-trend-filter-v1`
- instrument: QQQ
- frequency: daily
- primary benchmark: SPY gross economic buy-and-hold under the approved S3d2b
  benchmark economic policy
- secondary factual comparator: same-period QQQ economic buy-and-hold as a
  separate research run

This is a policy and specification authority only. It does not implement or
authorize data acquisition, temporal data composition, strategy execution,
holdout execution, parameter sweeps, paper trading, live trading, or autonomous
financial decisions. The bounded QQQ/SPY 2024 S3d2b acceptance remains
infrastructure-validation evidence only and is not broadened by this protocol.

## Human Approval Authority

> "I APPROVE the QQQ SMA trend-filter v1 research protocol decisions above,
> including the fixed SMA-200 rule, raw-close/split fail-closed policy, fungible
> settled cash, 2016–2025 data target, 2017–2020 development, 2021–2024
> validation, 2025 holdout, predefined catastrophic gates, and no parameter
> sweep or performance-driven retuning. I confirm I have not run or inspected
> QQQ SMA-200 strategy results for the 2025 holdout period."

This approval authorizes specification work only. It does not authorize
provider acquisition, real strategy execution, 2025 holdout execution,
parameter sweeps, paper trading, live trading, or autonomous financial
decisions. The quoted approval is already granted; repository adoption records
it and does not require a second approval.

## Fixed Strategy Semantics

V1 has exactly one parameter:

```text
lookback_sessions = 200
```

There is no parameter sweep in v1.

For execution session `T`:

1. Only completed QQQ bars from expected sessions strictly before `T` are
   strategy-visible.
2. The latest observable complete-bar session is `T-1`, meaning the expected
   session immediately preceding `T`.
3. The signal window contains exactly the latest 200 completed expected
   sessions ending at `T-1`.
4. `close(T-1)` is included in that same 200-session arithmetic mean.

```text
SMA200(T) = arithmetic mean of the 200 completed QQQ raw closes ending at T-1

if close(T-1) > SMA200(T):
    target_state = INVESTED
else:
    target_state = CASH
```

Equality means `CASH`. The decision must be completely resolved before the
session-`T` raw open becomes available as fill input. The `T` raw open is
execution input only, never signal input. The `T` raw close is valuation input
only, never same-session decision input.

If the target state equals the current position state, no trade occurs and no
transaction cost is generated. A target change authorizes exactly one
full-state transition at the `T` raw open.

## Position Policy

V1 has exactly two QQQ position states:

- `CASH`: zero QQQ shares.
- `INVESTED`: long the maximum whole integer QQQ quantity affordable under the
  approved buy fill and commission assumptions.

The only transitions are:

- `CASH -> INVESTED`: buy the maximum affordable integer QQQ quantity.
- `INVESTED -> CASH`: sell the entire integer QQQ position.

V1 has no shorting, leverage, fractional QQQ shares, partial sizing, target
weights, pyramiding, scaling, intraday trading, or discretionary overrides.

## Execution-Cost Policy

QQQ commission is one basis point per executed notional. QQQ slippage is two
basis points adverse to the strategy on every buy and sell.

Buy economics are:

```text
fill_price = raw_open * (1 + 0.0002)
executed_notional = integer_quantity * fill_price
commission = executed_notional * 0.0001
cash_delta = -(executed_notional + commission)
```

Sell economics are:

```text
fill_price = raw_open * (1 - 0.0002)
executed_notional = integer_quantity * fill_price
commission = executed_notional * 0.0001
cash_delta = executed_notional - commission
```

Slippage is embedded in `fill_price` and must not be subtracted from cash a
second time. The SPY benchmark has zero commission and zero slippage. Corporate
actions generate no transaction costs.

## Cash And Book-Cost Policy

Settled distribution cash is fungible spendable cash. A cash distribution does
not create a trade and does not trigger automatic reinvestment. A later,
independently generated SMA entry may use all then-spendable cash, including
previously settled distributions. This is not dividend reinvestment because the
allocation is authorized by a separate strategy signal.

On a full QQQ exit:

- sell all integer shares;
- set `total_book_cost` to exactly zero;
- preserve cash;
- preserve outstanding distribution receivables; and
- preserve applied corporate-action authority.

A later re-entry establishes a new book cost from the new buy economics and
does not revive an earlier cost basis. V1 requires no partial cost-basis
allocation.

## Corporate-Action Feature Policy

Economic accounting continues to use raw prices and explicit corporate
actions under the approved S3d1/S3d2b policy.

Cash distributions remain accounting events. Receivables and settled cash are
not strategy signal inputs. Raw ex-distribution price movement remains in the
raw-close SMA signal. V1 is therefore a **raw-price trend strategy**, not a
total-return trend strategy.

V1 fails closed if a QQQ split affects any session in the active 200-session
signal window. It must not silently splice raw prices, retroactively adjust
prices, infer adjusted closes, introduce split-normalized feature history, or
use provider-adjusted prices. A causally normalized split-aware feature series
requires a separately specified future strategy/data policy.

Economic split accounting outside the signal-window feature issue remains
governed by existing fail-closed rules, including rejection of a split that
would produce fractional QQQ shares.

## Warm-Up And Data Authority

Before the first evaluation session of every experiment partition, exactly 200
prior completed expected QQQ sessions must be available as signal history.
Fewer than 200 required sessions fails closed. The implementation must not emit
`CASH` by default, shorten the SMA, pad data, intersect dates, or repair missing
history.

Warm-up sessions are feature history only. They do not enter evaluation
performance metrics and do not carry portfolio state from another partition.

The intended historical authority target is 2016-01-04 through 2025-12-31.
Actual session membership must be defined by the versioned expected XNYS
session authority. This freezes the target period but does not authorize
provider acquisition.

Future multi-year data must provide one deterministic, provider-neutral
composite execution-data authority per instrument. This protocol does not
prescribe reuse of the existing snapshot-v2 contract name. A future design may
use a new versioned composite contract or a legitimate backward-compatible
snapshot extension, but it must provide:

- exact component verification;
- deterministic ordered provenance;
- no overlaps, gaps, duplicate expected sessions, repairs, or intersections;
- exact instrument, policy, profile, and calendar compatibility;
- deterministic composite identity;
- full-period session authority; and
- preserved corporate-action provenance.

## Frozen Research Partitions

The nominal calendar/session boundaries are:

| Partition | Dates | Use |
| --- | --- | --- |
| History / warm-up foundation | 2016-01-04 through 2016-12-30 | Feature history only; no strategy performance claim |
| Development | 2017-01-03 through 2020-12-31 | Development experiment |
| Validation | 2021-01-04 through 2024-12-31 | Validation experiment |
| Final holdout | 2025-01-02 through 2025-12-31 | Embargoed final holdout |

Actual first and last membership must be resolved against the versioned XNYS
expected-session authority.

Each evaluation partition is an independent deterministic experiment. For each
partition:

- initialize strategy capital at the first execution session;
- initialize the SPY benchmark independently at the first execution session;
- use the preceding 200 sessions only for feature history;
- do not carry QQQ holdings, cash, or benchmark holdings across boundaries;
- do not include warm-up equity in partition metrics; and
- retain the established first-session ordering in which corporate-action
  accounting occurs before first-session orders.

The first decision may use the immediately prior completed session when that
session is part of the required 200-session history.

## 2025 Holdout Embargo

The human owner confirms that QQQ SMA-200 results for 2025 have not been run or
inspected. The 2025 partition is therefore reserved as the final holdout for
v1.

Until development and validation gates are completed and separately approved,
do not:

- execute SMA-200 over 2025;
- calculate 2025 SMA-200 performance;
- generate a 2025 SMA-200 report card;
- inspect 2025 SMA-200 signals, trades, or metrics; or
- use 2025 strategy outcomes to alter the strategy.

General market knowledge about QQQ in 2025 does not by itself invalidate the
holdout; actual strategy-specific result inspection does. Any accidental 2025
SMA-200 execution or result inspection must be documented, and the holdout
designation must be reconsidered before proceeding.

## Parameter, Retuning, And Versioning Policy

SMA-200 is frozen before implementation. V1 has no first-version sensitivity
sweep and no result-driven changes to its lookback, comparison operator, signal
price series, execution lag, costs, sizing, cash-use policy, split policy, or
benchmark policy.

Any economically or strategically material change requires a new strategy
version, a new deterministic identity, and a restart of the validation sequence
before holdout use. V1 semantics must not be overwritten. A later small
sensitivity diagnostic requires separate human approval and must not replace
200 with whichever parameter performed best.

## Predefined Technical Failure Gates

Each of the following is an automatic technical failure. No performance result
may override it:

- any lookahead or leakage violation;
- any current-session bar entering decision input;
- any missing signal-window session;
- any data repair or date intersection;
- any unexpected or duplicate session;
- QQQ/SPY evaluation-session mismatch;
- insufficient 200-session history;
- unsupported or duplicate corporate action;
- a split affecting the active raw-price signal window;
- ambiguous payable-date or event authority;
- exact bundle or composite verification failure;
- nondeterministic result replay or identity;
- artifact semantic-verification failure;
- canonical result-reconciliation failure;
- ledger-mapping authority mismatch; or
- representation of `LATEST_KNOWN` evidence as point-in-time strategy
  knowledge.

## Predefined Catastrophic Strategy-Behavior Gates

These gates use each evaluation partition's economic equity and execution
records. They are broad rejection/diagnostic limits, not optimization targets,
and are frozen before development results.

### Maximum Drawdown

Fail when:

```text
maximum_drawdown < -0.50
```

This means an economic-equity drawdown worse than 50%.

### Excessive Transitions

Each executed QQQ buy or sell is one one-way trade.

```text
annualized_one_way_trade_count =
    one_way_trade_count * 252 / evaluation_session_count

fail when annualized_one_way_trade_count > 24
```

### Excessive Explicit Execution-Cost Burden

For every QQQ trade, retain commission and the monetary adverse slippage
represented by fill versus raw open. Embedded slippage must not be counted
twice.

```text
total_explicit_cost =
    sum(all QQQ commission)
    + sum(all QQQ adverse slippage amount)

annualized_cost_burden =
    (total_explicit_cost / partition_initial_capital)
    * 252 / evaluation_session_count

fail when annualized_cost_burden > 0.02
```

This is more than 2% of starting capital per evaluation year on an annualized
basis. These limits must not be relaxed after development or validation results
merely to make v1 pass.

## Performance Interpretation And Benchmark Policy

V1 has no mechanical minimum total return, excess return, CAGR, Sharpe,
volatility, or benchmark-relative return development gate. Underperformance is
evidence requiring human interpretation, not authorization to retune.

The primary engine benchmark is SPY gross economic buy-and-hold under the
existing accepted policy: raw prices, explicit corporate actions, distributions
retained as cash, fractional units, zero commission, and zero slippage.

The secondary comparator is a separate QQQ economic buy-and-hold run over the
same composite QQQ authority, composite SPY authority, evaluation sessions,
partition, initial capital, and economic data policy. Its own versioned baseline
governs its strategy costs. The accepted bounded S3d2b 2024 validation run must
not be reused as a multi-year or different-partition comparator.

The secondary comparator belongs in the report-card/comparison workflow, not
as a second engine benchmark leg. Future tooling may permit factual comparison
across different strategy/lookback/lag semantics while requiring shared data,
benchmark, temporal authority, and cost-policy disclosure. V1 must not rank
strategies solely by return, select the highest-performing parameter, make
alpha claims, or infer causal superiority.

## Known Failure Modes

Strategy and research failure modes include:

- whipsaw in sideways markets;
- repeated transaction-cost drag;
- overnight and next-open gap risk;
- cash drag during rapid rebounds;
- fixed-parameter sensitivity;
- raw ex-distribution price effects in signal history;
- regime dependence;
- concentration in one retrospectively named ETF;
- benchmark-relative or prolonged QQQ buy-and-hold underperformance;
- increased turnover from full-position transitions;
- settled distribution cash becoming available to later independent entries;
- no universe-generalization claim; and
- no alpha claim.

Infrastructure and data failure modes include:

- fewer than 200 prior expected sessions;
- missing, extra, duplicated, or misordered sessions;
- QQQ/SPY session mismatch;
- temporal-component overlap or gap;
- policy, profile, or calendar mismatch;
- provenance conflict;
- unsupported or duplicate corporate actions;
- a split-affected signal window or fractional QQQ split result;
- missing payable authority;
- exact verification failure;
- nondeterminism;
- semantic artifact mismatch;
- result-reconciliation failure;
- `LATEST_KNOWN`/point-in-time authority confusion;
- incomplete full-period coverage; and
- unsupported delisting behavior.

## Research-Process Gates

### Specification To Implementation

Requires human approval of this specification and frozen strategy semantics,
dates, benchmark, cost, cash, split, catastrophic-limit, and no-sweep policies.

### Implementation To Development

Development execution requires both implementation readiness and accepted
real-data authority. Completing the engineering implementation alone does not
authorize development execution.

Implementation readiness requires synthetic tests proving exact SMA windows,
no lookahead, `T-1` to `T`-open timing, buy/full-sell/re-entry behavior,
symmetric costs, book-cost reset and re-entry, ex-date entry/exit entitlement,
outstanding-receivable preservation, split-window fail-closed behavior,
deterministic replay and identity, canonical result validation, semantic
artifacts, pure ledger mapping, and unchanged legacy S3d2b behavior.

Real-data readiness requires separately authorized provider acquisition to be
complete, deterministic publication and composition to be complete, the exact
multi-year data authority to pass verification with zero repair or date
intersection, and the human owner to accept that composed data authority.
Development must not execute before that human data-authority acceptance.

### Development To Validation

Requires a completed and accepted development experiment, all technical gates
passing, deterministic replay, semantic artifact verification, reported
catastrophic gates, human review of development behavior and failure modes, no
strategy-semantic change, and explicit human authorization to proceed to
validation when appropriate.

### Validation To Final Holdout

Requires completed validation, passed technical gates, human review, unchanged
strategy/version/parameter/cost/timing/split/cash policies, no result-based
retuning, and explicit human authorization to open the 2025 holdout.

### Final Holdout To Controlled 5–10 Experiment Batch

Requires exactly one untouched holdout execution, deterministic replay,
canonical evidence, human interpretation, no retrospective v1 retuning, and
separate human approval for the controlled batch.

## Frozen Next Implementation Sequence

After repository adoption of this already human-approved specification:

1. PR 2: deterministic provider-neutral multi-year temporal data composition.
2. PR 3: narrow long/cash QQQ SMA economic execution.
3. PR 4: economic report-card and compatible factual-comparison support plus
   controlled-validation readiness.

After those boundaries are reviewed and merged, the required progression is:

1. separate human authorization for provider acquisition;
2. deterministic acquisition, publication, and composition;
3. human data-authority acceptance;
4. development execution and human review;
5. validation execution and human review;
6. explicit holdout authorization; and
7. exactly one final holdout execution.

A generic batch runner must not be built before these gates are complete.
