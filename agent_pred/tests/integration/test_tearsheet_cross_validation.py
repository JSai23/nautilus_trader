"""Tier 2 integration tests: tearsheet cross-validation.

Covers TEST_PLAN.md Section 14:
- Independent PnL computation from fill_records (FIFO deque)
- Fill records match fills_df
- Cross-validation between tearsheet PnL and independent computation
"""

import collections

import pytest

from runner.engine import ExperimentConfig, run_backtest
from tests.helpers import TEST_HOUR, local_data_generator


def _fifo_pnl_from_fill_records(fill_records):
    """Compute PnL from fill_records using a FIFO deque approach.

    Independent reimplementation — different algorithm and data source
    than tearsheet's _compute_round_trip_pnls which uses fills_df.
    """
    # Group by instrument
    by_instrument = collections.defaultdict(list)
    for record in sorted(fill_records, key=lambda r: int(r["timestamp"])):
        by_instrument[record["instrument_id"]].append(record)

    total_pnl = 0.0
    round_trips = 0

    for iid, records in by_instrument.items():
        pending_buys = collections.deque()
        for rec in records:
            if rec["side"] == "BUY":
                pending_buys.append(rec)
            elif rec["side"] == "SELL" and pending_buys:
                buy = pending_buys.popleft()
                pnl = (rec["price"] - buy["price"]) * rec["qty"]
                total_pnl += pnl
                round_trips += 1

    return total_pnl, round_trips


def _run_strategy(strategy_path, strategy_params, bundled_parquet_path,
                  bundled_market_infos, tmp_path, monkeypatch):
    """Run a strategy through run_backtest with monkeypatched data."""
    config = ExperimentConfig(
        mode="backtest",
        strategy_path=strategy_path,
        strategy_params=strategy_params,
        data_hours=[TEST_HOUR],
    )

    def local_gen(market_ids, hours, instruments, instrument_ids, **kwargs):
        yield from local_data_generator(
            bundled_parquet_path, market_ids, instruments, instrument_ids,
        )

    monkeypatch.setattr("runner.engine.pmxt_data_generator", local_gen)
    return run_backtest(config, bundled_market_infos, results_dir=tmp_path)


class TestCrossValidation:
    @pytest.mark.timeout(60)
    def test_tick_always_fifo_pnl_matches_tearsheet(
        self, bundled_parquet_path, bundled_market_infos, tmp_path, monkeypatch,
    ):
        """FIFO PnL from fill_records matches tearsheet total_pnl."""
        result = _run_strategy(
            "experiments.strategies.tick_always:TickAlways",
            {"trade_size": 1.0, "buy_after_ticks": 3, "sell_after_ticks": 10},
            bundled_parquet_path, bundled_market_infos, tmp_path, monkeypatch,
        )

        strategy = result.strategy
        fifo_pnl, fifo_rt = _fifo_pnl_from_fill_records(strategy._fill_records)

        # PnL should match within floating point tolerance
        assert abs(fifo_pnl - result.tearsheet.total_pnl) < 0.01, (
            f"FIFO PnL ({fifo_pnl:.4f}) != tearsheet PnL ({result.tearsheet.total_pnl:.4f})"
        )

        # Round trip count should match
        assert fifo_rt == result.tearsheet.num_round_trips, (
            f"FIFO round trips ({fifo_rt}) != "
            f"tearsheet ({result.tearsheet.num_round_trips})"
        )

    @pytest.mark.timeout(60)
    def test_timer_always_fifo_pnl_matches_tearsheet(
        self, bundled_parquet_path, bundled_market_infos, tmp_path, monkeypatch,
    ):
        """FIFO PnL cross-validation for TimerAlways."""
        result = _run_strategy(
            "experiments.strategies.timer_always:TimerAlways",
            {"trade_size": 1.0, "check_interval_minutes": 1, "hold_periods": 4},
            bundled_parquet_path, bundled_market_infos, tmp_path, monkeypatch,
        )

        strategy = result.strategy
        if strategy._orders_filled == 0:
            pytest.skip("No fills — cannot cross-validate")

        fifo_pnl, fifo_rt = _fifo_pnl_from_fill_records(strategy._fill_records)

        assert abs(fifo_pnl - result.tearsheet.total_pnl) < 0.01, (
            f"FIFO PnL ({fifo_pnl:.4f}) != tearsheet ({result.tearsheet.total_pnl:.4f})"
        )

    @pytest.mark.timeout(60)
    def test_fill_records_match_fills_df(
        self, bundled_parquet_path, bundled_market_infos, tmp_path, monkeypatch,
    ):
        """Strategy _fill_records count matches fills_df from ReportProvider."""
        result = _run_strategy(
            "experiments.strategies.tick_always:TickAlways",
            {"trade_size": 1.0, "buy_after_ticks": 3, "sell_after_ticks": 10},
            bundled_parquet_path, bundled_market_infos, tmp_path, monkeypatch,
        )

        strategy = result.strategy

        # Count match
        assert len(strategy._fill_records) == len(result.fills_df), (
            f"fill_records ({len(strategy._fill_records)}) != "
            f"fills_df ({len(result.fills_df)})"
        )

        # BUY/SELL counts match
        fr_buys = sum(1 for r in strategy._fill_records if r["side"] == "BUY")
        fr_sells = sum(1 for r in strategy._fill_records if r["side"] == "SELL")
        df_buys = len(result.fills_df[result.fills_df["order_side"] == "BUY"])
        df_sells = len(result.fills_df[result.fills_df["order_side"] == "SELL"])

        assert fr_buys == df_buys, f"BUY count mismatch: {fr_buys} vs {df_buys}"
        assert fr_sells == df_sells, f"SELL count mismatch: {fr_sells} vs {df_sells}"
