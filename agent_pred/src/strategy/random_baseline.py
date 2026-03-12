"""Random baseline strategy — enters randomly, exits after fixed hold period.

Uses base class interval timer for random entry decisions.
No signal logic — pure random with configurable probability.
This is the control: proves framework works regardless of signal quality.
"""

from __future__ import annotations

import random

from nautilus_trader.common.events import TimeEvent
from nautilus_trader.model.data import OrderBookDeltas
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events.position import PositionClosed
from nautilus_trader.model.identifiers import InstrumentId

from strategy.base import PolymarketStrategy, PolymarketStrategyConfig


class RandomBaselineStrategyConfig(PolymarketStrategyConfig, frozen=True):
    trade_size: float = 1.0
    check_interval_minutes: int = 1
    entry_probability: float = 0.3  # Probability of entering each interval
    hold_periods: int = 4  # Fixed hold time in intervals
    max_spread: float = 0.25
    max_entry_price: float = 0.92
    min_entry_price: float = 0.08
    seed: int = 42  # Reproducible randomness


class RandomBaselineStrategy(PolymarketStrategy):
    """Random entry control strategy: enter with probability p, exit after N intervals.

    On each timer tick:
    - If no position: enter with configured probability (coin flip)
    - If holding: exit after hold_periods intervals
    No signal, no prediction — pure random. Proves the framework handles
    any strategy type.
    """

    def __init__(self, config: RandomBaselineStrategyConfig) -> None:
        super().__init__(config)
        self._trade_size = config.trade_size
        self._entry_probability = config.entry_probability
        self._hold_periods = config.hold_periods
        self._max_spread = config.max_spread
        self._max_entry_price = config.max_entry_price
        self._min_entry_price = config.min_entry_price
        self._rng = random.Random(config.seed)

        # Per-instrument state
        self._hold_count: dict[InstrumentId, int] = {}
        self._round_trips: int = 0

    def on_interval(self, event: TimeEvent) -> None:
        for instrument_id in self._instrument_ids:
            if instrument_id in self._exiting or instrument_id in self._closed:
                continue
            self._check_instrument(instrument_id)

    def on_order_book_deltas(self, deltas: OrderBookDeltas) -> None:
        super().on_order_book_deltas(deltas)

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

        has_position = bool(self.cache.positions_open(instrument_id=instrument_id))

        if has_position:
            self._manage_position(instrument_id, bid)
        else:
            self._check_entry(instrument_id, bid, ask, spread)

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

        # Pure random entry decision
        if self._rng.random() >= self._entry_probability:
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

        # Fixed hold period — exit after N intervals
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
        self._hold_count.pop(instrument_id, None)
        self._closed.discard(instrument_id)
        self._exiting.discard(instrument_id)
        self._round_trips += 1

    @property
    def round_trips(self) -> int:
        return self._round_trips
