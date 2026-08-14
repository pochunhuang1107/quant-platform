"""Pure identity helpers for daily market-data source captures."""

from __future__ import annotations

import hashlib

from research_sdk.daily_market_data_source_capture.models import (
    SOURCE_CAPTURE_ID_PREFIX,
    DailyMarketDataSourceCaptureIdentityAuthority,
)
from research_sdk.daily_market_data_source_capture.serialization import (
    render_source_capture_model,
)


class DailyMarketDataSourceCaptureIdentityError(ValueError):
    """Raised when source-capture identity inputs are invalid."""


def derive_daily_market_data_source_capture_id(
    authority: DailyMarketDataSourceCaptureIdentityAuthority,
) -> str:
    """Derive a deterministic source-capture ID from identity authority only."""

    try:
        validated = DailyMarketDataSourceCaptureIdentityAuthority.model_validate(
            authority.model_dump(mode="json")
        )
    except Exception as exc:
        raise DailyMarketDataSourceCaptureIdentityError(
            "source-capture identity authority is invalid"
        ) from exc
    digest = hashlib.sha256(render_source_capture_model(validated)).hexdigest()
    return f"{SOURCE_CAPTURE_ID_PREFIX}{digest}"


__all__ = [
    "DailyMarketDataSourceCaptureIdentityError",
    "derive_daily_market_data_source_capture_id",
]
