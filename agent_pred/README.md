# agent_pred — Polymarket Trading Framework

A backtesting and paper trading framework for Polymarket prediction markets, built on [NautilusTrader](https://nautilustrader.io).

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  experiments/                                           │
│  ├── strategies/   Concrete trading strategies          │
│  └── configs/      Experiment config YAMLs              │
├─────────────────────────────────────────────────────────┤
│  src/ (framework)                                       │
│  ├── strategy/     Base strategy class (exit lifecycle)  │
│  ├── runner/       Backtest engine, tearsheet, MLflow    │
│  ├── pmxt/         Historical data pipeline             │
│  ├── universe/     Market discovery (Gamma/CLOB APIs)   │
│  └── discovery/    Live market discovery actor           │
├─────────────────────────────────────────────────────────┤
│  Infrastructure                                         │
│  ├── scripts/      CLI entry points                     │
│  ├── agents/       Dev loop (worker/reviewer)           │
│  └── results/      Backtest output                      │
└─────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# Install
cd agent_pred && uv sync

# Run a backtest
uv run python scripts/run_backtest.py experiments/configs/timer_momentum.yml

# Run tests
uv run pytest tests/ -x -q
```

## Writing a Strategy

1. Create `experiments/strategies/my_strategy.py`:

```python
from strategy.base import PolymarketStrategy, PolymarketStrategyConfig

class MyStrategyConfig(PolymarketStrategyConfig, frozen=True):
    trade_size: float = 5.0

class MyStrategy(PolymarketStrategy):
    def __init__(self, config: MyStrategyConfig) -> None:
        super().__init__(config)
        self._trade_size = config.trade_size

    def on_interval(self, event):
        for iid in self._instrument_ids:
            if iid in self._closed:
                continue
            book = self.cache.order_book(iid)
            # Your trading logic here
```

2. Create `experiments/configs/my_strategy.yml`:

```yaml
mode: "backtest"
strategy:
  path: "experiments.strategies.my_strategy:MyStrategy"
  params:
    trade_size: 5.0
    check_interval_minutes: 1
condition_ids:
  - "0x884c293e9eeeda6065f05e75fca16fd4d67b5fb911ee854b1bed58c785d3b33d"
data:
  hours: ["2026-03-09T09"]
```

3. Run: `uv run python scripts/run_backtest.py experiments/configs/my_strategy.yml`

## Data Sources

- **PMXT** (`r2.pmxt.dev`): Historical tick-level orderbook data in hourly parquet files
- **Gamma API**: Market discovery with server-side filtering
- **CLOB API**: Direct market metadata lookup by condition_id

## Results & Tracking

Backtest results are saved to `results/<run_id>/`:
- `tearsheet.json` — PnL, win_rate, sharpe_ratio, max_drawdown, etc.
- `status.json` — run lifecycle (running → completed/failed)
- `fills.csv`, `positions.csv`, `orders.csv`

MLflow tracking with experiment/variant/child-run hierarchy. Set `mlflow:` section in config YAML.

## Agent Loops

```bash
# Development loop (code review)
./agents/run.sh

# Strategy development loop (write → backtest → iterate)
./agents/run-strategy-loop.sh
```
