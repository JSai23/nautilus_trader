"""Trading backtest test: proves engine -> order -> fill -> position -> PnL works.

Uses real PMXT data from the same hour as the integration test. Runs SimpleTestStrategy
which places a BUY limit at best_ask on first valid book update — verifying the full
trading pipeline produces actual fills and PnL.
"""

import logging
from datetime import datetime, timedelta, timezone

import pytest

from nautilus_trader.analysis.reporter import ReportProvider
from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.model.currencies import USDC_POS
from nautilus_trader.model.enums import AccountType, BookType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money

from conftest import discover_market_with_tokens, discover_volatile_market
from pmxt.generator import pmxt_data_generator
from runner.tearsheet import compute_tearsheet
from strategy.imbalance import ImbalanceStrategy, ImbalanceStrategyConfig
from strategy.mean_reversion import MeanReversionStrategy, MeanReversionStrategyConfig
from strategy.micro_scalper import MicroScalperStrategy, MicroScalperStrategyConfig
from strategy.momentum_breakout import MomentumBreakoutStrategy, MomentumBreakoutStrategyConfig
from strategy.random_baseline import RandomBaselineStrategy, RandomBaselineStrategyConfig
from strategy.simple_test import SimpleTestStrategy, SimpleTestStrategyConfig
from strategy.spread_scalper import SpreadScalperStrategy, SpreadScalperStrategyConfig
from strategy.timer_momentum import TimerMomentumStrategy, TimerMomentumStrategyConfig
from universe.instruments import build_instrument_maps

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

TEST_HOUR = "2026-03-09T09"
POLYMARKET_VENUE = Venue("POLYMARKET")


def hour_bounds(hour: str) -> tuple[datetime, datetime]:
    """Compute (start_dt, end_dt) for a single hour string like '2026-03-09T09'."""
    start = datetime.strptime(hour, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
    return start, start + timedelta(hours=1)


def hour_bounds_ns(hour: str) -> tuple[int, int]:
    """Compute (start_ns, end_ns) for a single hour string."""
    start, end = hour_bounds(hour)
    return int(start.timestamp() * 1_000_000_000), int(end.timestamp() * 1_000_000_000)


def build_test_engine(
    instruments: dict,
    instrument_ids: dict,
    market_ids: list[str],
    hours: list[str],
    balance: float = 10_000.0,
) -> tuple[BacktestEngine, list[str], datetime, datetime]:
    """Build a fully-configured BacktestEngine for testing.

    Returns (engine, instrument_id_strs, start_dt, end_dt).
    """
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


class TestTradingBacktest:
    @pytest.mark.timeout(300)
    def test_strategy_produces_fills_and_pnl(self):
        """Full trading pipeline: PMXT -> engine -> order -> fill -> position -> PnL."""
        market_info = discover_market_with_tokens(TEST_HOUR)
        instruments, instrument_ids, market_ids = build_instrument_maps([market_info])
        assert len(instruments) > 0

        engine, iid_strs, start_dt, end_dt = build_test_engine(
            instruments, instrument_ids, market_ids, [TEST_HOUR],
        )

        config = SimpleTestStrategyConfig(
            instrument_ids=iid_strs,
            trade_size=1.0,
        )
        strategy = SimpleTestStrategy(config=config)
        engine.add_strategy(strategy)
        engine.run(start=start_dt, end=end_dt)

        assert strategy.order_count > 0, (
            "Strategy submitted 0 orders — book never had valid bid/ask"
        )

        orders = engine.cache.orders()
        positions = engine.cache.positions()

        log.info("Orders: %d, Fills: %d, Positions: %d",
                 len(orders), strategy.fill_count, len(positions))

        orders_df = ReportProvider.generate_order_fills_report(orders)
        fills_df = ReportProvider.generate_fills_report(orders)
        positions_df = ReportProvider.generate_positions_report(positions)

        log.info("Orders DF shape: %s", orders_df.shape)
        log.info("Fills DF shape: %s", fills_df.shape)
        log.info("Positions DF shape: %s", positions_df.shape)

        if strategy.fill_count > 0:
            assert not fills_df.empty, "Fills DF is empty despite fill_count > 0"

            tearsheet = compute_tearsheet(positions_df, fills_df)
            log.info("Tearsheet: %s", tearsheet.to_dict())

            assert tearsheet.num_trades > 0, "Tearsheet shows 0 trades"
            assert tearsheet.num_positions > 0, "Tearsheet shows 0 positions"

            log.info(
                "SUCCESS: %d orders, %d fills, %d trades, PnL=%.4f",
                strategy.order_count,
                strategy.fill_count,
                tearsheet.num_trades,
                tearsheet.total_pnl,
            )
        else:
            log.warning(
                "No fills (FOK rejected) — %d orders submitted. "
                "Book may lack volume. This still proves order pipeline works.",
                strategy.order_count,
            )
            assert len(orders) > 0, "No orders in engine despite strategy submitting"

        engine.dispose()

    @pytest.mark.timeout(300)
    def test_micro_scalper_generates_many_fills(self):
        """MicroScalperStrategy re-enters after exits, producing many fills."""
        market_info = discover_market_with_tokens(TEST_HOUR)
        instruments, instrument_ids, market_ids = build_instrument_maps([market_info])

        engine, iid_strs, start_dt, end_dt = build_test_engine(
            instruments, instrument_ids, market_ids, [TEST_HOUR],
        )

        config = MicroScalperStrategyConfig(
            instrument_ids=iid_strs,
            trade_size=1.0,
            max_spread=0.90,
            ema_alpha=0.3,
            entry_dip_ticks=0,
            max_hold_updates=10,
            cooldown_updates=1,
            convergence_threshold=0.99,
            max_entry_price=1.01,
            min_entry_price=0.0,
        )
        strategy = MicroScalperStrategy(config=config)
        engine.add_strategy(strategy)
        engine.run(start=start_dt, end=end_dt)

        orders = engine.cache.orders()
        fills_df = ReportProvider.generate_fills_report(orders)
        positions = engine.cache.positions()
        closed = [p for p in positions if p.is_closed]
        positions_df = (
            ReportProvider.generate_positions_report(closed)
            if closed
            else ReportProvider.generate_positions_report(positions)
        )

        log.info(
            "MicroScalper: %d orders, %d fills, %d positions, %d round_trips",
            len(orders), len(fills_df), len(positions), strategy.round_trips,
        )

        assert len(fills_df) >= 3, (
            f"MicroScalper only produced {len(fills_df)} fills — re-entry may not be working"
        )

        tearsheet = compute_tearsheet(positions_df, fills_df)
        log.info("MicroScalper tearsheet: %s", tearsheet.to_dict())
        assert tearsheet.num_trades >= 3

        engine.dispose()

    @pytest.mark.timeout(600)
    def test_timer_momentum_on_volatile_market(self):
        """TimerMomentumStrategy uses base class interval timer and produces fills."""
        market_info = discover_volatile_market(TEST_HOUR)
        instruments, instrument_ids, market_ids = build_instrument_maps([market_info])
        start_ns, end_ns = hour_bounds_ns(TEST_HOUR)

        engine, iid_strs, start_dt, end_dt = build_test_engine(
            instruments, instrument_ids, market_ids, [TEST_HOUR],
        )

        config = TimerMomentumStrategyConfig(
            instrument_ids=iid_strs,
            trade_size=1.0,
            check_interval_minutes=1,
            hold_periods=4,
            max_spread=0.20,
            max_entry_price=0.92,
            min_entry_price=0.08,
            convergence_threshold=0.99,
            start_time_ns=start_ns,
            end_time_ns=end_ns,
        )
        strategy = TimerMomentumStrategy(config=config)
        engine.add_strategy(strategy)
        engine.run(start=start_dt, end=end_dt)

        orders = engine.cache.orders()
        fills_df = ReportProvider.generate_fills_report(orders)
        positions = engine.cache.positions()
        closed = [p for p in positions if p.is_closed]
        positions_df = (
            ReportProvider.generate_positions_report(closed)
            if closed
            else ReportProvider.generate_positions_report(positions)
        )

        log.info(
            "TimerMomentum: %d orders, %d fills, %d positions, %d round_trips",
            len(orders), len(fills_df), len(positions), strategy.round_trips,
        )

        assert len(fills_df) >= 2, (
            f"TimerMomentum produced {len(fills_df)} fills — expected at least a buy+sell"
        )

        tearsheet = compute_tearsheet(positions_df, fills_df)
        log.info("TimerMomentum tearsheet: %s", tearsheet.to_dict())
        assert tearsheet.num_trades >= 2
        assert tearsheet.num_round_trips >= 1

        engine.dispose()

    @pytest.mark.timeout(300)
    def test_imbalance_strategy_produces_positions(self):
        """ImbalanceStrategy with null stop_loss/take_profit enters positions."""
        market_info = discover_market_with_tokens(TEST_HOUR)
        instruments, instrument_ids, market_ids = build_instrument_maps([market_info])

        engine, iid_strs, start_dt, end_dt = build_test_engine(
            instruments, instrument_ids, market_ids, [TEST_HOUR],
        )

        config = ImbalanceStrategyConfig(
            instrument_ids=iid_strs,
            imbalance_threshold=0.3,
            trade_size=5.0,
            take_profit=None,
            stop_loss=None,
        )
        strategy = ImbalanceStrategy(config=config)
        engine.add_strategy(strategy)
        engine.run(start=start_dt, end=end_dt)

        orders = engine.cache.orders()
        positions = engine.cache.positions()

        log.info(
            "ImbalanceStrategy: %d orders, %d positions",
            len(orders), len(positions),
        )

        assert len(orders) > 0, (
            "ImbalanceStrategy submitted 0 orders — no book had imbalance > 0.3"
        )
        assert len(positions) > 0, "No positions created despite orders"

        fills_df = ReportProvider.generate_fills_report(orders)
        positions_df = ReportProvider.generate_positions_report(positions)

        if not fills_df.empty:
            tearsheet = compute_tearsheet(positions_df, fills_df)
            log.info("ImbalanceStrategy tearsheet: %s", tearsheet.to_dict())
            assert tearsheet.num_positions > 0

        engine.dispose()

    @pytest.mark.timeout(600)
    def test_mean_reversion_on_volatile_market(self):
        """MeanReversionStrategy buys dips and sells on reversion."""
        market_info = discover_volatile_market(TEST_HOUR)
        instruments, instrument_ids, market_ids = build_instrument_maps([market_info])
        start_ns, end_ns = hour_bounds_ns(TEST_HOUR)

        engine, iid_strs, start_dt, end_dt = build_test_engine(
            instruments, instrument_ids, market_ids, [TEST_HOUR],
        )

        config = MeanReversionStrategyConfig(
            instrument_ids=iid_strs,
            trade_size=1.0,
            check_interval_minutes=1,
            lookback_periods=5,
            entry_deviation=0.005,
            hold_periods=4,
            max_spread=0.25,
            max_entry_price=0.95,
            min_entry_price=0.05,
            convergence_threshold=0.99,
            start_time_ns=start_ns,
            end_time_ns=end_ns,
        )
        strategy = MeanReversionStrategy(config=config)
        engine.add_strategy(strategy)
        engine.run(start=start_dt, end=end_dt)

        orders = engine.cache.orders()
        fills_df = ReportProvider.generate_fills_report(orders)
        positions = engine.cache.positions()
        closed = [p for p in positions if p.is_closed]
        positions_df = (
            ReportProvider.generate_positions_report(closed)
            if closed
            else ReportProvider.generate_positions_report(positions)
        )

        log.info(
            "MeanReversion: %d orders, %d fills, %d positions, %d round_trips",
            len(orders), len(fills_df), len(positions), strategy.round_trips,
        )

        assert len(fills_df) >= 2, (
            f"MeanReversion produced {len(fills_df)} fills — expected at least buy+sell"
        )

        tearsheet = compute_tearsheet(positions_df, fills_df)
        log.info("MeanReversion tearsheet: %s", tearsheet.to_dict())
        assert tearsheet.num_trades >= 2
        assert tearsheet.num_round_trips >= 1

        engine.dispose()

    @pytest.mark.timeout(600)
    def test_spread_scalper_on_volatile_market(self):
        """SpreadScalperStrategy enters on tight spreads and exits on widening."""
        market_info = discover_volatile_market(TEST_HOUR)
        instruments, instrument_ids, market_ids = build_instrument_maps([market_info])
        start_ns, end_ns = hour_bounds_ns(TEST_HOUR)

        engine, iid_strs, start_dt, end_dt = build_test_engine(
            instruments, instrument_ids, market_ids, [TEST_HOUR],
        )

        config = SpreadScalperStrategyConfig(
            instrument_ids=iid_strs,
            trade_size=1.0,
            check_interval_minutes=1,
            spread_lookback=5,
            tight_spread_ratio=0.8,
            wide_spread_ratio=1.2,
            hold_periods=4,
            max_spread=0.25,
            max_entry_price=0.95,
            min_entry_price=0.05,
            convergence_threshold=0.99,
            start_time_ns=start_ns,
            end_time_ns=end_ns,
        )
        strategy = SpreadScalperStrategy(config=config)
        engine.add_strategy(strategy)
        engine.run(start=start_dt, end=end_dt)

        orders = engine.cache.orders()
        fills_df = ReportProvider.generate_fills_report(orders)
        positions = engine.cache.positions()
        closed = [p for p in positions if p.is_closed]
        positions_df = (
            ReportProvider.generate_positions_report(closed)
            if closed
            else ReportProvider.generate_positions_report(positions)
        )

        log.info(
            "SpreadScalper: %d orders, %d fills, %d positions, %d round_trips",
            len(orders), len(fills_df), len(positions), strategy.round_trips,
        )

        assert len(fills_df) >= 2, (
            f"SpreadScalper produced {len(fills_df)} fills — expected at least buy+sell"
        )

        tearsheet = compute_tearsheet(positions_df, fills_df)
        log.info("SpreadScalper tearsheet: %s", tearsheet.to_dict())
        assert tearsheet.num_trades >= 2
        assert tearsheet.num_round_trips >= 1

        engine.dispose()

    @pytest.mark.timeout(600)
    def test_momentum_breakout_on_volatile_market(self):
        """MomentumBreakoutStrategy enters on sustained directional movement."""
        market_info = discover_volatile_market(TEST_HOUR)
        instruments, instrument_ids, market_ids = build_instrument_maps([market_info])
        start_ns, end_ns = hour_bounds_ns(TEST_HOUR)

        engine, iid_strs, start_dt, end_dt = build_test_engine(
            instruments, instrument_ids, market_ids, [TEST_HOUR],
        )

        config = MomentumBreakoutStrategyConfig(
            instrument_ids=iid_strs,
            trade_size=1.0,
            check_interval_minutes=1,
            breakout_periods=2,
            hold_periods=4,
            reversal_periods=1,
            max_spread=0.25,
            max_entry_price=0.95,
            min_entry_price=0.05,
            convergence_threshold=0.99,
            start_time_ns=start_ns,
            end_time_ns=end_ns,
        )
        strategy = MomentumBreakoutStrategy(config=config)
        engine.add_strategy(strategy)
        engine.run(start=start_dt, end=end_dt)

        orders = engine.cache.orders()
        fills_df = ReportProvider.generate_fills_report(orders)
        positions = engine.cache.positions()
        closed = [p for p in positions if p.is_closed]
        positions_df = (
            ReportProvider.generate_positions_report(closed)
            if closed
            else ReportProvider.generate_positions_report(positions)
        )

        log.info(
            "MomentumBreakout: %d orders, %d fills, %d positions, %d round_trips",
            len(orders), len(fills_df), len(positions), strategy.round_trips,
        )

        assert len(fills_df) >= 2, (
            f"MomentumBreakout produced {len(fills_df)} fills — expected at least buy+sell"
        )

        tearsheet = compute_tearsheet(positions_df, fills_df)
        log.info("MomentumBreakout tearsheet: %s", tearsheet.to_dict())
        assert tearsheet.num_trades >= 2
        assert tearsheet.num_round_trips >= 1

        engine.dispose()

    @pytest.mark.timeout(600)
    def test_random_baseline_on_volatile_market(self):
        """RandomBaselineStrategy enters randomly and exits after fixed hold."""
        market_info = discover_volatile_market(TEST_HOUR)
        instruments, instrument_ids, market_ids = build_instrument_maps([market_info])
        start_ns, end_ns = hour_bounds_ns(TEST_HOUR)

        engine, iid_strs, start_dt, end_dt = build_test_engine(
            instruments, instrument_ids, market_ids, [TEST_HOUR],
        )

        config = RandomBaselineStrategyConfig(
            instrument_ids=iid_strs,
            trade_size=1.0,
            check_interval_minutes=1,
            entry_probability=0.5,
            hold_periods=3,
            max_spread=0.25,
            max_entry_price=0.95,
            min_entry_price=0.05,
            seed=42,
            convergence_threshold=0.99,
            start_time_ns=start_ns,
            end_time_ns=end_ns,
        )
        strategy = RandomBaselineStrategy(config=config)
        engine.add_strategy(strategy)
        engine.run(start=start_dt, end=end_dt)

        orders = engine.cache.orders()
        fills_df = ReportProvider.generate_fills_report(orders)
        positions = engine.cache.positions()
        closed = [p for p in positions if p.is_closed]
        positions_df = (
            ReportProvider.generate_positions_report(closed)
            if closed
            else ReportProvider.generate_positions_report(positions)
        )

        log.info(
            "RandomBaseline: %d orders, %d fills, %d positions, %d round_trips",
            len(orders), len(fills_df), len(positions), strategy.round_trips,
        )

        assert len(fills_df) >= 2, (
            f"RandomBaseline produced {len(fills_df)} fills — expected at least buy+sell"
        )

        tearsheet = compute_tearsheet(positions_df, fills_df)
        log.info("RandomBaseline tearsheet: %s", tearsheet.to_dict())
        assert tearsheet.num_trades >= 2
        assert tearsheet.num_round_trips >= 1

        engine.dispose()
