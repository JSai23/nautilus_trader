"""Gamma API client for Polymarket market discovery.

Fetches market metadata from https://gamma-api.polymarket.com/markets.
No caching — always fetches fresh data. Markets change; stale metadata
causes silent bugs.

Server-side filters (pushed to API): active, closed, end_date_min/max,
start_date_min, volume_num_min, order, ascending.

Client-side filters (API ignores these): slug_contains, categories.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
GAMMA_MARKETS_ENDPOINT = f"{GAMMA_API_BASE}/markets"
CLOB_API_BASE = "https://clob.polymarket.com"

# Default page size for Gamma API pagination
_PAGE_SIZE = 100


@dataclass
class MarketFilter:
    """Filter criteria for Gamma API market queries.

    Server-side params are sent as query params to the Gamma API.
    Client-side params are applied after fetching because the API ignores them.
    """

    # Server-side filters
    active: bool | None = None
    closed: bool | None = None
    end_date_min: str | None = None  # ISO date, e.g. "2026-04-01"
    end_date_max: str | None = None
    start_date_min: str | None = None
    volume_num_min: float | None = None
    order: str | None = None  # camelCase field name, e.g. "volumeNum"
    ascending: bool | None = None

    # Client-side filters (API doesn't support these)
    slug_contains: str | None = None
    categories: list[str] = field(default_factory=list)

    # Pagination cap
    max_markets: int = 50


def fetch_markets(
    filter: MarketFilter | None = None,
    offset: int = 0,
    limit: int = _PAGE_SIZE,
) -> list[dict[str, Any]]:
    """Fetch markets from Gamma API with server-side filtering.

    Returns raw Gamma API market dicts.
    """
    params: dict[str, str] = {
        "limit": str(min(limit, _PAGE_SIZE)),
        "offset": str(offset),
    }
    if filter:
        if filter.active is not None:
            params["active"] = str(filter.active).lower()
        if filter.closed is not None:
            params["closed"] = str(filter.closed).lower()
        if filter.end_date_min:
            params["end_date_min"] = filter.end_date_min
        if filter.end_date_max:
            params["end_date_max"] = filter.end_date_max
        if filter.start_date_min:
            params["start_date_min"] = filter.start_date_min
        if filter.volume_num_min is not None and filter.volume_num_min > 0:
            params["volume_num_min"] = str(filter.volume_num_min)
        if filter.order:
            params["order"] = filter.order
        if filter.ascending is not None:
            params["ascending"] = str(filter.ascending).lower()

    url = f"{GAMMA_MARKETS_ENDPOINT}?{urlencode(params)}"
    log.debug("Fetching %s", url)

    req = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "agent-pred/0.1",
    })
    with urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())

    if not isinstance(data, list):
        log.warning("Unexpected Gamma API response type: %s", type(data))
        return []

    return data


def fetch_all_markets(filter: MarketFilter) -> list[dict[str, Any]]:
    """Fetch markets with pagination, applying client-side filters.

    Server-side filters are handled by fetch_markets().
    Client-side filters (slug_contains, categories) are applied here.
    Fetches up to filter.max_markets results.
    """
    results: list[dict[str, Any]] = []
    offset = 0

    while len(results) < filter.max_markets:
        batch = fetch_markets(filter=filter, offset=offset, limit=_PAGE_SIZE)
        if not batch:
            break

        for market in batch:
            if _matches_client_filter(market, filter):
                results.append(market)
                if len(results) >= filter.max_markets:
                    break

        offset += len(batch)

        # Safety: stop if we got fewer than a full page (no more data)
        if len(batch) < _PAGE_SIZE:
            break

    log.info("Fetched %d markets from Gamma API (offset reached %d)", len(results), offset)
    return results


def fetch_market_clob(condition_id: str) -> dict[str, Any] | None:
    """Fetch a single market's metadata from the CLOB API.

    Returns None if the market is not found or the request fails.
    """
    url = f"{CLOB_API_BASE}/markets/{condition_id}"
    log.debug("Fetching CLOB API: %s", url)

    req = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "agent-pred/0.1",
    })
    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        log.warning("CLOB API fetch failed for %s: %s", condition_id[:16], e)
        return None

    if not isinstance(data, dict) or "condition_id" not in data:
        log.warning("Unexpected CLOB API response for %s", condition_id[:16])
        return None

    return clob_to_metadata(data)


def clob_to_metadata(clob: dict[str, Any]) -> dict[str, Any]:
    """Normalize CLOB API response to our internal metadata format."""
    tokens = []
    for t in clob.get("tokens", []):
        tokens.append({
            "token_id": str(t["token_id"]),
            "outcome": t["outcome"],
        })

    return {
        "condition_id": clob["condition_id"],
        "question": clob.get("question", ""),
        "slug": clob.get("market_slug", ""),
        "category": "",
        "minimum_tick_size": str(clob.get("minimum_tick_size", "0.01")),
        "minimum_order_size": str(clob.get("minimum_order_size", "1")),
        "end_date_iso": clob.get("end_date_iso", ""),
        "maker_base_fee": str(clob.get("maker_base_fee", "0")),
        "taker_base_fee": str(clob.get("taker_base_fee", "0")),
        "tokens": tokens,
        "active": clob.get("active", False),
        "closed": clob.get("closed", False),
    }


def _matches_client_filter(market: dict[str, Any], filter: MarketFilter) -> bool:
    """Apply client-side filters the API doesn't support natively."""
    # Category filter
    if filter.categories:
        category = (market.get("category") or "").lower()
        if not any(c.lower() in category for c in filter.categories):
            return False

    # Slug substring filter
    if filter.slug_contains:
        slug = market.get("slug") or ""
        if filter.slug_contains.lower() not in slug.lower():
            return False

    # Must have clobTokenIds to be useful for trading
    clob_tokens_raw = market.get("clobTokenIds")
    if not clob_tokens_raw:
        return False

    return True


def gamma_to_metadata(market: dict[str, Any]) -> dict[str, Any]:
    """Convert a Gamma API market dict to our internal metadata format.

    The key fix: outcomes and clobTokenIds are positionally paired,
    giving us the CORRECT Yes/No token assignment instead of guessing
    by lexicographic sort.
    """
    condition_id = market.get("conditionId", "")

    # Parse JSON-encoded arrays
    outcomes_raw = market.get("outcomes", "[]")
    tokens_raw = market.get("clobTokenIds", "[]")

    outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
    token_ids = json.loads(tokens_raw) if isinstance(tokens_raw, str) else tokens_raw

    # Build tokens with correct outcome mapping (positional pairing)
    tokens = []
    for i, token_id in enumerate(token_ids):
        outcome = outcomes[i] if i < len(outcomes) else f"Outcome_{i}"
        tokens.append({"token_id": str(token_id), "outcome": outcome})

    # Extract tick size and order size from Gamma fields
    tick_size = str(market.get("orderPriceMinTickSize", "0.01"))
    order_min_size = str(market.get("orderMinSize", "1"))

    return {
        "condition_id": condition_id,
        "question": market.get("question", ""),
        "slug": market.get("slug", ""),
        "category": market.get("category", ""),
        "minimum_tick_size": tick_size,
        "minimum_order_size": order_min_size,
        "end_date_iso": market.get("endDate", ""),
        "maker_base_fee": "0",
        "taker_base_fee": "0",
        "tokens": tokens,
        "volume": market.get("volumeNum", 0),
        "active": market.get("active", False),
        "closed": market.get("closed", False),
        "fees_enabled": market.get("feesEnabled", False),
    }


def discover_markets(filter: MarketFilter) -> list[dict[str, Any]]:
    """Discover markets via Gamma API and convert to internal metadata format.

    No caching — always fetches fresh data. Returns list of metadata dicts.
    """
    raw_markets = fetch_all_markets(filter)
    results = []

    for raw in raw_markets:
        condition_id = raw.get("conditionId", "")
        if not condition_id:
            continue
        results.append(gamma_to_metadata(raw))

    log.info("Discovered %d markets from Gamma API", len(results))
    return results
