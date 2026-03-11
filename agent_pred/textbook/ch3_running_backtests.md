# Chapter 3: Running Backtests

How to run a backtest end-to-end: from universe definition to results in MLflow.

## Quick Start

```bash
# Auto-discover markets from PMXT data and run a backtest:
cd agent_pred
uv run python scripts/run_backtest.py configs/example_backtest.yml --discover
```

This will:
1. Stream PMXT data for the configured hours
2. Discover markets and extract token_ids
3. Save market metadata to `data/markets/`
4. Build instruments and feed data through BacktestEngine
5. Run the configured strategy
6. Print tearsheet summary
7. Save results to `results/{run_id}/`
8. Optionally log to MLflow

## Config Format

```yaml
mode: "backtest"

strategy:
  path: "strategy.imbalance:ImbalanceStrategy"
  params:
    instrument_ids: []
    imbalance_threshold: 0.3
    trade_size: 10.0

condition_ids: []  # Empty = use all discovered markets

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

## Strategy Path

Strategies are imported by dotted path: `"module.submodule:ClassName"`.

Built-in strategies:
| Path | Description |
|------|-------------|
| `strategy.imbalance:ImbalanceStrategy` | Trades order book bid/ask volume imbalance |
| `strategy.log_only:LogOnlyStrategy` | Logs data only, no trading (testing) |
| `strategy.simple_test:SimpleTestStrategy` | Places one order immediately (testing) |

Custom strategies must be importable from `src/`.

## Engine Pipeline

```python
from runner.engine import ExperimentConfig, run_backtest

config = ExperimentConfig.from_yaml(Path("configs/example.yml"))
result = run_backtest(
    config=config,
    market_infos=market_infos,        # list[dict] — market metadata
    data_cache_dir=Path("data/cache"), # optional PMXT cache
    results_dir=Path("results/my_run"),
    mlflow_tracking_uri=None,          # None = local ./mlruns/
)

# result.tearsheet — Tearsheet dataclass with 8 metrics
# result.orders_df — pandas DataFrame of all orders
# result.fills_df — pandas DataFrame of all fills
# result.positions_df — pandas DataFrame of all positions
```

## Tearsheet Metrics

| Metric | Description |
|--------|-------------|
| `total_pnl` | Sum of realized PnL across all positions |
| `num_trades` | Number of fills |
| `num_positions` | Number of position entries |
| `win_rate` | Fraction of positions with positive PnL |
| `sharpe_ratio` | Annualized Sharpe (PnL mean / std * sqrt(252)) |
| `max_drawdown` | Largest peak-to-trough PnL decline |
| `avg_trade_pnl` | Mean PnL per position |
| `profit_factor` | Total wins / total losses |

## MLflow Logging

When `mlflow.experiment` is set in config, results are logged to MLflow.

**Hierarchy:**
- **Experiment** = strategy idea (e.g., "orderbook-imbalance")
- **Parent Run** = variant name (e.g., "v1-simple-threshold")
- **Child Run** = individual execution

Every child run is auto-tagged with:
- `git_sha` — current git commit (12 chars)
- `strategy_file` — strategy import path
- `mode` — "backtest" or "paper"
- `universe_id` — universe identifier
- `date_range` — first..last data hour

```bash
# View results in MLflow UI:
uv run mlflow ui --port 5000
# Open http://localhost:5000
```

## Saved Artifacts

Each run saves to `results/{run_id}/`:
```
results/a1b2c3d4/
├── tearsheet.json    # 8 metrics
├── metadata.json     # config + timing
├── orders.csv        # all orders
├── fills.csv         # all fills
└── positions.csv     # all positions
```

## Writing Custom Strategies

Extend `PolymarketStrategy` for automatic exit lifecycle handling:

```python
from strategy.base import PolymarketStrategy, PolymarketStrategyConfig

class MyStrategyConfig(PolymarketStrategyConfig, frozen=True):
    my_param: float = 0.5

class MyStrategy(PolymarketStrategy):
    def __init__(self, config: MyStrategyConfig) -> None:
        super().__init__(config)
        self._my_param = config.my_param

    def on_order_book_deltas(self, deltas):
        super().on_order_book_deltas(deltas)  # Exit checks
        # Your entry logic here
```

`PolymarketStrategy` provides:
- Order book subscription on start
- Resolution timer (exit before market resolves)
- Price convergence detection (exit when price → 0 or 1)
- Take-profit / stop-loss
- Limit FOK exit with retry and price worsening
- HeldThrough tracking for failed exits

## Testing

```bash
# Full integration test (real PMXT data, ~2 min):
uv run pytest tests/test_integration.py -v --timeout=300

# Trading pipeline test (proves orders/fills work):
uv run pytest tests/test_trading_backtest.py -v --timeout=300

# Fast tests (no network):
uv run pytest tests/test_transformer.py tests/test_tearsheet.py tests/test_universe.py -v
```
