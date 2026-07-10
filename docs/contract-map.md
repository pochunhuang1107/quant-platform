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
| `ResearchNote` | `research_sdk.contracts.research_notes.ResearchNote` | `packages/research-sdk/src/research_sdk/contracts/research_notes.py` | `packages/research-sdk/schema/research_note.schema.json` | `tests/fixtures/contracts/research_note.json` | Structured research note and decision record. |

## Contract Responsibility Map

| Contract | Owner/producer later | Consumer later | Current validation level | Explicitly deferred behavior |
| --- | --- | --- | --- | --- |
| `VersionedContract` | Contract authors when adding schema-backed models. | Schema exporter, downstream validators, compatibility checks. | Pydantic validation, JSON schema export, committed schema sync, roundtrip fixture tests. | Schema migration execution, compatibility policy enforcement, database migration behavior. |
| `ReviewMetadata` | Research review workflow and human/risk review tools later. | Experiment ledger, research notes, report generation, review workflow. | Pydantic validation, JSON schema export, committed schema sync, roundtrip fixture tests. | Approval workflow execution, trading approval, reviewer identity verification, external approval record checks. |
| `ExperimentRunRecord` | Backtest/research runner after Phase 1 integration. | Comparison UI, report generation, research review workflow, future ledger persistence. | Pydantic validation, JSON schema export, committed schema sync, roundtrip fixture tests, focused model tests. | Database persistence, run execution, artifact writing, trading approval, external ID existence checks. |
| `RunArtifactManifest` | Backtest/research runner and artifact writer after Phase 1 integration. | Artifact validators, report generation, research review workflow, future storage indexing. | Pydantic validation, JSON schema export, committed schema sync, roundtrip fixture tests, focused model tests. | Artifact/file IO, storage reads or writes, hash verification, parquet inspection, artifact upload. |
| `DataSnapshotManifest` | Data engine after Phase 1 integration. | Backtest/research runner, feature generation, experiment ledger, leakage review. | Pydantic validation, JSON schema export, committed schema sync, roundtrip fixture tests, focused model tests. | Data ingestion, vendor API calls, storage IO, content hash verification, data quality scans, external snapshot existence checks. |
| `ResearchNote` | Research authoring and report generation tools later. | Research review workflow, comparison UI, reports, future search/indexing after approval. | Pydantic validation, JSON schema export, committed schema sync, roundtrip fixture tests, focused model tests. | Markdown rendering/parsing, LLM summarization, embeddings, semantic memory, knowledge graph behavior, agent workflow execution. |

## Contract Relationships

```text
DataSnapshotManifest
  snapshot_id
    -> ExperimentRunRecord.data_snapshot_id

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

## Current Schema And Fixture Files

Current schema files:

- `packages/research-sdk/schema/versioned_contract.schema.json`
- `packages/research-sdk/schema/review_metadata.schema.json`
- `packages/research-sdk/schema/experiment_run_record.schema.json`
- `packages/research-sdk/schema/run_artifact_manifest.schema.json`
- `packages/research-sdk/schema/data_snapshot_manifest.schema.json`
- `packages/research-sdk/schema/research_note.schema.json`

Current fixture files:

- `tests/fixtures/contracts/versioned_contract.json`
- `tests/fixtures/contracts/review_metadata.json`
- `tests/fixtures/contracts/experiment_run_record.json`
- `tests/fixtures/contracts/run_artifact_manifest.json`
- `tests/fixtures/contracts/data_snapshot_manifest.json`
- `tests/fixtures/contracts/research_note.json`

`tests/test_contract_roundtrip_validation.py` asserts that the fixture/schema
contract matrix matches `SCHEMA_EXPORTS`.

## Supporting Nested Models

Supporting models appear inside top-level contracts and should not be treated as
standalone top-level contracts unless they receive their own schema and fixture.
Current supporting models include `RunArtifactEntry`, `AssetUniverseReference`,
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
