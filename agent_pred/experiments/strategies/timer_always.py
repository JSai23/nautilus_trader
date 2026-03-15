"""Timer-based always-trade — buys and sells on every interval.

No signals. Timer fires? Buy. Already holding? Sell. Repeat.
Generates fills on every market. The baseline timer-pattern strategy.
"""

from __future__ import annotations

from nautilus_trader.common.events import TimeEvent
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events.position import PositionClosed
from nautilus_trader.model.identifiers import InstrumentId

from strategy.base import PolymarketStrategy, PolymarketStrategyConfig


class TimerAlwaysConfig(PolymarketStrategyConfig, frozen=True):
    trade_size: float = 5.0
    check_interval_minutes: int = 1
    hold_periods: int = 4  # Sell after N intervals


class TimerAlways(PolymarketStrategy):
    """Buy on first interval with valid book, sell after N intervals. Repeat."""

    def __init__(self, config: TimerAlwaysConfig) -> None:
        super().__init__(config)
        self._trade_size = config.trade_size
        self._hold_periods = config.hold_periods
        self._hold_count: dict[InstrumentId, int] = {}
        self._round_trips: int = 0

    def on_interval(self, event: TimeEvent) -> None:
        for iid in self._instrument_ids:
            if iid in self._exiting or iid in self._closed:
                continue

            book = self.cache.order_book(iid)
            if book is None:
                continue
            best_bid = book.best_bid_price()
            best_ask = book.best_ask_price()
            if best_bid is None or best_ask is None:
                continue

            bid = float(best_bid)
            ask = float(best_ask)

            has_position = bool(self.cache.positions_open(instrument_id=iid))
            has_orders = bool(self.cache.orders_open(instrument_id=iid))

            if has_position:
                self._hold_count[iid] = self._hold_count.get(iid, 0) + 1
                if self._hold_count[iid] >= self._hold_periods and not has_orders:
                    self._do_sell(iid, bid)
            elif not has_orders:
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
        self._hold_count[iid] = 0

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

    def on_position_closed(self, event: PositionClosed) -> None:
        iid = event.instrument_id
        self._hold_count.pop(iid, None)
        self._closed.discard(iid)
        self._exiting.discard(iid)
        self._round_trips += 1

    @property
    def round_trips(self) -> int:
        return self._round_trips
