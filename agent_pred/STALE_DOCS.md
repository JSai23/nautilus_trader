# Stale Documentation

Tracked for future cleanup. Do not fix individually — batch update when addressing docs.

## Ghost Reference: `timer_momentum`

Strategy was renamed/replaced by `momentum_drift`. These files still reference the old name:

| File | What's wrong |
|------|-------------|
| `README.md` | Example command uses `timer_momentum.yml` (doesn't exist) |
| `experiments/CLAUDE.md` | Strategy inventory lists `timer_momentum` |
| `textbook/ch1_overview.md` | References `TimerMomentumStrategy` class |
| `textbook/ch5_backtests.md` | Example uses `timer_momentum.yml` and `TimerMomentumStrategy` |
| `textbook/ch7_live.md` | References `paper_momentum.yml` and `TimerMomentumStrategy` |

## Stale CLI Flags: `headless-reference.md`

`agents/prompts/headless-reference.md` documents flags that don't exist in the claude CLI:
- `--system-prompt-file` → should be `--system-prompt <string>`
- `--append-system-prompt-file` → should be `--append-system-prompt <string>`
- `--max-turns` → doesn't exist

This is the root cause of BUG-005 (run.sh uses these nonexistent flags).

## Normal Dev Loop Session Prompts

`agents/session/SESSION_WORKER.md` and `SESSION_REVIEWER.md` are still set to the paper trading verification task from a previous loop. They need to be rewritten before running a non-strategy dev loop.
