#!/usr/bin/env python3
"""Run a single backtest from a config YAML file.

Usage:
    uv run python scripts/run_backtest.py configs/example.yml
    uv run python scripts/run_backtest.py configs/example.yml --discover
    uv run python scripts/run_backtest.py configs/example.yml --discover --refresh-metadata
    uv run python scripts/run_backtest.py configs/example.yml --results-dir results/my_run

The --discover flag queries the Gamma API for market metadata using filter
criteria from the config's `discovery` section. Without --discover, markets
are loaded from the metadata cache (condition_ids must be specified or cached).

Exit codes:
    0 = success
    1 = config error
    2 = data error
    3 = strategy crash (partial results)
"""

import argparse
import logging
import sys
from pathlib import Path

from runner.engine import ExperimentConfig, run_backtest
from universe.gamma import (
    GammaMarketCache,
    MarketFilter,
    discover_markets,
    fetch_market_clob,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

DEFAULT_METADATA_DIR = Path("data/markets")
DEFAULT_CACHE_DIR = Path("data/pmxt/cache")


def _resolve_market_infos(
    config: ExperimentConfig,
    metadata_dir: Path,
    do_discover: bool,
    refresh: bool,
) -> list[dict]:
    """Resolve market metadata: from config condition_ids, Gamma API, or cache.

    Pipeline:
    1. condition_ids in config → load from cache (or discover if missing)
    2. --discover flag → query Gamma API with discovery filters
    3. Neither → load all cached metadata, capped by max_markets
    """
    cache = GammaMarketCache(metadata_dir)

    # Path 1: Explicit condition_ids in config
    # Uses CLOB API for direct per-market lookup (Gamma API doesn't support condition_id queries)
    if config.condition_ids:
        market_infos = []
        for cid in config.condition_ids:
            cached = cache.get(cid)

            if cached and not refresh:
                market_infos.append(cached)
                continue

            # Fetch from CLOB API: either refresh requested or not cached
            metadata = fetch_market_clob(cid)
            if metadata:
                cache.put(metadata)
                market_infos.append(metadata)
                log.info("Fetched metadata for %s from CLOB API", cid[:16])
            elif cached:
                # CLOB fetch failed but we have stale cache — use it
                log.warning("CLOB API failed for %s, using stale cache", cid[:16])
                market_infos.append(cached)
            else:
                log.warning("No metadata for %s — skipping", cid[:16])

        return market_infos

    # Path 2: Discover via Gamma API
    if do_discover:
        disc = config.discovery
        mf = MarketFilter(
            active=disc.active,
            closed=disc.closed,
            min_volume=disc.min_volume,
            max_markets=disc.max_markets,
            categories=disc.categories,
            slug_contains=disc.slug_contains,
        )
        return discover_markets(mf, cache, refresh=refresh)

    # Path 3: Load all cached metadata
    all_cached = cache.list_all()
    cap = config.max_markets if config.max_markets > 0 else len(all_cached)
    if cap < len(all_cached):
        log.info("Capping cached markets from %d to max_markets=%d", len(all_cached), cap)
        all_cached = all_cached[:cap]
    log.info("Using %d cached markets", len(all_cached))
    return all_cached


def main():
    parser = argparse.ArgumentParser(description="Run a backtest experiment")
    parser.add_argument("config", type=Path, help="Path to experiment config YAML")
    parser.add_argument("--discover", action="store_true",
                        help="Discover markets via Gamma API using config filters")
    parser.add_argument("--refresh-metadata", action="store_true",
                        help="Re-fetch metadata from Gamma API even if cached")
    parser.add_argument("--results-dir", type=Path, help="Results output directory")
    parser.add_argument("--metadata-dir", type=Path, default=DEFAULT_METADATA_DIR)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--mlflow-uri", type=str, default=None)

    args = parser.parse_args()

    # Parse config
    try:
        config = ExperimentConfig.from_yaml(args.config)
    except Exception as e:
        log.error("Config parse error: %s", e)
        sys.exit(1)

    if not config.data_hours:
        log.error("Config must specify data.hours")
        sys.exit(1)

    # Resolve market metadata
    market_infos = _resolve_market_infos(
        config, args.metadata_dir, args.discover, args.refresh_metadata,
    )

    if not market_infos:
        log.error("No market metadata found. Use --discover or cache metadata first.")
        sys.exit(2)

    log.info("Resolved %d markets for backtest", len(market_infos))

    # Run
    result = run_backtest(
        config=config,
        market_infos=market_infos,
        data_cache_dir=args.cache_dir,
        results_dir=args.results_dir,
        mlflow_tracking_uri=args.mlflow_uri,
    )

    if not result.success:
        log.error("Backtest failed: %s", result.error)
        sys.exit(3)

    # Print summary
    ts = result.tearsheet
    print(f"\n{'='*60}")
    print(f"  BACKTEST RESULT: {result.run_id}")
    print(f"{'='*60}")
    print(f"  Total PnL:      {ts.total_pnl:.4f}")
    print(f"  Num Fills:      {ts.num_trades}")
    print(f"  Round Trips:    {ts.num_round_trips}")
    print(f"  Win Rate:       {ts.win_rate:.2%}")
    print(f"  Sharpe Ratio:   {ts.sharpe_ratio:.4f}")
    print(f"  Max Drawdown:   {ts.max_drawdown:.4f}")
    print(f"  Profit Factor:  {ts.profit_factor:.4f}")
    print(f"  Elapsed:        {result.elapsed_seconds:.1f}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
