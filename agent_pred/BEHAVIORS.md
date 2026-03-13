# Framework Behaviors

Everything the agent_pred framework must support. Each behavior has a status and verification criteria.

**Status key:** PASS = verified with real evidence, UNVERIFIED = code exists but not tested, FAIL = broken

## Universe

### Backtest Discovery — PASS
Gamma API fetch of all markets → client-side slug filter → pre-determined universe of instruments.
Config YAML `universe: slug_contains: "btc-updown-15m"` → `discover_markets()` → `build_instrument_maps()`.

**Evidence:** 3 btc-updown-4h markets discovered, 6 instruments (Up/Down each), cross-validated against direct Gamma API.

### Paper/Live Discovery — PASS
Same Gamma API slug matching, but polling on a timer (`MarketDiscoveryActor`). Detects new open markets, builds instruments, publishes to DataEngine cache, notifies strategy via `on_instrument()`, subscribes to orderbook WebSocket feeds. Runs continuously — markets come and go.

**Evidence (run ce5c096f, 20-min session):**
- Initial poll: 3 markets (1773438300, 1773439200, 1773440100)
- Window rotation at ~22:00 UTC: `discover_current_windows()` returns new market 1773441000
- `Discovered new instrument: 0x9da3fe51...` (2 instruments: Up + Down)
- `Published 2 new instruments (total known: 4 conditions)`
- `on_instrument: dynamic discovery — btc-updown-15m-1773441000 outcome=Down/Up`
- `SimulatedExchange: Added instrument ... and created matching engine`

### Universe Cross-Validation — PASS (backtest), PASS (paper)
Compare discovered universe against external source (pm cli, direct Gamma API curl) to verify we are picking up ALL matching markets and not silently dropping any.

**Evidence (backtest):** 3/3 markets consistent with direct Gamma API curl.
**Evidence (paper):** 3/3 current-window markets discovered via `discover_current_windows()`, cross-validated against direct Gamma API.

---

## Data

### Backtest Data — PASS
PMXT historical orderbook parquets. Every orderbook snapshot pushed through the engine as `OrderBookDeltas`.

**Evidence:** 432 ticks over 2h, realistic bid/ask values.

### Live Data — PASS
Polymarket WebSocket feed (`wss://ws-subscriptions-clob.polymarket.com`). Public, no auth needed. MARKET channel subscriptions by token_id.

**Evidence (run c23781eb):** 24,770 ticks in 120s (~206/sec). Real bid/ask prices (0.12-0.77). 6 instrument subscriptions active.

### Top-of-Book Storage — PASS
Strategy accumulates (timestamp_ns, instrument_id, best_bid, best_ask, bid_qty, ask_qty) into a DataFrame on each tick. Configurable (off by default for performance). Saved as CSV/parquet artifact after run. NOT full orderbook depth — just BBO.

**Evidence:** 432 records saved, timestamps monotonic, 0 < bid < ask < 1.

---

## Strategy Features

### Market Metadata Map — PASS (backtest + paper)
`self._market_meta: dict[InstrumentId, MarketMeta]` in base strategy. Contains slug, condition_id, token_id, outcome (Yes/No), question, start_date, end_date. Hydrated on `on_start()` for backtest instruments, on `on_instrument()` for live-discovered instruments. Enables strategy logic like: parse slug timestamp → determine active 15m window → only trade that window.

**Evidence (backtest):** All 6 instruments have full metadata. `slug_timestamp()` and `is_active_at()` verified.
**Evidence (paper):** 6 instruments with metadata: `meta: btc-updown-15m-1773435600 (0xb5e23443...) | outcome=Up token=...`

### on_instrument — PASS
Fires when `MarketDiscoveryActor` publishes a new instrument (paper/live mode with `dynamic_instruments=True`). Strategy auto-subscribes to orderbook data and adds to instrument list. Cache-polling workaround (10s timer) since Polymarket adapter doesn't implement `_subscribe_instruments`.

**Evidence (run ce5c096f):**
- Initial: 6 instruments hydrated with full metadata on `on_start()`
- Dynamic: `on_instrument: dynamic discovery — btc-updown-15m-1773441000 (0x9da3fe51...) outcome=Down`
- `on_instrument: dynamic discovery — btc-updown-15m-1773441000 (0x9da3fe51...) outcome=Up`
- Both Up and Down tokens for new market discovered and subscribed

### on_timer (on_interval) — PASS
Recurring timer at configurable interval (e.g., every 1 minute). Bounded by start_time_ns/end_time_ns to avoid epoch-start spam. Strategy checks all instruments each tick.

**Evidence:** ~120 callbacks/2h at 1-min interval. Timer fires within start/end bounds.

### on_tick (on_order_book_deltas) — PASS (backtest + paper)
Fires on every orderbook update. High frequency — hundreds to thousands per instrument per hour. Must call `super()` for exit condition checks.

**Evidence (backtest):** 432 ticks/2h. Both singular and plural handlers working.
**Evidence (paper):** 20,390-39,187 ticks in 120s. Real-time BTC price data flowing through callbacks.

### Exit Lifecycle — PARTIAL
Base class handles exits automatically:
- **Resolution timer** — PASS: exits N seconds before instrument expiration. Verified with test_resolution.yml.
- **Convergence** — PASS: exits when mid-price approaches 0 or 1. Verified with test_convergence.yml (34 exits).
- **Take-profit / Stop-loss** — UNVERIFIED: needs volatile data producing PnL movement.
- **End-of-data** — PASS: exits all positions 60s before data window ends. Verified in tick_always 2h run.
All exits use FOK limit orders at best bid/ask.

---

## Order Fill Handling

### FOK Order Mechanics — PASS
All orders are Fill-Or-Kill limit orders. The sim executor (backtest matching engine) matches against the L2 book and REJECTS (cancels) FOK orders when there's insufficient liquidity.

**Evidence:** 68 fills, 0 rejections (100% fill rate on 4h data with good liquidity).

### Order Callbacks — PASS
Base strategy has `on_order_filled()`, `on_order_canceled()`, `on_order_rejected()` with logging. Track: orders submitted vs filled vs rejected, fill prices vs book state, round-trip accounting.

**Evidence:** 34 buys = 34 sells, all BUY@0.51 <= ask, all SELL@0.49 >= bid.

---

## Tracking & Observability

### MLflow (Backtest) — PASS
Experiment/parent/child hierarchy. Metrics, params, tags, run name all logged.

**Evidence:** `experiment=testing, variant=tick-always, run_id=7640d8a1, git_sha=f9aff2387023`

### MLflow (Paper) — UNVERIFIED
Paper trading must have SAME MLflow integration. MLflow serves as live dashboard.
- Periodic metric updates DURING execution (not just at end)
- Same artifacts as backtest
- Heartbeat updates visible in MLflow tags

**Needs:** Paper run showing MLflow logging during execution.

### MLflow Artifacts — PASS
4 PNGs generated: PnL curve (39KB), position timeline (18KB), trade distribution (17KB), instrument lifecycle (22KB). All use slug+condition_id labels.

### Labeling — PASS
All visualizations, metrics, and artifacts use slug + condition_id. Never bare hex.

**Evidence:** `btc-updown-4h-1773475200 (0xd114df49...)` format everywhere.

### Heartbeat — PASS
status.json updated every 60s with fills, ticks, instruments, active count.

**Evidence:** 120 heartbeat lines in 2h, progression from 0 to 68 fills.

### Strategy Logging — PASS
Every lifecycle function logs with context: on_start, on_instrument, on_interval (periodic), on_tick (periodic), _trigger_exit, on_order_filled, on_order_canceled.

---

## Validation

### Reality Checks — PASS
- Opens match closes: 34 buys = 34 sells
- Fill prices within bid/ask spread: verified
- Tearsheet PnL matches fills: diff=0.0000
- Round trips = closed positions count

### Universe Validation — PASS (backtest)
Cross-validated 3/3 markets against Gamma API.

### Test Strategies — PASS
`tick_always` and `timer_always` are baseline test harnesses. Both produce fills on real data.

### Unit Tests — PASS
81/81 tests pass (5:25).

---

## Paper Trading Specific

### Credential Bypass — PASS
Dummy credentials work for MARKET WebSocket and L0 API calls (public, no auth).
Node builds and starts without POLYMARKET_API_KEY or other env vars.

**Evidence:** TradingNode starts, instruments load from CLOB API, WebSocket connects — all with dummy private_key, funder, api_key, api_secret, passphrase.

### WebSocket Connection — PASS
MARKET WebSocket connects to `wss://ws-subscriptions-clob.polymarket.com/ws/market` and receives live orderbook data.

**Evidence (run c23781eb):** 24,770 ticks in 120s (~206 ticks/sec). Real bid/ask prices (0.12-0.77 range). 6 instrument subscriptions active.

### Live Orderbook Flow — PASS
`on_order_book_deltas` fires on every WebSocket update. Strategy processes real-time book data.

**Evidence:** `on_tick #48000: btc-updown-15m-1773433800 (0x872a5229...) bid=0.12 ask=0.13` — prices move with real BTC price action during the 15-minute window.

### MarketDiscoveryActor — PASS
Actor starts with correct filter config, polls Gamma API, discovers new markets when window rotates.

**Evidence (run ce5c096f, 20-min session with 3-min polls):**
- Startup: `Starting MarketDiscoveryActor: poll_interval=3min`, `Found 3 existing condition_ids in cache`
- 7 Gamma API polls over 20 minutes (all successful)
- Window rotation at ~22:00 UTC detected by poll at 22:02
- New market 1773441000 discovered, 2 instruments published
- `on_stop`: processes pending discoveries on shutdown

### on_instrument — PASS
Initial instruments hydrated with full metadata (slug, condition_id, token_id, outcome, dates).
Dynamic discovery verified: new instruments trigger `on_instrument()` with full metadata.

**Evidence (run ce5c096f):**
- Initial: 6 instruments with metadata on `on_start()`
- Dynamic: `on_instrument: dynamic discovery — btc-updown-15m-1773441000 (0x9da3fe51...) outcome=Down/Up`
- SimulatedExchange automatically created matching engines for new instruments

### Active Window Trading — PASS
`tick_always` with `active_window_only=True` trades ONLY instruments in the active 15-min window. Uses `MarketMeta.is_active_at(time.time())` to filter. Existing positions on inactive instruments can still be sold.

**Evidence (run fcad3fb0):** 3 markets loaded (6 instruments), ALL 67 fills on active window `btc-updown-15m-1773435600` only. Zero fills on inactive windows `1773436500` and `1773437400`. Active window log: `active_window: btc-updown-15m-1773435600 active=True window=1773435600..1773436500 now=1773435820`.

### Paper MLflow — UNVERIFIED
Not implemented in paper mode. MLflow logging is in `engine.py` for backtests only.

### Paper Heartbeat — PASS
Heartbeat timer fires every 60s. status.json updated with live metrics during execution.

**Evidence (run c23781eb):** `heartbeat: fills=47 ticks=16330 sim_ts=1773434862302272000`. status.json shows: fills=47, submitted=4456, canceled=2629, ticks=16330, instruments=6.

### Paper Artifacts — PASS
fills.csv, status.json, and 4 PNG visualizations generated on shutdown.
Same artifact pipeline as backtest (`generate_all_artifacts()` via ReportProvider).

**Evidence (run beff974f):** `fills.csv` (8KB, 40 fills), `status.json` (completed), `pnl_curve.png` (40KB), `position_timeline.png` (18KB), `trade_distribution.png` (17KB), `instrument_lifecycle.png` (20KB).

### Paper Order Fills — PASS
Orders submit and fill against sandbox execution client with live book data. In-strategy fill tracking (`_fill_records`) ensures all fills are captured without cache eviction loss.

**Evidence (run ce5c096f, 20 min):** 137 fills. BUY=425.0, SELL=460.0 (ratio 1:1.08). Prices within bid/ask spread. Fills on multiple active windows as they rotate.

### Graceful Shutdown — PASS
Node stops cleanly after `paper_duration_seconds` via SIGALRM → node.stop() → DISPOSED.
All components disposed in order. No zombie processes.

**Evidence:** SIGALRM fires at 120s, node stops in ~13s. Final log: `TradingNode: DISPOSED`. Artifacts saved before dispose.
