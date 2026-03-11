# Chapter 2: Universe Management

How to define, resolve, and construct tradeable instruments from Polymarket markets.

## Concepts

| Term | Meaning |
|------|---------|
| **Market** | A Polymarket prediction market (identified by `condition_id`) |
| **Token** | An outcome token (Yes/No) within a market, identified by `token_id` |
| **Instrument** | A NautilusTrader `BinaryOption` built from a token |
| **Universe** | A set of markets selected for trading/backtesting |

Each market has 2+ tokens (typically Yes and No). Each token becomes a separate `BinaryOption` instrument in NautilusTrader.

## Universe Config (`src/universe/config.py`)

Define universes in YAML:

```yaml
# configs/universes/crypto_hourly.yml
universe_id: "crypto-hourly"
description: "Crypto markets with hourly resolution"
selection:
  slugs:
    - "will-bitcoin-*"
    - "will-ethereum-*"
  condition_ids:
    - "0xabc123..."
period:
  start: "2026-03-01"
  end: "2026-03-10"
```

Parse with:
```python
from universe.config import UniverseConfig

config = UniverseConfig.from_yaml(Path("configs/universes/crypto_hourly.yml"))
```

## Instrument Building (`src/universe/instruments.py`)

Build NautilusTrader instruments from market metadata:

```python
from universe.instruments import build_instrument_maps

# market_infos: list of dicts with condition_id, tokens, tick_size, etc.
instruments, instrument_ids, market_ids = build_instrument_maps(market_infos)

# instruments: dict[token_id, BinaryOption]
# instrument_ids: dict[token_id, InstrumentId]
# market_ids: set[condition_id]  — used for PMXT filtering
```

Uses `parse_polymarket_instrument()` from the NautilusTrader Polymarket adapter — same parsing as live trading.

### Market Metadata Format

```json
{
  "condition_id": "0xabc123...",
  "question": "Will Bitcoin reach $100k?",
  "minimum_tick_size": "0.01",
  "minimum_order_size": "1",
  "end_date_iso": "2027-12-31T00:00:00Z",
  "maker_base_fee": "0",
  "taker_base_fee": "0",
  "tokens": [
    {"token_id": "12345...", "outcome": "Yes"},
    {"token_id": "67890...", "outcome": "No"}
  ]
}
```

## Universe Resolver (`src/universe/resolver.py`)

Resolves a `UniverseConfig` to concrete `condition_ids` — expanding slug patterns via the Gamma API.

```python
from universe.resolver import UniverseResolver

resolver = UniverseResolver(metadata_cache_dir=Path("data/markets"))
instruments, instrument_ids, market_ids = resolver.resolve_from_config(config)
# Returns (instruments dict, instrument_ids dict, market_ids set)
```

## Instrument ID Format

NautilusTrader instruments are identified by `InstrumentId`:
```
{token_id}-{condition_id_prefix}-{outcome}.POLYMARKET
```

Example: `12345-0xabc123-Yes.POLYMARKET`

## Testing

```bash
uv run pytest tests/test_universe.py -v
```

Tests cover YAML parsing, instrument building from metadata, and resolver logic.
