"""Order book imbalance strategy — example strategy extending PolymarketStrategy.

Trades based on the ratio of bid volume to ask volume in the order book.
When imbalance exceeds threshold, BUYs the token (bullish signal).

Market-aware: only enters one side per market. Never sells/shorts tokens —
on Polymarket, a bearish view on YES means BUY NO, not SELL YES.
"""

from __future__ import annotations

from nautilus_trader.adapters.polymarket.common.symbol import get_polymarket_condition_id
from nautilus_trader.model.data import OrderBookDeltas
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId

from strategy.base import PolymarketStrategy, PolymarketStrategyConfig


class ImbalanceStrategyConfig(PolymarketStrategyConfig, frozen=True):
    imbalance_threshold: float = 0.3
    trade_size: float = 10.0


class ImbalanceStrategy(PolymarketStrategy):
    """Trades order book imbalance on Polymarket binary options.

    Only BUYs tokens when bid volume dominates (positive imbalance).
    Tracks positions per market (condition_id) to avoid entering both
    YES and NO tokens of the same market simultaneously.
    """

    def __init__(self, config: ImbalanceStrategyConfig) -> None:
        super().__init__(config)
        self._imbalance_threshold = config.imbalance_threshold
        self._trade_size = config.trade_size
        self._market_instruments: dict[str, list[InstrumentId]] = {}

    def on_start(self) -> None:
        super().on_start()
        # Group instruments by market (condition_id)
        for iid in self._instrument_ids:
            condition_id = get_polymarket_condition_id(iid)
            self._market_instruments.setdefault(condition_id, []).append(iid)

    def _market_has_position(self, instrument_id: InstrumentId) -> bool:
        """Check if any sibling token in the same market has an open position."""
        condition_id = get_polymarket_condition_id(instrument_id)
        for sibling_id in self._market_instruments.get(condition_id, []):
            if self.cache.positions_open(instrument_id=sibling_id):
                return True
        return False

    def on_order_book_deltas(self, deltas: OrderBookDeltas) -> None:
        super().on_order_book_deltas(deltas)

        instrument_id = deltas.instrument_id
        if self._data_ended or instrument_id in self._closed or instrument_id in self._exiting:
            return

        # Skip if this instrument already has a position
        if self.cache.positions_open(instrument_id=instrument_id):
            return

        # Skip if another token from the same market has a position
        if self._market_has_position(instrument_id):
            return

        # Skip if we have open orders
        if self.cache.orders_open(instrument_id=instrument_id):
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

        # Only BUY on positive imbalance (bid-heavy -> price likely to rise).
        # Never SELL/short — expressing a bearish view means buying the
        # opposite token, which will trigger via its own imbalance signal.
        if imbalance > self._imbalance_threshold and best_ask is not None:
            order = self.order_factory.limit(
                instrument_id=instrument_id,
                order_side=OrderSide.BUY,
                quantity=instrument.make_qty(self._trade_size),
                price=best_ask,
                time_in_force=TimeInForce.FOK,
            )
            self.submit_order(order)
