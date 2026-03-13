"""Contrarian strategy — buy when price drops significantly, bet on rebound.

If mid-price dropped by more than a percentage threshold over the lookback
window, buy the dip. Hold for a fixed number of intervals then exit.
"""

from __future__ import annotations

from collections import deque

from nautilus_trader.common.events import TimeEvent
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events.position import PositionClosed
from nautilus_trader.model.identifiers import InstrumentId

from strategy.base import PolymarketStrategy, PolymarketStrategyConfig


class ContrarianStrategyConfig(PolymarketStrategyConfig, frozen=True):
    trade_size: float = 1.0
    check_interval_minutes: int = 1
    drop_threshold_pct: float = 0.02  # Buy when price dropped >2% from peak
    lookback_periods: int = 15  # Window to measure drop (in intervals)
    hold_periods: int = 30  # Hold for N intervals then exit
    max_spread: float = 0.15
    max_entry_price: float = 0.92
    min_entry_price: float = 0.08


class ContrarianStrategy(PolymarketStrategy):
    """Buy dips, hold for recovery.

    On each interval:
    - Track mid prices over lookback window
    - If no position and mid dropped >threshold from window max, buy
    - If holding, exit after hold_periods intervals
    """

    def __init__(self, config: ContrarianStrategyConfig) -> None:
        super().__init__(config)
        self._trade_size = config.trade_size
        self._drop_threshold_pct = config.drop_threshold_pct
        self._lookback_periods = config.lookback_periods
        self._hold_periods = config.hold_periods
        self._max_spread = config.max_spread
        self._max_entry_price = config.max_entry_price
        self._min_entry_price = config.min_entry_price

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

        # Check if price dropped from peak by threshold
        window_max = max(history)
        if window_max <= 0:
            return

        drop_pct = (window_max - mid) / window_max
        if drop_pct < self._drop_threshold_pct:
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
