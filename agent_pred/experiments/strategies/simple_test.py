"""Simple test strategy — places one order on first valid book update.

Used for integration testing: proves the engine -> order -> fill -> position -> PnL
pipeline works end-to-end with real PMXT data. Not meant for actual trading.
"""

from __future__ import annotations

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import OrderBookDeltas
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy


class SimpleTestStrategyConfig(StrategyConfig, frozen=True):
    instrument_ids: list[str] = []
    trade_size: float = 1.0


class SimpleTestStrategy(Strategy):
    """Places a single BUY limit order at best_ask on first valid book update."""

    def __init__(self, config: SimpleTestStrategyConfig) -> None:
        super().__init__(config)
        self._instrument_ids = [
            InstrumentId.from_str(iid) for iid in config.instrument_ids
        ]
        self._trade_size = config.trade_size
        self._traded: set[InstrumentId] = set()
        self.order_count = 0
        self.fill_count = 0

    def on_start(self) -> None:
        for instrument_id in self._instrument_ids:
            self.subscribe_order_book_deltas(instrument_id)

    def on_order_book_deltas(self, deltas: OrderBookDeltas) -> None:
        instrument_id = deltas.instrument_id
        if instrument_id in self._traded:
            return

        book = self.cache.order_book(instrument_id)
        if book is None:
            return

        best_ask = book.best_ask_price()
        best_bid = book.best_bid_price()
        if best_ask is None or best_bid is None:
            return

        instrument = self.cache.instrument(instrument_id)
        if instrument is None:
            return

        # Place a BUY limit at best_ask — should fill immediately
        self._traded.add(instrument_id)
        qty = instrument.make_qty(self._trade_size)
        order = self.order_factory.limit(
            instrument_id=instrument_id,
            order_side=OrderSide.BUY,
            quantity=qty,
            price=best_ask,
            time_in_force=TimeInForce.FOK,
        )
        self.submit_order(order)
        self.order_count += 1
        self.log.info(
            f"Submitted BUY {qty} @ {best_ask} for {instrument_id}"
        )

    def on_order_filled(self, event) -> None:
        self.fill_count += 1
        self.log.info(f"FILLED: {event}")
