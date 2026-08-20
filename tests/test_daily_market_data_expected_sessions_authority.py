from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

import research_sdk.daily_market_data.expected_sessions as authority_module
from helpers_daily_market_data_snapshots_v2 import sample_plan_v2
from research_sdk.contracts.daily_market_data import DailyMarketDataInstrument
from research_sdk.contracts.daily_market_data_snapshots import (
    DailyMarketDataExpectedSessions,
)
from research_sdk.daily_market_data import (
    EXCHANGE_CALENDARS_PINNED_VERSION,
    US_EQUITY_DAILY_SESSION_CALENDAR,
    US_EQUITY_DAILY_SESSION_POLICY_VERSION,
    US_EQUITY_DAILY_SESSION_SOURCE_ID,
    US_EQUITY_DAILY_SESSION_SOURCE_VERSION,
    US_EQUITY_DAILY_SESSION_TIMEZONE,
    DailyMarketDataExpectedSessionsAuthorityError,
    derive_daily_market_data_expected_sessions_hash,
    derive_us_equity_daily_expected_sessions,
)
from research_sdk.daily_market_data_storage import (
    verify_daily_market_data_snapshot_bundle_v2,
)

FIRST_REAL_TARGET_HASH = (
    "sha256:2914d0d978fdc1e9f8aad436d1acbfc10dc1022b74e080565e13d6aab9295068"
)
FIRST_REAL_TARGET_START = date(2024, 1, 2)
FIRST_REAL_TARGET_END = date(2024, 12, 31)


class DateSubclass(date):
    pass


class MisleadingString(str):
    def __ne__(self, other: object) -> bool:
        return False


def test_installed_dependency_and_public_authority_metadata_are_exact() -> None:
    assert distribution_version("exchange-calendars") == "4.13.2"
    assert EXCHANGE_CALENDARS_PINNED_VERSION == "4.13.2"
    assert US_EQUITY_DAILY_SESSION_CALENDAR == "XNYS"
    assert US_EQUITY_DAILY_SESSION_TIMEZONE == "America/New_York"
    assert (
        US_EQUITY_DAILY_SESSION_POLICY_VERSION == "us-equity-regular-session-dates-v1"
    )
    assert US_EQUITY_DAILY_SESSION_SOURCE_ID == "exchange_calendars:XNYS"
    assert US_EQUITY_DAILY_SESSION_SOURCE_VERSION == (
        "exchange_calendars-4.13.2+us-equity-regular-session-dates-v1"
    )

    expected = derive_us_equity_daily_expected_sessions(
        start_date=date(2022, 1, 3),
        end_date=date(2022, 1, 3),
    )

    assert expected.schema_version == "1.0.0"
    assert expected.session_source_id == US_EQUITY_DAILY_SESSION_SOURCE_ID
    assert expected.session_source_version == US_EQUITY_DAILY_SESSION_SOURCE_VERSION
    assert expected.calendar == US_EQUITY_DAILY_SESSION_CALENDAR
    assert expected.timezone == US_EQUITY_DAILY_SESSION_TIMEZONE


def test_basic_known_range_materializes_exact_sessions() -> None:
    expected = derive_us_equity_daily_expected_sessions(
        start_date=date(2022, 1, 1),
        end_date=date(2022, 1, 11),
    )

    assert expected.session_dates == (
        date(2022, 1, 3),
        date(2022, 1, 4),
        date(2022, 1, 5),
        date(2022, 1, 6),
        date(2022, 1, 7),
        date(2022, 1, 10),
        date(2022, 1, 11),
    )
    assert date(2022, 1, 1) not in expected.session_dates
    assert expected.session_dates == tuple(sorted(expected.session_dates))


def test_first_real_target_2024_golden_is_frozen() -> None:
    expected = first_real_target_sessions()

    assert len(expected.session_dates) == 252
    assert expected.session_dates[0] == FIRST_REAL_TARGET_START
    assert expected.session_dates[-1] == FIRST_REAL_TARGET_END
    assert derive_daily_market_data_expected_sessions_hash(expected) == (
        FIRST_REAL_TARGET_HASH
    )


def test_selected_2024_holidays_are_not_sessions() -> None:
    sessions = set(first_real_target_sessions().session_dates)

    assert {
        date(2024, 3, 29),
        date(2024, 6, 19),
        date(2024, 7, 4),
        date(2024, 11, 28),
        date(2024, 12, 25),
    }.isdisjoint(sessions)


def test_selected_2024_early_close_dates_remain_session_dates() -> None:
    sessions = set(first_real_target_sessions().session_dates)

    assert {
        date(2024, 7, 3),
        date(2024, 11, 29),
        date(2024, 12, 24),
    } <= sessions


def test_repeated_calls_produce_identical_materialized_authority() -> None:
    first = first_real_target_sessions()
    second = first_real_target_sessions()

    assert first == second
    assert first is not second
    assert first.session_dates == second.session_dates
    assert first.session_source_id == second.session_source_id
    assert first.session_source_version == second.session_source_version
    assert derive_daily_market_data_expected_sessions_hash(first) == (
        derive_daily_market_data_expected_sessions_hash(second)
    )


@pytest.mark.parametrize(
    "session_date",
    (
        date(2024, 2, 29),
        date(2024, 7, 3),
        date(2024, 7, 5),
        date(2024, 7, 8),
        date(2024, 12, 31),
        date(2025, 1, 2),
    ),
)
def test_one_day_construction_pad_returns_only_requested_session(
    session_date: date,
) -> None:
    expected = derive_us_equity_daily_expected_sessions(
        start_date=session_date,
        end_date=session_date,
    )

    assert expected.session_dates == (session_date,)


@pytest.mark.parametrize(
    "non_session_date",
    (
        date(2024, 7, 4),
        date(2024, 7, 6),
        date(2024, 7, 7),
        date(2025, 1, 1),
    ),
)
def test_one_day_construction_pad_cannot_leak_a_later_session(
    non_session_date: date,
) -> None:
    with pytest.raises(
        DailyMarketDataExpectedSessionsAuthorityError,
        match="contains no XNYS regular sessions",
    ):
        derive_us_equity_daily_expected_sessions(
            start_date=non_session_date,
            end_date=non_session_date,
        )


@pytest.mark.parametrize(
    ("start_date", "end_date", "expected_dates"),
    (
        (
            date(2024, 3, 8),
            date(2024, 3, 12),
            (date(2024, 3, 8), date(2024, 3, 11), date(2024, 3, 12)),
        ),
        (
            date(2024, 11, 1),
            date(2024, 11, 5),
            (date(2024, 11, 1), date(2024, 11, 4), date(2024, 11, 5)),
        ),
    ),
)
def test_dst_transitions_do_not_shift_session_labels(
    start_date: date,
    end_date: date,
    expected_dates: tuple[date, ...],
) -> None:
    expected = derive_us_equity_daily_expected_sessions(
        start_date=start_date,
        end_date=end_date,
    )

    assert expected.session_dates == expected_dates


def test_session_and_non_session_range_boundaries() -> None:
    one_session = derive_us_equity_daily_expected_sessions(
        start_date=date(2022, 1, 3),
        end_date=date(2022, 1, 3),
    )
    weekend_to_monday = derive_us_equity_daily_expected_sessions(
        start_date=date(2022, 1, 8),
        end_date=date(2022, 1, 10),
    )

    assert one_session.session_dates == (date(2022, 1, 3),)
    assert weekend_to_monday.session_dates == (date(2022, 1, 10),)

    with pytest.raises(
        DailyMarketDataExpectedSessionsAuthorityError,
        match="contains no XNYS regular sessions",
    ):
        derive_us_equity_daily_expected_sessions(
            start_date=date(2022, 1, 8),
            end_date=date(2022, 1, 8),
        )

    with pytest.raises(
        DailyMarketDataExpectedSessionsAuthorityError,
        match="end_date must be greater than or equal to start_date",
    ):
        derive_us_equity_daily_expected_sessions(
            start_date=date(2022, 1, 4),
            end_date=date(2022, 1, 3),
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("start_date", datetime(2022, 1, 3, tzinfo=UTC)),
        ("end_date", datetime(2022, 1, 3, tzinfo=UTC)),
        ("start_date", True),
        ("end_date", False),
        ("start_date", "2022-01-03"),
        ("end_date", "2022-01-03"),
        ("start_date", 20220103),
        ("end_date", None),
        ("start_date", DateSubclass(2022, 1, 3)),
        ("end_date", DateSubclass(2022, 1, 3)),
    ),
)
def test_runtime_inputs_must_be_exact_date_values(
    field_name: str,
    value: object,
) -> None:
    arguments: dict[str, object] = {
        "start_date": date(2022, 1, 3),
        "end_date": date(2022, 1, 3),
    }
    arguments[field_name] = value

    with pytest.raises(
        DailyMarketDataExpectedSessionsAuthorityError,
        match=rf"{field_name} must be an exact date value",
    ):
        derive_us_equity_daily_expected_sessions(**arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "reported_version",
    (
        "4.13.1",
        "4.14",
        "malformed",
        MisleadingString("4.13.1"),
        object(),
    ),
)
def test_runtime_version_mismatch_fails_before_calendar_construction(
    monkeypatch: pytest.MonkeyPatch,
    reported_version: object,
) -> None:
    calendar_called = False

    def fail_if_called(*_args: object, **_kwargs: object) -> object:
        nonlocal calendar_called
        calendar_called = True
        raise AssertionError("calendar construction must not run")

    monkeypatch.setattr(
        authority_module,
        "distribution_version",
        lambda _name: reported_version,
    )
    monkeypatch.setattr(
        authority_module,
        "_get_explicitly_bounded_calendar",
        fail_if_called,
    )

    with pytest.raises(
        DailyMarketDataExpectedSessionsAuthorityError,
        match="installed exchange-calendars version must be exactly '4.13.2'",
    ):
        derive_us_equity_daily_expected_sessions(
            start_date=date(2022, 1, 3),
            end_date=date(2022, 1, 3),
        )

    assert not calendar_called


def test_missing_distribution_metadata_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_version(_distribution_name: str) -> str:
        raise PackageNotFoundError("exchange-calendars")

    monkeypatch.setattr(authority_module, "distribution_version", missing_version)

    with pytest.raises(
        DailyMarketDataExpectedSessionsAuthorityError,
        match="exchange-calendars distribution is not installed",
    ):
        derive_us_equity_daily_expected_sessions(
            start_date=date(2022, 1, 3),
            end_date=date(2022, 1, 3),
        )


def test_installed_version_is_captured_once_per_derivation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    reported_versions = iter(("4.13.2", "4.13.1"))

    def counted_version(distribution_name: str) -> str:
        calls.append(distribution_name)
        return next(reported_versions)

    monkeypatch.setattr(authority_module, "distribution_version", counted_version)

    derive_us_equity_daily_expected_sessions(
        start_date=date(2022, 1, 3),
        end_date=date(2022, 1, 3),
    )

    assert calls == ["exchange-calendars"]


@pytest.mark.parametrize(
    "module_name",
    (
        "research_sdk.daily_market_data",
        "research_sdk.daily_market_data_storage",
        "research_sdk.daily_market_data_storage.planning_v2",
        "research_sdk.daily_market_data_storage.local_v2",
    ),
)
def test_public_and_storage_imports_do_not_eagerly_load_calendar_stack(
    module_name: str,
) -> None:
    command = (
        f"import {module_name}; import json, sys; "
        "print(json.dumps({name: name in sys.modules for name in "
        "('exchange_calendars', 'pandas', 'numpy')}))"
    )

    result = subprocess.run(
        [sys.executable, "-c", command],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {
        "exchange_calendars": False,
        "pandas": False,
        "numpy": False,
    }


def test_calendar_is_constructed_with_fixed_name_and_explicit_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, date, date]] = []

    def get_calendar(*, calendar_name: str, start_date: date, end_date: date) -> object:
        calls.append((calendar_name, start_date, end_date))
        return SimpleNamespace(
            name="XNYS",
            tz=ZoneInfo("America/New_York"),
            sessions=(datetime(2022, 1, 3),),
        )

    monkeypatch.setattr(
        authority_module,
        "_get_explicitly_bounded_calendar",
        get_calendar,
    )

    expected = derive_us_equity_daily_expected_sessions(
        start_date=date(2022, 1, 3),
        end_date=date(2022, 1, 3),
    )

    assert calls == [("XNYS", date(2022, 1, 3), date(2022, 1, 4))]
    assert expected.session_dates == (date(2022, 1, 3),)


@pytest.mark.parametrize(
    ("calendar_name", "calendar_timezone", "message"),
    (
        (
            "XNAS",
            ZoneInfo("America/New_York"),
            "calendar authority must identify as XNYS",
        ),
        (
            MisleadingString("XNAS"),
            ZoneInfo("America/New_York"),
            "calendar authority must identify as XNYS",
        ),
        (
            "XNYS",
            ZoneInfo("UTC"),
            "calendar authority timezone must be America/New_York",
        ),
        (
            "XNYS",
            ZoneInfo("US/Eastern"),
            "calendar authority timezone must be America/New_York",
        ),
        (
            "XNYS",
            timezone(timedelta(hours=-5)),
            "calendar authority timezone must be America/New_York",
        ),
        (
            "XNYS",
            SimpleNamespace(key=MisleadingString("America/New_York")),
            "calendar authority timezone must be America/New_York",
        ),
    ),
)
def test_incoherent_calendar_authority_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    calendar_name: object,
    calendar_timezone: object,
    message: str,
) -> None:
    monkeypatch.setattr(
        authority_module,
        "_get_explicitly_bounded_calendar",
        lambda **_kwargs: SimpleNamespace(
            name=calendar_name,
            tz=calendar_timezone,
            sessions=(datetime(2022, 1, 3),),
        ),
    )

    with pytest.raises(DailyMarketDataExpectedSessionsAuthorityError, match=message):
        derive_us_equity_daily_expected_sessions(
            start_date=date(2022, 1, 3),
            end_date=date(2022, 1, 3),
        )


@pytest.mark.parametrize(
    ("labels", "message"),
    (
        (
            (datetime(2022, 1, 4), datetime(2022, 1, 3)),
            "unique and strictly ascending",
        ),
        (
            (datetime(2022, 1, 3), datetime(2022, 1, 3)),
            "unique and strictly ascending",
        ),
        ((datetime(2022, 1, 2),), "outside the requested inclusive range"),
        ((object(),), "session labels must expose a date value"),
        (
            (SimpleNamespace(date=lambda: datetime(2022, 1, 3)),),
            "session labels must materialize as exact date values",
        ),
        (None, "session labels must be iterable"),
        ((), "contains no XNYS regular sessions"),
    ),
)
def test_faulty_calendar_dates_are_not_sorted_deduplicated_or_repaired(
    monkeypatch: pytest.MonkeyPatch,
    labels: object,
    message: str,
) -> None:
    monkeypatch.setattr(
        authority_module,
        "_get_explicitly_bounded_calendar",
        lambda **_kwargs: SimpleNamespace(
            name="XNYS",
            tz=ZoneInfo("America/New_York"),
            sessions=labels,
        ),
    )

    with pytest.raises(DailyMarketDataExpectedSessionsAuthorityError, match=message):
        derive_us_equity_daily_expected_sessions(
            start_date=date(2022, 1, 3),
            end_date=date(2022, 1, 4),
        )


def test_calendar_authority_fields_are_captured_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DynamicCalendar:
        def __init__(self) -> None:
            self.name_reads = 0
            self.timezone_reads = 0
            self.session_reads = 0

        @property
        def name(self) -> str:
            self.name_reads += 1
            return "XNYS" if self.name_reads == 1 else "XNAS"

        @property
        def tz(self) -> ZoneInfo:
            self.timezone_reads += 1
            return ZoneInfo("America/New_York" if self.timezone_reads == 1 else "UTC")

        @property
        def sessions(self) -> tuple[datetime, ...]:
            self.session_reads += 1
            if self.session_reads > 1:
                raise AssertionError("sessions must be captured exactly once")
            return (datetime(2022, 1, 3),)

    calendar = DynamicCalendar()
    monkeypatch.setattr(
        authority_module,
        "_get_explicitly_bounded_calendar",
        lambda **_kwargs: calendar,
    )

    expected = derive_us_equity_daily_expected_sessions(
        start_date=date(2022, 1, 3),
        end_date=date(2022, 1, 3),
    )

    assert expected.session_dates == (date(2022, 1, 3),)
    assert calendar.name_reads == 1
    assert calendar.timezone_reads == 1
    assert calendar.session_reads == 1


def test_unreadable_calendar_authority_is_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        authority_module,
        "_get_explicitly_bounded_calendar",
        lambda **_kwargs: SimpleNamespace(
            name="XNYS",
            tz=ZoneInfo("America/New_York"),
        ),
    )

    with pytest.raises(
        DailyMarketDataExpectedSessionsAuthorityError,
        match="calendar authority metadata and session labels must be readable",
    ):
        derive_us_equity_daily_expected_sessions(
            start_date=date(2022, 1, 3),
            end_date=date(2022, 1, 3),
        )


def test_calendar_construction_failure_is_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import exchange_calendars  # type: ignore[import-untyped]

    def fail_calendar_construction(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("synthetic calendar failure")

    monkeypatch.setattr(
        exchange_calendars,
        "get_calendar",
        fail_calendar_construction,
    )

    with pytest.raises(
        DailyMarketDataExpectedSessionsAuthorityError,
        match="failed to construct explicitly bounded XNYS calendar authority",
    ):
        derive_us_equity_daily_expected_sessions(
            start_date=date(2022, 1, 3),
            end_date=date(2022, 1, 3),
        )


def test_output_contains_only_immutable_contract_data() -> None:
    expected = derive_us_equity_daily_expected_sessions(
        start_date=date(2022, 1, 3),
        end_date=date(2022, 1, 4),
    )

    assert isinstance(expected, DailyMarketDataExpectedSessions)
    assert type(expected.session_dates) is tuple
    assert all(type(session_date) is date for session_date in expected.session_dates)
    assert not any(callable(value) for value in expected.model_dump().values())
    with pytest.raises(ValidationError, match="frozen"):
        setattr(expected, "session_dates", (date(2022, 1, 5),))


def test_function_has_no_instrument_provider_or_venue_input() -> None:
    signature = inspect.signature(derive_us_equity_daily_expected_sessions)

    assert tuple(signature.parameters) == ("start_date", "end_date")
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in signature.parameters.values()
    )


def test_same_authority_is_reusable_for_qqq_xnas_and_spy_arcx() -> None:
    qqq = DailyMarketDataInstrument(
        instrument_id="instrument-us-etf-qqq-xnas",
        symbol="QQQ",
        venue="XNAS",
    )
    spy = DailyMarketDataInstrument(
        instrument_id="instrument-us-etf-spy-arcx",
        symbol="SPY",
        venue="ARCX",
    )
    asset_sessions = derive_us_equity_daily_expected_sessions(
        start_date=FIRST_REAL_TARGET_START,
        end_date=FIRST_REAL_TARGET_END,
    )
    benchmark_sessions = derive_us_equity_daily_expected_sessions(
        start_date=FIRST_REAL_TARGET_START,
        end_date=FIRST_REAL_TARGET_END,
    )

    assert qqq.venue == "XNAS"
    assert spy.venue == "ARCX"
    assert qqq.venue != asset_sessions.calendar
    assert spy.venue != benchmark_sessions.calendar
    assert asset_sessions == benchmark_sessions
    assert asset_sessions.calendar == "XNYS"


def test_frozen_authority_is_process_and_local_timezone_independent() -> None:
    command = "\n".join(
        (
            "from datetime import date",
            "from research_sdk.daily_market_data import (",
            "    derive_daily_market_data_expected_sessions_hash,",
            "    derive_us_equity_daily_expected_sessions,",
            ")",
            "expected = derive_us_equity_daily_expected_sessions(",
            "    start_date=date(2024, 1, 2),",
            "    end_date=date(2024, 12, 31),",
            ")",
            "print(derive_daily_market_data_expected_sessions_hash(expected))",
        )
    )

    for process_timezone in ("UTC", "America/Los_Angeles", "Asia/Tokyo"):
        result = subprocess.run(
            [sys.executable, "-c", command],
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "TZ": process_timezone},
        )
        assert result.stdout.strip() == FIRST_REAL_TARGET_HASH


def test_generated_sessions_are_directly_compatible_with_snapshot_v2_planning() -> None:
    expected = derive_us_equity_daily_expected_sessions(
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 5),
    )

    plan = sample_plan_v2(expected_sessions=expected)
    verified = verify_daily_market_data_snapshot_bundle_v2(plan.as_file_map())

    assert verified.expected_sessions == expected
    assert plan.expected_sessions_hash == (
        derive_daily_market_data_expected_sessions_hash(expected)
    )


def first_real_target_sessions() -> DailyMarketDataExpectedSessions:
    return derive_us_equity_daily_expected_sessions(
        start_date=FIRST_REAL_TARGET_START,
        end_date=FIRST_REAL_TARGET_END,
    )
