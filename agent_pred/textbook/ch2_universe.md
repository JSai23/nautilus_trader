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

## Market Discovery (`src/universe/gamma.py`)

Markets are discovered via the Gamma API at runtime. Define filters in the `universe:` section of experiment config YAMLs:

```yaml
# In configs/example_backtest.yml
universe:
  slug_contains: "bitcoin"       # client-side filter (API ignores slug queries)
  end_date_min: "2026-04-01"     # server-side (pushed to API)
  volume_min: 10000              # server-side (volume_num_min)
  active: true                   # server-side
  max_markets: 20                # pagination cap
```

Or use explicit `condition_ids:` for specific markets:
```yaml
condition_ids:
  - "0xabc123..."
```

Programmatic usage:
```python
from universe.gamma import MarketFilter, discover_markets

mf = MarketFilter(active=True, volume_num_min=10000, max_markets=20)
market_infos = discover_markets(mf)  # Always fresh from Gamma API
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

Tests cover instrument building from metadata.
