"""Tick-counter stress-test strategy — trades constantly on every subscribed market.

Counts orderbook updates per instrument. After buy_after_ticks updates, buys aggressively
(sweeping multiple price levels). After sell_after_ticks more updates, sells aggressively.
Repeats indefinitely. Produces hundreds of round trips to stress-test order submission,
fill processing, position tracking, PnL calculation, and tearsheet metrics.
"""

from __future__ import annotations

from nautilus_trader.model.data import OrderBookDeltas
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events.order import OrderFilled
from nautilus_trader.model.events.position import PositionClosed
from nautilus_trader.model.identifiers import InstrumentId

from strategy.base import PolymarketStrategy, PolymarketStrategyConfig


class TickStressStrategyConfig(PolymarketStrategyConfig, frozen=True):
    trade_size: float = 5.0
    buy_after_ticks: int = 5  # Buy after N orderbook updates from start/last exit
    sell_after_ticks: int = 30  # Sell after N orderbook updates from buy fill
    sweep_ticks: int = 20  # Place orders N ticks through the book to ensure FOK fills
    max_entry_price: float = 0.95
    min_entry_price: float = 0.05
    log_every_n_ticks: int = 100  # Log periodic updates every N ticks
    tick_size: float = 0.001


class TickStressStrategy(PolymarketStrategy):
    """Stress-test: buy after N ticks, sell after M ticks, repeat forever."""

    def __init__(self, config: TickStressStrategyConfig) -> None:
        super().__init__(config)
        self._trade_size = config.trade_size
        self._buy_after_ticks = config.buy_after_ticks
        self._sell_after_ticks = config.sell_after_ticks
        self._sweep_ticks = config.sweep_ticks
        self._max_entry_price = config.max_entry_price
        self._min_entry_price = config.min_entry_price
        self._log_every_n_ticks = config.log_every_n_ticks
        self._tick_size = config.tick_size

        # Per-instrument state
        self._tick_count: dict[InstrumentId, int] = {}
        self._hold_ticks: dict[InstrumentId, int] = {}
        self._entry_price: dict[InstrumentId, float] = {}

        # Counters for summary logging
        self._total_ticks: int = 0
        self._ticks_per_instrument: dict[InstrumentId, int] = {}
        self._total_buys: int = 0
        self._total_sells: int = 0
        self._round_trips: int = 0
        self._total_pnl: float = 0.0

    def on_start(self) -> None:
        super().on_start()
        # Log which instruments we received
        self.log.info(
            f"TickStress starting: {len(self._instrument_ids)} instruments"
        )
        for iid in self._instrument_ids:
            instrument = self.cache.instrument(iid)
            if instrument:
                self.log.info(
                    f"  Instrument: {iid}, "
                    f"tick_size={instrument.price_increment}, "
                    f"min_qty={instrument.min_quantity}"
                )
            self._tick_count[iid] = 0

    def on_order_book_deltas(self, deltas: OrderBookDeltas) -> None:
        super().on_order_book_deltas(deltas)

        instrument_id = deltas.instrument_id
        if self._data_ended or instrument_id in self._exiting:
            return

        # Count ticks
        self._total_ticks += 1
        self._ticks_per_instrument[instrument_id] = (
            self._ticks_per_instrument.get(instrument_id, 0) + 1
        )

        # Periodic summary
        if self._total_ticks % self._log_every_n_ticks == 0:
            self.log.info(
                f"Tick #{self._total_ticks}: "
                f"buys={self._total_buys}, sells={self._total_sells}, "
                f"round_trips={self._round_trips}, pnl={self._total_pnl:.4f}"
            )

        book = self.cache.order_book(instrument_id)
        if book is None:
            return

        best_bid = book.best_bid_price()
        best_ask = book.best_ask_price()
        if best_bid is None or best_ask is None:
            return

        bid = float(best_bid)
        ask = float(best_ask)

        has_position = bool(
            self.cache.positions_open(instrument_id=instrument_id)
        )
        has_orders = bool(
            self.cache.orders_open(instrument_id=instrument_id)
        )

        if has_position:
            self._manage_hold(instrument_id, bid)
        elif not has_orders:
            self._check_buy(instrument_id, bid, ask)

    def _check_buy(
        self, instrument_id: InstrumentId, bid: float, ask: float
    ) -> None:
        # Price bounds check
        if ask >= self._max_entry_price or ask <= self._min_entry_price:
            return

        self._tick_count[instrument_id] = (
            self._tick_count.get(instrument_id, 0) + 1
        )

        if self._tick_count[instrument_id] < self._buy_after_ticks:
            return

        instrument = self.cache.instrument(instrument_id)
        if instrument is None:
            return

        # Sweep: place limit above ask to fill against multiple price levels
        sweep_price = min(ask + self._sweep_ticks * self._tick_size, 0.999)

        self.log.info(
            f"BUY {instrument_id}: ask={ask:.4f}, bid={bid:.4f}, "
            f"sweep={sweep_price:.4f}, spread={ask - bid:.4f}, "
            f"ticks_waited={self._tick_count[instrument_id]}"
        )

        order = self.order_factory.limit(
            instrument_id=instrument_id,
            order_side=OrderSide.BUY,
            quantity=instrument.make_qty(self._trade_size),
            price=instrument.make_price(sweep_price),
            time_in_force=TimeInForce.FOK,
        )
        self.submit_order(order)
        self._entry_price[instrument_id] = ask  # Track actual ask, not sweep price
        self._hold_ticks[instrument_id] = 0
        self._tick_count[instrument_id] = 0
        self._total_buys += 1

    def _manage_hold(self, instrument_id: InstrumentId, bid: float) -> None:
        self._hold_ticks[instrument_id] = (
            self._hold_ticks.get(instrument_id, 0) + 1
        )

        if self._hold_ticks[instrument_id] < self._sell_after_ticks:
            return

        # Time to sell
        self._submit_exit(instrument_id, bid)

    def _submit_exit(self, instrument_id: InstrumentId, bid: float) -> None:
        positions = self.cache.positions_open(instrument_id=instrument_id)
        if not positions:
            return

        position = positions[0]
        instrument = self.cache.instrument(instrument_id)
        if instrument is None:
            return

        entry = self._entry_price.get(instrument_id, 0.0)
        pnl_est = (bid - entry) * self._trade_size

        self.log.info(
            f"SELL {instrument_id}: bid={bid:.4f}, "
            f"entry={entry:.4f}, est_pnl={pnl_est:.4f}, "
            f"hold_ticks={self._hold_ticks.get(instrument_id, 0)}"
        )

        self.cancel_all_orders(instrument_id)

        # Sweep: place limit below bid to fill against multiple price levels
        sweep_price = max(bid - self._sweep_ticks * self._tick_size, 0.001)

        qty = instrument.make_qty(abs(float(position.quantity)))
        order = self.order_factory.limit(
            instrument_id=instrument_id,
            order_side=OrderSide.SELL,
            quantity=qty,
            price=instrument.make_price(sweep_price),
            time_in_force=TimeInForce.FOK,
        )
        self.submit_order(order)
        self._total_sells += 1

    def on_order_filled(self, event: OrderFilled) -> None:
        self.log.info(
            f"FILL {event.instrument_id}: "
            f"side={event.order_side.name}, "
            f"price={float(event.last_px):.4f}, "
            f"qty={float(event.last_qty)}"
        )

    def on_position_closed(self, event: PositionClosed) -> None:
        instrument_id = event.instrument_id

        # Calculate actual PnL from the position
        realized = float(event.realized_pnl) if hasattr(event, "realized_pnl") else 0.0
        entry = self._entry_price.get(instrument_id, 0.0)
        hold = self._hold_ticks.get(instrument_id, 0)

        self._round_trips += 1
        self._total_pnl += realized

        self.log.info(
            f"RT#{self._round_trips} {instrument_id}: "
            f"entry={entry:.4f}, hold_ticks={hold}, "
            f"realized_pnl={realized:.4f}, cumulative_pnl={self._total_pnl:.4f}"
        )

        # Reset for next round
        self._entry_price.pop(instrument_id, None)
        self._hold_ticks.pop(instrument_id, None)
        self._tick_count[instrument_id] = 0
        self._closed.discard(instrument_id)
        self._exiting.discard(instrument_id)

    def on_stop(self) -> None:
        # Final summary
        self.log.info("=" * 60)
        self.log.info("TICK STRESS TEST SUMMARY")
        self.log.info("=" * 60)
        self.log.info(f"Total ticks processed: {self._total_ticks}")
        self.log.info(f"Total buys submitted:  {self._total_buys}")
        self.log.info(f"Total sells submitted: {self._total_sells}")
        self.log.info(f"Total round trips:     {self._round_trips}")
        self.log.info(f"Cumulative PnL:        {self._total_pnl:.4f}")
        self.log.info(f"Instruments traded:    {len(self._ticks_per_instrument)}")
        for iid, count in sorted(
            self._ticks_per_instrument.items(),
            key=lambda x: x[1],
            reverse=True,
        ):
            self.log.info(f"  {iid}: {count} ticks")
        self.log.info("=" * 60)

    @property
    def round_trips(self) -> int:
        return self._round_trips
