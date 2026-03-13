# Chapter 4: Running Experiments

How to configure and run backtests, from config YAML to tearsheet output.

## Config Format

Experiments are defined in YAML (`configs/example_backtest.yml`):

```yaml
mode: "backtest"

strategy:
  path: "strategy.imbalance:ImbalanceStrategy"
  params:
    imbalance_threshold: 0.3
    trade_size: 10.0
    take_profit: 0.05
    stop_loss: -0.03

condition_ids: []  # Empty = discover via universe: filters below

data:
  hours:
    - "2026-03-09T09"

fees: "zero"
starting_balance: 10000.0

mlflow:
  experiment: "imbalance-crypto-hourly"
  parent_run: "v1-simple-threshold"
  tags:
    iteration: "1"
```

## Running a Backtest

```bash
uv run python scripts/run_backtest.py configs/example_backtest.yml
```

Market resolution is automatic:
- If `condition_ids` are specified → fetches metadata via CLOB API
- If `universe:` section is specified → discovers markets via Gamma API with server-side filtering
- No caching — always fetches fresh market data

## Experiment Config (`src/runner/engine.py`)

```python
from runner.engine import ExperimentConfig, run_backtest

config = ExperimentConfig.from_yaml(Path("configs/example_backtest.yml"))
result = run_backtest(
    config=config,
    market_infos=market_infos,
    data_cache_dir=Path("data/pmxt/cache"),
    mlflow_tracking_uri="./mlruns",
)
```

### Strategy Instantiation Convention

The runner discovers the config class by convention:
- Strategy path: `strategy.imbalance:ImbalanceStrategy`
- Config class: `ImbalanceStrategyConfig` (same module, name + "Config")
- Resolved `instrument_ids` are injected automatically from universe resolution

## Output

### Tearsheet

```json
{
  "total_pnl": -1.45,
  "num_trades": 33,
  "win_rate": 0.42,
  "sharpe_ratio": -0.12,
  "max_drawdown": -2.30,
  "profit_factor": 0.85,
  "avg_trade_pnl": -0.044,
  "num_positions": 33
}
```

### Artifacts (saved to `results/{run_id}/`)

| File | Contents |
|------|----------|
| `tearsheet.json` | Performance metrics |
| `orders.csv` | All orders submitted |
| `fills.csv` | All fills received |
| `positions.csv` | All positions opened/closed |
| `metadata.json` | Run config and timing |

## Testing

```bash
# Fast tests (no network)
uv run pytest tests/ --ignore=tests/test_pmxt_reader.py --ignore=tests/test_integration.py --ignore=tests/test_trading_backtest.py -v

# Full suite including network tests (~2.5 min)
uv run pytest tests/ -v
```
