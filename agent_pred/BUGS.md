# Bugs

1. **MLflow child runs have random names — not useful.** The actual backtest execution (child run) gets MLflow's auto-generated random name. Should include something meaningful: strategy name, date range, market count, or timestamp. Currently you see a list of random words under each variant — no way to tell runs apart without clicking into each one.

   Current hierarchy:
   ```
   Experiment: "timer-momentum-stress-test"
     Parent Run: "v3-volatile-markets"
       Child Run: "dazzling-fox-123"      ← useless
       Child Run: "melodic-swan-456"      ← useless
   ```

   Better:
   ```
       Child Run: "timer_momentum · 5h · 25 markets · 2026-02-24"
   ```

   Fix in `mlflow_logger.py:95` — pass `run_name=...` to `mlflow.start_run()`.

## Fixed

1. ~~**Test suite downloads same PMXT parquet 8x over HTTP.** Fixed — session-scoped fixtures + local parquet caching. 18 min → 4 min.~~
