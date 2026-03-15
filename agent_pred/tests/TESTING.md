# Testing Guide

## Architecture

```
tests/
├── conftest.py                          # Shared fixtures (bundled data + network data)
├── fixtures/                            # Bundled test data (committed, no network needed)
│   ├── test_hour.parquet                #   ~1000 rows of PMXT orderbook data (83KB)
│   └── market_metadata.json             #   Market info for the bundled parquet
│
├── unit/                                # Tier 1: Pure functions, no engine, no network
│   ├── test_tearsheet.py                #   Round-trip PnL pairing, metrics (14 tests)
│   ├── test_transformer.py              #   PMXT → NautilusTrader data conversion (9 tests)
│   ├── test_universe.py                 #   Instrument building from metadata (2 tests)
│   ├── test_mlflow_logger.py            #   MLflow hierarchy and logging (10 tests)
│   └── test_unit.py                     #   MarketMeta, config parsing, slug labels (14 tests)
│
├── integration/                         # Tier 2: BacktestEngine with local data, no network
│   ├── test_lifecycle.py                #   Strategy lifecycle: start → interval → exit (10 tests)
│   ├── test_exits.py                    #   Exit lifecycle: convergence, TP/SL, FOK retry (8 tests)
│   ├── test_real_strategy.py            #   Run real strategies, check outputs (4 tests)
│   ├── test_log_verification.py         #   _log_buffer captures lifecycle events (4 tests)
│   ├── test_tearsheet_cross_validation.py  # Independent PnL vs tearsheet (3 tests)
│   ├── test_orders.py                   #   Order callbacks, counter consistency (3 tests)
│   ├── test_artifacts_integration.py    #   PNGs, CSVs, JSON artifact generation (5 tests)
│   ├── test_runner.py                   #   run_backtest pipeline end-to-end (3 tests)
│   ├── test_discovery.py                #   MarketDiscoveryActor with mock data (16 tests)
│   └── test_trading_backtest.py         #   Full backtest with network data (3 tests, @network)
│
└── e2e/                                 # Tier 3: Network required, CI skip
    ├── test_gamma.py                    #   Gamma API discovery + CLOB API (22 tests)
    ├── test_pmxt_reader.py              #   PMXT remote streaming (4 tests)
    ├── test_integration.py              #   Full pipeline: PMXT → engine → strategy (1 test)
    └── test_paper_properties.py         #   Paper trading invariants (3 tests)
```

## Three Tiers

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│  TIER 1: Unit            TIER 2: Integration       TIER 3: E2E     │
│  ─────────────           ──────────────────         ──────────      │
│                                                                     │
│  < 5 seconds             < 2 minutes                < 10 minutes   │
│  No engine               BacktestEngine             Network + live │
│  No network              Bundled parquet             External APIs  │
│  Inline data             Synthetic price paths       Real WebSocket │
│                                                                     │
│  ┌──────────┐            ┌──────────────┐           ┌──────────┐   │
│  │ tearsheet│            │  lifecycle   │           │  gamma   │   │
│  │ transform│            │  exits       │           │  pmxt    │   │
│  │ universe │            │  strategies  │           │  paper   │   │
│  │ mlflow   │            │  logs        │           │  e2e     │   │
│  │ unit     │            │  artifacts   │           └──────────┘   │
│  └──────────┘            │  runner      │                          │
│                          │  orders      │           @pytest.mark   │
│  49 tests                │  cross-val   │            .network      │
│                          └──────────────┘                          │
│                                                                     │
│                          59 tests                    30 tests       │
│                                                                     │
│  ◄──── pytest tests/unit/ tests/integration/ ────►  ◄── full ──►  │
│                 "fast suite"                           suite        │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Running Tests

```bash
# Fast suite (unit + integration, no network)
uv run pytest tests/unit/ tests/integration/ -x -q -m "not network"

# Full suite (includes network tests)
uv run pytest tests/ -x -q

# Single tier
uv run pytest tests/unit/ -x -q
uv run pytest tests/integration/ -x -q
uv run pytest tests/e2e/ -x -q

# Single file
uv run pytest tests/integration/test_exits.py -x -q

# With timeout
timeout 600 uv run pytest tests/ -x -q --timeout=300
```

## Behavior Coverage

Every behavior in `BEHAVIORS.md` maps to at least one test:

```
BEHAVIORS.md                          Test File
─────────────────────────────────     ──────────────────────────────────────

Universe
├── Backtest Discovery                test_discovery.py, test_gamma.py
├── Paper/Live Discovery              test_discovery.py
└── Universe Cross-Validation         test_gamma.py

Data
├── Backtest Data (PMXT)              test_lifecycle.py (data_flows_through_engine)
├── Live Data (WebSocket)             test_paper_properties.py
└── Top-of-Book Storage               test_lifecycle.py (top_of_book_recording)

Strategy Features
├── Market Metadata Map               test_lifecycle.py (market_meta_hydrated)
├── on_instrument                     test_discovery.py
├── on_timer (on_interval)            test_lifecycle.py (timer_fires_at_interval)
├── on_tick (on_order_book_deltas)    test_lifecycle.py (tick_callback_receives)
└── Exit Lifecycle
    ├── Resolution timer              test_exits.py
    ├── Convergence                   test_exits.py (near_one, near_zero)
    ├── Take-profit / Stop-loss       test_exits.py
    ├── End-of-data                   test_exits.py
    └── FOK retry                     test_exits.py (queues_retry, gives_up)

Order Fill Handling
├── FOK Order Mechanics               test_orders.py (fok_fills_at_correct_prices)
└── Order Callbacks                   test_orders.py (counter_consistency)

Tracking & Observability
├── MLflow (Backtest)                 test_mlflow_logger.py
├── MLflow Artifacts                  test_mlflow_logger.py
├── Labeling (slug + condition_id)    test_unit.py (slug_label)
├── Heartbeat (status.json)           test_lifecycle.py (heartbeat_writes)
└── Strategy Logging                  test_log_verification.py

Validation
├── Opens match closes                test_lifecycle.py (fill_records_tracking)
├── Fill prices within spread         test_lifecycle.py (fill_prices_within_spread)
├── Tearsheet PnL matches fills       test_tearsheet_cross_validation.py
└── Round trips = closed positions    test_lifecycle.py

Artifacts
├── PNGs generated                    test_artifacts_integration.py
├── CSVs generated                    test_artifacts_integration.py
├── tearsheet.json                    test_artifacts_integration.py
└── metadata.json                     test_artifacts_integration.py

Real Strategy Outputs
├── tick_always outputs               test_real_strategy.py
├── timer_always outputs              test_real_strategy.py
├── Counter consistency               test_real_strategy.py
└── All artifacts valid               test_real_strategy.py

Paper Trading
├── Structural correctness            test_paper_properties.py
├── Fill invariants                   test_paper_properties.py
└── Paper artifacts                   test_paper_properties.py
```

## Fixtures

### Tier 2 (bundled data, no network)

```python
# conftest.py provides:
bundled_parquet_path    # Path to tests/fixtures/test_hour.parquet
bundled_market_infos    # Parsed tests/fixtures/market_metadata.json
bundled_instruments     # NautilusTrader instruments from bundled metadata
```

### Tier 3 (network, session-scoped)

```python
# conftest.py provides:
_pmxt_local_path        # Downloaded PMXT parquet (cached for session)
market_with_tokens      # Most active market from downloaded data
volatile_market         # Market with price movement (for win/loss tests)
```

## Data Strategies

```
┌────────────────────────────────────────────────────────────────────┐
│                                                                    │
│  Bundled Parquet                    Synthetic Price Paths          │
│  ────────────────                   ──────────────────────         │
│                                                                    │
│  tests/fixtures/test_hour.parquet   Built in test code:           │
│  ~1000 rows, 83KB, committed        make_book_snapshot() helper   │
│                                                                    │
│  Used by:                           Used by:                      │
│  • test_lifecycle.py                • test_exits.py               │
│  • test_real_strategy.py              - convergence path (→1.0)   │
│  • test_log_verification.py           - take-profit path (+0.10)  │
│  • test_tearsheet_cross_val.py        - stop-loss path (-0.10)    │
│  • test_orders.py                     - end-of-data (steady)      │
│  • test_artifacts_integration.py      - FOK retry (thin bids)     │
│  • test_runner.py                     - FOK permanent failure     │
│                                                                    │
│  Deterministic: same data            Deterministic: programmatic  │
│  → same fills → same tearsheet       → exact price control        │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

## Log Verification

NautilusTrader's `self.log` uses a Rust-based logger that bypasses Python's `logging` module. `caplog` cannot capture it.

**Solution:** `_log_buffer` pattern in `PolymarketStrategy`:

```python
# Base strategy captures structured events:
self._log_buffer: list[dict] = []

def _log_event(self, event_type: str, **kwargs):
    self._log_buffer.append({"type": event_type, "ts": self.clock.timestamp_ns(), **kwargs})

# Instrumented at: START, FILL, INTERVAL, EXIT
# Tests read strategy._log_buffer after backtest completes
```

## Adding a New Test

1. **Decide the tier** — does it need the engine? Does it need network?
2. **Put it in the right directory** — `unit/`, `integration/`, or `e2e/`
3. **Name it** — `test_{module}_{behavior}` (e.g., `test_convergence_exit_near_one`)
4. **Use fixtures** — `bundled_instruments` + `bundled_parquet_path` for Tier 2
5. **Assert on outputs** — fills, tearsheet, artifacts, log buffer, status.json
6. **Mark network tests** — `@pytest.mark.network` for anything hitting external APIs

## Known Gaps

| Gap | Why | Priority |
|-----|-----|----------|
| MomentumDrift backtest test | Worker ran out of context building it | Medium |
| Active window filtering test | Needs 2-instrument synthetic data | Medium |
| Specific log line assertions (ENTRY/EXIT text) | Log buffer captures events, not formatted text | Low |
| Paper lifecycle timing test | Needs live WebSocket, timing-sensitive | Low |
| Paper active window invariants | Needs live data + active btc-updown-15m market | Low |
