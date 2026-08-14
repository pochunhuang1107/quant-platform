"""Pure in-memory verification for daily market-data source captures."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from research_sdk.daily_market_data_source_capture.identity import (
    derive_daily_market_data_source_capture_id,
)
from research_sdk.daily_market_data_source_capture.models import (
    CA_SOURCE_CAPTURE_ROLES,
    CA_SOURCE_MANIFEST_DOMAIN,
    CA_SOURCE_MANIFEST_PATH,
    CA_SOURCE_MANIFEST_VERSION,
    CAPTURE_MANIFEST_PATH,
    SOURCE_CAPTURE_ID_PATTERN,
    SOURCE_CAPTURE_MEMBER_PATHS,
    SOURCE_CAPTURE_REQUIRED_PATHS,
    DailyMarketDataCASourceManifest,
    DailyMarketDataSourceCaptureManifest,
    DailyMarketDataSourceCaptureRole,
)
from research_sdk.daily_market_data_source_capture.serialization import (
    parse_ca_source_manifest,
    parse_capture_manifest,
    render_ca_source_manifest,
)
from research_sdk.daily_market_data_storage.serialization import sha256_bytes


class DailyMarketDataSourceCaptureVerificationError(ValueError):
    """Raised when source-capture in-memory bytes are incoherent."""


@dataclass(frozen=True)
class VerifiedDailyMarketDataSourceCapture:
    """Verified source-capture facts and exact authoritative bytes."""

    capture_id: str
    capture_manifest: DailyMarketDataSourceCaptureManifest
    capture_manifest_bytes: bytes
    ca_source_manifest: DailyMarketDataCASourceManifest
    ca_source_manifest_bytes: bytes
    member_bytes: Mapping[DailyMarketDataSourceCaptureRole, bytes]
    ca_source_content_hash: str
    ca_source_size_bytes: int


def verify_daily_market_data_source_capture(
    files: Mapping[str, bytes],
) -> VerifiedDailyMarketDataSourceCapture:
    """Verify complete source-capture authority from in-memory bytes."""

    copied_files = _copy_and_validate_file_map(files)
    capture_manifest = _parse_capture_manifest(copied_files[CAPTURE_MANIFEST_PATH])
    ca_source_manifest = _parse_ca_source_manifest(
        copied_files[CA_SOURCE_MANIFEST_PATH]
    )
    _verify_capture_identity(capture_manifest)
    _verify_member_bytes(copied_files, capture_manifest)
    _verify_ca_source_manifest(
        capture_manifest=capture_manifest,
        ca_source_manifest=ca_source_manifest,
        ca_source_manifest_bytes=copied_files[CA_SOURCE_MANIFEST_PATH],
    )
    member_bytes = MappingProxyType(
        {role: copied_files[path] for role, path in SOURCE_CAPTURE_MEMBER_PATHS.items()}
    )
    return VerifiedDailyMarketDataSourceCapture(
        capture_id=capture_manifest.capture_id,
        capture_manifest=capture_manifest,
        capture_manifest_bytes=copied_files[CAPTURE_MANIFEST_PATH],
        ca_source_manifest=ca_source_manifest,
        ca_source_manifest_bytes=copied_files[CA_SOURCE_MANIFEST_PATH],
        member_bytes=member_bytes,
        ca_source_content_hash=sha256_bytes(copied_files[CA_SOURCE_MANIFEST_PATH]),
        ca_source_size_bytes=len(copied_files[CA_SOURCE_MANIFEST_PATH]),
    )


def _copy_and_validate_file_map(files: Mapping[str, bytes]) -> dict[str, bytes]:
    copied: dict[str, bytes] = {}
    for path, content in files.items():
        if type(path) is not str or type(content) is not bytes:
            raise DailyMarketDataSourceCaptureVerificationError(
                "source-capture files must map string paths to bytes"
            )
        copied[path] = content
    expected = set(SOURCE_CAPTURE_REQUIRED_PATHS)
    actual = set(copied)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise DailyMarketDataSourceCaptureVerificationError(
            f"source-capture file set mismatch; missing={missing}; "
            f"unexpected={unexpected}"
        )
    return copied


def _parse_capture_manifest(data: bytes) -> DailyMarketDataSourceCaptureManifest:
    try:
        return parse_capture_manifest(data)
    except Exception as exc:
        raise DailyMarketDataSourceCaptureVerificationError(
            "capture-manifest.json failed verification"
        ) from exc


def _parse_ca_source_manifest(data: bytes) -> DailyMarketDataCASourceManifest:
    try:
        return parse_ca_source_manifest(data)
    except Exception as exc:
        raise DailyMarketDataSourceCaptureVerificationError(
            "ca-source-manifest.json failed verification"
        ) from exc


def _verify_capture_identity(
    capture_manifest: DailyMarketDataSourceCaptureManifest,
) -> None:
    if SOURCE_CAPTURE_ID_PATTERN.fullmatch(capture_manifest.capture_id) is None:
        raise DailyMarketDataSourceCaptureVerificationError(
            "capture_id has invalid source-capture ID format"
        )
    expected_capture_id = derive_daily_market_data_source_capture_id(
        capture_manifest.identity_authority()
    )
    if capture_manifest.capture_id != expected_capture_id:
        raise DailyMarketDataSourceCaptureVerificationError(
            "capture_id does not match canonical identity authority"
        )


def _verify_member_bytes(
    files: Mapping[str, bytes],
    capture_manifest: DailyMarketDataSourceCaptureManifest,
) -> None:
    metadata_by_role = {member.role: member for member in capture_manifest.members}
    for role, path in SOURCE_CAPTURE_MEMBER_PATHS.items():
        content = files[path]
        metadata = metadata_by_role[role]
        if metadata.content_sha256 != sha256_bytes(content):
            raise DailyMarketDataSourceCaptureVerificationError(
                f"{role.value} content hash mismatch"
            )
        if metadata.size_bytes != len(content):
            raise DailyMarketDataSourceCaptureVerificationError(
                f"{role.value} size mismatch"
            )


def _verify_ca_source_manifest(
    *,
    capture_manifest: DailyMarketDataSourceCaptureManifest,
    ca_source_manifest: DailyMarketDataCASourceManifest,
    ca_source_manifest_bytes: bytes,
) -> None:
    ca_hash = sha256_bytes(ca_source_manifest_bytes)
    ca_size = len(ca_source_manifest_bytes)
    if capture_manifest.ca_source_manifest.content_sha256 != ca_hash:
        raise DailyMarketDataSourceCaptureVerificationError(
            "CA source-manifest hash mismatch"
        )
    if capture_manifest.ca_source_manifest.size_bytes != ca_size:
        raise DailyMarketDataSourceCaptureVerificationError(
            "CA source-manifest size mismatch"
        )
    expected_ca_manifest = DailyMarketDataCASourceManifest(
        domain=CA_SOURCE_MANIFEST_DOMAIN,
        manifest_version=CA_SOURCE_MANIFEST_VERSION,
        provider=capture_manifest.provider,
        source_family=capture_manifest.source_family,
        instrument_id=capture_manifest.instrument_id,
        symbol=capture_manifest.symbol,
        capture_observed_at=capture_manifest.capture_observed_at,
        acquisition_batch_id=capture_manifest.acquisition_batch_id,
        members=tuple(
            member.ca_source_authority()
            for member in capture_manifest.members
            if member.role in CA_SOURCE_CAPTURE_ROLES
        ),
    )
    if ca_source_manifest.model_dump(mode="json") != expected_ca_manifest.model_dump(
        mode="json"
    ):
        raise DailyMarketDataSourceCaptureVerificationError(
            "CA source manifest does not match dividend/split source authority"
        )
    if render_ca_source_manifest(ca_source_manifest) != ca_source_manifest_bytes:
        raise DailyMarketDataSourceCaptureVerificationError(
            "CA source manifest bytes are not canonical"
        )


__all__ = [
    "DailyMarketDataSourceCaptureVerificationError",
    "VerifiedDailyMarketDataSourceCapture",
    "verify_daily_market_data_source_capture",
]
