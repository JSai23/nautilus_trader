# Chapter 1: PMXT Data Pipeline

How historical Polymarket order book data flows from PMXT archive into NautilusTrader's BacktestEngine.

## Architecture

```
PMXT Archive (r2.pmxt.dev)
    │
    ▼  HTTP range requests (fsspec)
Reader (pmxt/reader.py)
    │  Streams row groups, filters by market_id
    ▼
Transformer (pmxt/transformer.py)
    │  PMXT JSON → OrderBookDelta / OrderBookDeltas
    ▼
Generator (pmxt/generator.py)
    │  Yields sorted list[Data] batches
    ▼
BacktestEngine.add_data_iterator("pmxt", gen)
```

## Data Source

PMXT publishes hourly parquet files at `https://r2.pmxt.dev/polymarket_orderbook_{hour}.parquet`.

Each file contains ~1M rows with columns: `market_id`, `update_type`, `data`, `timestamp_received`.

The `data` column is a JSON string with two shapes:
- **price_change**: single order book level update (price, size, side)
- **book_snapshot**: full L2 snapshot (bids + asks arrays)

## Reader (`src/pmxt/reader.py`)

Streams remote parquet files via fsspec HTTP range requests — never downloads the full file.

```python
from pmxt.reader import read_remote_filtered

# Stream rows for specific markets from a specific hour
market_ids = {"0xabc123...", "0xdef456..."}
for batch in read_remote_filtered("2026-03-09T09", market_ids):
    for row in batch:
        process(row)
```

**Key design**: processes one row group at a time (~1M rows, ~50MB). PyArrow `compute.is_in()` filters rows to target markets before converting to Python dicts.

### Caching

```python
from pmxt.reader import cache_filtered_data

# Download filtered data for specific markets, save per-market parquet files
cached = cache_filtered_data("2026-03-09T09", market_ids, cache_dir=Path("data/pmxt/cache"))
# Returns: {market_id: Path} mapping
```

Cached files are small (filtered to single market) and fast to read back.

## Transformer (`src/pmxt/transformer.py`)

Converts PMXT JSON rows into NautilusTrader order book types.

| PMXT type | NautilusTrader type | Details |
|-----------|-------------------|---------|
| `price_change` | `OrderBookDelta` | UPDATE or DELETE (size=0). F_LAST always set. |
| `book_snapshot` | `OrderBookDeltas` | CLEAR + ADD per level. F_LAST on final delta. |

Critical details:
- **Timestamp**: PMXT `data.timestamp` is unix seconds (float) → nanos via `int(ts * 1e9)`
- **order_id**: Always 0 (L2 data, matches live adapter)
- **F_LAST flag**: Must be set on the last delta of every batch for BacktestEngine book processing

```python
from pmxt.transformer import transform_row

result = transform_row(row, instruments, instrument_ids)
# Returns OrderBookDelta, OrderBookDeltas, or None (if token_id unknown)
```

## Generator (`src/pmxt/generator.py`)

Wraps reader + transformer into a generator compatible with `BacktestEngine.add_data_iterator()`.

```python
from pmxt.generator import pmxt_data_generator

gen = pmxt_data_generator(
    market_ids=market_ids,
    hours=["2026-03-09T09", "2026-03-09T10"],
    instruments=instruments,       # dict[token_id, BinaryOption]
    instrument_ids=instrument_ids, # dict[token_id, InstrumentId]
    cache_dir=Path("data/pmxt/cache"),
)

engine.add_data_iterator("pmxt", gen)
```

Processes hours in order. Within each hour, yields sorted `list[Data]` batches (sorted by `ts_init` for BacktestEngine ordering).

## Data Index (`src/pmxt/index.py`)

JSON-based index tracking which markets/hours are cached locally.

```python
from pmxt.index import PMXTIndex

index = PMXTIndex(Path("data/pmxt/index.json"))
index.has_data("0xabc123", "2026-03-09T09")  # True/False
index.register("0xabc123", "2026-03-09T09", cached_path)
```

## Server Constraints

- **Never load a full PMXT file into memory.** Always stream row groups.
- **Cache filtered subsets only.** Raw files are ~500MB; filtered per-market files are ~1MB.
- **Process one row group at a time.** Each group is ~50MB in memory.

## Testing

```bash
# Fast tests (no network):
uv run pytest tests/test_transformer.py -v

# Real HTTP tests (~30s each):
uv run pytest tests/test_pmxt_reader.py -v
```
