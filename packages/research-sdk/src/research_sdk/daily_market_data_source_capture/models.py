"""Operational models for immutable daily market-data source captures."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Self
from urllib.parse import parse_qsl, urlsplit

from pydantic import ConfigDict, Field, field_validator, model_validator

from research_sdk.contracts.base import BaseContractModel
from research_sdk.contracts.daily_market_data import SHA256_CONTENT_HASH_PATTERN
from research_sdk.contracts.time import UtcDatetime
from research_sdk.contracts.types import NonEmptyString

SOURCE_CAPTURE_FORMAT_VERSION: Final[str] = "daily-market-data-source-capture-v1"
SOURCE_CAPTURE_IDENTITY_DOMAIN: Final[str] = "daily-market-data-source-capture"
SOURCE_CAPTURE_IDENTITY_VERSION: Final[str] = "daily-market-data-source-capture-v1"
SOURCE_CAPTURE_ID_PREFIX: Final[str] = "daily-market-data-source-capture-v1-"
SOURCE_CAPTURE_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"^{SOURCE_CAPTURE_ID_PREFIX}[0-9a-f]{{64}}$"
)
CA_SOURCE_MANIFEST_DOMAIN: Final[str] = "daily-market-data-ca-source-manifest"
CA_SOURCE_MANIFEST_VERSION: Final[str] = "daily-market-data-ca-source-manifest-v1"
CAPTURE_MANIFEST_PATH: Final[str] = "capture-manifest.json"
CA_SOURCE_MANIFEST_PATH: Final[str] = "ca-source-manifest.json"

_SENSITIVE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "api-key",
        "api_key",
        "apikey",
        "authorization",
        "bearer",
        "sig",
        "signature",
        "token",
    }
)
_SENSITIVE_TEXT_MARKERS: Final[tuple[str, ...]] = (
    "authorization",
    "bearer",
)


class DailyMarketDataSourceCaptureRole(StrEnum):
    """Canonical source member roles for S3c3 daily market-data captures."""

    BAR_RESPONSE = "BAR_RESPONSE"
    DIVIDEND_RESPONSE = "DIVIDEND_RESPONSE"
    SPLIT_RESPONSE = "SPLIT_RESPONSE"


CANONICAL_SOURCE_CAPTURE_ROLE_ORDER: Final[
    tuple[DailyMarketDataSourceCaptureRole, ...]
] = (
    DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
    DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
    DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
)
SOURCE_CAPTURE_MEMBER_PATHS: Final[Mapping[DailyMarketDataSourceCaptureRole, str]] = (
    MappingProxyType(
        {
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE: "bars.json",
            DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE: "dividends.json",
            DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE: "splits.json",
        }
    )
)
SOURCE_CAPTURE_REQUIRED_PATHS: Final[tuple[str, ...]] = (
    SOURCE_CAPTURE_MEMBER_PATHS[DailyMarketDataSourceCaptureRole.BAR_RESPONSE],
    SOURCE_CAPTURE_MEMBER_PATHS[DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE],
    SOURCE_CAPTURE_MEMBER_PATHS[DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE],
    CAPTURE_MANIFEST_PATH,
    CA_SOURCE_MANIFEST_PATH,
)
CA_SOURCE_CAPTURE_ROLES: Final[tuple[DailyMarketDataSourceCaptureRole, ...]] = (
    DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
    DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
)


@dataclass(frozen=True)
class DailyMarketDataSourceCaptureMemberInput:
    """Exact source bytes plus caller-supplied non-byte source metadata."""

    role: DailyMarketDataSourceCaptureRole | str
    endpoint_family: str
    endpoint_version: str
    request_parameters: tuple[tuple[str, str], ...]
    sanitized_source_reference: str
    content: bytes
    http_status: int
    media_type: str
    requested_scope: tuple[tuple[str, str], ...] = ()
    api_request_id: str | None = None
    limitations: tuple[str, ...] = ()


class DailyMarketDataSourceCaptureRequestParameter(BaseContractModel):
    """Canonical key/value request or requested-scope parameter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: NonEmptyString
    value: NonEmptyString

    @field_validator("key")
    @classmethod
    def reject_sensitive_key(cls, value: str) -> str:
        if value.lower() in _SENSITIVE_KEYS:
            raise ValueError("request parameters must not contain credential keys")
        return value

    @field_validator("value")
    @classmethod
    def reject_sensitive_value(cls, value: str) -> str:
        return _reject_sensitive_text(value, context="request parameter values")


class DailyMarketDataSourceCaptureMemberIdentity(BaseContractModel):
    """Identity-binding metadata for one exact source member."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: DailyMarketDataSourceCaptureRole
    endpoint_family: NonEmptyString
    endpoint_version: NonEmptyString
    request_parameters: tuple[DailyMarketDataSourceCaptureRequestParameter, ...]
    requested_scope: tuple[DailyMarketDataSourceCaptureRequestParameter, ...] = ()
    content_sha256: NonEmptyString
    size_bytes: int = Field(ge=0)

    @field_validator("content_sha256")
    @classmethod
    def validate_content_hash(cls, value: str) -> str:
        if SHA256_CONTENT_HASH_PATTERN.fullmatch(value) is None:
            raise ValueError("content_sha256 must use sha256:<64 lowercase hex>")
        return value

    @field_validator("request_parameters", "requested_scope")
    @classmethod
    def validate_canonical_parameter_order(
        cls,
        value: tuple[DailyMarketDataSourceCaptureRequestParameter, ...],
    ) -> tuple[DailyMarketDataSourceCaptureRequestParameter, ...]:
        return _validate_parameter_tuple(value)


class DailyMarketDataCASourceMemberAuthority(BaseContractModel):
    """Evidence authority for one corporate-action source member.

    Source references are deliberately included here because CA evidence identity
    binds the dividend/split source manifest. They remain excluded from
    source-capture identity authority.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: DailyMarketDataSourceCaptureRole
    endpoint_family: NonEmptyString
    endpoint_version: NonEmptyString
    request_parameters: tuple[DailyMarketDataSourceCaptureRequestParameter, ...]
    requested_scope: tuple[DailyMarketDataSourceCaptureRequestParameter, ...] = ()
    sanitized_source_reference: NonEmptyString
    content_sha256: NonEmptyString
    size_bytes: int = Field(ge=0)

    @field_validator("role")
    @classmethod
    def validate_ca_role(
        cls,
        value: DailyMarketDataSourceCaptureRole,
    ) -> DailyMarketDataSourceCaptureRole:
        if value not in CA_SOURCE_CAPTURE_ROLES:
            raise ValueError("CA source authority only supports dividend/split roles")
        return value

    @field_validator("content_sha256")
    @classmethod
    def validate_content_hash(cls, value: str) -> str:
        if SHA256_CONTENT_HASH_PATTERN.fullmatch(value) is None:
            raise ValueError("content_sha256 must use sha256:<64 lowercase hex>")
        return value

    @field_validator("request_parameters", "requested_scope")
    @classmethod
    def validate_canonical_parameter_order(
        cls,
        value: tuple[DailyMarketDataSourceCaptureRequestParameter, ...],
    ) -> tuple[DailyMarketDataSourceCaptureRequestParameter, ...]:
        return _validate_parameter_tuple(value)

    @field_validator("sanitized_source_reference")
    @classmethod
    def validate_source_reference(cls, value: str) -> str:
        return reject_sensitive_source_reference(value)


class DailyMarketDataSourceCaptureMemberMetadata(BaseContractModel):
    """Complete manifest metadata for one exact source member."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: DailyMarketDataSourceCaptureRole
    endpoint_family: NonEmptyString
    endpoint_version: NonEmptyString
    request_parameters: tuple[DailyMarketDataSourceCaptureRequestParameter, ...]
    sanitized_source_reference: NonEmptyString
    content_sha256: NonEmptyString
    size_bytes: int = Field(ge=0)
    http_status: int
    media_type: NonEmptyString
    requested_scope: tuple[DailyMarketDataSourceCaptureRequestParameter, ...] = ()
    api_request_id: NonEmptyString | None = None
    limitations: tuple[NonEmptyString, ...] = ()

    @field_validator("content_sha256")
    @classmethod
    def validate_content_hash(cls, value: str) -> str:
        if SHA256_CONTENT_HASH_PATTERN.fullmatch(value) is None:
            raise ValueError("content_sha256 must use sha256:<64 lowercase hex>")
        return value

    @field_validator("http_status")
    @classmethod
    def require_success_status(cls, value: int) -> int:
        if value != 200:
            raise ValueError("source capture members require HTTP 200")
        return value

    @field_validator("request_parameters", "requested_scope")
    @classmethod
    def validate_canonical_parameter_order(
        cls,
        value: tuple[DailyMarketDataSourceCaptureRequestParameter, ...],
    ) -> tuple[DailyMarketDataSourceCaptureRequestParameter, ...]:
        return _validate_parameter_tuple(value)

    @field_validator("sanitized_source_reference")
    @classmethod
    def validate_source_reference(cls, value: str) -> str:
        return reject_sensitive_source_reference(value)

    @field_validator("media_type")
    @classmethod
    def validate_media_type(cls, value: str) -> str:
        return _reject_sensitive_text(value, context="media_type")

    @field_validator("api_request_id")
    @classmethod
    def validate_api_request_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _reject_sensitive_text(value, context="api_request_id")

    @field_validator("limitations")
    @classmethod
    def validate_limitations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            _reject_sensitive_text(limitation, context="limitations")
            for limitation in value
        )

    def identity_authority(self) -> DailyMarketDataSourceCaptureMemberIdentity:
        """Return only fields that bind source-capture identity."""

        return DailyMarketDataSourceCaptureMemberIdentity(
            role=self.role,
            endpoint_family=self.endpoint_family,
            endpoint_version=self.endpoint_version,
            request_parameters=self.request_parameters,
            requested_scope=self.requested_scope,
            content_sha256=self.content_sha256,
            size_bytes=self.size_bytes,
        )

    def ca_source_authority(self) -> DailyMarketDataCASourceMemberAuthority:
        """Return dividend/split evidence authority for the CA source manifest.

        Unlike capture identity, this authority intentionally binds
        sanitized_source_reference so the CA evidence manifest proves which
        provider source reference supplied the dividend and split bytes.
        """

        return DailyMarketDataCASourceMemberAuthority(
            role=self.role,
            endpoint_family=self.endpoint_family,
            endpoint_version=self.endpoint_version,
            request_parameters=self.request_parameters,
            requested_scope=self.requested_scope,
            sanitized_source_reference=self.sanitized_source_reference,
            content_sha256=self.content_sha256,
            size_bytes=self.size_bytes,
        )


class DailyMarketDataCASourceManifest(BaseContractModel):
    """Canonical source authority for corporate-action endpoint evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    domain: NonEmptyString
    manifest_version: NonEmptyString
    provider: NonEmptyString
    source_family: NonEmptyString
    instrument_id: NonEmptyString
    symbol: NonEmptyString
    capture_observed_at: UtcDatetime
    acquisition_batch_id: NonEmptyString | None = None
    members: tuple[DailyMarketDataCASourceMemberAuthority, ...]

    @field_validator("acquisition_batch_id")
    @classmethod
    def validate_batch_id(cls, value: str | None) -> str | None:
        return _validate_optional_identifier(value, field_name="acquisition_batch_id")

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if self.domain != CA_SOURCE_MANIFEST_DOMAIN:
            raise ValueError("unsupported CA source-manifest domain")
        if self.manifest_version != CA_SOURCE_MANIFEST_VERSION:
            raise ValueError("unsupported CA source-manifest version")
        if tuple(member.role for member in self.members) != CA_SOURCE_CAPTURE_ROLES:
            raise ValueError(
                "CA source manifest must contain DIVIDEND_RESPONSE then SPLIT_RESPONSE"
            )
        return self


class DailyMarketDataCASourceManifestMetadata(BaseContractModel):
    """Hash and size facts for canonical CA source-manifest bytes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    relative_path: NonEmptyString
    content_sha256: NonEmptyString
    size_bytes: int = Field(ge=0)

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        if value != CA_SOURCE_MANIFEST_PATH:
            raise ValueError("CA source manifest path must be ca-source-manifest.json")
        return value

    @field_validator("content_sha256")
    @classmethod
    def validate_content_hash(cls, value: str) -> str:
        if SHA256_CONTENT_HASH_PATTERN.fullmatch(value) is None:
            raise ValueError("content_sha256 must use sha256:<64 lowercase hex>")
        return value


class DailyMarketDataSourceCaptureIdentityAuthority(BaseContractModel):
    """Canonical capture identity payload excluding evidence-only fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    domain: NonEmptyString
    identity_version: NonEmptyString
    provider: NonEmptyString
    source_family: NonEmptyString
    instrument_id: NonEmptyString
    symbol: NonEmptyString
    capture_observed_at: UtcDatetime
    acquisition_batch_id: NonEmptyString | None = None
    members: tuple[DailyMarketDataSourceCaptureMemberIdentity, ...]

    @field_validator("acquisition_batch_id")
    @classmethod
    def validate_batch_id(cls, value: str | None) -> str | None:
        return _validate_optional_identifier(value, field_name="acquisition_batch_id")

    @model_validator(mode="after")
    def validate_identity_authority(self) -> Self:
        if self.domain != SOURCE_CAPTURE_IDENTITY_DOMAIN:
            raise ValueError("unsupported source-capture identity domain")
        if self.identity_version != SOURCE_CAPTURE_IDENTITY_VERSION:
            raise ValueError("unsupported source-capture identity version")
        if tuple(member.role for member in self.members) != (
            CANONICAL_SOURCE_CAPTURE_ROLE_ORDER
        ):
            raise ValueError("source-capture identity members must use canonical order")
        return self


class DailyMarketDataSourceCaptureManifest(BaseContractModel):
    """Complete in-memory source-capture manifest metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capture_format_version: NonEmptyString
    capture_id: NonEmptyString
    provider: NonEmptyString
    source_family: NonEmptyString
    instrument_id: NonEmptyString
    symbol: NonEmptyString
    capture_observed_at: UtcDatetime
    acquisition_batch_id: NonEmptyString | None = None
    members: tuple[DailyMarketDataSourceCaptureMemberMetadata, ...]
    ca_source_manifest: DailyMarketDataCASourceManifestMetadata
    limitations: tuple[NonEmptyString, ...] = ()

    @field_validator("capture_id")
    @classmethod
    def validate_capture_id(cls, value: str) -> str:
        if SOURCE_CAPTURE_ID_PATTERN.fullmatch(value) is None:
            raise ValueError(
                "capture_id must use daily-market-data-source-capture-v1-*"
            )
        return value

    @field_validator("acquisition_batch_id")
    @classmethod
    def validate_batch_id(cls, value: str | None) -> str | None:
        return _validate_optional_identifier(value, field_name="acquisition_batch_id")

    @field_validator("limitations")
    @classmethod
    def validate_limitations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            _reject_sensitive_text(limitation, context="limitations")
            for limitation in value
        )

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if self.capture_format_version != SOURCE_CAPTURE_FORMAT_VERSION:
            raise ValueError("unsupported source-capture format version")
        if tuple(member.role for member in self.members) != (
            CANONICAL_SOURCE_CAPTURE_ROLE_ORDER
        ):
            raise ValueError("source-capture members must use canonical role order")
        return self

    def identity_authority(self) -> DailyMarketDataSourceCaptureIdentityAuthority:
        """Return only fields that bind source-capture identity."""

        return DailyMarketDataSourceCaptureIdentityAuthority(
            domain=SOURCE_CAPTURE_IDENTITY_DOMAIN,
            identity_version=SOURCE_CAPTURE_IDENTITY_VERSION,
            provider=self.provider,
            source_family=self.source_family,
            instrument_id=self.instrument_id,
            symbol=self.symbol,
            capture_observed_at=self.capture_observed_at,
            acquisition_batch_id=self.acquisition_batch_id,
            members=tuple(member.identity_authority() for member in self.members),
        )


def canonical_source_capture_role_order() -> tuple[
    DailyMarketDataSourceCaptureRole, ...
]:
    """Return the explicit source-capture role order used for identity."""

    return CANONICAL_SOURCE_CAPTURE_ROLE_ORDER


def canonicalize_parameters(
    parameters: tuple[tuple[str, str], ...],
) -> tuple[DailyMarketDataSourceCaptureRequestParameter, ...]:
    """Validate and deterministically order request/scope parameters."""

    parsed: list[DailyMarketDataSourceCaptureRequestParameter] = []
    for key, value in parameters:
        if type(key) is not str or type(value) is not str:
            raise ValueError("request parameters must be string key/value pairs")
        parsed.append(
            DailyMarketDataSourceCaptureRequestParameter(key=key, value=value)
        )
    by_lower_key: dict[str, DailyMarketDataSourceCaptureRequestParameter] = {}
    for parameter in parsed:
        lower_key = parameter.key.lower()
        if lower_key in by_lower_key:
            raise ValueError("request parameter keys must be unique case-insensitively")
        by_lower_key[lower_key] = parameter
    ordered = tuple(sorted(parsed, key=lambda parameter: parameter.key))
    return _validate_parameter_tuple(ordered)


def reject_sensitive_source_reference(value: str) -> str:
    """Reject obvious credential-bearing or local absolute source references."""

    _reject_sensitive_text(value, context="source references")
    if value.startswith(("/", "~")) or re.match(r"^[A-Za-z]:[\\/]", value):
        raise ValueError("source references must not be local absolute paths")
    parsed = urlsplit(value)
    if parsed.scheme and parsed.netloc and (parsed.username or parsed.password):
        raise ValueError("source references must not contain URI userinfo")
    sensitive_query_keys = {
        key.lower() for key, _value in parse_qsl(parsed.query, keep_blank_values=True)
    }
    if sensitive_query_keys & _SENSITIVE_KEYS:
        raise ValueError("source references must not contain obvious access tokens")
    return value


def _validate_parameter_tuple(
    value: tuple[DailyMarketDataSourceCaptureRequestParameter, ...],
) -> tuple[DailyMarketDataSourceCaptureRequestParameter, ...]:
    lower_keys = tuple(parameter.key.lower() for parameter in value)
    if len(set(lower_keys)) != len(lower_keys):
        raise ValueError("request parameter keys must be unique case-insensitively")
    expected = tuple(sorted(value, key=lambda parameter: parameter.key))
    if value != expected:
        raise ValueError("request parameters must use canonical sorted order")
    return value


def _validate_optional_identifier(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    if len(value) > 128:
        raise ValueError(f"{field_name} must be at most 128 characters")
    _reject_sensitive_text(value, context=field_name)
    return value


def _reject_sensitive_text(value: str, *, context: str) -> str:
    lowered = value.lower()
    if any(marker in lowered for marker in _SENSITIVE_TEXT_MARKERS):
        raise ValueError(f"{context} must not contain obvious credential markers")
    return value


__all__ = [
    "CA_SOURCE_CAPTURE_ROLES",
    "CA_SOURCE_MANIFEST_DOMAIN",
    "CA_SOURCE_MANIFEST_PATH",
    "CA_SOURCE_MANIFEST_VERSION",
    "CANONICAL_SOURCE_CAPTURE_ROLE_ORDER",
    "CAPTURE_MANIFEST_PATH",
    "SOURCE_CAPTURE_FORMAT_VERSION",
    "SOURCE_CAPTURE_IDENTITY_DOMAIN",
    "SOURCE_CAPTURE_IDENTITY_VERSION",
    "SOURCE_CAPTURE_ID_PATTERN",
    "SOURCE_CAPTURE_ID_PREFIX",
    "SOURCE_CAPTURE_MEMBER_PATHS",
    "SOURCE_CAPTURE_REQUIRED_PATHS",
    "DailyMarketDataCASourceManifest",
    "DailyMarketDataCASourceManifestMetadata",
    "DailyMarketDataCASourceMemberAuthority",
    "DailyMarketDataSourceCaptureIdentityAuthority",
    "DailyMarketDataSourceCaptureManifest",
    "DailyMarketDataSourceCaptureMemberIdentity",
    "DailyMarketDataSourceCaptureMemberInput",
    "DailyMarketDataSourceCaptureMemberMetadata",
    "DailyMarketDataSourceCaptureRequestParameter",
    "DailyMarketDataSourceCaptureRole",
    "canonical_source_capture_role_order",
    "canonicalize_parameters",
    "reject_sensitive_source_reference",
]
