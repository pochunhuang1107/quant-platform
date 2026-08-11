# Architecture

## Current Phase

Phase 1A - Reproducibility Foundation Complete.

Phase 1B - Research Workflow Layer is next. Current roadmap details live in
`docs/roadmap-v0.2.md`.

The platform remains research-only. It is not ready for production-data
research, paper trading, or live trading.

## Existing Structure

The repository now contains implemented reproducibility infrastructure and
several scaffold-only areas.

Implemented:

- `packages/research-sdk`: immutable contracts, schema exports, persistence
  helpers, PostgreSQL repository writes, and completed-experiment recording.
- `packages/backtest-engine`: deterministic synthetic ETF infrastructure
  baseline, artifact generation, and pure backtest-to-ledger mapping.
- `infra/db`: Alembic migrations and local PostgreSQL support.
- Deterministic synthetic ETF artifacts for the required run artifact set.
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
  research-engine execution for the current synthetic ETF infrastructure slice.
  It includes an importable offline QQQ baseline with SPY as a gross benchmark,
  explicit costs and slippage, Decimal accounting, deterministic identity,
  local artifact generation, and pure ledger-record mapping. It does not own
  SQLAlchemy, Postgres, experiment-ledger transactions, API workflows, paper
  trading, live trading, broker integrations, or performance claims.
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
