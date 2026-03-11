#!/usr/bin/env python3
"""Download and cache PMXT data for specific markets and time ranges.

Usage:
    uv run python scripts/download_data.py --market-ids 0xabc123 --hours 2026-03-09T09 2026-03-09T10
    uv run python scripts/download_data.py --discover-hour 2026-03-09T09
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import fsspec
import pyarrow.parquet as pq

from pmxt.index import PMXTIndex
from pmxt.reader import cache_filtered_data, file_url

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path("data/pmxt/cache")
DEFAULT_INDEX_PATH = Path("data/pmxt/index.json")


def discover_markets(hour: str, max_markets: int = 50) -> list[dict]:
    """Discover markets in a PMXT hour file."""
    url = file_url(hour)
    log.info("Discovering markets in %s", url)

    fs = fsspec.filesystem("http")
    f = fs.open(url)
    pf = pq.ParquetFile(f)

    # Read just market_id column from first row group
    table = pf.read_row_group(0, columns=["market_id"])
    market_ids = set(table.column("market_id").to_pylist())
    f.close()

    log.info("Found %d unique market_ids in row group 0", len(market_ids))
    for mid in sorted(market_ids)[:max_markets]:
        print(mid)

    return [{"market_id": mid} for mid in sorted(market_ids)[:max_markets]]


def download_and_cache(
    market_ids: list[str],
    hours: list[str],
    cache_dir: Path,
    index_path: Path,
) -> None:
    """Download and cache filtered PMXT data."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    index = PMXTIndex(index_path)
    market_id_set = set(market_ids)

    for hour in hours:
        # Check what's already cached
        uncached_markets = {
            mid for mid in market_id_set if not index.has_data(mid, hour)
        }

        if not uncached_markets:
            log.info("All markets already cached for %s", hour)
            continue

        log.info("Downloading %d markets for %s", len(uncached_markets), hour)
        cached = cache_filtered_data(hour, uncached_markets, cache_dir)

        for mid, path in cached.items():
            index.register(mid, hour, path)

    log.info("Cache updated. Total size: %.1f MB", index._data.get("total_cache_size_mb", 0))


def main():
    parser = argparse.ArgumentParser(description="Download and cache PMXT data")
    parser.add_argument("--market-ids", nargs="+", help="Market condition IDs to download")
    parser.add_argument("--hours", nargs="+", help="Hour identifiers (e.g., 2026-03-09T09)")
    parser.add_argument("--discover-hour", help="Discover markets in a specific hour")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--index-path", type=Path, default=DEFAULT_INDEX_PATH)

    args = parser.parse_args()

    if args.discover_hour:
        discover_markets(args.discover_hour)
        return

    if not args.market_ids or not args.hours:
        parser.error("--market-ids and --hours are required for downloading")

    download_and_cache(args.market_ids, args.hours, args.cache_dir, args.index_path)


if __name__ == "__main__":
    main()
