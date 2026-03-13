"""Trend follower strategy — buy when mid-price moves up N ticks in a window.

Checks on each interval whether the mid-price has risen by a tick threshold
over a lookback window. Holds for a fixed number of intervals, then exits.
Simple momentum strategy designed to exercise infrastructure with real fills.
"""

from __future__ import annotations

from collections import deque

from nautilus_trader.common.events import TimeEvent
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events.position import PositionClosed
from nautilus_trader.model.identifiers import InstrumentId

from strategy.base import PolymarketStrategy, PolymarketStrategyConfig


class TrendFollowerStrategyConfig(PolymarketStrategyConfig, frozen=True):
    trade_size: float = 1.0
    check_interval_minutes: int = 1
    tick_threshold: int = 3  # Buy when mid moved up this many ticks
    lookback_periods: int = 5  # Window to measure trend (in intervals)
    hold_periods: int = 10  # Hold for N intervals then exit
    max_spread: float = 0.15
    max_entry_price: float = 0.92
    min_entry_price: float = 0.08
    tick_size: float = 0.001  # Polymarket tick size


class TrendFollowerStrategy(PolymarketStrategy):
    """Buy when mid-price rises by tick_threshold over lookback window.

    On each interval:
    - Record current mid price
    - If no position and mid rose by N ticks in last M intervals, buy at ask
    - If holding, exit after hold_periods intervals
    """

    def __init__(self, config: TrendFollowerStrategyConfig) -> None:
        super().__init__(config)
        self._trade_size = config.trade_size
        self._tick_threshold = config.tick_threshold
        self._lookback_periods = config.lookback_periods
        self._hold_periods = config.hold_periods
        self._max_spread = config.max_spread
        self._max_entry_price = config.max_entry_price
        self._min_entry_price = config.min_entry_price
        self._tick_size = config.tick_size

        self._mid_history: dict[InstrumentId, deque[float]] = {}
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

        # Track mid history
        if instrument_id not in self._mid_history:
            self._mid_history[instrument_id] = deque(maxlen=self._lookback_periods + 1)
        self._mid_history[instrument_id].append(mid)

        has_position = bool(self.cache.positions_open(instrument_id=instrument_id))

        if has_position:
            self._hold_count[instrument_id] = self._hold_count.get(instrument_id, 0) + 1
            if self._hold_count[instrument_id] >= self._hold_periods:
                self._submit_exit(instrument_id, bid)
        else:
            self._check_entry(instrument_id, ask, mid, spread)

    def _check_entry(
        self,
        instrument_id: InstrumentId,
        ask: float,
        mid: float,
        spread: float,
    ) -> None:
        if spread > self._max_spread or spread <= 0:
            return
        if ask >= self._max_entry_price or ask <= self._min_entry_price:
            return

        history = self._mid_history.get(instrument_id)
        if history is None or len(history) < self._lookback_periods:
            return

        # Check if mid rose by tick_threshold ticks from oldest to newest
        oldest_mid = history[0]
        tick_move = (mid - oldest_mid) / self._tick_size
        if tick_move < self._tick_threshold:
            return

        instrument = self.cache.instrument(instrument_id)
        if instrument is None:
            return
        if self.cache.orders_open(instrument_id=instrument_id):
            return

        order = self.order_factory.limit(
            instrument_id=instrument_id,
            order_side=OrderSide.BUY,
            quantity=instrument.make_qty(self._trade_size),
            price=instrument.make_price(ask),
            time_in_force=TimeInForce.FOK,
        )
        self.submit_order(order)
        self._hold_count[instrument_id] = 0

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
        self._hold_count.pop(instrument_id, None)
        self._closed.discard(instrument_id)
        self._exiting.discard(instrument_id)
        self._round_trips += 1

    @property
    def round_trips(self) -> int:
        return self._round_trips
