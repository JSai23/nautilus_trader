"""End-to-end integration test: PMXT data -> instruments -> BacktestEngine -> strategy.

This test hits real PMXT endpoints. It discovers a market from the data,
constructs instruments, feeds the data through the BacktestEngine, and
verifies the strategy receives order book callbacks.
"""

import logging

import pytest

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.model.currencies import USDC_POS
from nautilus_trader.model.enums import AccountType, BookType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money

from tests.conftest import discover_market_with_tokens
from pmxt.generator import pmxt_data_generator
from universe.instruments import build_instrument_maps
from experiments.strategies.log_only import LogOnlyStrategy, LogOnlyStrategyConfig

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

TEST_HOUR = "2026-03-09T09"
POLYMARKET_VENUE = Venue("POLYMARKET")


@pytest.mark.network
class TestEndToEnd:
    @pytest.mark.timeout(300)
    def test_pmxt_to_backtest_engine(self):
        """Full pipeline: PMXT data -> instruments -> BacktestEngine -> strategy callbacks."""
        # Step 1: Discover a real market from PMXT data
        market_info = discover_market_with_tokens(TEST_HOUR)
        condition_id = market_info["condition_id"]
        log.info("Using market: %s", condition_id[:16])

        # Step 2: Build instruments
        instruments, instrument_ids, market_ids = build_instrument_maps([market_info])
        assert len(instruments) > 0, "No instruments built"
        assert condition_id in market_ids

        log.info("Built %d instruments", len(instruments))
        for tid, inst in instruments.items():
            log.info("  %s -> %s (outcome=%s)", tid[:16], inst.id, inst.outcome)

        # Step 3: Set up BacktestEngine
        engine_config = BacktestEngineConfig(logging=False)
        engine = BacktestEngine(config=engine_config)

        engine.add_venue(
            venue=POLYMARKET_VENUE,
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            starting_balances=[Money(10_000, USDC_POS)],
            book_type=BookType.L2_MBP,
        )

        for inst in instruments.values():
            engine.add_instrument(inst)

        # Step 4: Build data generator and feed to engine
        gen = pmxt_data_generator(
            market_ids=market_ids,
            hours=[TEST_HOUR],
            instruments=instruments,
            instrument_ids=instrument_ids,
        )

        engine.add_data_iterator("pmxt", gen)

        # Step 5: Add log-only strategy
        instrument_id_strs = [str(iid) for iid in instrument_ids.values()]
        strategy_config = LogOnlyStrategyConfig(
            instrument_ids=instrument_id_strs,
            log_interval=500,
        )
        strategy = LogOnlyStrategy(config=strategy_config)
        engine.add_strategy(strategy)

        # Step 6: Run
        engine.run()

        # Step 7: Verify the strategy received data
        assert strategy.delta_count > 0, (
            f"Strategy received 0 deltas — data pipeline is broken"
        )

        log.info(
            "SUCCESS: Strategy received %d deltas from PMXT data",
            strategy.delta_count,
        )

        engine.dispose()
