# Test Plan: agent_pred Framework

Comprehensive test architecture for the Polymarket prediction market trading framework.

**Goal:** A test suite that runs in seconds (fast suite < 40s), covers every behavior in BEHAVIORS.md, uses real strategies against real orderbook data, and is deterministic (no network calls in the fast suite).

---

## 1. Test Tiers

### Tier 1: Unit Tests (< 5 seconds, no network, no engine)

Pure function tests with inline data. No BacktestEngine, no PMXT pipeline, no external APIs.

| Scope | What | Current coverage |
|-------|------|-----------------|
| Tearsheet math | Round-trip PnL pairing, metrics computation | 16 tests (good) |
| Transformer | price_change/book_snapshot → NautilusTrader data | 9 tests (good) |
| Instruments | build_instrument_maps, build_instruments_from_metadata | 2 tests (good) |
| Gamma metadata | gamma_to_metadata, clob_to_metadata normalization | 5 tests (good) |
| PMXT URL | file_url format | 1 test (good) |
| MarketMeta | slug_timestamp(), is_active_at(), label | **0 tests (gap)** |
| Config parsing | ExperimentConfig.from_yaml() | **0 tests (gap)** |
| Slug label | _slug_label() in artifacts.py | **0 tests (gap)** |
| MarketFilter | filter dataclass construction | partial (via test_discovery) |

### Tier 2: Integration Tests (< 30 seconds, local data only)

Full backtest execution with bundled parquet data or synthetic orderbook data. Strategy lifecycle verification, log capture, artifact generation. **No network calls.**

| Scope | What | Current coverage |
|-------|------|-----------------|
| Strategy lifecycle | on_start → on_interval → exits → on_stop | **0 tests (gap)** |
| Exit lifecycle | Resolution, convergence, TP/SL, end-of-data | **0 tests (gap)** |
| Heartbeat | status.json written periodically | **0 tests (gap)** |
| Artifacts | PNGs, CSVs, metadata.json generated | **0 tests (gap)** |
| Market metadata | _market_meta hydrated with correct fields | **0 tests (gap)** |
| Order callbacks | on_order_filled/canceled/rejected logging | **0 tests (gap)** |
| Timer interval | Fires at correct rate, bounded by start/end | **0 tests (gap)** |
| FOK retry | on_order_canceled retry queue (3x limit) | **0 tests (gap)** |
| Top-of-book | BBO recording to DataFrame | **0 tests (gap)** |
| Fill records | In-strategy _fill_records tracking | **0 tests (gap)** |
| Tearsheet accuracy | Engine fills match tearsheet PnL exactly | **0 tests (gap)** |
| Active window trading | Only trades instruments in active 15m window | **0 tests (gap)** |
| run_backtest pipeline | Config → engine → strategy → results | **0 tests (gap)** |
| Discovery actor tests | Already covered | 15 tests (good) |

### Tier 3: E2E Tests (< 5 minutes, network required, CI skip)

Real external API calls. Marked `@pytest.mark.network` for CI skip.

| Scope | What | Current coverage |
|-------|------|-----------------|
| Gamma API | fetch_markets, discover_markets | 12 tests (good) |
| CLOB API | fetch_market_clob | 4 tests (good) |
| PMXT reader | Remote streaming, cache creation | 3 tests (good) |
| Full E2E | PMXT → instruments → engine → strategy | 4 tests (good, but slow) |

---

## 2. Current Test Audit

### `test_tearsheet.py` — 16 tests

**What it tests:** Round-trip PnL pairing logic (`_compute_round_trip_pnls`), `compute_tearsheet` metrics (total_pnl, win_rate, sharpe_ratio, max_drawdown, profit_factor, avg_trade_pnl, num_positions, num_round_trips), edge cases (empty fills, unpaired buys, sell-without-buy, partial fills), Tearsheet.to_dict().

**Speed:** < 0.1 seconds. Pure computation on inline DataFrames.

**External deps:** None.

**Network needed:** No.

**BEHAVIORS.md coverage:** Reality Checks (partial — tearsheet accuracy verified mathematically but not against engine fills).

**Verdict:** Excellent. Keep as-is in Tier 1. No changes needed.

---

### `test_transformer.py` — 9 tests

**What it tests:** `transform_price_change` (BUY/SELL updates, DELETE on zero size, timestamp conversion), `transform_book_snapshot` (CLEAR + ADD deltas, F_LAST flags, empty snapshot), `transform_row` dispatch (price_change rows, book_snapshot rows, unknown token_id → None).

**Speed:** < 0.1 seconds. In-memory NautilusTrader object construction.

**External deps:** NautilusTrader `parse_polymarket_instrument` for fixture building.

**Network needed:** No.

**BEHAVIORS.md coverage:** Backtest Data (partial — verifies data transformation, not data sourcing).

**Verdict:** Excellent. Keep as-is in Tier 1. No changes needed.

---

### `test_universe.py` — 2 tests

**What it tests:** `build_instruments_from_metadata` (2 instruments from 2 tokens, correct outcome assignment), `build_instrument_maps` (instruments dict, instrument_ids dict, market_ids set).

**Speed:** < 0.1 seconds. Static metadata dict → instrument construction.

**External deps:** NautilusTrader `parse_polymarket_instrument`.

**Network needed:** No.

**BEHAVIORS.md coverage:** None directly (instrument building is infrastructure).

**Verdict:** Good. Keep as-is in Tier 1. Could add edge case tests (single token, missing fields) but not critical.

---

### `test_discovery.py` — 15 tests

**What it tests:**
- `MarketDiscoveryActor`: config → filter mapping, `_process_discovered_markets` adds to cache, multiple markets, duplicate skipping, mixed new/known, missing condition_id, known_ids snapshot, poll_running guard.
- `PolymarketStrategy` dynamic instruments: `on_instrument` subscribes (dynamic=True), no-op (dynamic=False), dedup, venue filtering, multi-instrument, default config, expiration timer setup.
- Integration: actor publishes → DataEngine → cache pipeline.

**Speed:** ~2 seconds. Uses BacktestEngine for component registration but no data flow.

**External deps:** NautilusTrader BacktestEngine, cache, msgbus.

**Network needed:** No. Uses fake market metadata constants.

**BEHAVIORS.md coverage:** MarketDiscoveryActor (PASS), on_instrument (PASS), Dynamic instruments.

**Verdict:** Excellent. Keep as-is. These are well-designed unit/integration tests with fake data. Could be in Tier 1 or 2 (currently straddles both).

---

### `test_mlflow_logger.py` — 8 tests

**What it tests:** MLflowLogger enabled state, experiment creation via `log_child_run`, git_sha tag on every run, parent-child hierarchy verification, metrics/params/artifacts/tags logging, parent run reuse across child runs.

**Speed:** ~1 second. Uses temp SQLite-backed MLflow tracking. No server.

**External deps:** MLflow library, git (for `_get_git_sha`).

**Network needed:** No.

**BEHAVIORS.md coverage:** MLflow (Backtest) — PASS.

**Verdict:** Excellent. Keep as-is in Tier 1. Well-isolated with temp directories.

---

### `test_pmxt_reader.py` — 4 tests

**What it tests:** `file_url` format string, `read_remote_filtered` streaming + filtering, nonexistent market filtering, `cache_filtered_data` per-market parquet creation.

**Speed:** ~2-3 minutes. 3 of 4 tests download PMXT data over HTTP.

**External deps:** PMXT R2 storage (HTTP), fsspec, pyarrow.

**Network needed:** Yes (3 of 4 tests).

**BEHAVIORS.md coverage:** Backtest Data (verifies data sourcing works).

**Verdict:** Move `test_url_format` to Tier 1. Mark remaining 3 tests as `@pytest.mark.network` (Tier 3). These are valuable for CI but should not block the fast suite.

---

### `test_gamma.py` — 17 tests

**What it tests:**
- `fetch_markets`: returns list, required fields, active filter, limit.
- Server-side filters: end_date_min, volume_num_min, order_by.
- `fetch_all_markets`: volume filter, max_markets, slug_contains.
- `gamma_to_metadata`: basic conversion, yes/no mapping, list outcomes.
- `discover_markets`: returns metadata, metadata is real, slug filter.
- `fetch_market_clob`: known market lookup, token outcomes, nonexistent → None, end_date.
- `clob_to_metadata`: numeric normalization, extra field stripping.

**Speed:** ~30-60 seconds. 12 tests hit real Gamma/CLOB APIs.

**External deps:** Gamma API (HTTP), CLOB API (HTTP).

**Network needed:** Yes (12 of 17 tests).

**BEHAVIORS.md coverage:** Backtest Discovery (PASS), Universe Cross-Validation.

**Verdict:** Keep 5 pure unit tests (`gamma_to_metadata`, `clob_to_metadata`) in Tier 1. Mark 12 API tests as `@pytest.mark.network` (Tier 3).

---

### `test_trading_backtest.py` — 3 tests

**What it tests:** `SimpleTestStrategy` places 1 order (pipeline proof), `TickAlways` generates many fills (tick pattern), `TimerAlways` on volatile market (timer pattern). All compute tearsheet from fills.

**Speed:** ~3-4 minutes. Dominated by PMXT download in session fixture + CLOB API metadata fetch.

**External deps:** PMXT R2 storage, CLOB API (via conftest `_resolve_test_metadata`).

**Network needed:** Yes (data download + metadata fetch on first run).

**BEHAVIORS.md coverage:** on_timer (PASS), on_tick (PASS), FOK Order Mechanics (partial), Test Strategies (PASS).

**Verdict:** These are the most valuable tests — they prove the trading pipeline works. **Must migrate to Tier 2** by bundling a small parquet data file and hardcoding market metadata. Currently they're slow because of network I/O, not because the engine is slow.

---

### `test_integration.py` — 1 test

**What it tests:** Full pipeline: PMXT HTTP download → instrument build → BacktestEngine → LogOnlyStrategy receives deltas.

**Speed:** ~3-5 minutes. Downloads PMXT data directly (no session cache).

**External deps:** PMXT R2 storage, CLOB API.

**Network needed:** Yes.

**BEHAVIORS.md coverage:** Backtest Data (proves data flows through engine).

**Verdict:** Keep as Tier 3 (network required). Consider removing entirely — `test_trading_backtest.py` already covers this and more. If kept, mark `@pytest.mark.network`.

---

## 3. Behavior Coverage Matrix

Every BEHAVIORS.md item mapped to a test (existing or planned).

### Universe

| Behavior | Status | Existing Test | Planned Test |
|----------|--------|--------------|--------------|
| Backtest Discovery (Gamma API) | PASS | test_gamma::TestDiscoverMarkets | — |
| Paper/Live Discovery (MarketDiscoveryActor) | PASS | test_discovery::TestMarketDiscoveryActor | — |
| Universe Cross-Validation | PASS | test_gamma (API tests) | — |

### Data

| Behavior | Status | Existing Test | Planned Test |
|----------|--------|--------------|--------------|
| Backtest Data (PMXT) | PASS | test_pmxt_reader (network) | `test_lifecycle::test_data_flows_through_engine` |
| Live Data (WebSocket) | PASS | — | Tier 3 only (requires live WS) |
| Top-of-Book Storage | PASS | — | `test_lifecycle::test_top_of_book_recording` |

### Strategy Features

| Behavior | Status | Existing Test | Planned Test |
|----------|--------|--------------|--------------|
| Market Metadata Map | PASS | — | `test_lifecycle::test_market_meta_hydrated` |
| on_instrument | PASS | test_discovery::TestPolymarketStrategyDynamic | — |
| on_timer (on_interval) | PASS | test_trading_backtest (partial) | `test_lifecycle::test_timer_fires_at_interval` |
| on_tick (on_order_book_deltas) | PASS | test_trading_backtest (partial) | `test_lifecycle::test_tick_callback_receives_all_deltas` |
| Exit: Resolution timer | PASS | — | `test_exits::test_resolution_timer_exits_before_expiration` |
| Exit: Convergence | PASS | — | `test_exits::test_convergence_exit_near_zero` + `test_convergence_exit_near_one` |
| Exit: Take-profit | PASS | — | `test_exits::test_take_profit_exit` |
| Exit: Stop-loss | PASS | — | `test_exits::test_stop_loss_exit` |
| Exit: End-of-data | PASS | — | `test_exits::test_end_of_data_exit_60s_before` |

### Order Fill Handling

| Behavior | Status | Existing Test | Planned Test |
|----------|--------|--------------|--------------|
| FOK Order Mechanics | PASS | test_trading_backtest (implicit) | `test_orders::test_fok_fills_against_book` |
| Order Callbacks | PASS | — | `test_orders::test_on_order_filled_increments_counter` |
| FOK Rejection Handling | — | — | `test_orders::test_fok_cancel_queues_retry` |

### Tracking & Observability

| Behavior | Status | Existing Test | Planned Test |
|----------|--------|--------------|--------------|
| MLflow (Backtest) | PASS | test_mlflow_logger (8 tests) | — |
| MLflow Artifacts | PASS | test_mlflow_logger::test_artifacts_logged | — |
| Labeling (slug + condition_id) | PASS | — | `test_unit::test_slug_label_formatting` |
| Heartbeat (status.json) | PASS | — | `test_lifecycle::test_heartbeat_writes_status_json` |
| Strategy Logging | PASS | — | `test_lifecycle::test_lifecycle_state_counters` (via state inspection, not log capture) |

### Validation

| Behavior | Status | Existing Test | Planned Test |
|----------|--------|--------------|--------------|
| Opens match closes | PASS | test_tearsheet (implicit) | `test_lifecycle::test_buys_equal_sells` |
| Fill prices within spread | PASS | — | `test_lifecycle::test_fill_prices_within_spread` |
| Tearsheet PnL matches fills | PASS | test_tearsheet (math only) | `test_lifecycle::test_tearsheet_matches_engine_fills` |
| Round trips = closed positions | PASS | test_tearsheet (math only) | `test_lifecycle::test_round_trips_match_closed_positions` |

### Artifacts

| Behavior | Status | Existing Test | Planned Test |
|----------|--------|--------------|--------------|
| PNGs generated (4 charts) | PASS | — | `test_artifacts::test_generate_all_artifacts_creates_pngs` |
| CSVs generated (fills, orders, positions) | PASS | — | `test_artifacts::test_save_artifacts_creates_csvs` |
| tearsheet.json content | PASS | — | `test_artifacts::test_tearsheet_json_matches_metrics` |
| metadata.json content | PASS | — | `test_artifacts::test_metadata_json_has_required_fields` |

### Config & Runner

| Behavior | Status | Existing Test | Planned Test |
|----------|--------|--------------|--------------|
| ExperimentConfig.from_yaml | — | — | `test_unit::test_config_from_yaml_parses_all_fields` |
| run_backtest pipeline | — | — | `test_runner::test_run_backtest_end_to_end` |
| Status.json lifecycle | — | — | `test_runner::test_status_json_running_then_completed` |

### Paper Trading Specific

Most paper trading behaviors require a live WebSocket connection and are inherently Tier 3 or manual verification. **Active Window Trading** is the exception — it tests pure framework logic (`_is_tradeable()` → `MarketMeta.is_active_at()`) and gets a Tier 2 test.

| Behavior | Status | Tier | Test Plan |
|----------|--------|------|-----------|
| Credential Bypass | PASS | 3 | Manual/E2E — requires live WebSocket and TradingNode startup |
| WebSocket Connection | PASS | 3 | Manual/E2E — requires live `wss://` connection |
| Live Orderbook Flow | PASS | 3 | Manual/E2E — requires real-time WebSocket data |
| Active Window Trading | PASS | **2** | `test_lifecycle::test_active_window_filters_instruments` — synthetic data, 2 instruments (active + inactive), asserts fills only on active window |
| Paper Heartbeat | PASS | 3 | Deferred — same heartbeat mechanism as backtest (covered by `test_heartbeat_writes_status_json`) |
| Paper Artifacts | PASS | 3 | Deferred — same artifact pipeline as backtest (covered by `test_artifacts_integration`) |
| Paper Order Fills | PASS | 3 | Manual — requires sandbox execution client with live book data |
| Graceful Shutdown | PASS | 3 | Manual — requires SIGALRM lifecycle and TradingNode dispose sequence |
| Paper MLflow | UNVERIFIED | 3 | Not implemented — no test planned (feature not yet built) |

### Validation & Meta

These are meta-behaviors about test infrastructure and experiments, not framework features. Explicitly excluded from Tier 2 test coverage.

| Behavior | Status | Note |
|----------|--------|------|
| Universe Validation | PASS | Covered by `test_gamma` API tests (Tier 3) — cross-validates discovered markets against Gamma API |
| Test Strategies (tick_always, timer_always) | PASS | Meta: these ARE the test harnesses used by the test suite itself |
| MomentumDrift Strategy | PASS | Experiment strategy, not framework — no regression test needed. Validated via strategy dev loop. |
| Unit Tests | PASS | Meta: this IS the test plan. Coverage tracked by this document. |

---

## 4. New Test Designs

### 4.1 Tier 1 Unit Tests (new file: `tests/test_unit.py`)

#### `test_market_meta_slug_timestamp`
- **Setup:** Create `MarketMeta(slug="btc-updown-15m-1773435600", ...)`
- **Action:** Call `meta.slug_timestamp()`
- **Assert:** Returns `1773435600`

#### `test_market_meta_slug_timestamp_no_match`
- **Setup:** Create `MarketMeta(slug="some-other-market", ...)`
- **Action:** Call `meta.slug_timestamp()`
- **Assert:** Returns `None`

#### `test_market_meta_is_active_at_in_window`
- **Setup:** Create `MarketMeta(slug="btc-updown-15m-1773435600", ...)`
- **Action:** Call `meta.is_active_at(1773435600 + 450)` (midpoint of 15-min window)
- **Assert:** Returns `True`

#### `test_market_meta_is_active_at_before_window`
- **Setup:** Same meta
- **Action:** Call `meta.is_active_at(1773435599)`
- **Assert:** Returns `False`

#### `test_market_meta_is_active_at_after_window`
- **Setup:** Same meta
- **Action:** Call `meta.is_active_at(1773435600 + 900)`
- **Assert:** Returns `False` (window is `[start, start+900)`)

#### `test_market_meta_label`
- **Setup:** Create `MarketMeta(slug="btc-updown-15m", condition_id="0xabc123def456", ...)`
- **Action:** Read `meta.label`
- **Assert:** Returns `"btc-updown-15m (0xabc123de...)"`

#### `test_slug_label_with_market_infos`
- **Setup:** Import `_slug_label` from `runner.artifacts`. Build instrument_id string and market_infos list.
- **Action:** Call `_slug_label(instrument_id_str, market_infos)`
- **Assert:** Returns `"btc-updown-15m-Up (0xabc123de...)"` format

#### `test_slug_label_without_market_infos`
- **Setup:** Same instrument_id string, no market_infos
- **Action:** Call `_slug_label(instrument_id_str, None)`
- **Assert:** Returns truncated condition_id `"0xabc123def456..."`

#### `test_config_from_yaml_parses_all_fields`
- **Setup:** Write a complete YAML config to a temp file with all fields (mode, strategy.path, strategy.params, condition_ids, data.hours, fees, mlflow.experiment, mlflow.parent_run, universe.slug_contains, etc.)
- **Action:** Call `ExperimentConfig.from_yaml(path)`
- **Assert:** Every field parsed correctly — mode, strategy_path, strategy_params dict, condition_ids list, data_hours list, fees, mlflow_experiment, mlflow_variant, universe.slug_contains, universe.volume_min, etc.

#### `test_config_from_yaml_defaults`
- **Setup:** Write minimal YAML (just `mode: backtest`, `strategy: {path: "x:Y"}`)
- **Action:** Call `ExperimentConfig.from_yaml(path)`
- **Assert:** Defaults: starting_balance=10000, fees="zero", condition_ids=[], etc.

#### `test_file_url_format`
- **Move from test_pmxt_reader.py**
- **Assert:** `file_url("2026-03-09T14") == "https://r2.pmxt.dev/polymarket_orderbook_2026-03-09T14.parquet"`

---

### 4.2 Tier 2 Integration Tests — Data Strategy

#### The Bundled Data Approach

Create a **test data fixture** — a small parquet file (~100KB) committed to the repo at `tests/data/test_hour.parquet`. This file contains ~500-1000 rows of real PMXT data for 1-2 markets with known price movements.

**How to generate it (one-time script, not committed):**
```python
# scripts/generate_test_data.py
from pmxt.reader import read_remote_filtered
import pyarrow as pa, pyarrow.parquet as pq

HOUR = "2026-03-09T09"
# Pick 2 markets with known activity
TARGET_MARKETS = {"0x884c293e...", "0xbcf53c26..."}

rows = []
for batch in read_remote_filtered(HOUR, TARGET_MARKETS):
    rows.extend(batch)
    if len(rows) > 1000:
        break

table = pa.Table.from_pylist(rows[:1000])
pq.write_table(table, "tests/data/test_hour.parquet")
```

**Companion metadata file:** `tests/data/test_markets.json` — hardcoded market metadata for the markets in the parquet file, eliminating the CLOB API call.

```json
[
  {
    "condition_id": "0x884c293e...",
    "question": "Counter-Strike: 100 Thieves vs FOKUS - Map 1 Winner",
    "minimum_tick_size": "0.001",
    "minimum_order_size": "1",
    "end_date_iso": "2027-12-31T00:00:00Z",
    "maker_base_fee": "0",
    "taker_base_fee": "0",
    "slug": "cs-100t-fokus-map1",
    "tokens": [
      {"token_id": "111...", "outcome": "100 Thieves"},
      {"token_id": "222...", "outcome": "FOKUS"}
    ]
  }
]
```

#### The Synthetic Data Approach

For behavior tests that need specific price paths (convergence, TP/SL), create synthetic orderbook data programmatically:

```python
def make_book_snapshot(instrument, instrument_id, bid: float, ask: float, ts_ns: int):
    """Create an OrderBookDeltas with a single bid/ask level."""
    from pmxt.transformer import transform_book_snapshot
    data = {
        "bids": [[str(bid), "1000"]],
        "asks": [[str(ask), "1000"]],
        "timestamp": ts_ns / 1e9,
    }
    return transform_book_snapshot(data, instrument_id, instrument, ts_ns, ts_ns)
```

This lets us craft exact price paths:
- **Convergence test:** bid/ask → 0.96/0.97 (mid > 0.95 threshold)
- **TP/SL test:** entry at 0.50, price rises to 0.58 (TP triggers) or drops to 0.46 (SL triggers)
- **End-of-data test:** normal prices, then time alert fires 60s before end

#### Shared Conftest Fixtures (new `tests/conftest.py` additions)

```python
# --- Tier 2 fixtures (local data, no network) ---

TEST_DATA_DIR = Path(__file__).parent / "data"

@pytest.fixture(scope="session")
def bundled_parquet_path():
    """Path to the bundled test parquet file (committed to repo)."""
    path = TEST_DATA_DIR / "test_hour.parquet"
    assert path.exists(), f"Bundled test data missing: {path}"
    return path

@pytest.fixture(scope="session")
def bundled_market_infos():
    """Hardcoded market metadata for bundled test data."""
    with open(TEST_DATA_DIR / "test_markets.json") as f:
        return json.load(f)

@pytest.fixture(scope="session")
def bundled_instruments(bundled_market_infos):
    """Instruments built from bundled market metadata."""
    return build_instrument_maps(bundled_market_infos)

@pytest.fixture
def test_engine(bundled_instruments, bundled_parquet_path):
    """BacktestEngine loaded with bundled data, ready to add a strategy."""
    instruments, instrument_ids, market_ids = bundled_instruments
    engine = BacktestEngine(config=BacktestEngineConfig(logging=False))
    engine.add_venue(
        venue=POLYMARKET_VENUE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        starting_balances=[Money(10_000, USDC_POS)],
        book_type=BookType.L2_MBP,
    )
    for inst in instruments.values():
        engine.add_instrument(inst)
    gen = _local_data_generator(bundled_parquet_path, market_ids, instruments, instrument_ids)
    engine.add_data_iterator("pmxt", gen)
    yield engine, instruments, instrument_ids, market_ids
    engine.dispose()
```

For synthetic data tests, a separate fixture:

```python
def make_synthetic_engine(instrument, instrument_id, price_path, start_ns, end_ns):
    """Build an engine with synthetic orderbook data following a specific price path.

    price_path: list of (timestamp_ns, bid, ask) tuples
    """
    engine = BacktestEngine(config=BacktestEngineConfig(logging=False))
    engine.add_venue(...)
    engine.add_instrument(instrument)

    def data_gen():
        batch = []
        for ts_ns, bid, ask in price_path:
            deltas = make_book_snapshot(instrument, instrument_id, bid, ask, ts_ns)
            batch.append(deltas)
            if len(batch) >= 50:
                batch.sort(key=lambda d: d.ts_init)
                yield batch
                batch = []
        if batch:
            batch.sort(key=lambda d: d.ts_init)
            yield batch

    engine.add_data_iterator("synthetic", data_gen())
    return engine
```

---

### 4.3 Tier 2 Integration Tests — Lifecycle (new file: `tests/test_lifecycle.py`)

All tests use bundled parquet data or synthetic data. No network.

#### `test_data_flows_through_engine`
- **Strategy:** LogOnlyStrategy
- **Data:** Bundled parquet
- **Action:** Run engine with bundled data
- **Assert:** `strategy.delta_count > 0` — proves data pipeline works without network

#### `test_market_meta_hydrated`
- **Strategy:** TickAlways (extends PolymarketStrategy)
- **Data:** Bundled parquet
- **Action:** Run engine, inspect `strategy._market_meta`
- **Assert:**
  - `len(strategy._market_meta) == len(instrument_ids)` — every instrument has metadata
  - Each MarketMeta has non-empty: slug, condition_id, token_id, outcome, question
  - `meta.slug_timestamp()` returns int (for btc-updown style) or None

#### `test_timer_fires_at_interval`
- **Strategy:** TimerAlways with `check_interval_minutes=1`
- **Data:** Bundled parquet (1 hour of data)
- **Setup:** `start_time_ns` and `end_time_ns` set to hour bounds
- **Action:** Run engine
- **Assert:**
  - `strategy._interval_count >= 50` (1-hour window at 1-min interval ≈ 60 ticks, minus some startup delay)
  - `strategy._interval_count <= 65` (bounded by end_time_ns)

#### `test_tick_callback_receives_all_deltas`
- **Strategy:** TickAlways with `buy_after_ticks=999999` (effectively never trades)
- **Data:** Bundled parquet
- **Action:** Run engine
- **Assert:**
  - `strategy._tick_count_total > 100` — received many book updates
  - No fills (ticks threshold never reached)

#### `test_heartbeat_writes_status_json`
- **Strategy:** TickAlways
- **Data:** Bundled parquet
- **Setup:** Set `strategy._heartbeat_dir = tmp_path` and `strategy._heartbeat_run_id = "test123"` **after** `engine.add_strategy(strategy)` but **before** `engine.run()`. The engine's `on_start()` reads `_heartbeat_dir` to decide whether to set up the heartbeat timer. These attributes default to `None` in `__init__` and are normally injected by the runner before execution.
- **Action:** Run engine
- **Assert:**
  - `(tmp_path / "status.json").exists()`
  - JSON contains: `run_id == "test123"`, `status == "running"`, `strategy == "TickAlways"`, `fills >= 0`, `ticks > 0`, `instruments > 0`

#### `test_top_of_book_recording`
- **Strategy:** TickAlways with `record_top_of_book=True`, `buy_after_ticks=999999`
- **Data:** Bundled parquet
- **Action:** Run engine, call `strategy.get_top_of_book_df()`
- **Assert:**
  - DataFrame is not empty
  - Columns: `timestamp_ns, instrument_id, bid, ask, bid_qty, ask_qty`
  - All bids > 0, all asks > 0, all bids < asks
  - Timestamps are monotonically non-decreasing per instrument

#### `test_fill_records_tracking`
- **Strategy:** TickAlways with `buy_after_ticks=3, sell_after_ticks=10`
- **Data:** Bundled parquet
- **Action:** Run engine
- **Assert:**
  - `len(strategy._fill_records) == strategy._orders_filled`
  - Each record has: timestamp, instrument_id, slug, side (BUY/SELL), qty, price
  - BUY count equals SELL count (or off by at most 1 for open positions)

#### `test_buys_equal_sells`
- **Strategy:** TickAlways
- **Data:** Bundled parquet
- **Action:** Run engine, compute fills report
- **Assert:**
  - Number of BUY fills equals number of SELL fills (for all closed round trips)
  - Or: total buy qty within 1.0 of total sell qty

#### `test_fill_prices_within_spread`
- **Strategy:** TickAlways
- **Data:** Bundled parquet
- **Action:** Run engine, compute fills report
- **Assert:**
  - All BUY fill prices <= 1.0 (valid prediction market range)
  - All SELL fill prices >= 0.0
  - All fill prices > 0.0 and < 1.0

#### `test_tearsheet_matches_engine_fills`
- **Strategy:** TickAlways
- **Data:** Bundled parquet
- **Action:** Run engine, compute tearsheet from fills
- **Assert:**
  - `tearsheet.num_trades == len(fills_df)` — fill count matches
  - `tearsheet.num_round_trips > 0` — some trades completed
  - Manual round-trip PnL computation from fills matches `tearsheet.total_pnl`

#### `test_round_trips_match_closed_positions`
- **Strategy:** TickAlways
- **Data:** Bundled parquet
- **Action:** Run engine
- **Assert:**
  - `strategy.round_trips == len(closed_positions)` — strategy's counter matches engine's closed positions
  - `tearsheet.num_round_trips == strategy.round_trips`

#### `test_lifecycle_state_counters`
- **Strategy:** TickAlways
- **Data:** Bundled parquet
- **Action:** Run engine
- **Assert:** Strategy state fields confirm lifecycle events occurred:
  - `strategy._orders_filled > 0` — fills happened
  - `strategy._orders_submitted > 0` — orders were submitted
  - `strategy._tick_count_total > 0` — tick callbacks fired
  - `len(strategy._fill_records) == strategy._orders_filled` — fill tracking consistent

**Note:** NautilusTrader uses its own Rust-based logger (pyo3). These logs cannot be reliably captured in Python. Instead of parsing log output, we verify lifecycle events via the strategy's internal state fields (`_orders_filled`, `_tick_count_total`, `_interval_count`, `_fill_records`). This is more reliable and doesn't depend on log format stability.

#### `test_active_window_filters_instruments`
- **Strategy:** TickAlways with `active_window_only=True`
- **Data:** Synthetic price paths for 2 instruments (same condition, Yes/No outcomes)
- **Setup:**
  1. Compute a slug timestamp for the **current** wall-clock 15-min window:
     ```python
     import time
     now = int(time.time())
     active_ts = now - (now % 900)  # current 15-min window start
     inactive_ts = active_ts + 7200  # 2 hours in the future (inactive)
     ```
  2. Create 2 FAKE_MARKET dicts with slug `f"btc-updown-15m-{active_ts}"` (active) and `f"btc-updown-15m-{inactive_ts}"` (inactive)
  3. Build instruments from both markets. Create synthetic price paths (bid=0.50, ask=0.51 for both instruments).
  4. Add both instruments to the engine with interleaved data.
  5. **Alternatively**, monkeypatch `time.time()` to return a fixed value within the active instrument's window.
- **Action:** Run engine with TickAlways `active_window_only=True, buy_after_ticks=3, sell_after_ticks=10`
- **Assert:**
  - `strategy._fill_records` has fills — some trading happened
  - All fills reference the **active-window** instrument only
  - Zero fills reference the **inactive-window** instrument
  - (Verify via `fill["instrument_id"]` containing the active slug timestamp)
- **Why this matters:** `_is_tradeable()` is pure framework logic in TickAlways. If someone changes the filtering, active window trading breaks silently. This is a real regression risk.

**Implementation note:** The `_is_tradeable()` method calls `time.time()` (wall clock), not sim clock. The test MUST either: (a) set slug timestamps relative to current wall time (preferred — no mocking), or (b) monkeypatch `time.time`. Option (a) is deterministic as long as the test runs in < 15 minutes.

---

### 4.4 Tier 2 Integration Tests — Exit Lifecycle (new file: `tests/test_exits.py`)

All tests use synthetic data with crafted price paths.

#### Shared helper

```python
FAKE_MARKET = {
    "condition_id": "0x" + "e" * 64,
    "question": "Test exit market",
    "minimum_tick_size": "0.01",
    "minimum_order_size": "1",
    "end_date_iso": "2027-12-31T00:00:00Z",  # far future (no resolution timer by default)
    "maker_base_fee": "0",
    "taker_base_fee": "0",
    "tokens": [
        {"token_id": "exit_token_yes", "outcome": "Yes"},
        {"token_id": "exit_token_no", "outcome": "No"},
    ],
}

def _run_with_price_path(price_path, strategy_config, start_ns, end_ns,
                          market_info=FAKE_MARKET, end_date_iso=None):
    """Build engine with synthetic price path and run strategy."""
    if end_date_iso:
        market_info = dict(market_info)
        market_info["end_date_iso"] = end_date_iso

    instruments, instrument_ids, market_ids = build_instrument_maps([market_info])
    instrument = list(instruments.values())[0]
    instrument_id = list(instrument_ids.values())[0]

    engine = make_synthetic_engine(instrument, instrument_id, price_path, start_ns, end_ns)

    # Inject instrument IDs into config
    strategy_config_dict = {**strategy_config, "instrument_ids": [str(instrument_id)],
                            "start_time_ns": start_ns, "end_time_ns": end_ns}
    config = TickAlwaysConfig(**strategy_config_dict)
    strategy = TickAlways(config=config)
    engine.add_strategy(strategy)

    start_dt = datetime.fromtimestamp(start_ns / 1e9, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(end_ns / 1e9, tz=timezone.utc)
    engine.run(start=start_dt, end=end_dt)

    return engine, strategy
```

#### `test_convergence_exit_near_one`
- **Price path:** Start at bid=0.50/ask=0.51, gradually increase to bid=0.96/ask=0.97 (mid=0.965 > 0.95 threshold)
- **Strategy:** TickAlways with `buy_after_ticks=3, sell_after_ticks=99999, convergence_threshold=0.95`
- **Expected:** Strategy buys early, then convergence exit triggers when mid > 0.95
- **Assert:**
  - At least 1 SELL fill (the convergence exit)
  - `instrument_id in strategy._closed` — marked as closed
  - Strategy does not re-enter after convergence

#### `test_convergence_exit_near_zero`
- **Price path:** Start at bid=0.50/ask=0.51, gradually decrease to bid=0.03/ask=0.04 (mid=0.035 < 0.05 threshold)
- **Strategy:** TickAlways with `convergence_threshold=0.95`
- **Expected:** Convergence exit when mid < (1 - 0.95) = 0.05
- **Assert:** Similar to above

#### `test_end_of_data_exit_60s_before`
- **Price path:** Steady prices (bid=0.50/ask=0.51) for the full hour
- **Strategy:** TickAlways with `buy_after_ticks=3`
- **Time bounds:** start_ns to end_ns spanning 1 hour
- **Expected:** Strategy buys, then end-of-data alert fires 60s before end_ns, exits all positions
- **Assert:**
  - `strategy._data_ended == True`
  - All positions closed
  - No open positions in engine cache

#### `test_resolution_timer_exits_before_expiration`
- **Price path:** Steady prices for the full period
- **Strategy:** TickAlways with `exit_before_resolution_secs=300`
- **Market:** Set `end_date_iso` to a time 600s after data start (so resolution alert fires 300s into the data)
- **Expected:** Resolution timer fires, exits positions 300s before market expiration
- **Assert:**
  - Instrument in `strategy._closed`
  - Position closed before expiration_ns - 300s

#### `test_take_profit_exit`
- **Price path:** bid=0.50/ask=0.51 for entry, then gradually rises to bid=0.60/ask=0.61
- **Strategy:** TickAlways with `take_profit=0.05` (trigger when unrealized PnL > 0.05)
- **Note:** TP/SL uses `position.unrealized_pnl(price)` which is `(price - avg_entry) * qty`. With qty=1, entry at 0.51, TP at gain > 0.05 means price > 0.56.
- **Assert:**
  - Exit sell fill exists
  - Instrument in `strategy._closed` or `strategy._exiting`

#### `test_stop_loss_exit`
- **Price path:** bid=0.50/ask=0.51 for entry, then drops to bid=0.40/ask=0.41
- **Strategy:** TickAlways with `stop_loss=-0.05` (trigger when unrealized PnL < -0.05)
- **Assert:** Similar — exit fill exists at loss

#### `test_fok_cancel_queues_retry`
- **Strategy:** TickAlways with `buy_after_ticks=3, convergence_threshold=0.95, check_interval_minutes=1`
- **Price path:** Entry → convergence → zero liquidity (FOK fails) → liquidity restored (retry succeeds)
  ```python
  ticks = []
  for i in range(120):
      ts = start_ns + i * 3_000_000_000  # 3s intervals (6 min total)
      if i < 10:
          bid, ask = 0.50, 0.51          # stable — entry fills here
      elif i < 30:
          bid, ask = 0.96, 0.97          # convergence triggers _trigger_exit()
      elif i < 60:
          bid, ask = 0.96, 0.0           # sell side empty — FOK cancel
          # NOTE: Use asks=[["0.97", "0"]] (zero qty) instead of empty asks
          # transform_book_snapshot always needs at least a CLEAR action
      else:
          bid, ask = 0.96, 0.97          # liquidity restored — retry succeeds
      ticks.append((ts, round(bid, 3), round(ask, 3)))
  ```
- **Key detail:** Zero-liquidity representation. `transform_book_snapshot` with `asks=[]` generates a CLEAR-only snapshot (no ADD actions). This empties the matching engine's ask side. A FOK SELL order with no counterparty gets canceled. **Verification needed:** confirm that NautilusTrader's matching engine cancels FOK against an empty book (expected yes, but test during implementation).
- **Expected flow:**
  1. Ticks 0-9: Strategy buys at 0.51
  2. Ticks 10-29: Convergence detected, `_trigger_exit()` submits FOK SELL → canceled (no ask liquidity)
  3. `_pending_exit_retry` populated, `_exiting` cleared on next interval
  4. Ticks 60+: Next convergence check re-triggers exit, FOK SELL succeeds (liquidity restored)
- **Assert:**
  - `strategy._orders_canceled >= 1` — at least one FOK cancel
  - `strategy._orders_filled >= 2` — entry BUY + exit SELL both filled
  - Position is closed (no open positions in cache)

#### `test_fok_cancel_gives_up_after_3_retries`
- **Strategy:** Same as above
- **Price path:** Entry → convergence → **permanent** zero sell-side liquidity
  ```python
  ticks = []
  for i in range(200):
      ts = start_ns + i * 3_000_000_000  # 3s intervals (10 min total)
      if i < 10:
          bid, ask = 0.50, 0.51          # stable — entry
      else:
          bid, ask = 0.96, 0.0           # convergence + zero liquidity forever
      ticks.append((ts, round(bid, 3), round(ask, 3)))
  ```
- **Expected flow:**
  1. Entry BUY fills at tick ~3
  2. Convergence triggers exit at tick ~10 → FOK SELL canceled
  3. Retry 1 on next interval → canceled
  4. Retry 2 → canceled
  5. Retry 3 → canceled → gives up, marks instrument as closed
- **Assert:**
  - `strategy._exit_retries[instrument_id] >= 3` — hit retry limit
  - `instrument_id in strategy._closed` — marked as closed despite open position
  - `instrument_id not in strategy._exiting` — cleared from exiting set

---

### 4.5 Tier 2 Integration Tests — Artifacts (new file: `tests/test_artifacts_integration.py`)

#### `test_generate_all_artifacts_creates_pngs`
- **Setup:** Create fills_df and positions_df with inline test data (reuse `_make_fills` from test_tearsheet). Create a temp directory.
- **Action:** Call `generate_all_artifacts(fills_df, positions_df, tmp_path, market_infos)`
- **Assert:**
  - `(tmp_path / "pnl_curve.png").exists()`
  - `(tmp_path / "position_timeline.png").exists()` (only if positions_df has ts_opened/ts_closed)
  - `(tmp_path / "trade_distribution.png").exists()`
  - `(tmp_path / "instrument_lifecycle.png").exists()`
  - Each PNG file size > 1000 bytes (not empty/corrupt)

#### `test_generate_all_artifacts_empty_data`
- **Setup:** Empty DataFrames
- **Action:** Call `generate_all_artifacts(pd.DataFrame(), pd.DataFrame(), tmp_path)`
- **Assert:** Returns empty list, no files created, no exceptions

#### `test_save_artifacts_creates_csvs`
- **Setup:** Create a RunResult with fills_df, orders_df, positions_df
- **Action:** Call `_save_artifacts(result, tmp_path, market_infos)`
- **Assert:**
  - `(tmp_path / "tearsheet.json").exists()`
  - `(tmp_path / "fills.csv").exists()`
  - `(tmp_path / "orders.csv").exists()`
  - `(tmp_path / "positions.csv").exists()`
  - `(tmp_path / "metadata.json").exists()`

#### `test_tearsheet_json_matches_metrics`
- **Setup:** Create RunResult with known tearsheet values
- **Action:** Call `_save_artifacts`, read back tearsheet.json
- **Assert:** JSON values match `tearsheet.to_dict()` exactly

#### `test_metadata_json_has_required_fields`
- **Setup:** Create RunResult with config
- **Action:** Call `_save_artifacts`, read back metadata.json
- **Assert:** Contains: run_id, mode, strategy_path, strategy_params, data_hours, elapsed_seconds, success

---

### 4.6 Tier 2 Integration Tests — Runner Pipeline (new file: `tests/test_runner.py`)

#### `test_run_backtest_end_to_end`
- **Setup:** Create ExperimentConfig manually (no YAML) with strategy_path pointing to TickAlways, bundled market_infos, bundled data hours
- **Data:** Bundled parquet (no network)
- **Action:** Call `run_backtest(config, market_infos, results_dir=tmp_path)`
- **Assert:**
  - `result.success == True`
  - `result.tearsheet.num_trades > 0`
  - `result.run_id` is 8 chars
  - `(tmp_path / "tearsheet.json").exists()`
  - `(tmp_path / "status.json").exists()` with `status == "completed"`

**Challenge:** `run_backtest` calls `pmxt_data_generator` which does remote HTTP reads. To make this work offline, either:
1. Pre-cache data and pass `data_cache_dir` with a populated index
2. Monkey-patch `pmxt_data_generator` to read from bundled parquet
3. Create a test-specific entry point in engine.py that accepts a local data path

Option 2 (monkeypatch) is simplest and most honest:
```python
def test_run_backtest_end_to_end(bundled_parquet_path, bundled_market_infos, tmp_path, monkeypatch):
    # Patch pmxt_data_generator to use local file
    def local_gen(market_ids, hours, instruments, instrument_ids, **kwargs):
        yield from _local_data_generator(bundled_parquet_path, market_ids, instruments, instrument_ids)
    monkeypatch.setattr("runner.engine.pmxt_data_generator", local_gen)
    ...
```

#### `test_status_json_running_then_completed`
- **Setup:** Same as above
- **Action:** Run backtest, read status.json
- **Assert:** Final status.json has `status == "completed"`, `total_pnl` is a number, `elapsed_seconds > 0`

#### `test_run_backtest_failure_writes_error`
- **Setup:** Create config with invalid strategy_path (e.g., "nonexistent.module:Foo")
- **Action:** Call `run_backtest(config, market_infos, results_dir=tmp_path)`
- **Assert:**
  - `result.success == False`
  - `result.error is not None`
  - `(tmp_path / "error.json").exists()`
  - `(tmp_path / "status.json")` has `status == "failed"`

---

### 4.7 Tier 2 Integration Tests — Order Callbacks (new file: `tests/test_orders.py`)

#### `test_on_order_filled_increments_counter`
- **Strategy:** TickAlways
- **Data:** Bundled parquet
- **Action:** Run engine
- **Assert:**
  - `strategy._orders_filled > 0`
  - `strategy._orders_submitted >= strategy._orders_filled`
  - `strategy._orders_filled == len(strategy._fill_records)`

#### `test_on_order_canceled_increments_counter`
- **Strategy:** TickAlways (some FOK orders may be canceled due to insufficient liquidity)
- **Data:** Bundled parquet
- **Action:** Run engine
- **Assert:**
  - `strategy._orders_canceled >= 0` (may be 0 if all fill)
  - `strategy._orders_submitted == strategy._orders_filled + strategy._orders_canceled + strategy._orders_rejected`

#### `test_fok_fills_against_book`
- **Strategy:** TickAlways
- **Data:** Bundled parquet
- **Action:** Run engine, get fills
- **Assert:**
  - Every BUY fill price is at the ask level (FOK at ask)
  - Every SELL fill price is at the bid level (FOK at bid)
  - All fill quantities match trade_size

---

## 5. Data Strategy Summary

| Data type | Where | Size | Used by |
|-----------|-------|------|---------|
| Bundled parquet | `tests/data/test_hour.parquet` | ~100KB | Tier 2 lifecycle, orders, runner tests |
| Market metadata JSON | `tests/data/test_markets.json` | ~2KB | Tier 2 (replaces CLOB API calls) |
| Synthetic price paths | Generated in test code | 0 bytes on disk | Tier 2 exit tests |
| Real PMXT download | Session-scoped fixture | ~50MB (temp) | Tier 3 only |

**Generation procedure for bundled data (one-time):**
1. Run a script that downloads 1 hour of PMXT data, filters to 1-2 known markets
2. Truncate to ~1000 rows
3. Save as `tests/data/test_hour.parquet`
4. Extract market metadata from CLOB API, save as `tests/data/test_markets.json`
5. Commit both files to the repo
6. Verify: all Tier 2 tests pass with this bundled data

**Requirements for the bundled data:**
- Must contain at least 2 markets (4 instruments — Yes/No for each)
- Must have enough price movement for TickAlways to generate fills (bid/ask spread must occasionally allow profitable round trips)
- Must span at least 30 minutes of timestamps (for timer tests)
- Should include both `price_change` and `book_snapshot` update types

---

## 6. Migration Plan

### Phase 1: Create test infrastructure (no behavior changes)

1. Create `tests/data/` directory
2. Generate and commit bundled parquet + market metadata JSON
3. Add new fixtures to `tests/conftest.py`:
   - `bundled_parquet_path`, `bundled_market_infos`, `bundled_instruments`, `test_engine`
   - `make_synthetic_engine` helper function
   - `make_book_snapshot` helper function
4. Add pytest marks: `pytest.mark.network` for tests that need HTTP
5. Update `pyproject.toml` or `conftest.py` with mark registration

### Phase 2: Add new Tier 1 unit tests

1. Create `tests/test_unit.py` with MarketMeta tests, config parsing tests, slug label tests
2. Move `test_url_format` from `test_pmxt_reader.py` to `test_unit.py`
3. Run: should complete in < 1 second

### Phase 3: Add Tier 2 lifecycle tests

1. Create `tests/test_lifecycle.py` — data flow, metadata, timer, ticks, heartbeat, top-of-book, fill records, tearsheet accuracy
2. Create `tests/test_exits.py` — convergence, resolution, TP/SL, end-of-data, FOK retry
3. Create `tests/test_orders.py` — order callback counters, FOK fill prices
4. Create `tests/test_artifacts_integration.py` — PNG/CSV/JSON generation
5. Create `tests/test_runner.py` — run_backtest pipeline, status.json lifecycle

### Phase 4: Migrate existing tests

1. Mark network tests in `test_pmxt_reader.py`, `test_gamma.py`, `test_integration.py` with `@pytest.mark.network`
2. Convert `test_trading_backtest.py` to use bundled data (remove `market_with_tokens`/`volatile_market` fixtures dependency, use `bundled_market_infos` instead)
3. The old session-scoped PMXT download fixture stays but is only used by `@pytest.mark.network` tests

### Phase 5: Configure pytest

Add to `pyproject.toml`:
```toml
[tool.pytest.ini_options]
markers = [
    "network: tests that require network access (deselect with '-m not network')",
]
```

Usage:
```bash
# Fast suite (< 40 seconds)
uv run pytest tests/ -m "not network" -x -q

# Full suite including network tests (< 5 minutes)
uv run pytest tests/ -x -q

# Only network tests
uv run pytest tests/ -m network -x -q
```

---

## 7. Fixture Architecture

### Scope hierarchy

```
session-scoped (created once per test run):
├── bundled_parquet_path          # Path to tests/data/test_hour.parquet
├── bundled_market_infos          # Parsed tests/data/test_markets.json
├── bundled_instruments           # (instruments, instrument_ids, market_ids) tuple
├── _pmxt_local_path              # Network: downloaded PMXT file (Tier 3 only)
├── market_with_tokens            # Network: discovered market metadata (Tier 3 only)
└── volatile_market               # Network: volatile market metadata (Tier 3 only)

function-scoped (created per test):
├── test_engine                   # BacktestEngine with bundled data loaded
├── mlflow_tmp_dir                # Temp dir for MLflow tests
├── tracking_uri                  # SQLite tracking URI
└── logger                        # MLflowLogger instance
```

### Helper functions (not fixtures)

```python
# conftest.py helpers
make_book_snapshot(instrument, instrument_id, bid, ask, ts_ns) -> OrderBookDeltas
make_price_path(start_bid, start_ask, end_bid, end_ask, num_ticks, start_ns, interval_ns) -> list[tuple]
make_synthetic_engine(instrument, instrument_id, price_path, start_ns, end_ns) -> BacktestEngine

# FAKE_MARKET constant — hardcoded market metadata for synthetic tests
FAKE_EXIT_MARKET = {...}
```

---

## 8. File Organization

### Final test directory structure

```
tests/
├── conftest.py                    # Shared fixtures: bundled data, synthetic helpers, network fixtures
├── data/
│   ├── test_hour.parquet          # ~100KB bundled PMXT data (1-2 markets, ~1000 rows)
│   └── test_markets.json          # Hardcoded market metadata for bundled data
├── test_unit.py                   # Tier 1: MarketMeta, config parsing, slug labels, file_url
├── test_tearsheet.py              # Tier 1: Tearsheet computation (existing, unchanged)
├── test_transformer.py            # Tier 1: PMXT transformation (existing, unchanged)
├── test_universe.py               # Tier 1: Instrument building (existing, unchanged)
├── test_mlflow_logger.py          # Tier 1: MLflow hierarchy (existing, unchanged)
├── test_discovery.py              # Tier 1/2: Actor + dynamic instruments (existing, unchanged)
├── test_lifecycle.py              # Tier 2: Strategy lifecycle, metadata, timers, ticks, heartbeat
├── test_exits.py                  # Tier 2: Exit lifecycle (convergence, resolution, TP/SL, end-of-data)
├── test_orders.py                 # Tier 2: Order callbacks, FOK mechanics
├── test_artifacts_integration.py  # Tier 2: PNG/CSV/JSON artifact generation
├── test_runner.py                 # Tier 2: run_backtest pipeline, status.json lifecycle
├── test_trading_backtest.py       # Tier 2 (migrated): Trading with bundled data (existing, modified)
├── test_pmxt_reader.py            # Tier 3: PMXT reader (existing, network tests marked)
├── test_gamma.py                  # Tier 3: Gamma/CLOB API (existing, network tests marked)
└── test_integration.py            # Tier 3: Full E2E (existing, marked network, consider removing)
```

### Naming conventions

- `test_unit.py` — pure function tests, no engine
- `test_<module>.py` — tests for a specific module (tearsheet, transformer, etc.)
- `test_<behavior>.py` — tests for a cross-cutting behavior (lifecycle, exits, orders)
- `test_<module>_integration.py` — integration tests for a module that needs an engine

### Test naming within files

```python
class TestMarketMeta:           # Group by feature
    def test_slug_timestamp(self):        # Specific behavior
    def test_is_active_at_in_window(self):

class TestConvergenceExit:      # Group by exit type
    def test_near_one(self):
    def test_near_zero(self):
```

---

## 9. Expected Test Counts and Timing

### After migration

| Tier | File | Tests | Time |
|------|------|-------|------|
| 1 | test_unit.py | ~11 | < 0.5s |
| 1 | test_tearsheet.py | 16 | < 0.1s |
| 1 | test_transformer.py | 9 | < 0.1s |
| 1 | test_universe.py | 2 | < 0.1s |
| 1 | test_mlflow_logger.py | 8 | < 1s |
| 1/2 | test_discovery.py | 15 | < 2s |
| 2 | test_lifecycle.py | ~13 | < 15s |
| 2 | test_exits.py | ~8 | < 10s |
| 2 | test_orders.py | ~3 | < 3s |
| 2 | test_artifacts_integration.py | ~5 | < 2s |
| 2 | test_runner.py | ~3 | < 5s |
| 2 | test_trading_backtest.py | 3 | < 5s |
| **Fast total** | | **~96** | **< 40s** |
| 3 | test_pmxt_reader.py | 4 | ~2 min |
| 3 | test_gamma.py | 17 | ~1 min |
| 3 | test_integration.py | 1 | ~3 min |
| **Full total** | | **~118** | **< 5 min** |

**Note on timing estimates:** Each Tier 2 test creates a function-scoped BacktestEngine, loads bundled data via PyArrow (~100ms), transforms ~1000 rows (~300ms), and runs a strategy. Estimated ~0.5-1.5s per test. The < 40s target is conservative — actual timing depends on engine creation overhead and number of fills per test.

### Improvement

| Metric | Before | After |
|--------|--------|-------|
| Total tests | 81 | ~118 |
| Fast suite time | ~6 min (all tests) | < 40s (Tier 1+2) |
| BEHAVIORS.md coverage | ~30% | ~95% (all 33 behaviors mapped) |
| Network-dependent tests | ~24 (always run) | ~22 (opt-in only) |
| Exit lifecycle tests | 0 | 8 |
| Artifact tests | 0 | 5 |
| Runner pipeline tests | 0 | 3 |
| Active window trading test | 0 | 1 |

---

## 10. Implementation Priority

**Phase 1 (highest value, do first):**
1. Generate bundled test data + market metadata JSON
2. Add Tier 2 fixtures to conftest.py
3. Write `test_lifecycle.py` — proves the framework works end-to-end without network
4. Write `test_exits.py` — covers the most complex framework behavior (exit lifecycle)

**Phase 2 (high value):**
5. Write `test_unit.py` — catches regressions in pure functions
6. Write `test_orders.py` — verifies order callback handling
7. Mark existing network tests with `@pytest.mark.network`
8. Migrate `test_trading_backtest.py` to use bundled data

**Phase 3 (cleanup):**
9. Write `test_artifacts_integration.py` — verifies PNG/CSV generation
10. Write `test_runner.py` — verifies run_backtest pipeline
11. Configure pytest marks in pyproject.toml
12. Consider removing `test_integration.py` (redundant with migrated trading tests)

---

## Appendix A: Synthetic Price Path Examples

### Convergence path (mid → 1.0)
```python
# 100 ticks over 10 minutes, price rising from 0.50 to 0.97
start_ns = 1773046800_000_000_000  # some epoch
ticks = []
for i in range(100):
    t = i / 100.0
    bid = 0.50 + t * 0.47  # 0.50 → 0.97
    ask = bid + 0.01
    ts = start_ns + i * 6_000_000_000  # 6s intervals
    ticks.append((ts, round(bid, 3), round(ask, 3)))
```

### Take-profit path (entry at 0.50, rises to 0.60)
```python
# 50 ticks: stable at 0.50 for entry, then rises
ticks = []
for i in range(50):
    ts = start_ns + i * 6_000_000_000
    if i < 10:
        bid, ask = 0.50, 0.51  # stable for entry
    else:
        progress = (i - 10) / 40.0
        bid = 0.50 + progress * 0.10  # rise to 0.60
        ask = bid + 0.01
    ticks.append((ts, round(bid, 3), round(ask, 3)))
```

### Stop-loss path (entry at 0.50, drops to 0.40)
```python
ticks = []
for i in range(50):
    ts = start_ns + i * 6_000_000_000
    if i < 10:
        bid, ask = 0.50, 0.51
    else:
        progress = (i - 10) / 40.0
        bid = 0.50 - progress * 0.10  # drop to 0.40
        ask = bid + 0.01
    ticks.append((ts, round(bid, 3), round(ask, 3)))
```

### End-of-data path (steady, relies on timer)
```python
# 3600 ticks over 1 hour at 1s intervals, steady price
ticks = [(start_ns + i * 1_000_000_000, 0.50, 0.51) for i in range(3600)]
```

### FOK retry path (entry → convergence → zero liquidity → restored)
```python
# 120 ticks over 6 minutes at 3s intervals
# Phase 1: stable entry, Phase 2: convergence, Phase 3: empty book, Phase 4: restored
ticks = []
for i in range(120):
    ts = start_ns + i * 3_000_000_000
    if i < 10:
        bid, ask = 0.50, 0.51          # entry fills
    elif i < 30:
        bid, ask = 0.96, 0.97          # convergence triggers exit
    elif i < 60:
        bid, ask = 0.96, 0.0           # sell-side empty — FOK SELL cancels
    else:
        bid, ask = 0.96, 0.97          # liquidity restored — retry succeeds
    ticks.append((ts, round(bid, 3), round(ask, 3)))
```
**Zero-liquidity encoding:** When `ask=0.0`, `make_book_snapshot` should use `asks=[["0.97", "0"]]` (zero quantity) instead of `asks=[]`. This ensures `transform_book_snapshot` generates a valid CLEAR + ADD(qty=0) sequence. The matching engine will see no executable liquidity and cancel the FOK order. Verify during implementation that this produces the expected cancel event.

### FOK permanent failure path (gives up after 3 retries)
```python
# 200 ticks over 10 minutes — zero sell-side after entry
ticks = []
for i in range(200):
    ts = start_ns + i * 3_000_000_000
    if i < 10:
        bid, ask = 0.50, 0.51          # entry
    else:
        bid, ask = 0.96, 0.0           # convergence + permanent zero liquidity
    ticks.append((ts, round(bid, 3), round(ask, 3)))
```

## Appendix B: Key Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Bundled data becomes stale (PMXT format changes) | Tier 2 tests fail | Regenerate with script. Format hasn't changed in months. |
| Synthetic data doesn't match real engine behavior | False passes | Validate synthetic tests against one real-data test |
| NautilusTrader internal API changes break tests | Test failures | Pin nautilus_trader version. Tests use public API where possible. |
| FOK retry test is flaky (timing-dependent) | Intermittent failures | Use deterministic synthetic data with exact liquidity control |
| Log capture doesn't work with NautilusTrader's Rust logger | Can't verify log messages | Use state inspection (counters, sets) instead of log parsing |
