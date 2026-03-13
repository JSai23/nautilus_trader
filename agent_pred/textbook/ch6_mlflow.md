# Chapter 6: MLflow Experiment Tracking

How experiment results are organized, logged, and queried in MLflow.

## The Hierarchy

MLflow organizes runs in a three-level tree:

```
Experiment (strategy concept)
  └── Parent Run (variant name)
        └── Child Run (individual execution)
```

| Level | Example | What it represents |
|-------|---------|-------------------|
| Experiment | `orderbook-imbalance` | A strategy idea you're exploring |
| Parent Run | `v1-simple-threshold` | A specific approach or parameter set |
| Child Run | `TimerMomentumStrategy_4m_2026-03-09T09..2026-03-09T12` | One backtest execution |

This hierarchy lets you compare variants within a strategy (which threshold works best?) and compare strategies across experiments (does imbalance beat momentum?).

## Configuration

Add an `mlflow:` section to your config YAML:

```yaml
mlflow:
  experiment: "momentum-crypto"       # Creates/reuses this experiment
  parent_run: "v1-5min-intervals"     # Creates/reuses this parent run
  tags:                                # Custom tags for this run
    iteration: "3"
    note: "increased trade_size"
```

If the `mlflow:` section is omitted, no MLflow logging occurs. Results are still saved locally to `results/`.

## What Gets Logged

### Metrics (queryable, plottable)

All tearsheet values: `total_pnl`, `num_trades`, `win_rate`, `sharpe_ratio`, `max_drawdown`, `profit_factor`, `avg_trade_pnl`, `num_positions`.

### Params

All strategy config values (stringified): `trade_size`, `check_interval_minutes`, `instrument_ids`, etc.

### Tags

Every child run is automatically tagged with:

| Tag | Source |
|-----|--------|
| `git_sha` | Current git commit (12 chars) |
| `mlflow.parentRunId` | Parent run ID (hierarchy link) |
| `mode` | `backtest` or `paper` |
| `strategy_file` | Strategy import path |
| `universe_id` | From config (if set) |
| `date_range` | `first_hour..last_hour` |

Custom tags from config YAML are preserved alongside auto-tags.

### Artifacts

The entire results directory is uploaded: `tearsheet.json`, `orders.csv`, `fills.csv`, `positions.csv`, `metadata.json`.

### Run Name

Child runs get a descriptive name: `{StrategyName}_{N}m_{date_range}`. Example: `TimerMomentumStrategy_4m_2026-03-09T09..2026-03-09T12`. This makes the MLflow UI scannable without clicking into each run.

## The Logger (`src/runner/mlflow_logger.py`)

```python
from runner.mlflow_logger import MLflowLogger

logger = MLflowLogger(tracking_uri="./mlruns")

logger.log_child_run(
    experiment_name="momentum-crypto",
    variant_name="v1-5min",
    metrics=tearsheet.to_dict(),
    params=strategy_params,
    tags={"iteration": "1"},
    artifacts_dir=Path("results/a1b2c3d4/"),
)
```

### Parent Run Reuse

The logger searches for an existing parent run by name before creating one. Multiple child runs under the same variant share a single parent:

```python
# First call: creates experiment + parent "v1" + child
logger.log_child_run("exp", "v1", metrics1, params1)

# Second call: reuses parent "v1", creates new child
logger.log_child_run("exp", "v1", metrics2, params2)
```

This means you can iterate on a variant — change params, re-run — and all results group under the same parent run in the UI.

## Querying Results

```bash
# Start the MLflow UI
uv run mlflow ui --port 5000
# Open http://localhost:5000
```

Or query programmatically:

```python
import mlflow

mlflow.set_tracking_uri("./mlruns")
runs = mlflow.search_runs(experiment_names=["momentum-crypto"])
print(runs[["tags.git_sha", "metrics.total_pnl", "metrics.sharpe_ratio"]])
```

## Failure Handling

If MLflow logging fails (network error, permission issue), the error is logged but the backtest result is NOT lost — it's already saved to `results/{run_id}/`. MLflow is optional tracking, not the source of truth.

```python
# In engine.py
try:
    _log_to_mlflow(result, results_dir, tracking_uri)
except Exception:
    log.exception("MLflow logging failed — results saved locally")
```
