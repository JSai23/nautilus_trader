"""Tier 2 integration tests: run_backtest pipeline.

Covers TEST_PLAN.md Section 4.6:
- run_backtest end-to-end with monkeypatched data
- status.json lifecycle (running → completed)
- run_backtest failure writes error
"""

import json

import pytest

from runner.engine import ExperimentConfig, run_backtest
from tests.helpers import TEST_HOUR, FIXTURES_DIR, local_data_generator


def _make_config():
    """Build a minimal ExperimentConfig for backtest tests."""
    return ExperimentConfig(
        mode="backtest",
        strategy_path="experiments.strategies.tick_always:TickAlways",
        strategy_params={
            "trade_size": 1.0,
            "buy_after_ticks": 3,
            "sell_after_ticks": 10,
        },
        data_hours=[TEST_HOUR],
        fees="zero",
        starting_balance=10_000.0,
    )


class TestRunBacktest:
    @pytest.mark.timeout(60)
    def test_run_backtest_end_to_end(self, bundled_parquet_path, bundled_market_infos, tmp_path, monkeypatch):
        """run_backtest produces success result with artifacts."""
        config = _make_config()

        # Monkeypatch pmxt_data_generator to use bundled parquet
        def local_gen(market_ids, hours, instruments, instrument_ids, **kwargs):
            yield from local_data_generator(bundled_parquet_path, market_ids, instruments, instrument_ids)

        monkeypatch.setattr("runner.engine.pmxt_data_generator", local_gen)

        result = run_backtest(config, bundled_market_infos, results_dir=tmp_path)

        assert result.success is True
        assert result.tearsheet.num_trades > 0
        assert len(result.run_id) == 8
        assert (tmp_path / "tearsheet.json").exists()
        assert (tmp_path / "status.json").exists()

    @pytest.mark.timeout(60)
    def test_status_json_completed(self, bundled_parquet_path, bundled_market_infos, tmp_path, monkeypatch):
        """Final status.json has status=completed with metrics."""
        config = _make_config()

        def local_gen(market_ids, hours, instruments, instrument_ids, **kwargs):
            yield from local_data_generator(bundled_parquet_path, market_ids, instruments, instrument_ids)

        monkeypatch.setattr("runner.engine.pmxt_data_generator", local_gen)

        result = run_backtest(config, bundled_market_infos, results_dir=tmp_path)

        with open(tmp_path / "status.json") as f:
            status = json.load(f)

        assert status["status"] == "completed"
        assert "total_pnl" in status
        assert status["elapsed_seconds"] > 0

    @pytest.mark.timeout(30)
    def test_run_backtest_failure_writes_error(self, bundled_market_infos, tmp_path):
        """Invalid strategy path causes failure with error.json."""
        config = ExperimentConfig(
            mode="backtest",
            strategy_path="nonexistent.module:FakeStrategy",
            data_hours=[TEST_HOUR],
        )

        result = run_backtest(config, bundled_market_infos, results_dir=tmp_path)

        assert result.success is False
        assert result.error is not None
        assert (tmp_path / "error.json").exists()
        assert (tmp_path / "status.json").exists()

        with open(tmp_path / "status.json") as f:
            status = json.load(f)
        assert status["status"] == "failed"
