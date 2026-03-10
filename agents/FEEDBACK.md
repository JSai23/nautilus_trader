# FEEDBACK — Plan v2.3 Review (Iteration 4)

## Big Picture Assessment

**The plan is strong.** After 4 iterations, it has matured from a name-dropping reference document (run 1) into a genuine newcomer-friendly system plan. Every NautilusTrader feature is explained in plain English before being used. EXISTS/BUILD/BLOCKED separation is consistent across all 6 capability sections. The 5 deep-dive walkthroughs are concrete, with real Python code using real imports. The PMXT pipeline section is honest about what's known vs unknown.

Zero MUST FIX issues remain. The plan is close to final.

## Verification Summary

**17 code claims verified this iteration.** All correct. No false claims.

| Claim | Source File | Verdict |
|-------|-----------|---------|
| ImportableStrategyConfig fields: strategy_path, config_path, config | trading/config.py:103-121 | CORRECT |
| StrategyFactory.create() takes ImportableStrategyConfig, returns Strategy | trading/config.py:129-153 | CORRECT |
| StrategyFactory flow: resolve_path → resolve_config_path → msgspec.json.encode → parse | trading/config.py:140-153 | CORRECT |
| ReportProvider.generate_orders_report(orders) exists | analysis/reporter.py:32 | CORRECT |
| ReportProvider.generate_order_fills_report(orders) exists | analysis/reporter.py:54 | CORRECT |
| ReportProvider.generate_positions_report(positions) exists | analysis/reporter.py | CORRECT |
| ReportProvider.generate_account_report(account) exists | analysis/reporter.py | CORRECT |
| POLYMARKET_VENUE defined at common/constants.py:25 | adapters/polymarket/common/constants.py:25 | CORRECT |
| POLYMARKET_VENUE exported from __init__.py:33 | adapters/polymarket/__init__.py:33 | CORRECT |
| SandboxExecutionClient hardcodes MakerTakerFeeModel() | sandbox/execution.py:119 | CORRECT (line off — see N-1) |
| SandboxExecutionClient subscribes data.*.{venue}.* | sandbox/execution.py:148 | CORRECT |
| SandboxExecutionClient.on_data() routing | sandbox/execution.py:205-225 | CORRECT |
| StreamingFeatherWriter subscribes via trader.subscribe("*") | kernel.py:604 | CORRECT (functionally equivalent to msgbus) |
| convert_stream_to_data() signature | persistence/catalog/parquet.py:2428 | CORRECT |
| FeeModel.get_commission(order, fill_qty, fill_px, instrument) | backtest/models/fee.pyx:37-43 | CORRECT |
| Trader.subscribe() delegates to msgbus.subscribe() | trading/trader.py:801 | CORRECT |
| 1h slug format: {coin}-up-or-down-{month}-{day}-{hour}{ampm}-et | Polymarket CLI verified | CORRECT |

**1 Polymarket CLI claim verified:** Hourly crypto slugs match the format exactly. Examples: `ethereum-up-or-down-march-8-2am-et`, `solana-up-or-down-march-8-2am-et`.

## Previous Iteration Fixes — Verified

All 4 fixes from DONEXT iteration 3 are correctly applied:

| Fix | Status |
|-----|--------|
| MF-1: StrategyFactory.create() replaces ConfigClass(**params) in 3 locations (Section 4.6, build_backtest_engine, build_paper_node) | VERIFIED |
| SF-1: ImportableStrategyConfig/StrategyFactory explained in Section 4.6 with WARNING box | VERIFIED |
| SF-2: Dead `import asyncio` removed from Sections 4.2 AND 5.2 | VERIFIED |
| SF-3: POLYMARKET_VENUE imported from adapter in runner; standalone examples correctly use local Venue | VERIFIED |

Additional checks:
- No remaining references to `import_class()` helper | VERIFIED
- No remaining `importlib` import in runner code | VERIFIED
- Version header says v2.3 | VERIFIED
- No stale v2.0/v2.1/v2.2 version references in text | VERIFIED

## Primary Review Tests

### Test 1: Feature Explanation — PASS

Every NautilusTrader feature is explained before use. Key features verified:

| Feature | Where Explained |
|---------|----------------|
| BacktestEngine | S2.5 (overview), S4.1 (full API, complete code example) |
| SimulatedExchange | S2.5, S4.1, S4.2 (how it matches orders) |
| StreamingConfig | S3.6 (what it does, what gets recorded, file structure) |
| SandboxExecutionClient | S4.2 (internal sequence diagram, data routing) |
| Strategy class | S2.2 (full code example with all callbacks) |
| StrategyConfig | S2.2, S4.6 (serialization, frozen struct) |
| InstrumentProvider | S4.4 (three discovery methods with code) |
| MessageBus | S2.4 (Mermaid diagram, publish/subscribe explanation) |
| ParquetDataCatalog | S3.4 (callout box: what it is, where it lives, key methods) |
| ImportableStrategyConfig | S4.6 (field-by-field explanation + WARNING) |
| StrategyFactory | S4.6 (full flow explanation) |
| ReportProvider | S4.1, S5.1 (used with imports shown) |
| FeeModel | Block 7 (interface, custom implementation, built-in alternatives) |
| BinaryOption | S2.3 (properties, info dict, methods) |

No name-drops without explanation found.

### Test 2: Exists vs Build Separation — PASS

All 6 capability sections (4.1-4.6) use the EXISTS/BUILD/BLOCKED format consistently. No mixing.

### Test 3: Actionability — PASS

All 5 questions answerable from the plan:
1. "What can I do RIGHT NOW?" → Section 9 table
2. "What do I need to build to backtest with PMXT data?" → Section 3.3-3.5 step-by-step
3. "What do I need to build for paper trading?" → Section 4.2 shows it works TODAY
4. "How do I define a universe?" → Section 4.4 three methods with code
5. "How do strategies handle expiring markets?" → Section 4.5 state diagram + sequence diagram

### Test 4: PMXT Data Pipeline Depth — PASS

- Schema described (known fields from CLI): YES
- Unknown parts explicitly flagged: YES ("STATUS: We have not yet downloaded or inspected PMXT Parquet files")
- Mapping to NT types explicit: YES (OrderBookDelta, TradeTick field-by-field)
- Full pipeline step-by-step: YES (Filter → Transform → Load → Run with code)
- 12 GB/day size problem addressed: YES (PyArrow predicate pushdown filtering)
- Alternative path described: YES (Section 3.6 record-and-replay)
- Both paths compared: YES (Section 3.7 table)

### Test 5: Code Examples — PASS

All 4 required examples present as real Python (not pseudocode):
- Backtest setup: Section 4.1 + Section 5.1
- Paper trading setup: Section 4.2 + Section 5.2
- Minimal strategy: Section 2.2 + Section 5.2 (ImbalanceStrategy)
- Runner script: Section 6.3 (complete, ~160 lines)

## Issues Found

### SHOULD FIX

**SF-1: Runner flowchart references `importlib.import_module` (stale)**

Line 1608:
```
PARSE --> IMPORT["importlib.import_module<br/>to load strategy class"]
```

The runner code below this flowchart uses `StrategyFactory.create(ImportableStrategyConfig(...))` — there is no `importlib.import_module` call anywhere in the runner. This is a leftover from before the StrategyFactory migration (MF-1 iteration 3). The flowchart node should say `StrategyFactory.create<br/>to instantiate strategy` or similar.

**SF-2: Runner's `export_reports()` missing `account.csv`**

The state contract at line 1587 promises:
```
│   │   ├── account.csv           # Runner: from ReportProvider.generate_account_report()
```

But the runner's `export_reports()` function (lines 1739-1749) only generates `orders.csv`, `fills.csv`, and `positions.csv`. It does NOT generate `account.csv`. Either:
- (A) Add `account.csv` generation to `export_reports()` (need to pass venue or get account from cache), or
- (B) Remove `account.csv` from the state contract

Option A is better — the Analyst agent would benefit from account balance data. But `generate_account_report()` takes an `Account` object, so the function signature needs to change or it needs to look up the account from `trader.cache.account_for_venue(POLYMARKET_VENUE)`.

### NITPICKS

**N-1: Fee model hardcoding line number**

Plan says `sandbox/execution.py:130` (line 1971) but the actual hardcoding is at line 119. Not functionally wrong — the claim is accurate — but the line reference is off by 11.

**N-2: `generate_positions_report()` has an additional optional parameter**

`generate_positions_report(positions, snapshots=None)` — the plan only shows the `positions` parameter. This doesn't break anything (the optional param defaults to None), but the full signature would be more complete.

## Cumulative Issue Tracker

| Iteration | Issues Found | Issues Fixed | Remaining |
|-----------|-------------|-------------|-----------|
| 1 (review) | 4 MF + 3 SF | — | 4 MF + 3 SF |
| 2 (fix)    | — | 4 MF + 3 SF | 0 |
| 2 (review) | 2 MF + 2 SF | — | 2 MF + 2 SF |
| 3 (fix)    | — | 2 MF + 2 SF | 0 |
| 3 (review) | 1 MF + 3 SF | — | 1 MF + 3 SF |
| 4 (fix)    | — | 1 MF + 3 SF | 0 |
| 4 (review) | 0 MF + 2 SF | — | **0 MF + 2 SF** |

**The trend is clear: issue severity and count declining each iteration.** The plan has converged.
