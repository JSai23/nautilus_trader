"""Momentum breakout strategy — enters on sustained directional movement.

Uses base class interval timer for checks. Tracks consecutive
up/down moves over last N intervals and enters on breakout (sustained
direction), exiting on reversal or after a hold period.
"""

from __future__ import annotations

from collections import deque

from nautilus_trader.common.events import TimeEvent
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events.position import PositionClosed
from nautilus_trader.model.identifiers import InstrumentId

from strategy.base import PolymarketStrategy, PolymarketStrategyConfig


class MomentumBreakoutStrategyConfig(PolymarketStrategyConfig, frozen=True):
    trade_size: float = 1.0
    check_interval_minutes: int = 1
    breakout_periods: int = 3  # Consecutive up-moves to trigger entry
    hold_periods: int = 6  # Max hold time in intervals
    reversal_periods: int = 2  # Consecutive down-moves to trigger exit
    max_spread: float = 0.20
    max_entry_price: float = 0.92
    min_entry_price: float = 0.08


class MomentumBreakoutStrategy(PolymarketStrategy):
    """Timer-based momentum: enter on N consecutive up-moves, exit on reversal.

    On each timer tick:
    - Records price direction (up/down vs previous tick)
    - If no position: buy after breakout_periods consecutive up-moves
    - If holding: exit after reversal_periods consecutive down-moves or hold timeout
    """

    def __init__(self, config: MomentumBreakoutStrategyConfig) -> None:
        super().__init__(config)
        self._trade_size = config.trade_size
        self._breakout_periods = config.breakout_periods
        self._hold_periods = config.hold_periods
        self._reversal_periods = config.reversal_periods
        self._max_spread = config.max_spread
        self._max_entry_price = config.max_entry_price
        self._min_entry_price = config.min_entry_price

        # Per-instrument state
        self._prev_mid: dict[InstrumentId, float] = {}
        self._direction_history: dict[InstrumentId, deque[int]] = {}  # +1 up, -1 down
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

        # Track direction
        prev = self._prev_mid.get(instrument_id)
        self._prev_mid[instrument_id] = mid

        if prev is not None:
            direction = 1 if mid > prev else -1
            if instrument_id not in self._direction_history:
                self._direction_history[instrument_id] = deque(
                    maxlen=max(self._breakout_periods, self._reversal_periods)
                )
            self._direction_history[instrument_id].append(direction)

        has_position = bool(self.cache.positions_open(instrument_id=instrument_id))

        if has_position:
            self._manage_position(instrument_id, bid)
        else:
            self._check_entry(instrument_id, bid, ask, spread)

    def _consecutive_direction(self, instrument_id: InstrumentId, direction: int) -> int:
        """Count consecutive moves in given direction from the end of history."""
        history = self._direction_history.get(instrument_id)
        if not history:
            return 0
        count = 0
        for d in reversed(history):
            if d == direction:
                count += 1
            else:
                break
        return count

    def _check_entry(
        self,
        instrument_id: InstrumentId,
        bid: float,
        ask: float,
        spread: float,
    ) -> None:
        if spread > self._max_spread or spread <= 0:
            return
        if ask >= self._max_entry_price or ask <= self._min_entry_price:
            return

        # Enter on sustained upward momentum (breakout)
        up_count = self._consecutive_direction(instrument_id, 1)
        if up_count < self._breakout_periods:
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

    def _manage_position(
        self,
        instrument_id: InstrumentId,
        bid: float,
    ) -> None:
        self._hold_count[instrument_id] = self._hold_count.get(instrument_id, 0) + 1

        should_exit = False

        # Exit on reversal (consecutive down-moves)
        down_count = self._consecutive_direction(instrument_id, -1)
        if down_count >= self._reversal_periods:
            should_exit = True

        # Time stop
        if self._hold_count[instrument_id] >= self._hold_periods:
            should_exit = True

        if should_exit:
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
        self._hold_count.pop(instrument_id, None)
        self._closed.discard(instrument_id)
        self._exiting.discard(instrument_id)
        self._round_trips += 1

    @property
    def round_trips(self) -> int:
        return self._round_trips
