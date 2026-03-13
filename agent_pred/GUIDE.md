# Agent Pred — Human Guide

## Directory Map

```
nautilus_trader/                  # NautilusTrader repo (upstream fork)
├── agent_pred/                   # YOUR CODE — version controlled
│   ├── src/                      # Python source (pmxt, runner, strategy, universe)
│   ├── tests/                    # Tests (no mocks, all real)
│   ├── scripts/                  # CLI entry points
│   ├── configs/                  # Backtest + universe YAML configs
│   ├── textbook/                 # Agent reference chapters
│   ├── data/                     # Local data cache (gitignored)
│   │   ├── pmxt/cache/           # Filtered PMXT parquet subsets
│   │   ├── pmxt/index.json       # What's cached
│   │   └── (markets discovered live via Gamma API)
│   ├── results/                  # Run outputs (gitignored)
│   │   └── {run_id}/            # tearsheet.json, orders.csv, fills.csv, etc.
│   ├── PLAN.md                   # System decomposition (context)
│   ├── IMPL_PLAN.md              # Implementation plan
│   └── pyproject.toml            # uv project config
│
├── agents/                       # AGENT LOOP CONTROL PLANE — gitignored
│   ├── READ_BEFORE_RESET.md      # Read this before resetting loop state
│   ├── POLYMARKET_CLI_GUIDE.md   # Permanent reference
│   ├── prompts/                  # Synced from ~/claude-tooling
│   ├── session/                  # You write these before kicking off a loop
│   │   ├── SESSION_WORKER.md
│   │   └── SESSION_REVIEWER.md
│   ├── run.sh                    # Loop orchestrator
│   └── archive/                  # Archived loop states
│
├── mlruns/                       # MLflow data (local, in agent_pred/)
└── .venv/                        # Legacy venv (use agent_pred's uv project instead)
```

## Quick Start

### 1. Install deps

```bash
cd agent_pred
uv sync
```

### 2. Run tests

```bash
cd agent_pred
uv run pytest tests/                    # all tests (fast ones ~2s)
uv run pytest tests/ -m "not network"   # skip network tests
```

### 3. Run a backtest

```bash
cd agent_pred

# Run a backtest (markets discovered via Gamma API or config condition_ids):
uv run python scripts/run_backtest.py configs/example_backtest.yml

# Output goes to results/{run_id}/
# - tearsheet.json    (PnL, Sharpe, drawdown, win rate)
# - orders.csv        (all orders)
# - fills.csv         (all fills)
# - positions.csv     (all positions)
# - metadata.json     (config, timing, git sha)
```

### 4. Download specific data

```bash
cd agent_pred

# Discover markets via Gamma API:
uv run python scripts/download_data.py --discover-markets --active --limit 50

# Cache specific markets:
uv run python scripts/download_data.py \
  --market-ids 0xbcf53c26... \
  --hours 2026-03-09T09 2026-03-09T10
```

---

## MLflow

### Starting the server

```bash
cd agent_pred
uv run mlflow ui --port 5000
```

Then open http://localhost:5000 in your browser.

If running on a remote server, either:
- SSH tunnel: `ssh -L 5000:localhost:5000 your-server`
- Or expose via Caddy (see infra repo)

### MLflow hierarchy

```
Experiment: "orderbook-imbalance"          ← strategy idea
  └── Run: "v1-simple-threshold"           ← conceptual variant
       ├── Child Run: backtest 2024-06..08 ← single execution
       └── Child Run: backtest 2024-09..11 ← single execution
  └── Run: "v2-ema-weighted"               ← different approach
       └── Child Run: paper 1hr            ← single execution
```

Every child run is auto-tagged with:
- `git_sha` — exact commit
- `strategy_file` — which .py ran
- `mode` — backtest / paper / live
- `date_range` — data window
- `universe_id` — which universe
- All hyperparameters as tags

### Browsing results

In the MLflow UI:
1. Select an experiment (left sidebar)
2. See all parent runs (variants)
3. Click a parent run → see child runs
4. Click a child run → metrics, params, artifacts (CSVs, tearsheet)

---

## Writing a Strategy

### Minimal strategy

```python
# agent_pred/src/strategy/my_strategy.py
from strategy.base import PolymarketStrategyConfig, PolymarketStrategy

class MyConfig(PolymarketStrategyConfig, frozen=True):
    threshold: float = 0.3
    trade_size: float = 10.0

class MyStrategy(PolymarketStrategy):
    def on_order_book_deltas(self, deltas):
        # your logic here
        pass
```

### Config YAML

```yaml
mode: "backtest"
strategy:
  path: "strategy.my_strategy:MyStrategy"
  params:
    threshold: 0.3
    trade_size: 10.0
condition_ids: []
data:
  hours:
    - "2026-03-09T09"
    - "2026-03-09T10"
starting_balance: 10000.0
mlflow:
  experiment: "my-experiment"
  parent_run: "v1-initial"
```

### Run it

```bash
cd agent_pred
uv run python scripts/run_backtest.py configs/my_config.yml
```

---

## Running the Agent Loop

The agent loop is a worker/reviewer cycle that iterates on code. You control it, agents execute it.

### Before starting a loop

1. **Read `agents/READ_BEFORE_RESET.md`** — archive old state if any exists
2. **Write session prompts:**
   - `agents/session/SESSION_WORKER.md` — what the worker should do
   - `agents/session/SESSION_REVIEWER.md` — what the reviewer checks
3. **Sync tooling** (if stale):
   ```bash
   cp ~/claude-tooling/agents-src/prompts/*.md agents/prompts/
   cp ~/claude-tooling/agents-src/run.sh agents/run.sh
   ```

### Starting a loop

```bash
# In a tmux session:
WORKER_RUNTIME=claude \
REVIEWER_RUNTIME=claude \
WORKER_SPEC=python.md \
MAX_ITERATIONS=20 \
CLAUDE_EFFORT=high \
./agents/run.sh
```

Key env vars:

| Var | Options | Default |
|-----|---------|---------|
| `WORKER_RUNTIME` | claude, codex | claude |
| `REVIEWER_RUNTIME` | claude, codex | codex |
| `WORKER_SPEC` | python.md, planner.md, etc. | none |
| `MAX_ITERATIONS` | any number | 10 |
| `CLAUDE_EFFORT` | low, medium, high | medium |
| `WORKER_MAX_TURNS` | number or empty (unlimited) | empty |
| `REVIEWER_MAX_TURNS` | number or empty (unlimited) | empty |

### Monitoring a loop

```bash
# Attach to the tmux session:
tmux attach -t <session-name>

# Or check the session log:
tail -f agents/.script_logs/*/session.log

# Check what iteration it's on:
tail -20 agents/.script_logs/*/session.log
```

### When a loop finishes

1. Check `agents/STOP.txt` for why it stopped
2. Check `agents/FEEDBACK.md` for the final review
3. **Move deliverables** out of `agents/` to `agent_pred/` (agents/ is gitignored)
4. Archive loop state: `agents/READ_BEFORE_RESET.md` has instructions

---

## Data Pipeline Summary

```
PMXT archive (https://archive.pmxt.dev/Polymarket)
  │  hourly parquet files, 300-700MB each, ALL markets
  │
  ▼  stream via HTTP (never download full raw file)
PyArrow predicate filter: market_id IN [your markets]
  │
  ▼  cache filtered subset (5-50MB per market per hour)
data/pmxt/cache/{market_id}/{hour}.parquet
  │
  ▼  transform to NautilusTrader types
OrderBookDelta / OrderBookDeltas
  │
  ▼  feed via generator
BacktestEngine.add_data_iterator()
```

**Server constraint:** ~40GB storage, limited RAM. Never load a full PMXT file into memory. The pipeline streams, filters, and caches only the rows you need.

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `scripts/run_backtest.py` | Main entry point — config → backtest → results → MLflow |
| `scripts/download_data.py` | Pre-cache PMXT data for specific markets |
| `src/pmxt/reader.py` | Stream + filter PMXT parquet via HTTP |
| `src/pmxt/transformer.py` | PMXT rows → NautilusTrader OrderBookDelta |
| `src/pmxt/generator.py` | Generator that yields data chunks for add_data_iterator() |
| `src/universe/gamma.py` | Gamma API client for market discovery |
| `src/runner/engine.py` | Wires everything together, runs BacktestEngine |
| `src/runner/tearsheet.py` | Computes PnL, Sharpe, drawdown from results |
| `src/runner/mlflow_logger.py` | Logs to MLflow with experiment/variant/child hierarchy |
| `src/strategy/base.py` | PolymarketStrategy base class |
| `configs/example_backtest.yml` | Example config |
| `textbook/ch1-ch5` | Detailed chapters for agent reference |
