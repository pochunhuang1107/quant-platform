"""Datetime helpers for contract fields that require UTC timestamps."""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator


def ensure_utc_datetime(value: datetime) -> datetime:
    """Return an aware datetime normalized to UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")

    return value.astimezone(UTC)


type UtcDatetime = Annotated[datetime, AfterValidator(ensure_utc_datetime)]
