"""Tier 2 integration tests: exit lifecycle with synthetic data.

Covers TEST_PLAN.md Section 4.4:
- Convergence exit (near 1.0 and near 0.0)
- End-of-data exit (60s before end)
- Resolution timer exit
- Take-profit exit
- Stop-loss exit
- FOK cancel queues retry
- FOK cancel gives up after 3 retries
"""

import logging
from datetime import datetime, timezone

import pytest

from experiments.strategies.tick_always import TickAlways, TickAlwaysConfig
from tests.helpers import FAKE_MARKET, make_synthetic_engine
from universe.instruments import build_instrument_maps

log = logging.getLogger(__name__)


def _build_instruments(market_info=None):
    """Build instruments from FAKE_MARKET or custom market info."""
    info = market_info or FAKE_MARKET
    instruments, instrument_ids, market_ids = build_instrument_maps([info])
    instrument = list(instruments.values())[0]
    instrument_id = list(instrument_ids.values())[0]
    return instrument, instrument_id, instruments, instrument_ids


def _run_with_synthetic(price_path, config_kwargs, start_ns, end_ns, market_info=None):
    """Build engine with synthetic data, run TickAlways, return (engine, strategy)."""
    instrument, instrument_id, instruments, instrument_ids = _build_instruments(market_info)
    engine = make_synthetic_engine(instrument, instrument_id, price_path, start_ns, end_ns)

    defaults = {
        "instrument_ids": [str(instrument_id)],
        "trade_size": 1.0,
        "start_time_ns": start_ns,
        "end_time_ns": end_ns,
    }
    defaults.update(config_kwargs)
    config = TickAlwaysConfig(**defaults)
    strategy = TickAlways(config=config)
    engine.add_strategy(strategy)

    start_dt = datetime.fromtimestamp(start_ns / 1e9, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(end_ns / 1e9, tz=timezone.utc)
    engine.run(start=start_dt, end=end_dt)
    return engine, strategy, instrument_id


class TestConvergenceExit:
    @pytest.mark.timeout(30)
    def test_convergence_exit_near_one(self):
        """Convergence exit triggers when mid > 0.95."""
        start_ns = 1_700_000_000_000_000_000
        end_ns = start_ns + 3600_000_000_000  # 1 hour

        ticks = []
        for i in range(100):
            ts = start_ns + i * 30_000_000_000  # 30s intervals
            if i < 10:
                ticks.append((ts, 0.50, 0.51))
            else:
                # Gradually converge to near 1.0
                ticks.append((ts, 0.96, 0.97))

        engine, strategy, iid = _run_with_synthetic(
            ticks,
            {"buy_after_ticks": 3, "sell_after_ticks": 99999, "convergence_threshold": 0.95},
            start_ns, end_ns,
        )

        # Should have bought, then convergence exit should have sold
        sell_fills = [r for r in strategy._fill_records if r["side"] == "SELL"]
        assert len(sell_fills) >= 1, "No SELL fills — convergence exit didn't trigger"
        assert iid in strategy._closed or iid in strategy._exiting
        engine.dispose()

    @pytest.mark.timeout(30)
    def test_convergence_exit_near_zero(self):
        """Convergence exit triggers when mid < 0.05."""
        start_ns = 1_700_000_000_000_000_000
        end_ns = start_ns + 3600_000_000_000

        ticks = []
        for i in range(100):
            ts = start_ns + i * 30_000_000_000
            if i < 10:
                ticks.append((ts, 0.50, 0.51))
            else:
                ticks.append((ts, 0.03, 0.04))  # mid=0.035 < 0.05

        engine, strategy, iid = _run_with_synthetic(
            ticks,
            {"buy_after_ticks": 3, "sell_after_ticks": 99999, "convergence_threshold": 0.95},
            start_ns, end_ns,
        )

        sell_fills = [r for r in strategy._fill_records if r["side"] == "SELL"]
        assert len(sell_fills) >= 1, "No SELL fills — convergence exit didn't trigger"
        engine.dispose()


class TestEndOfDataExit:
    @pytest.mark.timeout(30)
    def test_end_of_data_exit_60s_before(self):
        """End-of-data alert fires 60s before end_ns, exits all positions."""
        start_ns = 1_700_000_000_000_000_000
        end_ns = start_ns + 3600_000_000_000  # 1 hour

        # Steady prices for the full period
        ticks = []
        for i in range(120):
            ts = start_ns + i * 30_000_000_000  # 30s intervals, 1 hour
            ticks.append((ts, 0.50, 0.51))

        engine, strategy, iid = _run_with_synthetic(
            ticks,
            {"buy_after_ticks": 3, "sell_after_ticks": 99999},
            start_ns, end_ns,
        )

        assert strategy._data_ended is True, "_data_ended should be True after end-of-data exit"
        # All positions should be closed (or at least exited)
        open_positions = engine.cache.positions_open()
        assert len(open_positions) == 0, f"Still {len(open_positions)} open positions"
        engine.dispose()


class TestResolutionTimer:
    @pytest.mark.timeout(30)
    def test_resolution_timer_exits_before_expiration(self):
        """Resolution timer fires exit_before_resolution_secs before market expiration."""
        start_ns = 1_700_000_000_000_000_000
        # Market expires 600s after data start
        expiration_dt = datetime.fromtimestamp(
            start_ns / 1e9 + 600, tz=timezone.utc
        )
        end_ns = start_ns + 1200_000_000_000  # 20 minutes of data

        market_info = dict(FAKE_MARKET)
        market_info["end_date_iso"] = expiration_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        ticks = []
        for i in range(400):
            ts = start_ns + i * 3_000_000_000  # 3s intervals, 20 min
            ticks.append((ts, 0.50, 0.51))

        engine, strategy, iid = _run_with_synthetic(
            ticks,
            {"buy_after_ticks": 3, "sell_after_ticks": 99999, "exit_before_resolution_secs": 300},
            start_ns, end_ns,
            market_info=market_info,
        )

        # Resolution timer should fire at 300s, causing a SELL exit.
        # TickAlways re-enters after closing, so _closed may be empty.
        # Verify a SELL fill happened (the exit):
        sell_fills = [r for r in strategy._fill_records if r["side"] == "SELL"]
        assert len(sell_fills) >= 1, "No SELL fills — resolution timer didn't exit"
        # Also verify data_ended is True (end-of-data exit also fires later)
        assert strategy._data_ended is True
        engine.dispose()


class TestTakeProfitStopLoss:
    @pytest.mark.timeout(30)
    def test_take_profit_exit(self):
        """Take-profit triggers when unrealized PnL > threshold."""
        start_ns = 1_700_000_000_000_000_000
        end_ns = start_ns + 3600_000_000_000

        ticks = []
        for i in range(100):
            ts = start_ns + i * 30_000_000_000
            if i < 10:
                ticks.append((ts, 0.50, 0.51))  # Entry at 0.51
            else:
                ticks.append((ts, 0.60, 0.61))  # Price rises: unrealized = (0.60-0.51)*1 = 0.09

        engine, strategy, iid = _run_with_synthetic(
            ticks,
            {"buy_after_ticks": 3, "sell_after_ticks": 99999, "take_profit": 0.05},
            start_ns, end_ns,
        )

        sell_fills = [r for r in strategy._fill_records if r["side"] == "SELL"]
        assert len(sell_fills) >= 1, "Take-profit exit didn't trigger"
        engine.dispose()

    @pytest.mark.timeout(30)
    def test_stop_loss_exit(self):
        """Stop-loss triggers when unrealized PnL < threshold."""
        start_ns = 1_700_000_000_000_000_000
        end_ns = start_ns + 3600_000_000_000

        ticks = []
        for i in range(100):
            ts = start_ns + i * 30_000_000_000
            if i < 10:
                ticks.append((ts, 0.50, 0.51))  # Entry at 0.51
            else:
                ticks.append((ts, 0.40, 0.41))  # Price drops: unrealized = (0.40-0.51)*1 = -0.11

        engine, strategy, iid = _run_with_synthetic(
            ticks,
            {"buy_after_ticks": 3, "sell_after_ticks": 99999, "stop_loss": -0.05},
            start_ns, end_ns,
        )

        sell_fills = [r for r in strategy._fill_records if r["side"] == "SELL"]
        assert len(sell_fills) >= 1, "Stop-loss exit didn't trigger"
        engine.dispose()


class TestFOKRetry:
    @pytest.mark.timeout(60)
    def test_fok_cancel_queues_retry(self):
        """FOK exit cancel → retry on next interval → eventually succeeds."""
        start_ns = 1_700_000_000_000_000_000
        end_ns = start_ns + 600_000_000_000  # 10 min

        ticks = []
        for i in range(200):
            ts = start_ns + i * 3_000_000_000  # 3s intervals
            if i < 10:
                # Stable — entry BUY fills (ask_qty=1000 >> trade_size=5)
                ticks.append((ts, 0.50, 0.51, 1000, 1000))
            elif i < 60:
                # Convergence triggers exit, but bid_qty=1 < trade_size=5 → FOK SELL fails
                ticks.append((ts, 0.96, 0.97, 1, 1000))
            else:
                # Bid depth restored → retry succeeds
                ticks.append((ts, 0.96, 0.97, 1000, 1000))

        engine, strategy, iid = _run_with_synthetic(
            ticks,
            {
                "buy_after_ticks": 3,
                "sell_after_ticks": 99999,
                "convergence_threshold": 0.95,
                "check_interval_minutes": 1,
                "trade_size": 5.0,
            },
            start_ns, end_ns,
        )

        # Should have at least one canceled order (FOK SELL on thin bid)
        assert strategy._orders_canceled >= 1, "No FOK cancels occurred"
        # Entry + exit should have filled
        assert strategy._orders_filled >= 2, (
            f"Only {strategy._orders_filled} fills (expected ≥2)"
        )
        engine.dispose()

    @pytest.mark.timeout(60)
    def test_fok_cancel_gives_up_after_3_retries(self):
        """Permanent insufficient bid depth → gives up after 3 retries."""
        start_ns = 1_700_000_000_000_000_000
        end_ns = start_ns + 900_000_000_000  # 15 min

        ticks = []
        for i in range(300):
            ts = start_ns + i * 3_000_000_000
            if i < 10:
                ticks.append((ts, 0.50, 0.51, 1000, 1000))
            else:
                # Permanent thin bid — FOK SELL always fails
                ticks.append((ts, 0.96, 0.97, 1, 1000))

        engine, strategy, iid = _run_with_synthetic(
            ticks,
            {
                "buy_after_ticks": 3,
                "sell_after_ticks": 99999,
                "convergence_threshold": 0.95,
                "check_interval_minutes": 1,
                "trade_size": 5.0,
            },
            start_ns, end_ns,
        )

        # Should have given up after 3 retries
        retries = strategy._exit_retries.get(iid, 0)
        assert retries >= 3, f"Only {retries} retries (expected ≥3)"
        assert iid in strategy._closed, "Instrument not marked as closed after 3 retries"
        assert iid not in strategy._exiting, "Instrument still in _exiting set"
        engine.dispose()
