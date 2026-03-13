"""Spread scalper strategy — enters when spread tightens, exits when it widens.

Uses base class interval timer for spread monitoring. Tracks rolling
spread average and enters when current spread is below threshold, exiting
when spread widens or after a fixed hold period.
"""

from __future__ import annotations

from collections import deque

from nautilus_trader.common.events import TimeEvent
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events.position import PositionClosed
from nautilus_trader.model.identifiers import InstrumentId

from strategy.base import PolymarketStrategy, PolymarketStrategyConfig


class SpreadScalperStrategyConfig(PolymarketStrategyConfig, frozen=True):
    trade_size: float = 1.0
    check_interval_minutes: int = 1
    spread_lookback: int = 10  # Rolling window for spread average
    tight_spread_ratio: float = 0.6  # Enter when spread < ratio * avg_spread
    wide_spread_ratio: float = 1.4  # Exit when spread > ratio * avg_spread
    hold_periods: int = 5  # Max hold time in intervals
    max_spread: float = 0.15  # Absolute max spread to consider
    max_entry_price: float = 0.92
    min_entry_price: float = 0.08


class SpreadScalperStrategy(PolymarketStrategy):
    """Timer-based spread scalper: enter on tight spreads, exit on widening.

    On each timer tick:
    - Updates rolling spread window
    - If no position: buy when spread tightens below threshold
    - If holding: exit when spread widens or hold period expires
    """

    def __init__(self, config: SpreadScalperStrategyConfig) -> None:
        super().__init__(config)
        self._trade_size = config.trade_size
        self._spread_lookback = config.spread_lookback
        self._tight_spread_ratio = config.tight_spread_ratio
        self._wide_spread_ratio = config.wide_spread_ratio
        self._hold_periods = config.hold_periods
        self._max_spread = config.max_spread
        self._max_entry_price = config.max_entry_price
        self._min_entry_price = config.min_entry_price

        # Per-instrument state
        self._spread_history: dict[InstrumentId, deque[float]] = {}
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

        if spread <= 0:
            return

        # Update rolling spread window
        if instrument_id not in self._spread_history:
            self._spread_history[instrument_id] = deque(maxlen=self._spread_lookback)
        self._spread_history[instrument_id].append(spread)

        has_position = bool(self.cache.positions_open(instrument_id=instrument_id))

        if has_position:
            self._manage_position(instrument_id, bid, spread)
        else:
            self._check_entry(instrument_id, bid, ask, spread)

    def _check_entry(
        self,
        instrument_id: InstrumentId,
        bid: float,
        ask: float,
        spread: float,
    ) -> None:
        if spread > self._max_spread:
            return
        if ask >= self._max_entry_price or ask <= self._min_entry_price:
            return

        history = self._spread_history.get(instrument_id)
        if history is None or len(history) < 3:
            return

        avg_spread = sum(history) / len(history)

        # Enter when spread is tighter than average (liquidity improving)
        if spread < avg_spread * self._tight_spread_ratio:
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
        spread: float,
    ) -> None:
        self._hold_count[instrument_id] = self._hold_count.get(instrument_id, 0) + 1

        history = self._spread_history.get(instrument_id)
        avg_spread = sum(history) / len(history) if history else spread

        should_exit = False

        # Exit when spread widens (liquidity deteriorating)
        if spread > avg_spread * self._wide_spread_ratio:
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
