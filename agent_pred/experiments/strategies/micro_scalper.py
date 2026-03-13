"""Micro scalper strategy — high-frequency mean reversion on orderbook updates.

Designed to generate many trades by:
- Trading every instrument independently (no per-market restriction)
- Using bid-vs-entry profit targets (exit only when bid > entry ask)
- Re-entering immediately after exits
- Exiting on time (update count) if price doesn't move

This is a stress-test strategy — volume over profitability.
"""

from __future__ import annotations

from nautilus_trader.model.data import OrderBookDeltas
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events.position import PositionClosed
from nautilus_trader.model.identifiers import InstrumentId

from strategy.base import PolymarketStrategy, PolymarketStrategyConfig


class MicroScalperStrategyConfig(PolymarketStrategyConfig, frozen=True):
    trade_size: float = 5.0
    max_spread: float = 0.30  # Only enter when spread <= this (filters illiquid books)
    ema_alpha: float = 0.3  # EMA smoothing for mid price (higher = more responsive)
    entry_dip_ticks: int = 1  # Enter when mid is N ticks below EMA
    max_hold_updates: int = 50  # Force exit after N orderbook updates
    cooldown_updates: int = 5  # Wait N updates after exit before re-entering
    tick_size: float = 0.01  # Polymarket tick size
    max_entry_price: float = 0.95  # Don't buy at/above this (price ceiling)
    min_entry_price: float = 0.05  # Don't buy at/below this (price floor)


class MicroScalperStrategy(PolymarketStrategy):
    """High-frequency mean reversion scalper for stress testing.

    Trades every instrument independently, enters on micro dips below
    a fast EMA, and exits when the current bid exceeds the entry ask
    (guaranteed profit) or on a time stop. Configurable ceiling/floor
    filters avoid trading at price extremes.
    """

    def __init__(self, config: MicroScalperStrategyConfig) -> None:
        super().__init__(config)
        self._trade_size = config.trade_size
        self._max_spread = config.max_spread
        self._ema_alpha = config.ema_alpha
        self._entry_dip_ticks = config.entry_dip_ticks
        self._max_hold_updates = config.max_hold_updates
        self._cooldown_updates = config.cooldown_updates
        self._tick_size = config.tick_size
        self._max_entry_price = config.max_entry_price
        self._min_entry_price = config.min_entry_price

        # Per-instrument state
        self._ema_mid: dict[InstrumentId, float] = {}
        self._entry_price: dict[InstrumentId, float] = {}  # ask at entry
        self._hold_count: dict[InstrumentId, int] = {}
        self._cooldown_remaining: dict[InstrumentId, int] = {}
        self._round_trips: int = 0

    def on_order_book_deltas(self, deltas: OrderBookDeltas) -> None:
        # Let base class handle exit conditions (convergence, end-of-data)
        super().on_order_book_deltas(deltas)

        instrument_id = deltas.instrument_id
        if self._data_ended:
            return

        # Skip if currently in exit process (base class is handling it)
        if instrument_id in self._exiting:
            return

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

        # Update EMA
        if instrument_id not in self._ema_mid:
            self._ema_mid[instrument_id] = mid
        else:
            self._ema_mid[instrument_id] = (
                self._ema_alpha * mid
                + (1 - self._ema_alpha) * self._ema_mid[instrument_id]
            )

        # Handle cooldown
        if instrument_id in self._cooldown_remaining:
            self._cooldown_remaining[instrument_id] -= 1
            if self._cooldown_remaining[instrument_id] <= 0:
                del self._cooldown_remaining[instrument_id]
            else:
                return

        has_position = bool(self.cache.positions_open(instrument_id=instrument_id))
        has_orders = bool(self.cache.orders_open(instrument_id=instrument_id))

        if has_position:
            self._manage_position(instrument_id, bid, ask, mid)
        elif not has_orders:
            self._check_entry(instrument_id, bid, ask, mid, spread)

    def _check_entry(
        self,
        instrument_id: InstrumentId,
        bid: float,
        ask: float,
        mid: float,
        spread: float,
    ) -> None:
        """Check for entry signal and submit order."""
        # Filter: spread too wide → illiquid, skip
        if spread > self._max_spread:
            return

        # Filter: price ceiling/floor — no room for price movement
        if ask >= self._max_entry_price or ask <= self._min_entry_price:
            return

        ema = self._ema_mid.get(instrument_id, mid)
        dip_threshold = ema - self._entry_dip_ticks * self._tick_size

        # Enter when mid dips below EMA by entry_dip_ticks
        if mid <= dip_threshold:
            instrument = self.cache.instrument(instrument_id)
            if instrument is None:
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

    def _manage_position(
        self,
        instrument_id: InstrumentId,
        bid: float,
        ask: float,
        mid: float,
    ) -> None:
        """Check exit conditions for an open position."""
        self._hold_count[instrument_id] = self._hold_count.get(instrument_id, 0) + 1

        entry_ask = self._entry_price.get(instrument_id)
        if entry_ask is None:
            return

        should_exit = False
        reason = ""

        # Take profit: only exit when bid > entry ask (guarantees actual profit).
        # With FOK execution, bid is the exit price. bid > entry_ask means
        # the sell price exceeds the buy price → real profit.
        if bid > entry_ask:
            should_exit = True
            reason = "take_profit"

        # Time stop: held too many updates without profit
        elif self._hold_count[instrument_id] >= self._max_hold_updates:
            should_exit = True
            reason = "time_stop"

        if should_exit:
            self._submit_exit(instrument_id, bid, reason)

    def _submit_exit(
        self,
        instrument_id: InstrumentId,
        bid: float,
        reason: str,
    ) -> None:
        """Submit a FOK sell to close the position."""
        positions = self.cache.positions_open(instrument_id=instrument_id)
        if not positions:
            return

        position = positions[0]
        instrument = self.cache.instrument(instrument_id)
        if instrument is None:
            return

        self.log.info(f"Scalper exit {instrument_id}: {reason}")

        # Cancel any open orders first
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

        # Clean up tracking state
        self._entry_price.pop(instrument_id, None)
        self._hold_count.pop(instrument_id, None)

        # Remove from base class closed/exiting sets to allow re-entry
        self._closed.discard(instrument_id)
        self._exiting.discard(instrument_id)

        # Start cooldown
        self._cooldown_remaining[instrument_id] = self._cooldown_updates

        self._round_trips += 1
        self.log.info(
            f"Position closed {instrument_id}, "
            f"round_trips={self._round_trips}, cooldown={self._cooldown_updates}"
        )

    @property
    def round_trips(self) -> int:
        return self._round_trips
