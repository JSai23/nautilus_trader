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
uv run python scripts/run_backtest.py experiments/configs/momentum_drift.yml

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

## Project Structure

```
agent_pred/
├── src/                        # Framework code (importable packages)
│   ├── strategy/               #   Base strategy class, exit lifecycle, market metadata
│   │   └── base.py             #     PolymarketStrategy — all strategies extend this
│   ├── runner/                 #   Execution layer
│   │   ├── engine.py           #     Backtest engine: config → engine → strategy → results
│   │   ├── paper.py            #     Paper trading: TradingNode + live WebSocket data
│   │   ├── tearsheet.py        #     PnL metrics from fill pairs (win_rate, sharpe, etc.)
│   │   ├── artifacts.py        #     PnL curve, position timeline, trade distribution PNGs
│   │   ├── mlflow_logger.py    #     MLflow experiment/variant/child-run hierarchy
│   │   └── utils.py            #     Dynamic strategy class import
│   ├── pmxt/                   #   Historical data pipeline (parquet → NautilusTrader)
│   │   ├── reader.py           #     Stream PMXT parquets from r2.pmxt.dev
│   │   ├── transformer.py      #     Raw ticks → NautilusTrader OrderBookDeltas
│   │   ├── generator.py        #     Combine reader + transformer for engine injection
│   │   └── index.py            #     PMXT market index lookup
│   ├── universe/               #   Market discovery
│   │   ├── gamma.py            #     Gamma API discovery + CLOB API condition_id lookup
│   │   └── instruments.py      #     Build NautilusTrader instruments from market metadata
│   └── discovery/              #   Live market discovery
│       └── actor.py            #     MarketDiscoveryActor — polls for new markets in paper/live
│
├── experiments/                # Strategy research (consumer code, not framework)
│   ├── strategies/             #   Concrete strategy implementations
│   │   ├── momentum_drift.py   #     MomentumDrift — timer-based trend following with TP/SL
│   │   ├── tick_always.py      #     Baseline: buy/sell on every book update
│   │   ├── timer_always.py     #     Baseline: buy/sell on every interval
│   │   ├── log_only.py         #     Test harness: logs data, no trades
│   │   └── simple_test.py      #     Test harness: places one order
│   └── configs/                #   Experiment config YAMLs
│       ├── momentum_drift.yml  #     Main strategy config (btc-updown-4h)
│       ├── momentum_drift_*.yml#     IS/OOS variants for validation
│       ├── tick_always.yml     #     Baseline tick config
│       ├── timer_always.yml    #     Baseline timer config
│       └── paper_tick.yml      #     Paper trading config
│
├── scripts/                    # CLI entry points
│   └── run_backtest.py         #   Dispatches backtest or paper mode from config YAML
│
├── tests/                      # pytest suite (81 tests, ~6 min)
│   ├── conftest.py             #   Session-scoped fixtures, local parquet caching
│   ├── test_trading_backtest.py#   Full backtest integration tests
│   ├── test_tearsheet.py       #   Tearsheet computation tests
│   └── ...                     #   Unit tests for each src/ module
│
├── docs/                       # Documentation
│   └── textbook/               #   7-chapter guide (overview → live trading)
│
├── agents/                     # Dev loop infrastructure
│   ├── run.sh                  #   Worker/reviewer loop orchestrator
│   ├── run-strategy-loop.sh    #   Strategy loop launcher (sets session dir + python.md spec)
│   ├── prompts/                #   Role primitives (worker.md, reviewer.md, session.md)
│   ├── session/                #   Generic dev loop session prompts
│   └── strategy-loop/session/  #   Strategy loop session prompts
│
├── CLAUDE.md                   # Framework instructions for Claude Code
├── README.md                   # This file
├── BEHAVIORS.md                # Behavior verification tracking (PASS/UNVERIFIED/FAIL)
├── BUGS.md                     # Known issues tracker
└── pyproject.toml              # Dependencies and build config
```
