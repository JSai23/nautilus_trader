#!/usr/bin/env python3
"""Run a backtest or paper trading session from a config YAML file.

Usage:
    uv run python scripts/run_backtest.py experiments/configs/example_backtest.yml
    uv run python scripts/run_backtest.py experiments/configs/paper_momentum.yml
    uv run python scripts/run_backtest.py experiments/configs/example_backtest.yml --results-dir results/my_run

Market resolution:
    - If condition_ids are in the config, fetches metadata from CLOB API.
    - Otherwise, discovers markets via Gamma API using the `universe` section.

Modes:
    - mode: "backtest" — replay historical PMXT data through BacktestEngine
    - mode: "paper" — live Polymarket data, simulated execution via TradingNode

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
    MarketFilter,
    discover_markets,
    fetch_market_clob,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path("data/pmxt/cache")


def _resolve_market_infos(config: ExperimentConfig) -> list[dict]:
    """Resolve market metadata from config.

    Two paths:
    1. condition_ids in config → fetch each from CLOB API
    2. No condition_ids → discover via Gamma API using universe filters
    """
    # Path 1: Explicit condition_ids — fetch from CLOB API
    if config.condition_ids:
        market_infos = []
        for cid in config.condition_ids:
            metadata = fetch_market_clob(cid)
            if metadata:
                market_infos.append(metadata)
                log.info("Fetched metadata for %s from CLOB API", cid[:16])
            else:
                log.warning("No metadata for %s — skipping", cid[:16])
        return market_infos

    # Path 2: Discover via Gamma API using universe filters
    uni = config.universe
    mf = MarketFilter(
        active=uni.active,
        closed=uni.closed,
        end_date_min=uni.end_date_min,
        end_date_max=uni.end_date_max,
        start_date_min=uni.start_date_min,
        volume_num_min=uni.volume_min,
        order=uni.order_by,
        ascending=uni.ascending,
        slug_contains=uni.slug_contains,
        categories=uni.categories,
        max_markets=uni.max_markets,
    )
    return discover_markets(mf)


def main():
    parser = argparse.ArgumentParser(description="Run a backtest experiment")
    parser.add_argument("config", type=Path, help="Path to experiment config YAML")
    parser.add_argument("--results-dir", type=Path, help="Results output directory")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--mlflow-uri", type=str, default=None)

    args = parser.parse_args()

    # Parse config
    try:
        config = ExperimentConfig.from_yaml(args.config)
    except Exception as e:
        log.error("Config parse error: %s", e)
        sys.exit(1)

    # Resolve market metadata
    market_infos = _resolve_market_infos(config)

    if not market_infos:
        log.error("No market metadata found. Add condition_ids or universe filters to config.")
        sys.exit(2)

    log.info("Resolved %d markets", len(market_infos))

    # Dispatch based on mode
    if config.mode == "paper":
        _run_paper_mode(config, market_infos)
    else:
        _run_backtest_mode(config, market_infos, args)


def _run_backtest_mode(config, market_infos, args):
    """Run historical backtest."""
    if not config.data_hours:
        log.error("Backtest mode requires data.hours in config")
        sys.exit(1)

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


def _run_paper_mode(config, market_infos):
    """Run paper trading with live data."""
    from runner.paper import run_paper

    print(f"\n{'='*60}")
    print(f"  PAPER TRADING")
    print(f"{'='*60}")
    print(f"  Strategy:   {config.strategy_path}")
    print(f"  Markets:    {len(market_infos)}")
    print(f"  Duration:   {config.paper_duration_seconds}s")
    print(f"  Balance:    {config.starting_balance}")
    print(f"{'='*60}\n")

    run_paper(config=config, market_infos=market_infos)


if __name__ == "__main__":
    main()
