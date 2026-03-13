"""PolymarketStrategy base class with safe exit defaults.

Per IMPL_PLAN Block 4:
- Limit-order FOK exit (close_position is broken on Polymarket)
- Resolution timer from instrument.expiration_ns
- Price convergence detection
- Configurable take-profit / stop-loss

Dynamic instrument support:
- When dynamic_instruments=True (paper/live mode), subscribes to
  instrument updates from MarketDiscoveryActor
- on_instrument() subscribes to orderbook data for newly discovered markets
- on_new_instrument() hook for subclass-specific handling
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from nautilus_trader.common.events import TimeEvent
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import OrderBookDelta, OrderBookDeltas
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId, Venue
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.trading.strategy import Strategy

INTERVAL_TIMER_NAME = "polymarket_interval"


POLYMARKET_VENUE = Venue("POLYMARKET")


class PolymarketStrategyConfig(StrategyConfig, frozen=True):
    instrument_ids: list[str] = []
    check_interval_minutes: int = 0  # >0 enables recurring on_interval() timer
    exit_before_resolution_secs: int = 300
    convergence_threshold: float = 0.95
    take_profit: float | None = None
    stop_loss: float | None = None
    start_time_ns: int = 0  # Start of data window (ns epoch). Safety bound for timers.
    end_time_ns: int = 0  # End of data window (ns epoch). Triggers exit 60s before.
    dynamic_instruments: bool = False  # Enable for paper/live: subscribe to new instruments


class PolymarketStrategy(Strategy):
    """Base strategy for Polymarket prediction markets.

    Handles:
    - Order book subscription on start
    - Exit lifecycle (resolution timer, convergence, take-profit, stop-loss)
    """

    def __init__(self, config: PolymarketStrategyConfig) -> None:
        super().__init__(config)
        self._instrument_ids: list[InstrumentId] = [
            InstrumentId.from_str(iid) for iid in config.instrument_ids
        ]
        self._check_interval_minutes = config.check_interval_minutes
        self._exit_before_resolution_secs = config.exit_before_resolution_secs
        self._convergence_threshold = config.convergence_threshold
        self._take_profit = config.take_profit
        self._stop_loss = config.stop_loss

        self._start_time_ns = config.start_time_ns
        self._end_time_ns = config.end_time_ns
        self._dynamic_instruments = config.dynamic_instruments

        self._data_ended = False  # Set when end-of-data exit fires; blocks new entries
        self._exiting: set[InstrumentId] = set()
        self._closed: set[InstrumentId] = set()
        self._subscribed_ids: set[InstrumentId] = set()  # Track all subscribed instruments

    def on_start(self) -> None:
        # Subscribe to instrument updates so on_instrument() fires
        # for dynamically discovered markets
        if self._dynamic_instruments:
            self.subscribe_instruments(POLYMARKET_VENUE)

        for instrument_id in self._instrument_ids:
            self._subscribe_instrument(instrument_id)

        # End-of-data exit: close all positions 60s before data window ends.
        # Prevents positions from reaching resolution timer with stale book prices.
        if self._end_time_ns > 0:
            exit_ns = self._end_time_ns - 60_000_000_000  # 60s before
            if exit_ns > 0:
                self.clock.set_time_alert_ns(
                    name="end_of_data_exit",
                    alert_time_ns=exit_ns,
                )

        # Recurring interval timer for subclass on_interval() callbacks.
        # start_time_ns bounds the timer so it won't fire before data starts.
        # Without it, add_data_iterator() causes engine.run() to default
        # start_ns=0 (epoch), creating millions of empty timer ticks.
        if self._check_interval_minutes > 0:
            if self._start_time_ns == 0:
                self.log.warning(
                    "check_interval_minutes=%d but start_time_ns=0 — "
                    "timer will fire from engine clock start. "
                    "Set start_time_ns via run_backtest() or engine config.",
                    self._check_interval_minutes,
                )
            timer_kwargs: dict[str, Any] = {
                "name": INTERVAL_TIMER_NAME,
                "interval": pd.Timedelta(minutes=self._check_interval_minutes),
                "callback": self._on_interval_event,
            }
            if self._start_time_ns > 0:
                timer_kwargs["start_time"] = pd.Timestamp(
                    self._start_time_ns, unit="ns", tz="UTC"
                )
            if self._end_time_ns > 0:
                timer_kwargs["stop_time"] = pd.Timestamp(
                    self._end_time_ns, unit="ns", tz="UTC"
                )
            self.clock.set_timer(**timer_kwargs)

    def _subscribe_instrument(self, instrument_id: InstrumentId) -> None:
        """Subscribe to orderbook data and set up exit timers for an instrument."""
        if instrument_id in self._subscribed_ids:
            return
        self._subscribed_ids.add(instrument_id)

        self.subscribe_order_book_deltas(instrument_id)
        instrument = self.cache.instrument(instrument_id)
        if instrument and hasattr(instrument, "expiration_ns") and instrument.expiration_ns > 0:
            lead_ns = self._exit_before_resolution_secs * 1_000_000_000
            alert_ns = instrument.expiration_ns - lead_ns
            if alert_ns > self.clock.timestamp_ns():
                self.clock.set_time_alert_ns(
                    name=f"resolution_{instrument_id}",
                    alert_time_ns=alert_ns,
                )

    def on_instrument(self, instrument: Instrument) -> None:
        """Handle new instrument from MarketDiscoveryActor.

        When dynamic_instruments is enabled, automatically subscribes to
        orderbook data for newly discovered instruments and calls
        on_new_instrument() for subclass-specific handling.
        """
        if not self._dynamic_instruments:
            return
        if instrument.id in self._subscribed_ids:
            return
        if instrument.id.venue != POLYMARKET_VENUE:
            return

        self.log.info(f"Dynamic instrument discovered: {instrument.id}")
        self._instrument_ids.append(instrument.id)
        self._subscribe_instrument(instrument.id)
        self.on_new_instrument(instrument)

    def on_new_instrument(self, instrument: Instrument) -> None:
        """Called when a new instrument is dynamically discovered. Override in subclasses."""

    def _on_interval_event(self, event: TimeEvent) -> None:
        """Dispatch interval timer events to subclass on_interval()."""
        if not self._data_ended:
            self.on_interval(event)

    def on_interval(self, event: TimeEvent) -> None:
        """Called on each interval timer tick. Override in subclasses."""

    def on_order_book_deltas(self, deltas: OrderBookDeltas) -> None:
        instrument_id = deltas.instrument_id
        if instrument_id in self._closed:
            return
        self._check_exit_conditions(instrument_id)

    def on_order_book_delta(self, delta: OrderBookDelta) -> None:
        instrument_id = delta.instrument_id
        if instrument_id in self._closed:
            return
        self._check_exit_conditions(instrument_id)

    def on_event(self, event: Any) -> None:
        if not (hasattr(event, "name") and isinstance(event.name, str)):
            return

        if event.name.startswith("resolution_"):
            iid_str = event.name[len("resolution_"):]
            instrument_id = InstrumentId.from_str(iid_str)
            self._trigger_exit(instrument_id, reason="resolution_timer")
        elif event.name == "end_of_data_exit":
            self._exit_all_open(reason="end_of_data")

    def _check_exit_conditions(self, instrument_id: InstrumentId) -> None:
        if instrument_id in self._exiting or instrument_id in self._closed:
            return

        book = self.cache.order_book(instrument_id)
        if book is None:
            return

        # Price convergence check
        best_bid = book.best_bid_price()
        best_ask = book.best_ask_price()
        if best_bid is not None and best_ask is not None:
            mid = (float(best_bid) + float(best_ask)) / 2.0
            if mid > self._convergence_threshold or mid < (1.0 - self._convergence_threshold):
                self._trigger_exit(instrument_id, reason="convergence")
                return

        # Take-profit / stop-loss (skip entirely when both are disabled)
        if self._take_profit is not None or self._stop_loss is not None:
            open_positions = self.cache.positions_open(instrument_id=instrument_id)
            position = open_positions[0] if open_positions else None
            if position:
                price = best_bid if position.is_long else best_ask
                if price is None:
                    return
                unrealized = float(position.unrealized_pnl(price))
                if self._take_profit is not None and unrealized > self._take_profit:
                    self._trigger_exit(instrument_id, reason="take_profit")
                elif self._stop_loss is not None and unrealized < self._stop_loss:
                    self._trigger_exit(instrument_id, reason="stop_loss")

    def _exit_all_open(self, reason: str) -> None:
        """Exit all open positions across all instruments."""
        self._data_ended = True
        for instrument_id in self._instrument_ids:
            if instrument_id in self._closed or instrument_id in self._exiting:
                continue
            if self.cache.positions_open(instrument_id=instrument_id):
                self._trigger_exit(instrument_id, reason=reason)

    def _trigger_exit(self, instrument_id: InstrumentId, reason: str) -> None:
        if instrument_id in self._exiting or instrument_id in self._closed:
            return

        self._exiting.add(instrument_id)
        self.log.info(f"Exit triggered for {instrument_id}: {reason}")

        # Cancel all open orders for this instrument
        self.cancel_all_orders(instrument_id)

        open_positions = self.cache.positions_open(instrument_id=instrument_id)
        position = open_positions[0] if open_positions else None
        if position is None:
            self._closed.add(instrument_id)
            self._exiting.discard(instrument_id)
            return

        book = self.cache.order_book(instrument_id)
        if book is None:
            self._exiting.discard(instrument_id)
            return

        instrument = self.cache.instrument(instrument_id)
        if instrument is None:
            return

        # Determine exit side and price
        if position.is_long:
            side = OrderSide.SELL
            price = book.best_bid_price()
        else:
            side = OrderSide.BUY
            price = book.best_ask_price()

        if price is None:
            self._exiting.discard(instrument_id)
            return

        qty = instrument.make_qty(abs(float(position.quantity)))

        order = self.order_factory.limit(
            instrument_id=instrument_id,
            order_side=side,
            quantity=qty,
            price=price,
            time_in_force=TimeInForce.FOK,
        )
        self.submit_order(order)
