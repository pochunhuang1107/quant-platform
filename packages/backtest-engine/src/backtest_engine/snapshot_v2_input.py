"""Engine-side snapshot-v2 execution input loading."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict

from research_sdk.contracts.daily_market_data import CanonicalDailyBar
from research_sdk.daily_market_data_storage.serialization import (
    parse_canonical_daily_bars,
)
from research_sdk.daily_market_data_storage.verification_v2 import (
    VerifiedDailyMarketDataSnapshotV2,
    verify_daily_market_data_snapshot_bundle_v2,
)


class DailyMarketDataSnapshotV2InputError(ValueError):
    """Raised when snapshot-v2 execution input bytes cannot be loaded."""


class SnapshotV2InputModel(PydanticBaseModel):
    """Frozen operational model base for S3d2a snapshot inputs."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)


class LoadedDailyMarketDataSnapshotV2(SnapshotV2InputModel):
    """Verifier-produced snapshot-v2 facts plus bars parsed from the same bytes.

    Normal execution authority starts with ``load_daily_market_data_snapshot_v2``.
    Manually constructing this operational object is outside the normal
    loader-produced trust path.
    """

    verified_snapshot: VerifiedDailyMarketDataSnapshotV2
    bars: tuple[CanonicalDailyBar, ...]


def load_daily_market_data_snapshot_v2(
    files: Mapping[str, bytes],
) -> LoadedDailyMarketDataSnapshotV2:
    """Load a snapshot-v2 bundle from one exact in-memory byte mapping."""

    copied_files = _copy_bundle_files(files)
    try:
        verified = verify_daily_market_data_snapshot_bundle_v2(copied_files)
        bars = parse_canonical_daily_bars(copied_files["bars.jsonl"])
    except Exception as exc:
        raise DailyMarketDataSnapshotV2InputError(
            "snapshot-v2 execution input failed verification or bar parsing"
        ) from exc
    return LoadedDailyMarketDataSnapshotV2(
        verified_snapshot=verified,
        bars=bars,
    )


def _copy_bundle_files(files: Mapping[str, bytes]) -> dict[str, bytes]:
    copied_files: dict[str, bytes] = {}
    for path, content in files.items():
        if type(path) is not str or type(content) is not bytes:
            raise DailyMarketDataSnapshotV2InputError(
                "snapshot-v2 execution input must map string paths to bytes"
            )
        copied_files[path] = content
    return copied_files


__all__ = [
    "DailyMarketDataSnapshotV2InputError",
    "LoadedDailyMarketDataSnapshotV2",
    "load_daily_market_data_snapshot_v2",
]
