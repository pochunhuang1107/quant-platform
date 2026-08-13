"""Information-timing primitives for daily ETF decisions."""

from __future__ import annotations

from datetime import date
from typing import Self

from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, model_validator

DAILY_INFORMATION_TIMING_POLICY_VERSION = "daily-etf-next-expected-session-v1"


class DailyInformationTimingError(ValueError):
    """Raised when daily decision timing inputs violate supplied session authority."""


class DailyTimingModel(PydanticBaseModel):
    """Frozen operational model base for S3d1 timing results."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DailyDecisionInformationBoundary(DailyTimingModel):
    """Complete daily bars visible before a decision session."""

    decision_session: date
    observable_complete_bar_sessions: tuple[date, ...]
    latest_observable_complete_bar_session: date | None

    @model_validator(mode="after")
    def validate_boundary(self) -> Self:
        _validate_date(self.decision_session, field_name="decision_session")
        _validate_session_tuple(
            self.observable_complete_bar_sessions,
            field_name="observable_complete_bar_sessions",
            allow_empty=True,
        )
        expected_latest = (
            self.observable_complete_bar_sessions[-1]
            if self.observable_complete_bar_sessions
            else None
        )
        if self.latest_observable_complete_bar_session != expected_latest:
            raise ValueError("latest observable session must match observable prefix")
        if self.decision_session in self.observable_complete_bar_sessions:
            raise ValueError("decision session must not be observable")
        if any(
            observable_session > self.decision_session
            for observable_session in self.observable_complete_bar_sessions
        ):
            raise ValueError("future sessions must not be observable")
        return self


def validate_expected_session_dates(
    expected_session_dates: tuple[date, ...],
) -> tuple[date, ...]:
    """Require expected sessions to be non-empty, unique, and ascending."""

    return _validate_session_tuple(
        expected_session_dates,
        field_name="expected_session_dates",
        allow_empty=False,
    )


def build_daily_decision_information_boundary(
    *,
    decision_session: date,
    expected_session_dates: tuple[date, ...],
) -> DailyDecisionInformationBoundary:
    """Build the NEXT_EXPECTED_SESSION complete-bar visibility boundary."""

    _validate_date(decision_session, field_name="decision_session")
    sessions = validate_expected_session_dates(expected_session_dates)
    if decision_session not in sessions:
        raise DailyInformationTimingError("decision_session must be expected")
    decision_index = sessions.index(decision_session)
    observable_sessions = sessions[:decision_index]
    latest_observable = observable_sessions[-1] if observable_sessions else None
    return DailyDecisionInformationBoundary(
        decision_session=decision_session,
        observable_complete_bar_sessions=observable_sessions,
        latest_observable_complete_bar_session=latest_observable,
    )


def first_expected_session_after(
    calendar_date: date,
    expected_session_dates: tuple[date, ...],
) -> date | None:
    """Return the first supplied expected session strictly after a calendar date."""

    _validate_date(calendar_date, field_name="calendar_date")
    for session_date in validate_expected_session_dates(expected_session_dates):
        if session_date > calendar_date:
            return session_date
    return None


def _validate_session_tuple(
    session_dates: tuple[date, ...],
    *,
    field_name: str,
    allow_empty: bool,
) -> tuple[date, ...]:
    if not allow_empty and not session_dates:
        raise DailyInformationTimingError(f"{field_name} must be non-empty")
    for session_date in session_dates:
        _validate_date(session_date, field_name=field_name)
    if len(set(session_dates)) != len(session_dates):
        raise DailyInformationTimingError(f"{field_name} must not contain duplicates")
    if session_dates != tuple(sorted(session_dates)):
        raise DailyInformationTimingError(f"{field_name} must be strictly ascending")
    return session_dates


def _validate_date(value: date, *, field_name: str) -> None:
    if type(value) is not date:
        raise DailyInformationTimingError(f"{field_name} must contain date values only")


__all__ = [
    "DAILY_INFORMATION_TIMING_POLICY_VERSION",
    "DailyDecisionInformationBoundary",
    "DailyInformationTimingError",
    "build_daily_decision_information_boundary",
    "first_expected_session_after",
    "validate_expected_session_dates",
]
