"""Shared test fixtures and helpers for agent_pred tests."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import fsspec
import pyarrow.parquet as pq

from pmxt.reader import file_url
from universe.gamma import GammaMarketCache, fetch_market_clob

log = logging.getLogger(__name__)

_MARKET_CACHE = GammaMarketCache(Path("data/markets"))


def _adapt_metadata_for_testing(metadata: dict, hour: str) -> dict:
    """Adapt real API metadata for test use.

    Real metadata from CLOB API may have constraints that prevent test
    strategies from executing (resolved markets, high minimum order sizes).
    This adjusts metadata so tests exercise strategy logic correctly:

    1. Extends end_date_iso past the test hour (prevents resolution timer
       from firing immediately on already-resolved markets)
    2. Sets minimum_order_size to "1" (tests use trade_size=1.0, but real
       markets require 5+ — we're testing strategy logic, not exchange limits)
    """
    metadata = dict(metadata)  # shallow copy to avoid mutating cache

    # Extend end_date if market resolved before test data window
    end_date = metadata.get("end_date_iso", "")
    if end_date:
        try:
            hour_dt = datetime.strptime(hour, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            if end_dt <= hour_dt:
                extended = hour_dt.replace(hour=23, minute=59, second=59)
                metadata["end_date_iso"] = extended.strftime("%Y-%m-%dT%H:%M:%SZ")
                log.info(
                    "Extended end_date for %s from %s to %s (test override)",
                    metadata["condition_id"][:16],
                    end_date,
                    metadata["end_date_iso"],
                )
        except (ValueError, TypeError):
            pass

    # Override minimum_order_size for test compatibility
    metadata["minimum_order_size"] = "1"

    return metadata


def discover_market_with_tokens(hour: str) -> dict:
    """Discover a market from PMXT data and extract token_ids.

    Reads the first row group of the PMXT parquet file for the given hour,
    finds the market with the most activity, and builds a market_info dict
    suitable for instrument construction.
    """
    url = file_url(hour)
    fs = fsspec.filesystem("http")
    f = fs.open(url)
    pf = pq.ParquetFile(f)

    table = pf.read_row_group(0, columns=["market_id", "update_type", "data"])
    rows = table.to_pylist()
    f.close()

    market_tokens: dict[str, set[str]] = {}
    market_rows: dict[str, list[dict]] = {}

    for row in rows[:5000]:
        data = json.loads(row["data"])
        mid = row["market_id"]
        token_id = str(data.get("token_id", ""))
        if not token_id:
            continue
        if mid not in market_tokens:
            market_tokens[mid] = set()
            market_rows[mid] = []
        market_tokens[mid].add(token_id)
        market_rows[mid].append(row)

    # Pick market with most activity
    best_market = max(market_rows, key=lambda mid: len(market_rows[mid]))
    tokens = market_tokens[best_market]

    log.info(
        "Discovered market %s with %d tokens, %d rows",
        best_market[:16],
        len(tokens),
        len(market_rows[best_market]),
    )

    # Prefer real metadata from cache, then CLOB API
    cached = _MARKET_CACHE.get(best_market)
    if cached:
        log.info("Using cached metadata for %s", best_market[:16])
        return _adapt_metadata_for_testing(cached, hour)

    # Try CLOB API for real metadata
    clob = fetch_market_clob(best_market)
    if clob:
        _MARKET_CACHE.put(clob)
        log.info("Fetched CLOB API metadata for %s", best_market[:16])
        return _adapt_metadata_for_testing(clob, hour)

    # Fallback: fabricated metadata when neither cache nor API has this market
    log.warning("No API metadata for %s — using fabricated metadata", best_market[:16])
    token_list = []
    for i, tid in enumerate(sorted(tokens)):
        outcome = "Yes" if i == 0 else "No"
        token_list.append({"token_id": tid, "outcome": outcome})

    return {
        "condition_id": best_market,
        "question": f"Test market {best_market[:16]}",
        "minimum_tick_size": "0.01",
        "minimum_order_size": "1",
        "end_date_iso": "2027-12-31T00:00:00Z",
        "maker_base_fee": "0",
        "taker_base_fee": "0",
        "tokens": token_list,
    }


def discover_volatile_market(hour: str) -> dict:
    """Discover a volatile market from PMXT data.

    Reads all row groups and finds a market where max_bid > min_ask
    for at least one token (price moved enough for FOK wins).
    """
    url = file_url(hour)
    fs = fsspec.filesystem("http")
    f = fs.open(url)
    pf = pq.ParquetFile(f)

    # Track per-token price ranges grouped by market
    token_stats: dict[str, dict] = {}  # token_id -> {min_ask, max_bid, market_id}
    market_tokens: dict[str, set[str]] = {}

    for rg_idx in range(pf.metadata.num_row_groups):
        table = pf.read_row_group(rg_idx, columns=["market_id", "data"])
        for row in table.to_pylist():
            data = json.loads(row["data"])
            token_id = str(data.get("token_id", ""))
            if not token_id:
                continue
            best_bid = data.get("best_bid")
            best_ask = data.get("best_ask")
            if best_bid is None or best_ask is None:
                continue
            bid = float(best_bid)
            ask = float(best_ask)
            if bid <= 0 or ask <= 0:
                continue
            mid = row["market_id"]
            if mid not in market_tokens:
                market_tokens[mid] = set()
            market_tokens[mid].add(token_id)

            if token_id not in token_stats:
                token_stats[token_id] = {"min_ask": ask, "max_bid": bid, "market_id": mid}
            else:
                s = token_stats[token_id]
                s["min_ask"] = min(s["min_ask"], ask)
                s["max_bid"] = max(s["max_bid"], bid)
    f.close()

    # Find market with best gap (max_bid - min_ask) and 2+ tokens
    best_mid = None
    best_gap = 0.0
    for tid, stats in token_stats.items():
        mid = stats["market_id"]
        if len(market_tokens.get(mid, set())) < 2:
            continue
        gap = stats["max_bid"] - stats["min_ask"]
        if gap > best_gap:
            best_gap = gap
            best_mid = mid

    if best_mid is None:
        raise RuntimeError("No volatile market found in data")

    tokens = market_tokens[best_mid]
    log.info("Volatile market %s, gap=%.3f, %d tokens", best_mid[:16], best_gap, len(tokens))

    # Prefer real metadata from cache, then CLOB API
    cached = _MARKET_CACHE.get(best_mid)
    if cached:
        log.info("Using cached metadata for %s", best_mid[:16])
        return _adapt_metadata_for_testing(cached, hour)

    # Try CLOB API for real metadata
    clob = fetch_market_clob(best_mid)
    if clob:
        _MARKET_CACHE.put(clob)
        log.info("Fetched CLOB API metadata for %s", best_mid[:16])
        return _adapt_metadata_for_testing(clob, hour)

    # Fallback: fabricated metadata when neither cache nor API has this market
    log.warning("No API metadata for %s — using fabricated metadata", best_mid[:16])
    token_list = []
    for i, tid in enumerate(sorted(tokens)):
        outcome = "Yes" if i == 0 else "No"
        token_list.append({"token_id": tid, "outcome": outcome})

    return {
        "condition_id": best_mid,
        "question": f"Volatile market {best_mid[:16]}",
        "minimum_tick_size": "0.01",
        "minimum_order_size": "1",
        "end_date_iso": "2027-12-31T00:00:00Z",
        "maker_base_fee": "0",
        "taker_base_fee": "0",
        "tokens": token_list,
    }
