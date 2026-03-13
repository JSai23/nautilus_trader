"""Tick-based always-trade — buys and sells on book updates.

No signals. See book? Buy. Holding? Sell. Repeat.
Generates fills on every market. The baseline tick-pattern strategy.
"""

from __future__ import annotations

from nautilus_trader.model.data import OrderBookDeltas
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events.position import PositionClosed
from nautilus_trader.model.identifiers import InstrumentId

from strategy.base import PolymarketStrategy, PolymarketStrategyConfig


class TickAlwaysConfig(PolymarketStrategyConfig, frozen=True):
    trade_size: float = 5.0
    buy_after_ticks: int = 3  # Buy after N book updates (avoid first-tick junk)
    sell_after_ticks: int = 10  # Hold for N book updates then sell


class TickAlways(PolymarketStrategy):
    """Buy after N ticks, sell after M ticks, repeat. No signals."""

    def __init__(self, config: TickAlwaysConfig) -> None:
        super().__init__(config)
        self._trade_size = config.trade_size
        self._buy_after = config.buy_after_ticks
        self._sell_after = config.sell_after_ticks

        self._tick_count: dict[InstrumentId, int] = {}
        self._hold_ticks: dict[InstrumentId, int] = {}
        self._buys: int = 0
        self._sells: int = 0
        self._round_trips: int = 0

    def on_order_book_deltas(self, deltas: OrderBookDeltas) -> None:
        super().on_order_book_deltas(deltas)
        iid = deltas.instrument_id

        if self._data_ended or iid in self._exiting:
            return

        book = self.cache.order_book(iid)
        if book is None:
            return
        best_bid = book.best_bid_price()
        best_ask = book.best_ask_price()
        if best_bid is None or best_ask is None:
            return

        bid = float(best_bid)
        ask = float(best_ask)

        has_position = bool(self.cache.positions_open(instrument_id=iid))
        has_orders = bool(self.cache.orders_open(instrument_id=iid))

        if has_position:
            self._hold_ticks[iid] = self._hold_ticks.get(iid, 0) + 1
            if self._hold_ticks[iid] >= self._sell_after and not has_orders:
                self._do_sell(iid, bid)
        elif not has_orders:
            self._tick_count[iid] = self._tick_count.get(iid, 0) + 1
            if self._tick_count[iid] >= self._buy_after:
                self._do_buy(iid, ask)

    def _do_buy(self, iid: InstrumentId, ask: float) -> None:
        instrument = self.cache.instrument(iid)
        if instrument is None:
            return
        order = self.order_factory.limit(
            instrument_id=iid,
            order_side=OrderSide.BUY,
            quantity=instrument.make_qty(self._trade_size),
            price=instrument.make_price(ask),
            time_in_force=TimeInForce.FOK,
        )
        self.submit_order(order)
        self._tick_count[iid] = 0
        self._hold_ticks[iid] = 0
        self._buys += 1

    def _do_sell(self, iid: InstrumentId, bid: float) -> None:
        positions = self.cache.positions_open(instrument_id=iid)
        if not positions:
            return
        instrument = self.cache.instrument(iid)
        if instrument is None:
            return
        self.cancel_all_orders(iid)
        qty = instrument.make_qty(abs(float(positions[0].quantity)))
        order = self.order_factory.limit(
            instrument_id=iid,
            order_side=OrderSide.SELL,
            quantity=qty,
            price=instrument.make_price(bid),
            time_in_force=TimeInForce.FOK,
        )
        self.submit_order(order)
        self._sells += 1

    def on_position_closed(self, event: PositionClosed) -> None:
        iid = event.instrument_id
        self._hold_ticks.pop(iid, None)
        self._tick_count[iid] = 0
        self._closed.discard(iid)
        self._exiting.discard(iid)
        self._round_trips += 1

    @property
    def round_trips(self) -> int:
        return self._round_trips
