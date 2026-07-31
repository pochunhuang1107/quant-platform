"""Persistence write result value objects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class PersistenceDisposition(StrEnum):
    """Successful persistence write outcomes."""

    CREATED = "created"
    REPLAYED = "replayed"


@dataclass(frozen=True)
class PersistedRecordMetadata:
    """Safe metadata describing a durable persisted record."""

    table_name: str
    primary_key: Mapping[str, str]
    contract_hash: str | None = None
    inserted_at: datetime | None = None


@dataclass(frozen=True)
class PersistenceWriteResult:
    """Successful persistence write-operation result."""

    disposition: PersistenceDisposition
    record: PersistedRecordMetadata
    aggregate_entry_count: int | None = None

    def __post_init__(self) -> None:
        if self.aggregate_entry_count is not None and self.aggregate_entry_count < 0:
            raise ValueError("aggregate_entry_count must be non-negative")


__all__ = [
    "PersistedRecordMetadata",
    "PersistenceDisposition",
    "PersistenceWriteResult",
]
