# Backlog

## Architecture

1. **Separate framework from consumers.** `agent_pred/` is the framework — PMXT pipeline, universe discovery, runner, base strategy class, tearsheet, MLflow, agents. All configs and concrete strategies (timer_momentum, tick_stress, trend_follower, etc.) are *consumers* of the framework and should live in a separate folder entirely. The framework is our Polymarket extension for NautilusTrader. The strategies/configs are experiments built on top of it.

   Framework (stays in `agent_pred/`):
   - `src/pmxt/` — data pipeline
   - `src/universe/` — market discovery
   - `src/runner/` — backtest + paper runners
   - `src/strategy/base.py` — base strategy class
   - `src/agents/` — orchestrator
   - `tests/`
   - `agents/` — dev loop infrastructure

   Consumers (move out):
   - `configs/*.yml` — experiment configs
   - `src/strategy/*.py` (except `base.py`) — concrete strategies
   - Possibly their own tests

2. **Live universe discovery — dynamic market subscription at runtime.** Currently in progress (dev loop running). New markets need to be discovered, instruments added to cache, and data feeds subscribed — all without restarting the node. Major blocker for live trading.

## Observability & Monitoring

3. **Dashboard for all running strategies, backtests, and paper trading.** We need a single place to see everything that's running and how it's performing. Currently there's no way to monitor what's active.

   Needs:
   - See all running backtests and paper trading sessions at a glance
   - Check in on them via MLflow (metrics, PnL, fills, round trips)
   - Strategy dev loop should log results somewhere queryable (not just stdout in tmux)
   - The run scripts should register/update their status in a known location (file, MLflow, db — whatever works)
   - Graphs: equity curves, PnL over time, per-strategy comparison, drawdown
   - Historical view: which strategies ran when, how they performed, easy comparison
   - Think about what a proper strategy research workflow looks like — MLflow is the start but we probably need more visualization (tearsheet charts, market-level breakdown, etc.)

## Tooling

4. **Change strategy dev loop to use Claude Code CLI like the normal dev loop.** The current strategy dev loop should work the same way as `agents/run.sh` — worker/reviewer alternation via `claude -p` CLI. Not the Python orchestrator with `anthropic.Anthropic()`. Same pattern, just different session prompts focused on strategy development.
