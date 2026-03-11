#!/usr/bin/env python3
"""Run a single backtest from a config YAML file.

Usage:
    uv run python scripts/run_backtest.py configs/example.yml
    uv run python scripts/run_backtest.py configs/example.yml --discover
    uv run python scripts/run_backtest.py configs/example.yml --results-dir results/my_run

The --discover flag auto-discovers markets from PMXT data and writes metadata
to the metadata directory. This removes the need to pre-cache metadata files.

Exit codes:
    0 = success
    1 = config error
    2 = data error
    3 = strategy crash (partial results)
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import fsspec
import pyarrow.parquet as pq

from pmxt.reader import file_url
from runner.engine import ExperimentConfig, run_backtest
from universe.instruments import load_market_metadata

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

DEFAULT_METADATA_DIR = Path("data/markets")
DEFAULT_CACHE_DIR = Path("data/pmxt/cache")


def discover_markets(hours: list[str], metadata_dir: Path) -> list[dict]:
    """Discover markets from PMXT data and save metadata to disk.

    Scans PMXT parquet files to extract market_ids and token_ids,
    then creates metadata JSON files for instrument construction.
    """
    metadata_dir.mkdir(parents=True, exist_ok=True)
    all_markets: dict[str, dict[str, set[str]]] = {}  # market_id -> {token_ids}

    for hour in hours[:1]:  # Only need first hour for discovery
        url = file_url(hour)
        log.info("Discovering markets from %s", url)

        fs = fsspec.filesystem("http")
        f = fs.open(url)
        pf = pq.ParquetFile(f)

        table = pf.read_row_group(0, columns=["market_id", "data"])
        rows = table.to_pylist()
        f.close()

        for row in rows[:10_000]:
            data = json.loads(row["data"])
            mid = row["market_id"]
            token_id = str(data.get("token_id", ""))
            if not token_id:
                continue
            if mid not in all_markets:
                all_markets[mid] = {"tokens": set(), "count": 0}
            all_markets[mid]["tokens"].add(token_id)
            all_markets[mid]["count"] += 1

    # Build and save metadata for discovered markets
    market_infos = []
    for mid, info in sorted(all_markets.items(), key=lambda x: -x[1]["count"]):
        tokens = info["tokens"]
        if len(tokens) < 2:
            continue  # Need at least Yes/No tokens

        token_list = []
        for i, tid in enumerate(sorted(tokens)):
            outcome = "Yes" if i == 0 else "No"
            token_list.append({"token_id": tid, "outcome": outcome})

        market_info = {
            "condition_id": mid,
            "question": f"Discovered market {mid[:16]}",
            "minimum_tick_size": "0.01",
            "minimum_order_size": "1",
            "end_date_iso": "2027-12-31T00:00:00Z",
            "maker_base_fee": "0",
            "taker_base_fee": "0",
            "tokens": token_list,
        }

        # Save to disk
        path = metadata_dir / f"{mid}.json"
        with open(path, "w") as fp:
            json.dump(market_info, fp, indent=2)
        log.info("Saved metadata: %s (%d tokens, %d rows)", mid[:16], len(tokens), info["count"])

        market_infos.append(market_info)

    log.info("Discovered %d markets with 2+ tokens", len(market_infos))
    return market_infos


def main():
    parser = argparse.ArgumentParser(description="Run a backtest experiment")
    parser.add_argument("config", type=Path, help="Path to experiment config YAML")
    parser.add_argument("--discover", action="store_true",
                        help="Auto-discover markets from PMXT data")
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

    # Discover markets if requested
    if args.discover:
        discovered = discover_markets(config.data_hours, args.metadata_dir)
        if not discovered:
            log.error("No markets discovered from PMXT data")
            sys.exit(2)

        # If config has condition_ids, filter to those
        if config.condition_ids:
            known = {m["condition_id"] for m in discovered}
            missing = [cid for cid in config.condition_ids if cid not in known]
            if missing:
                log.warning("Condition IDs not found in data: %s", [c[:16] for c in missing])

    # Load market metadata
    market_infos = []

    if config.condition_ids:
        # Load specific condition IDs
        for cid in config.condition_ids:
            path = args.metadata_dir / f"{cid}.json"
            if path.exists():
                market_infos.append(load_market_metadata(path))
            else:
                log.warning("No metadata for %s — skipping", cid[:16])
    elif args.discover:
        # Use all discovered markets
        for f in sorted(args.metadata_dir.glob("*.json")):
            market_infos.append(load_market_metadata(f))
        log.info("Using all %d discovered markets", len(market_infos))

    if not market_infos:
        log.error("No market metadata found. Use --discover or cache metadata first.")
        sys.exit(2)

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
    print(f"  Num Trades:     {ts.num_trades}")
    print(f"  Win Rate:       {ts.win_rate:.2%}")
    print(f"  Sharpe Ratio:   {ts.sharpe_ratio:.4f}")
    print(f"  Max Drawdown:   {ts.max_drawdown:.4f}")
    print(f"  Profit Factor:  {ts.profit_factor:.4f}")
    print(f"  Elapsed:        {result.elapsed_seconds:.1f}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
