# Known Bugs & Issues

**Status key:** OPEN = confirmed bug, FIXED = resolved, WONTFIX = by design or not worth fixing

---

## BUG-001: PnL chart shows fewer points than round trips — FIXED

Replaced custom pairing logic in `generate_pnl_curve()` with `_compute_round_trip_pnls()` from tearsheet.py. Added `MaxNLocator(integer=True)` for x-axis.

---

## BUG-002: Double handler in base strategy — FIXED

Extracted shared logic into `_handle_book_update()`. Both `on_order_book_deltas()` and `on_order_book_delta()` now delegate to it.

---

## BUG-003: Tearsheet fill pairing can drop trades — WONTFIX

Strategies enforce one position per instrument via NETTING mode. Consecutive BUYs without an intervening SELL cannot occur in practice. The groupby-per-instrument approach is correct.

---

## BUG-004: Sharpe ratio uses wrong annualization factor — FIXED

Removed `sqrt(252)` annualization. Now reports per-trade Sharpe (mean/std) with explanatory comment.

---

## BUG-005: Agent loop CLI flags are stale — INVALID

`--append-system-prompt-file` IS a valid claude CLI flag (not shown in `--help` but works). The original bug report was wrong. The run.sh usage was correct all along. headless-reference.md was updated unnecessarily but the content is still accurate.

---

## BUG-006: `download_data.py` is unnecessary — FIXED

Deleted `scripts/download_data.py`. Runner handles PMXT data on-the-fly.

---

## BUG-007: PnL chart and tearsheet pairing logic diverged — FIXED

Both `generate_pnl_curve()` and `generate_trade_distribution()` in artifacts.py now call `_compute_round_trip_pnls()` from tearsheet.py instead of reimplementing pairing logic.
