# agent_pred

Polymarket prediction market trading framework built on NautilusTrader.

## Structure

```
agent_pred/
├── src/                    # Framework code (importable packages)
│   ├── strategy/           # Base strategy class (PolymarketStrategy)
│   ├── runner/             # Backtest engine, tearsheet, MLflow, paper trading
│   ├── pmxt/               # PMXT historical data pipeline (parquet → NautilusTrader)
│   ├── universe/           # Market discovery (Gamma API, CLOB API, instruments)
│   └── discovery/          # Live market discovery actor (MarketDiscoveryActor)
├── experiments/            # Consumer code (strategies + configs)
│   ├── strategies/         # Concrete strategy implementations
│   └── configs/            # Experiment config YAMLs
├── scripts/                # CLI entry point
│   └── run_backtest.py     # Run backtest or paper trading from config YAML
├── tests/                  # pytest test suite
├── docs/                   # Detailed documentation
│   └── textbook/           # Framework textbook (ch1-ch7)
├── agents/                 # Dev loop infrastructure (gitignored)
│   ├── run.sh              # Worker/reviewer loop orchestrator
│   ├── strategy-loop/      # Strategy development loop prompts
│   └── run-strategy-loop.sh # Strategy loop launcher
└── results/                # Backtest output (tearsheet, fills, positions)
```

## Key Commands

```bash
# Run backtest
uv run python scripts/run_backtest.py experiments/configs/tick_always.yml

# Run tests (81 tests, ~6 min — downloads PMXT data on first run)
uv run pytest tests/ -x -q

# Start dev loop
./agents/run.sh

# Start strategy development loop
./agents/run-strategy-loop.sh
```

## Import Paths

Framework code is in `src/` (on pythonpath). Experiments are at project root (also on pythonpath).

```python
# Framework
from strategy.base import PolymarketStrategy, PolymarketStrategyConfig
from runner.engine import run_backtest, ExperimentConfig
from universe.gamma import discover_markets

# Experiments
from experiments.strategies.momentum_drift import MomentumDrift
```

## Config YAML Format

```yaml
mode: "backtest"            # or "paper"
strategy:
  path: "experiments.strategies.my_strategy:MyStrategy"
  params: { ... }
condition_ids: [...]         # Explicit markets (CLOB API lookup)
# OR
universe:                    # Dynamic discovery (Gamma API)
  slug_contains: "trump"
  volume_min: 10000
data:
  hours: ["2026-03-09T09"]
mlflow:
  experiment: "my-experiment"
  parent_run: "v1"
```

## Strategy Patterns

Two patterns — timer-based strategies perform better than tick-reactive:

1. **Timer-based** (`on_interval`): Set `check_interval_minutes > 0`. Hold positions across intervals.
2. **Tick-reactive** (`on_order_book_deltas`): React to every book update. Must call `super()`.

## Key Constraints

- `trade_size` minimum is 5.0 for real CLOB (tests use 1.0)
- All orders use `TimeInForce.FOK` (fill-or-kill)
- Exit uses limit orders at best bid/ask (not `close_position`)
- `start_time_ns` and `end_time_ns` are auto-injected by the runner
