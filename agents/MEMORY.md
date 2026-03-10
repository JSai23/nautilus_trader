## [WORKER] 2026-03-09 05:10

### Session: Plan v2 Writer (Iteration 1)

**Objective:** Rewrite agents/PLAN.md as a system plan that explains NautilusTrader to newcomers, uses EXISTS/BUILD/BLOCKED format, and deeply covers the PMXT data pipeline.

**Research completed:**
- Read full previous plan (agents/archive/PLAN_run1.md) - 27 code-verified claims
- Launched 4 research agents covering: BacktestEngine API, Sandbox/paper trading, Polymarket adapter, data catalog conversion pipeline
- All research returned comprehensive results with exact method signatures, file paths, and examples

**Key discoveries from research:**

1. **BacktestEngine API:** Constructor takes BacktestEngineConfig. Flow: add_venue() → add_instrument() → add_data() → add_strategy() → run() → get_result(). Streaming mode available for large datasets. FillModel and FeeModel are per-venue.

2. **Sandbox paper trading:** SandboxExecutionClient subscribes to `data.*.{venue}.*` on MessageBus, intercepts live data, routes to SimulatedExchange. Key config: SandboxExecutionClientConfig(venue, starting_balances, oms_type, account_type, book_type). Factory: SandboxLiveExecClientFactory.

3. **Polymarket adapter:** Data client supports L2_MBP book deltas, synthesized quotes, trade ticks via WS. Execution: limit orders only (GTC/GTD/FAK/FOK). No market/stop/modify. Instrument provider: Gamma API, CLOB API, or event_slug_builder. BinaryOption type with info dict.

4. **Data pipeline:** StreamingFeatherWriter creates `{catalog_path}/{env}/{instance_id}/{data_type}/{instrument}/...feather`. convert_stream_to_data() converts feather→parquet at `{catalog_path}/data/{data_type}/{identifier}/{ts}.parquet`. BacktestDataConfig queries parquet.

5. **PMXT data:** We know it's hourly Parquet dumps of all Polymarket data. We do NOT have samples to inspect the schema. The plan must describe what we know and flag the schema mapping as requiring investigation.

**Decision: Plan structure**
- Phase 1: Problem + scope + end-goal ASCII diagram
- Phase 2: Design (6 capabilities with EXISTS/BUILD/BLOCKED)
- Phase 3: Deep dives (4 concrete walkthroughs)
- Phase 4: Agentic loop
- Phase 5: Implementation blocks

### Plan v2.0 written — key design decisions:

1. **Added NautilusTrader Primer (Section 2):** Explains Strategy, Instrument, MessageBus, and Execution Modes from scratch. This was the biggest gap in run 1.

2. **PMXT pipeline is speculative:** We haven't inspected PMXT files. Documented what we know (file naming, sizes, content type) and what we must investigate (exact schema, column names). Provided a transformation pattern that will work once schema is known.

3. **Record-and-replay is the recommended first path:** It works today with zero custom code (just a config flag for recording + convert_stream_to_data() for replay). PMXT integration is v2.

4. **Every code example uses real imports and API calls:** Verified against research agent findings. Key patterns:
   - BacktestEngine: add_venue(NETTING, CASH, USDC) + add_instrument + add_data + run
   - Paper: TradingNode + PolymarketDataClientConfig + SandboxExecutionClientConfig + SandboxLiveExecClientFactory
   - Live: Same but swap to PolymarketExecClientConfig + PolymarketLiveExecClientFactory

5. **Emphasized the close_position() bug prominently:** Appears in constraints table, paper trading section, lifecycle section, and deep dives. This is the #1 gotcha for any Polymarket strategy.

6. **Fee economics table connected to market selection guidance:** Zero-fee markets first for validation, hourly crypto later. This affects which universe the agentic loop starts with.

## [WORKER] 2026-03-09 06:15

### Session: Plan v2 Fix Pass (Iteration 2)

**Objective:** Apply 4 MUST FIX + 3 SHOULD FIX issues from reviewer (FEEDBACK.md / DONEXT.md).

**Fixes applied:**

1. **MF-1: Removed `reduce_only=True` from resolution exit.** The Polymarket adapter rejects `reduce_only` orders (`execution.py:1092-1095`). Dangerous because SimulatedExchange in backtest/paper DOES support it — so the bug hides during testing and breaks in production. Fixed the sequence diagram to use explicit side checks. Added a WARNING box.

2. **MF-2: Fixed `StrategyClass.config_class` (nonexistent API).** NautilusTrader has no `config_class` attribute on Strategy. Fixed by requiring explicit `strategy_config_class` in the YAML config. Updated both Section 4.6 (parameterization) and Section 6.3 (runner script). Added `import_class()` helper.

3. **MF-3: Fixed orderbook JSON example.** Verified via `polymarket clob book` CLI:
   - No `hash` field exists
   - Added real fields: `last_trade_price`, `min_order_size`, `neg_risk`, `tick_size`
   - Timestamp is ISO 8601 (`"2026-03-09T04:19:38.241+00:00"`), NOT unix seconds
   - Added a field-by-field explanation table

4. **MF-4: Added ParquetDataCatalog explanation.** Inserted a callout box where it first appears (Section 3.4) explaining: what it is, where it lives, what methods it has, and its directory structure.

5. **SF-1: Completed runner script.** Replaced "Runner pseudocode" with full "Runner script". Implemented `build_backtest_engine()` and `build_paper_node()` inline using the exact patterns from Sections 4.1 and 4.2. Added real imports, `import_class()` helper, and `if __name__ == "__main__"` entry point.

6. **SF-2: Removed dangling BacktestDataConfig import.** Was imported in Section 5.1 but never used. Removed it. The plan now consistently uses `catalog.query()` + `engine.add_data()`.

7. **SF-3: Added FeeModel example.** Expanded Block 7 with:
   - Explanation of WHY we need a custom FeeModel (adapter hardcodes fees as None)
   - Complete `PolymarketFeeModel` class with `get_commission()` implementation
   - Reference to all 3 built-in fee models: `MakerTakerFeeModel`, `FixedFeeModel`, `PerContractFeeModel`
   - Warning that SandboxExecutionClientConfig hardcodes `MakerTakerFeeModel()` internally — no way to override fees in paper trading without modifying sandbox code

8. **SF-4: Already fixed.** `reject_stop_orders` was already in the parameter table (reviewer referenced wrong line numbers, likely from an earlier version).

**Additional nitpick fixes:**
- N-1: Added note about `add_venue()` having ~20 params (table shows curated subset)
- N-4: Changed fee table to show both bps and percentage ("1000 bps (10%)")

**Key discoveries during fixes:**

1. **SandboxExecutionClientConfig hardcodes MakerTakerFeeModel()** at line 130 of `sandbox/execution.py`. There is no config parameter to override it. This means paper trading ALWAYS has zero fees (since Polymarket adapter sets maker_fee/taker_fee to None). Fee accuracy is only achievable in backtest mode via `engine.add_venue(fee_model=...)`.

2. **FeeModel interface** is in `backtest/models/fee.pyx`. Single method: `get_commission(order, fill_qty, fill_px, instrument) -> Money`. Three built-in implementations exist. The factory pattern (`ImportableFeeModelConfig` + `FeeModelFactory`) supports dynamic loading from dotted paths.

3. **CLOB book timestamp is ISO 8601**, not unix seconds as the CLI guide stated. The actual format is `"2026-03-09T04:19:38.241+00:00"` — with millisecond precision and UTC offset.

## [REVIEWER] 2026-03-09 07:30

### Session: Plan v2.1 Review (Iteration 2)

**Objective:** Review plan v2.1 against 5 primary criteria (feature explanation, exists/build separation, actionability, PMXT depth, code examples) plus factual verification.

**Verified 15 code claims, 4 CLI claims.** 18 correct, 1 false (slug format).

**Issues found:**

1. **MUST FIX: Slug format is wrong.** Plan uses `btc-updown-1h-{timestamp}` but Polymarket slugs are `ethereum-up-or-down-march-8-2am-et`. Full coin name, "up-or-down", human-readable ET date. The slug builder code in Sections 4.4 and 5.3 would produce invalid slugs and silently return zero instruments.

2. **MUST FIX: signal.alarm() in runner doesn't raise TimeoutError.** SIGALRM terminates the process by default, no Python exception. Runner's paper trading timeout mechanism is broken. Needs a signal handler, threading timer, or removal.

3. **SHOULD FIX: ReportProvider inconsistency.** Section 5.1 uses `engine.trader.generate_order_fills_report()`, Section 6.3 uses `ReportProvider()` static methods. Both work but confusing for newcomers. This was N-2 from last review and went unaddressed.

4. **SHOULD FIX: Version bump.** Plan header says v2.1 but should be v2.2 after fixes.

**All 5 primary review criteria PASS.** All 7 previous-iteration fixes verified as correctly applied.

**Key discovery:** Polymarket event slugs use human-readable Eastern Time dates, not Unix timestamps. Slug builders need to format dates as `{month}-{day}-{hour}{am/pm}-et` and use full coin names. The slug format is fragile and may change — tag-based discovery via Gamma API is more robust for production.

## [WORKER] 2026-03-09 08:45

### Session: Plan v2.2 Fix Pass (Iteration 3)

**Objective:** Apply 2 MUST FIX + 2 SHOULD FIX issues from reviewer (FEEDBACK.md / DONEXT.md iteration 2).

**Fixes applied:**

1. **MF-1: Fixed slug builder format in Sections 4.4 and 5.3.**
   - Section 4.4: The 15-minute slug builder (`btc-updown-15m-{timestamp}`) is actually CORRECT — verified via `polymarket events list --tag 15m`. The NautilusTrader example slugs are accurate for 15-min markets. Added a comparison table showing that 15-min and 1h markets use completely different slug formats. Added a comprehensive warning about slug fragility and silent failure.
   - Section 5.3: Replaced the wrong hourly slug builder (`{asset}-updown-1h-{timestamp}`) with the correct format (`{coin}-up-or-down-{month}-{day}-{hour}{ampm}-et`). Uses `zoneinfo.ZoneInfo("America/New_York")` for ET conversion, full coin names (`bitcoin`, `ethereum`, `solana`), and `strftime("%-I%p").lower()` for 12-hour format.
   - Added recommendation to use tag-based Gamma API discovery for production (more robust than slug builders).

2. **MF-2: Fixed runner paper trading timeout.**
   - Replaced `signal.alarm()` + `except TimeoutError` with `threading.Timer(duration, lambda: node.stop())`.
   - `signal.alarm()` was wrong because SIGALRM kills the process by default (no Python exception raised) and is not asyncio-safe.
   - `node.stop()` is the correct graceful shutdown method (verified at `live/node.py:381`).
   - Timer is daemon thread so it doesn't block process exit.

3. **SF-1: Standardized ReportProvider usage.**
   - Updated Section 4.1 (BacktestEngine intro) and Section 5.1 (backtest walkthrough) to use `ReportProvider()` pattern instead of `engine.trader.generate_*_report()`.
   - All three reporting locations (4.1, 5.1, 6.3) now consistently use: `ReportProvider().generate_orders_report(orders)` with explicit args from cache.
   - Verified `ReportProvider.generate_account_report(account: Account)` takes an Account object.
   - Verified `cache.account_for_venue(venue)` exists at `cache/cache.pyx:3869`.

4. **SF-2: Bumped version header to Draft v2.2.**

**Key discoveries:**

1. **15-min and 1h Polymarket slugs use completely different formats.**
   - 15-min: `{ticker}-updown-15m-{unix_timestamp}` (e.g., `btc-updown-15m-1773030600`) — tickers (`btc`, `eth`, `sol`), UTC timestamp
   - 1h: `{coin_name}-up-or-down-{month}-{day}-{hour}{ampm}-et` (e.g., `ethereum-up-or-down-march-8-3am-et`) — full names (`bitcoin`, `ethereum`, `solana`), ET human-readable date
   - The reviewer's MF-1 was partially wrong — Section 4.4's 15-min builder IS correct. Only Section 5.3's 1h builder was wrong.

2. **Full coin name mapping for 1h markets** (verified via `polymarket events list --tag 1h`):
   `bitcoin`, `ethereum`, `solana`, `xrp`, `bnb`, `hype`

3. **`node.stop()` is at `live/node.py:381`** — "Stop the trading node gracefully."

## [REVIEWER] 2026-03-09 10:00

### Session: Plan v2.2 Review (Iteration 3)

**Objective:** Review plan v2.2 against 5 primary criteria + factual verification.

**Verified 11 code claims, 4 CLI claims.** All correct. Zero false claims found.

**Issues found:**

1. **MUST FIX: Runner config instantiation bypasses msgspec decoding.** `ConfigClass(**exp["parameters"])` passes raw YAML strings to fields typed as `InstrumentId` and `Decimal`. `InstrumentId.__init__` takes `(Symbol, Venue)`, not a string — this crashes. The fix: use `ConfigClass.parse(msgspec.json.encode(...))` or (better) NautilusTrader's built-in `StrategyFactory.create()` with `ImportableStrategyConfig`.

2. **SHOULD FIX: Plan doesn't mention ImportableStrategyConfig/StrategyFactory** — existing framework machinery for exactly the runner's use case.

3. **SHOULD FIX: Dead `import asyncio` in Section 4.2.**

4. **SHOULD FIX: `POLYMARKET_VENUE` constant exists but plan creates Venue manually.**

**Key discovery:** `NautilusConfig.parse()` routes through `msgspec.json.decode(raw, dec_hook=msgspec_decoding_hook)` which handles `InstrumentId.from_str()`, `Decimal()`, etc. Direct `__init__` via `**kwargs` bypasses this entirely. All config instantiation from serialized data MUST use the parse pathway.

**All 5 primary review criteria PASS.** All 4 previous-iteration fixes verified as correctly applied.

## [WORKER] 2026-03-09 11:15

### Session: Plan v2.3 Fix Pass (Iteration 4)

**Objective:** Apply 1 MUST FIX + 3 SHOULD FIX issues from reviewer (FEEDBACK.md / DONEXT.md iteration 3).

**Fixes applied:**

1. **MF-1: Replaced ConfigClass(**params) with StrategyFactory.create() in 3 locations.**
   - Section 4.6: Rewrote config-driven instantiation example to use `ImportableStrategyConfig` + `StrategyFactory`. Added detailed inline comments explaining WHY the parse path is needed (msgspec decoding hooks). Added WARNING box about never using direct `**kwargs` unpacking.
   - Runner `build_backtest_engine()`: Replaced `ConfigClass(**exp["parameters"])` with `StrategyFactory.create(ImportableStrategyConfig(...))`. Updated function signature — no longer takes `StrategyClass, ConfigClass` params.
   - Runner `build_paper_node()`: Same replacement. Same signature update.
   - Removed `import_class()` helper — no longer needed since StrategyFactory handles path resolution internally.
   - Updated `run_experiment()` to call `build_backtest_engine(exp)` and `build_paper_node(exp)` without class args.

2. **SF-1: Added ImportableStrategyConfig/StrategyFactory explanation.** Section 4.6 now leads with StrategyFactory as THE recommended approach, not as an afterthought. The reader sees the correct pattern first.

3. **SF-2: Removed dead `import asyncio`.** Found and removed from BOTH Section 4.2 (paper trading EXISTS example) AND Section 5.2 (paper trading deep dive). The original reviewer only flagged Section 4.2.

4. **SF-3: Added POLYMARKET_VENUE constant note.** Added an inline comment in Section 4.1's backtest example explaining both constants: `POLYMARKET` (str, for config dict keys) and `POLYMARKET_VENUE` (Venue, for engine.add_venue()). Runner now imports `POLYMARKET_VENUE` from `adapters.polymarket.common.constants` instead of creating `Venue("POLYMARKET")` manually.

5. **Version bumped to v2.3.**

**Key decisions:**

1. **Chose StrategyFactory over parse-only approach.** DONEXT offered two options: (A) `ConfigClass.parse(msgspec.json.encode(...))` or (B) `StrategyFactory.create()`. Chose B because it also handles path resolution, making `import_class()` unnecessary. This simplifies the runner significantly — fewer lines, fewer manual steps, fewer opportunities for bugs.

2. **Updated function signatures to match.** Since StrategyFactory internally resolves both the strategy class and config class from dotted paths, `build_backtest_engine()` and `build_paper_node()` no longer need `StrategyClass` and `ConfigClass` as parameters. They only need the experiment dict.

3. **Updated config.yml note.** Added explanation that YAML fields `strategy_class` and `strategy_config_class` map to `ImportableStrategyConfig.strategy_path` and `ImportableStrategyConfig.config_path` respectively.

**Verified:**
- `StrategyFactory.create()` signature: takes `ImportableStrategyConfig`, returns `Strategy` (`trading/config.py:129-153`)
- `ImportableStrategyConfig` fields: `strategy_path: str`, `config_path: str`, `config: dict[str, Any]` (`trading/config.py:103-121`)
- `POLYMARKET_VENUE` exported from `adapters/polymarket/__init__.py:33` and defined at `common/constants.py:25`

## [REVIEWER] 2026-03-09 12:30

### Session: Plan v2.3 Review (Iteration 4)

**Objective:** Final review of plan v2.3 against 5 primary criteria + factual verification.

**Verified 17 code claims, 1 CLI claim.** All correct. Zero false claims found.

**All 5 primary review tests PASS.** The plan has fully addressed the run 1 failure mode (name-dropping without explanation). Every NT feature is explained before use. EXISTS/BUILD/BLOCKED format is consistent.

**Issues found:**

1. **SHOULD FIX: Runner flowchart still says `importlib.import_module`** at line 1608. Stale from pre-StrategyFactory. Code below uses StrategyFactory — just the diagram label is wrong.

2. **SHOULD FIX: Runner's `export_reports()` missing `account.csv`** — State contract at line 1587 promises it, but the function (lines 1739-1749) doesn't generate it.

**Key discoveries:**

1. **`Trader.subscribe()` delegates to `self._msgbus.subscribe()`** — So the plan's claim that StreamingFeatherWriter subscribes on the MessageBus is functionally correct, even though the actual call goes through `self._trader.subscribe()`.

2. **SandboxExecutionClient fee model hardcoding is at line 119, not 130** as the plan claims. Minor line number discrepancy, not a functional issue.

3. **`generate_positions_report()` has an additional optional `snapshots` parameter** not mentioned in the plan. Doesn't break anything (defaults to None).

**Verdict:** Plan has converged. Issue severity declining each iteration (4 MF → 2 MF → 1 MF → 0 MF). Ready for use.

## [WORKER] 2026-03-09 13:00

### Session: Plan v2.4 Final Fix Pass (Iteration 5)

**Objective:** Apply final 2 SF + 2 N fixes from reviewer iteration 4.

**Fixes applied:**

1. **SF-1: Replaced `importlib.import_module` with `StrategyFactory.create()` in runner flowchart (line 1608).** Last stale reference to pre-StrategyFactory approach. Verified zero `importlib` references remain.

2. **SF-2: Added `account.csv` generation to `export_reports()`.** Added `trader.cache.account_for_venue(POLYMARKET_VENUE)` lookup and `reporter.generate_account_report(account)` call. Guarded with `if account:` since venue may not have an account in edge cases. State contract now matches runner code.

3. **N-1: Fixed line reference `sandbox/execution.py:130` → `sandbox/execution.py:119`.** Cosmetic but accurate.

4. **N-2: Skipped.** `generate_positions_report(positions, snapshots=None)` — the `snapshots` param is optional with `None` default. All call sites are correct as-is. Adding it would be noise.

5. **Version bumped to v2.4 (final).**

**Final state:** Zero issues remaining. Plan has gone through 4 review cycles with all issues addressed. Ready for use as the system plan for execution planning.
