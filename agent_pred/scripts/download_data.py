#!/usr/bin/env python3
"""Download and cache PMXT data for specific markets and time ranges.

Usage:
    # Download data for specific markets
    uv run python scripts/download_data.py --market-ids 0xabc123 --hours 2026-03-09T09 2026-03-09T10

    # Discover markets via Gamma API
    uv run python scripts/download_data.py --discover-markets --active --limit 50
    uv run python scripts/download_data.py --discover-markets --min-volume 10000 --categories crypto

    # Discover markets and download their data
    uv run python scripts/download_data.py --discover-markets --active --limit 20 --hours 2026-03-09T09

    # Refresh cached metadata from Gamma API
    uv run python scripts/download_data.py --discover-markets --refresh
"""

import argparse
import logging
import sys
from pathlib import Path

from pmxt.index import PMXTIndex
from pmxt.reader import cache_filtered_data
from universe.gamma import GammaMarketCache, MarketFilter, discover_markets

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path("data/pmxt/cache")
DEFAULT_INDEX_PATH = Path("data/pmxt/index.json")
DEFAULT_METADATA_DIR = Path("data/markets")


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
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--index-path", type=Path, default=DEFAULT_INDEX_PATH)
    parser.add_argument("--metadata-dir", type=Path, default=DEFAULT_METADATA_DIR)

    # Gamma API discovery
    parser.add_argument("--discover-markets", action="store_true",
                        help="Discover markets via Gamma API")
    parser.add_argument("--active", action="store_true", default=False,
                        help="Only active markets")
    parser.add_argument("--min-volume", type=float, default=0.0,
                        help="Minimum trading volume")
    parser.add_argument("--limit", type=int, default=50,
                        help="Maximum number of markets to discover")
    parser.add_argument("--categories", nargs="+", default=[],
                        help="Filter by categories (e.g., crypto politics)")
    parser.add_argument("--slug-contains", type=str, default=None,
                        help="Filter by slug substring")
    parser.add_argument("--refresh", action="store_true",
                        help="Re-fetch metadata from API even if cached")

    args = parser.parse_args()

    if args.discover_markets:
        mf = MarketFilter(
            active=True if args.active else None,
            closed=False if args.active else None,
            min_volume=args.min_volume,
            max_markets=args.limit,
            categories=args.categories,
            slug_contains=args.slug_contains,
        )
        cache = GammaMarketCache(args.metadata_dir)
        markets = discover_markets(mf, cache, refresh=args.refresh)

        print(f"\nDiscovered {len(markets)} markets:")
        for m in markets:
            q = m.get("question", "")[:60]
            vol = m.get("volume", 0)
            cid = m["condition_id"][:16]
            n_tokens = len(m.get("tokens", []))
            print(f"  {cid}...  vol={vol:>10.0f}  tokens={n_tokens}  {q}")

        # If hours also provided, download data for discovered markets
        if args.hours:
            condition_ids = [m["condition_id"] for m in markets]
            download_and_cache(condition_ids, args.hours, args.cache_dir, args.index_path)
        return

    if not args.market_ids or not args.hours:
        parser.error("--market-ids and --hours are required for downloading (or use --discover-markets)")

    download_and_cache(args.market_ids, args.hours, args.cache_dir, args.index_path)


if __name__ == "__main__":
    main()
