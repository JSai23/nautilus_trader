"""Spread capture strategy — buy aggressively when spread is wide, exit at entry+1 tick.

When spread exceeds a threshold, buy at ask (FOK) to guarantee fill.
After fill, hold until bid reaches entry + profit_ticks for quick profit.
Falls back to time-stop exit if the take-profit level isn't reached.
"""

from __future__ import annotations

from nautilus_trader.common.events import TimeEvent
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events.position import PositionClosed
from nautilus_trader.model.identifiers import InstrumentId

from strategy.base import PolymarketStrategy, PolymarketStrategyConfig


class SpreadCaptureStrategyConfig(PolymarketStrategyConfig, frozen=True):
    trade_size: float = 1.0
    check_interval_minutes: int = 1
    min_spread_ticks: int = 3  # Only enter when spread >= N ticks
    profit_ticks: int = 1  # Target profit in ticks above entry
    hold_periods: int = 5  # Max hold time before forced exit
    max_entry_price: float = 0.92
    min_entry_price: float = 0.08
    tick_size: float = 0.001


class SpreadCaptureStrategy(PolymarketStrategy):
    """Capture spread by buying at ask and exiting when bid >= entry + profit_ticks.

    On each interval:
    - If no position and spread >= min_spread_ticks, buy at ask (FOK)
    - If holding and bid >= entry + profit_ticks, sell at bid (take profit)
    - If holding too long, sell at bid (time stop)
    """

    def __init__(self, config: SpreadCaptureStrategyConfig) -> None:
        super().__init__(config)
        self._trade_size = config.trade_size
        self._min_spread_ticks = config.min_spread_ticks
        self._profit_ticks = config.profit_ticks
        self._hold_periods = config.hold_periods
        self._max_entry_price = config.max_entry_price
        self._min_entry_price = config.min_entry_price
        self._tick_size = config.tick_size

        self._entry_price: dict[InstrumentId, float] = {}
        self._hold_count: dict[InstrumentId, int] = {}
        self._round_trips: int = 0

    def on_interval(self, event: TimeEvent) -> None:
        for instrument_id in self._instrument_ids:
            if instrument_id in self._exiting or instrument_id in self._closed:
                continue
            self._check_instrument(instrument_id)

    def _check_instrument(self, instrument_id: InstrumentId) -> None:
        book = self.cache.order_book(instrument_id)
        if book is None:
            return

        best_bid = book.best_bid_price()
        best_ask = book.best_ask_price()
        if best_bid is None or best_ask is None:
            return

        bid = float(best_bid)
        ask = float(best_ask)
        spread = ask - bid
        mid = (bid + ask) / 2.0

        has_position = bool(self.cache.positions_open(instrument_id=instrument_id))

        if has_position:
            self._manage_position(instrument_id, bid)
        else:
            self._check_entry(instrument_id, bid, ask, mid, spread)

    def _check_entry(
        self,
        instrument_id: InstrumentId,
        bid: float,
        ask: float,
        mid: float,
        spread: float,
    ) -> None:
        if ask >= self._max_entry_price or ask <= self._min_entry_price:
            return

        spread_ticks = spread / self._tick_size
        if spread_ticks < self._min_spread_ticks:
            return

        instrument = self.cache.instrument(instrument_id)
        if instrument is None:
            return
        if self.cache.orders_open(instrument_id=instrument_id):
            return

        # Buy at ask (aggressive, ensures FOK fill) when spread is wide
        order = self.order_factory.limit(
            instrument_id=instrument_id,
            order_side=OrderSide.BUY,
            quantity=instrument.make_qty(self._trade_size),
            price=instrument.make_price(ask),
            time_in_force=TimeInForce.FOK,
        )
        self.submit_order(order)
        self._entry_price[instrument_id] = ask
        self._hold_count[instrument_id] = 0

    def _manage_position(self, instrument_id: InstrumentId, bid: float) -> None:
        self._hold_count[instrument_id] = self._hold_count.get(instrument_id, 0) + 1

        entry = self._entry_price.get(instrument_id)
        if entry is None:
            # Shouldn't happen, but exit gracefully
            self._submit_exit(instrument_id, bid)
            return

        # Try take-profit: sell at entry + profit_ticks
        target = entry + self._profit_ticks * self._tick_size

        # Check if bid is at or above target — we can exit profitably
        if bid >= target:
            self._submit_exit(instrument_id, bid)
            return

        # Time stop: forced exit
        if self._hold_count[instrument_id] >= self._hold_periods:
            self._submit_exit(instrument_id, bid)

    def _submit_exit(self, instrument_id: InstrumentId, bid: float) -> None:
        positions = self.cache.positions_open(instrument_id=instrument_id)
        if not positions:
            return

        position = positions[0]
        instrument = self.cache.instrument(instrument_id)
        if instrument is None:
            return

        self.cancel_all_orders(instrument_id)

        qty = instrument.make_qty(abs(float(position.quantity)))
        order = self.order_factory.limit(
            instrument_id=instrument_id,
            order_side=OrderSide.SELL,
            quantity=qty,
            price=instrument.make_price(bid),
            time_in_force=TimeInForce.FOK,
        )
        self.submit_order(order)

    def on_position_closed(self, event: PositionClosed) -> None:
        instrument_id = event.instrument_id
        self._entry_price.pop(instrument_id, None)
        self._hold_count.pop(instrument_id, None)
        self._closed.discard(instrument_id)
        self._exiting.discard(instrument_id)
        self._round_trips += 1

    @property
    def round_trips(self) -> int:
        return self._round_trips
