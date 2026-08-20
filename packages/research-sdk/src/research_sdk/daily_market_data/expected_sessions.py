"""Versioned common U.S.-equity daily expected-session authority."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from typing import Final, Protocol, cast

from research_sdk.contracts.daily_market_data_snapshots import (
    DailyMarketDataExpectedSessions,
)
from research_sdk.contracts.schema import RESEARCH_SDK_CONTRACT_SCHEMA_VERSION

EXCHANGE_CALENDARS_PINNED_VERSION: Final[str] = "4.13.2"
US_EQUITY_DAILY_SESSION_CALENDAR: Final[str] = "XNYS"
US_EQUITY_DAILY_SESSION_TIMEZONE: Final[str] = "America/New_York"
US_EQUITY_DAILY_SESSION_POLICY_VERSION: Final[str] = (
    "us-equity-regular-session-dates-v1"
)
US_EQUITY_DAILY_SESSION_SOURCE_ID: Final[str] = (
    f"exchange_calendars:{US_EQUITY_DAILY_SESSION_CALENDAR}"
)
US_EQUITY_DAILY_SESSION_SOURCE_VERSION: Final[str] = (
    f"exchange_calendars-{EXCHANGE_CALENDARS_PINNED_VERSION}"
    f"+{US_EQUITY_DAILY_SESSION_POLICY_VERSION}"
)

_EXCHANGE_CALENDARS_DISTRIBUTION = "exchange-calendars"


class DailyMarketDataExpectedSessionsAuthorityError(ValueError):
    """Raised when approved daily expected-session authority cannot be derived."""


class _SessionLabel(Protocol):
    def date(self) -> date:
        """Return the session label's calendar date without timezone conversion."""


class _CalendarTimezone(Protocol):
    key: str


class _ExplicitlyBoundedCalendar(Protocol):
    name: str
    tz: _CalendarTimezone
    sessions: Iterable[_SessionLabel]


def derive_us_equity_daily_expected_sessions(
    *,
    start_date: date,
    end_date: date,
) -> DailyMarketDataExpectedSessions:
    """Derive inclusive XNYS regular-session dates from explicit date bounds."""

    validated_start = _require_exact_date(start_date, name="start_date")
    validated_end = _require_exact_date(end_date, name="end_date")
    if validated_end < validated_start:
        raise DailyMarketDataExpectedSessionsAuthorityError(
            "end_date must be greater than or equal to start_date"
        )

    installed_version = _installed_exchange_calendars_version()
    if (
        type(installed_version) is not str
        or installed_version != EXCHANGE_CALENDARS_PINNED_VERSION
    ):
        raise DailyMarketDataExpectedSessionsAuthorityError(
            "installed exchange-calendars version must be exactly "
            f"{EXCHANGE_CALENDARS_PINNED_VERSION!r}; got {installed_version!r}"
        )

    construction_end = validated_end
    if validated_start == validated_end:
        # exchange_calendars 4.13.2 requires distinct construction bounds.
        # The explicit one-day pad is removed before durable dates are returned.
        try:
            construction_end = validated_end + timedelta(days=1)
        except OverflowError as exc:
            raise DailyMarketDataExpectedSessionsAuthorityError(
                "single-date range cannot be represented by calendar bounds"
            ) from exc

    calendar = _get_explicitly_bounded_calendar(
        calendar_name=US_EQUITY_DAILY_SESSION_CALENDAR,
        start_date=validated_start,
        end_date=construction_end,
    )

    try:
        calendar_name = calendar.name
        calendar_timezone = calendar.tz
        calendar_timezone_key = getattr(calendar_timezone, "key", None)
        session_labels = calendar.sessions
    except Exception as exc:
        raise DailyMarketDataExpectedSessionsAuthorityError(
            "calendar authority metadata and session labels must be readable"
        ) from exc

    if (
        type(calendar_name) is not str
        or calendar_name != US_EQUITY_DAILY_SESSION_CALENDAR
    ):
        raise DailyMarketDataExpectedSessionsAuthorityError(
            "calendar authority must identify as XNYS"
        )
    if (
        type(calendar_timezone_key) is not str
        or calendar_timezone_key != US_EQUITY_DAILY_SESSION_TIMEZONE
    ):
        raise DailyMarketDataExpectedSessionsAuthorityError(
            "calendar authority timezone must be America/New_York"
        )

    constructed_session_dates = _materialize_session_dates(
        session_labels,
        start_date=validated_start,
        end_date=construction_end,
    )
    session_dates = tuple(
        session_date
        for session_date in constructed_session_dates
        if session_date <= validated_end
    )
    if not session_dates:
        raise DailyMarketDataExpectedSessionsAuthorityError(
            "inclusive date range contains no XNYS regular sessions"
        )

    return DailyMarketDataExpectedSessions(
        schema_version=RESEARCH_SDK_CONTRACT_SCHEMA_VERSION,
        session_source_id=US_EQUITY_DAILY_SESSION_SOURCE_ID,
        session_source_version=US_EQUITY_DAILY_SESSION_SOURCE_VERSION,
        calendar=US_EQUITY_DAILY_SESSION_CALENDAR,
        timezone=US_EQUITY_DAILY_SESSION_TIMEZONE,
        session_dates=session_dates,
    )


def _installed_exchange_calendars_version() -> str:
    try:
        return distribution_version(_EXCHANGE_CALENDARS_DISTRIBUTION)
    except PackageNotFoundError as exc:
        raise DailyMarketDataExpectedSessionsAuthorityError(
            "exchange-calendars distribution is not installed"
        ) from exc


def _get_explicitly_bounded_calendar(
    *,
    calendar_name: str,
    start_date: date,
    end_date: date,
) -> _ExplicitlyBoundedCalendar:
    # Keep the operational calendar stack out of imports that only need pure
    # daily-market-data or snapshot-storage helpers.
    import exchange_calendars  # type: ignore[import-untyped]
    from exchange_calendars import errors as xc_errors

    try:
        return cast(
            _ExplicitlyBoundedCalendar,
            exchange_calendars.get_calendar(
                calendar_name,
                start=start_date,
                end=end_date,
            ),
        )
    except xc_errors.NoSessionsError as exc:
        raise DailyMarketDataExpectedSessionsAuthorityError(
            "inclusive date range contains no XNYS regular sessions"
        ) from exc
    except Exception as exc:
        raise DailyMarketDataExpectedSessionsAuthorityError(
            "failed to construct explicitly bounded XNYS calendar authority"
        ) from exc


def _require_exact_date(value: object, *, name: str) -> date:
    if type(value) is not date:
        raise DailyMarketDataExpectedSessionsAuthorityError(
            f"{name} must be an exact date value"
        )
    return value


def _materialize_session_dates(
    labels: Iterable[_SessionLabel],
    *,
    start_date: date,
    end_date: date,
) -> tuple[date, ...]:
    materialized: list[date] = []
    previous: date | None = None
    try:
        iterator = iter(labels)
    except Exception as exc:
        raise DailyMarketDataExpectedSessionsAuthorityError(
            "XNYS session labels must be iterable"
        ) from exc

    while True:
        try:
            label = next(iterator)
        except StopIteration:
            break
        except Exception as exc:
            raise DailyMarketDataExpectedSessionsAuthorityError(
                "failed while reading XNYS session labels"
            ) from exc

        try:
            session_date = label.date()
        except Exception as exc:
            raise DailyMarketDataExpectedSessionsAuthorityError(
                "XNYS session labels must expose a date value"
            ) from exc
        if type(session_date) is not date:
            raise DailyMarketDataExpectedSessionsAuthorityError(
                "XNYS session labels must materialize as exact date values"
            )
        if not start_date <= session_date <= end_date:
            raise DailyMarketDataExpectedSessionsAuthorityError(
                "XNYS session date lies outside the requested inclusive range"
            )
        if previous is not None and session_date <= previous:
            raise DailyMarketDataExpectedSessionsAuthorityError(
                "XNYS session dates must be unique and strictly ascending"
            )
        materialized.append(session_date)
        previous = session_date
    return tuple(materialized)


__all__ = [
    "EXCHANGE_CALENDARS_PINNED_VERSION",
    "US_EQUITY_DAILY_SESSION_CALENDAR",
    "US_EQUITY_DAILY_SESSION_POLICY_VERSION",
    "US_EQUITY_DAILY_SESSION_SOURCE_ID",
    "US_EQUITY_DAILY_SESSION_SOURCE_VERSION",
    "US_EQUITY_DAILY_SESSION_TIMEZONE",
    "DailyMarketDataExpectedSessionsAuthorityError",
    "derive_us_equity_daily_expected_sessions",
]
