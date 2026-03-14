# experiments — Concrete Strategies & Configs

Consumer code that uses the framework. Not part of the framework itself.

## Creating a New Experiment

1. Write strategy in `experiments/strategies/my_strategy.py`
2. Write config in `experiments/configs/my_strategy.yml`
3. Run: `uv run python scripts/run_backtest.py experiments/configs/my_strategy.yml`

## Strategy File Template

```python
"""One-line description."""
from __future__ import annotations
from strategy.base import PolymarketStrategy, PolymarketStrategyConfig

class MyStrategyConfig(PolymarketStrategyConfig, frozen=True):
    trade_size: float = 5.0
    # your params...

class MyStrategy(PolymarketStrategy):
    def __init__(self, config: MyStrategyConfig) -> None:
        super().__init__(config)
        self._trade_size = config.trade_size

    def on_interval(self, event):
        for iid in self._instrument_ids:
            if iid in self._closed or iid in self._exiting:
                continue
            # your logic...
```

## Config YAML Template

```yaml
mode: "backtest"
strategy:
  path: "experiments.strategies.my_strategy:MyStrategy"
  params:
    trade_size: 5.0
    check_interval_minutes: 1
    convergence_threshold: 0.99
condition_ids:
  - "0x..."
data:
  hours: ["2026-03-09T09"]
fees: "zero"
starting_balance: 10000.0
mlflow:
  experiment: "my-experiment"
  parent_run: "v1"
```

## Existing Strategies

| Strategy | Pattern | Description |
|----------|---------|-------------|
| momentum_drift | timer | Momentum-based entry with drift detection. The main strategy. |
| tick_always | tick | Buys/sells on book updates. No signals. The baseline tick strategy. |
| timer_always | timer | Buys/sells on intervals. No signals. The baseline timer strategy. |
| log_only | tick | Logs data (test-only) |
| simple_test | tick | Places one order (test-only) |
