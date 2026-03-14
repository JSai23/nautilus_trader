# Chapter 3: Universe — Markets and Instruments

How Polymarket markets are discovered, resolved, and turned into tradeable NautilusTrader instruments.

## The Concept Chain

```
Market (Polymarket)
  │  identified by condition_id (hex string)
  │  has 2+ outcome tokens
  ▼
Token (Polymarket)
  │  identified by token_id (numeric string)
  │  represents one outcome (Yes or No)
  ▼
BinaryOption (NautilusTrader)
  │  identified by InstrumentId
  │  format: {token_id}-{condition_id_prefix}-{outcome}.POLYMARKET
  ▼
Tradeable instrument with orderbook, orders, positions
```

A Polymarket market like "Will Bitcoin reach $100k?" has a `condition_id` and two tokens: a Yes token and a No token. Each token is independently tradeable with its own orderbook. In NautilusTrader, each token becomes a separate `BinaryOption` instrument.

## Two Discovery Paths

Markets are resolved through one of two APIs depending on configuration.

### Path 1: Gamma API (Discovery)

Used when the config has `universe:` filters but no explicit `condition_ids`.

```yaml
# experiments/configs/my_strategy.yml
universe:
  slug_contains: "bitcoin"       # client-side (API doesn't support slug search)
  end_date_min: "2026-04-01"     # server-side (pushed to API query params)
  volume_min: 10000              # server-side
  active: true                   # server-side
  max_markets: 20                # pagination cap
```

```python
from universe.gamma import MarketFilter, discover_markets

mf = MarketFilter(
    active=True,
    volume_num_min=10000,
    slug_contains="bitcoin",
    max_markets=20,
)
market_infos = discover_markets(mf)  # list[dict] — normalized metadata
```

The Gamma API (`https://gamma-api.polymarket.com/markets`) supports server-side filtering on: `active`, `closed`, `end_date_min/max`, `start_date_min`, `volume_num_min`, `order`, `ascending`.

The API does NOT support filtering by slug or category — those are applied client-side after fetching. This means a `slug_contains: "bitcoin"` filter may need to paginate through many pages to find matches.

Results are always fresh — no caching. Markets change frequently; stale metadata causes silent bugs (wrong tick sizes, wrong token mappings, missing markets).

### Path 2: CLOB API (Direct Lookup)

Used when the config has explicit `condition_ids`.

```yaml
# experiments/configs/my_strategy.yml
condition_ids:
  - "0xabc123..."
  - "0xdef456..."
```

```python
from universe.gamma import fetch_market_clob

metadata = fetch_market_clob("0xabc123...")  # dict or None
```

The CLOB API (`https://clob.polymarket.com/markets/{condition_id}`) returns detailed metadata for a single market. This is simpler and faster when you know exactly which markets you want.

## Metadata Normalization

Both APIs return different JSON shapes. `gamma_to_metadata()` and `clob_to_metadata()` normalize them into a common format:

```python
{
    "condition_id": "0xabc123...",
    "question": "Will Bitcoin reach $100k?",
    "slug": "will-bitcoin-reach-100k",
    "category": "Crypto",
    "minimum_tick_size": "0.01",
    "minimum_order_size": "1",
    "end_date_iso": "2027-12-31T00:00:00Z",
    "maker_base_fee": "0",
    "taker_base_fee": "0",
    "tokens": [
        {"token_id": "12345...", "outcome": "Yes"},
        {"token_id": "67890...", "outcome": "No"},
    ],
}
```

A critical detail: the Gamma API returns `outcomes` and `clobTokenIds` as JSON-encoded arrays that are **positionally paired**. `outcomes[0]` corresponds to `clobTokenIds[0]`. `gamma_to_metadata()` preserves this pairing — earlier approaches that sorted token IDs lexicographically assigned Yes/No to the wrong tokens.

## Instrument Construction

`build_instrument_maps()` converts metadata dicts into NautilusTrader instruments:

```python
from universe.instruments import build_instrument_maps

instruments, instrument_ids, market_ids = build_instrument_maps(market_infos)

# instruments:     dict[str, BinaryOption]   — token_id → instrument
# instrument_ids:  dict[str, InstrumentId]   — token_id → NautilusTrader ID
# market_ids:      set[str]                  — condition_ids for PMXT filtering
```

Under the hood, this calls `parse_polymarket_instrument()` from NautilusTrader's Polymarket adapter — the same parser used in live trading, ensuring backtest and live use identical instruments.

The `market_ids` set is passed to the PMXT data pipeline to filter parquet data to only the markets being traded.

## The Instrument ID Format

```
{token_id}-{condition_id_prefix}-{outcome}.POLYMARKET
```

Example: `12345-0xabc123-Yes.POLYMARKET`

This format is defined by NautilusTrader's Polymarket adapter. The condition_id is truncated in the string representation but the full ID is stored on the instrument object.

## What Strategies See

After instrument construction, strategies receive a list of `InstrumentId` strings. The strategy can look up the full instrument from cache:

```python
instrument = self.cache.instrument(instrument_id)
# instrument.expiration_ns — market end date as nanosecond timestamp
```

Market metadata (question text, category, slug) is NOT stored on the instrument. If a strategy needs this information, it must be passed through strategy config params. The standard pattern is that this metadata is consumed during discovery and instrument construction, then discarded.
