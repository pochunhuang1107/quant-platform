"""Deterministic persistence-domain error taxonomy."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

_HASH_PREFIX_PATTERN = re.compile(r"[0-9a-f]{1,12}")


@dataclass(frozen=True)
class PersistenceErrorContext:
    """Safe structured context for deterministic persistence-domain errors."""

    table_name: str
    operation: str
    logical_identity: Mapping[str, str]
    constraint_name: str | None = None
    existing_hash_prefix: str | None = None
    attempted_hash_prefix: str | None = None

    def __post_init__(self) -> None:
        if not self.table_name.strip():
            raise ValueError("table_name must not be blank")
        if not self.operation.strip():
            raise ValueError("operation must not be blank")
        if not self.logical_identity:
            raise ValueError("logical_identity must not be empty")

        _validate_hash_prefix("existing_hash_prefix", self.existing_hash_prefix)
        _validate_hash_prefix("attempted_hash_prefix", self.attempted_hash_prefix)


class PersistenceError(Exception):
    """Root deterministic persistence-domain error."""

    def __init__(self, context: PersistenceErrorContext) -> None:
        self._context = context
        super().__init__(_format_error_message(type(self).__name__, context))

    @property
    def context(self) -> PersistenceErrorContext:
        """Safe structured context for this persistence-domain error."""

        return self._context


class PersistenceConflictError(PersistenceError):
    """Base class for deterministic persistence conflicts."""


class ContractHashConflictError(PersistenceConflictError):
    """Raised when a logical identity exists with a different contract hash."""


class NaturalKeyConflictError(PersistenceConflictError):
    """Raised when a write collides with a natural or non-primary identity."""


class UnsupportedVersioningConflictError(NaturalKeyConflictError):
    """Raised when unsupported versioning or supersession is attempted."""


class DuplicateReviewEventError(PersistenceConflictError):
    """Raised when a duplicate review event identity is rejected."""


class AggregateIntegrityError(PersistenceError):
    """Raised when persisted aggregate state does not match its projection."""


def _validate_hash_prefix(field_name: str, value: str | None) -> None:
    if value is None:
        return

    if _HASH_PREFIX_PATTERN.fullmatch(value) is None:
        raise ValueError(
            f"{field_name} must be 1 to 12 lowercase hexadecimal characters"
        )


def _format_error_message(
    error_name: str,
    context: PersistenceErrorContext,
) -> str:
    identity = ", ".join(
        f"{key}={value}" for key, value in sorted(context.logical_identity.items())
    )
    parts = [
        error_name,
        f"table_name={context.table_name}",
        f"operation={context.operation}",
        f"logical_identity={{{identity}}}",
    ]

    if context.constraint_name is not None:
        parts.append(f"constraint_name={context.constraint_name}")
    if context.existing_hash_prefix is not None:
        parts.append(f"existing_hash_prefix={context.existing_hash_prefix}")
    if context.attempted_hash_prefix is not None:
        parts.append(f"attempted_hash_prefix={context.attempted_hash_prefix}")

    return "; ".join(parts)


__all__ = [
    "AggregateIntegrityError",
    "ContractHashConflictError",
    "DuplicateReviewEventError",
    "NaturalKeyConflictError",
    "PersistenceConflictError",
    "PersistenceError",
    "PersistenceErrorContext",
    "UnsupportedVersioningConflictError",
]
