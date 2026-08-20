# Contract Map

## Purpose

This is the current Phase 1 contract map. It maps schema-backed Python models to
their JSON schemas and test fixtures so contract ownership, validation coverage,
and deferred behavior are visible in one place.

This page is documentation-only. The contracts define reproducibility metadata
and validation boundaries for research records, run artifacts, data snapshots,
research notes, and review metadata. They do not perform IO, persistence,
execution, approval workflows, trading, or external validation.

## Contract Inventory

| Contract | Python model | Source module | JSON schema | Example fixture | Primary purpose |
| --- | --- | --- | --- | --- | --- |
| `VersionedContract` | `research_sdk.contracts.schema.VersionedContract` | `packages/research-sdk/src/research_sdk/contracts/schema.py` | `packages/research-sdk/schema/versioned_contract.schema.json` | `tests/fixtures/contracts/versioned_contract.json` | Shared schema version base contract. |
| `ReviewMetadata` | `research_sdk.contracts.review.ReviewMetadata` | `packages/research-sdk/src/research_sdk/contracts/review.py` | `packages/research-sdk/schema/review_metadata.schema.json` | `tests/fixtures/contracts/review_metadata.json` | Review state and risk-review metadata only. |
| `ExperimentRunRecord` | `research_sdk.contracts.ledger.ExperimentRunRecord` | `packages/research-sdk/src/research_sdk/contracts/ledger.py` | `packages/research-sdk/schema/experiment_run_record.schema.json` | `tests/fixtures/contracts/experiment_run_record.json` | Reproducible experiment/run ledger record. |
| `RunArtifactManifest` | `research_sdk.contracts.artifacts.RunArtifactManifest` | `packages/research-sdk/src/research_sdk/contracts/artifacts.py` | `packages/research-sdk/schema/run_artifact_manifest.schema.json` | `tests/fixtures/contracts/run_artifact_manifest.json` | Declared manifest of expected run artifacts. |
| `DataSnapshotManifest` | `research_sdk.contracts.data_snapshots.DataSnapshotManifest` | `packages/research-sdk/src/research_sdk/contracts/data_snapshots.py` | `packages/research-sdk/schema/data_snapshot_manifest.schema.json` | `tests/fixtures/contracts/data_snapshot_manifest.json` | Reproducible point-in-time dataset snapshot metadata. |
| `DailyMarketDataPolicy` | `research_sdk.contracts.daily_market_data.DailyMarketDataPolicy` | `packages/research-sdk/src/research_sdk/contracts/daily_market_data.py` | `packages/research-sdk/schema/daily_market_data_policy.schema.json` | `tests/fixtures/contracts/daily_market_data_policy.json` | Provider-neutral daily market-data policy for curated execution bars. |
| `DailyMarketDataQualityReport` | `research_sdk.contracts.daily_market_data.DailyMarketDataQualityReport` | `packages/research-sdk/src/research_sdk/contracts/daily_market_data.py` | `packages/research-sdk/schema/daily_market_data_quality_report.schema.json` | `tests/fixtures/contracts/daily_market_data_quality_report.json` | Deterministic quality evidence for one canonical daily instrument dataset. |
| `DailyMarketDataCorporateActionEvidence` | `research_sdk.contracts.daily_market_data_economics.DailyMarketDataCorporateActionEvidence` | `packages/research-sdk/src/research_sdk/contracts/daily_market_data_economics.py` | `packages/research-sdk/schema/daily_market_data_corporate_action_evidence.schema.json` | `tests/fixtures/contracts/daily_market_data_corporate_action_evidence.json` | Complete checked provider-neutral corporate-action economic evidence for one daily instrument and coverage period. |
| `DailyMarketDataResearchProfile` | `research_sdk.contracts.daily_market_data_economics.DailyMarketDataResearchProfile` | `packages/research-sdk/src/research_sdk/contracts/daily_market_data_economics.py` | `packages/research-sdk/schema/daily_market_data_research_profile.schema.json` | `tests/fixtures/contracts/daily_market_data_research_profile.json` | Versioned deterministic daily ETF research-data policy requirements, not human approval. |
| `DailyMarketDataExpectedSessions` | `research_sdk.contracts.daily_market_data_snapshots.DailyMarketDataExpectedSessions` | `packages/research-sdk/src/research_sdk/contracts/daily_market_data_snapshots.py` | `packages/research-sdk/schema/daily_market_data_expected_sessions.schema.json` | `tests/fixtures/contracts/daily_market_data_expected_sessions.json` | Exact expected-session authority used for daily market-data quality validation. |
| `DailyMarketDataSnapshotProvenance` | `research_sdk.contracts.daily_market_data_snapshots.DailyMarketDataSnapshotProvenance` | `packages/research-sdk/src/research_sdk/contracts/daily_market_data_snapshots.py` | `packages/research-sdk/schema/daily_market_data_snapshot_provenance.schema.json` | `tests/fixtures/contracts/daily_market_data_snapshot_provenance.json` | Source/capture lineage bound into immutable daily market-data snapshot identity. |
| `DailyMarketDataSnapshotBundleManifest` | `research_sdk.contracts.daily_market_data_snapshots.DailyMarketDataSnapshotBundleManifest` | `packages/research-sdk/src/research_sdk/contracts/daily_market_data_snapshots.py` | `packages/research-sdk/schema/daily_market_data_snapshot_bundle_manifest.schema.json` | `tests/fixtures/contracts/daily_market_data_snapshot_bundle_manifest.json` | Dataset-specific file-integrity manifest for an S3b1 daily market-data snapshot bundle. |
| `DailyMarketDataBarSourceProvenanceV2` | `research_sdk.contracts.daily_market_data_snapshots_v2.DailyMarketDataBarSourceProvenanceV2` | `packages/research-sdk/src/research_sdk/contracts/daily_market_data_snapshots_v2.py` | `packages/research-sdk/schema/daily_market_data_bar_source_provenance_v2.schema.json` | `tests/fixtures/contracts/daily_market_data_bar_source_provenance_v2.json` | Bar-only source/capture authority for a snapshot-v2 bundle. |
| `DailyMarketDataSnapshotBundleManifestV2` | `research_sdk.contracts.daily_market_data_snapshots_v2.DailyMarketDataSnapshotBundleManifestV2` | `packages/research-sdk/src/research_sdk/contracts/daily_market_data_snapshots_v2.py` | `packages/research-sdk/schema/daily_market_data_snapshot_bundle_manifest_v2.schema.json` | `tests/fixtures/contracts/daily_market_data_snapshot_bundle_manifest_v2.json` | Dataset-specific file-integrity manifest for an S3c2a daily market-data snapshot-v2 bundle. |
| `ResearchNote` | `research_sdk.contracts.research_notes.ResearchNote` | `packages/research-sdk/src/research_sdk/contracts/research_notes.py` | `packages/research-sdk/schema/research_note.schema.json` | `tests/fixtures/contracts/research_note.json` | Structured research note and decision record. |

## Contract Responsibility Map

| Contract | Owner/producer later | Consumer later | Current validation level | Explicitly deferred behavior |
| --- | --- | --- | --- | --- |
| `VersionedContract` | Contract authors when adding schema-backed models. | Schema exporter, downstream validators, compatibility checks. | Pydantic validation, JSON schema export, committed schema sync, roundtrip fixture tests. | Schema migration execution, compatibility policy enforcement, database migration behavior. |
| `ReviewMetadata` | Research review workflow and human/risk review tools later. | Experiment ledger, research notes, report generation, review workflow. | Pydantic validation, JSON schema export, committed schema sync, roundtrip fixture tests. | Approval workflow execution, trading approval, reviewer identity verification, external approval record checks. |
| `ExperimentRunRecord` | Backtest/research runner after Phase 1 integration. | Comparison UI, report generation, research review workflow, future ledger persistence. | Pydantic validation, JSON schema export, committed schema sync, roundtrip fixture tests, focused model tests. | Database persistence, run execution, artifact writing, trading approval, external ID existence checks. |
| `RunArtifactManifest` | Backtest/research runner and artifact writer after Phase 1 integration. | Artifact validators, report generation, research review workflow, future storage indexing. | Pydantic validation, JSON schema export, committed schema sync, roundtrip fixture tests, focused model tests. | Artifact/file IO, storage reads or writes, hash verification, parquet inspection, artifact upload. |
| `DataSnapshotManifest` | Data engine after Phase 1 integration. | Backtest/research runner, feature generation, experiment ledger, leakage review. | Pydantic validation, JSON schema export, committed schema sync, roundtrip fixture tests, focused model tests. | Data ingestion, vendor API calls, storage IO, content hash verification, data quality scans, external snapshot existence checks. |
| `DailyMarketDataPolicy` | Research/data policy layer before curated snapshot creation. | Data engine, snapshot validation, leakage review, future backtest input adapters. | Pydantic validation, JSON schema export, committed schema sync, roundtrip fixture tests, focused model tests. | Provider selection, provider calls, storage adapters, calendar-source integration, benchmark calculation, strategy execution, split/dividend accounting. |
| `DailyMarketDataQualityReport` | Pure daily market-data quality service after canonical bars and expected sessions are supplied. | Snapshot validation, experiment gate checks, future report generation. | Pydantic validation, JSON schema export, committed schema sync, roundtrip fixture tests, focused model tests. | Calendar derivation, provider/source provenance, storage inspection, file-byte verification, real-data authority, paper/live approval. |
| `DailyMarketDataCorporateActionEvidence` | Provider-neutral callers; S3c3c3 Massive bridge from offline adapted events and exact canonical CA source-manifest bytes. | S3c2a snapshot-v2 identity/bundle planning and verification, future economic evidence/profile checks, future backtest input adapters. | Pydantic validation, JSON schema export, committed schema sync, roundtrip fixture tests, focused S3c1 semantic-hash/coherence and S3c3c3 bridge-authority tests. | Provider calls, provider approval, licensing approval, profile compatibility/readiness approval, split/dividend accounting. |
| `DailyMarketDataResearchProfile` | Research/data policy authoring after human owner chooses candidate requirements. | Future S3c2 readiness gate, economic evidence/profile checks, future report and strategy validation. | Pydantic validation, JSON schema export, committed schema sync, roundtrip fixture tests, focused S3c1 profile tests. | Human approval workflow, provider selection, license acceptance, benchmark policy execution, strategy validation, paper/live approval. |
| `DailyMarketDataExpectedSessions` | Caller or future calendar/session authority adapter. | S3b1 snapshot planner, quality verification, readback verifier. | Pydantic validation, JSON schema export, committed schema sync, roundtrip fixture tests, focused model tests. | Calendar derivation, exchange-calendar provider selection, holiday inference, network/source lookup. |
| `DailyMarketDataSnapshotProvenance` | S3b1 snapshot planner from caller-supplied source/capture facts and exact source bytes. | Snapshot identity, manifest construction, readback verifier, future audit tools. | Pydantic validation, JSON schema export, committed schema sync, roundtrip fixture tests, focused model tests. | Source truth verification, raw vendor evidence archival, credential management, licensing enforcement, corporate-action accounting. |
| `DailyMarketDataSnapshotBundleManifest` | S3b1 pure planner after final bundle payload bytes are rendered. | S3b1 in-memory verifier and later S3b2 local filesystem verifier. | Pydantic validation, JSON schema export, committed schema sync, roundtrip fixture tests, focused model tests. | Filesystem publication, atomic rename, object storage, external signature/anchoring, artifact-run manifest semantics. |
| `DailyMarketDataBarSourceProvenanceV2` | S3c2a snapshot-v2 planner from caller-supplied facts and planner-derived byte authority; S3c3c3 Massive bridge supplies canonical bars separately from exact verified `BAR_RESPONSE` authority. | Snapshot-v2 identity, manifest construction, bundle-v2 verifier, future audit tools. | Pydantic validation, JSON schema export, committed schema sync, roundtrip fixture tests, focused S3c2a contract/identity/planning and S3c3c3 bridge-authority tests. | Source truth beyond verified capture, provider calls, credential management, licensing enforcement, filesystem publication, profile compatibility, corporate-action accounting. |
| `DailyMarketDataSnapshotBundleManifestV2` | S3c2a pure planner after final bundle-v2 payload bytes are rendered. | S3c2a in-memory verifier and S3c2b/S3c3c2 local exact-byte filesystem readback. | Pydantic validation, JSON schema export, committed schema sync, roundtrip fixture tests, focused S3c2a verification and local exact-byte readback tests. | Object storage, external signature/anchoring, profile compatibility/readiness, artifact-run manifest semantics, downstream orchestration. |
| `ResearchNote` | Research authoring and report generation tools later. | Research review workflow, comparison UI, reports, future search/indexing after approval. | Pydantic validation, JSON schema export, committed schema sync, roundtrip fixture tests, focused model tests. | Markdown rendering/parsing, LLM summarization, embeddings, semantic memory, knowledge graph behavior, agent workflow execution. |

## Contract Relationships

```text
DataSnapshotManifest
  snapshot_id
    -> ExperimentRunRecord.data_snapshot_id

DailyMarketDataPolicy + DailyMarketDataQualityReport
  policy_id + content_hash + coverage + observed_session_count + one symbol
    -> validate single-instrument DataSnapshotManifest metadata before experiment use

DailyMarketDataExpectedSessions + DailyMarketDataSnapshotProvenance
  policy/session/provenance hashes + S3a semantic content hash
    -> daily-market-data-snapshot-v1-* natural identity
    -> DataSnapshotManifest constructed by pure S3b1 planner

DailyMarketDataCorporateActionEvidence + DailyMarketDataResearchProfile
  corporate-action semantic hash + deterministic evidence/profile coherence
    -> S3c1 economic evidence semantics only
    -> future S3c2b daily-market-data snapshot/profile compatibility gate
    -> does not alter daily-market-data-snapshot-v1-* identity

DailyMarketDataBarSourceProvenanceV2 + DailyMarketDataCorporateActionEvidence
  bar-source authority hash + corporate-action semantic/evidence authority hashes
    -> daily-market-data-snapshot-v2-* natural identity
    -> DataSnapshotManifest constructed by pure S3c2a planner
    -> S3c3c3 Massive bridge derives bar authority from exact BAR_RESPONSE bytes
       and CA authority from exact ca-source-manifest.json bytes
    -> S3c3c3 compatible acquisition vintage uses explicit batch + per-role
       request specification; no new durable contract

DailyMarketDataSnapshotBundleManifest
  payload file byte hashes and sizes, excluding bundle-manifest.json itself
    -> pure in-memory readback verification of S3b1 bundle bytes

DailyMarketDataSnapshotBundleManifestV2
  payload file byte hashes and sizes, excluding bundle-manifest.json itself
    -> pure in-memory readback verification of S3c2a bundle-v2 bytes
    -> S3c3c2 immutable exact-byte local readback; no new durable contract

RunArtifactManifest
  artifact_root_uri + artifacts[]
    -> ExperimentRunRecord.artifact_manifest_uri
    -> ExperimentRunRecord.artifact_manifest_hash
    -> includes research_note.md

ExperimentRunRecord
  experiment_id + run_id + data_snapshot_id + benchmark.snapshot_id
    -> ResearchNote.references.*

ReviewMetadata
  -> embedded in ExperimentRunRecord.review
  -> embedded in ResearchNote.review
```

References are declarative only. Current contracts do not validate that
referenced IDs, URIs, files, hashes, or snapshots actually exist. Hash fields are
declared metadata only in this phase.

See [Experiment Ledger DB Plan](experiment-ledger-db-plan.md) for how
schema-backed contracts map to current and future Postgres tables.
As of PR 14, `ResearchNote` is projected into `research_notes`, and
`ReviewMetadata` is projected into generic `review_events` audit metadata using
`subject_type`, `subject_id`, and `raw_review`.

## Current Schema And Fixture Files

Current schema files:

- `packages/research-sdk/schema/versioned_contract.schema.json`
- `packages/research-sdk/schema/review_metadata.schema.json`
- `packages/research-sdk/schema/experiment_run_record.schema.json`
- `packages/research-sdk/schema/run_artifact_manifest.schema.json`
- `packages/research-sdk/schema/data_snapshot_manifest.schema.json`
- `packages/research-sdk/schema/daily_market_data_policy.schema.json`
- `packages/research-sdk/schema/daily_market_data_quality_report.schema.json`
- `packages/research-sdk/schema/daily_market_data_corporate_action_evidence.schema.json`
- `packages/research-sdk/schema/daily_market_data_research_profile.schema.json`
- `packages/research-sdk/schema/daily_market_data_expected_sessions.schema.json`
- `packages/research-sdk/schema/daily_market_data_snapshot_provenance.schema.json`
- `packages/research-sdk/schema/daily_market_data_snapshot_bundle_manifest.schema.json`
- `packages/research-sdk/schema/daily_market_data_bar_source_provenance_v2.schema.json`
- `packages/research-sdk/schema/daily_market_data_snapshot_bundle_manifest_v2.schema.json`
- `packages/research-sdk/schema/research_note.schema.json`

Current fixture files:

- `tests/fixtures/contracts/versioned_contract.json`
- `tests/fixtures/contracts/review_metadata.json`
- `tests/fixtures/contracts/experiment_run_record.json`
- `tests/fixtures/contracts/run_artifact_manifest.json`
- `tests/fixtures/contracts/data_snapshot_manifest.json`
- `tests/fixtures/contracts/daily_market_data_policy.json`
- `tests/fixtures/contracts/daily_market_data_quality_report.json`
- `tests/fixtures/contracts/daily_market_data_corporate_action_evidence.json`
- `tests/fixtures/contracts/daily_market_data_research_profile.json`
- `tests/fixtures/contracts/daily_market_data_expected_sessions.json`
- `tests/fixtures/contracts/daily_market_data_snapshot_provenance.json`
- `tests/fixtures/contracts/daily_market_data_snapshot_bundle_manifest.json`
- `tests/fixtures/contracts/daily_market_data_bar_source_provenance_v2.json`
- `tests/fixtures/contracts/daily_market_data_snapshot_bundle_manifest_v2.json`
- `tests/fixtures/contracts/research_note.json`

`tests/test_contract_roundtrip_validation.py` asserts that the fixture/schema
contract matrix matches `SCHEMA_EXPORTS`.

## Supporting Nested Models

Supporting models appear inside top-level contracts and should not be treated as
standalone top-level contracts unless they receive their own schema and fixture.
Current supporting models include `RunArtifactEntry`,
`DailyMarketDataInstrument`, `CanonicalDailyBar`,
`DailyMarketDataCashDistribution`, `DailyMarketDataSplit`,
`DailyMarketDataUnsupportedCorporateAction`,
`DailyMarketDataSnapshotFileEntry`, `DailyMarketDataSnapshotFileEntryV2`,
`AssetUniverseReference`,
`BenchmarkReference`, `RunEnvironment`, `RandomSeedMetadata`, `TimeRange`,
`ResearchHypothesis`, `ResearchNoteReferences`, and `ResearchDecision`.

`ReviewMetadata` is both standalone schema-backed metadata and embedded metadata
inside `ExperimentRunRecord.review` and `ResearchNote.review`.

## How To Add A New Contract

- Add the Pydantic model under `packages/research-sdk/src/research_sdk/contracts/`.
- Reuse `BaseContractModel`, `VersionedContract`, `UtcDatetime`,
  `NonEmptyString`, and existing enums when possible.
- Add enums only when the lifecycle or state vocabulary is stable enough.
- Export the model from `research_sdk.contracts` when it is public.
- Register the model in `SCHEMA_EXPORTS` if it is a top-level schema-backed contract.
- Generate and commit the schema file.
- Add focused validation tests.
- Add or update roundtrip fixture tests.
- Update `docs/contract-map.md`.
- Run validation commands.

## What Not To Put In Contracts

Contracts must not contain:

- Database persistence logic.
- Artifact/file IO.
- Storage reads/writes.
- Data ingestion.
- Vendor API calls.
- Hash verification.
- Broker integration.
- Paper/live trading execution.
- Credentials.
- Strategy execution.
- UI/editor behavior.
- Markdown rendering/parsing.
- Embeddings.
- Semantic memory.
- Knowledge graph behavior.
- Search/indexing.
- LLM summarization.
- Agent workflow execution.
- Financial approval automation.

## Validation Commands

Run these commands for contract documentation changes:

```bash
git diff --check
uv run python -m research_sdk.contracts.json_schema --output-dir packages/research-sdk/schema --check
uv run pytest tests/test_contract_roundtrip_validation.py tests/test_contract_json_schema_export.py
uv run pytest
```

If `uv` is unavailable on `PATH`, use `python -m uv` as the equivalent command
prefix.
