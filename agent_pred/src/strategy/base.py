"""PolymarketStrategy base class with safe exit defaults.

Exit lifecycle:
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

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from nautilus_trader.common.events import TimeEvent
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import OrderBookDelta, OrderBookDeltas
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events.order import OrderFilled, OrderCanceled, OrderRejected
from nautilus_trader.model.identifiers import InstrumentId, Venue
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.trading.strategy import Strategy

INTERVAL_TIMER_NAME = "polymarket_interval"


POLYMARKET_VENUE = Venue("POLYMARKET")


@dataclass(frozen=True)
class MarketMeta:
    """Metadata for a Polymarket instrument."""

    slug: str
    condition_id: str
    token_id: str
    outcome: str  # "Yes" or "No"
    question: str
    start_date: str  # ISO date or ""
    end_date: str  # ISO date or ""

    @property
    def label(self) -> str:
        """Human-readable label: slug + truncated condition_id."""
        return f"{self.slug} ({self.condition_id[:10]}...)"

    def slug_timestamp(self) -> int | None:
        """Parse Unix timestamp from btc-updown-15m slug, or None."""
        match = re.search(r"-(\d{10})$", self.slug)
        return int(match.group(1)) if match else None

    def is_active_at(self, ts: float) -> bool:
        """Check if this btc-updown-15m market's 15-min window contains ts (unix seconds)."""
        slug_ts = self.slug_timestamp()
        if slug_ts is None:
            return False
        return slug_ts <= ts < slug_ts + 900  # 15 minutes


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
    record_top_of_book: bool = False  # Enable top-of-book BBO recording (Block 6)


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
        self._exit_retries: dict[InstrumentId, int] = {}  # FOK exit failure counter
        self._pending_exit_retry: set[InstrumentId] = set()  # Retry on next interval
        self._subscribed_ids: set[InstrumentId] = set()  # Track all subscribed instruments

        # Market metadata map (Block 1)
        self._market_meta: dict[InstrumentId, MarketMeta] = {}

        # Order tracking counters (Block 3)
        self._orders_submitted: int = 0
        self._orders_filled: int = 0
        self._orders_canceled: int = 0
        self._orders_rejected: int = 0
        self._tick_count_total: int = 0
        self._interval_count: int = 0

        # Top-of-book BBO recording (Block 6)
        self._record_tob = config.record_top_of_book
        self._tob_records: list[dict] = []

        # Fill records — in-strategy tracking to avoid cache eviction loss
        self._fill_records: list[dict] = []

        # Heartbeat (Block 5) — engine injects _heartbeat_dir before run
        self._heartbeat_dir: Path | None = None
        self._heartbeat_run_id: str = ""
        self._heartbeat_start_time: float = 0.0

    def on_start(self) -> None:
        # For dynamic instruments, set up a periodic cache poll to detect
        # new instruments from the MarketDiscoveryActor. The Polymarket data
        # client does not implement _subscribe_instruments, so we poll instead.
        if self._dynamic_instruments:
            self.clock.set_timer(
                name="instrument_discovery_check",
                interval=pd.Timedelta(seconds=10),
                callback=self._on_instrument_check,
            )

        for instrument_id in self._instrument_ids:
            self._subscribe_instrument(instrument_id)
            self._hydrate_market_meta(instrument_id)

        # Log startup summary (Block 9)
        self.log.info(
            f"on_start: {len(self._instrument_ids)} instruments, "
            f"interval={self._check_interval_minutes}min, "
            f"exit_before_resolution={self._exit_before_resolution_secs}s, "
            f"convergence={self._convergence_threshold}, "
            f"tp={self._take_profit}, sl={self._stop_loss}, "
            f"dynamic={self._dynamic_instruments}"
        )
        for iid, meta in self._market_meta.items():
            self.log.info(
                f"  meta: {meta.label} | outcome={meta.outcome} "
                f"token={meta.token_id[:16]}... end={meta.end_date}"
            )

        # Heartbeat timer: update status.json every 60s (Block 5)
        if self._heartbeat_dir is not None:
            self._heartbeat_start_time = self.clock.timestamp() / 1e9
            hb_kwargs: dict[str, Any] = {
                "name": "heartbeat",
                "interval": pd.Timedelta(seconds=60),
                "callback": self._on_heartbeat,
            }
            if self._start_time_ns > 0:
                hb_kwargs["start_time"] = pd.Timestamp(
                    self._start_time_ns, unit="ns", tz="UTC"
                )
            if self._end_time_ns > 0:
                hb_kwargs["stop_time"] = pd.Timestamp(
                    self._end_time_ns, unit="ns", tz="UTC"
                )
            self.clock.set_timer(**hb_kwargs)

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

    def _hydrate_market_meta(self, instrument_id: InstrumentId) -> None:
        """Extract MarketMeta from instrument.info dict."""
        if instrument_id in self._market_meta:
            return
        instrument = self.cache.instrument(instrument_id)
        if instrument is None:
            return
        info = getattr(instrument, "info", None) or {}
        # Extract token_id from instrument symbol: "{condition_id}-{token_id}"
        symbol_str = instrument_id.symbol.value
        parts = symbol_str.split("-", 1)
        token_id = parts[1] if len(parts) == 2 else ""
        # Find outcome for this specific token
        outcome = getattr(instrument, "outcome", "")
        if not outcome:
            for t in info.get("tokens", []):
                if str(t.get("token_id", "")) == token_id:
                    outcome = t.get("outcome", "")
                    break
        self._market_meta[instrument_id] = MarketMeta(
            slug=info.get("slug", "") or info.get("market_slug", ""),
            condition_id=info.get("condition_id", parts[0] if parts else ""),
            token_id=token_id,
            outcome=outcome,
            question=info.get("question", getattr(instrument, "description", "")),
            start_date=info.get("start_date_iso", ""),
            end_date=info.get("end_date_iso", ""),
        )

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

        self._instrument_ids.append(instrument.id)
        self._subscribe_instrument(instrument.id)
        self._hydrate_market_meta(instrument.id)
        meta = self._market_meta.get(instrument.id)
        meta_str = meta.label if meta else str(instrument.id)
        self.log.info(
            f"on_instrument: dynamic discovery — {meta_str} "
            f"outcome={meta.outcome if meta else '?'}"
        )
        self.on_new_instrument(instrument)

    def on_new_instrument(self, instrument: Instrument) -> None:
        """Called when a new instrument is dynamically discovered. Override in subclasses."""

    def _on_instrument_check(self, event: TimeEvent) -> None:
        """Poll cache for new instruments from MarketDiscoveryActor.

        Workaround for Polymarket data client not implementing
        _subscribe_instruments. Checks every 10s for instruments in
        the cache that aren't yet subscribed.
        """
        for iid in self.cache.instrument_ids(venue=POLYMARKET_VENUE):
            if iid not in self._subscribed_ids:
                instrument = self.cache.instrument(iid)
                if instrument:
                    self.on_instrument(instrument)

    def _on_interval_event(self, event: TimeEvent) -> None:
        """Dispatch interval timer events to subclass on_interval()."""
        # Process pending exit retries (queued by failed FOK exits)
        if self._pending_exit_retry:
            retrying = list(self._pending_exit_retry)
            self._pending_exit_retry.clear()
            for iid in retrying:
                self._exiting.discard(iid)
            self.log.info(f"Retrying {len(retrying)} failed exits")

        if not self._data_ended:
            self._interval_count += 1
            if self._interval_count % 10 == 1:
                active = len(self._instrument_ids) - len(self._closed) - len(self._exiting)
                self.log.info(
                    f"on_interval #{self._interval_count}: ts={event.ts_event} "
                    f"instruments={len(self._instrument_ids)} active={active} "
                    f"exiting={len(self._exiting)} closed={len(self._closed)}"
                )
            self.on_interval(event)

    def on_interval(self, event: TimeEvent) -> None:
        """Called on each interval timer tick. Override in subclasses."""

    def _on_heartbeat(self, event: TimeEvent) -> None:
        """Write periodic heartbeat to status.json."""
        if self._heartbeat_dir is None:
            return
        self.log.info(
            f"heartbeat: fills={self._orders_filled} ticks={self._tick_count_total} "
            f"sim_ts={event.ts_event}"
        )
        status = {
            "run_id": self._heartbeat_run_id,
            "status": "running",
            "strategy": type(self).__name__,
            "fills": self._orders_filled,
            "submitted": self._orders_submitted,
            "canceled": self._orders_canceled,
            "rejected": self._orders_rejected,
            "ticks": self._tick_count_total,
            "instruments": len(self._instrument_ids),
            "active": len(self._instrument_ids) - len(self._closed) - len(self._exiting),
            "heartbeat_ts": datetime.now(tz=timezone.utc).isoformat(),
            "sim_ts_ns": event.ts_event,
        }
        try:
            with open(self._heartbeat_dir / "status.json", "w") as f:
                json.dump(status, f, indent=2)
        except Exception as e:
            self.log.debug(f"heartbeat write failed: {e}")

    def _handle_book_update(self, instrument_id: InstrumentId, ts_event: int) -> None:
        """Shared handler for order book updates (both singular and plural deltas)."""
        if instrument_id in self._closed:
            return
        self._tick_count_total += 1

        book = self.cache.order_book(instrument_id)
        if book:
            bid = book.best_bid_price()
            ask = book.best_ask_price()

            if self._tick_count_total % 500 == 0:
                meta = self._market_meta.get(instrument_id)
                label = meta.label if meta else str(instrument_id)
                self.log.info(
                    f"on_tick #{self._tick_count_total}: {label} "
                    f"bid={bid} ask={ask}"
                )

            if self._record_tob and bid is not None and ask is not None:
                bid_qty = book.best_bid_size()
                ask_qty = book.best_ask_size()
                self._tob_records.append({
                    "timestamp_ns": ts_event,
                    "instrument_id": str(instrument_id),
                    "bid": float(bid),
                    "ask": float(ask),
                    "bid_qty": float(bid_qty) if bid_qty else 0.0,
                    "ask_qty": float(ask_qty) if ask_qty else 0.0,
                })

        self._check_exit_conditions(instrument_id)

    def on_order_book_deltas(self, deltas: OrderBookDeltas) -> None:
        self._handle_book_update(deltas.instrument_id, deltas.ts_event)

    def get_top_of_book_df(self) -> pd.DataFrame:
        """Return top-of-book records as a DataFrame."""
        if not self._tob_records:
            return pd.DataFrame()
        return pd.DataFrame(self._tob_records)

    def on_order_book_delta(self, delta: OrderBookDelta) -> None:
        self._handle_book_update(delta.instrument_id, delta.ts_event)

    # --- Order callbacks (Block 3 + Block 9) ---

    def on_order_filled(self, event: OrderFilled) -> None:
        self._orders_filled += 1
        meta = self._market_meta.get(event.instrument_id)
        label = meta.label if meta else str(event.instrument_id)
        self.log.info(
            f"FILLED: {label} {event.order_side.name} "
            f"qty={event.last_qty} @ {event.last_px} "
            f"(fills={self._orders_filled}/{self._orders_submitted})"
        )
        # Track fill in-strategy to avoid cache eviction loss
        self._fill_records.append({
            "timestamp": str(event.ts_event),
            "instrument_id": str(event.instrument_id),
            "slug": meta.slug if meta else "",
            "side": event.order_side.name,
            "qty": float(event.last_qty),
            "price": float(event.last_px),
        })

    def on_order_canceled(self, event: OrderCanceled) -> None:
        self._orders_canceled += 1
        iid = event.instrument_id
        meta = self._market_meta.get(iid)
        label = meta.label if meta else str(iid)
        self.log.info(
            f"CANCELED: {label} "
            f"(canceled={self._orders_canceled}/{self._orders_submitted})"
        )
        # If an exit FOK failed (instrument in _exiting but still has open position),
        # mark for retry on the next interval (not immediately — avoids infinite loops
        # from tick-level convergence checks firing repeatedly).
        if iid in self._exiting and self.cache.positions_open(instrument_id=iid):
            retries = self._exit_retries.get(iid, 0) + 1
            self._exit_retries[iid] = retries
            if retries <= 3:
                self._pending_exit_retry.add(iid)
                self.log.info(f"EXIT FOK failed for {label} — queued retry {retries}/3")
            else:
                self.log.warning(f"EXIT FOK failed 3x for {label} — giving up")
                self._closed.add(iid)
                self._exiting.discard(iid)

    def on_order_rejected(self, event: OrderRejected) -> None:
        self._orders_rejected += 1
        meta = self._market_meta.get(event.instrument_id)
        label = meta.label if meta else str(event.instrument_id)
        self.log.warning(
            f"REJECTED: {label} reason={event.reason} "
            f"(rejected={self._orders_rejected}/{self._orders_submitted})"
        )

    def submit_order(self, order, **kwargs) -> None:
        """Override to count submissions."""
        self._orders_submitted += 1
        super().submit_order(order, **kwargs)

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
        meta = self._market_meta.get(instrument_id)
        label = meta.label if meta else str(instrument_id)
        # Log position size and unrealized PnL if available
        positions = self.cache.positions_open(instrument_id=instrument_id)
        pos_info = ""
        if positions:
            pos = positions[0]
            book = self.cache.order_book(instrument_id)
            if book:
                price = book.best_bid_price() if pos.is_long else book.best_ask_price()
                if price:
                    pnl = float(pos.unrealized_pnl(price))
                    pos_info = f" qty={pos.quantity} unrealized_pnl={pnl:.4f}"
        self.log.info(f"EXIT [{reason}]: {label}{pos_info}")

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
