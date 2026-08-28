from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from backtest_engine import (
    CompletedEconomicBacktestLedgerMappingInput,
    CompletedEconomicBacktestResult,
    CompletedEconomicResultValidationError,
    ResolvedEconomicBacktestConfig,
    canonicalize_completed_economic_backtest_result,
    generate_economic_artifact_bundle,
    map_completed_economic_backtest_to_ledger_records,
    run_snapshot_v2_buy_and_hold_backtest,
)
from helpers_backtest_engine_economic import (
    DEFAULT_SESSIONS,
    QQQ_INSTRUMENT_ID,
    SPY_INSTRUMENT_ID,
    compatible_profile,
    execution_metadata,
    qqq_bundle_files,
    resolved_config,
    spy_bundle_files,
)
from helpers_daily_market_data_snapshots_v2 import cash_distribution_v2
from research_sdk.contracts import ReviewMetadata, ReviewStatus

STALE_RESULT_MUTATIONS = (
    "total_return",
    "benchmark_total_return",
    "excess_return",
    "observation_count",
    "maximum_drawdown",
    "drawdown_series",
    "monthly_returns",
    "ending_total_book_cost",
    "ending_strategy_receivables",
    "ending_benchmark_receivables",
    "first_trade_quantity",
    "first_trade_commission",
    "first_daily_cash",
    "first_daily_book_cost",
    "missing_action_application",
    "duplicate_action_application",
)


@pytest.mark.parametrize("mutation", STALE_RESULT_MUTATIONS)
def test_canonical_result_validation_rejects_stale_economic_outputs(
    mutation: str,
) -> None:
    result = completed_result_with_horizon_receivables()
    stale = stale_result(result, mutation)

    with pytest.raises(CompletedEconomicResultValidationError):
        canonicalize_completed_economic_backtest_result(stale)


def test_artifact_generation_rejects_stale_result_before_writing(
    tmp_path: Path,
) -> None:
    result = completed_result_with_horizon_receivables()
    stale = stale_result(result, "total_return")

    with pytest.raises(CompletedEconomicResultValidationError):
        generate_economic_artifact_bundle(result=stale, artifact_base_dir=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_ledger_mapping_rejects_stale_result_before_record_construction(
    tmp_path: Path,
) -> None:
    result = completed_result_with_horizon_receivables()
    artifacts = generate_economic_artifact_bundle(
        result=result,
        artifact_base_dir=tmp_path,
    )
    stale = stale_result(result, "missing_action_application")

    with pytest.raises(CompletedEconomicResultValidationError):
        map_completed_economic_backtest_to_ledger_records(
            CompletedEconomicBacktestLedgerMappingInput(
                result=stale,
                artifacts=artifacts,
                created_by="agent-s3d2b-test",
                review=ReviewMetadata(
                    review_status=ReviewStatus.PENDING,
                    risk_approval_required=True,
                ),
            )
        )


def test_representable_initial_capital_spellings_are_one_canonical_authority(
    tmp_path: Path,
) -> None:
    capital_values = (
        Decimal("100000"),
        Decimal("100000.0"),
        Decimal("100000.000000"),
    )
    configs = tuple(resolved_config(initial_capital=value) for value in capital_values)
    assert {config.initial_capital for config in configs} == {Decimal("100000.000000")}

    qqq = qqq_bundle_files()
    results = tuple(
        run_snapshot_v2_buy_and_hold_backtest(
            asset_files=qqq,
            benchmark_files=spy_bundle_files(),
            research_profile=compatible_profile(qqq),
            resolved_config=config,
            execution_metadata=execution_metadata(),
        )
        for config in configs
    )
    assert len({result.run_id for result in results}) == 1
    assert len({result.daily_records for result in results}) == 1
    assert len({result.metrics for result in results}) == 1

    bundles = tuple(
        generate_economic_artifact_bundle(
            result=result,
            artifact_base_dir=tmp_path / f"capital-{index}",
        )
        for index, result in enumerate(results)
    )
    payload_hash_sets = tuple(
        tuple((item.filename, item.content_hash) for item in bundle.payload_artifacts)
        for bundle in bundles
    )
    assert len(set(payload_hash_sets)) == 1


def test_nonrepresentable_initial_capital_fails_config_validation() -> None:
    with pytest.raises(ValueError, match="six-decimal"):
        resolved_config(initial_capital=Decimal("100000.0000004"))

    with pytest.raises(TypeError, match="Decimal values"):
        ResolvedEconomicBacktestConfig(
            **{
                **resolved_config().model_dump(mode="python"),
                "initial_capital": 100000.0,
            }
        )


def completed_result_with_horizon_receivables() -> CompletedEconomicBacktestResult:
    last = DEFAULT_SESSIONS[-1]
    qqq_event = cash_distribution_v2(
        event_id="qqq-validation-horizon-distribution",
        instrument_id=QQQ_INSTRUMENT_ID,
        ex_date=last,
        record_date=last,
        payable_date=last,
        amount=Decimal("0.5"),
    )
    spy_event = cash_distribution_v2(
        event_id="spy-validation-horizon-distribution",
        instrument_id=SPY_INSTRUMENT_ID,
        source_event_reference="synthetic-v2/actions/spy-validation-horizon",
        ex_date=last,
        record_date=last,
        payable_date=last,
        amount=Decimal("0.5"),
    )
    qqq = qqq_bundle_files(events=(qqq_event,))
    return run_snapshot_v2_buy_and_hold_backtest(
        asset_files=qqq,
        benchmark_files=spy_bundle_files(events=(spy_event,)),
        research_profile=compatible_profile(qqq),
        resolved_config=resolved_config(),
        execution_metadata=execution_metadata(),
    )


def stale_result(
    result: CompletedEconomicBacktestResult,
    mutation: str,
) -> CompletedEconomicBacktestResult:
    if mutation in {
        "total_return",
        "benchmark_total_return",
        "excess_return",
        "observation_count",
        "maximum_drawdown",
    }:
        value: object = Decimal("0")
        if mutation == "observation_count":
            value = 999
        elif mutation == "maximum_drawdown":
            value = Decimal("-0.5")
        return result.model_copy(
            update={"metrics": result.metrics.model_copy(update={mutation: value})}
        )
    if mutation == "drawdown_series":
        changed = result.drawdown_series[0].model_copy(
            update={"drawdown": Decimal("-0.5")}
        )
        return result.model_copy(
            update={"drawdown_series": (changed, *result.drawdown_series[1:])}
        )
    if mutation == "monthly_returns":
        changed = result.monthly_returns[0].model_copy(
            update={"return_value": Decimal("0")}
        )
        return result.model_copy(
            update={"monthly_returns": (changed, *result.monthly_returns[1:])}
        )
    if mutation == "ending_total_book_cost":
        state = result.ending_strategy_state.model_copy(
            update={"total_book_cost": Decimal("1")}
        )
        return result.model_copy(update={"ending_strategy_state": state})
    if mutation == "ending_strategy_receivables":
        state = result.ending_strategy_state.model_copy(update={"receivables": ()})
        return result.model_copy(update={"ending_strategy_state": state})
    if mutation == "ending_benchmark_receivables":
        state = result.ending_benchmark_state.model_copy(update={"receivables": ()})
        return result.model_copy(update={"ending_benchmark_state": state})
    if mutation in {"first_trade_quantity", "first_trade_commission"}:
        field = mutation.removeprefix("first_trade_")
        value = result.trade_records[0].quantity + 1
        if field == "commission":
            value = result.trade_records[0].commission + Decimal("1")
        trade = result.trade_records[0].model_copy(update={field: value})
        return result.model_copy(update={"trade_records": (trade,)})
    if mutation in {"first_daily_cash", "first_daily_book_cost"}:
        field = (
            "strategy_cash"
            if mutation == "first_daily_cash"
            else "strategy_total_book_cost"
        )
        value = getattr(result.daily_records[0], field) + Decimal("1")
        daily = result.daily_records[0].model_copy(update={field: value})
        return result.model_copy(
            update={"daily_records": (daily, *result.daily_records[1:])}
        )
    application = next(
        row
        for row in result.corporate_action_audit
        if row.accounting_action == "cash_distribution_entitlement"
    )
    if mutation == "missing_action_application":
        return result.model_copy(
            update={
                "corporate_action_audit": tuple(
                    row for row in result.corporate_action_audit if row != application
                )
            }
        )
    if mutation == "duplicate_action_application":
        return result.model_copy(
            update={
                "corporate_action_audit": (
                    *result.corporate_action_audit,
                    application,
                )
            }
        )
    raise AssertionError(f"unknown stale-result mutation: {mutation}")
