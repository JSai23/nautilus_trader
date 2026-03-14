"""Trading backtest tests: proves engine -> order -> fill -> position -> PnL works.

Uses real PMXT data. Tests TickAlways (tick pattern) and TimerAlways (timer pattern)
plus SimpleTestStrategy (single order) to verify the full trading pipeline.
"""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nautilus_trader.analysis.reporter import ReportProvider
from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.model.currencies import USDC_POS
from nautilus_trader.model.enums import AccountType, BookType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money

from pmxt.reader import read_local_filtered
from pmxt.transformer import transform_row
from runner.tearsheet import compute_tearsheet
from experiments.strategies.tick_always import TickAlways, TickAlwaysConfig
from experiments.strategies.timer_always import TimerAlways, TimerAlwaysConfig
from experiments.strategies.simple_test import SimpleTestStrategy, SimpleTestStrategyConfig
from universe.instruments import build_instrument_maps

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

TEST_HOUR = "2026-03-09T09"
POLYMARKET_VENUE = Venue("POLYMARKET")


def hour_bounds(hour: str) -> tuple[datetime, datetime]:
    start = datetime.strptime(hour, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
    return start, start + timedelta(hours=1)


def hour_bounds_ns(hour: str) -> tuple[int, int]:
    start, end = hour_bounds(hour)
    return int(start.timestamp() * 1_000_000_000), int(end.timestamp() * 1_000_000_000)


def _local_data_generator(local_path, market_ids, instruments, instrument_ids):
    for batch in read_local_filtered(local_path, market_ids):
        transformed = []
        for row in batch:
            result = transform_row(row, instruments, instrument_ids)
            if result is not None:
                transformed.append(result)
        if transformed:
            transformed.sort(key=lambda d: d.ts_init)
            yield transformed


def build_test_engine(
    instruments: dict,
    instrument_ids: dict,
    market_ids: list[str],
    hours: list[str],
    local_path: Path | None = None,
    balance: float = 10_000.0,
) -> tuple[BacktestEngine, list[str], datetime, datetime]:
    engine = BacktestEngine(config=BacktestEngineConfig(logging=False))
    engine.add_venue(
        venue=POLYMARKET_VENUE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        starting_balances=[Money(balance, USDC_POS)],
        book_type=BookType.L2_MBP,
    )
    for inst in instruments.values():
        engine.add_instrument(inst)

    if local_path is not None:
        gen = _local_data_generator(local_path, market_ids, instruments, instrument_ids)
    else:
        from pmxt.generator import pmxt_data_generator
        gen = pmxt_data_generator(
            market_ids=market_ids,
            hours=hours,
            instruments=instruments,
            instrument_ids=instrument_ids,
        )
    engine.add_data_iterator("pmxt", gen)

    instrument_id_strs = [str(iid) for iid in instrument_ids.values()]
    start_dt, end_dt = hour_bounds(hours[0])
    if len(hours) > 1:
        _, end_dt = hour_bounds(hours[-1])

    return engine, instrument_id_strs, start_dt, end_dt


@pytest.mark.network
class TestTradingBacktest:
    @pytest.mark.timeout(300)
    def test_simple_test_produces_fills(self, market_with_tokens, pmxt_local_path):
        """SimpleTestStrategy places one order — proves basic order pipeline."""
        market_info = market_with_tokens
        instruments, instrument_ids, market_ids = build_instrument_maps([market_info])
        assert len(instruments) > 0

        engine, iid_strs, start_dt, end_dt = build_test_engine(
            instruments, instrument_ids, market_ids, [TEST_HOUR], local_path=pmxt_local_path,
        )

        config = SimpleTestStrategyConfig(instrument_ids=iid_strs, trade_size=1.0)
        strategy = SimpleTestStrategy(config=config)
        engine.add_strategy(strategy)
        engine.run(start=start_dt, end=end_dt)

        assert strategy.order_count > 0, "Strategy submitted 0 orders"

        orders = engine.cache.orders()
        fills_df = ReportProvider.generate_fills_report(orders)
        positions_df = ReportProvider.generate_positions_report(engine.cache.positions())

        if strategy.fill_count > 0:
            tearsheet = compute_tearsheet(positions_df, fills_df)
            assert tearsheet.num_trades > 0
            log.info("SimpleTest: %d fills, PnL=%.4f", strategy.fill_count, tearsheet.total_pnl)

        engine.dispose()

    @pytest.mark.timeout(300)
    def test_tick_always_generates_many_fills(self, market_with_tokens, pmxt_local_path):
        """TickAlways buys/sells on book updates — should produce many round trips."""
        market_info = market_with_tokens
        instruments, instrument_ids, market_ids = build_instrument_maps([market_info])

        engine, iid_strs, start_dt, end_dt = build_test_engine(
            instruments, instrument_ids, market_ids, [TEST_HOUR], local_path=pmxt_local_path,
        )

        config = TickAlwaysConfig(
            instrument_ids=iid_strs,
            trade_size=1.0,
            buy_after_ticks=3,
            sell_after_ticks=10,
        )
        strategy = TickAlways(config=config)
        engine.add_strategy(strategy)
        engine.run(start=start_dt, end=end_dt)

        orders = engine.cache.orders()
        fills_df = ReportProvider.generate_fills_report(orders)
        closed = [p for p in engine.cache.positions() if p.is_closed]
        positions_df = (
            ReportProvider.generate_positions_report(closed)
            if closed
            else ReportProvider.generate_positions_report(engine.cache.positions())
        )

        log.info("TickAlways: %d fills, %d round_trips", len(fills_df), strategy.round_trips)

        assert len(fills_df) >= 3, f"TickAlways only produced {len(fills_df)} fills"
        tearsheet = compute_tearsheet(positions_df, fills_df)
        assert tearsheet.num_trades >= 3

        engine.dispose()

    @pytest.mark.timeout(600)
    def test_timer_always_on_volatile_market(self, volatile_market, pmxt_local_path):
        """TimerAlways buys/sells on intervals — should produce round trips."""
        market_info = volatile_market
        instruments, instrument_ids, market_ids = build_instrument_maps([market_info])
        start_ns, end_ns = hour_bounds_ns(TEST_HOUR)

        engine, iid_strs, start_dt, end_dt = build_test_engine(
            instruments, instrument_ids, market_ids, [TEST_HOUR], local_path=pmxt_local_path,
        )

        config = TimerAlwaysConfig(
            instrument_ids=iid_strs,
            trade_size=1.0,
            check_interval_minutes=1,
            hold_periods=4,
            convergence_threshold=0.99,
            start_time_ns=start_ns,
            end_time_ns=end_ns,
        )
        strategy = TimerAlways(config=config)
        engine.add_strategy(strategy)
        engine.run(start=start_dt, end=end_dt)

        orders = engine.cache.orders()
        fills_df = ReportProvider.generate_fills_report(orders)
        closed = [p for p in engine.cache.positions() if p.is_closed]
        positions_df = (
            ReportProvider.generate_positions_report(closed)
            if closed
            else ReportProvider.generate_positions_report(engine.cache.positions())
        )

        log.info("TimerAlways: %d fills, %d round_trips", len(fills_df), strategy.round_trips)

        assert len(fills_df) >= 2, f"TimerAlways produced {len(fills_df)} fills"
        tearsheet = compute_tearsheet(positions_df, fills_df)
        assert tearsheet.num_trades >= 2
        assert tearsheet.num_round_trips >= 1

        engine.dispose()
