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

## Immutable Daily Market-Data Snapshot Planning

S3b1 adds pure immutable snapshot-support contracts in
`research_sdk.contracts.daily_market_data_snapshots`, pure identity helpers in
`research_sdk.daily_market_data.snapshot_identity`, and pure bytes planning and
verification helpers under `research_sdk.daily_market_data_storage`. This layer
does not add filesystem publication, temp directories, atomic rename behavior,
providers, S3/Athena, database persistence, calendar libraries, backtest-engine
integration, strategy logic, or real backtests.

The only S3b1 v1 curated source-byte format is canonicalizable UTF-8 JSON
Lines. Each source line must be one JSON object with exactly `session_date`,
`open`, `high`, `low`, `close`, and `volume`; dates are `YYYY-MM-DD`; OHLC
values are JSON strings parsed as Decimals; volume is a JSON integer; and nulls,
unknown keys, JSON floating-point OHLC, blank lines, comments, and malformed
JSON fail closed. Source input may omit a final newline, but canonical
published `bars.jsonl` always uses LF line endings and one final newline.
Duplicate JSON object keys fail closed instead of using last-key-wins parsing.
Non-standard JSON constants such as NaN, Infinity, and -Infinity also fail
closed.

`DailyMarketDataExpectedSessions` records the exact nonempty, unique, strictly
ascending expected session dates used for S3a quality validation, plus the
session source ID/version, calendar, and timezone. S3b1 hashes this complete
contract as session authority. It still does not infer weekdays or integrate a
calendar provider.

`DailyMarketDataSnapshotProvenance` records source and capture lineage:
creator, source dataset/version/type/reference, source byte SHA-256 and size,
parser version, temporal coverage, `as_of`, source-observed time when present,
ingestion completion, availability, vendor/license metadata when relevant,
instrument source reference, currency, known limitations, and corporate-action
evidence status. The planner receives exact source bytes and derives the source
byte hash and size from those same bytes before parsing. Source references must
not contain URI userinfo; callers and future adapters remain responsible for
sanitizing credential-bearing references.

Parser version and provenance-policy version are planner-owned facts, not
caller assertions. The S3b1 planner always persists
`daily-market-data-jsonl-parser-v1` and
`daily-market-data-snapshot-provenance-v1` for the current implementation. A
future parser or provenance-policy change must change the production constant
deliberately.

S3b1 provenance timestamps are part of snapshot vintage identity. Re-ingesting
the same bars from the same source version at a genuinely different
source/capture time normally gives the same S3a semantic market-data hash but a
different provenance hash and snapshot ID. Idempotency means the same complete
snapshot plan, not merely the same OHLCV values.

`TemporalCoverage.MIXED` is rejected by S3b1 provenance because explanatory
mixed-coverage authority is not yet modeled. Non-mixed temporal coverage values
remain structurally available when their semantics are accurate for the source.

S3b1 defines deterministic hashes for:

- the full `DailyMarketDataPolicy` contract;
- the full `DailyMarketDataExpectedSessions` contract;
- the full `DailyMarketDataSnapshotProvenance` contract.

Snapshot IDs use `daily-market-data-snapshot-v1-<sha256>` over the S3a semantic
content hash, policy hash, expected-session hash, and provenance hash. Storage
format version, output root, temporary paths, hostnames, usernames, checkout
paths, `data_root_uri`, file hashes, file sizes, and bundle-manifest bytes are
not snapshot-ID inputs. A future deterministic Parquet representation of the
same semantic/provenance snapshot can keep the same snapshot ID while having a
different storage bundle.

The S3b1 planner constructs `DataSnapshotManifest` rather than accepting a
caller-provided completed manifest. It derives market-data kind, completed
status, asset class, single-instrument universe, coverage, frequency,
portable `data_root_uri`, policy fields, SHA-256 hash algorithm, semantic
content hash, row count, currency, `file_count = 1`, and `size_bytes =
len(bars.jsonl)`. It copies validated provenance into source, temporal,
creator, license, and limitation fields. `DataSnapshotManifest` itself remains
unchanged. The portable data root is `daily-market-data/<snapshot_id>`.

An S3b1 in-memory bundle contains exactly:

- `bars.jsonl`
- `expected-sessions.json`
- `policy.json`
- `provenance.json`
- `quality-report.json`
- `snapshot-manifest.json`
- `bundle-manifest.json`

`DailyMarketDataSnapshotBundleManifest` is dataset-specific. It records the
six payload files other than itself with roles, top-level relative paths, media
types, SHA-256 byte hashes, sizes, and the bars row count. It has no self-entry
and no self-hash. `RunArtifactManifest` is not reused because run artifacts and
dataset snapshots are separate authority domains.

The pure verifier accepts a filename-to-bytes mapping, rejects missing or
unexpected files, validates storage hashes and canonical bytes, parses all
contracts, reruns S3a quality from stored bars, expected sessions, and policy,
requires the persisted quality report to match the rerun report, validates the
manifest through S3a compatibility, enforces S3b1 single-instrument
universe/currency/payload-size rules, and rederives the snapshot ID. This proves
offline internal consistency only. It does not prove external source truth, and
it is not paper-trading or live-trading authority.

Public canonical sidecar serialization revalidates contract objects through
their own JSON representation before rendering. This prevents invalid
`model_copy(update=...)` state from being serialized into authoritative bundle
bytes.

Corporate-action evidence remains explicit but not economically implemented.
S3b1 provenance supports `not_integrated`, `checked_no_events`, and
`events_present_unsupported`; no event schema or evidence sidecar is added.
Because the planner receives no authoritative corporate-action evidence bytes,
S3b1 planning only permits `not_integrated`. Checked states remain contract
vocabulary for later Slice 3 work but cannot be asserted by the current
planner. `not_integrated` must carry a known limitation stating that
corporate-action/distribution evidence is not integrated. Synthetic fixtures use
`DataSourceType.RESEARCH_GENERATED`, `TemporalCoverage.NOT_APPLICABLE`, USD
currency, and infrastructure-only limitations; they are not historical
performance evidence.

## Local Daily Market-Data Snapshot Storage

S3b2 adds operational local filesystem storage for immutable S3b1 daily
market-data snapshot bundles. It does not add or modify a contract,
`DataSnapshotManifest`, JSON schema, semantic hash, snapshot identity input,
provider adapter, network call, S3/Athena integration, database persistence,
migration, calendar provider, corporate-action event source, backtest-engine
production path, strategy, real market data, paper-trading behavior, or
live-trading behavior.

The publisher receives only a caller-owned `snapshot_root` and an already
planned `DailyMarketDataSnapshotPlan`. It first runs the pure S3b1 verifier on
`plan.as_file_map()` and requires the verified snapshot ID to equal
`plan.snapshot_id` before any filesystem mutation. Invalid or corrupted plan
state cannot create the root, `daily-market-data`, `.staging`, or any bundle
file.

The required local mapping is:

```text
<snapshot_root>/daily-market-data/<snapshot_id>/
```

This is the filesystem realization of the S3b1 portable
`data_root_uri = daily-market-data/<snapshot_id>`. The caller may pass a
relative or absolute root; S3b2 resolves it for I/O only. The root path is not
persisted in any of the seven files and is not part of snapshot identity, file
hashes, manifest content, or provenance. A complete
`daily-market-data/<snapshot_id>` directory can be copied under another root and
verified there without changing identity or manifest bytes.

S3b2 writes exactly the seven S3b1 authoritative files:

- `bars.jsonl`
- `expected-sessions.json`
- `policy.json`
- `provenance.json`
- `quality-report.json`
- `snapshot-manifest.json`
- `bundle-manifest.json`

No success marker, current/latest pointer, lock metadata, publication manifest,
repair record, or eighth sidecar is added. The exact bytes from
`plan.as_file_map()` are the storage authority. Publication uses exclusive file
creation and never deserializes, reserializes, reorders internal content,
normalizes newlines, decodes/re-encodes, or pretty-prints bundle files.

Publication stages under:

```text
<snapshot_root>/daily-market-data/.staging/<snapshot_id>.<pid>.<random>/
```

The staging directory is on the same filesystem as the final snapshot directory
so `os.rename(staging_path, final_path)` can provide atomic final visibility.
S3b2 deliberately uses `os.rename`, not `os.replace`, and does not add lock
files, global locks, database locks, or platform-specific native rename
bindings. The v1 trust model is a caller-owned cooperating local root. S3b2 does
not claim hostile-actor hard no-replace semantics against an arbitrary local
actor racing an empty destination directory into existence between precheck and
rename.

Every staged file is flushed and `fsync`ed after writing. S3b2 also attempts
directory `fsync` on the staging directory after file writes and on the
`daily-market-data` parent after final rename. Unsupported directory `fsync`
errno results are allowed as best-effort continuation; other directory `fsync`
errors fail publication. Atomic visibility and crash durability are separate:
the rename boundary prevents cooperating readers from observing a partially
written final directory, while fsync attempts improve but do not exhaustively
prove power-loss durability.

Before final rename, S3b2 reads the staged directory back, requires the exact
seven-file set with no extras, rejects symlinks and non-regular authoritative
files, runs the pure S3b1 verifier on the exact bytes, requires the verified
snapshot ID to match the plan, and requires every staged byte to equal the plan
bytes. After a successful rename, S3b2 performs required final readback
verification and exact-byte comparison again. If final verification fails after
rename, S3b2 raises a disk verification error and does not delete or repair the
published immutable directory.

Idempotency is exact-byte based. If the final snapshot already exists,
publication performs no staging or overwrite. It verifies the existing bundle,
requires the verified snapshot ID to match the requested plan, and requires all
seven authoritative bytes to equal the plan. If so, publication returns
`ALREADY_PRESENT`. Any missing file, extra file, symlink, non-regular file,
failed verification, wrong snapshot ID, or byte difference is a conflict. S3b2
does not repair, merge, overwrite, rename aside, or delete existing final
snapshots. Corrections require a new S3b1 plan and snapshot ID.

The read-only local verifier validates the S3b1 snapshot ID shape, validates the
root without creating it, resolves the fixed `daily-market-data/<snapshot_id>`
path, rejects path anomalies and symlinks, reads exactly seven regular files,
passes exact bytes to the pure S3b1 verifier, and requires the verified snapshot
ID to match the request. It never writes, creates directories, normalizes,
repairs, deletes, or cleans staging. S3b2 refuses symlinks for the root,
managed parent, staging parent, final snapshot directory, and authoritative
files. `openat`/`O_NOFOLLOW` TOCTOU hardening is deferred because S3b2 v1 is
workstation/cooperating-process infrastructure rather than a hardened
multi-user storage daemon.

S3b2 cleans up only the exact staging directory created by the current
invocation on pre-rename failure. It never scans `.staging`, deletes unrelated
staging children, or performs global orphan cleanup. Crash-created staging
directories may remain and are non-authoritative until a future explicit
maintenance command or manual cleanup handles them.

## Daily Market-Data Corporate-Action Economic Evidence

S3c1 adds pure provider-neutral corporate-action economic-evidence contracts
and a candidate daily ETF research-data profile. These contracts are additive.
They do not change `DataSnapshotManifest`, the S3b1 v1 snapshot ID projection,
the seven-file S3b1/S3b2 bundle, local storage, persistence, provider
selection, calendar-source selection, real-data ingestion, backtest-engine
accounting, or strategy behavior. No snapshot becomes research-ready in S3c1.

The corporate-action event vocabulary is intentionally narrow:

- `cash_distribution`
- `split`
- `unsupported`

`unsupported` preserves provider evidence that an unmodeled corporate action
exists. It is fail-closed evidence for later readiness/accounting decisions,
not an economic model.

Every event records a platform `event_id`, platform `instrument_id`,
credential-free `source_event_reference`, source-level
`source_available_at`, and event type. The economic/effective date and source
availability time are separate facts. Cash distributions use `ex_date` as the
economic date and require a strictly positive Decimal-compatible `amount` plus
nonblank `currency`. Splits use `effective_date`, strictly positive integer
`numerator` and `denominator`, reject bool ratio values, reject 1:1 events, and
reduce ratios for semantic hashing so `2:1` and `4:2` represent the same split
economics. Unsupported events carry provider event type and effective date but
do not model economics.

`DailyMarketDataCorporateActionEvidence` records complete checked evidence for
one `DailyMarketDataInstrument` over an explicit covered period. It records
source dataset/version/type/reference, exact source byte hash and size,
source-observed time, ingestion completion, availability, creation facts,
canonicalization version, event set, vendor/license metadata when relevant,
and known limitations. It does not embed raw provider bytes and does not derive
source hashes itself; a future adapter/capture boundary must compute those
facts from exact upstream bytes. If raw bytes cannot legally be retained, a
future source workflow must disclose the resulting audit limitation rather than
claiming equivalent reproducibility.

S3c1 uses a new evidence completeness enum:

- `checked_no_events`: the covered period was checked and the event set is
  empty.
- `checked_events_captured`: the covered period was checked and one or more
  events were captured.

Unsupported events are represented as event records, not as a completeness
state. Evidence chronology requires:

```text
source_observed_at <= ingestion_completed_at <= available_at <= created_at
```

Each event economic date must lie inside evidence coverage, every event must
match the evidence instrument ID, event IDs must be unique, and event tuples
must use canonical ordering by economic/effective date, event type, and event
ID. This is deterministic contract validation only; fuzzy provider-event
deduplication is not attempted.

The corporate-action semantic content hash uses the
`daily-market-data-corporate-actions-v1` domain/version. It binds instrument
identity, coverage start/end, and canonical event economics. It excludes event
IDs, source references, and source timestamps because those are lineage facts
retained in the full evidence contract. A checked empty event set still hashes
the instrument and coverage dates, so different no-event windows have
different semantic hashes. S3c2 will decide how this semantic hash and the full
evidence contract are bound into a versioned market-data snapshot identity.

`DailyMarketDataResearchProfile` is a deterministic policy definition, not an
approval record. The first candidate profile is ETF/daily/USD, RAW tradable
OHLCV, `explicit_cash` distributions, `latest_known` temporal coverage for
ordinary real historical captures unless an official PIT source is later
verified, `next_expected_session` daily-bar availability, checked
corporate-action evidence, cash-distribution and split support, no unsupported
events, fixed preselected ETF instruments, no historical constituent
discovery, no survivorship-free security-selection claim, and full instrument
coverage for the tested period. Provider choice, calendar authority, licensing
acceptance, paid data spend, and any financial conclusion remain outside the
contract.

`validate_daily_market_data_economic_evidence(...)` validates only
evidence/profile coherence across a supplied daily market-data policy,
expected sessions, v1 snapshot provenance, quality report, corporate-action
evidence, and research profile. A successful result does not establish
snapshot research readiness, experiment readiness, benchmark compatibility,
provider approval, license approval, backtest accounting support, strategy
validity, paper-trading readiness, or live-trading readiness. Existing S3b1 v1
provenance may still say `not_integrated`; separate S3c1 evidence does not
retroactively alter v1 snapshot identity.

## Daily Market-Data Snapshot V2

S3c2a adds a pure immutable snapshot-v2 authority layer. It freezes how
S3c1 corporate-action evidence is bound into daily market-data snapshot
identity, but it does not add filesystem publication, provider acquisition,
source-capture storage, persistence, profile compatibility, readiness
approval, backtest-engine accounting, or strategy behavior.

Snapshot-v2 IDs use:

```text
daily-market-data-snapshot-v2-<sha256>
```

over exactly:

- S3a daily bar semantic content hash;
- unchanged `DailyMarketDataPolicy` hash;
- unchanged `DailyMarketDataExpectedSessions` hash;
- complete `DailyMarketDataBarSourceProvenanceV2` hash;
- S3c1 corporate-action economic semantic hash;
- complete corporate-action evidence authority hash.

The bundle representation version is
`daily-market-data-snapshot-bundle-v2` and is not a natural identity input.
Storage byte hashes, filesystem roots, staging paths, bundle-manifest bytes,
compression, and local publication details remain outside snapshot-v2 natural
identity.

`DailyMarketDataBarSourceProvenanceV2` is a new bar-only source/capture
contract. It preserves the useful bar source fields from v1 provenance but
omits every corporate-action evidence field. This avoids carrying v1
`not_integrated` corporate-action status into a snapshot version that binds
separate checked corporate-action evidence. The v2 bar provenance contract
rejects the exact legacy limitation
`corporate-action/distribution evidence is not integrated`.

Snapshot-v2 planning separates canonical bar input bytes from optional exact
upstream bar-source authority. `source_bytes` always contains canonicalizable
daily-bar JSONL and alone drives parsing, quality validation, semantic bar
content, and the canonical `bars.jsonl` payload. When no separate authority is
supplied, provenance hash/size and parser version retain the historical
canonical-JSONL behavior. When a `DailyMarketDataBarSourceAuthorityInputV2` is
supplied, the planner derives provenance hash/size from its exact `content`
bytes and records its `parser_version`; callers cannot supply hashes or sizes.
Zero-length authority content remains valid at this generic layer because the
durable provenance contract permits a zero-byte source; source-specific
capture and adapter boundaries determine whether such evidence is usable.
This operational input adds no durable contract, file, identity version, or
bundle-format field and performs no source acquisition or I/O.

S3c2a uses exactly eight authoritative files:

- `bars.jsonl`
- `expected-sessions.json`
- `policy.json`
- `bar-provenance.json`
- `quality-report.json`
- `corporate-action-evidence.json`
- `snapshot-manifest.json`
- `bundle-manifest.json`

There is no `provenance.json`, `corporate-actions.jsonl`, profile file,
readiness file, latest/current marker, or local filesystem publication in
S3c2a. The bundle manifest records the first seven payload files and excludes
itself. Only the bars file entry carries `row_count`; sidecars do not.

The corporate-action semantic hash remains the S3c1
`daily-market-data-corporate-actions-v1` economic projection. S3c2a adds a
separate `daily-market-data-corporate-action-evidence-authority-v1` hash over
the complete validated `DailyMarketDataCorporateActionEvidence` contract.
Changing only source reference, source version, source content hash, event
`source_available_at`, source observation, availability, or creation facts
changes the evidence-authority hash and snapshot-v2 ID without changing the
economic semantic hash.

`DataSnapshotManifest` remains unchanged. In v2, its source fields describe the
primary bar dataset: bar source dataset/version/type, bar source observation,
bar vendor/license fields, bar currency, and bar creator. Corporate-action
source authority is represented in `corporate-action-evidence.json` and bound
through the v2 hashes and snapshot ID. Manifest `content_hash`, `row_count`,
`file_count`, and `size_bytes` remain bars-only payload facts.

S3c2a deterministic manifest timing uses component maxima:

```text
ingestion_completed_at = max(bar ingestion, corporate-action ingestion)
available_at = max(bar availability, corporate-action availability)
created_at = max(bar created_at, corporate-action created_at)
as_of = max(bar as_of, corporate-action source_observed_at)
```

No runtime clock is used for persisted v2 facts. The v2 `as_of` means combined
bound source-vintage cutoff. It is not the final historical session date,
event availability time, or physical planning wall-clock time.

Snapshot-v2 planning requires passing S3a bar quality, expected-session
calendar/timezone coherence with policy, bar coverage not exceeding bar
provenance `as_of`, full instrument equality between bars and corporate-action
evidence, and corporate-action evidence coverage covering the expected bar
session range. Unsupported corporate-action events may be preserved in v2
because profile compatibility is deferred. S3c2a answers what exact evidence
exists, not whether the evidence is acceptable under a research profile.

Pure v2 verification requires the exact eight-file bundle, strict canonical
bytes, rederived bar/policy/session/bar-provenance/corporate-action hashes,
rederived snapshot-v2 ID, exact bundle-manifest coherence, and exact
`DataSnapshotManifest` boundary semantics. It performs no filesystem,
provider, network, database, or backtest-engine I/O.

## Local Daily Market-Data Snapshot-V2 Storage

S3c2b1 adds operational local filesystem publication and readback for already
planned S3c2a snapshot-v2 bundles. It adds no durable contract, JSON schema,
snapshot identity input, bundle-v2 file, provider adapter, real-data
acquisition, source archive, database persistence, migration, backtest-engine
accounting, strategy logic, profile compatibility, research-readiness claim,
paper-trading behavior, or live-trading behavior.

The implementation is intentionally additive in
`research_sdk.daily_market_data_storage.local_v2`. The closed S3b2 v1
`local.py` behavior remains separate, and callers choose explicit APIs rather
than a version dispatcher:

- v1: `publish_local_daily_market_data_snapshot(...)` and
  `verify_local_daily_market_data_snapshot(...)`
- v2: `publish_local_daily_market_data_snapshot_v2(...)` and
  `verify_local_daily_market_data_snapshot_v2(...)`

Both versions use the same physical namespace:

```text
<snapshot_root>/daily-market-data/<snapshot_id>/
```

This matches the portable `DataSnapshotManifest.data_root_uri` convention.
Version separation comes from the required snapshot ID prefixes, including
`daily-market-data-snapshot-v2-<64 lowercase hex>` for the v2 local APIs.
S3c2b1 also retains the shared private staging namespace:
`<snapshot_root>/daily-market-data/.staging/`.

V2 local storage publishes exactly:

- `bars.jsonl`
- `expected-sessions.json`
- `policy.json`
- `bar-provenance.json`
- `quality-report.json`
- `corporate-action-evidence.json`
- `snapshot-manifest.json`
- `bundle-manifest.json`

No `provenance.json`, `corporate-actions.jsonl`, profile file, compatibility
file, readiness marker, success marker, latest/current pointer, lock metadata,
or publication manifest is added. The exact bytes from
`DailyMarketDataSnapshotPlanV2.as_file_map()` are the storage authority.

Before any filesystem mutation, the publisher verifies the plan bytes through
`verify_daily_market_data_snapshot_bundle_v2(...)`, requires the verified
snapshot ID to equal the plan ID, and validates the v2 snapshot-ID shape.
Invalid plan state cannot create the root, managed parent, staging namespace,
staging directory, or authoritative files.

Publication mirrors the S3b2 immutable local-storage mechanics: caller-owned
root, symlink refusal for managed paths and authoritative files, private
same-filesystem staging, exclusive file creation, exact planned bytes, file
flush and `fsync`, staging-directory `fsync` attempt, staged v2 verification
and byte comparison, `os.rename` without overwrite or copy fallback, managed
parent `fsync` attempt, final read-only v2 verification, and final exact-byte
comparison. Unsupported directory `fsync` errno values remain best-effort;
other directory `fsync` errors fail publication.

Idempotency is exact-byte based. If the requested v2 final directory already
exists, publication verifies it as v2 and returns `ALREADY_PRESENT` only when
all eight authoritative bytes exactly match the requested plan. Missing files,
extra files, corrupt files, symlinks, non-regular files, failed v2
verification, wrong snapshot ID, or byte differences are immutable conflicts.
The publisher never overwrites, repairs, normalizes, merges, deletes, or
renames aside an existing final snapshot.

The read-only v2 local verifier validates the v2 ID, validates the existing
root, resolves `daily-market-data/<snapshot_id>`, reads exactly the eight
regular authoritative files, passes those bytes to the pure v2 verifier, and
requires the verified snapshot ID to match the request. It creates, rewrites,
repairs, deletes, and cleans nothing. The local filesystem trust model remains
the S3b2 cooperating-root model, not a hardened untrusted multi-tenant
filesystem sandbox.

S3c3c2 exposes that read as the frozen operational
`LocalDailyMarketDataSnapshotReadbackV2` through
`load_local_daily_market_data_snapshot_v2(...)`. The result contains the
requested and verified snapshot ID, resolved immutable snapshot directory,
the exact eight-file `Mapping[str, bytes]` read from disk, and the
`VerifiedDailyMarketDataSnapshotV2` derived from that same immutable mapping.
The mapping is caller-immutable, its values remain exact immutable `bytes`,
and no file is reopened to construct the result. This is not a durable
Pydantic contract and adds no schema, fixture, sidecar, identity field, or
bundle-format field.

`verify_local_daily_market_data_snapshot_v2(...)` keeps its existing signature
and return type as a compatibility wrapper over the loader. Final CREATED and
ALREADY_PRESENT publication verification now compare the loader's already
verified exact byte mapping directly with the plan, eliminating a second
authoritative-directory read without changing publication, idempotency, or
conflict semantics. Readback has no lookback, lag, calendar, acquisition, or
leakage semantics: it consumes only an existing local root and snapshot ID,
preserves stored bytes exactly, and makes no research-readiness or S3d2a
execution claim.

If publication fails before final rename, S3c2b1 best-effort removes only the
staging directory created by the current invocation. If final verification
fails after a successful rename, it raises a disk verification error and
preserves the final directory for diagnosis.

## Daily Market-Data Snapshot-V2/Profile Compatibility

S3c2b2 adds no durable contract or JSON schema. It adds a pure operational
profile hash and a verified snapshot-v2/profile compatibility helper. The
profile hash domain is `daily-market-data-research-profile`; the identity
version is `daily-market-data-research-profile-hash-v1`. The hash payload
wraps the complete revalidated `DailyMarketDataResearchProfile` JSON model
dump. It does not omit `profile_id`, does not create a selective semantic
projection, and does not modify snapshot-v1 or snapshot-v2 identity.

Profile identity remains separate from snapshot identity. Snapshot-v2 identity
continues to bind the immutable bars, policy, expected sessions, bar
provenance, corporate-action economics, and corporate-action evidence
authority. Profile identity binds the exact policy requirements being
requested. Compatibility evaluates whether one verified snapshot-v2 satisfies
the machine-evaluable data-side requirements of one exact profile. It does not
write a sidecar, alter local storage, alter bundle-v2, or require filesystem
publication.

The v2 compatibility API accepts only `VerifiedDailyMarketDataSnapshotV2` and
`DailyMarketDataResearchProfile`. Callers should obtain the verified snapshot
from `verify_daily_market_data_snapshot_bundle_v2(...)` or
`verify_local_daily_market_data_snapshot_v2(...)`. Compatibility performs a
runtime v2 type check and revalidates the research profile. It does not rerun
bundle verification, recompute snapshot-v2 IDs or component hashes, read
files, call providers, query networks, or persist results. A manually
constructed `VerifiedDailyMarketDataSnapshotV2` object is outside the normal
verifier-produced trust path.

The operational compatibility result contains exactly: `snapshot_id`,
`profile_id`, `profile_hash`, `profile_policy_version`, `instrument_id`,
`unsupported_event_count`, and
`required_daily_bar_availability_policy`. It intentionally has no
`research_ready`, `experiment_ready`, `approved`, or `leakage_safe` field.
Incompatibility raises a deterministic fail-closed compatibility error rather
than returning a partial pass.

The snapshot-evaluable checks cover policy asset class, frequency, adjustment
policy, distribution treatment, calendar, timezone, universe-membership policy,
survivorship policy, and delisting policy; quality PASS and coherent
single-instrument facts; bar currency and temporal coverage; expected-session
calendar, timezone, session source ID, and session source version;
corporate-action evidence coverage over the quality expected-session range;
allowed evidence completeness; unsupported-event fail-closed behavior;
supported corporate-action event types; and cash-distribution currency.

`corporate_action_coverage_requirement` is bound into profile identity as free
text but is not parsed or interpreted as executable logic. Coverage
compatibility is enforced from structured
`corporate_action_evidence.coverage_start_date`,
`corporate_action_evidence.coverage_end_date`,
`quality_report.expected_start_date`, and
`quality_report.expected_end_date`. Future multiple executable coverage modes
should be modeled as structured versioned policy, not prose interpretation.

`next_expected_session` is carried in the result as the required daily-bar
availability policy and a downstream obligation. S3c2b2 does not prove a
backtest or strategy consumed each session's OHLCV no earlier than the next
expected session. It also does not prove corporate-action accounting,
benchmark compatibility, provider approval, license approval, source factual
correctness, experiment readiness, paper-trading readiness, or live-trading
readiness.

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
