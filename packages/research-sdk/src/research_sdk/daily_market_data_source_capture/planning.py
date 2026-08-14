"""Pure in-memory planning for immutable daily market-data source captures."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from research_sdk.daily_market_data_source_capture.identity import (
    derive_daily_market_data_source_capture_id,
)
from research_sdk.daily_market_data_source_capture.models import (
    CA_SOURCE_CAPTURE_ROLES,
    CA_SOURCE_MANIFEST_DOMAIN,
    CA_SOURCE_MANIFEST_PATH,
    CA_SOURCE_MANIFEST_VERSION,
    CANONICAL_SOURCE_CAPTURE_ROLE_ORDER,
    CAPTURE_MANIFEST_PATH,
    SOURCE_CAPTURE_FORMAT_VERSION,
    SOURCE_CAPTURE_IDENTITY_DOMAIN,
    SOURCE_CAPTURE_IDENTITY_VERSION,
    SOURCE_CAPTURE_MEMBER_PATHS,
    DailyMarketDataCASourceManifest,
    DailyMarketDataCASourceManifestMetadata,
    DailyMarketDataSourceCaptureIdentityAuthority,
    DailyMarketDataSourceCaptureManifest,
    DailyMarketDataSourceCaptureMemberInput,
    DailyMarketDataSourceCaptureMemberMetadata,
    DailyMarketDataSourceCaptureRole,
    canonicalize_parameters,
)
from research_sdk.daily_market_data_source_capture.serialization import (
    render_ca_source_manifest,
    render_capture_manifest,
)
from research_sdk.daily_market_data_storage.serialization import sha256_bytes


class DailyMarketDataSourceCapturePlanningError(ValueError):
    """Raised when source-capture planning inputs are invalid."""


@dataclass(frozen=True)
class PlannedDailyMarketDataSourceCaptureMemberBytes:
    """Canonical in-memory bytes for one planned source member."""

    role: DailyMarketDataSourceCaptureRole
    relative_path: str
    content: bytes


@dataclass(frozen=True)
class PlannedDailyMarketDataSourceCapture:
    """Pure in-memory source-capture plan with final canonical bytes."""

    capture_id: str
    capture_manifest: DailyMarketDataSourceCaptureManifest
    capture_manifest_bytes: bytes
    ca_source_manifest: DailyMarketDataCASourceManifest
    ca_source_manifest_bytes: bytes
    ca_source_content_hash: str
    ca_source_size_bytes: int
    member_bytes: tuple[PlannedDailyMarketDataSourceCaptureMemberBytes, ...]

    def as_file_map(self) -> dict[str, bytes]:
        """Return detached authoritative in-memory capture files."""

        files = {member.relative_path: member.content for member in self.member_bytes}
        files[CAPTURE_MANIFEST_PATH] = self.capture_manifest_bytes
        files[CA_SOURCE_MANIFEST_PATH] = self.ca_source_manifest_bytes
        return files


def plan_daily_market_data_source_capture(
    *,
    provider: str,
    source_family: str,
    instrument_id: str,
    symbol: str,
    capture_observed_at: datetime,
    members: tuple[DailyMarketDataSourceCaptureMemberInput, ...],
    acquisition_batch_id: str | None = None,
    limitations: tuple[str, ...] = (),
) -> PlannedDailyMarketDataSourceCapture:
    """Build a deterministic source-capture plan from exact member bytes."""

    planned_members = _plan_members(members)
    member_metadata = tuple(
        planned_members[role] for role in CANONICAL_SOURCE_CAPTURE_ROLE_ORDER
    )
    ca_source_manifest = DailyMarketDataCASourceManifest(
        domain=CA_SOURCE_MANIFEST_DOMAIN,
        manifest_version=CA_SOURCE_MANIFEST_VERSION,
        provider=provider,
        source_family=source_family,
        instrument_id=instrument_id,
        symbol=symbol,
        capture_observed_at=capture_observed_at,
        acquisition_batch_id=acquisition_batch_id,
        members=tuple(
            planned_members[role].ca_source_authority()
            for role in CA_SOURCE_CAPTURE_ROLES
        ),
    )
    ca_source_manifest_bytes = render_ca_source_manifest(ca_source_manifest)
    ca_source_content_hash = sha256_bytes(ca_source_manifest_bytes)
    ca_source_size_bytes = len(ca_source_manifest_bytes)
    identity_authority = DailyMarketDataSourceCaptureIdentityAuthority(
        domain=SOURCE_CAPTURE_IDENTITY_DOMAIN,
        identity_version=SOURCE_CAPTURE_IDENTITY_VERSION,
        provider=provider,
        source_family=source_family,
        instrument_id=instrument_id,
        symbol=symbol,
        capture_observed_at=capture_observed_at,
        acquisition_batch_id=acquisition_batch_id,
        members=tuple(member.identity_authority() for member in member_metadata),
    )
    capture_id = derive_daily_market_data_source_capture_id(identity_authority)
    capture_manifest = DailyMarketDataSourceCaptureManifest(
        capture_format_version=SOURCE_CAPTURE_FORMAT_VERSION,
        capture_id=capture_id,
        provider=provider,
        source_family=source_family,
        instrument_id=instrument_id,
        symbol=symbol,
        capture_observed_at=capture_observed_at,
        acquisition_batch_id=acquisition_batch_id,
        members=member_metadata,
        ca_source_manifest=DailyMarketDataCASourceManifestMetadata(
            relative_path=CA_SOURCE_MANIFEST_PATH,
            content_sha256=ca_source_content_hash,
            size_bytes=ca_source_size_bytes,
        ),
        limitations=_canonicalize_limitations(limitations),
    )
    capture_manifest_bytes = render_capture_manifest(capture_manifest)
    member_bytes = tuple(
        PlannedDailyMarketDataSourceCaptureMemberBytes(
            role=role,
            relative_path=SOURCE_CAPTURE_MEMBER_PATHS[role],
            content=_member_content_for_role(members, role),
        )
        for role in CANONICAL_SOURCE_CAPTURE_ROLE_ORDER
    )
    return PlannedDailyMarketDataSourceCapture(
        capture_id=capture_id,
        capture_manifest=capture_manifest,
        capture_manifest_bytes=capture_manifest_bytes,
        ca_source_manifest=ca_source_manifest,
        ca_source_manifest_bytes=ca_source_manifest_bytes,
        ca_source_content_hash=ca_source_content_hash,
        ca_source_size_bytes=ca_source_size_bytes,
        member_bytes=member_bytes,
    )


def _plan_members(
    members: tuple[DailyMarketDataSourceCaptureMemberInput, ...],
) -> Mapping[
    DailyMarketDataSourceCaptureRole, DailyMarketDataSourceCaptureMemberMetadata
]:
    metadata_by_role: dict[
        DailyMarketDataSourceCaptureRole, DailyMarketDataSourceCaptureMemberMetadata
    ] = {}
    expected_roles = set(CANONICAL_SOURCE_CAPTURE_ROLE_ORDER)
    for member_input in members:
        role = _parse_role(member_input.role)
        if role in metadata_by_role:
            raise DailyMarketDataSourceCapturePlanningError(
                f"duplicate source member role: {role.value}"
            )
        if type(member_input.content) is not bytes:
            raise DailyMarketDataSourceCapturePlanningError(
                f"{role.value} content must be bytes"
            )
        metadata_by_role[role] = DailyMarketDataSourceCaptureMemberMetadata(
            role=role,
            endpoint_family=member_input.endpoint_family,
            endpoint_version=member_input.endpoint_version,
            request_parameters=canonicalize_parameters(member_input.request_parameters),
            sanitized_source_reference=member_input.sanitized_source_reference,
            content_sha256=sha256_bytes(member_input.content),
            size_bytes=len(member_input.content),
            http_status=member_input.http_status,
            media_type=member_input.media_type,
            requested_scope=canonicalize_parameters(member_input.requested_scope),
            api_request_id=member_input.api_request_id,
            limitations=_canonicalize_limitations(member_input.limitations),
        )
    missing_roles = expected_roles - set(metadata_by_role)
    if missing_roles:
        missing = ", ".join(sorted(role.value for role in missing_roles))
        raise DailyMarketDataSourceCapturePlanningError(
            f"missing required source member roles: {missing}"
        )
    unexpected_roles = set(metadata_by_role) - expected_roles
    if unexpected_roles:
        unexpected = ", ".join(sorted(role.value for role in unexpected_roles))
        raise DailyMarketDataSourceCapturePlanningError(
            f"unexpected source member roles: {unexpected}"
        )
    return metadata_by_role


def _member_content_for_role(
    members: tuple[DailyMarketDataSourceCaptureMemberInput, ...],
    role: DailyMarketDataSourceCaptureRole,
) -> bytes:
    for member_input in members:
        if _parse_role(member_input.role) is role:
            if type(member_input.content) is not bytes:
                raise DailyMarketDataSourceCapturePlanningError(
                    f"{role.value} content must be bytes"
                )
            return member_input.content
    raise DailyMarketDataSourceCapturePlanningError(
        f"missing required source member role: {role.value}"
    )


def _parse_role(
    role: DailyMarketDataSourceCaptureRole | str,
) -> DailyMarketDataSourceCaptureRole:
    try:
        return DailyMarketDataSourceCaptureRole(role)
    except ValueError as exc:
        raise DailyMarketDataSourceCapturePlanningError(
            f"unsupported source member role: {role!r}"
        ) from exc


def _canonicalize_limitations(limitations: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(dict.fromkeys(limitations)))


__all__ = [
    "DailyMarketDataSourceCapturePlanningError",
    "PlannedDailyMarketDataSourceCapture",
    "PlannedDailyMarketDataSourceCaptureMemberBytes",
    "plan_daily_market_data_source_capture",
]
