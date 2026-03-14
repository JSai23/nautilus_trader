"""Momentum drift — buy the winning side early, take profit on further drift.

btc-updown markets: Up + Down sum to ~1.0. Prices start at 0.50, drift to 0/1.

Strategy: buy tokens early in the drift (mid 0.52-0.65), take profit when
mid rises further (locking gains), cut losses on reversal.
Only one position per condition_id. Require narrow spread for entry.
"""

from __future__ import annotations

from collections import deque

from nautilus_trader.common.events import TimeEvent
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events.order import OrderCanceled, OrderFilled
from nautilus_trader.model.events.position import PositionClosed
from nautilus_trader.model.identifiers import InstrumentId

from strategy.base import PolymarketStrategy, PolymarketStrategyConfig


class MomentumDriftConfig(PolymarketStrategyConfig, frozen=True):
    trade_size: float = 100.0
    check_interval_minutes: int = 1
    lookback: int = 3  # compare current mid to N intervals ago
    min_drift: float = 0.02  # minimum drift to trigger entry
    max_spread: float = 0.06  # don't enter when spread is wider than this
    entry_mid_low: float = 0.52  # only enter above this (must show some drift)
    entry_mid_high: float = 0.65  # don't enter above this (too late, not enough upside)
    min_hold: int = 2  # minimum intervals before exit
    take_profit_delta: float = 0.08  # exit when mid rises this much above entry
    stop_loss_delta: float = 0.04  # exit when mid drops this much below entry
    reversal_threshold: float = 0.05  # exit when mid drops this much from peak (after TP range)
    convergence_threshold: float = 0.95


class MomentumDrift(PolymarketStrategy):
    """Buy early drift, hold through noise, exit on strong reversal."""

    def __init__(self, config: MomentumDriftConfig) -> None:
        super().__init__(config)
        self._trade_size = config.trade_size
        self._lookback = config.lookback
        self._min_drift = config.min_drift
        self._max_spread = config.max_spread
        self._entry_mid_low = config.entry_mid_low
        self._entry_mid_high = config.entry_mid_high
        self._min_hold = config.min_hold
        self._take_profit_delta = config.take_profit_delta
        self._stop_loss_delta = config.stop_loss_delta
        self._reversal_threshold = config.reversal_threshold

        self._mid_history: dict[InstrumentId, deque[float]] = {}
        self._peak_mid: dict[InstrumentId, float] = {}
        self._hold_count: dict[InstrumentId, int] = {}
        self._entry_mid: dict[InstrumentId, float] = {}
        self._condition_has_position: set[str] = set()
        self._iid_to_condition: dict[InstrumentId, str] = {}
        self._round_trips: int = 0

    def on_start(self) -> None:
        super().on_start()
        for iid in self._instrument_ids:
            meta = self._market_meta.get(iid)
            if meta:
                self._iid_to_condition[iid] = meta.condition_id

    def on_interval(self, event: TimeEvent) -> None:
        for iid in self._instrument_ids:
            if iid in self._exiting or iid in self._closed:
                continue

            book = self.cache.order_book(iid)
            if book is None:
                continue
            best_bid = book.best_bid_price()
            best_ask = book.best_ask_price()
            if best_bid is None or best_ask is None:
                continue

            bid = float(best_bid)
            ask = float(best_ask)
            mid = (bid + ask) / 2.0
            spread = ask - bid

            if iid not in self._mid_history:
                self._mid_history[iid] = deque(maxlen=self._lookback + 1)
            self._mid_history[iid].append(mid)

            # Diagnostic logging every 20 intervals
            if self._interval_count % 20 == 1:
                meta = self._market_meta.get(iid)
                label = meta.label if meta else str(iid)[:30]
                history = self._mid_history[iid]
                drift = mid - history[0] if len(history) > self._lookback else 0
                hold = self._hold_count.get(iid, 0)
                self.log.info(
                    f"  {label} out={meta.outcome if meta else '?'} "
                    f"mid={mid:.3f} spr={spread:.3f} drift={drift:+.3f} "
                    f"hold={hold}"
                )

            has_position = bool(self.cache.positions_open(instrument_id=iid))
            has_orders = bool(self.cache.orders_open(instrument_id=iid))

            if has_position:
                self._hold_count[iid] = self._hold_count.get(iid, 0) + 1
                self._manage_exit(iid, mid, bid, spread, has_orders)
            elif not has_orders:
                self._check_entry(iid, mid, ask, spread)

    def _check_entry(self, iid: InstrumentId, mid: float, ask: float, spread: float) -> None:
        """Enter if: mid in sweet spot, drifting up, spread narrow, no other position on condition."""
        history = self._mid_history.get(iid)
        if history is None or len(history) < self._lookback + 1:
            return

        # Only buy in the sweet spot: 0.52-0.65
        if mid < self._entry_mid_low or mid > self._entry_mid_high:
            return

        # Require narrow spread
        if spread > self._max_spread:
            return

        # One position per condition
        cond = self._iid_to_condition.get(iid, "")
        if cond and cond in self._condition_has_position:
            return

        # Check drift: net drift must exceed threshold
        old_mid = history[0]
        drift = mid - old_mid
        if drift < self._min_drift:
            return

        # Require monotonic drift: each interval must be >= previous
        # This filters out choppy reversals that create false drift signals
        for i in range(1, len(history)):
            if history[i] < history[i - 1]:
                return

        instrument = self.cache.instrument(iid)
        if instrument is None:
            return

        meta = self._market_meta.get(iid)
        label = meta.label if meta else str(iid)
        self.log.info(
            f"ENTRY: {label} out={meta.outcome if meta else '?'} "
            f"mid={mid:.3f} drift={drift:+.3f} spread={spread:.3f} ask={ask:.3f}"
        )

        order = self.order_factory.limit(
            instrument_id=iid,
            order_side=OrderSide.BUY,
            quantity=instrument.make_qty(self._trade_size),
            price=instrument.make_price(ask),
            time_in_force=TimeInForce.FOK,
        )
        self.submit_order(order)
        # State is set in on_order_filled (not here) to avoid locking
        # the condition when a FOK entry fails to fill.

    def _manage_exit(self, iid: InstrumentId, mid: float, bid: float,
                     spread: float, has_orders: bool) -> None:
        """Exit on take-profit, stop-loss, or trailing reversal."""
        peak = self._peak_mid.get(iid, mid)
        if mid > peak:
            self._peak_mid[iid] = mid
            peak = mid

        hold = self._hold_count.get(iid, 0)
        if hold < self._min_hold or has_orders:
            return

        entry_mid = self._entry_mid.get(iid, 0)
        gain = mid - entry_mid
        drawdown = peak - mid
        reason = ""

        # Take profit: mid rose enough above entry
        if gain >= self._take_profit_delta:
            reason = "take_profit"
        # Stop loss: mid dropped below entry
        elif gain <= -self._stop_loss_delta:
            reason = "stop_loss"
        # Trailing reversal: mid dropped from peak (only after some gain)
        elif gain > 0 and drawdown >= self._reversal_threshold:
            reason = "reversal"

        if not reason:
            return

        positions = self.cache.positions_open(instrument_id=iid)
        if not positions:
            return
        pos = positions[0]
        if not pos.is_long:
            return

        instrument = self.cache.instrument(iid)
        if instrument is None:
            return

        pnl_est = (bid - entry_mid) * self._trade_size
        meta = self._market_meta.get(iid)
        label = meta.label if meta else str(iid)
        self.log.info(
            f"EXIT [{reason}]: {label} mid={mid:.3f} entry={entry_mid:.3f} "
            f"gain={gain:+.3f} peak={peak:.3f} dd={drawdown:.3f} "
            f"hold={hold} est_pnl={pnl_est:+.1f}"
        )

        self.cancel_all_orders(iid)
        qty = instrument.make_qty(float(pos.quantity))
        order = self.order_factory.limit(
            instrument_id=iid,
            order_side=OrderSide.SELL,
            quantity=qty,
            price=instrument.make_price(bid),
            time_in_force=TimeInForce.FOK,
        )
        self.submit_order(order)

    def on_order_filled(self, event: OrderFilled) -> None:
        super().on_order_filled(event)
        iid = event.instrument_id
        # Only set entry state on BUY fills (not exits)
        if event.order_side == OrderSide.BUY and iid not in self._entry_mid:
            fill_price = float(event.last_px)
            self._entry_mid[iid] = fill_price
            self._peak_mid[iid] = fill_price
            self._hold_count[iid] = 0
            cond = self._iid_to_condition.get(iid, "")
            if cond:
                self._condition_has_position.add(cond)

    def on_order_canceled(self, event: OrderCanceled) -> None:
        super().on_order_canceled(event)
        iid = event.instrument_id
        # Only clean up state for ENTRY cancels (BUY FOK that didn't fill).
        # EXIT cancels (SELL FOK that didn't fill) must NOT clear entry state,
        # otherwise _entry_mid becomes 0 and subsequent TP/SL checks use wrong reference.
        has_position = bool(self.cache.positions_open(instrument_id=iid))
        if not has_position:
            # No position = this was an entry that failed. Clean up.
            self._entry_mid.pop(iid, None)
            self._peak_mid.pop(iid, None)
            self._hold_count.pop(iid, None)

    def on_position_closed(self, event: PositionClosed) -> None:
        iid = event.instrument_id
        self._peak_mid.pop(iid, None)
        self._hold_count.pop(iid, None)
        self._entry_mid.pop(iid, None)
        self._closed.discard(iid)
        self._exiting.discard(iid)
        self._round_trips += 1
        cond = self._iid_to_condition.get(iid, "")
        if cond:
            self._condition_has_position.discard(cond)

    @property
    def round_trips(self) -> int:
        return self._round_trips
