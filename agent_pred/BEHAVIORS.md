# Framework Behaviors

Everything the agent_pred framework must support. Each behavior has a status and verification criteria.

## Universe

### Backtest Discovery
Gamma API fetch of all markets → client-side slug filter → pre-determined universe of instruments.
Config YAML `universe: slug_contains: "btc-updown-15m"` → `discover_markets()` → `build_instrument_maps()`.

### Paper/Live Discovery
Same Gamma API slug matching, but polling on a timer (`MarketDiscoveryActor`). Detects new open markets, builds instruments, publishes to DataEngine cache, notifies strategy via `on_instrument()`, subscribes to orderbook WebSocket feeds. Runs continuously — markets come and go.

### Universe Cross-Validation
Compare discovered universe against external source (pm cli, direct Gamma API curl) to verify we are picking up ALL matching markets and not silently dropping any.

---

## Data

### Backtest Data
PMXT historical orderbook parquets. Every orderbook snapshot pushed through the engine as `OrderBookDeltas`.

### Live Data
Polymarket WebSocket feed (`wss://ws-subscriptions-clob.polymarket.com`). Public, no auth needed. MARKET channel subscriptions by token_id.

### Top-of-Book Storage
Strategy accumulates (timestamp_ns, instrument_id, best_bid, best_ask, bid_qty, ask_qty) into a DataFrame on each tick. Configurable (off by default for performance). Saved as CSV/parquet artifact after run. NOT full orderbook depth — just BBO.

---

## Strategy Features

### Market Metadata Map
`self._market_meta: dict[InstrumentId, MarketMeta]` in base strategy. Contains slug, condition_id, token_id, outcome (Yes/No), question, start_date, end_date. Hydrated on `on_start()` for backtest instruments, on `on_instrument()` for live-discovered instruments. Enables strategy logic like: parse slug timestamp → determine active 15m window → only trade that window.

### on_instrument
Fires when `MarketDiscoveryActor` publishes a new instrument (paper/live mode with `dynamic_instruments=True`). Strategy auto-subscribes to orderbook data and adds to instrument list.

### on_timer (on_interval)
Recurring timer at configurable interval (e.g., every 1 minute). Bounded by start_time_ns/end_time_ns to avoid epoch-start spam. Strategy checks all instruments each tick.

### on_tick (on_order_book_deltas)
Fires on every orderbook update. High frequency — hundreds to thousands per instrument per hour. Must call `super()` for exit condition checks.

### Exit Lifecycle
Base class handles exits automatically:
- **Resolution timer**: exits N seconds before instrument expiration
- **Convergence**: exits when mid-price approaches 0 or 1 (market resolving)
- **Take-profit / Stop-loss**: exits on unrealized PnL thresholds
- **End-of-data**: exits all positions 60s before data window ends (backtest)
All exits use FOK limit orders at best bid/ask.

---

## Order Fill Handling

### FOK Order Mechanics
All orders are Fill-Or-Kill limit orders. The sim executor (backtest matching engine) matches against the L2 book and REJECTS (cancels) FOK orders when there's insufficient liquidity. Not a "fill everything" simulator.

### Order Callbacks
Base strategy must have `on_order_filled()`, `on_order_canceled()` with logging. Track: orders submitted vs filled vs rejected, fill prices vs book state, round-trip accounting (every buy eventually has a sell).

---

## Tracking & Observability

### MLflow (Backtest + Paper)
Both backtest AND paper trading log to MLflow. MLflow serves as a live dashboard for running strategies.
- **Hierarchy**: experiment → parent run (variant) → child run (individual execution)
- **Metrics**: all tearsheet fields (PnL, win_rate, sharpe, drawdown, etc.)
- **Params**: strategy config, universe filters, data hours
- **Tags**: git_sha, strategy name, market slugs
- **Run name**: meaningful format like `TickAlways_6m_2026-03-13T10..T12`

### MLflow Artifacts
Saved in results/ and uploaded as MLflow artifacts:
- **PnL curve**: cumulative PnL over time (PNG or HTML)
- **Position timeline**: Gantt chart showing when each position was open (instrument on Y, time on X)
- **Instrument lifecycle**: Gantt showing each instrument's existence from first to last data point
- **Trade distribution**: histogram of PnL per trade
- **Top-of-book CSV**: if recording enabled
- **Raw data**: orders.csv, fills.csv, positions.csv, tearsheet.json, metadata.json

### Labeling
ALL visualizations, metrics, and artifacts use **slug + condition_id** for instrument identification. Never bare condition_id hex strings. Example: `btc-updown-15m-1773493200 (0x0a00bb30...)` not `0x0a00bb3094f3edef14...`.

### Heartbeat
status.json updated periodically during execution (every 60s or every N trades) with current trade count, PnL, timestamp. Handles the case where a run gets killed — last heartbeat time shows when it died, not just "started".

### Strategy Logging
Every lifecycle function in base strategy logs with context:
- `on_start()`: instruments subscribed, timer config, exit thresholds
- `on_instrument()`: slug, condition_id, token_id, outcome
- `on_interval()`: timestamp, instrument count, active/exiting/closed counts (periodic, not every tick)
- `on_order_book_deltas()`: periodic summary (every Nth tick) with bid/ask/spread
- `_trigger_exit()`: reason, position size, unrealized PnL
- `on_order_filled()`: fill price, quantity, side
- `on_order_canceled()`: rejection reason, order details

---

## Validation

### Reality Checks
After every backtest:
- Opens match closes (every buy has a sell or is still open at end)
- Fill prices within bid/ask spread at time of fill
- Tearsheet metrics align with raw fills
- Round trips = closed positions count

### Universe Validation
Cross-validate discovered markets against Gamma API or pm cli. Confirm: no markets silently dropped, slug filtering matches expected pattern, correct token count per market.

### Test Strategies
`tick_always` and `timer_always` are the baseline test harnesses. They just trade — no signals. All testing uses these or copies of them. Future strategies build on top.
