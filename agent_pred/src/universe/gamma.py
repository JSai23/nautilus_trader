"""Gamma API client for Polymarket market discovery.

Fetches real market metadata from https://gamma-api.polymarket.com/markets,
replacing the parquet-scanning hack that guessed Yes/No token assignments.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
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
    """Filter criteria for Gamma API market queries."""

    active: bool | None = None
    closed: bool | None = None
    categories: list[str] = field(default_factory=list)
    min_volume: float = 0.0
    max_markets: int = 50
    slug_contains: str | None = None


def fetch_markets(
    filter: MarketFilter | None = None,
    offset: int = 0,
    limit: int = _PAGE_SIZE,
) -> list[dict[str, Any]]:
    """Fetch markets from Gamma API with filtering.

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
    """Fetch markets with pagination, applying filters.

    Fetches up to filter.max_markets results, paginating through the API.
    Client-side filters (min_volume, categories, slug_contains) are applied
    after fetching since the Gamma API doesn't support all filter params.
    """
    results: list[dict[str, Any]] = []
    offset = 0

    while len(results) < filter.max_markets:
        batch = fetch_markets(filter=filter, offset=offset, limit=_PAGE_SIZE)
        if not batch:
            break

        for market in batch:
            if _matches_filter(market, filter):
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

    The CLOB API supports direct lookup by condition_id and returns data
    in our internal metadata format (no conversion needed).
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
    """Normalize CLOB API response to our internal metadata format.

    The CLOB API already uses our field names. We just normalize numeric
    fields to strings (to match what parse_polymarket_instrument expects)
    and extract the token fields we need.
    """
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


def _matches_filter(market: dict[str, Any], filter: MarketFilter) -> bool:
    """Apply client-side filters that the API doesn't support natively."""
    # Volume filter
    volume = market.get("volumeNum", 0) or 0
    if filter.min_volume and volume < filter.min_volume:
        return False

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


class GammaMarketCache:
    """Persistent JSON cache for Gamma API market metadata."""

    def __init__(self, cache_dir: Path):
        self._dir = cache_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def get(self, condition_id: str) -> dict[str, Any] | None:
        path = self._path(condition_id)
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return None

    def put(self, metadata: dict[str, Any]) -> Path:
        condition_id = metadata["condition_id"]
        path = self._path(condition_id)
        with open(path, "w") as f:
            json.dump(metadata, f, indent=2)
        return path

    def has(self, condition_id: str) -> bool:
        return self._path(condition_id).exists()

    def list_all(self) -> list[dict[str, Any]]:
        results = []
        for path in sorted(self._dir.glob("*.json")):
            with open(path) as f:
                results.append(json.load(f))
        return results

    def count(self) -> int:
        return len(list(self._dir.glob("*.json")))

    def delete(self, condition_id: str) -> bool:
        """Delete a cached market entry. Returns True if it existed."""
        path = self._path(condition_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def purge_fabricated(self) -> int:
        """Delete all cache entries with fabricated metadata.

        Fabricated entries have questions matching "Discovered market",
        "Test market", or "Volatile market" — produced by the old hack.
        """
        import re
        pattern = re.compile(r"^(Discovered|Test|Volatile) market")
        purged = 0
        for path in list(self._dir.glob("*.json")):
            try:
                with open(path) as f:
                    data = json.load(f)
                question = data.get("question", "")
                if pattern.match(question):
                    path.unlink()
                    purged += 1
            except (json.JSONDecodeError, OSError):
                # Corrupt file — purge it too
                path.unlink()
                purged += 1
        log.info("Purged %d fabricated cache entries", purged)
        return purged

    def _path(self, condition_id: str) -> Path:
        return self._dir / f"{condition_id}.json"


def discover_markets(
    filter: MarketFilter,
    cache: GammaMarketCache,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    """Discover markets via Gamma API and cache metadata.

    Returns list of metadata dicts in our internal format.
    If refresh=False, returns cached data for condition_ids that already exist.
    """
    raw_markets = fetch_all_markets(filter)
    results = []
    cached_count = 0
    new_count = 0

    for raw in raw_markets:
        condition_id = raw.get("conditionId", "")
        if not condition_id:
            continue

        if not refresh and cache.has(condition_id):
            metadata = cache.get(condition_id)
            cached_count += 1
        else:
            metadata = gamma_to_metadata(raw)
            cache.put(metadata)
            new_count += 1

        results.append(metadata)

    log.info(
        "Discovered %d markets (%d cached, %d new)",
        len(results),
        cached_count,
        new_count,
    )
    return results
