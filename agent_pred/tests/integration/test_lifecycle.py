"""Tier 2 integration tests: strategy lifecycle with bundled data.

Covers TEST_PLAN.md Section 4.3:
- Data flows through engine
- Market metadata hydrated
- Timer fires at correct interval
- Tick callbacks receive deltas
- Heartbeat writes status.json
- Top-of-book recording
- Fill records tracking
- Fill prices within spread
- Tearsheet matches engine fills
- Lifecycle state counters
"""

import json
import logging

import pytest

from nautilus_trader.analysis.reporter import ReportProvider

from experiments.strategies.log_only import LogOnlyStrategy, LogOnlyStrategyConfig
from experiments.strategies.tick_always import TickAlways, TickAlwaysConfig
from experiments.strategies.timer_always import TimerAlways, TimerAlwaysConfig
from runner.tearsheet import compute_tearsheet
from tests.helpers import TEST_HOUR, build_test_engine, hour_bounds, hour_bounds_ns

log = logging.getLogger(__name__)


class TestDataFlow:
    @pytest.mark.timeout(60)
    def test_data_flows_through_engine(self, bundled_instruments, bundled_parquet_path):
        """LogOnlyStrategy receives deltas — proves data pipeline works without network."""
        instruments, instrument_ids, market_ids = bundled_instruments
        engine = build_test_engine(instruments, instrument_ids, market_ids, bundled_parquet_path)

        iid_strs = [str(iid) for iid in instrument_ids.values()]
        config = LogOnlyStrategyConfig(instrument_ids=iid_strs)
        strategy = LogOnlyStrategy(config=config)
        engine.add_strategy(strategy)

        start_dt, end_dt = hour_bounds(TEST_HOUR)
        engine.run(start=start_dt, end=end_dt)

        assert strategy.delta_count > 0, "No deltas received — data pipeline broken"
        engine.dispose()


class TestMarketMetadata:
    @pytest.mark.timeout(60)
    def test_market_meta_hydrated(self, bundled_instruments, bundled_parquet_path):
        """Every instrument gets MarketMeta with non-empty fields."""
        instruments, instrument_ids, market_ids = bundled_instruments
        engine = build_test_engine(instruments, instrument_ids, market_ids, bundled_parquet_path)

        start_ns, end_ns = hour_bounds_ns(TEST_HOUR)
        iid_strs = [str(iid) for iid in instrument_ids.values()]
        config = TickAlwaysConfig(
            instrument_ids=iid_strs, trade_size=1.0,
            buy_after_ticks=3, sell_after_ticks=10,
            start_time_ns=start_ns, end_time_ns=end_ns,
        )
        strategy = TickAlways(config=config)
        engine.add_strategy(strategy)

        start_dt, end_dt = hour_bounds(TEST_HOUR)
        engine.run(start=start_dt, end=end_dt)

        assert len(strategy._market_meta) == len(instrument_ids)
        for iid, meta in strategy._market_meta.items():
            assert meta.condition_id, f"Empty condition_id for {iid}"
            assert meta.token_id, f"Empty token_id for {iid}"
            assert meta.outcome, f"Empty outcome for {iid}"
            assert meta.question, f"Empty question for {iid}"
        engine.dispose()


class TestTimerInterval:
    @pytest.mark.timeout(60)
    def test_timer_fires_at_interval(self, bundled_instruments, bundled_parquet_path):
        """TimerAlways with 1-min interval fires ~60 times in 1 hour of data."""
        instruments, instrument_ids, market_ids = bundled_instruments
        engine = build_test_engine(instruments, instrument_ids, market_ids, bundled_parquet_path)

        start_ns, end_ns = hour_bounds_ns(TEST_HOUR)
        iid_strs = [str(iid) for iid in instrument_ids.values()]
        config = TimerAlwaysConfig(
            instrument_ids=iid_strs, trade_size=1.0,
            check_interval_minutes=1, hold_periods=4,
            start_time_ns=start_ns, end_time_ns=end_ns,
        )
        strategy = TimerAlways(config=config)
        engine.add_strategy(strategy)

        start_dt, end_dt = hour_bounds(TEST_HOUR)
        engine.run(start=start_dt, end=end_dt)

        assert strategy._interval_count >= 50, (
            f"Timer only fired {strategy._interval_count} times (expected ≥50)"
        )
        assert strategy._interval_count <= 65
        engine.dispose()


class TestTickCallbacks:
    @pytest.mark.timeout(60)
    def test_tick_callback_receives_all_deltas(self, bundled_instruments, bundled_parquet_path):
        """TickAlways with high tick threshold receives many updates without trading."""
        instruments, instrument_ids, market_ids = bundled_instruments
        engine = build_test_engine(instruments, instrument_ids, market_ids, bundled_parquet_path)

        start_ns, end_ns = hour_bounds_ns(TEST_HOUR)
        iid_strs = [str(iid) for iid in instrument_ids.values()]
        config = TickAlwaysConfig(
            instrument_ids=iid_strs, trade_size=1.0,
            buy_after_ticks=999999, sell_after_ticks=999999,
            start_time_ns=start_ns, end_time_ns=end_ns,
        )
        strategy = TickAlways(config=config)
        engine.add_strategy(strategy)

        start_dt, end_dt = hour_bounds(TEST_HOUR)
        engine.run(start=start_dt, end=end_dt)

        assert strategy._tick_count_total > 100
        assert strategy._orders_filled == 0
        engine.dispose()


class TestHeartbeat:
    @pytest.mark.timeout(60)
    def test_heartbeat_writes_status_json(self, bundled_instruments, bundled_parquet_path, tmp_path):
        """Heartbeat timer writes status.json with correct fields."""
        instruments, instrument_ids, market_ids = bundled_instruments
        engine = build_test_engine(instruments, instrument_ids, market_ids, bundled_parquet_path)

        start_ns, end_ns = hour_bounds_ns(TEST_HOUR)
        iid_strs = [str(iid) for iid in instrument_ids.values()]
        config = TickAlwaysConfig(
            instrument_ids=iid_strs, trade_size=1.0,
            buy_after_ticks=3, sell_after_ticks=10,
            start_time_ns=start_ns, end_time_ns=end_ns,
        )
        strategy = TickAlways(config=config)
        engine.add_strategy(strategy)

        # Inject heartbeat dir AFTER add_strategy but BEFORE run
        strategy._heartbeat_dir = tmp_path
        strategy._heartbeat_run_id = "test123"

        start_dt, end_dt = hour_bounds(TEST_HOUR)
        engine.run(start=start_dt, end=end_dt)

        status_path = tmp_path / "status.json"
        assert status_path.exists(), "status.json not written by heartbeat"

        with open(status_path) as f:
            status = json.load(f)

        assert status["run_id"] == "test123"
        assert status["status"] == "running"
        assert status["strategy"] == "TickAlways"
        assert status["ticks"] > 0
        assert status["instruments"] > 0
        engine.dispose()


class TestTopOfBook:
    @pytest.mark.timeout(60)
    def test_top_of_book_recording(self, bundled_instruments, bundled_parquet_path):
        """Top-of-book recording captures BBO data as a DataFrame."""
        instruments, instrument_ids, market_ids = bundled_instruments
        engine = build_test_engine(instruments, instrument_ids, market_ids, bundled_parquet_path)

        start_ns, end_ns = hour_bounds_ns(TEST_HOUR)
        iid_strs = [str(iid) for iid in instrument_ids.values()]
        config = TickAlwaysConfig(
            instrument_ids=iid_strs, trade_size=1.0,
            buy_after_ticks=999999, sell_after_ticks=999999,
            record_top_of_book=True,
            start_time_ns=start_ns, end_time_ns=end_ns,
        )
        strategy = TickAlways(config=config)
        engine.add_strategy(strategy)

        start_dt, end_dt = hour_bounds(TEST_HOUR)
        engine.run(start=start_dt, end=end_dt)

        df = strategy.get_top_of_book_df()
        assert not df.empty, "Top-of-book DataFrame is empty"
        expected_cols = {"timestamp_ns", "instrument_id", "bid", "ask", "bid_qty", "ask_qty"}
        assert set(df.columns) == expected_cols
        assert (df["bid"] > 0).all()
        assert (df["ask"] > 0).all()
        engine.dispose()


class TestFillRecords:
    @pytest.mark.timeout(60)
    def test_fill_records_tracking(self, bundled_instruments, bundled_parquet_path):
        """In-strategy _fill_records matches _orders_filled count."""
        instruments, instrument_ids, market_ids = bundled_instruments
        engine = build_test_engine(instruments, instrument_ids, market_ids, bundled_parquet_path)

        start_ns, end_ns = hour_bounds_ns(TEST_HOUR)
        iid_strs = [str(iid) for iid in instrument_ids.values()]
        config = TickAlwaysConfig(
            instrument_ids=iid_strs, trade_size=1.0,
            buy_after_ticks=3, sell_after_ticks=10,
            start_time_ns=start_ns, end_time_ns=end_ns,
        )
        strategy = TickAlways(config=config)
        engine.add_strategy(strategy)

        start_dt, end_dt = hour_bounds(TEST_HOUR)
        engine.run(start=start_dt, end=end_dt)

        assert strategy._orders_filled > 0
        assert len(strategy._fill_records) == strategy._orders_filled
        for rec in strategy._fill_records:
            assert rec["side"] in ("BUY", "SELL")
            assert rec["price"] > 0
            assert rec["qty"] > 0
        engine.dispose()


class TestValidation:
    @pytest.mark.timeout(60)
    def test_fill_prices_within_spread(self, bundled_instruments, bundled_parquet_path):
        """All fill prices are in valid prediction market range (0, 1)."""
        instruments, instrument_ids, market_ids = bundled_instruments
        engine = build_test_engine(instruments, instrument_ids, market_ids, bundled_parquet_path)

        start_ns, end_ns = hour_bounds_ns(TEST_HOUR)
        iid_strs = [str(iid) for iid in instrument_ids.values()]
        config = TickAlwaysConfig(
            instrument_ids=iid_strs, trade_size=1.0,
            buy_after_ticks=3, sell_after_ticks=10,
            start_time_ns=start_ns, end_time_ns=end_ns,
        )
        strategy = TickAlways(config=config)
        engine.add_strategy(strategy)

        start_dt, end_dt = hour_bounds(TEST_HOUR)
        engine.run(start=start_dt, end=end_dt)

        for rec in strategy._fill_records:
            assert 0 < rec["price"] <= 1.0, f"Fill price {rec['price']} out of range"
        engine.dispose()

    @pytest.mark.timeout(60)
    def test_lifecycle_state_counters(self, bundled_instruments, bundled_parquet_path):
        """Strategy state fields confirm lifecycle events occurred."""
        instruments, instrument_ids, market_ids = bundled_instruments
        engine = build_test_engine(instruments, instrument_ids, market_ids, bundled_parquet_path)

        start_ns, end_ns = hour_bounds_ns(TEST_HOUR)
        iid_strs = [str(iid) for iid in instrument_ids.values()]
        config = TickAlwaysConfig(
            instrument_ids=iid_strs, trade_size=1.0,
            buy_after_ticks=3, sell_after_ticks=10,
            start_time_ns=start_ns, end_time_ns=end_ns,
        )
        strategy = TickAlways(config=config)
        engine.add_strategy(strategy)

        start_dt, end_dt = hour_bounds(TEST_HOUR)
        engine.run(start=start_dt, end=end_dt)

        assert strategy._orders_filled > 0
        assert strategy._orders_submitted > 0
        assert strategy._tick_count_total > 0
        assert len(strategy._fill_records) == strategy._orders_filled
        engine.dispose()

    @pytest.mark.timeout(60)
    def test_tearsheet_matches_engine_fills(self, bundled_instruments, bundled_parquet_path):
        """Tearsheet computed from fills matches actual fill count."""
        instruments, instrument_ids, market_ids = bundled_instruments
        engine = build_test_engine(instruments, instrument_ids, market_ids, bundled_parquet_path)

        start_ns, end_ns = hour_bounds_ns(TEST_HOUR)
        iid_strs = [str(iid) for iid in instrument_ids.values()]
        config = TickAlwaysConfig(
            instrument_ids=iid_strs, trade_size=1.0,
            buy_after_ticks=3, sell_after_ticks=10,
            start_time_ns=start_ns, end_time_ns=end_ns,
        )
        strategy = TickAlways(config=config)
        engine.add_strategy(strategy)

        start_dt, end_dt = hour_bounds(TEST_HOUR)
        engine.run(start=start_dt, end=end_dt)

        orders = engine.cache.orders()
        fills_df = ReportProvider.generate_fills_report(orders)
        closed = [p for p in engine.cache.positions() if p.is_closed]
        positions_df = (
            ReportProvider.generate_positions_report(closed)
            if closed
            else ReportProvider.generate_positions_report(engine.cache.positions())
        )

        tearsheet = compute_tearsheet(positions_df, fills_df)
        assert tearsheet.num_trades > 0
        assert tearsheet.num_trades == len(fills_df)
        assert tearsheet.num_round_trips > 0
        engine.dispose()
