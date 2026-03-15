"""MarketDiscoveryActor — periodic polling for new Polymarket markets.

Runs inside a TradingNode as an Actor. Every `poll_interval_minutes`, it:
1. Polls Gamma API with configured filters (in a thread executor)
2. Diffs against instruments already in the cache
3. For new markets: builds BinaryOption instruments and publishes them
   through the DataEngine pipeline (cache + message bus)

Strategies subscribed via `subscribe_instruments(POLYMARKET)` receive new
instruments in their `on_instrument()` callback, where they can subscribe
to orderbook data and start trading.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict
from typing import Any

import pandas as pd

from nautilus_trader.common.actor import Actor
from nautilus_trader.common.events import TimeEvent
from nautilus_trader.config import ActorConfig
from nautilus_trader.model.identifiers import InstrumentId, Venue

from universe.gamma import MarketFilter, discover_markets
from universe.instruments import build_instruments_from_metadata

log = logging.getLogger(__name__)

POLYMARKET_VENUE = Venue("POLYMARKET")
DISCOVERY_TIMER = "market_discovery_poll"


class MarketDiscoveryConfig(ActorConfig, frozen=True):
    """Configuration for MarketDiscoveryActor."""

    poll_interval_minutes: int = 5
    # MarketFilter fields — flattened into config for simplicity
    filter_active: bool | None = True
    filter_closed: bool | None = False
    filter_slug_contains: str | None = None
    filter_categories: tuple[str, ...] = ()
    filter_end_date_min: str | None = None
    filter_end_date_max: str | None = None
    filter_start_date_min: str | None = None
    filter_volume_num_min: float | None = None
    filter_max_markets: int = 50


class MarketDiscoveryActor(Actor):
    """Periodically discovers new Polymarket markets and publishes instruments.

    Parameters
    ----------
    config : MarketDiscoveryConfig
        The actor configuration.

    """

    def __init__(self, config: MarketDiscoveryConfig) -> None:
        super().__init__(config)
        self._poll_interval_minutes = config.poll_interval_minutes
        self._filter = MarketFilter(
            active=config.filter_active,
            closed=config.filter_closed,
            slug_contains=config.filter_slug_contains,
            categories=list(config.filter_categories),
            end_date_min=config.filter_end_date_min,
            end_date_max=config.filter_end_date_max,
            start_date_min=config.filter_start_date_min,
            volume_num_min=config.filter_volume_num_min,
            max_markets=config.filter_max_markets,
        )

        # Pending results from the executor thread
        self._pending_markets: list[dict[str, Any]] = []
        self._poll_running = False
        # Track condition_ids we've already processed to avoid re-adding
        self._known_condition_ids: set[str] = set()

    def on_start(self) -> None:
        self.log.info(
            f"Starting MarketDiscoveryActor: "
            f"poll_interval={self._poll_interval_minutes}min, "
            f"filter={asdict(self._filter)}",
        )

        # Snapshot what's already in cache
        for instrument_id in self.cache.instrument_ids(venue=POLYMARKET_VENUE):
            # Extract condition_id from instrument_id format:
            # {condition_id}-{token_id}.POLYMARKET
            symbol = instrument_id.symbol.value
            condition_id = symbol.split("-")[0] if "-" in symbol else symbol
            self._known_condition_ids.add(condition_id)

        self.log.info(
            f"Found {len(self._known_condition_ids)} existing condition_ids in cache",
        )

        # Kick off initial discovery immediately
        self._start_poll()

        # Register recurring timer
        self.clock.set_timer(
            name=DISCOVERY_TIMER,
            interval=pd.Timedelta(minutes=self._poll_interval_minutes),
            callback=self._on_poll_timer,
        )

    def on_stop(self) -> None:
        # Process any pending discoveries before shutdown
        if self._pending_markets:
            self.log.info("Processing pending discoveries on shutdown")
            self._process_discovered_markets(self._pending_markets)
            self._pending_markets = []

    def _on_poll_timer(self, event: TimeEvent) -> None:
        # Thread safety note: _pending_markets is written by the executor
        # thread (_poll_gamma_api) and read here on the main thread. Python
        # list assignment is atomic, and this check-then-clear runs only on
        # the main thread. Worst case: the executor writes results between
        # the check and clear below, delaying those results to the next
        # timer tick. This is acceptable — no locks needed.
        if self._pending_markets:
            self._process_discovered_markets(self._pending_markets)
            self._pending_markets = []

        # Then kick off a new poll (if not already running)
        self._start_poll()

    def _start_poll(self) -> None:
        if self._poll_running:
            self.log.debug("Poll already running, skipping")
            return

        self._poll_running = True
        self.run_in_executor(self._poll_gamma_api)

    def _poll_gamma_api(self) -> None:
        """Runs in a thread executor — blocking HTTP calls are safe here."""
        try:
            markets = discover_markets(self._filter)
            self._pending_markets = markets
            self.log.info(f"Gamma API poll complete: {len(markets)} markets found")
        except Exception as e:
            self.log.error(f"Gamma API poll failed: {e}")
        finally:
            self._poll_running = False

    def _process_discovered_markets(
        self,
        market_infos: list[dict[str, Any]],
    ) -> None:
        """Process discovered markets on the main thread.

        Builds instruments for new markets, adds them to the cache, and
        publishes them through the DataEngine so strategies receive
        on_instrument() callbacks.
        """
        new_count = 0
        ts_init = time.time_ns()

        for market_info in market_infos:
            condition_id = str(market_info.get("condition_id", ""))
            if not condition_id:
                continue

            if condition_id in self._known_condition_ids:
                continue

            # New market — build instruments
            instruments = build_instruments_from_metadata(market_info, ts_init)
            if not instruments:
                self.log.warning(
                    f"No instruments built for condition_id={condition_id[:16]}",
                )
                continue

            self._known_condition_ids.add(condition_id)

            for instrument, token_id in instruments:
                # Publish through DataEngine pipeline (synchronous):
                # DataEngine._handle_instrument() adds to cache AND
                # publishes on message bus — triggering on_instrument()
                # for subscribed strategies. No separate cache.add_instrument()
                # needed; the DataEngine handles it atomically.
                self.msgbus.send(
                    endpoint="DataEngine.process",
                    msg=instrument,
                )

                self.log.info(
                    f"Discovered new instrument: {instrument.id} "
                    f"({market_info.get('question', '')[:60]})",
                )
                new_count += 1

        if new_count > 0:
            self.log.info(
                f"Published {new_count} new instruments "
                f"(total known: {len(self._known_condition_ids)} conditions)",
            )
