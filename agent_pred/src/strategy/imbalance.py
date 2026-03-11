"""Order book imbalance strategy — example strategy extending PolymarketStrategy.

Trades based on the ratio of bid volume to ask volume in the order book.
When imbalance exceeds threshold, enters a position in the dominant direction.
"""

from __future__ import annotations

from nautilus_trader.model.data import OrderBookDeltas
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId

from strategy.base import PolymarketStrategy, PolymarketStrategyConfig


class ImbalanceStrategyConfig(PolymarketStrategyConfig, frozen=True):
    imbalance_threshold: float = 0.3
    trade_size: float = 10.0


class ImbalanceStrategy(PolymarketStrategy):
    """Trades order book imbalance on Polymarket binary options."""

    def __init__(self, config: ImbalanceStrategyConfig) -> None:
        super().__init__(config)
        self._imbalance_threshold = config.imbalance_threshold
        self._trade_size = config.trade_size

    def on_order_book_deltas(self, deltas: OrderBookDeltas) -> None:
        super().on_order_book_deltas(deltas)

        instrument_id = deltas.instrument_id
        if instrument_id in self._closed or instrument_id in self._exiting:
            return

        # Skip if we already have a position
        open_positions = self.cache.positions_open(instrument_id=instrument_id)
        if open_positions:
            return

        # Skip if we have open orders
        orders = self.cache.orders_open(instrument_id=instrument_id)
        if orders:
            return

        book = self.cache.order_book(instrument_id)
        if book is None:
            return

        # Compute imbalance
        bids = book.bids()
        asks = book.asks()
        if not bids or not asks:
            return

        bid_vol = sum(level.size() for level in bids)
        ask_vol = sum(level.size() for level in asks)
        total = bid_vol + ask_vol

        if total == 0:
            return

        imbalance = (bid_vol - ask_vol) / total

        instrument = self.cache.instrument(instrument_id)
        if instrument is None:
            return

        best_ask = book.best_ask_price()
        best_bid = book.best_bid_price()

        if imbalance > self._imbalance_threshold and best_ask is not None:
            # More bids than asks -> price likely to rise -> buy
            order = self.order_factory.limit(
                instrument_id=instrument_id,
                order_side=OrderSide.BUY,
                quantity=instrument.make_qty(self._trade_size),
                price=best_ask,
                time_in_force=TimeInForce.FOK,
            )
            self.submit_order(order)

        elif imbalance < -self._imbalance_threshold and best_bid is not None:
            # More asks than bids -> price likely to fall -> sell
            order = self.order_factory.limit(
                instrument_id=instrument_id,
                order_side=OrderSide.SELL,
                quantity=instrument.make_qty(self._trade_size),
                price=best_bid,
                time_in_force=TimeInForce.FOK,
            )
            self.submit_order(order)
