"""Log-only strategy — subscribes to order book data and logs events.

Used for integration testing: verifies data flows through the full pipeline
without any trading logic to complicate debugging.
"""

from __future__ import annotations

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import OrderBookDelta, OrderBookDeltas
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy


class LogOnlyStrategyConfig(StrategyConfig, frozen=True):
    instrument_ids: list[str] = []
    log_interval: int = 1000  # Log every N deltas


class LogOnlyStrategy(Strategy):
    """Subscribes to order book data and logs — no trading."""

    def __init__(self, config: LogOnlyStrategyConfig) -> None:
        super().__init__(config)
        self._instrument_ids = [
            InstrumentId.from_str(iid) for iid in config.instrument_ids
        ]
        self._log_interval = config.log_interval
        self._delta_count = 0
        self._snapshot_count = 0

    def on_start(self) -> None:
        for instrument_id in self._instrument_ids:
            self.subscribe_order_book_deltas(instrument_id)
            self.log.info(f"Subscribed to {instrument_id}")

    def on_order_book_deltas(self, deltas: OrderBookDeltas) -> None:
        self._snapshot_count += 1
        self._delta_count += len(deltas.deltas)

        if self._delta_count % self._log_interval == 0:
            book = self.cache.order_book(deltas.instrument_id)
            bid = book.best_bid_price() if book else None
            ask = book.best_ask_price() if book else None
            self.log.info(
                f"Deltas: {self._delta_count}, "
                f"Snapshots: {self._snapshot_count}, "
                f"Bid: {bid}, Ask: {ask}"
            )

    def on_order_book_delta(self, delta: OrderBookDelta) -> None:
        self._delta_count += 1

        if self._delta_count % self._log_interval == 0:
            book = self.cache.order_book(delta.instrument_id)
            bid = book.best_bid_price() if book else None
            ask = book.best_ask_price() if book else None
            self.log.info(
                f"Deltas: {self._delta_count}, "
                f"Bid: {bid}, Ask: {ask}"
            )

    def on_stop(self) -> None:
        self.log.info(
            f"Final count: {self._delta_count} deltas, "
            f"{self._snapshot_count} snapshots"
        )

    @property
    def delta_count(self) -> int:
        return self._delta_count
