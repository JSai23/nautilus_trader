# Stale Documentation — All Fixed

All items resolved as of 2026-03-14.

## Ghost Reference: `timer_momentum` — FIXED

Replaced all references with `momentum_drift` / `MomentumDrift`:
- `README.md` — FIXED
- `CLAUDE.md` — FIXED
- `experiments/CLAUDE.md` — FIXED (added momentum_drift to strategy table)
- `docs/textbook/ch1_overview.md` — was not actually stale (no reference found)
- `docs/textbook/ch5_backtests.md` — FIXED
- `docs/textbook/ch6_mlflow.md` — FIXED
- `docs/textbook/ch7_live.md` — FIXED

## Stale CLI Flags: `headless-reference.md` — FIXED

Updated `agents/prompts/headless-reference.md` to use correct flags:
- `--system-prompt-file` → `--system-prompt` (string arg)
- `--append-system-prompt-file` → `--append-system-prompt` (string arg)
- `--max-turns` → removed (doesn't exist)

## Normal Dev Loop Session Prompts — OPEN

`agents/session/SESSION_WORKER.md` and `SESSION_REVIEWER.md` are still set to the paper trading verification task. They need rewriting before running a non-strategy dev loop.
