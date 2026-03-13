# Framework Behaviors

Everything the agent_pred framework must support. Each behavior has a status and verification criteria.

**Status key:** PASS = verified with real evidence, UNVERIFIED = code exists but not tested, FAIL = broken

## Universe

### Backtest Discovery — PASS
Gamma API fetch of all markets → client-side slug filter → pre-determined universe of instruments.
Config YAML `universe: slug_contains: "btc-updown-15m"` → `discover_markets()` → `build_instrument_maps()`.

**Evidence:** 3 btc-updown-4h markets discovered, 6 instruments (Up/Down each), cross-validated against direct Gamma API.

### Paper/Live Discovery — UNVERIFIED
Same Gamma API slug matching, but polling on a timer (`MarketDiscoveryActor`). Detects new open markets, builds instruments, publishes to DataEngine cache, notifies strategy via `on_instrument()`, subscribes to orderbook WebSocket feeds. Runs continuously — markets come and go.

**Needs:** End-to-end paper trading run showing discovery events in logs.

### Universe Cross-Validation — PASS (backtest), UNVERIFIED (paper)
Compare discovered universe against external source (pm cli, direct Gamma API curl) to verify we are picking up ALL matching markets and not silently dropping any.

**Evidence (backtest):** 3/3 markets consistent with direct Gamma API curl.

---

## Data

### Backtest Data — PASS
PMXT historical orderbook parquets. Every orderbook snapshot pushed through the engine as `OrderBookDeltas`.

**Evidence:** 432 ticks over 2h, realistic bid/ask values.

### Live Data — UNVERIFIED
Polymarket WebSocket feed (`wss://ws-subscriptions-clob.polymarket.com`). Public, no auth needed. MARKET channel subscriptions by token_id.

**Needs:** Paper trading run showing WebSocket connection and orderbook updates.

### Top-of-Book Storage — PASS
Strategy accumulates (timestamp_ns, instrument_id, best_bid, best_ask, bid_qty, ask_qty) into a DataFrame on each tick. Configurable (off by default for performance). Saved as CSV/parquet artifact after run. NOT full orderbook depth — just BBO.

**Evidence:** 432 records saved, timestamps monotonic, 0 < bid < ask < 1.

---

## Strategy Features

### Market Metadata Map — PASS (backtest), UNVERIFIED (paper on_instrument hydration)
`self._market_meta: dict[InstrumentId, MarketMeta]` in base strategy. Contains slug, condition_id, token_id, outcome (Yes/No), question, start_date, end_date. Hydrated on `on_start()` for backtest instruments, on `on_instrument()` for live-discovered instruments. Enables strategy logic like: parse slug timestamp → determine active 15m window → only trade that window.

**Evidence (backtest):** All 6 instruments have full metadata. `slug_timestamp()` and `is_active_at()` verified.
**Needs (paper):** `on_instrument()` hydrating metadata for dynamically discovered instruments.

### on_instrument — UNVERIFIED
Fires when `MarketDiscoveryActor` publishes a new instrument (paper/live mode with `dynamic_instruments=True`). Strategy auto-subscribes to orderbook data and adds to instrument list.

**Needs:** Paper trading logs showing on_instrument fires, strategy subscribes, trading begins.

### on_timer (on_interval) — PASS
Recurring timer at configurable interval (e.g., every 1 minute). Bounded by start_time_ns/end_time_ns to avoid epoch-start spam. Strategy checks all instruments each tick.

**Evidence:** ~120 callbacks/2h at 1-min interval. Timer fires within start/end bounds.

### on_tick (on_order_book_deltas) — PASS (backtest), UNVERIFIED (paper)
Fires on every orderbook update. High frequency — hundreds to thousands per instrument per hour. Must call `super()` for exit condition checks.

**Evidence (backtest):** 432 ticks/2h. Both singular and plural handlers working.
**Needs (paper):** Live WebSocket data flowing through to on_tick callbacks.

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

## Paper Trading Specific — ALL UNVERIFIED

These behaviors require a live paper trading session to verify:

| Behavior | What to verify |
|----------|---------------|
| WebSocket connection | MARKET channel connects without auth |
| Live orderbook flow | on_tick fires with real-time data |
| MarketDiscoveryActor | Polls Gamma API, finds active markets |
| on_instrument | Fires for dynamically discovered instruments |
| Metadata hydration (paper) | _market_meta populated via on_instrument |
| Active window trading | Strategy trades only the current 15m btc-updown window |
| Paper MLflow | Metrics logged DURING execution, not just at end |
| Paper heartbeat | status.json updated during paper run |
| Paper artifacts | PnL curve, position timeline, fills CSV generated |
| Credential bypass | Dummy creds work — no env vars needed |
| Graceful shutdown | Node stops cleanly after paper_duration_seconds |
