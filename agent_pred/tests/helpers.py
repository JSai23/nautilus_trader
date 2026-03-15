"""Shared test helper functions for agent_pred tests.

These are importable from any test file, unlike conftest.py fixtures.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.model.currencies import USDC_POS
from nautilus_trader.model.enums import AccountType, BookType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money

from pmxt.reader import read_local_filtered
from pmxt.transformer import transform_book_snapshot, transform_row
from universe.instruments import build_instrument_maps

TEST_HOUR = "2026-03-09T09"
POLYMARKET_VENUE = Venue("POLYMARKET")
FIXTURES_DIR = Path(__file__).parent / "fixtures"

FAKE_MARKET = {
    "condition_id": "0x" + "e" * 64,
    "question": "Test exit market",
    "minimum_tick_size": "0.01",
    "minimum_order_size": "1",
    "end_date_iso": "2027-12-31T00:00:00Z",
    "maker_base_fee": "0",
    "taker_base_fee": "0",
    "tokens": [
        {"token_id": "exit_token_yes", "outcome": "Yes"},
        {"token_id": "exit_token_no", "outcome": "No"},
    ],
}


def hour_bounds(hour: str) -> tuple[datetime, datetime]:
    start = datetime.strptime(hour, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
    return start, start + timedelta(hours=1)


def hour_bounds_ns(hour: str) -> tuple[int, int]:
    start, end = hour_bounds(hour)
    return int(start.timestamp() * 1_000_000_000), int(end.timestamp() * 1_000_000_000)


def local_data_generator(local_path, market_ids, instruments, instrument_ids):
    """Yield sorted NautilusTrader data batches from a local parquet file."""
    for batch in read_local_filtered(local_path, market_ids):
        transformed = []
        for row in batch:
            result = transform_row(row, instruments, instrument_ids)
            if result is not None:
                transformed.append(result)
        if transformed:
            transformed.sort(key=lambda d: d.ts_init)
            yield transformed


def build_test_engine(instruments, instrument_ids, market_ids, local_path, balance=10_000.0):
    """Build a BacktestEngine with local data loaded, ready for a strategy."""
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

    gen = local_data_generator(local_path, market_ids, instruments, instrument_ids)
    engine.add_data_iterator("pmxt", gen)
    return engine


def make_book_snapshot(instrument, instrument_id, bid, ask, ts_ns,
                       bid_qty=1000, ask_qty=1000):
    """Create OrderBookDeltas with a single bid/ask level."""
    data = {
        "bids": [[str(bid), str(bid_qty)]],
        "asks": [[str(ask), str(ask_qty)]],
        "timestamp": ts_ns / 1e9,
    }
    return transform_book_snapshot(data, instrument_id, instrument, ts_ns, ts_ns)


def make_synthetic_engine(instrument, instrument_id, price_path, start_ns, end_ns):
    """Build engine with synthetic orderbook data following a specific price path.

    price_path: list of tuples — either:
      (timestamp_ns, bid, ask)                    — default qty=1000
      (timestamp_ns, bid, ask, bid_qty, ask_qty)  — custom qty
    """
    engine = BacktestEngine(config=BacktestEngineConfig(logging=False))
    engine.add_venue(
        venue=POLYMARKET_VENUE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        starting_balances=[Money(10_000, USDC_POS)],
        book_type=BookType.L2_MBP,
    )
    engine.add_instrument(instrument)

    def data_gen():
        batch = []
        for tick in price_path:
            ts, bid, ask = tick[0], tick[1], tick[2]
            bq = tick[3] if len(tick) > 3 else 1000
            aq = tick[4] if len(tick) > 4 else 1000
            deltas = make_book_snapshot(instrument, instrument_id, bid, ask, ts,
                                        bid_qty=bq, ask_qty=aq)
            batch.append(deltas)
            if len(batch) >= 50:
                batch.sort(key=lambda d: d.ts_init)
                yield batch
                batch = []
        if batch:
            batch.sort(key=lambda d: d.ts_init)
            yield batch

    engine.add_data_iterator("synthetic", data_gen())
    return engine
