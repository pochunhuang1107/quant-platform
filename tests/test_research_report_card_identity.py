from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from backtest_engine import canonical_json_bytes
from research_sdk.report_card_identity import (
    ResearchReportCardIdentityError,
    derive_research_report_card_id_from_fields,
    verify_research_report_card_identity,
)
from test_deterministic_etf_report_card import (
    EXPECTED_REPORT_CARD_ID,
    mapped_records,
    report_card_from_records,
)


def test_generic_identity_helper_preserves_b1a_golden_id(tmp_path: Path) -> None:
    records = mapped_records(tmp_path)
    stable_run = records.run.model_copy(
        update={
            "config_hash": f"sha256:{'1' * 64}",
            "parameter_hash": f"sha256:{'2' * 64}",
            "artifact_manifest_hash": f"sha256:{'3' * 64}",
        }
    )
    stable_snapshot = records.snapshot.model_copy(
        update={"content_hash": f"sha256:{'4' * 64}"}
    )

    report_card_id = derive_research_report_card_id_from_fields(
        source_run_id=stable_run.run_id,
        schema_version="1.0.0",
        derivation_policy_version="deterministic-etf-report-card-v1",
        data_snapshot_content_hash=stable_snapshot.content_hash,
        benchmark_snapshot_content_hash=stable_snapshot.content_hash,
        config_hash=stable_run.config_hash,
        parameter_hash=stable_run.parameter_hash,
        artifact_manifest_hash=stable_run.artifact_manifest_hash,
    )

    assert report_card_id == EXPECTED_REPORT_CARD_ID


def test_generated_report_card_verifies_with_generic_identity_helper(
    tmp_path: Path,
) -> None:
    report_card = report_card_from_records(mapped_records(tmp_path))

    verify_research_report_card_identity(report_card)


def test_stale_report_card_id_is_rejected(tmp_path: Path) -> None:
    report_card = report_card_from_records(mapped_records(tmp_path))
    stale = report_card.model_copy(update={"report_card_id": f"report-card-{'9' * 64}"})

    with pytest.raises(ResearchReportCardIdentityError, match="stale|inconsistent"):
        verify_research_report_card_identity(stale)


def test_changed_identity_input_is_rejected(tmp_path: Path) -> None:
    report_card = report_card_from_records(mapped_records(tmp_path))
    changed_lineage = report_card.lineage.model_copy(
        update={"config_hash": f"sha256:{'9' * 64}"}
    )
    stale = report_card.model_copy(update={"lineage": changed_lineage})

    with pytest.raises(ResearchReportCardIdentityError, match="stale|inconsistent"):
        verify_research_report_card_identity(stale)


def test_changed_non_identity_metric_keeps_natural_id(tmp_path: Path) -> None:
    report_card = report_card_from_records(mapped_records(tmp_path))
    changed_metrics = report_card.metrics.model_copy(
        update={"total_return": "0.000000000000"}
    )
    changed_report_card = report_card.model_copy(update={"metrics": changed_metrics})

    verify_research_report_card_identity(changed_report_card)

    assert changed_report_card.report_card_id == report_card.report_card_id
    assert canonical_json_bytes(changed_report_card) != canonical_json_bytes(
        report_card
    )


def test_malformed_report_card_id_is_rejected(tmp_path: Path) -> None:
    report_card = report_card_from_records(mapped_records(tmp_path))
    malformed = report_card.model_copy(update={"report_card_id": "report-card-short"})

    with pytest.raises(ResearchReportCardIdentityError, match="report_card_id"):
        verify_research_report_card_identity(malformed)


def test_pure_identity_helper_import_boundary() -> None:
    code = """
import sys
from research_sdk.report_card_identity import verify_research_report_card_identity

forbidden = {
    "sqlalchemy",
    "psycopg",
    "research_sdk.persistence",
    "research_sdk.experiment_recording",
    "backtest_engine",
}
loaded = sorted(name for name in forbidden if name in sys.modules)
if loaded:
    raise SystemExit(f"forbidden modules loaded: {loaded}")
assert verify_research_report_card_identity is not None
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr or result.stdout
