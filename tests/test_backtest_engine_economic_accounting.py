from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from backtest_engine.economic_accounting import (
    apply_session_open_economic_accounting,
    value_economic_portfolio,
)
from backtest_engine.economic_models import (
    ECONOMIC_ACCOUNTING_POLICY_VERSION,
    CashDistributionReceivable,
    EconomicAccountingError,
    EconomicPortfolioState,
)
from research_sdk.contracts.daily_market_data_economics import (
    DailyMarketDataCashDistribution,
    DailyMarketDataSplit,
    DailyMarketDataUnsupportedCorporateAction,
)

INSTRUMENT_ID = "instrument-us-etf-qqq-xnas"
OTHER_INSTRUMENT_ID = "instrument-us-etf-spy-arcx"
SESSIONS = (
    date(2026, 1, 2),
    date(2026, 1, 5),
    date(2026, 1, 6),
    date(2026, 1, 9),
)


def test_accounting_policy_version_is_frozen() -> None:
    assert ECONOMIC_ACCOUNTING_POLICY_VERSION == "daily-etf-economic-accounting-v1"


def test_receivable_amount_must_match_quantity_times_amount_per_share() -> None:
    with pytest.raises(ValidationError, match="receivable_amount must equal"):
        receivable(
            event_id="dist-bad-receivable",
            ex_date=date(2026, 1, 2),
            amount_per_share=Decimal("0.50"),
            receivable_amount=Decimal("49.990000"),
            payable_date=date(2026, 1, 5),
            cash_available_session=date(2026, 1, 6),
        )


def test_portfolio_receivables_must_have_applied_event_ids() -> None:
    with pytest.raises(ValidationError, match="receivable event ID must be applied"):
        portfolio_state(
            quantity=100,
            total_book_cost=Decimal("10000"),
            receivables=(
                receivable(
                    event_id="dist-unapplied",
                    ex_date=date(2026, 1, 2),
                    payable_date=date(2026, 1, 5),
                    cash_available_session=date(2026, 1, 6),
                ),
            ),
        )


def test_portfolio_receivables_are_canonicalized_on_construction() -> None:
    later = receivable(
        event_id="dist-later",
        ex_date=date(2026, 1, 5),
        payable_date=date(2026, 1, 9),
        cash_available_session=None,
    )
    earlier_b = receivable(
        event_id="dist-b",
        ex_date=date(2026, 1, 2),
        payable_date=date(2026, 1, 5),
        cash_available_session=date(2026, 1, 6),
    )
    earlier_a = receivable(
        event_id="dist-a",
        ex_date=date(2026, 1, 2),
        payable_date=date(2026, 1, 5),
        cash_available_session=date(2026, 1, 6),
    )

    state = portfolio_state(
        quantity=100,
        total_book_cost=Decimal("10000"),
        receivables=(later, earlier_b, earlier_a),
        applied_corporate_action_event_ids=(
            "dist-a",
            "dist-b",
            "dist-later",
        ),
    )

    assert tuple(item.event_id for item in state.receivables) == (
        "dist-a",
        "dist-b",
        "dist-later",
    )


def test_two_for_one_split_preserves_market_value_and_book_cost() -> None:
    state = portfolio_state(quantity=100, total_book_cost=Decimal("7500"))
    before = value_economic_portfolio(
        state=state,
        session_date=date(2026, 1, 2),
        market_price=Decimal("100"),
    )

    new_state, records = apply_session_open_economic_accounting(
        state=state,
        session_date=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
        corporate_action_events=(
            split_event("split-2-for-1", effective_date=date(2026, 1, 5)),
        ),
    )
    after = value_economic_portfolio(
        state=new_state,
        session_date=date(2026, 1, 5),
        market_price=Decimal("50"),
    )

    assert new_state.quantity == 200
    assert new_state.total_book_cost == Decimal("7500.000000")
    assert before.market_value == after.market_value == Decimal("10000.000000")
    assert records[0].accounting_action == "split_applied"


def test_non_divisible_reverse_split_fails_and_leaves_state_untouched() -> None:
    state = portfolio_state(quantity=100, total_book_cost=Decimal("10000"))

    with pytest.raises(EconomicAccountingError, match="fractional strategy shares"):
        apply_session_open_economic_accounting(
            state=state,
            session_date=date(2026, 1, 5),
            expected_session_dates=SESSIONS,
            corporate_action_events=(
                split_event(
                    "split-1-for-3",
                    effective_date=date(2026, 1, 5),
                    numerator=1,
                    denominator=3,
                ),
            ),
        )

    assert state.quantity == 100
    assert state.applied_corporate_action_event_ids == ()


def test_zero_holdings_split_is_harmless() -> None:
    state = portfolio_state(quantity=0, total_book_cost=Decimal("0"))

    new_state, records = apply_session_open_economic_accounting(
        state=state,
        session_date=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
        corporate_action_events=(
            split_event("split-zero", effective_date=date(2026, 1, 5)),
        ),
    )

    assert new_state.quantity == 0
    assert new_state.total_book_cost == Decimal("0.000000")
    assert records[0].pre_quantity == records[0].post_quantity == 0


def test_multiple_splits_same_day_with_holdings_fail() -> None:
    state = portfolio_state(quantity=100, total_book_cost=Decimal("10000"))

    with pytest.raises(EconomicAccountingError, match="multiple same-day splits"):
        apply_session_open_economic_accounting(
            state=state,
            session_date=date(2026, 1, 5),
            expected_session_dates=SESSIONS,
            corporate_action_events=(
                split_event("split-a", effective_date=date(2026, 1, 5)),
                split_event(
                    "split-b",
                    effective_date=date(2026, 1, 5),
                    numerator=3,
                    denominator=1,
                ),
            ),
        )


def test_held_before_ex_date_earns_entitlement() -> None:
    state = portfolio_state(quantity=100, total_book_cost=Decimal("10000"))

    new_state, records = apply_session_open_economic_accounting(
        state=state,
        session_date=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
        corporate_action_events=(
            cash_distribution_event(
                "dist-held",
                ex_date=date(2026, 1, 5),
                amount=Decimal("0.50"),
                payable_date=date(2026, 1, 5),
            ),
        ),
    )

    assert len(new_state.receivables) == 1
    assert new_state.receivables[0].entitled_quantity == 100
    assert new_state.receivables[0].receivable_amount == Decimal("50.000000")
    assert new_state.receivables[0].cash_available_session == date(2026, 1, 6)
    assert records[0].accounting_action == "cash_distribution_entitlement"


def test_zero_holdings_on_ex_date_earns_no_entitlement() -> None:
    state = portfolio_state(quantity=0, total_book_cost=Decimal("0"))

    new_state, records = apply_session_open_economic_accounting(
        state=state,
        session_date=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
        corporate_action_events=(
            cash_distribution_event(
                "dist-zero",
                ex_date=date(2026, 1, 5),
                amount=Decimal("0.50"),
                payable_date=date(2026, 1, 5),
            ),
        ),
    )

    assert new_state.receivables == ()
    assert records[0].entitlement_quantity == 0
    assert records[0].receivable_delta == Decimal("0.000000")


def test_bought_on_ex_date_is_represented_by_zero_pre_open_holdings() -> None:
    state = portfolio_state(quantity=0, total_book_cost=Decimal("0"))

    new_state, _records = apply_session_open_economic_accounting(
        state=state,
        session_date=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
        corporate_action_events=(
            cash_distribution_event(
                "dist-before-buy",
                ex_date=date(2026, 1, 5),
                amount=Decimal("1"),
                payable_date=date(2026, 1, 5),
            ),
        ),
    )

    assert new_state.quantity == 0
    assert new_state.receivables == ()


def test_receivable_offsets_synthetic_raw_price_distribution_drop() -> None:
    before_state = portfolio_state(quantity=100, total_book_cost=Decimal("10000"))
    before = value_economic_portfolio(
        state=before_state,
        session_date=date(2026, 1, 2),
        market_price=Decimal("100"),
    )
    ex_state, _records = apply_session_open_economic_accounting(
        state=before_state,
        session_date=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
        corporate_action_events=(
            cash_distribution_event(
                "dist-raw-drop",
                ex_date=date(2026, 1, 5),
                amount=Decimal("0.50"),
                payable_date=date(2026, 1, 5),
            ),
        ),
    )

    after = value_economic_portfolio(
        state=ex_state,
        session_date=date(2026, 1, 5),
        market_price=Decimal("99.50"),
    )

    assert before.total_equity == Decimal("10000.000000")
    assert after.market_value == Decimal("9950.000000")
    assert after.receivable_value == Decimal("50.000000")
    assert after.total_equity == Decimal("10000.000000")


def test_missing_payable_date_with_entitlement_fails() -> None:
    state = portfolio_state(quantity=100, total_book_cost=Decimal("10000"))

    with pytest.raises(EconomicAccountingError, match="requires payable_date"):
        apply_session_open_economic_accounting(
            state=state,
            session_date=date(2026, 1, 5),
            expected_session_dates=SESSIONS,
            corporate_action_events=(
                cash_distribution_event(
                    "dist-no-pay",
                    ex_date=date(2026, 1, 5),
                    payable_date=None,
                ),
            ),
        )


def test_missing_payable_date_with_zero_holdings_does_not_fail() -> None:
    state = portfolio_state(quantity=0, total_book_cost=Decimal("0"))

    new_state, records = apply_session_open_economic_accounting(
        state=state,
        session_date=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
        corporate_action_events=(
            cash_distribution_event(
                "dist-no-pay-zero",
                ex_date=date(2026, 1, 5),
                payable_date=None,
            ),
        ),
    )

    assert new_state.receivables == ()
    assert records[0].entitlement_quantity == 0


def test_zero_holding_distribution_is_marked_applied_and_cannot_replay() -> None:
    state = portfolio_state(quantity=0, total_book_cost=Decimal("0"))
    event = cash_distribution_event(
        "dist-zero-replay",
        ex_date=date(2026, 1, 5),
        payable_date=None,
    )

    new_state, _records = apply_session_open_economic_accounting(
        state=state,
        session_date=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
        corporate_action_events=(event,),
    )

    assert new_state.receivables == ()
    assert new_state.applied_corporate_action_event_ids == ("dist-zero-replay",)
    with pytest.raises(EconomicAccountingError, match="already applied"):
        apply_session_open_economic_accounting(
            state=new_state,
            session_date=date(2026, 1, 5),
            expected_session_dates=SESSIONS,
            corporate_action_events=(event,),
        )


def test_payable_date_before_ex_date_fails_when_entitled() -> None:
    state = portfolio_state(quantity=100, total_book_cost=Decimal("10000"))

    with pytest.raises(EconomicAccountingError, match="payable_date"):
        apply_session_open_economic_accounting(
            state=state,
            session_date=date(2026, 1, 5),
            expected_session_dates=SESSIONS,
            corporate_action_events=(
                cash_distribution_event(
                    "dist-bad-pay",
                    ex_date=date(2026, 1, 5),
                    payable_date=date(2026, 1, 2),
                ),
            ),
        )


def test_settlement_occurs_at_first_expected_session_strictly_after_payable_date() -> (
    None
):
    entitled_state, _records = apply_session_open_economic_accounting(
        state=portfolio_state(quantity=100, total_book_cost=Decimal("10000")),
        session_date=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
        corporate_action_events=(
            cash_distribution_event(
                "dist-settle",
                ex_date=date(2026, 1, 5),
                payable_date=date(2026, 1, 5),
            ),
        ),
    )

    next_state, records = apply_session_open_economic_accounting(
        state=entitled_state,
        session_date=date(2026, 1, 6),
        expected_session_dates=SESSIONS,
        corporate_action_events=(),
    )

    assert next_state.cash == Decimal("50.000000")
    assert next_state.receivables == ()
    assert records[0].accounting_action == "cash_distribution_settlement"


def test_payable_date_equal_ex_date_is_not_same_day_cash() -> None:
    new_state, _records = apply_session_open_economic_accounting(
        state=portfolio_state(quantity=100, total_book_cost=Decimal("10000")),
        session_date=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
        corporate_action_events=(
            cash_distribution_event(
                "dist-ex-pay-same",
                ex_date=date(2026, 1, 5),
                payable_date=date(2026, 1, 5),
            ),
        ),
    )

    assert new_state.cash == Decimal("0.000000")
    assert new_state.receivables[0].cash_available_session == date(2026, 1, 6)


def test_payable_date_on_non_session_maps_to_next_expected_session() -> None:
    new_state, _records = apply_session_open_economic_accounting(
        state=portfolio_state(quantity=100, total_book_cost=Decimal("10000")),
        session_date=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
        corporate_action_events=(
            cash_distribution_event(
                "dist-weekend-pay",
                ex_date=date(2026, 1, 5),
                payable_date=date(2026, 1, 7),
            ),
        ),
    )

    assert new_state.receivables[0].cash_available_session == date(2026, 1, 9)


def test_settlement_preserves_equity_holding_market_value_constant() -> None:
    entitled_state = portfolio_state(
        quantity=100,
        total_book_cost=Decimal("10000"),
        receivables=(
            CashDistributionReceivable(
                event_id="dist-existing",
                instrument_id=INSTRUMENT_ID,
                ex_date=date(2026, 1, 2),
                entitled_quantity=100,
                amount_per_share=Decimal("0.50"),
                receivable_amount=Decimal("50.000000"),
                currency="USD",
                payable_date=date(2026, 1, 5),
                cash_available_session=date(2026, 1, 6),
            ),
        ),
        applied_corporate_action_event_ids=("dist-existing",),
    )
    before = value_economic_portfolio(
        state=entitled_state,
        session_date=date(2026, 1, 5),
        market_price=Decimal("99.50"),
    )

    settled_state, _records = apply_session_open_economic_accounting(
        state=entitled_state,
        session_date=date(2026, 1, 6),
        expected_session_dates=SESSIONS,
        corporate_action_events=(),
    )
    after = value_economic_portfolio(
        state=settled_state,
        session_date=date(2026, 1, 6),
        market_price=Decimal("99.50"),
    )

    assert before.total_equity == after.total_equity
    assert after.cash == Decimal("50.000000")
    assert after.receivable_value == Decimal("0.000000")


def test_multiple_receivable_settlement_preserves_later_receivable() -> None:
    state = portfolio_state(
        quantity=100,
        total_book_cost=Decimal("10000"),
        receivables=(
            receivable(
                event_id="dist-settle-b",
                ex_date=date(2026, 1, 2),
                amount_per_share=Decimal("0.25"),
                receivable_amount=Decimal("25.000000"),
                payable_date=date(2026, 1, 5),
                cash_available_session=date(2026, 1, 6),
            ),
            receivable(
                event_id="dist-later",
                ex_date=date(2026, 1, 5),
                amount_per_share=Decimal("0.75"),
                receivable_amount=Decimal("75.000000"),
                payable_date=date(2026, 1, 6),
                cash_available_session=date(2026, 1, 9),
            ),
            receivable(
                event_id="dist-settle-a",
                ex_date=date(2026, 1, 2),
                amount_per_share=Decimal("0.50"),
                receivable_amount=Decimal("50.000000"),
                payable_date=date(2026, 1, 5),
                cash_available_session=date(2026, 1, 6),
            ),
        ),
        applied_corporate_action_event_ids=(
            "dist-later",
            "dist-settle-a",
            "dist-settle-b",
        ),
    )
    before = value_economic_portfolio(
        state=state,
        session_date=date(2026, 1, 5),
        market_price=Decimal("99.50"),
    )

    new_state, records = apply_session_open_economic_accounting(
        state=state,
        session_date=date(2026, 1, 6),
        expected_session_dates=SESSIONS,
        corporate_action_events=(),
    )
    after = value_economic_portfolio(
        state=new_state,
        session_date=date(2026, 1, 6),
        market_price=Decimal("99.50"),
    )

    assert new_state.cash == Decimal("75.000000")
    assert tuple(item.event_id for item in new_state.receivables) == ("dist-later",)
    assert tuple(record.event_id for record in records) == (
        "dist-settle-a",
        "dist-settle-b",
    )
    assert before.total_equity == after.total_equity


def test_pay_after_supplied_session_horizon_leaves_receivable_outstanding() -> None:
    new_state, _records = apply_session_open_economic_accounting(
        state=portfolio_state(quantity=100, total_book_cost=Decimal("10000")),
        session_date=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
        corporate_action_events=(
            cash_distribution_event(
                "dist-after-horizon",
                ex_date=date(2026, 1, 5),
                payable_date=date(2026, 1, 9),
            ),
        ),
    )

    assert new_state.receivables[0].cash_available_session is None


def test_multiple_same_day_cash_distributions_produce_separate_receivables() -> None:
    new_state, records = apply_session_open_economic_accounting(
        state=portfolio_state(quantity=100, total_book_cost=Decimal("10000")),
        session_date=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
        corporate_action_events=(
            cash_distribution_event(
                "dist-b",
                ex_date=date(2026, 1, 5),
                amount=Decimal("0.25"),
                payable_date=date(2026, 1, 5),
            ),
            cash_distribution_event(
                "dist-a",
                ex_date=date(2026, 1, 5),
                amount=Decimal("0.50"),
                payable_date=date(2026, 1, 5),
            ),
        ),
    )

    assert tuple(receivable.event_id for receivable in new_state.receivables) == (
        "dist-a",
        "dist-b",
    )
    assert tuple(record.event_id for record in records) == ("dist-a", "dist-b")


def test_same_day_cash_distribution_order_is_canonicalized() -> None:
    state = portfolio_state(quantity=100, total_book_cost=Decimal("10000"))
    event_a = cash_distribution_event(
        "dist-order-a",
        ex_date=date(2026, 1, 5),
        amount=Decimal("0.50"),
        payable_date=date(2026, 1, 5),
    )
    event_b = cash_distribution_event(
        "dist-order-b",
        ex_date=date(2026, 1, 5),
        amount=Decimal("0.25"),
        payable_date=date(2026, 1, 5),
    )

    state_ab, records_ab = apply_session_open_economic_accounting(
        state=state,
        session_date=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
        corporate_action_events=(event_a, event_b),
    )
    state_ba, records_ba = apply_session_open_economic_accounting(
        state=state,
        session_date=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
        corporate_action_events=(event_b, event_a),
    )

    assert state_ab == state_ba
    assert records_ab == records_ba


def test_duplicate_current_session_event_ids_fail_closed() -> None:
    state = portfolio_state(quantity=100, total_book_cost=Decimal("10000"))
    event = cash_distribution_event(
        "dist-same-call-duplicate",
        ex_date=date(2026, 1, 5),
        payable_date=date(2026, 1, 5),
    )

    with pytest.raises(EconomicAccountingError, match="duplicate IDs"):
        apply_session_open_economic_accounting(
            state=state,
            session_date=date(2026, 1, 5),
            expected_session_dates=SESSIONS,
            corporate_action_events=(event, event),
        )

    assert state.receivables == ()
    assert state.applied_corporate_action_event_ids == ()


def test_same_day_split_and_distribution_with_holdings_fails_atomically() -> None:
    state = portfolio_state(quantity=100, total_book_cost=Decimal("10000"))

    with pytest.raises(EconomicAccountingError, match="ambiguous"):
        apply_session_open_economic_accounting(
            state=state,
            session_date=date(2026, 1, 5),
            expected_session_dates=SESSIONS,
            corporate_action_events=(
                split_event("split-with-dist", effective_date=date(2026, 1, 5)),
                cash_distribution_event(
                    "dist-with-split",
                    ex_date=date(2026, 1, 5),
                    payable_date=date(2026, 1, 5),
                ),
            ),
        )

    assert state.quantity == 100
    assert state.receivables == ()
    assert state.applied_corporate_action_event_ids == ()


def test_settlement_plus_invalid_current_event_fails_atomically() -> None:
    state = portfolio_state(
        quantity=100,
        total_book_cost=Decimal("10000"),
        receivables=(
            receivable(
                event_id="dist-due",
                ex_date=date(2026, 1, 2),
                payable_date=date(2026, 1, 5),
                cash_available_session=date(2026, 1, 6),
            ),
        ),
        applied_corporate_action_event_ids=("dist-due",),
    )

    with pytest.raises(EconomicAccountingError, match="unsupported"):
        apply_session_open_economic_accounting(
            state=state,
            session_date=date(2026, 1, 6),
            expected_session_dates=SESSIONS,
            corporate_action_events=(
                unsupported_event("unsupported-today", effective_date=date(2026, 1, 6)),
            ),
        )

    assert state.cash == Decimal("0.000000")
    assert tuple(item.event_id for item in state.receivables) == ("dist-due",)


def test_unsupported_event_fails() -> None:
    state = portfolio_state(quantity=0, total_book_cost=Decimal("0"))

    with pytest.raises(EconomicAccountingError, match="unsupported"):
        apply_session_open_economic_accounting(
            state=state,
            session_date=date(2026, 1, 5),
            expected_session_dates=SESSIONS,
            corporate_action_events=(
                unsupported_event("unsupported", effective_date=date(2026, 1, 5)),
            ),
        )


def test_event_instrument_mismatch_fails() -> None:
    state = portfolio_state(quantity=100, total_book_cost=Decimal("10000"))

    with pytest.raises(EconomicAccountingError, match="instrument_id"):
        apply_session_open_economic_accounting(
            state=state,
            session_date=date(2026, 1, 5),
            expected_session_dates=SESSIONS,
            corporate_action_events=(
                split_event(
                    "split-other-instrument",
                    effective_date=date(2026, 1, 5),
                    instrument_id=OTHER_INSTRUMENT_ID,
                ),
            ),
        )


def test_cash_currency_mismatch_fails() -> None:
    state = portfolio_state(quantity=100, total_book_cost=Decimal("10000"))

    with pytest.raises(EconomicAccountingError, match="currency"):
        apply_session_open_economic_accounting(
            state=state,
            session_date=date(2026, 1, 5),
            expected_session_dates=SESSIONS,
            corporate_action_events=(
                cash_distribution_event(
                    "dist-currency",
                    ex_date=date(2026, 1, 5),
                    payable_date=date(2026, 1, 5),
                    currency="CAD",
                ),
            ),
        )


def test_duplicate_economic_event_application_fails_and_leaves_state_untouched() -> (
    None
):
    state = portfolio_state(
        quantity=100,
        total_book_cost=Decimal("10000"),
        applied_corporate_action_event_ids=("dist-duplicate",),
    )

    with pytest.raises(EconomicAccountingError, match="already applied"):
        apply_session_open_economic_accounting(
            state=state,
            session_date=date(2026, 1, 5),
            expected_session_dates=SESSIONS,
            corporate_action_events=(
                cash_distribution_event(
                    "dist-duplicate",
                    ex_date=date(2026, 1, 5),
                    payable_date=date(2026, 1, 5),
                ),
            ),
        )

    assert state.receivables == ()
    assert state.applied_corporate_action_event_ids == ("dist-duplicate",)


def test_record_date_does_not_drive_entitlement() -> None:
    state = portfolio_state(quantity=100, total_book_cost=Decimal("10000"))

    new_state, _records = apply_session_open_economic_accounting(
        state=state,
        session_date=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
        corporate_action_events=(
            cash_distribution_event(
                "dist-record-date",
                ex_date=date(2026, 1, 5),
                payable_date=date(2026, 1, 5),
                record_date=date(2026, 1, 9),
            ),
        ),
    )

    assert new_state.receivables[0].entitled_quantity == 100


def test_announced_and_source_available_do_not_drive_cash_timing() -> None:
    state = portfolio_state(quantity=100, total_book_cost=Decimal("10000"))

    new_state, _records = apply_session_open_economic_accounting(
        state=state,
        session_date=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
        corporate_action_events=(
            cash_distribution_event(
                "dist-source-time",
                ex_date=date(2026, 1, 5),
                payable_date=date(2026, 1, 5),
                announced_at=datetime(2026, 1, 4, 18, 0, tzinfo=UTC),
                source_available_at=datetime(2026, 1, 8, 18, 0, tzinfo=UTC),
            ),
        ),
    )

    assert new_state.receivables[0].cash_available_session == date(2026, 1, 6)


def test_receivable_creation_uses_round_half_even_midpoint() -> None:
    new_state, _records = apply_session_open_economic_accounting(
        state=portfolio_state(quantity=3, total_book_cost=Decimal("300")),
        session_date=date(2026, 1, 5),
        expected_session_dates=SESSIONS,
        corporate_action_events=(
            cash_distribution_event(
                "dist-half-even",
                ex_date=date(2026, 1, 5),
                amount=Decimal("0.3333335"),
                payable_date=date(2026, 1, 5),
            ),
        ),
    )

    assert new_state.receivables[0].receivable_amount == Decimal("1.000000")


def portfolio_state(
    *,
    quantity: int,
    total_book_cost: Decimal,
    cash: Decimal = Decimal("0"),
    receivables: tuple[CashDistributionReceivable, ...] = (),
    applied_corporate_action_event_ids: tuple[str, ...] = (),
) -> EconomicPortfolioState:
    return EconomicPortfolioState(
        instrument_id=INSTRUMENT_ID,
        currency="USD",
        cash=cash,
        quantity=quantity,
        total_book_cost=total_book_cost,
        receivables=receivables,
        applied_corporate_action_event_ids=applied_corporate_action_event_ids,
    )


def receivable(
    *,
    event_id: str,
    ex_date: date,
    amount_per_share: Decimal = Decimal("0.50"),
    receivable_amount: Decimal = Decimal("50.000000"),
    payable_date: date,
    cash_available_session: date | None,
) -> CashDistributionReceivable:
    return CashDistributionReceivable(
        event_id=event_id,
        instrument_id=INSTRUMENT_ID,
        ex_date=ex_date,
        entitled_quantity=100,
        amount_per_share=amount_per_share,
        receivable_amount=receivable_amount,
        currency="USD",
        payable_date=payable_date,
        cash_available_session=cash_available_session,
    )


def split_event(
    event_id: str,
    *,
    effective_date: date,
    numerator: int = 2,
    denominator: int = 1,
    instrument_id: str = INSTRUMENT_ID,
) -> DailyMarketDataSplit:
    return DailyMarketDataSplit(
        schema_version="1.0.0",
        event_id=event_id,
        instrument_id=instrument_id,
        source_event_reference=f"synthetic://{event_id}",
        source_available_at=datetime(2026, 1, 2, tzinfo=UTC),
        effective_date=effective_date,
        numerator=numerator,
        denominator=denominator,
    )


def cash_distribution_event(
    event_id: str,
    *,
    ex_date: date,
    amount: Decimal = Decimal("0.50"),
    currency: str = "USD",
    payable_date: date | None,
    record_date: date | None = None,
    announced_at: datetime | None = None,
    source_available_at: datetime = datetime(2026, 1, 2, tzinfo=UTC),
) -> DailyMarketDataCashDistribution:
    return DailyMarketDataCashDistribution(
        schema_version="1.0.0",
        event_id=event_id,
        instrument_id=INSTRUMENT_ID,
        source_event_reference=f"synthetic://{event_id}",
        source_available_at=source_available_at,
        ex_date=ex_date,
        amount=amount,
        currency=currency,
        record_date=record_date,
        payable_date=payable_date,
        announced_at=announced_at,
    )


def unsupported_event(
    event_id: str,
    *,
    effective_date: date,
) -> DailyMarketDataUnsupportedCorporateAction:
    return DailyMarketDataUnsupportedCorporateAction(
        schema_version="1.0.0",
        event_id=event_id,
        instrument_id=INSTRUMENT_ID,
        source_event_reference=f"synthetic://{event_id}",
        source_available_at=datetime(2026, 1, 2, tzinfo=UTC),
        effective_date=effective_date,
        provider_event_type="merger",
        description="unsupported synthetic event",
    )
