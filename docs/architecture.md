# Architecture

## Current Phase

Phase 1A - Reproducibility Foundation Complete.

Phase 1B - Research Workflow Layer is next. Current roadmap details live in
`docs/roadmap-v0.2.md`.

The platform remains research-only. One bounded QQQ/SPY 2024 `LATEST_KNOWN`
economic execution has completed human-accepted infrastructure validation; this
does not establish general production-data research readiness, paper-trading
readiness, or live-trading readiness.

## Existing Structure

The repository now contains implemented reproducibility infrastructure and
several scaffold-only areas.

Implemented:

- `packages/research-sdk`: immutable contracts, schema exports, persistence
  helpers, PostgreSQL repository writes, and completed-experiment recording.
- `packages/backtest-engine`: deterministic synthetic ETF infrastructure plus
  pure snapshot-v2 QQQ/SPY economic execution, artifact generation and semantic
  verification, and pure backtest-to-ledger mapping.
- `infra/db`: Alembic migrations and local PostgreSQL support.
- Deterministic synthetic and snapshot-v2 economic ETF artifacts for the
  required run artifact set; economic runs add a corporate-action audit.
- Completed-experiment ledger recording through a caller-owned transaction.
- Hosted CI and PostgreSQL smoke coverage.

Scaffold-only or deferred:

- `apps/api`
- `apps/web`
- `apps/worker`
- `apps/mcp-server`
- `packages/data-engine`
- `packages/feature-store`
- `packages/portfolio-engine`
- `packages/execution-engine`
- `packages/agent-tools`
- strategy families
- production research workflows

## Planned Responsibilities

- `apps/api`: scaffold-only future service API for research metadata and
  platform workflows.
- `apps/web`: scaffold-only future web UI for experiment review, reports, and
  approvals.
- `apps/worker`: scaffold-only future asynchronous jobs for data validation,
  backtests, and reports.
- `apps/mcp-server`: scaffold-only future agent-facing tool surface for
  controlled platform access.
- `packages/research-sdk`: implemented shared contracts, schema export,
  persistence, completed-experiment recording boundaries, and durable
  deterministic report-card persistence. It does not yet provide broad
  read/query services, batch orchestration, or approval-workflow authority.
- `packages/data-engine`: scaffold-only future data ingestion, validation, and
  snapshot logic.
- `packages/feature-store`: scaffold-only future feature definitions and
  point-in-time materialization.
- `packages/backtest-engine`: partially implemented deterministic
  research-engine execution for the synthetic fixture baseline and the bounded
  snapshot-v2 QQQ/SPY economic baseline. It includes exact S3d2a pair
  validation, raw-price explicit corporate-action accounting, QQQ integer and
  SPY fractional economics, explicit costs, deterministic identity, local
  artifact generation and semantic verification, and pure pair-ledger mapping.
  It does not own SQLAlchemy, Postgres, experiment-ledger transactions, API
  workflows, paper trading, live trading, broker integrations, or performance
  claims.
- `packages/portfolio-engine`: scaffold-only future portfolio construction and
  risk calculations.
- `packages/execution-engine`: reserved and inactive until later phases; no
  paper trading execution, live trading implementation, broker integration, or
  account-specific configuration is allowed in the current roadmap.
- `packages/agent-tools`: scaffold-only future safe automation helpers for
  agents.
- `strategies/*`: scaffold-only future strategy families by asset class or
  horizon.
- `research/hypotheses`: written research hypotheses before implementation.
- `research/notebooks`: exploratory notebooks; not authoritative experiment records.
- `research/reports`: reviewed research outputs and summaries.
- `infra/db`: implemented PostgreSQL ledger migrations, local disposable
  PostgreSQL Compose support, and migration configuration.
- `infra/docker`: future local development containers beyond the current
  database-specific support.
- `infra/terraform`: reserved for later infrastructure definitions.
- `docs`: source of truth for architecture, contracts, risk rules, and operating model.

## Research Lifecycle

Accepted research must follow this lifecycle:

1. Hypothesis: define the research question, asset universe, expected behavior, failure modes, and validation plan.
2. Config: write a reproducible run configuration with benchmark, costs, slippage, lookback, lag, and leakage assumptions.
3. Data snapshot: reference point-in-time input data with a snapshot manifest.
4. Feature snapshot: reference derived features and their availability assumptions when applicable.
5. Backtest: execute deterministic research code with captured Python version, lockfile hash, seed, and run command.
6. Artifacts: write the required artifact bundle and artifact manifest.
7. Ledger: register the run, artifacts, assumptions, review status, and integrity hashes.
8. Report: write deterministic report-card evidence and supporting failure
   analysis. The current `research_note.md` file is a generated run artifact;
   a persisted `ResearchNote` contract is a separate human-reviewed
   interpretation record.
9. Review decision: record human review metadata and accepted, rejected, invalid, or superseded status.

Notebooks are exploratory. Notebook-derived charts or tables cannot be cited as
accepted results unless reproduced by versioned code with a ledger `run_id` and
artifact manifest.

## Historical Phase 0 Foundation

The original Phase 0 objectives established the repository foundation,
scaffold, documentation, ledger contract direction, data contract direction,
agent rules, and trading-risk policy. Historical acceptance details remain
preserved in `docs/roadmap.md`.

Those objectives have been superseded by the Phase 1A/Phase 1B roadmap
structure in `docs/roadmap-v0.2.md`.

## Boundary Decisions

- The platform is research-first. Paper trading and live trading are later phases.
- Notebooks may support exploration, but accepted results must be reproducible from versioned code, config, data snapshots, and run artifacts.
- Backtests must include benchmark comparison, transaction cost assumptions, slippage assumptions, and leakage notes.
- The first deterministic ETF backtest is infrastructure validation only. It
  uses version-controlled synthetic fixture data, not historical market data or
  a production data source, and it must not be used for investment conclusions.
- Backtest engine core models and execution code remain independent of
  persistence repositories and transaction handling. The deterministic ETF
  ledger integration is a separate mapping boundary that verifies fixture and
  artifact bytes read-only, constructs immutable ledger records from stable
  contracts only, and leaves completed-bundle construction and recording to the
  application boundary.
- The platform must support multiple asset classes without embedding a
  preferred broker, exchange, or data vendor in the current roadmap.
- Agents can implement and test but cannot approve financial conclusions, risk exceptions, paper trading, or live trading.
- Formal approval can only be granted by Po-Chun Huang for now.

## Daily Market-Data Policy Boundary

Slice 3 introduces a provider-neutral daily market-data policy layer in
`research_sdk.contracts.daily_market_data` and pure helpers under
`research_sdk.daily_market_data`. This layer is additive around
`DataSnapshotManifest`; the generic durable snapshot envelope is unchanged.

The terminology is:

- Raw source evidence: provider or source output preserved as received for
  provenance.
- Curated dataset: deterministically normalized daily bars suitable for
  research validation.
- Research snapshot: immutable selected curated content referenced by an
  experiment through `DataSnapshotManifest`.

The S3a policy supports ETF daily execution-bar validation only. It records the
asset class, frequency, calendar, timezone, adjustment policy, distribution
treatment, corporate-action policy, universe-membership policy, survivorship
policy, delisting policy, canonicalization version, and quality policy version.
It does not choose a provider, calendar library, storage backend, benchmark
calculation, strategy, parameter set, or real experiment.

Canonical daily market-data content hashes are semantic SHA-256 hashes over the
platform instrument reference and canonical daily bars sorted by session date
and row content. The hash excludes provider name, source URI, storage URI,
retrieval timestamps, policy ID, quality status, file bytes, Parquet metadata,
strategy, benchmark, costs, and slippage. File-byte and storage-integrity hashes
remain separate metadata concerns for later snapshot creation work.

Quality validation is deterministic and pure. The caller supplies nonempty,
unique expected session dates; S3a canonicalizes valid caller order but does not
infer weekdays, use a calendar library, consult system locale, call a provider,
read files, inspect object storage, or open a database. For ETF daily v1,
duplicate sessions, missing expected sessions, unexpected sessions, and
zero-volume sessions are fatal. Quality report fatal codes are exact derived
facts, warnings are empty in S3a v1, and `duplicate_row_count` records physical
duplicate rows beyond the first row for each duplicated session date. The
quality report also records expected coverage start/end, and manifest
compatibility requires `DataSnapshotManifest.time_range` to match that coverage.
The service never forward-fills missing bars or synthesizes prices.

S3a manifest compatibility is intentionally single-instrument: the manifest's
explicit symbols must be exactly the one quality-report symbol, and
`row_count` means one observed daily bar row for that instrument. Multi-symbol
curated snapshots are deferred. Current `AssetUniverseReference` cannot prove
the daily-market-data `instrument_id` or venue, so those remain policy-layer
facts until a later identity/reference contract extends the manifest boundary.

The intended auditable economic direction for the first fully meaningful daily
ETF research path remains raw OHLCV plus explicit corporate-action and
distribution evidence with explicit cash distributions. Total-return-adjusted
series are not accepted as tradable execution OHLC in S3a. If a future selected
window contains an unsupported split or corporate action, the real-data workflow
must fail closed until support exists.

Passing `DailyMarketDataQualityReport` is necessary but not sufficient to call a
dataset real historical research evidence. Provider provenance, immutable
snapshot creation, source licensing, and durable storage remain later S3 work.
Historical backtest evidence still does not imply paper-trading or live-trading
authority.

For comparable QQQ strategy runs, the intended structured report-card benchmark
remains SPY under one explicit economic return policy. QQQ buy-and-hold should
be recorded as a separate baseline experiment/run and compared through C2b, not
used to replace the shared `BenchmarkReference`.

## Daily Market-Data Snapshot Planning

Slice 3 S3b1 adds a pure immutable snapshot-planning layer around the S3a daily
market-data authority. It does not publish files, create temp directories,
rename paths atomically, call providers, read storage, write persistence rows,
modify the backtest engine, or establish real historical research authority.

The S3b1 curated source format is canonicalizable UTF-8 JSON Lines: one daily
bar object per line, exact OHLCV fields, `YYYY-MM-DD` session dates, Decimal
OHLC strings, integer volume, no unknown keys, no comments, no nulls, and no
JSON floating-point OHLC values. The planner parses the exact source bytes,
hashes those same bytes for provenance, then renders canonical published
`bars.jsonl` bytes with sorted rows, deterministic keys, canonical Decimal
strings, LF line endings, and one final newline. Duplicate JSON object keys and
non-standard JSON constants such as NaN and Infinity fail closed; source
evidence is never interpreted with last-key-wins JSON behavior. Source row order
may differ from canonical storage order; that preserves the same S3a semantic
content hash while changing source-byte provenance and therefore the S3b1
snapshot vintage.

S3b1 keeps identities separate. The S3a semantic content hash remains the
market-data content authority. S3b1 adds deterministic hashes for the complete
daily-market-data policy contract, the exact expected-session authority
contract, and the full source/capture provenance contract. Snapshot IDs use:

```text
daily-market-data-snapshot-v1-<sha256>
```

over the semantic content hash, policy hash, expected-session hash, and
provenance hash. Provenance timestamps are part of the provenance hash, so a
later ingestion can produce a distinct immutable snapshot vintage even when
OHLCV values are unchanged. Output roots, temporary paths, hostnames, local
usernames, repository checkout paths, `data_root_uri`, storage format version,
file byte hashes, bundle-manifest bytes, file counts, and sizes are excluded
from snapshot identity.

Parser version and provenance-policy version are planner-owned facts. Callers
cannot assert a parser version or provenance-policy version different from the
S3b1 code path that actually parsed the source bytes and built the persisted
provenance contract. Public canonical sidecar serialization revalidates the
supplied contract through its own JSON representation before rendering, so
copied Pydantic model state that bypassed validators cannot be persisted as
authoritative bundle bytes.

The S3b1 `DataSnapshotManifest.data_root_uri` is the portable relative logical
path `daily-market-data/<snapshot_id>`. S3b2 will resolve that under a caller
owned local snapshot root. No custom URI scheme and no absolute developer path
is introduced. `DataSnapshotManifest.file_count` and `size_bytes` describe only
the curated data payload, currently `bars.jsonl`; the dataset-specific bundle
manifest records sidecar file hashes and sizes.

An S3b1 bundle plan contains exactly `bars.jsonl`, `expected-sessions.json`,
`policy.json`, `provenance.json`, `quality-report.json`,
`snapshot-manifest.json`, and `bundle-manifest.json`. The bundle manifest is a
dataset-specific contract, not `RunArtifactManifest`; it records payload file
roles, relative paths, media types, byte SHA-256 hashes, sizes, and the bars
row count. It deliberately omits a self-entry and self-hash for
`bundle-manifest.json`.

In-memory readback verification accepts only a mapping of filenames to bytes.
It verifies the exact file set, storage hashes, canonical JSON/JSONL bytes,
policy/session/provenance hashes, S3a semantic hash, rerun quality evidence,
`DataSnapshotManifest` compatibility, S3b1 single-instrument universe rule,
portable data-root rule, payload size semantics, and snapshot ID coherence. It
can prove internal bundle consistency offline, but it cannot prove that
recorded upstream source facts are truthful when raw source evidence is not
embedded, and it is not cryptographic authenticity against an attacker who can
rewrite the whole unanchored bundle.

Corporate-action/distribution evidence remains an explicit boundary. S3b1 does
not add a corporate-action event schema, evidence sidecar, source bytes, or
economic accounting. The provenance contract can represent future
`checked_no_events` and `events_present_unsupported` states, but the S3b1
planner only publishes `not_integrated` because it has no dedicated
corporate-action evidence input to verify checked claims. The synthetic S3b1
fixture uses `not_integrated` and must disclose that corporate-action/
distribution evidence is not integrated. A future real RAW plus explicit-cash
research gate must reject `not_integrated` until event evidence and accounting
support are deliberately implemented. `TemporalCoverage.MIXED` is deferred in
S3b1 because explanatory mixed-coverage authority is not yet modeled. Currency
is explicit in provenance and the manifest; the synthetic US ETF fixture uses
USD, but the core contracts remain provider and country neutral.

## Daily Market-Data Local Snapshot Storage

Slice 3 S3b2 adds local filesystem publication and read-only verification for
already planned S3b1 daily market-data snapshot bundles. It is operational
storage code only. S3b1 still owns identity, deterministic bytes, bundle
filenames, `DataSnapshotManifest` contents, and pure semantic verification.
S3b2 does not add a durable contract, schema export, provider, calendar source,
corporate-action event data, database persistence, backtest-engine integration,
strategy behavior, real historical evidence, paper-trading authority, or
live-trading authority.

Publication accepts a caller-owned `snapshot_root` and an already valid
`DailyMarketDataSnapshotPlan`. Before creating the root, managed parent,
staging directory, or any file, S3b2 verifies `plan.as_file_map()` through the
pure S3b1 verifier and requires the verified snapshot ID to equal
`plan.snapshot_id`. Invalid copied or corrupted plan state therefore produces
no filesystem mutation.

The local path mapping is fixed:

```text
<snapshot_root>/daily-market-data/<snapshot_id>/
```

This corresponds exactly to the portable S3b1
`DataSnapshotManifest.data_root_uri` value `daily-market-data/<snapshot_id>`.
The caller may provide a relative or absolute root; S3b2 normalizes it for I/O,
but the physical root path never enters snapshot identity, bundle bytes,
manifests, or hashes. Published bundles can be moved under another caller-owned
root and reverified by resolving the same relative mapping there.

S3b2 publishes exactly the seven S3b1 files: `bars.jsonl`,
`expected-sessions.json`, `policy.json`, `provenance.json`,
`quality-report.json`, `snapshot-manifest.json`, and
`bundle-manifest.json`. There is no `_SUCCESS`, `READY`, `COMPLETED`, `latest`,
`current`, lock metadata, publication manifest, or eighth sidecar. The
publisher writes the exact bytes from the plan, using exclusive file creation,
without deserializing, reserializing, newline normalization, or pretty-printing.

Staging lives in the private operational namespace:

```text
<snapshot_root>/daily-market-data/.staging/<snapshot_id>.<pid>.<random>/
```

Staging randomness is only an operational collision-avoidance detail and never
enters persisted files or research identity. S3b2 removes only the exact staging
directory created by the current invocation on pre-publication failures. It
does not scan `.staging`, delete stale siblings, or implement orphan cleanup;
hard-crash staging directories may remain for future explicit maintenance or
manual cleanup.

Publication flushes and `fsync`s every staged file after writing. It also
attempts to `fsync` the staging directory after all files are written and the
`daily-market-data` parent after final publication. Unsupported directory
`fsync` errors are treated as best-effort continuation; other directory `fsync`
errors fail publication. Atomic visibility is required, and the fsync attempts
improve crash durability, but S3b2 does not claim exhaustive power-loss
durability guarantees.

After writing staging files, S3b2 reads the exact staged directory back, rejects
missing or extra entries, rejects symlinked or non-regular authoritative files,
runs the pure S3b1 verifier, requires the staged snapshot ID to equal the plan
ID, and requires every staged byte to equal the plan bytes. Only then does it
publish with `os.rename(staging_path, final_path)`. It deliberately does not
use `os.replace`, platform-specific `renameat2` bindings, lock files, global
locks, or database locks. The v1 trust model is a caller-owned, cooperating
local snapshot root; it does not claim hostile-actor hard no-replace semantics
against an arbitrary local actor racing an empty destination directory into
existence between the precheck and rename.

Existing final snapshots are immutable. If the final path already exists,
publication never overwrites it. S3b2 verifies the existing bundle and requires
exact byte-for-byte equality with the requested plan before returning
idempotent `ALREADY_PRESENT`. Semantic equivalence alone is insufficient. Any
missing file, extra file, symlink, non-regular file, verification failure, wrong
snapshot ID, or same-ID byte difference is a conflict; S3b2 does not repair,
replace, merge, rename aside, or delete the published path. Concurrent
cooperating publication of the same snapshot is handled by independent staging:
one `os.rename` creates the final directory, and a loser that sees an expected
destination collision verifies exact final bytes and returns `ALREADY_PRESENT`
or reports conflict. Different snapshot IDs publish independently.

After a successful rename, S3b2 performs required final on-disk verification
through the read-only local verifier and again requires exact final bytes to
match the plan. If this rare post-rename verification fails, S3b2 raises a disk
verification error and does not delete or repair the final directory; an
unexpectedly bad immutable published path requires manual investigation.

The read-only local verifier validates the S3b1 snapshot ID shape, validates
the supplied root without creating anything, resolves
`daily-market-data/<snapshot_id>`, rejects symlink or path anomalies, reads only
the exact seven regular authoritative files, passes those exact bytes to the
pure S3b1 verifier, and requires the verified snapshot ID to match the request.
It never creates, rewrites, repairs, normalizes, deletes, or cleans up files.
S3b2 refuses symlinks for the snapshot root, `daily-market-data`, `.staging`,
final snapshot directories, and authoritative files. TOCTOU hardening with
`openat`/`O_NOFOLLOW` is intentionally out of scope for this
workstation/cooperating-process v1 trust model.

## Daily Market-Data Economic Evidence Semantics

Slice 3 S3c1 freezes pure provider-neutral corporate-action economic evidence
semantics and a candidate versioned daily ETF research-data profile. It does
not add a provider, select a vendor, ingest real data, call a network API,
change S3b1 snapshot identity, add `corporate-actions.jsonl`, change S3b2
local storage, write persistence rows, modify the backtest engine, implement
corporate-action accounting, or declare any snapshot research-ready.

The long-term complete daily ETF economic policy remains raw tradable OHLCV
plus explicit split evidence, explicit cash-distribution evidence, and later
backtest accounting for split quantities and cash entitlements. S3c1 defines
the evidence language only. S3c2 must bind this evidence into a new versioned
snapshot identity and readiness gate before any real snapshot can be called
research usable.

S3c1 corporate-action events are limited to `cash_distribution`, `split`, and
`unsupported`. Unsupported events intentionally preserve fail-closed evidence
for provider event types that the platform cannot economically model. Event
economic dates and source availability are distinct: a cash distribution uses
`ex_date`, a split or unsupported event uses `effective_date`, and every event
also records `source_available_at`, the earliest recorded source-evidence
availability time supplied by the captured source. Source availability is not
inferred from ex-date, effective date, payment date, or historical bar date.

`DailyMarketDataCorporateActionEvidence` records complete checked evidence for
one platform instrument over one explicit coverage period from one source
capture/vintage. It records source dataset/version/type/reference, source
hash/size, source observation, ingestion, availability, creation facts,
canonicalization version, events, and limitations. It does not embed raw
provider bytes; future adapters must derive source hashes and sizes from exact
source bytes. Raw source-capture storage and retention semantics remain
deferred until an approved provider/export and license posture exist.

The new evidence completeness states are `checked_no_events` and
`checked_events_captured`. Unsupported event support is derived from event
contents rather than from completeness state, keeping evidence completeness
separate from engine economic capability. The v1
`DailyMarketDataSnapshotProvenance.corporate_action_evidence_status` enum is
unchanged; a separate S3c1 evidence object does not retroactively alter any
S3b1/S3b2 v1 snapshot identity.

`derive_daily_market_data_corporate_action_content_hash(...)` computes a
semantic hash over the corporate-action economic projection, including the
hash domain/version, instrument identity, coverage dates, and canonical events.
For cash distributions the projection includes event type, instrument ID,
ex-date, canonical Decimal amount, and currency. For splits it includes event
type, instrument ID, effective date, and reduced split ratio. For unsupported
events it includes event type, instrument ID, effective date, and provider
event type. Event IDs, source references, and source timestamps remain lineage
facts in the evidence contract and are excluded from this semantic economic
hash. Empty checked evidence still hashes the instrument and coverage period so
different no-event windows remain distinct.

`DailyMarketDataResearchProfile` is a deterministic policy contract, not human
approval. The first candidate profile expresses ETF daily USD raw OHLCV,
explicit cash distributions, next-expected-session bar availability, checked
corporate-action evidence, supported cash-distribution and split events, no
unsupported events, fixed preselected ETF instruments, no historical
constituent reconstruction, and full instrument coverage for the tested period.
Provider selection, calendar authority, source licensing, paid data spend,
research interpretation, strategy promotion, paper trading, and live trading
remain human-owner decisions.

The pure economic evidence/profile coherence helper validates only that
supplied policy, sessions, provenance, quality, corporate-action evidence, and
profile facts are mutually compatible. A successful check is not snapshot
research readiness, not provider approval, not license approval, not benchmark
compatibility, not backtest-accounting readiness, and not strategy readiness.
S3b1/S3b2 v1 bundles remain infrastructure artifacts for explicit-economics
research until S3c2 introduces a versioned identity/bundle binding.

Slice 3 S3c2a adds pure daily market-data snapshot-v2 authority, natural
identity, bundle planning, and in-memory verification. It is additive and does
not modify S3a semantics, v1 snapshot contracts, v1 identity, v1
planning/verification, S3b2 local filesystem behavior, provider acquisition,
persistence, backtest-engine accounting, or strategy behavior.

Snapshot-v2 IDs use:

```text
daily-market-data-snapshot-v2-<sha256>
```

over the S3a bar semantic content hash, unchanged policy hash, unchanged
expected-session hash, v2 bar-source provenance hash, S3c1 corporate-action
semantic hash, and complete corporate-action evidence authority hash. The
identity domain/version is `daily-market-data-snapshot-v2`. Bundle format is
separate and uses `daily-market-data-snapshot-bundle-v2`; bundle format,
filesystem paths, file-byte hashes, staging paths, and bundle-manifest bytes
are not natural identity inputs.

V2 uses a bar-only provenance sidecar because v1
`DailyMarketDataSnapshotProvenance` contains
`corporate_action_evidence_status` and S3b1 intentionally records
`not_integrated`. Snapshot-v2 therefore persists `bar-provenance.json` using
`DailyMarketDataBarSourceProvenanceV2`; it records only bar source/capture
authority and rejects the legacy `corporate-action/distribution evidence is
not integrated` limitation. Corporate-action source authority remains in
`corporate-action-evidence.json`.

The pure snapshot-v2 planner has two bar-byte inputs with distinct authority.
Canonical `source_bytes` always drive JSONL parsing, quality checks, semantic
bar identity, and deterministic `bars.jsonl` rendering. An optional frozen
`DailyMarketDataBarSourceAuthorityInputV2` may instead supply the exact
upstream bytes used only to derive bar-provenance content hash/size together
with the parser/adapter version that consumed them. Omitting it preserves the
historical canonical-JSONL provenance path exactly. The operational authority
input has no caller hash/size, does not alter durable contracts or identity
versions, and introduces no provider, network, filesystem, clock, or
acquisition behavior.

The exact S3c2a bundle-v2 files are:

- `bars.jsonl`
- `expected-sessions.json`
- `policy.json`
- `bar-provenance.json`
- `quality-report.json`
- `corporate-action-evidence.json`
- `snapshot-manifest.json`
- `bundle-manifest.json`

There is no `provenance.json`, `corporate-actions.jsonl`, authority sidecar,
profile sidecar, readiness marker, latest/current pointer, or filesystem
publication in S3c2a. The bundle manifest records the first seven payload
files and excludes `bundle-manifest.json` itself.

S3c2a adds a complete authority hash over the validated
`DailyMarketDataCorporateActionEvidence` contract. This is intentionally
separate from the S3c1 economic semantic hash: identical split/cash economics
from different source references, source hashes, vintages, event
`source_available_at` facts, or capture timestamps keep the same economic hash
but produce a different evidence-authority hash and therefore a different
snapshot-v2 ID.

`DataSnapshotManifest` remains unchanged. In v2 its source dataset/version/type,
source observation, vendor/license, currency, and creator fields remain
primary bar-dataset metadata. Corporate-action source authority is represented
by `corporate-action-evidence.json` and bound through the v2 bundle manifest
and snapshot ID. `content_hash`, `row_count`, `file_count = 1`, and
`size_bytes` continue to describe the primary `bars.jsonl` payload only.

V2 manifest timing is deterministic and uses no runtime clock. It derives
`ingestion_completed_at` as the max of bar and corporate-action ingestion
completion, `available_at` as the max of both availability timestamps,
`created_at` as the max of both created timestamps, and `as_of` as the max of
bar provenance `as_of` and corporate-action evidence `source_observed_at`.
The v2 `as_of` is the combined bound source-vintage cutoff, not the final
historical session date and not wall-clock planning time.

S3c2a still proves internal captured authority only. It does not prove provider
truth, source licensing, raw source retention, benchmark compatibility,
backtest corporate-action accounting, leakage-safe strategy execution, or
human approval. V2 local publication and deterministic snapshot/profile
compatibility remain S3c2b.

Slice 3 S3c2b1 adds local filesystem publication and read-only verification for
already planned S3c2a snapshot-v2 bundles. It is additive in
`daily_market_data_storage.local_v2`; the closed S3b2 v1 `local.py`
implementation remains unchanged. Callers must use explicit APIs:
`publish_local_daily_market_data_snapshot(...)` and
`verify_local_daily_market_data_snapshot(...)` for v1, and
`publish_local_daily_market_data_snapshot_v2(...)` and
`verify_local_daily_market_data_snapshot_v2(...)` for v2. There is no generic
version dispatcher and no automatic publication dispatcher.

S3c2b1 uses the same local namespace as v1:

```text
<snapshot_root>/daily-market-data/<snapshot_id>/
```

The v1 and v2 snapshot ID prefixes provide directory identity separation, so
both versions may coexist under one `daily-market-data` root. V2 publication
stores exactly the eight S3c2a files: `bars.jsonl`, `expected-sessions.json`,
`policy.json`, `bar-provenance.json`, `quality-report.json`,
`corporate-action-evidence.json`, `snapshot-manifest.json`, and
`bundle-manifest.json`. It adds no `provenance.json`, profile sidecar,
compatibility sidecar, success marker, latest/current pointer, lock metadata,
or publication manifest.

Before creating `snapshot_root`, `daily-market-data`, `.staging`, a staging
directory, or any bundle file, S3c2b1 runs
`verify_daily_market_data_snapshot_bundle_v2(...)` on `plan.as_file_map()` and
requires the verified snapshot ID to match `plan.snapshot_id` and the v2 ID
pattern. Invalid or corrupted plan state therefore produces no filesystem
mutation.

Publication mirrors the S3b2 cooperating-root model: caller-owned root,
symlink refusal for the root, managed parent, staging parent, final snapshot
directory, and authoritative files, private same-filesystem staging under
`daily-market-data/.staging/`, exclusive file creation, exact planned bytes,
file flush and `fsync`, best-effort portable directory `fsync`, staged readback
through the pure v2 verifier, `os.rename` for final visibility, parent
directory `fsync`, and mandatory final readback verification. It deliberately
does not use `os.replace`, copy fallback, overwrite, repair, or broad
`openat`/`O_NOFOLLOW` hostile-root hardening.

Existing final snapshot-v2 directories are immutable exact-byte authority.
Same snapshot ID plus identical authoritative bytes returns `ALREADY_PRESENT`;
same snapshot ID plus any byte, file-set, symlink, non-regular file, or
verification difference is a conflict. If final verification fails after a
successful rename, S3c2b1 raises a disk verification error and leaves the final
directory in place for diagnosis. Staging cleanup removes only the staging
directory created by the current invocation and leaves unrelated staging
children untouched.

S3c3c2 adds exact-byte snapshot-v2 local readback without changing that
storage or trust model. `load_local_daily_market_data_snapshot_v2(...)` reads
the authoritative eight-file directory once, freezes the exact
`Mapping[str, bytes]`, passes that same immutable mapping to
`verify_daily_market_data_snapshot_bundle_v2(...)`, and returns it with the
verified facts and resolved immutable directory in
`LocalDailyMarketDataSnapshotReadbackV2`. The existing
`verify_local_daily_market_data_snapshot_v2(...)` remains a compatibility
wrapper that returns only `readback.verified`.

Created and already-present publication paths use that readback result for
both verification and exact comparison with the planned file map. The final
authoritative directory is therefore not independently read once for
verification and again for byte comparison. The loader does not decode,
normalize, rerender, reconstruct, repair, cache, or persist bundle content,
and it never creates root, managed, or staging directories. Its only inputs
are an existing cooperating snapshot root and an exact snapshot-v2 ID. It
introduces no lookback, lag, calendar inference, source acquisition, or
leakage/readiness claim. A later orchestration layer may pass the returned
exact byte mapping downstream; S3c3c2 does not import or change the
backtest-engine or S3d2a.

S3c2b1 still does not add profile hashing, snapshot/profile compatibility,
research readiness, provider/source acquisition, raw-source archival,
persistence, migrations, backtest-engine accounting, strategy behavior, paper
trading, or live trading. Deterministic snapshot/profile compatibility remains
a later S3c2b slice.

Slice 3 S3c2b2 adds deterministic daily market-data research-profile identity
and pure verified snapshot-v2/profile compatibility. The profile hash uses the
domain `daily-market-data-research-profile` and identity version
`daily-market-data-research-profile-hash-v1`; it hashes the complete
revalidated `DailyMarketDataResearchProfile.model_dump(mode="json")` inside
that domain/version wrapper with the same canonical JSON semantics as snapshot
identity helpers. The complete profile contract is the projection, including
`profile_id`, `profile_policy_version`, temporal coverage, corporate-action
policies, calendar/session authority, and universe/survivorship/delisting
policy strings. There is no separate semantic profile subset.

The profile hash is intentionally separate from snapshot identity. Snapshot-v1
and snapshot-v2 IDs continue to answer which immutable data and evidence are
present. A profile answers which exact policy requirements are being requested,
and compatibility answers whether a verified snapshot-v2 satisfies the
snapshot-evaluable data-side requirements of that exact profile. The same
snapshot-v2 can be tested against multiple profiles without changing its
snapshot ID, bundle manifest, snapshot manifest, local storage path, or bundle
bytes.

S3c2b2 operates only on `VerifiedDailyMarketDataSnapshotV2`, normally produced
by `verify_daily_market_data_snapshot_bundle_v2(...)` or
`verify_local_daily_market_data_snapshot_v2(...)`. The compatibility helper
performs a v2 runtime type check and revalidates the research profile, but it
does not reconstruct bundle bytes, rerun snapshot-v2 verification, recompute
snapshot-v2 identity, access the filesystem, or persist any result. A manually
constructed Python `VerifiedDailyMarketDataSnapshotV2` dataclass is outside
the normal verifier-produced trust path and is not made cryptographic
authority by compatibility.

Compatibility checks are limited to snapshot-evaluable profile requirements:
policy asset class, frequency, adjustment policy, distribution treatment,
calendar, timezone, universe policy, survivorship policy, and delisting policy;
quality PASS and single-instrument coherence; bar currency and temporal
coverage; expected-session calendar, timezone, source ID, and source version;
structured corporate-action evidence coverage over the quality expected-session
range; allowed evidence completeness; supported corporate-action event types;
unsupported-event fail-closed behavior; and cash-distribution currency. A
successful result returns only operational facts: snapshot ID, profile ID,
profile hash, profile policy version, instrument ID, unsupported-event count,
and the required daily-bar availability policy.

`corporate_action_coverage_requirement` remains profile identity and is bound
into the complete profile hash, but S3c2b2 does not parse, substring-match, or
infer executable semantics from that free text. Executable coverage
compatibility uses the structured evidence coverage dates and quality expected
dates. If future profiles need multiple executable coverage modes, that should
be a structured versioned policy field rather than arbitrary prose. Likewise,
`next_expected_session` is carried as a downstream execution obligation; this
validator does not prove any future strategy consumed bars only on the next
expected session.

Successful S3c2b2 compatibility is not research readiness, experiment
readiness, benchmark compatibility, provider approval, license approval,
source truth verification, backtest corporate-action accounting support,
leakage-safe execution proof, paper-trading approval, or live-trading
approval. It adds no JSON schema, durable contract, persistence row, migration,
storage file, profile sidecar, readiness marker, benchmark logic, provider
adapter, real-data acquisition, backtest-engine behavior, strategy behavior,
paper behavior, or live behavior.

## Daily ETF Economic Accounting And Timing Kernel

Slice 3 S3d1 adds an additive, pure engine-side kernel for daily ETF economic
accounting and complete-bar information timing. The accounting policy version
is `daily-etf-economic-accounting-v1`; the timing policy version is
`daily-etf-next-expected-session-v1`. These are operational S3d1 semantic
policy identifiers only. They are not engine versions, snapshot identities,
research-sdk durable contracts, or readiness approvals, and S3d1 does not add a
new engine/run identity.

The S3d1 accounting state is single-instrument, long-only, and integer-share
only for strategy holdings. It tracks cash, integer quantity, total economic
book cost, outstanding cash-distribution receivables, and applied corporate
action event IDs. It does not model shorts, borrowing, margin, taxes,
withholding, benchmark portfolios, fractional benchmark units, automatic
reinvestment, snapshot-v2 loading, bundle parsing, providers, network access,
persistence, migrations, paper trading, or live trading.

For each supplied expected session, the deterministic session-open accounting
sequence is:

1. Settle previously earned receivables whose
   `cash_available_session` is the current session.
2. Validate the full current-session corporate-action event set before any
   state change.
3. Apply mechanical splits effective on the session to carried holdings.
4. Establish cash-distribution entitlement from holdings carried into the
   session before any strategy trade.
5. Return the pre-trading economic state and audit records.

Splits are applied before the session's trading boundary because raw prices for
that session are already in effective units. Total book cost is unchanged. A
split that would produce fractional strategy shares fails closed; S3d1 does
not round or create cash-in-lieu. A split on a first session with zero holdings
is a deterministic no-op because there is no pre-run position to restate.
Multiple same-day splits with held shares fail closed. Mechanical splits have
no commission, slippage, or fake trade record.

For a cash distribution with ex-date `D`, entitlement is the quantity held
immediately before session `D` trading. A position bought at the session `D`
open earns no same-day distribution; a later sale would not revoke an already
created entitlement. On ex-date, an entitled distribution creates a receivable
equal to entitled quantity times amount per share. The receivable is included
in economic equity immediately, while cash and book cost are unchanged. This
keeps raw-price ex-date drops from creating false accounting losses. Record
date is evidence metadata only and does not drive entitlement.

Entitled distributions require a `payable_date` on or after ex-date. Missing
payable date fails closed when the portfolio earns entitlement; missing
payable date with zero pre-open holdings does not fail solely because there is
no portfolio entitlement to settle. Spendable cash becomes available at the
first supplied expected session strictly after `payable_date`. If no such
session exists in the supplied horizon, the receivable remains outstanding and
ending economic equity may include it. Ex-date before run start plus no prior
position does not create an entitlement or later cash settlement.

Same-day split and cash distribution evidence is ambiguous for held shares
because the provider-neutral event contract does not state whether the cash
amount and entitlement quantity are pre-split or post-split. S3d1 therefore
fails closed before applying any same-day events when shares are held. With
zero holdings, the same event set has no portfolio economic effect. Multiple
same-day cash distributions are supported and processed in canonical
economic-date/type/event-ID order. Unsupported corporate-action events,
instrument mismatches, cash currency mismatches, duplicate event application,
and unsupported same-day economics fail closed.

S3d1 exposes a `NEXT_EXPECTED_SESSION` timing primitive over supplied expected
session dates only. For decision session `T`, strategy decision logic may see
complete daily bars only from expected sessions strictly before `T`; the first
expected session exposes no complete daily bars. No weekdays, holidays,
runtime clocks, or calendars are inferred. S3d1 timing models do not carry
bars, corporate-action events, `announced_at`, `source_available_at`, or source
references.

This timing authority describes only what complete daily bars may be exposed
to strategy decision logic. A later S3d2 fill simulator may read session-`T`
open after an order already exists; execution simulator access to the current
open is not strategy observation. Corporate-action events are accounting
inputs only in S3d1, not strategy-facing features. A future strategy that
trades on announcements or corporate-action knowledge needs a separate
point-in-time feature design.

### S3d2b Economic Foundation

The first S3d2b prerequisite adds pure accounting components only; it does not
connect snapshot-v2 inputs to a complete backtest run. The gross SPY benchmark
policy version is
`daily-etf-gross-benchmark-economic-accounting-v1`. It uses raw prices,
twelve-decimal fractional units, explicit splits, and explicit
cash-distribution receivables. Initial units are rounded down to the policy unit
quantum and any residual value is retained as cash at the existing six-decimal
money precision. Benchmark distributions settle to retained cash and are not
reinvested. The benchmark has no commission or slippage.

Benchmark session-open accounting shares S3d1 event-authority validation and
ordering: settle eligible receivables, validate the complete current event
set, apply splits, then establish distribution entitlement from carried units.
Outstanding receivables remain in economic equity beyond the run horizon.
Duplicate, unsupported, instrument-mismatched, currency-mismatched, and
ambiguous same-session events fail closed. Fractional benchmark units remain a
separate state from the integer-share strategy portfolio; no cash-in-lieu is
inferred.

The same prerequisite also provides a pure initial QQQ buy transition into
`EconomicPortfolioState`. It applies configured buy slippage and commission to
the raw open, chooses an integer quantity, reduces cash, and records total book
cost as executed notional plus commission. Corporate-action accounting does
not create fills, commissions, slippage, or synthetic trades. The legacy
synthetic baseline delegates its unchanged initial-fill arithmetic to this
helper, but this slice adds no snapshot-v2 runner, artifacts, lineage, ledger,
provider, paper-trading, or live-trading behavior.

## Snapshot-V2 Economic Backtest Input Pair

Slice 3 S3d2a adds a pure engine-side execution-input bridge for snapshot-v2
daily ETF bundles. It consumes only in-memory exact bundle bytes supplied by
the caller. The loader copies the supplied `Mapping[str, bytes]` once at
function entry, then uses that same copied byte map for both
`verify_daily_market_data_snapshot_bundle_v2(...)` and
`parse_canonical_daily_bars(...)`. This preserves same-byte authority between
the verifier-produced `VerifiedDailyMarketDataSnapshotV2` facts and the parsed
canonical bars. Runtime bundle keys must be strings and values must be actual
`bytes`; the loader does not coerce strings, `bytearray`, or `memoryview`.

The engine-owned `LoadedDailyMarketDataSnapshotV2` result contains only the
verified snapshot-v2 result and the parsed `CanonicalDailyBar` tuple. It does
not retain filesystem paths, provider URLs, raw mapping references, readiness
flags, approval fields, persistence identity, or a durable schema. The normal
trust path begins at exact bundle bytes; S3d2a deliberately provides no API
that accepts `VerifiedDailyMarketDataSnapshotV2` plus detached bars. Manually
constructing the loaded operational object is outside the loader-produced trust
path. `CanonicalDailyBar` remains provider-neutral and has no instrument or
symbol field; instrument authority comes from the verified snapshot's
instrument ID and quality-report instrument.

The first S3d2a pair API accepts two raw snapshot-v2 bundle byte mappings, one
exact `DailyMarketDataResearchProfile`, and an inclusive `start_date` /
`end_date` run window. It internally loads both bundles through the same-byte
loader, then independently validates each verified snapshot against the same
research profile through
`validate_daily_market_data_snapshot_profile_compatibility(...)`. Both
compatibility results must bind the same exact profile hash and must require
`NEXT_EXPECTED_SESSION` daily-bar availability. This establishes the downstream
timing obligation for S3d2b; it is not a general leakage-safety proof.

S3d2a is intentionally fixed to the first reviewable pair: QQQ as the strategy
asset and SPY as the benchmark. The strategy snapshot symbol must be `QQQ`, the
benchmark snapshot symbol must be `SPY`, and the snapshot IDs and instrument IDs
must be distinct. S3d2a also defensively requires matching daily frequency,
policy calendar/timezone, expected-session calendar/timezone, expected-session
source ID/version, and currency. Provider/vendor/source dataset strings are
not compared as approval semantics; source selection, license review, and
source-family approval remain S3c3 responsibilities.

The requested run window uses exact supplied expected-session authority. Both
endpoints must be expected sessions in both snapshots, `start_date` must be on
or before `end_date`, and at least two expected run sessions are required. The
asset and benchmark run-session tuples are derived independently from their
verified expected-session contracts and must match exactly. S3d2a never unions,
intersects, forward-fills, infers holidays, or repairs dates. The projected
asset and benchmark run bars must contain exactly one bar for every run session
and no unexpected in-window bar.

Corporate-action evidence is projected only for execution-input coherence. The
normal verifier-plus-profile path applies to each complete snapshot, so the
approved S3d2a profile rejects unsupported corporate-action evidence globally
rather than only inside the requested run window. For supported events, an
economic date before the run start or after the run end is irrelevant to S3d2a
because the future S3d2b portfolios start with zero holdings. A payable date
inside the run does not make a pre-run ex-date event economically in-run, and a
payable date after the run does not make an in-run ex-date invalid. An event
whose economic date falls inside the requested run window must fall on one of
the exact run sessions; S3d2a fails closed rather than shifting weekend or
non-session events to another date. Unsupported-event rejection is also retained
as pair-level defense in depth for any internally inconsistent operational
object outside the normal profile-produced trust path. Actual split,
distribution, entitlement, receivable, settlement, and benchmark accounting
remain S3d2b concerns and must preserve S3d1 semantics.

S3d2a does not read local snapshot directories, import local-v2 filesystem
verification helpers, walk roots, parse paths, access networks, persist bytes,
write artifacts, build ledger/report-card records, create an engine config,
derive a run identity, implement fills, implement benchmark accounting, or
claim research/experiment readiness. A later orchestration boundary may bridge
local snapshot IDs to exact authoritative bundle bytes before calling this pure
in-memory input layer.

## Snapshot-V2 Economic Execution

S3d2b adds the pure
`run_snapshot_v2_buy_and_hold_backtest(...)` application boundary. Callers
supply exact QQQ and SPY snapshot-v2 bundle bytes, the required research
profile, a resolved versioned economic configuration, and injected runtime
lineage. The boundary invokes S3d2a verification and exact pair validation
itself; it does not accept a caller-constructed parsed pair. It performs no
filesystem, network, database, provider, clock, broker, paper-trading, or
live-trading work.

Both portfolios begin each run with cash and zero holdings. On the first
session, the S3d1 strategy and benchmark accounting kernels settle and validate
events, apply zero-position splits, and record zero-position distribution
entitlements before the unconditional allocations execute at the raw open.
Consequently, shares or units bought on a first-session ex-date do not earn
that distribution. Later sessions use carried holdings for split and
distribution accounting before raw-close valuation. QQQ uses integer shares
and configured commission/slippage; SPY uses twelve-decimal fractional units
and zero costs. Both retain settled distribution cash without reinvestment.

`CompletedEconomicBacktestResult` is separate from the legacy synthetic
`CompletedBacktestResult`. Its daily rows reconcile cash, position, raw close,
market value, outstanding receivables, book cost where applicable, economic
equity, and cumulative QQQ costs. Metrics are calculated from economic equity,
so explicit distribution receivables offset corresponding raw-price drops,
settlement is equity-neutral, and splits are economically neutral within the
declared integer/fractional precision policies. Before artifacts or ledger
records are produced, a pure canonical validation boundary reconstructs the
result, recomputes metrics/drawdown/monthly returns and the initial fill, and
reconciles terminal states, receivables, costs, and action-application audit
authority. Initial capital must already be exactly representable at the
six-decimal economic-money precision.

Economic identity is `snapshot-v2-economic-execution-identity-v1`. It binds
the complete resolved economic policy and dedicated pair market-data lineage:
both snapshot IDs and verifier hashes, exact bundle file authority, both
verified snapshot manifests, the research-profile hash and contract, exact run
sessions, accounting/timing policies, capital, costs, and price/share/
distribution policies. Injected Git/runtime metadata remains result lineage but
does not change the economic run ID. `LATEST_KNOWN` is mandatory and is
recorded as a limitation, never as point-in-time strategy knowledge.

The economic artifact writer emits the ten required run artifacts plus
`economic_corporate_action_audit.parquet`. Payload bytes use deterministic
JSON/Parquet policies, bind the economic run ID, expose both snapshot lineages,
and contain no current-time value. Artifact timestamps derive from the already
identity-bound snapshot manifests. Writer and verifier use the same semantic
serialization functions for every payload, and verification compares stored
bytes with result-derived expected bytes rather than trusting rebuilt hashes or
row-count metadata. No object-store publication is included.

The exported boundaries are `ResolvedEconomicBacktestConfig`,
`CompletedEconomicBacktestResult`,
`run_snapshot_v2_buy_and_hold_backtest(...)`,
`canonicalize_completed_economic_backtest_result(...)`,
`generate_economic_artifact_bundle(...)`,
`verify_economic_artifact_bundle(...)`, and
`map_completed_economic_backtest_to_ledger_records(...)`. Exact snapshot-v2
bytes enter through the public runner, which invokes S3d2a itself; no parsed-pair
bypass is an execution boundary.

Pair-aware experiment recording adds
`CompletedExperimentPairRecordBundle` and
`record_completed_experiment_pair(...)`. The QQQ manifest is the run's primary
`data_snapshot_id`; the distinct SPY manifest is the benchmark
`snapshot_id`. Both manifests are written before the run and artifact manifest
inside the caller-owned transaction. The existing table can store both
manifests, so S3d2b requires no migration. The legacy single-snapshot recording
service and synthetic runner retain their behavior.

The human-accepted bounded QQQ/SPY 2024 validation exercised pure pair-ledger
mapping and canonical `CompletedExperimentPairRecordBundle` construction only.
It did not call `record_completed_experiment_pair(...)`, open a database
transaction, or persist the accepted real validation run to PostgreSQL. Detailed
evidence and the acceptance boundary are recorded in
`docs/validation/s3d2b-qqq-spy-2024.md`.

## Massive Primary Source Capture

Slice 3 S3c3a records the owner-selected S3c3 development-source decision and
the immutable source-capture design. Massive is the primary development source
for private research/development. Tiingo remains a secondary independent
comparison and validation source. This is a technical source decision only: it
does not establish commercial license approval, enterprise approval, permanent
archival legal approval, redistribution approval, experiment readiness,
paper-trading readiness, or live-trading readiness.

The S3c3 data path is:

```text
Massive API
-> immutable exact-byte source capture
-> offline Massive adapter
-> provider-neutral daily market-data inputs
-> snapshot-v2
-> S3d2a trusted QQQ/SPY execution-input pair
```

Network acquisition and normalization are separate boundaries. Acquisition may
use the network and a Massive credential to produce exact immutable source
captures. Adaptation is offline, credential-free, and consumes only immutable
capture bytes plus capture metadata. The adapter must never call Massive to
fill missing facts on demand; missing source evidence fails closed.

S3c3c5 implements only bounded acquisition plus in-memory source-capture
planning. Credential-free planning fixes three requests per instrument in
`BAR_RESPONSE`, `DIVIDEND_RESPONSE`, `SPLIT_RESPONSE` order. Pair execution
validates and canonically rederives both public operational plans before request
one, then performs asset bars/dividends/splits followed by benchmark
bars/dividends/splits. Both plans must share an explicit nonempty
`acquisition_batch_id` and date range while retaining distinct IDs and symbols.
The inclusive request span is limited to 366 calendar days. There is no
concurrency, retry, pagination following, filesystem mutation, or partial pair
result.

The production transport is deliberately narrow: stdlib HTTPS GET only to
`api.massive.com`, default verified TLS context, no caller-controlled base URL,
no redirects or ambient proxy framework, and `Authorization: Bearer` only.
Credentials are runtime-only redacted operational objects; platform-owned
acquisition code never places them in a query, source reference, request
metadata, manifest, error, or log. Exact credential text is also rejected if
it appears in any persistent acquisition
fact or exact provider response bytes. The credential holder rejects
serialization, and acquisition request, plan, response, and pair renderings do
not expose their contents. The executor captures credential authority once and
uses fresh redacted holders derived from that captured value for transport
calls. An injected transport is executable in-process code with credential
access, not a secret sandbox; only trusted implementations may be injected.
Its response objects and exceptions are nevertheless untrusted evidence inputs:
the executor captures response fields once, re-applies all HTTP/header/size/
envelope checks, and discards external exception context. Network capability in
the codebase is not authorization for a real provider call. All S3c3c5 tests
use injected or stubbed transports, and a later S3c3c6 human run gate owns any
real acquisition.

Each request uses a 5-second connection timeout, 15-second read-inactivity
timeout, and 30-second monotonic application deadline. The connection timeout
covers socket connection and TLS handshake; after connection, the remaining
deadline is recomputed around request send and response-header/status wait and
before every body read, with a final check after end-of-body. As an explicit
stdlib limitation, DNS resolution cannot be interrupted as a hard real-time
30-second deadline; if a blocking phase returns after the deadline, acquisition
fails before accepting the response (and before request send when connection
establishment itself returns late). Response bodies are read incrementally and
capped at 4 MiB for bars and 2 MiB for each corporate-action role, with 8 MiB
per instrument and 16 MiB per pair. Exactly HTTP 200
and JSON media type are accepted; content encoding must be absent or identity,
and ambiguous or inconsistent authority headers fail closed. Successful bodies
must be nonempty strict UTF-8 JSON objects with exact `status="OK"`, a normalized
provider `request_id`, and no `next_url` key. Acquisition inspects only this
operational envelope—not economic rows—and preserves accepted entity bytes
without decoding/re-encoding, normalization, or decompression.

After all three responses for one instrument pass, acquisition calls its UTC
clock exactly once. That observation time means all three exact bodies have
been successfully observed by the process; sequential asset and benchmark
times may differ arbitrarily. The unchanged source-capture planner receives
the exact bodies and credential-free request authority and remains solely
responsible for member hashes/sizes, the CA source manifest, and capture
identity. S3c3c5 does not call the immutable publisher. S3c3c6 must complete
both plans and separately pass the human-authorized publication/orchestration
gate. At the S3c3c5 stage, S3d2b therefore remained blocked. Human-accepted
S3c3c run-008 has now completed the separate gate and unblocked S3d2b.

S3c3c6a adds that operator gate as fake-provider-only orchestration. Its
credential-free preflight requires a clean `main` checkout whose local
HEAD/main/origin-main refs equal an explicit reviewed commit, an already
existing external data root separate from the repository hierarchy, the exact
QQQ (`instrument-us-etf-qqq-xnas`, `QQQ`, `XNAS`) and SPY
(`instrument-us-etf-spy-arcx`, `SPY`, `ARCX`) authorities, the independently
derived 2024 XNYS sessions, and the approved policy/profile hashes. It prints
and binds these non-secret facts in an explicitly labeled operational approval
fingerprint. The fingerprint is not source-capture, snapshot, experiment, or
research identity. Preflight accepts no credential, performs no acquisition or
publication, and does not mutate its data root.

Execution rebuilds and rechecks preflight, verifies the reviewed fingerprint,
requires the exact endpoint/retention attestation followed by
`ACQUIRE MASSIVE QQQ SPY 2024-01-02 2024-12-31`, and only then permits an
interactive non-echoing `getpass` credential prompt. The production command
accepts no credential argument, environment variable, stdin-pipe mode, or
credential file; a noninteractive or echoed-fallback prompt fails closed. It
then repeats the Git/root/fingerprint authority check before request one.
Research-sdk orchestration acquires
the six responses, verifies and adapts both in-memory captures, checks pair
compatibility and the frozen independent authorities, publishes and exact-loads
both source captures, re-adapts from durable readback, and prepares and verifies
both snapshot-v2 plans. It stops before snapshot publication and does not
import the backtest engine. The operator script first runs S3d2a against both
in-memory snapshot plans; only a successful prepublication pair proof permits
sequential snapshot publication/readback. Final S3d2a consumes only the exact
snapshot readback mappings. Failures retain already published immutable
evidence without retry, repair, rollback, deletion, or fabricated success.
The single injected clock has five named UTC reads on a successful run: QQQ
and SPY observation times inside S3c3c5, then shared ingestion-completed,
available, and snapshot-created times. Chronology is validated, never repaired
or inferred from proximity.

The real profile is
`daily-etf-latest-known-us-equity-v1` under policy version
`daily-etf-latest-known-us-equity-profile-v1`. Its durable session authority is
`exchange_calendars:XNYS` and
`exchange_calendars-4.13.2+us-equity-regular-session-dates-v1`, with canonical
profile hash
`sha256:3f0945bac4b4faa3d228805d367ae8dd0e009db8e241e02299e8c7663c64a7ed`.
The underscore in the durable source-version prefix follows S3c3c4; the
hyphenated `exchange-calendars` spelling is only the installed distribution
metadata name. XNYS remains a common daily research session policy, not QQQ or
SPY listing-venue metadata.

S3c3c6a tests use synthetic provider evidence, blocked DNS/socket/TLS entry
points, and temporary local roots. S3c3c6b remains a separately authorized
operational event: merge, CI success, network-capable code, or credential
availability does not authorize a real request. No S3c3c6b execution or real
QQQ/SPY publication occurs in S3c3c6a. PAPER/LIVE TRADING NOT APPROVED.
Path checks and the existing publishers revalidate symlink and managed-root
safety at their respective boundaries. As with ordinary local filesystem
operations, this relies on a cooperating host: it does not claim to eliminate
mount-point or privileged concurrent-mutation TOCTOU.

Authoritative Massive capture preserves the exact HTTP response body bytes
before parsing. The first QQQ/SPY capture design requires three independently
verifiable source members per instrument: `BAR_RESPONSE`, `DIVIDEND_RESPONSE`,
and `SPLIT_RESPONSE`. Empty valid split responses are still captured members.
Normalized or reserialized JSON is not raw source authority.

For the Massive path,
`DailyMarketDataBarSourceProvenanceV2.source_content_hash` binds the exact RAW
`BAR_RESPONSE` body bytes consumed by the adapter, and `source_size_bytes`
binds that same response body size. Corporate-action evidence uses the existing
single source hash/size fields by hashing a deterministic canonical
corporate-action source manifest that identifies and hashes both the dividend
and split response members. It does not concatenate raw endpoint bytes without
framing and does not pretend either endpoint alone is complete corporate-action
source authority.

Massive bars must be requested and verified as `adjusted=false`. The adapter
must fail closed if request and response authority do not establish RAW
semantics. There is no fallback to adjusted bars and no normalization of
adjusted history into RAW.

For first historical Massive captures, temporal coverage remains
`LATEST_KNOWN` unless independently verifiable historical point-in-time
availability evidence is later available. Corporate-action `source_available_at`
comes from explicit capture observation authority for this first historical
path, not from ex-dividend dates, pay dates, record dates, declaration dates,
or split execution dates.

Expected sessions remain independent deterministic calendar/session authority.
Returned Massive bar dates do not define the expected-session calendar, and the
platform must not use naive weekday generation. The first real QQQ/SPY
snapshots should use a deterministic US-equity exchange calendar source with
explicit calendar, timezone, session source ID, and session source version.

S3c3c4 closes that daily date-authority boundary with the human-approved
combination `exchange_calendars==4.13.2`, calendar `XNYS`, timezone
`America/New_York`, and semantic policy
`us-equity-regular-session-dates-v1`. The resulting source authority is labeled
`exchange_calendars:XNYS` at version
`exchange_calendars-4.13.2+us-equity-regular-session-dates-v1`. Exact pinning
matters because an unlabeled installed calendar result is not reproducible
authority; each derivation checks installed distribution metadata and fails
closed unless it is exactly `4.13.2`.

`derive_us_equity_daily_expected_sessions(...)` accepts exact, explicit,
inclusive `start_date` and `end_date` values, constructs XNYS with explicit
bounds, verifies the returned calendar name and timezone, and materializes its
strictly ascending regular-session labels directly as `tuple[date, ...]`. It
does not use a wall clock, network, bars, ticker, instrument, venue, provider,
weekday approximation, open/close timestamps, or inferred current date. An
early-close day remains an expected session because this policy is date-only.
The durable result is the existing `DailyMarketDataExpectedSessions` contract,
not a pandas index, calendar handle, or lazy package object.

XNYS is deliberately the common U.S.-equity daily research-session policy for
the first supported QQQ/SPY pair. It is not listing-venue or execution-venue
metadata and does not claim either instrument is NYSE-listed: QQQ remains XNAS
and SPY remains ARCX while both reuse the same independent XNYS session-date
tuple. Intraday, venue-specific, other-exchange, and other-asset-class calendar
semantics remain future work.

The existing canonical expected-session hash remains the only session identity
hash and binds the fully materialized dates plus source/calendar/timezone
metadata into snapshot identity. A dependency upgrade, semantic-policy change,
or revised historical session tuple is therefore an explicit authority
migration requiring a new pin/source version, reviewed golden output, and any
resulting expected-session hash and snapshot-identity change. Calendar dates do
not create a point-in-time or leakage-safe market-data claim.

S3c3c3 adds a pure provider-specific bridge from one verified, offline-adapted
Massive capture to the existing generic snapshot-v2 planner. It renders
canonical `bars.jsonl` input from the adapter's canonical bars, while the bar
provenance hash and size bind the exact immutable `BAR_RESPONSE` bytes and the
adapter parser version. Corporate-action evidence binds the exact canonical
`ca-source-manifest.json` bytes, which already bind the dividend and split
response authorities. Logical references use
`daily-market-data-source-capture://<capture_id>/bars.json` and
`daily-market-data-source-capture://<capture_id>/ca-source-manifest.json`;
provider URLs, credentials, authorization headers, and local absolute paths do
not enter snapshot provenance.

The bridge calls no clock. Ingestion completion, availability, creation,
creator, licensing notes, and human-reviewed limitations are explicit caller
inputs. Chronology is fail closed:

```text
capture_observed_at
<= ingestion_completed_at
<= available_at
<= created_at
```

For this first historical path, both bar `as_of` and source observation use the
capture observation time and temporal coverage remains `LATEST_KNOWN`. Event
`source_available_at` values from the offline adapter are not rewritten.
Expected sessions remain a separate caller-supplied authority and are passed
unchanged to generic planning; the bridge performs no exchange-calendar,
weekday, or returned-bar-date derivation.

S3c3c3 also adds a provider-specific pair-vintage check before later
asset/benchmark orchestration. Two independently captured instruments must
share a nonempty `acquisition_batch_id`, provider, source family, capture
format, parser, temporal coverage, currency, requested bar range, corporate-
action coverage, and the per-role endpoint and request/scope specification
after removing only `ticker`. Capture IDs, instrument IDs, and symbols must be
distinct. Sequential capture timestamps, sanitized source references, API
request IDs, response bodies, hashes, sizes, provider event IDs, and
limitations may differ. The explicit batch is the grouping authority; timestamp
proximity is not. This check is acquisition compatibility only, not research
readiness, pair semantics, provider/license approval, or trading approval.

The bridge's inputs are immutable verified source evidence, canonical adapter
output, a caller-selected RAW daily policy, independent expected sessions, and
explicit operational review facts. Its lookback and coverage are exactly the
bar and corporate-action request bounds already verified by the adapter; it
adds no lag or calendar rule. Because the first path is `LATEST_KNOWN`, it makes
no point-in-time or leakage-safe research claim. Those semantics remain visible
in provenance and require later profile, pair, and human review.

At this public composition boundary, operational dataclass authorities are
captured once before validation and use. The bridge reasserts the small set of
lineage facts needed to prevent a manually constructed adapted value from
misstating Massive authority: provider/source family, capture format, parser,
instrument and capture identity coherence, canonical Massive endpoints and
request bounds, RAW bar request facts, and cash-distribution currency. It still
trusts the closed source-capture verifier and offline adapter for their full
byte and semantic verification rather than duplicating either transform.

The S3c3 implementation sequence is S3c3a design, then S3c3b immutable capture
and offline Massive adapter, then S3c3c1 raw/canonical bar authority, S3c3c2
exact local readback, S3c3c3 provider composition and acquisition-vintage
validation, S3c3c4 common U.S.-equity expected-session date authority, S3c3c5
bounded acquisition plus planning, and human-authorized real QQQ/SPY
acquisition and snapshot-v2 publication. Human-accepted run-008 completed that
sequence and produced trusted QQQ/SPY snapshot-v2 execution-input bundles. S3d2b
subsequently implemented the pure economic execution path and completed the
separately human-accepted bounded validation recorded in
`docs/validation/s3d2b-qqq-spy-2024.md`.

## Deterministic ETF Baseline

The initial backtest-engine slice runs one unconditional long-only QQQ
buy-and-hold baseline with SPY as a gross benchmark. It validates aligned daily
bars from a small synthetic JSON fixture, buys QQQ once at the first aligned
session open, values the strategy at each aligned close, and does not liquidate
at the end of the period. The order decision does not use same-day close,
future values, indicators, or prior performance.

The baseline uses `Decimal` accounting with explicit `ROUND_HALF_EVEN`
quantization. Monetary values are quantized to `0.000001`; return and ratio
values are quantized to `0.000000000001`. The default assumptions are
`100000` initial capital, 1 basis point commission on executed QQQ notional, 2
basis points buy slippage, integer QQQ shares, retained cash, open execution,
close valuation, and a gross fractional-unit SPY benchmark with no commission
or slippage.

Execution identity is content-addressed from execution inputs and lineage:
resolved configuration, fixture content hash, data and benchmark snapshot
identities, strategy identity and version, engine version, injected Git and
environment metadata, dependency-lock hash, execution command, and the explicit
no-randomness marker. Output metrics, returns, trades, artifact hashes,
artifact root paths, generated timestamps, runtime duration, and wall-clock
timestamps are excluded. Public run IDs use `run-` followed by the full
64-character lowercase SHA-256 digest.

The artifact writer emits the required local payload files under a
caller-supplied artifact root and writes `artifact_manifest.json` last. JSON and
Markdown payload bytes are canonical and deterministic. Parquet payloads use
explicit PyArrow schemas, stable row ordering, no pandas metadata, no
dictionary encoding, no statistics, and uncompressed output. Payload bytes do
not depend on the physical artifact root. The manifest contains actual
`file://` URIs, so manifest bytes and `artifact_manifest_hash` are expected to
depend on the artifact root; writing the same result to the same root remains
byte-for-byte deterministic.

The backtest-to-ledger integration maps one completed deterministic result and
its generated artifact bundle to immutable records containing
`DataSnapshotManifest`, `ExperimentRunRecord`, caller-owned `manifest_id`, and
`RunArtifactManifest`. Backtest execution and artifact writing happen before
any database transaction. The mapper performs only read-only verification: it
reloads the synthetic fixture, checks snapshot identity equality, verifies
payload hashes, sizes, URIs, and the canonical `artifact_manifest.json`, and
rejects dirty execution metadata. It imports only stable contracts from
`research_sdk`, does not load persistence or completed-experiment service
dependencies, and does not write, repair, relocate, or delete artifacts.

Persistence remains owned by `research_sdk.experiment_recording`: the
application caller wraps the pure mapped records in a
`CompletedExperimentRecordBundle` and passes that bundle to
`record_completed_experiment` with a transaction factory such as
`engine.begin`. The data snapshot, experiment run, and artifact manifest
aggregate are recorded atomically in that caller-owned transaction. Exact
replay succeeds only when the same canonical artifact root and contracts are
supplied; a different artifact root for the same `run_id` changes the run
contract and is expected to conflict rather than silently relocate artifacts.

## Deterministic Research Report Cards

`research_sdk.contracts.ResearchReportCard` is the common deterministic
evidence contract for Phase 1B report cards. It is owned by `research_sdk`
because future research engines and asset classes must be able to emit the same
kind of factual evidence summary.

The current builder lives in `packages/backtest-engine` as
`build_deterministic_etf_report_card`. It supports only completed deterministic
QQQ buy-and-hold runs with SPY as the gross benchmark. The builder consumes
already constructed ledger contracts and a caller-owned artifact `manifest_id`;
it performs no filesystem, network, database, repository, transaction, or
current-time work.

The `deterministic-etf-report-card-v1` policy uses one shared synthetic QQQ/SPY
market-data snapshot for both researched data and benchmark data. The builder
does not claim support for independent benchmark snapshots until a future
derivation-policy version adds that behavior.

Report-card identity is derived from the source `run_id`, contract schema
version, derivation-policy version, data and benchmark snapshot content hashes,
run config hash, parameter hash, and artifact manifest hash. The identity is
evidence-derived and does not replace the engine-owned run identity. Human
review metadata, `ResearchNote` content, generated prose, runtime duration,
current process environment, and local working-directory paths are excluded.
Artifact-root-dependent data may affect identity only through the already
recorded `artifact_manifest_hash`.

Before constructing evidence, the builder canonicalizes the supplied
`RunArtifactManifest` contract, hashes those bytes as `sha256:<hex>`, and
requires that value to equal the run's `artifact_manifest_hash`. It also
requires `manifest_id` to be `manifest-` plus the 64-character run digest, the
run and manifest root/manifest URIs to agree, the CONFIG artifact evidence hash
to equal the run's `config_hash`, and each required artifact URI to be
`artifact_root_uri/filename`. The public report-card contract independently
requires every artifact kind in the required artifact set exactly once.

Metric strings use canonical fixed scales: twelve fractional digits for return
and drawdown ratios, and six fractional digits for commissions, slippage, and
ending equity. Negative zero is rejected as a noncanonical metric encoding.
Evidence entries are ordered by artifact kind, filename, and artifact ID. Use
restrictions are treated as set-like metadata and normalized by enum value.

`ReportCardLineage` stores both data and benchmark snapshot content hashes.
They are equal under the v1 shared-snapshot policy, but both are retained so
the report-card ID can be recomputed from durable report-card fields through
the pure identity verifier without reloading source snapshots.

Report cards are durably persisted by `research_sdk` in the dedicated
`research_report_cards` table, and the completed run artifact bundle is not
mutated to add report-card files. The persisted `report_card_id` is the natural
deterministic evidence identity; `contract_hash` is
`contract_sha256(ResearchReportCard)`, the SHA-256 hex digest of the entire
canonical contract payload. Exact replay requires the same `report_card_id` and
the same `contract_hash`; the same `report_card_id` with changed metrics or
other non-identity content is a `ContractHashConflictError`, never
last-write-wins.

Generic report-card identity verification lives in
`research_sdk.report_card_identity` and does not import persistence,
experiment-recording, SQLAlchemy, psycopg, or `backtest_engine`. The
deterministic ETF v1 policy restriction remains in `backtest_engine`.
Persistence separately validates source coherence against the already persisted
run, data snapshot, benchmark snapshot, and artifact manifest before first
write and again on readback. Foreign-key existence alone is not sufficient
evidence integrity: the report card must match the durable source contracts,
their stored hashes, normalized columns, completed run state, snapshot
coverage, authoritative metric summary, and artifact-manifest evidence. Caller
mismatches are rejected as source-coherence errors; corrupted persisted source
anchors are rejected as persistence corruption and are not repaired.

Because report cards are now durable, `ResearchReportCard` schema changes that
alter canonical `model_dump(mode="json")` output must not be introduced under
the same `schema_version` without an explicit migration or version-aware
deserialization policy.

A deterministic report card is factual evidence. A persisted `ResearchNote` is
a separate human-reviewed interpretation. The generated `research_note.md`
artifact, `ResearchReportCard`, and persisted `ResearchNote` are not
interchangeable.

## Deterministic Report-Card Comparison

`research_sdk.report_card_comparison` adds the pure C2a comparison boundary for
two supplied `ResearchReportCard` objects. Before assessment, C2a
canonicalizes each supplied card through `ResearchReportCard.model_validate`
over its JSON dump and verifies the natural `report_card_id` with the pure
`research_sdk.report_card_identity` helper. Stale, malformed, or structurally
invalid source cards are input-integrity failures, not incompatibility
assessments. It does not load persistence, SQLAlchemy, psycopg,
`research_sdk.experiment_recording`, `backtest_engine`, raw artifacts, files,
network services, or clocks.

The comparison policy versions are explicit and independent:
`research-comparison-compatibility-v1` for context assessment and
`research-comparison-metrics-v1` for numeric deltas. Comparison identity uses
`report-card-comparison-v1-<sha256>` over the comparison schema version, both
policy versions, and the ordered baseline and candidate report-card IDs.
Baseline/candidate order is meaningful, and deltas are `candidate - baseline`.

C2a distinguishes three statuses. `STRICT_COMPATIBLE` means required research
context and observed strategy/config lineage fields match.
`CONTEXT_COMPATIBLE` means required research context matches but one or more of
`strategy_id`, `strategy_version`, `config_hash`, or `parameter_hash` differs.
Those opaque lineage differences are reported as evidence facts only; current
hashes do not prove that exactly one strategy parameter changed or establish
causal attribution. `INCOMPATIBLE` means a required context dimension differs,
such as dates, frequency, data or benchmark snapshots, benchmark total return,
costs, slippage, leakage assumptions, random seed, engine version, source
limitations, or use restrictions.

Metrics-v1 compares only non-annualized authoritative report-card facts:
`total_return`, `excess_return`, `maximum_drawdown`, and
`number_of_trades`. Benchmark total return and observation count are context
invariants. Realized commission, realized slippage, and ending equity are not
compared in C2a because the report-card contract does not expose the initial
capital basis as structured evidence. CAGR, Sharpe, volatility, annualized
volatility, ranking, winner selection, and investment recommendations remain
out of scope.
Exported comparison value objects independently validate metric deltas as
deterministic `candidate - baseline` arithmetic and require compatibility
difference codes to match their canonical category, field path, and policy
order.

`research_sdk.report_card_comparison_query` adds the C2b persisted read-only
query boundary for ordered baseline/candidate report-card IDs. It loads each
card through `get_research_report_card(...)`, so B1b1 durable readback remains
the authority for persisted contract validity, report-card natural identity,
normalized columns, and source coherence before C2a runs. Missing report-card
inputs are query not-found errors rather than `INCOMPATIBLE` compatibility
results.

C2b calls C2a for compatibility and, only for compatible pairs, numeric
comparison output. For incompatible pairs, it preserves the C2a deterministic
compatibility assessment and returns no numeric comparison. It then reverse
reads linked ResearchNote IDs through
`get_research_note_ids_for_report_card(...)` and loads every linked note
through durable `get_research_note(...)` readback before projecting direct
review-state facts. The query does not join raw note rows, skip corrupt links,
query review events, choose a current or best note, classify authoritative
interpretations, rank strategies, or persist comparison results.

C2b review visibility is a read-time projection. Because immutable notes and
links may be appended later, the same report-card pair can retain the same C2a
comparison identity while returning additional linked review-state rows in a
later query. C2b therefore adds no query-result natural identity and no
generated timestamp. `risk_approval_required` is exposed only as persisted
metadata; it is not risk approval, paper-trading approval, live-trading
approval, trading authorization, or strategy acceptance.

Finalized single-result interpretations now use a normalized
`research_note_report_cards` association table. The `ResearchNote` contract
remains unchanged; report-card linkage is not embedded into the contract, so
existing note canonical serialization and whole-contract `contract_hash`
semantics remain stable. Generic `record_research_note` remains a permissive
low-level persistence primitive for drafts and candidates. The authoritative
Phase 1B interpretation boundary is
`record_finalized_research_interpretation`, which requires a finalized
`EXPERIMENT_RESULT` note, `APPROVED` embedded review metadata, a nonblank
reviewer ID, `HUMAN_OWNER` review role, reviewed timestamp, finalized-v1
deterministic note identity, and strict structured reference coherence with
the already persisted report card.

The finalized-v1 note ID is `research-note-finalized-v1-<sha256>` over the
semantic interpretation projection plus linked report-card IDs. Review
metadata, timestamps, body markdown, tags, and database `inserted_at` are
excluded from natural identity but remain protected by the immutable
whole-contract hash. Review events remain separate append-only audit history
and are not approval authority. Reviewer IDs are trusted workflow attribution,
not authentication. This workflow confers no risk approval, paper-trading
approval, live-trading approval, or strategy acceptance. Corrections create a
new note and use `supersedes_note_id`; prior finalized rows are not mutated.
Comparison notes with multiple report cards remain deferred.

## Roadmap Alignment

Phase 0 history is preserved in `docs/roadmap.md`. Phase 1A completion and
Phase 1B acceptance criteria are defined in `docs/roadmap-v0.2.md`.

This architecture document describes current boundaries and responsibilities.
It is not the canonical phase-gate document.
