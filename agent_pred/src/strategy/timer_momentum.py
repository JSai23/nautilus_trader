"""Time-interval momentum strategy that holds positions for minutes.

Uses base class interval timer to check signals at fixed intervals. Holding for
minutes allows price to move enough to produce both wins and losses —
unlike tick-reactive strategies that always lose the spread.
"""

from __future__ import annotations

from nautilus_trader.common.events import TimeEvent
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events.position import PositionClosed
from nautilus_trader.model.identifiers import InstrumentId

from strategy.base import PolymarketStrategy, PolymarketStrategyConfig


class TimerMomentumStrategyConfig(PolymarketStrategyConfig, frozen=True):
    trade_size: float = 1.0
    check_interval_minutes: int = 1  # Check signal every N minutes
    hold_periods: int = 8  # Hold for N intervals before exiting
    max_spread: float = 0.20  # Skip instruments with wider spread
    max_entry_price: float = 0.92  # Don't buy at/above this (ceiling trap)
    min_entry_price: float = 0.08  # Don't buy at/below this (floor trap)


class TimerMomentumStrategy(PolymarketStrategy):
    """Time-based strategy that holds for minutes, producing wins and losses.

    On each timer tick:
    - If no position: buy if mid price moved up since last check (momentum)
    - If holding: exit after hold_periods intervals
    """

    def __init__(self, config: TimerMomentumStrategyConfig) -> None:
        super().__init__(config)
        self._trade_size = config.trade_size
        self._hold_periods = config.hold_periods
        self._max_spread = config.max_spread
        self._max_entry_price = config.max_entry_price
        self._min_entry_price = config.min_entry_price

        # Per-instrument state
        self._prev_mid: dict[InstrumentId, float] = {}
        self._hold_count: dict[InstrumentId, int] = {}
        self._entry_price: dict[InstrumentId, float] = {}
        self._round_trips: int = 0

    def on_interval(self, event: TimeEvent) -> None:
        """Check all instruments on each timer tick."""
        for instrument_id in self._instrument_ids:
            if instrument_id in self._exiting or instrument_id in self._closed:
                continue
            self._check_instrument(instrument_id)

    def _check_instrument(self, instrument_id: InstrumentId) -> None:
        """Check signal and manage position for one instrument."""
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
            self._hold_count[instrument_id] = self._hold_count.get(instrument_id, 0) + 1
            if self._hold_count[instrument_id] >= self._hold_periods:
                self._submit_exit(instrument_id, bid)
        else:
            self._check_entry(instrument_id, bid, ask, mid, spread)

        # Update previous mid for next interval
        self._prev_mid[instrument_id] = mid

    def _check_entry(
        self,
        instrument_id: InstrumentId,
        bid: float,
        ask: float,
        mid: float,
        spread: float,
    ) -> None:
        """Check entry signal and submit buy order."""
        if spread > self._max_spread or spread <= 0:
            return

        if ask >= self._max_entry_price or ask <= self._min_entry_price:
            return

        # Momentum check: only enter if mid moved up since last check
        prev = self._prev_mid.get(instrument_id)
        if prev is None:
            return  # Need baseline from previous interval

        if mid <= prev:
            return  # No upward momentum, skip

        instrument = self.cache.instrument(instrument_id)
        if instrument is None:
            return

        if self.cache.orders_open(instrument_id=instrument_id):
            return

        order = self.order_factory.limit(
            instrument_id=instrument_id,
            order_side=OrderSide.BUY,
            quantity=instrument.make_qty(self._trade_size),
            price=instrument.make_price(ask),  # Aggressive: buy at ask for FOK fill
            time_in_force=TimeInForce.FOK,
        )
        self.submit_order(order)

        self._entry_price[instrument_id] = ask
        self._hold_count[instrument_id] = 0

    def _submit_exit(self, instrument_id: InstrumentId, bid: float) -> None:
        """Submit FOK sell to close position."""
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
        """Re-enable instrument for trading after position closes."""
        instrument_id = event.instrument_id

        self._entry_price.pop(instrument_id, None)
        self._hold_count.pop(instrument_id, None)

        # Clear base class tracking for re-entry
        self._closed.discard(instrument_id)
        self._exiting.discard(instrument_id)

        self._round_trips += 1

    @property
    def round_trips(self) -> int:
        return self._round_trips
