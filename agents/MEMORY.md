# MEMORY — Polymarket Framework Plan

## [WORKER] 2026-03-10 — Corrections Pass (v2.4 → v3.0)

### What I Did
Applied all 10 corrections from `agents/CORRECTIONS.md` to produce PLAN.md v3.0. Complete rewrite approach (not incremental edits) because corrections were cross-cutting — almost every section needed changes.

### Key Decisions

**Complete rewrite vs incremental edits:** Chose full rewrite because:
- C3 (flatten to v0/v1) touched every section's "BLOCKED UNTIL" blocks
- C10 (agent model) required Section 1 + Section 6 consistency
- C9 (runner automation) changed the state contract, runner script, and cycle diagram
- Incremental edits would risk inconsistency between sections

**`add_data_iterator()` API verified:** Checked `engine.pyx:920-950`. API is:
```python
engine.add_data_iterator(
    data_name: str,
    generator: Generator[list[Data], None, None],
    client_id: ClientId = None,
)
```
- Generator yields `list[Data]` sorted by `ts_init`
- Lazy evaluation — engine processes one batch, then requests next
- Does NOT validate `instrument_id` against cache (unlike `add_data()`)

**instrument-data connection verified:** Checked `engine.pyx:860-918`. The `add_data()` method inspects the first data element's `instrument_id` and validates it exists in cache. Connection is implicit through `instrument_id` field on data objects.

### What I Removed
- All "BLOCKED UNTIL (v2+)" sections (6 of them across Sections 4.1-4.6)
- Section 3.6 (Record-and-Replay — full dedicated section with code examples)
- Section 3.7 (Record-and-Replay vs PMXT comparison table)
- Blocks 8-13 (v2/v3 implementation blocks)
- Researcher/Writer/Analyzer agent model from Section 1 ASCII diagram
- `performance.json` and `analysis.md` from Analyst's automated outputs (now Analyst only writes `analysis.md`, runner writes `tearsheet.json`)

### What I Added
- Instrument-data connection explanation (Section 4.1)
- `add_data_iterator()` with PMXT generator example (Sections 3.3, 4.1, 5.1, 6.3)
- event_slug_builder live/paper/backtest asymmetry table (Section 4.4)
- Python library freedom note (Section 2.2, Section 9)
- All v0 position handling mechanisms a-e (Section 4.5)
- Inert instruments note (Section 4.1)
- `compute_tearsheet()` and `log_to_mlflow()` in runner script (Section 6.3)
- MLflow infra prerequisite note (Section 7)
- Backtest instrument builder concept (Section 4.4, Block 3)

## [WORKER] 2026-03-10 — Reviewer Fixes (v3.0 → v3.1)

### What I Did
Applied 2 must-fix issues and 1 optional cleanup identified by the reviewer in FEEDBACK.md/DONEXT.md.

### Fixes Applied
1. **Removed Section 5.4** (StreamingConfig subsection) — violated C3c/C4. The one-liner at line 239 already covers StreamingConfig. Deleted the entire subsection (5 lines + header).
2. **Fixed `reduce_only=True` in Section 4.5(a) code example** — replaced with explicit position-side check using `self.cache.position()`. Added inline comment warning against `reduce_only=True`. Now consistent with the WARNING block at line ~1086.
3. **Renamed `imbalance_v2.py` → `imbalance_iter2.py`** in the Section 6 sequence diagram — avoids confusion with v0/v1 scope tiers.

## [REVIEWER] 2026-03-10 — Iteration 2 Verification

### Result
All 10 corrections APPLIED. All 3 iteration 1 fixes APPLIED. 0 must-fix issues. Plan is ready for human review.

### Verified Against Source Code
- `add_data_iterator()` API at `engine.pyx:920-925` — exact match
- `event_slug_builder` at `providers.py:62, 128-129` — exact match
- `reduce_only` rejection at `execution.py:1092, 1167` — exact match

### Minor Observations (not blocking)
- Strategy filenames in state contract (line 1540) use `_v1` suffix while sequence diagram uses `_iter2` — inconsistent convention but cosmetic
- Missing `InstrumentId` import in Section 4.2 paper trading example — trivial

## [WORKER] 2026-03-10 — Final Polish (v3.1 → v3.2)

### What I Did
Applied the 2 optional cosmetic fixes from reviewer iteration 2.

### Fixes Applied
1. **Added `InstrumentId` import** to Section 4.2 paper trading example (line 603). Changed `from nautilus_trader.model.identifiers import TraderId` to `import TraderId, InstrumentId`. The code at line 640 uses `InstrumentId.from_str(...)` — now the import is present.
2. **Renamed strategy filenames** in state contract: `imbalance_v1.py` → `imbalance_iter1.py`, `spread_v1.py` → `spread_iter1.py`. Added comment clarifying `_iter` suffix is NOT a scope tier. Consistent with `imbalance_iter2.py` in the sequence diagram.

### Status
All work complete. Plan v3.2 ready for human review. No remaining items except human approval and subsequent execution plan.

## [REVIEWER] 2026-03-10 — Iteration 3 Final Verification

### Result
All 10 corrections APPLIED. All 5 previous fixes APPLIED. 0 must-fix issues. Plan v3.2 confirmed ready for human review.

### Verified Against Source Code (additional checks)
- `ReportProvider` methods: all 4 report methods exist as `@staticmethod` (`reporter.py:32, 54, 117, 171`)
- `Position.to_dict()` includes `realized_pnl` field (`position.pyx:231`) — `compute_tearsheet()` column access valid
- `reduce_only` rejection exists in both Python (`execution.py:1092`) AND Rust (`execution/mod.rs:532`)

### Review Convergence
Three iterations with monotonically decreasing issue counts confirms convergence:
- Iteration 1: 2 must-fix + 1 optional
- Iteration 2: 0 must-fix + 2 cosmetic
- Iteration 3: 0 issues

No further worker-reviewer iterations needed.
