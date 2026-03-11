# CORRECTIONS — Human Review of PLAN.md v2.4

These corrections must be incorporated into the next plan revision. Each one was verified by reading source code.

---

## CORRECTION 1: Section 4.1 — Instrument-Data Connection Is Unexplained

**Problem:** Section 4.1 shows `add_instrument()` and `add_data()` as separate calls but never explains how they're connected. A newcomer would wonder: "how does the engine know which data belongs to which instrument?"

**Answer (verified, `engine.pyx:860-918`):**
- They're connected via the `instrument_id` field on each data object.
- When you call `add_data(data)`, the engine inspects the first element:
  - If data has `instrument_id` (OrderBookDelta, TradeTick, QuoteTick), it validates that `instrument_id` already exists in the cache — you MUST call `add_instrument()` first.
  - If data is `Bar`, it checks `bar_type.instrument_id` against the cache.
- All data goes into one sorted list. At runtime, when a strategy calls `subscribe_book_deltas(instrument_id=X)`, the engine registers subscription name `OrderBookDelta.X`, and the message bus routes matching events to the strategy's `on_orderbook_deltas()` handler.
- **The connection is implicit via instrument_id.** You add them separately, the engine validates the link, and the message bus routes data to the right handler at runtime.

**Required fix:** Add a clear explanation of this mechanism in Section 4.1 where `add_instrument` and `add_data` are introduced. The reader must understand: (1) add instrument first, (2) add data second, (3) they're linked by instrument_id on the data objects, (4) the message bus routes data to strategy handlers based on subscriptions.

---

## CORRECTION 2: Section 4.1 — `add_data_iterator()` Not Mentioned (Streaming/Lazy Loading)

**Problem:** Section 4.1 only shows `add_data(list)` which requires all data preloaded in memory as Python objects. For PMXT data at 12 GB/day, this is a serious problem. The plan doesn't mention the first-class streaming alternative.

**Answer (verified, `engine.pyx:920-950`):**
`BacktestEngine.add_data_iterator()` exists exactly for this. It accepts a Python generator that yields `list[Data]` chunks:

```python
def pmxt_data_generator(parquet_files, condition_id):
    """Stream PMXT data without loading everything into memory."""
    for parquet_file in sorted(parquet_files):
        df = pd.read_parquet(parquet_file,
            filters=[("condition_id", "==", condition_id)])
        deltas = transform_to_orderbook_deltas(df)
        yield deltas  # list[OrderBookDelta]

engine.add_data_iterator(
    data_name="polymarket_orderbook",
    generator=pmxt_data_generator(files, cid),
    client_id=ClientId("POLYMARKET"),
)
```

Key details:
- Generator yields batches, engine processes each batch then asks for next — lazy evaluation
- Data must be sorted by `ts_init` within each yielded batch
- Unlike `add_data()`, this does NOT validate instrument_id against cache — you must still call `add_instrument()` first, but the data itself streams lazily
- There's also an internal subscription-based generator mechanism (`engine.pyx:962-999`) that pulls data in time-range windows, but `add_data_iterator()` is the public API

**Required fix:** Section 4.1 must introduce `add_data_iterator()` alongside `add_data()`, explain when to use which (small datasets → `add_data`, large datasets like PMXT → `add_data_iterator`), and show a concrete generator example for PMXT parquet files. This is critical for the PMXT pipeline — without it, the plan implies we need to load 12 GB into memory.

Also update Section 3 (PMXT pipeline) and Section 5.1 (backtest walkthrough) to use `add_data_iterator()` instead of `add_data()` for the PMXT path.

---

## CORRECTION 3: Scope Restructure — Flatten to v0/v1 Only, Kill v2/v3

**Problem:** The plan has v0/v1/v2/v3 tiers. This is overengineered for the actual goal. The user is building a **research playground to unblock experimentation today**, not long-term production infrastructure.

**Required changes:**

### 3a. Remove v2 and v3 entirely
- Delete all v2 and v3 sections, tier tables, and references.
- If something was in v2/v3 and is actually needed, it moves to v1. If it's not needed for the research playground, it's cut.
- No "future extensions" sections. No "design for but don't build." The plan covers what we do NOW.

### 3b. Move PMXT data pipeline into v1
- The PMXT transformer (external parquet → NautilusTrader types) is v1, not v2.
- This is the critical unblock for backtesting. Without it, there's no research.
- The pipeline is: download PMXT parquets → filter by condition_id → transform to `OrderBookDelta`/`TradeTick` → feed to `BacktestEngine` via `add_data_iterator()`.
- This is a Python-side transformer — no Rust changes needed. It belongs in v1.

### 3c. Remove record-and-replay / StreamingConfig from the plan
- The continuous recording pipeline (StreamingConfig → feather → convert → catalog → backtest) is **not relevant** to this project. That's long-term infrastructure for a separate production system.
- This plan is about getting a research environment running with historical PMXT data dumps.
- Mentioning StreamingConfig as context is fine (one sentence: "NautilusTrader also supports recording live data via StreamingConfig for later replay, but that's a separate concern"). Do NOT dedicate a section to it.

### 3d. Resulting scope

| Tier | What it covers |
|------|---------------|
| **v0** | What works today with zero changes — live trading, paper trading, instrument discovery. Warts and all. |
| **v1** | Everything we build — PMXT data transformer, universe management, strategy base classes, market lifecycle handling, experiment runner, the agentic loop. All Python-side. |

That's it. Two tiers. Clear boundary: v0 = exists, v1 = we build.

---

## CORRECTION 4: Clarify the Two Data Paths (and Which One We Care About)

**Problem:** The plan conflates two different data paths — record-and-replay (built-in) and PMXT historical (must build). This confuses the reader about what's native vs custom.

**The two paths:**

| Path | Source | Conversion | Exists? | Relevant to us? |
|------|--------|-----------|---------|-----------------|
| **Record-and-replay** | Live data → StreamingConfig → feather → `convert_stream_to_data()` → parquet catalog → backtest | Fully built into NautilusTrader (`ParquetDataCatalog.convert_stream_to_data()`) | YES — zero custom code | **NO** — this is production infra, not our research playground |
| **PMXT historical** | PMXT parquet dumps (external schema) → custom transformer → NautilusTrader types → `add_data_iterator()` → BacktestEngine | Custom Python transformer mapping PMXT columns to `OrderBookDelta` fields | NO — must build | **YES** — this is how we backtest |

**Required fix:** The plan should mention record-and-replay briefly as context ("NautilusTrader has this built-in, but it's not what we're using"). Then focus entirely on the PMXT path. No dedicated section for StreamingConfig. No pipeline diagrams for record-and-replay.

---

## CORRECTION 5: event_slug_builder — Explain Clearly, Address Live/Paper/Backtest Asymmetry

**Problem:** The plan references `event_slug_builder` but doesn't explain how it actually works or address a critical asymmetry: it only works for live/paper modes (it calls the Gamma API at runtime), NOT for backtesting.

**How event_slug_builder works (verified, `providers.py:43-156`, `slug_builders.py`):**

The `event_slug_builder` is a config option on `PolymarketInstrumentProviderConfig`. You give it a fully qualified Python path to a function that returns `list[str]` — a list of Polymarket event slugs. When the instrument provider initializes (or refreshes), it calls your function, gets the slug list, then fetches each event from the Gamma API to discover instruments.

Example — loading all BTC 15-min UpDown markets for the next 2 hours:

```python
# slug_builders.py
def build_btc_updown_slugs() -> list[str]:
    now = datetime.now(tz=UTC)
    minutes = (now.minute // 15) * 15
    base_time = now.replace(minute=minutes, second=0, microsecond=0)
    slugs = []
    for i in range(8):
        interval_time = base_time + timedelta(minutes=15 * i)
        timestamp = int(interval_time.timestamp())
        slugs.append(f"btc-updown-15m-{timestamp}")
    return slugs

# config
instrument_config = PolymarketInstrumentProviderConfig(
    event_slug_builder="myproject.slug_builders:build_btc_updown_slugs",
)
```

The provider calls the Gamma API per slug (`_fetch_event_by_slug`), extracts condition_id + token_ids from each event's markets, and creates `BinaryOption` instruments. It handles missing slugs gracefully (logs warning, continues). It can also auto-refresh on an interval via `update_instruments_interval_mins`.

**The asymmetry across execution modes:**

| Mode | How instruments are discovered | event_slug_builder works? |
|------|-------------------------------|--------------------------|
| **Live** | Provider calls Gamma API at startup + refresh intervals | YES — this is what it was built for |
| **Paper** | Same as live — provider calls Gamma API | YES — identical to live |
| **Backtest** | Instruments must be added manually via `engine.add_instrument()` | **NO** — there's no API to call, no provider running. You must construct BinaryOption instruments yourself from PMXT data or cached metadata. |

**Required fix:** The plan must:
1. Explain event_slug_builder clearly (what it is, how the function works, the Gamma API call chain)
2. Explicitly state this is a **live/paper-only** mechanism
3. For backtesting, explain that instruments must be constructed manually — the slug builder doesn't help because there's no live API. You'd build instruments from PMXT metadata or pre-cached instrument definitions. This is part of the PMXT transformer (v1).
4. Show the existing example at `examples/live/polymarket/slug_builders.py` and `polymarket_slug_builder_tester.py`

---

## CORRECTION 6: Python Library Freedom — No Restrictions

**Problem:** The plan doesn't clarify whether strategies are sandboxed or can use arbitrary Python libraries.

**Answer (verified by examining example strategies):**
NautilusTrader strategies are plain Python classes inheriting from `Strategy`. There is **zero restriction** on what Python libraries you import. Example strategies already use `pandas`, and there's nothing preventing you from importing `numpy`, `sklearn`, `torch`, `polars`, `requests`, or anything else.

Your strategy's `on_orderbook_deltas()` handler is a normal Python method. You can do whatever you want inside it — call ML models, compute features with numpy, log to external services, read files. The only constraint is performance: if your handler takes too long, you'll fall behind the data stream in live/paper mode. In backtesting this doesn't matter (it's synchronous replay).

**Required fix:** Add a clear statement in the strategy section: "Strategies are plain Python — you can import any library (numpy, pandas, sklearn, torch, etc). No sandboxing, no restrictions. The only consideration is handler latency in live mode."

---

## CORRECTION 7: Position Handling for Unsold/Expiring Markets — v0 Options

**Problem:** The plan identifies that `close_position()` uses MarketOrder (which Polymarket rejects) but doesn't fully explore what v0 options exist for handling positions approaching resolution.

**Answer (verified from codebase):**

NautilusTrader has several mechanisms a strategy can use in v0 (no platform changes) to handle expiring positions:

**a) Price-threshold exit (works in v0):**
Inside `on_order_book_deltas()`, check best bid/ask. If the price converges past a threshold (e.g., bid > 0.95 or ask < 0.05), submit a limit order to exit:
```python
def on_order_book_deltas(self, deltas):
    book = self.cache.order_book(deltas.instrument_id)
    best_bid = book.best_bid_price()
    if best_bid and float(best_bid) > 0.95:
        # Market is resolving YES — sell our YES tokens via limit order
        self.submit_order(self.order_factory.limit(..., reduce_only=True))
```

**b) Time-based exit (works in v0):**
`BinaryOption` has `expiration_ns` (parsed from Polymarket's `end_date` at `parse.rs:185`). Strategy can check `self.clock.utc_now()` against the instrument's expiration and exit before resolution. However: some markets have `expiration_ns = 0` (no end_date set) — the strategy must handle this.

**c) No-quotes detection (works in v0):**
If the orderbook empties (no bids or asks), `book.best_bid_price()` returns `None`. Strategy can detect this:
```python
if book.best_bid_price() is None and book.best_ask_price() is None:
    # Book is empty — market may be resolving or illiquid
```

**d) `InstrumentClose` / `InstrumentStatus` events (exists in NT, unclear if Polymarket adapter emits them):**
NautilusTrader has `on_instrument_close()` and `on_instrument_status()` handlers (`data_actor.rs:398-408`). Strategies can subscribe via `subscribe_instrument_status()` / `subscribe_instrument_close()`. However — it's unclear whether the Polymarket adapter ever emits these events. This needs verification. If it doesn't, these handlers are useless for Polymarket.

**e) What happens to positions we DON'T sell:**
In backtesting: the backtest simply ends. Positions remain open. The PnL report shows unrealized PnL. There's no automatic settlement.
In live: the position stays on Polymarket. When the market resolves, Polymarket settles the CTF tokens — winning tokens become redeemable for USDC. NautilusTrader won't know about this automatically.
In paper: SimulatedExchange doesn't simulate resolution. Position stays open with last known price.

**Required fix:** Add a section explaining ALL of these v0 mechanisms for handling expiring positions. Be clear: (a-c) work today with zero changes, (d) might work but needs verification, (e) explains what happens if you do nothing. The strategy should implement a-c as part of its core logic — this is not an extension, it's fundamental strategy design.

---

## CORRECTION 8: Backtest Engine Only Processes Data You Add — Instruments Without Data Are Inert

**Problem:** The user asks whether adding many instruments but only some having data causes problems.

**Answer (verified, `engine.pyx:1300-1364`, `data_iterator.rs:80-106`):**

The BacktestEngine is entirely data-driven. It replays events from a sorted data stream chronologically. If you add an instrument but no data for it, that instrument simply never generates events — the strategy's handlers are never called for it. It's completely inert.

The engine doesn't iterate over instruments. It iterates over the data stream (a priority queue / binary heap in `BacktestDataIterator`). Only data objects you explicitly added via `add_data()` or `add_data_iterator()` appear in the stream. Adding 100 instruments but data for only 5 means only those 5 generate events.

The strategy's `subscribe_book_deltas(instrument_id=X)` registers a subscription. If no data exists for X, the subscription exists but never fires. No error, no warning — just silence.

**Required fix:** Add a clear note: "You can safely add more instruments than you have data for. The backtest engine only processes data that exists in the stream. Instruments without data are ignored — no errors, no overhead. This means you can define a broad universe of instruments and let the data availability determine which ones are actually active in the backtest."

---

## CORRECTION 9: Automate Metrics/Tearsheet/MLflow — Not the Analyst Agent's Job

**Problem:** The plan puts result parsing, metrics computation, and report generation in the analyst agent's responsibilities. This is wrong. Metrics computation is deterministic — it should be automated in the runner script, not done by an LLM.

**Required changes:**

The **runner script** (deterministic, not LLM) should:
1. Run the backtest via NautilusTrader
2. Extract results using `ReportProvider` (positions, orders, fills, account reports)
3. Generate a standardized tearsheet (PnL curve, drawdown, Sharpe, win rate, etc.)
4. Log everything to MLflow: hyperparameters, metrics, tearsheet artifacts
5. Write results to a known location on disk in a structured format

The **analyst agent** (LLM) should ONLY:
1. Read the already-computed tearsheet and metrics
2. Interpret results (why did this strategy work/fail?)
3. Propose next experiments based on patterns across runs
4. Write analysis to state files

**The boundary:** All number-crunching is deterministic and automated. The LLM reads finished reports and thinks about what to try next. It never computes metrics.

**MLflow hosting:** The infra repo (separate from this codebase) needs to be updated to host and serve an MLflow tracking server. Add this as a prerequisite in the plan's implementation blocks — "MLflow server must be running and accessible before the agentic loop can log experiments."

---

## CORRECTION 10: Fix Agent Role Inconsistency — Pick One Model

**Problem:** The plan uses two different agent models in different sections:
- Section 1 ASCII diagram: **Researcher → Writer → Analyzer** (3 agents)
- Section 6 (Agentic Loop Design): **Strategist + Analyst** (2 agents)

These are contradictory. Pick one and use it consistently everywhere.

**Required fix:** Use the **Strategist + Analyst** model from Section 6 (it's the better design — fewer handoffs, cleaner state contract). Update the Section 1 ASCII diagram to match. Remove all references to "Researcher" and "Writer" as separate agents. The Strategist does both research and writing. The Analyst interprets results and proposes next experiments.
