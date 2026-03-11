# Chapter 5: MLflow Experiment Tracking

How experiment results are logged, organized, and queried in MLflow.

## Hierarchy

Per IMPL_PLAN Section 5.3, MLflow uses a three-level hierarchy:

```
Experiment (strategy idea)
  └── Parent Run (variant / semver name)
        └── Child Run (individual execution)
```

| Level | Example | Maps to |
|-------|---------|---------|
| Experiment | `orderbook-imbalance` | Strategy concept |
| Parent Run | `v1-simple-threshold` | Conceptual variant |
| Child Run | Auto-generated | Single backtest execution |

## Child Run Tags

Every child run is automatically tagged with:

| Tag | Source | Required |
|-----|--------|----------|
| `git_sha` | `git rev-parse HEAD` (12 chars) | **Yes** (non-negotiable) |
| `mlflow.parentRunId` | Parent run ID | Yes (hierarchy link) |
| `mode` | `backtest` or `paper` | Yes |
| `universe_id` | From config | Yes |
| `strategy_file` | Strategy import path | Yes |
| `date_range` | First..last data hour | If data hours exist |

Custom tags from config YAML are preserved alongside auto-tags.

## MLflow Logger (`src/runner/mlflow_logger.py`)

```python
from runner.mlflow_logger import MLflowLogger

logger = MLflowLogger(tracking_uri="./mlruns")

child_run_id = logger.log_child_run(
    experiment_name="imbalance-crypto-hourly",
    variant_name="v1-simple-threshold",
    metrics={"total_pnl": -1.45, "sharpe_ratio": -0.12, ...},
    params={"imbalance_threshold": "0.3", "trade_size": "10.0"},
    tags={"iteration": "1"},
    artifacts_dir=Path("results/abc123/"),
)
```

### Parent Run Reuse

The logger searches for an existing parent run by name before creating a new one. Multiple child runs under the same variant share a single parent:

```python
# First call creates parent "v1" + child
logger.log_child_run("exp", "v1", metrics1, params1)
# Second call reuses parent "v1" + creates new child
logger.log_child_run("exp", "v1", metrics2, params2)
```

## What Gets Logged

### Metrics (queryable, plottable)

All tearsheet values: `total_pnl`, `num_trades`, `win_rate`, `sharpe_ratio`, `max_drawdown`, `profit_factor`, `avg_trade_pnl`, `num_positions`.

### Params

All strategy config values (stringified): `imbalance_threshold`, `trade_size`, `instrument_ids`, etc.

### Artifacts

Everything in the results directory: `tearsheet.json`, `orders.csv`, `fills.csv`, `positions.csv`, `metadata.json`.

## Querying Results

```bash
# Start MLflow UI
uv run mlflow ui --backend-store-uri ./mlruns

# Or query programmatically
uv run python -c "
import mlflow
mlflow.set_tracking_uri('./mlruns')
runs = mlflow.search_runs(experiment_names=['imbalance-crypto-hourly'])
print(runs[['tags.git_sha', 'metrics.total_pnl', 'metrics.sharpe_ratio']])
"
```

## Testing

```bash
uv run pytest tests/test_mlflow_logger.py -v
```

10 tests cover: experiment creation, git_sha tagging, parent-child hierarchy, metrics/params/artifacts logging, parent reuse, custom tag preservation. All use real MLflow with a temporary file store.
