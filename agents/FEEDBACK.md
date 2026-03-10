# FEEDBACK — Reviewer Iteration 3 (Final Verification)

**Reviewing:** PLAN.md v3.2 (all corrections + iteration 1 fixes + iteration 2 cosmetic fixes)
**Against:** agents/CORRECTIONS.md (10 corrections) + previous FEEDBACK/DONEXT iterations
**Date:** 2026-03-10

---

## Big Picture Assessment

The plan is complete and well-integrated. All 10 corrections have been applied. All reviewer fixes from iterations 1 and 2 have been applied. The document reads as a single coherent narrative — corrections are woven into the flow, not bolted on. The v0/v1 boundary is clean. The agent model is consistent. Source code references are accurate.

**Overall grade: 9.5/10.** No must-fix issues. One minor observation (ReportProvider method call style) is cosmetic and not worth changing.

---

## Correction-by-Correction Verification

### C1: Instrument-Data Connection — APPLIED

Lines 509-517. Four-part explanation:
1. Connection via `instrument_id` field on data objects
2. `add_instrument()` must be called first — `add_data()` validates against cache
3. `Bar` checks `bar_type.instrument_id`
4. Message bus routes data to strategy handlers via subscriptions

Source reference `engine.pyx:860-918` — verified. The validation logic at line 862 inspects the first element's `instrument_id`.

**Verdict: APPLIED. Correct and complete.**

### C2: `add_data_iterator()` — APPLIED

Coverage across 5+ locations:
- Section 3.3 (lines 266-299): Core introduction, comparison table, PMXT generator example, key details
- Section 4.1 (lines 519-541): Second code example
- Section 5.1 (lines 1241-1265): Backtest walkthrough uses `add_data_iterator()`
- Section 6.3 (lines 1626-1637): Runner script uses `add_data_iterator()`
- Section 3.4 (line 369): Pipeline diagram ends with `add_data_iterator()`

API verified against `engine.pyx:920-925`:
```
def add_data_iterator(self, str data_name, generator: Generator[list[Data], None, None], ClientId client_id = None)
```
Plan matches exactly.

**Verdict: APPLIED. Thorough and accurate.**

### C3: Flatten to v0/v1 — APPLIED

Searched for `v2`, `v3`, `tier 2`, `tier 3` (case-insensitive) across entire plan. Results:
- `v3.2` — plan version number (acceptable)
- `v2.4` — historical reference in header (acceptable)
- `stateDiagram-v2` — Mermaid syntax at line 1050 (not a scope tier)

No other matches. All "BLOCKED UNTIL" sections removed (confirmed via grep). v0/v1 tier table at lines 50-53 is clean. EXISTS/BUILD format used consistently in Sections 4.1-4.6.

StreamingConfig reduced to one-liner at line 239. No Section 5.4.

PMXT pipeline is v1 (Section 3, Block 4). Correct.

**Verdict: APPLIED. Complete.**

### C4: Two Data Paths — APPLIED

Line 239 provides the brief context mention: "NautilusTrader also supports recording live data via StreamingConfig for later replay... but that's a separate concern for production infrastructure." No dedicated section for StreamingConfig/record-and-replay. Only references to StreamingFeatherWriter are in Section 2.4 (MessageBus diagram, line 186) — contextual, not a deep-dive. The plan focuses entirely on the PMXT path.

**Verdict: APPLIED. Complete.**

### C5: event_slug_builder — APPLIED

Section 4.4 (lines 838-968). Covers:
1. What it is: config option, fully qualified Python path to callable returning `list[str]`
2. How it works: provider calls Gamma API per slug
3. Asymmetry table (lines 853-857): Live=YES, Paper=YES, Backtest=NO
4. Backtest workaround: construct instruments from PMXT data (lines 851, 967)
5. Existing examples referenced (line 859)
6. Both 15-minute and hourly slug builders with code (lines 870-920)
7. Slug format fragility warning (lines 861-868, 922)
8. Tag-based alternative noted (line 922)

Verified against `providers.py`:
- `event_slug_builder: str | None = None` at line 62 — matches
- `slug_builder = resolve_path(self._config.event_slug_builder)` then `event_slugs: list[str] = slug_builder()` at lines 128-129 — matches
- Provider checks for `event_slug_builder` first before `use_gamma_markets` at lines 103-108 — consistent

**Verdict: APPLIED. Excellent coverage.**

### C6: Python Library Freedom — APPLIED

Line 152 in Section 2.2:
> "Strategies are plain Python — you can import any library (numpy, pandas, sklearn, torch, polars, etc). No sandboxing, no restrictions."

Includes handler latency caveat. Also in Summary table at line 2005.

**Verdict: APPLIED. Correct.**

### C7: Position Handling — APPLIED

Section 4.5, lines 969-1033. All five mechanisms present:
- (a) Price-threshold exit with code example (lines 977-998) — uses explicit position-side check (`position.is_long`), NOT `reduce_only=True`. Inline comment: "NOTE: Do NOT use reduce_only=True — Polymarket rejects it in live mode."
- (b) Time-based exit with `expiration_ns` (lines 1000-1002) — includes `expiration_ns = 0` caveat
- (c) No-quotes detection (lines 1004-1012)
- (d) InstrumentClose/InstrumentStatus — unverified for Polymarket (lines 1014-1016)
- (e) Unsold positions table by mode (lines 1018-1024) — Backtest/Live/Paper
- Summary at line 1026: "a-c work today with zero changes"

`reduce_only` rejection verified at `execution.py:1092` and `execution.py:1167` — plan references accurate.

WARNING block at line 1086 is consistent with the code example — no contradiction.

**Verdict: APPLIED. Correct. Code example properly fixed from iteration 1.**

### C8: Inert Instruments — APPLIED

Lines 543-545. Clear explanation:
> "You can safely add more instruments than you have data for. The BacktestEngine is entirely data-driven..."

References `engine.pyx:1300-1364`, `data_iterator.rs:80-106`. Explanation of priority queue/binary heap, subscription behavior, no overhead.

**Verdict: APPLIED. Correct.**

### C9: Runner Automation — APPLIED

Section 6.3 (lines 1547-1796). Complete runner implementation:
- `build_backtest_engine()` — loads instruments, streams PMXT via `add_data_iterator()`, uses `StrategyFactory.create()`
- `build_paper_node()` — TradingNode in sandbox mode with timed shutdown
- `compute_tearsheet()` (lines 1687-1729) — extracts via `ReportProvider`, computes: total_pnl, num_trades, num_positions, win_rate, win_count, loss_count. Writes `tearsheet.json` + CSV reports.
- `log_to_mlflow()` (lines 1731-1747) — logs params, metrics, artifacts. Import is inside the function (lazy).
- `run_experiment()` (lines 1749-1795) — orchestrates all of the above, writes metadata.json
- MLflow failure handled gracefully (try/except at lines 1788-1791)

Analyst role at line 1516: "Reads the **already-computed** tearsheet and metrics."

The boundary is clean: runner does all computation, analyst reads finished reports.

MLflow infra prerequisite stated at lines 1880, 1911, 1976.

Verified ReportProvider API against source:
- `generate_orders_report(orders)` — exists at `reporter.py:32` (static method)
- `generate_order_fills_report(orders)` — exists at `reporter.py:54` (static method)
- `generate_positions_report(positions)` — exists at `reporter.py:117` (static method)
- `generate_account_report(account)` — exists at `reporter.py:171` (static method)
- `positions_report["realized_pnl"]` — verified: `Position.to_dict()` includes `realized_pnl` at `position.pyx:231`

**Verdict: APPLIED. Solid implementation. API matches source code.**

### C10: Agent Model Consistency — APPLIED

Section 1 diagram (lines 19-45): Shows Strategist Agent, Runner (Python, NO LLM), Analyst Agent. No Researcher, Writer, or Analyzer.

Searched for "Researcher", "Writer", "Analyzer" as agent roles in PLAN.md: zero matches. Only "StreamingFeatherWriter" (a NautilusTrader class name in Section 2.4) — not an agent role.

Section 6 roles table (lines 1512-1516): Strategist + Runner + Analyst. Consistent with diagram.

`imbalance_iter1.py` (line 1540), `spread_iter1.py` (line 1541), `imbalance_iter2.py` (line 1809) — all use `_iter` suffix, not `_v` suffix.

**Verdict: APPLIED. Consistent everywhere.**

---

## Previous Iteration Fixes Verification

| Fix | Status |
|-----|--------|
| Remove Section 5.4 (StreamingConfig subsection) | **DONE** — only line 239 one-liner remains |
| Fix `reduce_only=True` in Section 4.5(a) code example | **DONE** — uses explicit position-side check + inline warning |
| Rename `imbalance_v2.py` → `imbalance_iter2.py` | **DONE** — line 1809 |
| Add `InstrumentId` import in Section 4.2 | **DONE** — line 603 |
| Rename `imbalance_v1.py`/`spread_v1.py` → `_iter1` in state contract | **DONE** — lines 1540-1541 |

---

## Scope Cleanup

- **v2/v3 references:** All removed except plan version ("v2.4", "v3.2") and Mermaid syntax (`stateDiagram-v2`)
- **EXISTS/BUILD format:** Consistent across Sections 4.1-4.6
- **Two-tier table:** Clean at lines 50-53
- **No "BLOCKED UNTIL" sections:** Confirmed absent via grep

---

## Agent Model Consistency

- Section 1 diagram: Strategist + Runner (no LLM) + Analyst
- Section 6 roles table: Same three components
- No references to "Researcher", "Writer", or "Analyzer" as agent roles
- Runner clearly positioned as deterministic ("Python, NO LLM" in diagram, "deterministic, no LLM" in code)

---

## Runner Automation

- `compute_tearsheet()` computes: total_pnl, num_trades, num_positions, win_rate, win_count, loss_count
- `log_to_mlflow()` logs: params, metrics, artifacts
- MLflow failure handled gracefully (try/except)
- MLflow infra prerequisite stated at lines 1880, 1911, 1976
- Analyst role limited to reading finished reports and interpreting
- ReportProvider API calls match actual source code (all 4 static methods verified)
- `positions_report["realized_pnl"]` column exists (from `Position.to_dict()`)

---

## PMXT Focus

- StreamingConfig reduced to one-liner at line 239
- PMXT transformer clearly in v1 (Section 3, Block 4)
- PMXT pipeline uses `add_data_iterator()` consistently (Sections 3.3, 3.4, 4.1, 5.1, 6.3)

---

## Newcomer Clarity (Spot-Check — 3 Features)

1. **StrategyConfig** (Section 2.2, lines 105-152): Code example with frozen struct, field annotations, key points for newcomers, library freedom statement. A newcomer would understand what StrategyConfig is, how to define one, and what the constraints are.

2. **BacktestEngine** (Section 4.1, lines 430-580): Complete API walkthrough with line-by-line commented code. `add_venue()` parameters table with Polymarket-specific settings. Instrument-data connection explained. Two data loading methods shown. Inert instruments noted. A newcomer could write a working backtest from this section alone.

3. **event_slug_builder** (Section 4.4, lines 838-920): Full explanation of what it is, how the function works, the Gamma API call chain, live/paper/backtest asymmetry table, two code examples (15-min and hourly), slug format fragility warnings. Not just name-dropped — thoroughly explained.

**Verdict: Newcomer clarity is strong.** Features are explained (what, how, code, caveats), not just referenced.

---

## Factual Accuracy (Spot-Checks)

1. **`add_data_iterator()` API** — Verified at `engine.pyx:920-925`. Plan states: `data_name: str, generator: Generator[list[Data], None, None], client_id: ClientId = None`. Source confirms exact signature.

2. **`event_slug_builder`** — Verified at `providers.py:62`: `event_slug_builder: str | None = None`. At lines 128-129: `slug_builder = resolve_path(self._config.event_slug_builder)` then `event_slugs: list[str] = slug_builder()`. Plan matches.

3. **`reduce_only` rejection** — Verified at `execution.py:1092`: `if order.is_reduce_only:` followed by error log. Also at Rust side: `execution/mod.rs:532`. Also `execution.py:1167`: `return "REDUCE_ONLY_NOT_SUPPORTED"`. Plan references are accurate.

4. **`ReportProvider` API** — Verified all 4 report methods exist: `generate_orders_report`, `generate_order_fills_report`, `generate_positions_report`, `generate_account_report`. All are `@staticmethod`. The `positions_report["realized_pnl"]` column access is valid (verified via `Position.to_dict()` at `position.pyx:231`).

---

## Minor Observations (not must-fix)

### 1. `compute_tearsheet()` still basic — acknowledged

The tearsheet computes basic metrics (PnL, win rate) with comments noting Sharpe/drawdown will be added when sufficient data is available. This is appropriate for a plan — the exact computation depends on PMXT data format. Not a plan deficiency.

### 2. `ReportProvider` called via instance (cosmetic)

The runner creates `reporter = ReportProvider()` then calls `reporter.generate_orders_report(orders)`. These are `@staticmethod` methods, so `ReportProvider.generate_orders_report(orders)` would be more idiomatic Python. But calling a static method via an instance is valid Python and works fine. Not worth changing.

---

## Summary Table

| Correction | Status | Notes |
|-----------|--------|-------|
| C1: Instrument-data connection | **APPLIED** | Clear, correct, verified |
| C2: `add_data_iterator()` | **APPLIED** | 5+ locations, verified API |
| C3: Flatten to v0/v1 | **APPLIED** | All tiers clean, no BLOCKED sections |
| C4: Two data paths | **APPLIED** | One-liner only, no dedicated section |
| C5: event_slug_builder | **APPLIED** | Comprehensive, verified against providers.py |
| C6: Python library freedom | **APPLIED** | Clear statement + latency caveat |
| C7: Position handling | **APPLIED** | Code example fixed, all 5 mechanisms present |
| C8: Inert instruments | **APPLIED** | Clear, well-sourced |
| C9: Runner automation | **APPLIED** | Complete runner, verified ReportProvider API |
| C10: Agent model | **APPLIED** | Consistent everywhere, _iter convention |

| Previous Fix | Status |
|-------------|--------|
| Remove Section 5.4 | **DONE** |
| Fix reduce_only code | **DONE** |
| Rename imbalance_v2 | **DONE** |
| Add InstrumentId import | **DONE** |
| Rename _v1 → _iter1 filenames | **DONE** |

**10 of 10 corrections fully applied. 5 of 5 previous fixes applied. 0 must-fix issues. Plan v3.2 is ready for human review.**
