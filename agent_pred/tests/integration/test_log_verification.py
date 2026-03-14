"""Tier 2 integration tests: log verification via _log_buffer.

Covers TEST_PLAN.md Section 12:
- _log_buffer captures START, FILL, EXIT, INTERVAL events
- Fill events match _fill_records
- Heartbeat events present when heartbeat configured
- Interval events match _interval_count
"""

import pytest

from runner.engine import ExperimentConfig, run_backtest
from tests.helpers import TEST_HOUR, local_data_generator


def _run_tick_always(bundled_parquet_path, bundled_market_infos, tmp_path, monkeypatch):
    """Run TickAlways through run_backtest."""
    config = ExperimentConfig(
        mode="backtest",
        strategy_path="experiments.strategies.tick_always:TickAlways",
        strategy_params={"trade_size": 1.0, "buy_after_ticks": 3, "sell_after_ticks": 10},
        data_hours=[TEST_HOUR],
    )

    def local_gen(market_ids, hours, instruments, instrument_ids, **kwargs):
        yield from local_data_generator(
            bundled_parquet_path, market_ids, instruments, instrument_ids,
        )

    monkeypatch.setattr("runner.engine.pmxt_data_generator", local_gen)
    return run_backtest(config, bundled_market_infos, results_dir=tmp_path)


class TestLogBuffer:
    @pytest.mark.timeout(60)
    def test_log_buffer_captures_start_event(
        self, bundled_parquet_path, bundled_market_infos, tmp_path, monkeypatch,
    ):
        """_log_buffer captures START event from on_start."""
        result = _run_tick_always(
            bundled_parquet_path, bundled_market_infos, tmp_path, monkeypatch,
        )

        strategy = result.strategy
        events = strategy._log_buffer

        start_events = [e for e in events if e["type"] == "START"]
        assert len(start_events) == 1, f"Expected 1 START event, got {len(start_events)}"
        assert start_events[0]["instruments"] > 0

    @pytest.mark.timeout(60)
    def test_log_buffer_captures_fill_events(
        self, bundled_parquet_path, bundled_market_infos, tmp_path, monkeypatch,
    ):
        """FILL events in _log_buffer match _fill_records count."""
        result = _run_tick_always(
            bundled_parquet_path, bundled_market_infos, tmp_path, monkeypatch,
        )

        strategy = result.strategy
        events = strategy._log_buffer

        fill_events = [e for e in events if e["type"] == "FILL"]
        assert len(fill_events) == len(strategy._fill_records), (
            f"FILL events ({len(fill_events)}) != "
            f"fill_records ({len(strategy._fill_records)})"
        )

        # Each fill event has required fields
        for fe in fill_events:
            assert "instrument_id" in fe
            assert "side" in fe
            assert fe["side"] in ("BUY", "SELL")
            assert "price" in fe
            assert fe["price"] > 0

    @pytest.mark.timeout(60)
    def test_log_buffer_captures_interval_events(
        self, bundled_parquet_path, bundled_market_infos, tmp_path, monkeypatch,
    ):
        """INTERVAL events match _interval_count for timer-based strategy."""
        config = ExperimentConfig(
            mode="backtest",
            strategy_path="experiments.strategies.timer_always:TimerAlways",
            strategy_params={
                "trade_size": 1.0,
                "check_interval_minutes": 1,
                "hold_periods": 4,
            },
            data_hours=[TEST_HOUR],
        )

        def local_gen(market_ids, hours, instruments, instrument_ids, **kwargs):
            yield from local_data_generator(
                bundled_parquet_path, market_ids, instruments, instrument_ids,
            )

        monkeypatch.setattr("runner.engine.pmxt_data_generator", local_gen)
        result = run_backtest(config, bundled_market_infos, results_dir=tmp_path)

        strategy = result.strategy
        events = strategy._log_buffer

        interval_events = [e for e in events if e["type"] == "INTERVAL"]
        assert len(interval_events) == strategy._interval_count, (
            f"INTERVAL events ({len(interval_events)}) != "
            f"_interval_count ({strategy._interval_count})"
        )

    @pytest.mark.timeout(60)
    def test_log_buffer_event_ordering(
        self, bundled_parquet_path, bundled_market_infos, tmp_path, monkeypatch,
    ):
        """Events in _log_buffer have monotonically non-decreasing timestamps."""
        result = _run_tick_always(
            bundled_parquet_path, bundled_market_infos, tmp_path, monkeypatch,
        )

        strategy = result.strategy
        events = strategy._log_buffer

        assert len(events) > 0, "No events captured"

        timestamps = [e["ts"] for e in events]
        for i in range(1, len(timestamps)):
            assert timestamps[i] >= timestamps[i - 1], (
                f"Events out of order at index {i}: "
                f"{timestamps[i-1]} > {timestamps[i]}"
            )
