from __future__ import annotations

import inspect
from datetime import date

import pytest

import backtest_engine.timing as timing_module
from backtest_engine.timing import (
    DAILY_INFORMATION_TIMING_POLICY_VERSION,
    DailyInformationTimingError,
    build_daily_decision_information_boundary,
    first_expected_session_after,
)

SESSIONS = (
    date(2026, 1, 2),
    date(2026, 1, 5),
    date(2026, 1, 6),
)


def test_timing_policy_version_is_frozen() -> None:
    assert (
        DAILY_INFORMATION_TIMING_POLICY_VERSION == "daily-etf-next-expected-session-v1"
    )


def test_expected_sessions_must_be_strictly_ascending() -> None:
    with pytest.raises(DailyInformationTimingError, match="strictly ascending"):
        build_daily_decision_information_boundary(
            decision_session=date(2026, 1, 5),
            expected_session_dates=(date(2026, 1, 5), date(2026, 1, 2)),
        )


def test_duplicate_expected_sessions_fail() -> None:
    with pytest.raises(DailyInformationTimingError, match="duplicates"):
        build_daily_decision_information_boundary(
            decision_session=date(2026, 1, 5),
            expected_session_dates=(date(2026, 1, 5), date(2026, 1, 5)),
        )


def test_decision_session_must_be_expected() -> None:
    with pytest.raises(DailyInformationTimingError, match="decision_session"):
        build_daily_decision_information_boundary(
            decision_session=date(2026, 1, 7),
            expected_session_dates=SESSIONS,
        )


def test_first_decision_session_exposes_zero_complete_bars() -> None:
    boundary = build_daily_decision_information_boundary(
        decision_session=date(2026, 1, 2),
        expected_session_dates=SESSIONS,
    )

    assert boundary.observable_complete_bar_sessions == ()
    assert boundary.latest_observable_complete_bar_session is None


def test_later_decision_exposes_only_strictly_prior_sessions() -> None:
    boundary = build_daily_decision_information_boundary(
        decision_session=date(2026, 1, 6),
        expected_session_dates=SESSIONS,
    )

    assert boundary.observable_complete_bar_sessions == (
        date(2026, 1, 2),
        date(2026, 1, 5),
    )


def test_same_day_session_is_excluded() -> None:
    boundary = build_daily_decision_information_boundary(
        decision_session=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
    )

    assert date(2026, 1, 5) not in boundary.observable_complete_bar_sessions


def test_future_sessions_are_excluded() -> None:
    boundary = build_daily_decision_information_boundary(
        decision_session=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
    )

    assert all(
        observable_session < boundary.decision_session
        for observable_session in boundary.observable_complete_bar_sessions
    )


def test_latest_observable_session_exact() -> None:
    boundary = build_daily_decision_information_boundary(
        decision_session=date(2026, 1, 6),
        expected_session_dates=SESSIONS,
    )

    assert boundary.latest_observable_complete_bar_session == date(2026, 1, 5)


def test_first_expected_session_after_is_strict() -> None:
    assert first_expected_session_after(date(2026, 1, 5), SESSIONS) == date(2026, 1, 6)


def test_weekend_non_session_payable_maps_to_next_expected_session() -> None:
    assert first_expected_session_after(date(2026, 1, 3), SESSIONS) == date(2026, 1, 5)


def test_no_future_expected_session_returns_none() -> None:
    assert first_expected_session_after(date(2026, 1, 6), SESSIONS) is None


def test_deterministic_same_inputs_same_result() -> None:
    first = build_daily_decision_information_boundary(
        decision_session=date(2026, 1, 6),
        expected_session_dates=SESSIONS,
    )
    second = build_daily_decision_information_boundary(
        decision_session=date(2026, 1, 6),
        expected_session_dates=SESSIONS,
    )

    assert first == second


def test_timing_source_has_no_wall_clock_dependency() -> None:
    source = inspect.getsource(timing_module)

    for prohibited in ("datetime.now", "datetime.utcnow", "date.today", "time.time"):
        assert prohibited not in source
