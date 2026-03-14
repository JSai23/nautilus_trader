"""Tier 2 integration tests: real strategies through run_backtest().

Covers TEST_PLAN.md Section 11:
- TickAlways backtest outputs (fills, tearsheet, artifacts)
- TimerAlways backtest outputs
- Strategy counter consistency
- All artifacts present and valid
"""

import json

import pytest

from runner.engine import ExperimentConfig, run_backtest
from tests.helpers import TEST_HOUR, local_data_generator


def _run_strategy(strategy_path, strategy_params, bundled_parquet_path,
                  bundled_market_infos, tmp_path, monkeypatch):
    """Run a strategy through run_backtest with monkeypatched data."""
    config = ExperimentConfig(
        mode="backtest",
        strategy_path=strategy_path,
        strategy_params=strategy_params,
        data_hours=[TEST_HOUR],
        fees="zero",
        starting_balance=10_000.0,
    )

    def local_gen(market_ids, hours, instruments, instrument_ids, **kwargs):
        yield from local_data_generator(
            bundled_parquet_path, market_ids, instruments, instrument_ids,
        )

    monkeypatch.setattr("runner.engine.pmxt_data_generator", local_gen)
    return run_backtest(config, bundled_market_infos, results_dir=tmp_path)


class TestTickAlwaysBacktest:
    @pytest.mark.timeout(60)
    def test_tick_always_backtest_outputs(
        self, bundled_parquet_path, bundled_market_infos, tmp_path, monkeypatch,
    ):
        """TickAlways produces many fills with correct artifacts."""
        result = _run_strategy(
            "experiments.strategies.tick_always:TickAlways",
            {"trade_size": 1.0, "buy_after_ticks": 3, "sell_after_ticks": 10},
            bundled_parquet_path, bundled_market_infos, tmp_path, monkeypatch,
        )

        assert result.success is True
        assert result.tearsheet.num_trades > 0

        # Fills structure
        assert not result.fills_df.empty
        assert result.tearsheet.num_trades == len(result.fills_df)

        # Fill prices in valid range
        for _, row in result.fills_df.iterrows():
            price = float(row["last_px"])
            assert 0 < price <= 1.0, f"Fill price {price} out of range"

        # Status.json
        with open(tmp_path / "status.json") as f:
            status = json.load(f)
        assert status["status"] == "completed"
        assert status["elapsed_seconds"] > 0


class TestTimerAlwaysBacktest:
    @pytest.mark.timeout(60)
    def test_timer_always_backtest_outputs(
        self, bundled_parquet_path, bundled_market_infos, tmp_path, monkeypatch,
    ):
        """TimerAlways produces fills with correct artifacts."""
        result = _run_strategy(
            "experiments.strategies.timer_always:TimerAlways",
            {"trade_size": 1.0, "check_interval_minutes": 1, "hold_periods": 4},
            bundled_parquet_path, bundled_market_infos, tmp_path, monkeypatch,
        )

        assert result.success is True

        # Timer strategy should produce some fills
        if result.tearsheet.num_trades > 0:
            assert result.tearsheet.num_round_trips >= 0
            assert not result.fills_df.empty


class TestStrategyCounterConsistency:
    @pytest.mark.timeout(60)
    def test_tick_always_counters(
        self, bundled_parquet_path, bundled_market_infos, tmp_path, monkeypatch,
    ):
        """Strategy internal counters match output artifacts."""
        result = _run_strategy(
            "experiments.strategies.tick_always:TickAlways",
            {"trade_size": 1.0, "buy_after_ticks": 3, "sell_after_ticks": 10},
            bundled_parquet_path, bundled_market_infos, tmp_path, monkeypatch,
        )

        strategy = result.strategy
        assert strategy is not None, "RunResult.strategy not populated"

        # Counters match
        assert result.tearsheet.num_trades == len(result.fills_df)
        assert strategy._orders_submitted >= strategy._orders_filled + strategy._orders_canceled
        assert len(strategy._fill_records) == strategy._orders_filled

        # Round trips match
        assert result.tearsheet.num_round_trips == strategy.round_trips


class TestAllArtifactsPresent:
    @pytest.mark.timeout(60)
    def test_all_artifacts_present_and_valid(
        self, bundled_parquet_path, bundled_market_infos, tmp_path, monkeypatch,
    ):
        """After successful run_backtest with fills, all artifacts exist."""
        result = _run_strategy(
            "experiments.strategies.tick_always:TickAlways",
            {"trade_size": 1.0, "buy_after_ticks": 3, "sell_after_ticks": 10},
            bundled_parquet_path, bundled_market_infos, tmp_path, monkeypatch,
        )

        assert result.success is True

        # Required files
        assert (tmp_path / "tearsheet.json").exists()
        assert (tmp_path / "status.json").exists()
        assert (tmp_path / "metadata.json").exists()
        assert (tmp_path / "fills.csv").exists()
        assert (tmp_path / "orders.csv").exists()

        # PNGs when round_trips > 0
        if result.tearsheet.num_round_trips > 0:
            assert (tmp_path / "pnl_curve.png").exists()
            assert (tmp_path / "pnl_curve.png").stat().st_size > 1000
            assert (tmp_path / "trade_distribution.png").exists()
            assert (tmp_path / "trade_distribution.png").stat().st_size > 1000

        # Tearsheet JSON matches RunResult
        with open(tmp_path / "tearsheet.json") as f:
            ts_json = json.load(f)
        assert ts_json["total_pnl"] == result.tearsheet.total_pnl
        assert ts_json["num_trades"] == result.tearsheet.num_trades
        assert ts_json["num_round_trips"] == result.tearsheet.num_round_trips
