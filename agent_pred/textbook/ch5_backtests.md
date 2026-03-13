# Chapter 5: Running Backtests

How to configure, run, and interpret backtest results.

## Quick Start

```bash
cd agent_pred
uv run python scripts/run_backtest.py experiments/configs/timer_momentum.yml
```

This parses the config, discovers markets, streams data, runs the strategy, prints a tearsheet, and saves results.

## Config YAML Format

```yaml
mode: "backtest"

strategy:
  path: "experiments.strategies.timer_momentum:TimerMomentumStrategy"
  params:
    trade_size: 5.0
    check_interval_minutes: 1
    momentum_periods: 5

# Option A: Explicit markets
condition_ids:
  - "0xabc123..."

# Option B: Discovery filters (if no condition_ids)
universe:
  slug_contains: "bitcoin"
  end_date_min: "2026-04-01"
  volume_min: 10000
  active: true
  max_markets: 20

data:
  hours:
    - "2026-03-09T09"
    - "2026-03-09T10"

fees: "zero"
starting_balance: 10000.0

mlflow:
  experiment: "momentum-crypto"
  parent_run: "v1"
  tags:
    iteration: "1"
```

### Strategy Path

Format: `"module.path:ClassName"`. Resolved via `importlib`. The runner also looks for `ClassNameConfig` in the same module (convention: strategy and config class live together).

Framework strategies are in `experiments.strategies.*`. Custom strategies can be anywhere importable.

### Market Resolution

The `scripts/run_backtest.py` entry point handles market resolution before calling `run_backtest()`:

- **`condition_ids` present** → fetches each from CLOB API (`fetch_market_clob()`)
- **`universe` section present** (no condition_ids) → discovers via Gamma API (`discover_markets()`)

### Data Hours

List of hourly PMXT data files to stream. Format: `"YYYY-MM-DDTHH"` (ISO 8601 hour).

The runner sorts these, derives `start_dt` and `end_dt`, and:
- Passes them to `engine.run(start=start_dt, end=end_dt)` to initialize clocks correctly
- Injects `start_time_ns` and `end_time_ns` into strategy params to bound timers and schedule end-of-data exits

### Params Injected Automatically

The runner injects three params into strategy config that you should NOT set in YAML:

| Param | Source | Purpose |
|-------|--------|---------|
| `instrument_ids` | Universe resolution | Which instruments to trade |
| `start_time_ns` | First data hour | Timer lower bound (prevents epoch bug) |
| `end_time_ns` | Last data hour + 1h | End-of-data exit trigger |

## What Happens Under the Hood

```python
# 1. Parse config
config = ExperimentConfig.from_yaml(Path("experiments/configs/my_strategy.yml"))

# 2. Build instruments from market metadata
instruments, instrument_ids, market_ids = build_instrument_maps(market_infos)

# 3. Create engine with venue
engine = BacktestEngine(config=BacktestEngineConfig(logging=False))
engine.add_venue(
    venue=Venue("POLYMARKET"),
    oms_type=OmsType.NETTING,          # Single position per instrument
    account_type=AccountType.CASH,
    starting_balances=[Money(10_000, USDC_POS)],
    book_type=BookType.L2_MBP,
)

# 4. Add instruments
for instrument in instruments.values():
    engine.add_instrument(instrument)

# 5. Attach data generator
gen = pmxt_data_generator(market_ids, hours, instruments, instrument_ids)
engine.add_data_iterator("pmxt", gen)

# 6. Import strategy, inject params, instantiate
strategy_cls = import_strategy_class("experiments.strategies.my:MyStrategy")
config_cls = MyStrategyConfig
strategy = strategy_cls(config_cls(**params))
engine.add_strategy(strategy)

# 7. Run
engine.run(start=start_dt, end=end_dt)
```

### Key Design Decisions

**NETTING OMS**: One position per instrument. Buying 10 then buying 5 gives you a position of 15, not two separate positions. This matches Polymarket's actual behavior.

**L2_MBP book type**: Level 2 Market-By-Price. Tracks price levels with aggregated size, not individual orders. Matches PMXT data granularity.

**Explicit start/end**: Passed to `engine.run()` because `add_data_iterator()` doesn't populate the engine's internal data timeline. Without explicit bounds, the engine clock starts at Unix epoch (1970), causing `set_timer()` to fire millions of times catching up.

## Tearsheet

After the engine runs, a tearsheet is computed from closed positions and fills:

```python
tearsheet = compute_tearsheet(closed_positions_df, fills_df)
```

| Metric | How It's Computed |
|--------|-------------------|
| `total_pnl` | Sum of fill-based PnL across all positions |
| `num_trades` | Number of fills |
| `num_positions` | Number of position entries |
| `win_rate` | Fraction of positions with positive PnL |
| `sharpe_ratio` | Annualized: mean(pnl) / std(pnl) * sqrt(252) |
| `max_drawdown` | Largest peak-to-trough cumulative PnL decline |
| `avg_trade_pnl` | Mean PnL per position |
| `profit_factor` | Sum(winning PnL) / abs(Sum(losing PnL)) |

**Why fills, not positions?** NautilusTrader's NETTING mode under-reports `position.realized_pnl` when multiple buys are netted into one position. Computing PnL from fill prices (BUY/SELL pairs) gives accurate results.

**Why closed positions only?** Open positions have no realized PnL. Including them dilutes win_rate and avg_trade_pnl with zeros.

## Saved Artifacts

Every run saves to `results/{run_id}/`:

```
results/a1b2c3d4/
├── status.json       # Run lifecycle: running → completed/failed
├── tearsheet.json    # Performance metrics
├── metadata.json     # Config + timing
├── orders.csv        # All orders submitted
├── fills.csv         # All fills received
└── positions.csv     # All positions opened/closed
```

`status.json` is written at three points:
1. **Start**: `{"status": "running", ...}` — marks the run as in-progress
2. **Success**: `{"status": "completed", "total_pnl": ..., "num_trades": ...}`
3. **Failure**: `{"status": "failed", "error": "..."}`

This enables external monitoring — you can poll `status.json` to check if a run is still going.

## Interpreting Results

A backtest tells you whether a strategy idea has signal. Here's how to read it:

**`num_trades = 0`**: Strategy never entered. Either the entry condition is too restrictive, or the market data doesn't contain the signal being tested. Check the `orders.csv` — if orders were submitted but none filled, the book may have moved before FOK execution.

**`win_rate` close to 0.5 with negative `total_pnl`**: The strategy is trading randomly but paying the spread on entry/exit. The spread cost is the baseline you need to overcome.

**`profit_factor < 1.0`**: Losing more than winning. Below 0.8 with any reasonable sample size (>30 trades) suggests the idea doesn't work on this data.

**`sharpe_ratio`**: Below -0.5 is a strong rejection signal. Above 0.5 is worth investigating further. Between -0.5 and 0.5 is noise.

**High `max_drawdown` relative to `total_pnl`**: The strategy may be profitable but with unacceptable risk. A strategy that makes $5 but draws down $20 along the way isn't viable.

## Testing

```bash
# Full integration test (real PMXT data, ~2 min):
uv run pytest tests/test_integration.py -v --timeout=300

# Trading pipeline (orders/fills work, ~4 min):
uv run pytest tests/test_trading_backtest.py -v --timeout=300

# Fast tearsheet tests (no network):
uv run pytest tests/test_tearsheet.py -v
```
