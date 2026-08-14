# S3c3 Massive Source-Capture Decision

## Status

Accepted for S3c3a design. This is a documentation-only decision for Roadmap
v0.2 Slice 3. It does not implement acquisition, parsing, storage, snapshot
publication, execution, persistence, migrations, paper trading, or live trading.

## Scope

S3c3a freezes the primary development source decision and the immutable
source-capture design needed before S3c3b can implement capture and offline
adapter code. S3d1 and S3d2a are closed. S3d2b remains deferred until S3c3
produces real verified QQQ/SPY snapshot-v2 inputs.

## Owner Decision

Massive is the owner-selected primary S3c3 development source for private
research/development. The Massive capability probe made it technically suitable
for S3c3 development.

Tiingo remains a secondary independent comparison and validation source. The
platform must not splice Tiingo and Massive price history, automatically fill
Massive gaps with Tiingo, create a blended provider identity, or imply Tiingo
validates Massive merely by existing. Any future multi-source policy requires
explicit owner approval.

This decision is not a finding that Massive is commercially licensed,
enterprise approved, permanent archival legally approved, redistribution
approved, experiment ready, paper ready, or live ready. Technical source
selection and contractual/legal approval are separate authority levels.

## Probe Evidence

The owner-reviewed Massive capability probe is technical evidence only. The
probe hashes are not production snapshot-v2 identities.

| Probe | Observed facts | SHA-256 | Size |
| --- | --- | --- | --- |
| QQQ RAW bars | HTTP 200, `adjusted=false`, `o/h/l/c/v`, `vw`, `n`, and `request_id` present | `f75fce691e54d58a0b2e5b9de48626cf35f86966ebfeef5563aa91f59365cf89` | 893 |
| SPY RAW bars | HTTP 200, `adjusted=false`, `o/h/l/c/v`, `vw`, `n`, and `request_id` present | `7250165a688b33ea4296468a73418ee1e3d052971de0d4088bad760bfe9caa70` | 897 |
| QQQ dividends | 64 rows, field family observed, `declaration_date` on 43 rows | `19165e72e6e1f17db45e4ab4fac38c9b8f566ac7479894d3205093931cedfa34` | 22857 |
| SPY dividends | 78 rows, same field family, `declaration_date` on 55 rows | `3032cf5eaee82cca675ab0bd73e6f538974d08e4d53ba33fb4eba1aa2c18d1f8` | 27967 |
| QQQ splits | HTTP 200, 0 rows, `request_id` present | `7e1f533bd7544472dffba509dba1073a184c8095df664ee03c13de109788395c` | 76 |
| SPY splits | HTTP 200, 0 rows, `request_id` present | `8e9b46045b4f4e0d156259f0c7dbd7af354e6a57728640febb9e383ce69306a0` | 76 |

No probe request required retry.

The observed dividend field family was `cash_amount`, `currency`,
`declaration_date`, `distribution_type`, `ex_dividend_date`, `frequency`,
`historical_adjustment_factor`, `id`, `pay_date`, `record_date`,
`split_adjusted_cash_amount`, and `ticker`.

The official Massive documentation used for the probe identifies the current
non-deprecated stock endpoints as:

- stock custom bars: `/v2/aggs/ticker/{stocksTicker}/range/{multiplier}/{timespan}/{from}/{to}`;
- dividends: `/stocks/v1/dividends`;
- splits: `/stocks/v1/splits`.

It also identifies `split_to` as the split ratio numerator/new shares and
`split_from` as the denominator/old shares.

## Source Acquisition Architecture

The S3c3 path is:

```text
Massive API
-> exact immutable source-response capture
-> offline Massive adapter
-> provider-neutral bars / expected-session authority / corporate-action evidence
-> snapshot-v2 planner
-> snapshot-v2 immutable publication
-> S3d2a trusted QQQ/SPY execution-input pair
```

Network acquisition and normalization are separate components. Acquisition may
use the network and credentials to produce an immutable capture. Adaptation is
offline, credential-free, and consumes only immutable capture bytes and
metadata. The offline Massive adapter must never fetch missing source facts on
demand. Missing source evidence fails closed.

## Exact-Response-Byte Authority

Authoritative source capture preserves the exact Massive HTTP response body
bytes before parsing. Normalized or reserialized JSON is not raw authority.

Every source member authority records at minimum:

- exact bytes;
- SHA-256 of those exact bytes;
- `size_bytes`;
- provider;
- endpoint family and version;
- sanitized request parameters;
- ticker or instrument;
- explicit observation/capture timestamp;
- HTTP status;
- API `request_id` when present;
- media type;
- known limitations.

No credential, authorization header, bearer token, credential-bearing URL,
temporary path, runtime hostname, or repository checkout path enters source
authority.

## Capture Members

The first Massive QQQ/SPY capture has three independently verifiable logical
members per instrument:

- `BAR_RESPONSE`;
- `DIVIDEND_RESPONSE`;
- `SPLIT_RESPONSE`.

These members must not be collapsed into one reserialized JSON payload. An
empty valid split response remains an authoritative captured member and must not
be omitted because its result set is empty.

## Capture Manifest

S3c3b should introduce an operational source-capture manifest. It is capture
metadata for the S3c3 path, not necessarily a new durable research-sdk contract
with JSON schema.

Recommended manifest fields:

- `capture_format_version`;
- `provider`;
- `source_family`;
- `instrument_id`;
- `symbol`;
- `capture_observed_at`;
- `members`.

Each member should contain:

- `role`;
- `endpoint_family`;
- `endpoint_version`;
- `sanitized_source_reference`;
- `request_parameters`;
- `content_sha256`;
- `size_bytes`;
- `http_status`;
- `api_request_id` when present;
- `media_type`;
- requested temporal or filter scope;
- limitations when needed.

Member order must be canonical and deterministic. For Massive daily ETF S3c3,
the recommended order is `BAR_RESPONSE`, `DIVIDEND_RESPONSE`, then
`SPLIT_RESPONSE`.

The manifest must not contain credentials, authorization headers,
provider-approval booleans, `research_ready`, or `experiment_ready`.

## Capture Identity

The recommended source-capture identity namespace is:

- domain: `daily-market-data-source-capture`;
- identity version: `daily-market-data-source-capture-v1`.

The public capture ID should be derived from canonical capture metadata
including the ordered member identities, member hashes, and member sizes. It
must bind:

- domain;
- capture identity version;
- provider and source family;
- instrument identity;
- symbol;
- explicit capture observation timestamp;
- complete ordered member metadata;
- member content hashes;
- member sizes;
- endpoint and request semantics.

The identity must not include filesystem paths, temporary directories,
credentials, runtime hostnames, or a wall-clock timestamp generated inside
identity derivation. The observation timestamp is an explicit input. Therefore,
the same exact source bytes plus different observation/vintage metadata may
produce a different capture ID. That is intentional and matches existing
snapshot-vintage conventions.

## Bar Source-Content Hash

For the Massive path,
`DailyMarketDataBarSourceProvenanceV2.source_content_hash` binds the exact
authoritative RAW `BAR_RESPONSE` HTTP body bytes consumed by the adapter.

It does not bind normalized bars, Parquet, snapshot-v2 `bars.jsonl`, the whole
capture manifest, dividend bytes, or split bytes. The corresponding
`source_size_bytes` is the exact `BAR_RESPONSE` body byte length.

## Corporate-Action Source Authority

Massive corporate-action source authority consists of two independent exact
source members: `DIVIDEND_RESPONSE` and `SPLIT_RESPONSE`. One endpoint alone is
not complete corporate-action evidence for the current source family.

S3c3 freezes this design:

1. Retain both immutable members independently.
2. Create a deterministic canonical corporate-action source-member manifest
   from the relevant exact member metadata and hashes.
3. Serialize that manifest canonically.
4. Set `DailyMarketDataCorporateActionEvidence.source_content_hash` to the
   SHA-256 of the canonical corporate-action source manifest bytes.
5. Set `DailyMarketDataCorporateActionEvidence.source_size_bytes` to that
   manifest byte length.

This preserves the existing single `source_content_hash` and `source_size_bytes`
fields without changing the closed research-sdk contract. Do not concatenate
raw endpoint bytes without framing, and do not invent an order-dependent raw
byte concatenation authority.

Recommended corporate-action source manifest fields:

- domain and version;
- provider and source family;
- instrument identity;
- dividend member source reference, SHA-256, and size;
- split member source reference, SHA-256, and size;
- explicit common observation/capture authority when applicable.

Canonical deterministic JSON plus a final newline is preferred because it
matches the repository's existing identity helper conventions.

## Source Availability And Temporal Coverage

`source_available_at` must not be derived from `ex_dividend_date`, `pay_date`,
`record_date`, `declaration_date`, or `execution_date`. Those are economic or
source-event dates, not source-observation availability facts.

For the first historical Massive `LATEST_KNOWN` acquisition, use:

```text
source_available_at = explicit capture observation timestamp
```

This means the platform does not claim an event was knowable before the
capture. It is conservative and not point-in-time evidence.

The first historical Massive capture uses `LATEST_KNOWN` temporal coverage
unless Massive later provides independently verifiable historical
point-in-time availability evidence. Do not infer point-in-time coverage from
Massive request IDs, capture time, event declaration dates, or historical bar
dates.

## RAW Bar Policy

Massive bars must be requested with `adjusted=false`. The observed QQQ/SPY
probe confirmed `adjusted=false` in the response.

The Massive adapter must fail closed if the request authority and response
authority do not establish unadjusted RAW semantics. There is no fallback to
adjusted bars and no normalization of adjusted history into RAW.

## Dividend Mapping

Planned Massive dividend mapping to `DailyMarketDataCashDistribution`:

- Massive `id` maps to `event_id` and `source_event_reference`;
- `ex_dividend_date` maps to `ex_date`;
- `cash_amount` maps to `amount`;
- `currency` maps to `currency`;
- `pay_date` maps to `payable_date`;
- `record_date` maps to `record_date`;
- `declaration_date`, when present, maps to `announced_at` only under an
  explicit date-only timestamp policy;
- `distribution_type`, when safely mappable, maps to
  `distribution_classification`.

The adapter must not invent a missing declaration date. The current contract
allows `announced_at` to be absent. Because Massive declaration values are
date-only, the first S3c3b adapter should preserve absence for `announced_at`
unless a repository policy is introduced later for converting provider
date-only announcements into UTC datetimes without claiming false intraday
precision. `source_available_at` remains capture-observation authority, not a
declaration-date derivative.

## Split Mapping

Planned Massive split mapping to `DailyMarketDataSplit`:

- Massive `id` maps to `event_id` and `source_event_reference`;
- `execution_date` maps to `effective_date`;
- `split_to` maps to numerator/new shares;
- `split_from` maps to denominator/old shares.

The numerator/denominator mapping is based on current official Massive
documentation. The QQQ/SPY split probe returned empty result sets, so non-empty
split conversion has not yet been live-probed for those instruments. S3c3b
tests must use deterministic provider-shaped split fixtures. Empty QQQ/SPY
split responses do not block S3c3b.

## Unsupported Corporate Actions

The platform must not silently discard Massive corporate-action semantics that
cannot be mapped to current supported `CASH_DISTRIBUTION` or `SPLIT` events.
If future acquisition discovers unsupported source-event semantics, preserve
them as `DailyMarketDataUnsupportedCorporateAction` where possible. The current
research profile rejects unsupported evidence. Fail closed.

## Expected Sessions

Returned QQQ/SPY bar dates do not define the expected-session calendar. The
probe observed that QQQ and SPY returned matching dates for the small window,
but that observation is not calendar authority.

Expected sessions must come from an independent deterministic
calendar/session authority. The first real snapshots should use a deterministic
US-equity exchange calendar source with explicit:

- calendar;
- timezone;
- `session_source_id`;
- `session_source_version`.

Do not use "all dates returned by Massive" as expected-session authority. Do
not use naive weekday generation.

## Compatible QQQ/SPY Vintage

For the first QQQ/SPY pair, compatible source vintage means:

- same provider and source family;
- same acquisition run or batch;
- same explicit capture observation timestamp or same acquisition batch ID;
- same endpoint versions;
- same request-policy version;
- same temporal coverage policy;
- same expected-session authority.

It does not require Massive response bytes, request IDs, or server-side
timestamps to be identical. QQQ and SPY are distinct instruments with distinct
source bytes and provider request IDs.

## First Real Validation Range

The recommended first S3c3c real QQQ/SPY validation range is:

```text
2024-01-02 through 2024-12-31
```

This bounded one-year range provides enough sessions for real validation,
includes several QQQ/SPY distributions, remains manageable for capture and
manual review, and avoids decade-scale first acceptance before the
capture/adapter path is proven.

## Credential Boundary

`MASSIVE_API_KEY`, or any future Massive credential, is acquisition-only. It
must never be serialized into raw source bytes, capture manifests,
corporate-action source manifests, source references, snapshot manifests,
tests, logs, or Git.

Bearer-header authentication is preferred. Credential-bearing query URLs are
prohibited for authoritative acquisition.

## Capture Filesystem Layout

S3c3b should use immutable local source-capture storage independent of the
snapshot-v2 namespace. Recommended layout:

```text
<root>/
  daily-market-data-source-captures/
    <capture_id>/
      bars.json
      dividends.json
      splits.json
      capture-manifest.json
      ca-source-manifest.json
```

`bars.json`, `dividends.json`, and `splits.json` are exact Massive response
body bytes, not reserialized JSON. There must be no mutable `latest/`,
`current/`, or symbol-only overwrite path as authority.

## Publication Atomicity And Idempotency

S3c3b source-capture publication should require:

- pre-write validation;
- canonical manifest bytes;
- content-hash and size verification;
- same-filesystem staging directory;
- exclusive file writes;
- symlink rejection for managed paths and authoritative files;
- file flush and `fsync`;
- atomic directory rename with no overwrite;
- exact-byte idempotency for an existing capture;
- existing conflicting capture fails closed;
- final read-only verification.

Directory `fsync` should follow the existing snapshot local-storage posture:
required to attempt where supported, with unsupported portable errors treated
as best effort. Hostile multi-user `openat`/`O_NOFOLLOW` hardening can remain
deferred unless S3c3b explicitly expands the trust model beyond a caller-owned
cooperating local root.

## Durable Contract Decision

S3c3a does not add `ProviderApproval`, `VendorApproval`, `LicenseApproval`, or
another durable runtime approval schema. The provider decision belongs
initially in versioned documentation, capture metadata, and human review. A
durable runtime approval contract can be added later only if a concrete
consumer requires it.

## Proposed S3c3b Implementation Scope

Capture and adapter code belongs in quant-platform but should remain
independent of `backtest-engine`. The smallest S3c3b implementation should live
in `packages/research-sdk` because it feeds research-sdk daily market-data
contracts and snapshot-v2 planners without requiring engine execution code.

Recommended paths:

```text
packages/research-sdk/src/research_sdk/daily_market_data_source_capture/
  models.py
  identity.py
  serialization.py
  local.py

packages/research-sdk/src/research_sdk/daily_market_data_adapters/
  massive.py
```

S3c3b should implement only immutable capture models/identity/serialization,
local capture publication/verification, and an offline Massive adapter that
consumes capture bytes and produces provider-neutral bars plus corporate-action
evidence suitable for the existing snapshot-v2 planner. It must not implement
network acquisition, credentials, snapshot-v2 publication, S3d2a execution,
S3d2b accounting integration, persistence, or migrations.

Required future capture tests:

- exact bytes;
- deterministic member hashes;
- capture identity;
- same bytes and same metadata are idempotent;
- same bytes and new observation vintage produce a new capture identity;
- changed bytes produce a changed capture identity;
- malformed manifest fails;
- credential-bearing reference fails;
- symlink fails;
- atomic publication;
- read-only verification.

Required future Massive adapter tests:

- RAW bar mapping;
- `adjusted=true` fails;
- deterministic bars;
- duplicate date fails;
- invalid OHLC fails;
- invalid volume fails;
- dividend mapping;
- missing optional declaration allowed;
- payable date preserved;
- split ratio mapping;
- malformed split fails;
- unsupported event preserved and fails current profile;
- no network;
- no wall clock;
- deterministic output.

## Sequencing

The sequence is:

```text
S3c3a Massive decision/capture design
-> S3c3b immutable capture + offline Massive adapter
-> S3c3c first bounded real QQQ/SPY capture and snapshot-v2 publication
-> resume S3d2b economic execution integration
```

S3d2b must not begin before S3c3 is complete enough to provide trusted QQQ/SPY
snapshot-v2 execution-input bundles.

## Explicit Non-Goals

S3c3a does not implement Massive HTTP acquisition, credential handling,
immutable capture storage, adapter code, local-export parsing, snapshot-v2
generation, S3d2a execution, S3d2b execution, persistence, migrations, paper
behavior, live behavior, source licensing approval, provider redistribution
approval, or strategy validation.

## Unresolved Contractual And Commercial Questions

Unresolved questions before broader use:

- whether the subscription terms approve enterprise use;
- whether permanent archival of exact response bytes is legally approved;
- whether redistribution or team sharing is approved;
- whether any additional vendor attribution is required;
- whether a later durable provider/license approval contract is needed by a
  concrete runtime consumer.
