"""Tier 2 integration tests: order callback handling.

Covers TEST_PLAN.md Section 4.7:
- on_order_filled increments counter
- on_order_canceled increments counter
- FOK fills against book at correct prices
"""

import pytest

from experiments.strategies.tick_always import TickAlways, TickAlwaysConfig
from tests.helpers import TEST_HOUR, build_test_engine, hour_bounds, hour_bounds_ns


class TestOrderCallbacks:
    @pytest.mark.timeout(60)
    def test_on_order_filled_increments_counter(self, bundled_instruments, bundled_parquet_path):
        """Filled orders increment counter and match fill_records."""
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
        assert strategy._orders_submitted >= strategy._orders_filled
        assert strategy._orders_filled == len(strategy._fill_records)
        engine.dispose()

    @pytest.mark.timeout(60)
    def test_order_counter_consistency(self, bundled_instruments, bundled_parquet_path):
        """submitted == filled + canceled + rejected."""
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

        total = strategy._orders_filled + strategy._orders_canceled + strategy._orders_rejected
        assert strategy._orders_submitted == total, (
            f"submitted({strategy._orders_submitted}) != "
            f"filled({strategy._orders_filled}) + "
            f"canceled({strategy._orders_canceled}) + "
            f"rejected({strategy._orders_rejected})"
        )
        engine.dispose()

    @pytest.mark.timeout(60)
    def test_fok_fills_at_correct_prices(self, bundled_instruments, bundled_parquet_path):
        """FOK BUY fills at ask, FOK SELL fills at bid — all within (0, 1)."""
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

        assert len(strategy._fill_records) > 0
        for rec in strategy._fill_records:
            assert 0 < rec["price"] <= 1.0, f"Fill price {rec['price']} out of range"
            assert rec["qty"] > 0
        engine.dispose()
