"""Export JSON Schema artifacts for allowlisted research SDK contracts."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from research_sdk.contracts.artifacts import RunArtifactManifest
from research_sdk.contracts.base import BaseContractModel
from research_sdk.contracts.data_snapshots import DataSnapshotManifest
from research_sdk.contracts.ledger import ExperimentRunRecord
from research_sdk.contracts.review import ReviewMetadata
from research_sdk.contracts.schema import VersionedContract

SCHEMA_EXPORTS: Final[dict[str, type[BaseContractModel]]] = {
    "versioned_contract.schema.json": VersionedContract,
    "review_metadata.schema.json": ReviewMetadata,
    "experiment_run_record.schema.json": ExperimentRunRecord,
    "run_artifact_manifest.schema.json": RunArtifactManifest,
    "data_snapshot_manifest.schema.json": DataSnapshotManifest,
}


def render_schema(model: type[BaseContractModel]) -> str:
    """Render a Pydantic model JSON Schema in canonical repository format."""

    schema = model.model_json_schema(mode="validation")
    return f"{json.dumps(schema, indent=2, sort_keys=True)}\n"


def generate_schema_files() -> dict[str, str]:
    """Return generated schema filenames and canonical JSON contents."""

    return {
        filename: render_schema(model)
        for filename, model in sorted(SCHEMA_EXPORTS.items())
    }


def write_schema_files(output_dir: Path) -> list[Path]:
    """Write generated schema files to output_dir."""

    output_dir.mkdir(parents=True, exist_ok=True)
    written_paths: list[Path] = []

    for filename, content in generate_schema_files().items():
        output_path = output_dir / filename
        output_path.write_text(content, encoding="utf-8")
        written_paths.append(output_path)

    return written_paths


def check_schema_files(output_dir: Path) -> list[str]:
    """Return concise sync errors for missing or stale generated schemas."""

    errors: list[str] = []

    for filename, expected_content in generate_schema_files().items():
        output_path = output_dir / filename
        if not output_path.exists():
            errors.append(f"missing schema file: {output_path}")
            continue

        actual_content = output_path.read_text(encoding="utf-8")
        if actual_content != expected_content:
            errors.append(f"stale schema file: {output_path}")

    return errors


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments for module execution."""

    parser = argparse.ArgumentParser(
        description="Export JSON Schema files for allowlisted research SDK contracts."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("packages/research-sdk/schema"),
        help="Directory where schema files are written or checked.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check committed schema files instead of writing them.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the JSON Schema exporter."""

    args = parse_args(argv)

    if args.check:
        errors = check_schema_files(args.output_dir)
        if errors:
            print("JSON Schema files are out of sync:", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
            print(
                "Run: python -m research_sdk.contracts.json_schema "
                f"--output-dir {args.output_dir}",
                file=sys.stderr,
            )
            return 1

        print(f"JSON Schema files are up to date in {args.output_dir}")
        return 0

    written_paths = write_schema_files(args.output_dir)
    for written_path in written_paths:
        print(f"wrote {written_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
