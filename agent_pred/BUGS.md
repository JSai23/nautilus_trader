# Known Bugs & Issues

**Status key:** OPEN = confirmed bug, FIXED = resolved, WONTFIX = by design or not worth fixing

---

## BUG-001: PnL chart shows fewer points than round trips — OPEN

**Severity:** Medium
**Location:** `src/runner/artifacts.py:47-105` (`generate_pnl_curve`)

The PnL curve pairs BUY/SELL fills using a flat `pending_buys` dict keyed by instrument_id. Two problems:

1. **Timestamp ordering** — fills are sorted by `ts_event`, but if a SELL timestamp precedes its BUY (seen in run 29ca082d: SELL at 21:25:31, BUY at 21:27:00), the SELL finds no pending BUY and gets dropped. The subsequent BUY goes into pending but never matches. Loses an entire round trip.
2. **Fractional x-axis** — with few data points (e.g. 3 round trips), matplotlib auto-ticks at 0.25, 0.50, 0.75... making "Trade #" axis nonsensical. Should force integer ticks.

**Result:** Chart says "2 trades" visually when tearsheet says 3 round trips / 8 fills.

**Fix:** Use the same `groupby("instrument_id")` approach as `_compute_round_trip_pnls` in tearsheet.py (which handles this correctly). Force `ax.xaxis.set_major_locator(MaxNLocator(integer=True))`.

---

## BUG-002: Double handler in base strategy — OPEN

**Severity:** Medium
**Location:** `src/strategy/base.py` — `on_order_book_deltas()` and `on_order_book_delta()`

Both handlers contain near-identical 70+ line implementations (BBO recording, exit checks, tick counting). The plural form handles `OrderBookDeltas`, the singular handles `OrderBookDelta`. Both can fire depending on the data source.

**Risk:** Changes to one handler without updating the other creates silent behavioral divergence.

**Fix:** Extract shared logic into a private method called from both handlers.

---

## BUG-003: Tearsheet fill pairing can drop trades — OPEN

**Severity:** Low (less severe than BUG-001 because tearsheet groups by instrument)

**Location:** `src/runner/tearsheet.py:35-73` (`_compute_round_trip_pnls`)

The tearsheet groups by instrument_id before pairing, which is more robust than the artifact code. But it still uses `pending_buy = {"px": px, "qty": qty}` — if two consecutive BUYs happen on the same instrument (e.g. partial fill then re-entry before exit), the first BUY is overwritten.

**Likelihood:** Low in practice since strategies enforce one position per instrument.

---

## BUG-004: Sharpe ratio uses wrong annualization factor — OPEN

**Severity:** Low
**Location:** `src/runner/tearsheet.py:124-125`

```python
ts.sharpe_ratio = round(mean_pnl / std_pnl * math.sqrt(252), 4)
```

Uses `sqrt(252)` which assumes daily returns. But trades happen intraday (often minutes apart). The Sharpe is inflated/deflated depending on trade frequency.

**Fix:** Either use `sqrt(N)` where N = expected trades per year, or report per-trade Sharpe without annualization (simpler and more honest).

---

## BUG-005: Agent loop CLI flags are stale — OPEN

**Severity:** High (role prompts silently lost)
**Location:** `agents/run.sh:131-140`

```bash
claude -p \
  --append-system-prompt-file "$system_prompt_file" \   # DOES NOT EXIST
  ${max_turns:+--max-turns "$max_turns"} \              # DOES NOT EXIST
```

`--append-system-prompt-file` and `--max-turns` are not valid claude CLI flags. They're silently ignored, meaning the composed system prompt (session.md + worker.md/reviewer.md + specialization) **never reaches the model**. The worker/reviewer only sees the primer text passed via `-p`.

**Impact:** Loop "works" because the primer contains enough context, but role separation, primitives, and specializations are all dead weight.

**Fix:** Use `--system-prompt "$(cat $system_prompt_file)"` to inject inline.

---

## BUG-006: `download_data.py` is unnecessary — OPEN

**Severity:** Low (dead code)
**Location:** `scripts/download_data.py`

Runner handles PMXT data on-the-fly via `pmxt_data_generator()`. This script duplicates that and pre-caches data that may never be used.

**Fix:** Delete it.

---

## BUG-007: PnL chart and tearsheet pairing logic diverged — OPEN

**Severity:** Medium
**Location:** `src/runner/artifacts.py:68-85` vs `src/runner/tearsheet.py:55-71`

Both pair BUY/SELL fills to compute PnL, but use different algorithms:
- **Tearsheet:** groups by instrument_id first, then pairs sequentially. More correct.
- **Artifacts (PnL chart):** flat dict keyed by instrument_id, no grouping. Loses trades.

They should use the same function. The tearsheet's `_compute_round_trip_pnls()` should be the single source of truth, called by both.
