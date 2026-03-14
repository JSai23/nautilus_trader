# Chapter 2: The Data Pipeline

How historical Polymarket orderbook data flows from PMXT archive into NautilusTrader's BacktestEngine.

## PMXT: The Data Source

[PMXT](https://r2.pmxt.dev) publishes hourly parquet files containing every orderbook update across all Polymarket markets:

```
https://r2.pmxt.dev/polymarket_orderbook_2026-03-09T09.parquet
```

Each file is ~500MB with ~1M rows. Columns:

| Column | Type | Example |
|--------|------|---------|
| `market_id` | string | `"0xabc123..."` (condition_id) |
| `update_type` | string | `"price_change"` or `"book_snapshot"` |
| `data` | JSON string | Orderbook update payload |
| `timestamp_received` | float | Unix epoch seconds |

The `data` column contains two shapes:

**price_change** — a single level update:
```json
{"price": "0.55", "size": "100", "side": "BUY", "timestamp": 1741510800.123}
```

**book_snapshot** — full L2 state:
```json
{"bids": [["0.55", "100"], ...], "asks": [["0.56", "50"], ...], "timestamp": 1741510800.456}
```

## The Pipeline

```
PMXT Archive (r2.pmxt.dev)
    │
    ▼  HTTP range requests (fsspec)
Reader (src/pmxt/reader.py)
    │  Streams row groups, filters by market_id
    ▼
Transformer (src/pmxt/transformer.py)
    │  PMXT JSON → OrderBookDelta / OrderBookDeltas
    ▼
Generator (src/pmxt/generator.py)
    │  Yields sorted list[Data] batches per hour
    ▼
BacktestEngine.add_data_iterator("pmxt", gen)
```

### Reader

The reader streams remote parquet files via fsspec HTTP range requests. It never downloads the full file — it processes one row group at a time (~50MB in memory).

```python
from pmxt.reader import read_remote_filtered

# Stream rows for specific markets from one hour
for batch in read_remote_filtered("2026-03-09T09", market_ids):
    for row in batch:
        process(row)
```

PyArrow's `compute.is_in()` filters to target markets within each row group. Out of ~1M rows per file, you typically need a few thousand for your specific markets.

**Caching**: Filtered subsets can be saved locally as per-market parquet files (~1MB each vs 500MB raw). The `PMXTIndex` (`src/pmxt/index.py`) tracks what's cached.

### Transformer

Converts raw PMXT rows into NautilusTrader types:

| PMXT type | NautilusTrader type | What it represents |
|-----------|--------------------|--------------------|
| `price_change` | `OrderBookDelta` | Single level UPDATE or DELETE (size=0) |
| `book_snapshot` | `OrderBookDeltas` | CLEAR + one ADD per level |

Three details that matter:

1. **Timestamps**: PMXT `data.timestamp` is unix seconds (float) → converted to nanoseconds via `int(ts * 1e9)`. This becomes `ts_init` on the NautilusTrader data object — the timestamp the engine uses for ordering.

2. **order_id = 0**: PMXT is L2 data (price levels, not individual orders). All deltas use `order_id=0`, which matches the Polymarket live adapter.

3. **F_LAST flag**: The last delta in every batch must have `flags = RecordFlag.F_LAST`. This tells BacktestEngine's book processing "this batch is complete, update the book now." Without it, the engine buffers deltas indefinitely.

### Generator

Wraps reader + transformer into a generator that BacktestEngine can consume:

```python
from pmxt.generator import pmxt_data_generator

gen = pmxt_data_generator(
    market_ids=market_ids,          # set of condition_ids to filter
    hours=["2026-03-09T09", "2026-03-09T10"],
    instruments=instruments,         # dict[token_id, BinaryOption]
    instrument_ids=instrument_ids,   # dict[token_id, InstrumentId]
    cache_dir=Path("data/pmxt/cache"),
)

engine.add_data_iterator("pmxt", gen)
```

Hours are processed in order. Within each hour, events are sorted by `ts_init` to maintain chronological ordering for the engine.

## Why Streaming Matters

PMXT files are large. Loading one into memory would consume ~2GB. The pipeline avoids this by:

1. **Reader**: processes one row group at a time (fsspec range requests)
2. **Filter**: drops rows not matching target markets (typically 99%+ of data)
3. **Transform**: converts in-place to NautilusTrader types
4. **Yield**: generator yields sorted batches, not the full dataset

This means you can backtest against many hours of data without memory problems. The bottleneck is network bandwidth for uncached data, not memory.

## The Data-to-Engine Contract

`BacktestEngine.add_data_iterator()` is the integration point. It accepts any generator yielding `list[Data]`. Each list must be sorted by `ts_init` — the engine processes events in timestamp order.

There's a subtlety: `add_data_iterator()` doesn't populate the engine's internal `_data` list. This means the engine can't infer start/end times from the data. The runner must pass explicit `start` and `end` to `engine.run()` — without them, the engine defaults `start_ns=0` (Unix epoch), and any `set_timer()` calls in strategies will fire millions of times trying to catch up from 1970 to the actual data timestamps.

This was the source of a significant bug early in development. See the runner chapter for how it's handled.
