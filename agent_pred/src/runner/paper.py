"""Paper trading runner — live data, simulated execution, dynamic market discovery.

Uses NautilusTrader's TradingNode with:
- PolymarketDataClient for live WebSocket market data
- SandboxExecutionClient for simulated order fills
- MarketDiscoveryActor for periodic new-market polling via Gamma API

When discovery is enabled (universe filters present in config), the runner
registers a MarketDiscoveryActor that polls the Gamma API on a timer. New
instruments are published through the DataEngine, triggering on_instrument()
on strategies that have dynamic_instruments=True.
"""

from __future__ import annotations

import importlib
import json
import logging
import signal
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nautilus_trader.adapters.polymarket import (
    POLYMARKET,
    PolymarketDataClientConfig,
    PolymarketLiveDataClientFactory,
    get_polymarket_instrument_id,
)
from nautilus_trader.adapters.polymarket.providers import (
    PolymarketInstrumentProviderConfig,
)
from nautilus_trader.adapters.sandbox.config import SandboxExecutionClientConfig
from nautilus_trader.adapters.sandbox.factory import SandboxLiveExecClientFactory
from nautilus_trader.config import (
    LiveExecEngineConfig,
    LoggingConfig,
    TradingNodeConfig,
)
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.identifiers import TraderId

from discovery.actor import MarketDiscoveryActor, MarketDiscoveryConfig
from runner.artifacts import generate_all_artifacts
from runner.engine import ExperimentConfig
from runner.utils import import_strategy_class

log = logging.getLogger(__name__)

SANDBOX_VENUE = "POLYMARKET"


def _build_instrument_id_strings(market_infos: list[dict[str, Any]]) -> list[str]:
    """Extract NautilusTrader instrument ID strings from market metadata.

    Each market has tokens (Yes/No outcomes). Each token becomes an instrument
    with ID format: {condition_id}-{token_id}.POLYMARKET
    """
    ids = []
    for info in market_infos:
        condition_id = str(info["condition_id"])
        for token in info.get("tokens", []):
            token_id = str(token["token_id"])
            iid = get_polymarket_instrument_id(condition_id, token_id)
            ids.append(str(iid))
    return ids


def _build_discovery_config(config: ExperimentConfig) -> MarketDiscoveryConfig | None:
    """Build MarketDiscoveryConfig from experiment config's universe section.

    Returns None if no universe filters are configured (explicit condition_ids mode).
    """
    if config.condition_ids:
        # Explicit instruments — no discovery needed
        return None

    uni = config.universe
    poll_minutes = config.discovery_poll_minutes

    return MarketDiscoveryConfig(
        poll_interval_minutes=poll_minutes,
        filter_active=uni.active,
        filter_closed=uni.closed,
        filter_slug_contains=uni.slug_contains,
        filter_categories=tuple(uni.categories),
        filter_end_date_min=uni.end_date_min,
        filter_end_date_max=uni.end_date_max,
        filter_start_date_min=uni.start_date_min,
        filter_volume_num_min=uni.volume_min if uni.volume_min > 0 else None,
        filter_max_markets=uni.max_markets,
    )


def run_paper(
    config: ExperimentConfig,
    market_infos: list[dict[str, Any]],
    results_dir: Path | None = None,
) -> None:
    """Run a paper trading session with live data and simulated execution.

    Parameters
    ----------
    config : ExperimentConfig
        Parsed experiment configuration with mode="paper".
    market_infos : list[dict]
        Market metadata dicts (from Gamma API or CLOB API).
    results_dir : Path | None
        Directory for status.json, fills CSV, and other artifacts.

    """
    # Build instrument ID strings for the provider
    instrument_id_strs = _build_instrument_id_strings(market_infos)
    if not instrument_id_strs:
        raise ValueError("No instruments found in market_infos")

    log.info("Paper trading %d instruments from %d markets", len(instrument_id_strs), len(market_infos))

    # Configure instrument provider to load our specific instruments
    instrument_provider_config = PolymarketInstrumentProviderConfig(
        load_ids=frozenset(instrument_id_strs),
    )

    # Configure TradingNode
    node_config = TradingNodeConfig(
        trader_id=TraderId("PAPER-001"),
        logging=LoggingConfig(log_level="INFO", use_pyo3=True),
        exec_engine=LiveExecEngineConfig(
            reconciliation=False,
        ),
        data_clients={
            POLYMARKET: PolymarketDataClientConfig(
                instrument_config=instrument_provider_config,
                compute_effective_deltas=True,
                # Dummy credentials — MARKET WebSocket and L0 API calls are public,
                # but the factory resolves env vars when these are None.
                private_key="0x0000000000000000000000000000000000000000000000000000000000000001",
                funder="0x0000000000000000000000000000000000000000",
                api_key="dummy",
                api_secret="dummy",
                passphrase="dummy",
            ),
        },
        exec_clients={
            SANDBOX_VENUE: SandboxExecutionClientConfig(
                venue=SANDBOX_VENUE,
                starting_balances=[f"{config.starting_balance} USDC.e"],
                oms_type="NETTING",
                account_type="CASH",
                book_type="L2_MBP",
                bar_execution=False,
                trade_execution=True,
                reject_stop_orders=False,
                use_reduce_only=False,
            ),
        },
        timeout_connection=30.0,
        timeout_disconnection=10.0,
        timeout_post_stop=5.0,
    )

    node = TradingNode(config=node_config)

    # Import and configure strategy (same pattern as backtest engine)
    strategy_cls = import_strategy_class(config.strategy_path)
    config_module_path = config.strategy_path.rsplit(":", 1)[0]
    config_class_name = strategy_cls.__name__ + "Config"
    config_cls = getattr(importlib.import_module(config_module_path), config_class_name)

    # Inject instrument IDs into strategy params
    strategy_params = dict(config.strategy_params)
    strategy_params["instrument_ids"] = instrument_id_strs

    # For paper trading, don't set start_time_ns/end_time_ns — the live clock handles timing.
    # Remove backtest-specific time bounds if present.
    strategy_params.pop("start_time_ns", None)
    strategy_params.pop("end_time_ns", None)

    # Enable dynamic instruments if discovery is configured
    discovery_config = _build_discovery_config(config)
    if discovery_config is not None:
        strategy_params["dynamic_instruments"] = True

    strategy_config = config_cls(**strategy_params)
    strategy = strategy_cls(strategy_config)
    node.trader.add_strategy(strategy)

    # Set up results directory and heartbeat
    run_id = str(uuid.uuid4())[:8]
    if results_dir is None:
        results_dir = Path("results") / f"paper-{run_id}"
    results_dir.mkdir(parents=True, exist_ok=True)
    strategy._heartbeat_dir = results_dir
    strategy._heartbeat_run_id = run_id
    log.info("Paper run_id=%s, results_dir=%s", run_id, results_dir)

    # Register MarketDiscoveryActor if discovery is configured
    if discovery_config is not None:
        discovery_actor = MarketDiscoveryActor(discovery_config)
        node.trader.add_actor(discovery_actor)
        log.info(
            "Registered MarketDiscoveryActor (poll every %d min)",
            discovery_config.poll_interval_minutes,
        )

    # Register client factories
    node.add_data_client_factory(POLYMARKET, PolymarketLiveDataClientFactory)
    node.add_exec_client_factory(SANDBOX_VENUE, SandboxLiveExecClientFactory)

    # Build clients
    node.build()

    duration = config.paper_duration_seconds
    log.info("Starting paper trading for %d seconds", duration)

    # Set up auto-stop timer
    def _stop_handler(signum, frame):
        log.info("Stopping paper trading node...")
        node.stop()

    signal.signal(signal.SIGALRM, _stop_handler)
    signal.alarm(duration)

    # Write initial status
    _write_status(results_dir, {
        "run_id": run_id,
        "status": "running",
        "strategy": config.strategy_path,
        "mode": "paper",
        "started": datetime.now(tz=timezone.utc).isoformat(),
    })

    try:
        node.run()
    except KeyboardInterrupt:
        log.info("Paper trading interrupted by user")
    finally:
        signal.alarm(0)  # Cancel alarm
        # Save artifacts before dispose
        _save_paper_artifacts(strategy, results_dir, run_id, market_infos)
        node.dispose()
        log.info("Paper trading session ended")


def _write_status(results_dir: Path, status: dict[str, Any]) -> None:
    """Write status.json to results directory."""
    with open(results_dir / "status.json", "w") as f:
        json.dump(status, f, indent=2)


def _save_paper_artifacts(
    strategy: Any,
    results_dir: Path,
    run_id: str,
    market_infos: list[dict[str, Any]],
) -> None:
    """Save paper trading artifacts after run completes."""
    try:
        from nautilus_trader.analysis.reporter import ReportProvider

        # Use in-strategy fill records (avoids cache eviction losing older fills)
        rows = list(strategy._fill_records)
        if rows:
            import csv
            fills_path = results_dir / "fills.csv"
            with open(fills_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            # Log BUY/SELL balance for verification
            buy_qty = sum(r["qty"] for r in rows if r["side"] == "BUY")
            sell_qty = sum(r["qty"] for r in rows if r["side"] == "SELL")
            log.info(
                "Saved %d fills to %s (BUY=%.1f, SELL=%.1f)",
                len(rows), fills_path, buy_qty, sell_qty,
            )

        # Generate visualization PNGs using ReportProvider DataFrames
        try:
            orders = strategy.cache.orders()
            positions = strategy.cache.positions()
            fills_df = ReportProvider.generate_fills_report(orders)
            positions_df = ReportProvider.generate_positions_report(positions)

            generated = generate_all_artifacts(
                fills_df=fills_df,
                positions_df=positions_df,
                results_dir=results_dir,
                market_infos=market_infos,
            )
            if generated:
                log.info("Generated %d visualization artifacts", len(generated))
        except Exception as e:
            log.warning("PNG artifact generation failed: %s", e)

        # Top-of-book data if recorded
        tob_df = strategy.get_top_of_book_df()
        if not tob_df.empty:
            tob_path = results_dir / "top_of_book.csv"
            tob_df.to_csv(tob_path, index=False)
            log.info("Saved top-of-book data to %s", tob_path)

        # Final status
        _write_status(results_dir, {
            "run_id": run_id,
            "status": "completed",
            "mode": "paper",
            "fills": strategy._orders_filled,
            "submitted": strategy._orders_submitted,
            "canceled": strategy._orders_canceled,
            "rejected": strategy._orders_rejected,
            "ticks": strategy._tick_count_total,
            "instruments": len(strategy._instrument_ids),
            "finished": datetime.now(tz=timezone.utc).isoformat(),
        })
        log.info("Saved paper artifacts to %s", results_dir)
    except Exception as e:
        log.error("Failed to save paper artifacts: %s", e)
