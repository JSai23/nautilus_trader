"""PolymarketStrategy base class with safe exit defaults.

Per IMPL_PLAN Block 4:
- Limit-order FOK exit (close_position is broken on Polymarket)
- Resolution timer from instrument.expiration_ns
- Price convergence detection
- Configurable take-profit / stop-loss
- HeldThrough tracking for failed exits
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import OrderBookDelta, OrderBookDeltas
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.trading.strategy import Strategy


class PolymarketStrategyConfig(StrategyConfig, frozen=True):
    instrument_ids: list[str] = []
    exit_before_resolution_secs: int = 300
    convergence_threshold: float = 0.95
    max_exit_retries: int = 3
    take_profit: float | None = None
    stop_loss: float | None = None


class PolymarketStrategy(Strategy):
    """Base strategy for Polymarket prediction markets.

    Handles:
    - Order book subscription on start
    - Exit lifecycle (resolution timer, convergence, take-profit, stop-loss)
    - HeldThrough tracking for failed exits
    """

    def __init__(self, config: PolymarketStrategyConfig) -> None:
        super().__init__(config)
        self._instrument_ids: list[InstrumentId] = [
            InstrumentId.from_str(iid) for iid in config.instrument_ids
        ]
        self._exit_before_resolution_secs = config.exit_before_resolution_secs
        self._convergence_threshold = config.convergence_threshold
        self._max_exit_retries = config.max_exit_retries
        self._take_profit = config.take_profit
        self._stop_loss = config.stop_loss

        self._exiting: set[InstrumentId] = set()
        self._closed: set[InstrumentId] = set()
        self._held_through: dict[InstrumentId, bool] = {}

    def on_start(self) -> None:
        for instrument_id in self._instrument_ids:
            self.subscribe_order_book_deltas(instrument_id)
            instrument = self.cache.instrument(instrument_id)
            if instrument and hasattr(instrument, "expiration_ns") and instrument.expiration_ns > 0:
                lead_ns = self._exit_before_resolution_secs * 1_000_000_000
                alert_ns = instrument.expiration_ns - lead_ns
                if alert_ns > 0:
                    self.clock.set_time_alert_ns(
                        name=f"resolution_{instrument_id}",
                        alert_time_ns=alert_ns,
                    )

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
        # Handle resolution timer alerts
        if hasattr(event, "name") and isinstance(event.name, str) and event.name.startswith("resolution_"):
            iid_str = event.name[len("resolution_"):]
            instrument_id = InstrumentId.from_str(iid_str)
            self._trigger_exit(instrument_id, reason="resolution_timer")

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

        # Take-profit / stop-loss
        open_positions = self.cache.positions_open(instrument_id=instrument_id)
        position = open_positions[0] if open_positions else None
        if position:
            unrealized = float(position.unrealized_pnl(best_bid if position.is_long else best_ask))
            if self._take_profit and unrealized > self._take_profit:
                self._trigger_exit(instrument_id, reason="take_profit")
            elif self._stop_loss and unrealized < self._stop_loss:
                self._trigger_exit(instrument_id, reason="stop_loss")

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

        self._attempt_exit(instrument_id, attempt=0)

    def _attempt_exit(self, instrument_id: InstrumentId, attempt: int) -> None:
        if attempt >= self._max_exit_retries:
            self.log.warning(
                f"HeldThrough: {instrument_id}, failed_exits={attempt}"
            )
            self._held_through[instrument_id] = True
            self._exiting.discard(instrument_id)
            return

        open_positions = self.cache.positions_open(instrument_id=instrument_id)
        position = open_positions[0] if open_positions else None
        if position is None:
            self._closed.add(instrument_id)
            self._exiting.discard(instrument_id)
            return

        book = self.cache.order_book(instrument_id)
        if book is None:
            self._held_through[instrument_id] = True
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
            self._held_through[instrument_id] = True
            self._exiting.discard(instrument_id)
            return

        # Worsen price by attempt * tick_size
        if attempt > 0:
            tick = float(instrument.price_increment)
            if side == OrderSide.SELL:
                price = instrument.make_price(float(price) - tick * attempt)
            else:
                price = instrument.make_price(float(price) + tick * attempt)

        qty = instrument.make_qty(abs(float(position.quantity)))

        order = self.order_factory.limit(
            instrument_id=instrument_id,
            order_side=side,
            quantity=qty,
            price=price,
            time_in_force=TimeInForce.FOK,
        )
        self.submit_order(order)

    @property
    def held_through_instruments(self) -> list[InstrumentId]:
        return [iid for iid, held in self._held_through.items() if held]
