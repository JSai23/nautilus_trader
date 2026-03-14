# Chapter 7: Paper and Live Trading

How the framework runs strategies against live Polymarket data with simulated execution and dynamic market discovery.

## Paper Trading

Paper trading uses real market data but simulated fills. The same strategy class that runs in backtests runs here — no code changes.

```bash
uv run python scripts/run_backtest.py experiments/configs/paper_tick.yml
```

The `scripts/run_backtest.py` entry point dispatches on `mode`:
- `mode: "backtest"` → `run_backtest()` (BacktestEngine + PMXT data)
- `mode: "paper"` → `run_paper()` (TradingNode + live WebSocket)

### Paper Config

```yaml
mode: "paper"

strategy:
  path: "experiments.strategies.momentum_drift:MomentumDrift"
  params:
    trade_size: 5.0
    check_interval_minutes: 1

condition_ids:
  - "0xabc123..."

starting_balance: 10000.0

paper:
  duration_seconds: 3600    # Run for 1 hour then stop

# Optional: enable dynamic discovery
discovery:
  poll_minutes: 5

universe:
  slug_contains: "bitcoin"
  active: true
  max_markets: 20
```

## Architecture

```
TradingNode
├── PolymarketDataClient     (live WebSocket → orderbook deltas)
├── SandboxExecutionClient   (simulated fills against live book)
├── MarketDiscoveryActor     (polls Gamma API for new markets)
└── YourStrategy             (same class as backtest)
```

### TradingNode

NautilusTrader's live trading runtime. Manages data clients, execution clients, strategies, and actors in an event loop.

### PolymarketDataClient

Connects to Polymarket's WebSocket feed for live orderbook data. Configured with `load_ids` — the set of instrument IDs to subscribe to initially.

### SandboxExecutionClient

Simulated execution that matches orders against the live orderbook. Orders fill at current book prices but no real money moves. Uses the same NETTING OMS and CASH account as backtests.

### MarketDiscoveryActor

The key addition for live trading. Periodically polls the Gamma API and publishes newly discovered instruments:

```
Timer fires (every N minutes)
  → _poll_gamma_api()        (runs in thread executor — HTTP is blocking)
  → _pending_markets = [...]  (thread writes results)

Next timer fires
  → _process_discovered_markets()  (main thread reads pending results)
  → skip known condition_ids
  → build_instruments_from_metadata()
  → msgbus.send("DataEngine.process", instrument)
    → DataEngine adds to cache
    → publishes on message bus
    → strategy.on_instrument() fires
```

The actor runs the HTTP call in a thread executor to avoid blocking the event loop. Results are picked up on the next timer tick. This means there's up to one poll interval of latency between a market appearing on the API and the strategy seeing it.

## Dynamic Instrument Flow

When `MarketDiscoveryActor` finds a new market, here's the full chain:

```
1. Actor polls Gamma API
   → new market with condition_id not in _known_condition_ids

2. Actor builds BinaryOption instruments from metadata
   → uses build_instruments_from_metadata() (same as backtest)

3. Actor publishes to DataEngine
   → msgbus.send("DataEngine.process", instrument)
   → DataEngine adds to cache + publishes to subscribers

4. Strategy receives on_instrument(instrument) callback
   → base class checks: is it from POLYMARKET? is it new?
   → if yes: appends to _instrument_ids
   → subscribes to orderbook data
   → calls on_new_instrument(instrument) for subclass handling

5. PolymarketDataClient subscribes to WebSocket channel
   → orderbook deltas start flowing for the new instrument

6. Strategy starts receiving on_order_book_deltas() for the new instrument
   → trading logic applies to newly discovered market
```

This means a paper trading session can start with 5 markets and grow to 25 as the actor discovers more matching the filter criteria.

## The Strategy's Perspective

From the strategy's point of view, the only difference between backtest and paper/live is:

| Aspect | Backtest | Paper/Live |
|--------|----------|------------|
| `_instrument_ids` at start | Fixed from config | Seed set, grows dynamically |
| `on_instrument()` | Never fires | Fires for new discoveries |
| Clock | Replayed timestamps | Real wall clock |
| Timer behavior | Fires at data timestamps | Fires at real intervals |
| `start_time_ns` / `end_time_ns` | Set (bounds timers) | Not set (timers unbounded) |
| `_data_ended` | Set 60s before end | Never set |

The runner handles these differences:
- For paper mode, `start_time_ns` and `end_time_ns` are removed from strategy params (live clock handles timing)
- `dynamic_instruments` is set to `True` if discovery is configured
- No PMXT data generator — data comes from the WebSocket client

## Duration and Shutdown

Paper trading runs for `paper.duration_seconds` (default: 3600 = 1 hour), then stops automatically via `signal.SIGALRM`. Can also be stopped manually with Ctrl-C.

```python
# Auto-stop after duration
signal.signal(signal.SIGALRM, _stop_handler)
signal.alarm(duration)

try:
    node.run()  # Blocks until stopped
except KeyboardInterrupt:
    log.info("Paper trading interrupted by user")
finally:
    signal.alarm(0)  # Cancel alarm
    node.dispose()
```

## Requirements

Paper trading requires Polymarket API credentials in environment variables (for the data client WebSocket connection). The specific variables depend on NautilusTrader's Polymarket adapter configuration. Backtest mode does not require credentials — it uses PMXT data directly.

## What's Not Here Yet

**Live trading with real execution.** The framework supports it architecturally — swap `SandboxExecutionClient` for `PolymarketExecutionClient` — but it's not wired up. The strategy class and discovery actor work identically; only the execution client changes.

**Paper trading metrics/tearsheet.** Unlike backtests, paper runs don't compute tearsheets automatically. The TradingNode doesn't have the same report generation pipeline. Adding this would require extracting positions and fills from the cache after the node stops.
