# Session Objective: Polymarket Agentic Trading Framework — System Plan v2

You are writing a **system plan** in `agents/PLAN.md`. A previous iteration exists at `agents/archive/PLAN_run1.md` — read it. It is a solid foundation with 27 code-verified claims. Your job is to take that plan and make it dramatically clearer, deeper, and more actionable in the areas described below.

---

## YOUR AUDIENCE DOES NOT KNOW NAUTILUS TRADER

This is the most important instruction. The reader of this plan has never used NautilusTrader. Every time you reference a NautilusTrader feature, you MUST explain:

1. **What it is** — what does this feature do, in plain English?
2. **How it works** — what's the mechanism? Not just "use StreamingConfig" but "StreamingConfig is a flag you set in the engine config that tells NautilusTrader to write every data event it processes to disk as feather files, organized by instrument and data type."
3. **What it looks like** — show the actual Python code or config to use it. Not pseudocode — real API calls.

**Examples of BAD writing (from run 1):**
- "Paper trading uses Sandbox mode with SimulatedExchange" — What is Sandbox mode? How do you activate it? What does SimulatedExchange simulate? How accurate is it?
- "StreamingConfig → StreamingFeatherWriter records all data types" — What is StreamingConfig? Where do you set it? What are feather files? Where do they go? How big are they?
- "Use `subscribe_book_deltas()`" — How? In what method? What does the callback receive? What does the data look like?

**Examples of GOOD writing:**
- "Paper trading in NautilusTrader works by connecting to real live data feeds (you get real Polymarket orderbook data streaming in real-time) but routing orders to a SimulatedExchange instead of Polymarket's actual CLOB. The SimulatedExchange maintains its own internal orderbook and matches your orders against it. You activate this by setting `environment=Environment.SANDBOX` in your TradingNodeConfig — everything else (strategy code, data subscriptions) stays identical to live trading. Here's what the config looks like: [code]"

Every NautilusTrader concept gets this treatment. No exceptions. If you catch yourself writing "use X" without explaining what X is and how it works, stop and fix it.

---

## WHAT EXISTS vs WHAT WE BUILD — MAKE IT UNMISTAKABLE

For every capability in the plan, use this exact format:

```
### [Capability Name]

**EXISTS TODAY (v0):** [What NautilusTrader provides right now, with zero changes]
- How it works (explained for a newcomer)
- What code/config activates it
- What its limitations are

**WE MUST BUILD (v1):** [What we need to add — Python code, configs, scripts]
- Exactly what files/classes/functions we write
- What NautilusTrader features they plug into
- Effort estimate (small/medium/large)

**BLOCKED UNTIL (v2+):** [What can't work yet and why]
- What's missing
- What would unblock it
```

This format must be used for: backtesting, paper trading, live trading, universe definition, market resolution, strategy parameterization, data pipelines, and the agentic loop.

Do NOT mix "exists" and "we build" in the same paragraph. The reader must be able to scan the plan and instantly know "this works today" vs "this requires work."

---

## 1. The End-Goal System

(Same as before — keep the ASCII diagram and description from the previous session prompt. The agentic loop concept is clear.)

```
┌─────────────────────────────────────────────────────────────────┐
│                    AGENTIC RESEARCH LOOP                        │
│                                                                 │
│  ┌──────────────┐     ┌──────────────┐     ┌────────────────┐  │
│  │  RESEARCHER   │────▶│   WRITER     │────▶│  EXPERIMENT    │  │
│  │  AGENT        │     │   AGENT      │     │  CONFIG        │  │
│  │              │     │              │     │  (strategy.py   │  │
│  │ reads results │     │ writes strat │     │   + params.yml) │  │
│  │ proposes ideas│     │ code + config│     │                │  │
│  └──────────────┘     └──────────────┘     └───────┬────────┘  │
│         ▲                                           │           │
│         │                                           ▼           │
│  ┌──────┴───────┐                          ┌───────────────┐   │
│  │  ANALYZER     │◀─────results────────────│  RUNNER       │   │
│  │  AGENT        │     (deterministic)      │  (bash script) │  │
│  │               │                          │               │   │
│  │ reads PnL,    │                          │ runs backtest │   │
│  │ fills, logs   │                          │ or paper trade│   │
│  │ writes report │                          │ via Nautilus  │   │
│  │ logs to MLflow│                          │ NO LLM here  │   │
│  └──────────────┘                          └───────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

LLM agents write strategy code and experiment configs. A deterministic bash script runs them through NautilusTrader. Results go to disk. Agents read results. The LLM is never inside the execution loop.

---

## 2. PMXT Data — The Backtesting Lifeline

PMXT provides **hourly Parquet dumps of all Polymarket orderbook and trade data**. This is our primary path to backtesting.

### What PMXT provides
- Files named: `polymarket_orderbook_YYYY-MM-DDTHH.parquet`
- One file per hour, covering ALL active Polymarket markets
- File sizes: 300–700 MB per hour (~12 GB per day)
- Format: Parquet (standard columnar format)
- Data: orderbook snapshots and trades, keyed by condition_id/token_id
- Updated hourly, freely available

### The core data challenge

NautilusTrader's BacktestEngine expects data in its own internal types (`OrderBookDelta`, `TradeTick`, `QuoteTick`, `Bar`). PMXT provides raw Polymarket orderbook/trade data in its own schema. **The central engineering problem is: how do we transform PMXT Parquet data into NautilusTrader-compatible types and feed them to the backtest engine?**

Your plan MUST:
1. **Inspect the PMXT data schema** — read `agents/archive/PLAN_run1.md` for what's known, and use the `polymarket` CLI to verify market/orderbook structures
2. **Map PMXT fields to NautilusTrader types** — which PMXT fields become which NT fields? Show the mapping explicitly.
3. **Describe the exact pipeline** — download PMXT parquet → filter by condition_id → transform to NT types → load into BacktestEngine. Show real code for each step.
4. **Address the size problem** — 12 GB/day. How do we filter to just the markets we care about? Can we pre-filter the parquet files? What's the memory model?
5. **Show what alternative paths exist** — can we also record live data via NautilusTrader's StreamingConfig and replay it? How does that compare? Which is easier? Which is better?

This section is the MOST IMPORTANT part of the plan. Without backtesting, nothing else matters.

---

## 3. Required Capabilities — With Exists/Build/Blocked Format

For each of these, use the EXISTS/BUILD/BLOCKED format described above:

### 3.1 Backtesting
- How does NautilusTrader's BacktestEngine work? (Explain for newcomer)
- What data does it accept? What formats?
- How do you load data into it? Show real code.
- Can we backtest with PMXT data today? If not, what exactly do we need to build?
- Can we backtest by recording live data and replaying it? How?
- What does a complete backtest script look like? Show the real Python.

### 3.2 Paper Trading
- How does NautilusTrader's paper trading work? (Explain for newcomer)
- What is Sandbox mode? How do you activate it?
- What is SimulatedExchange? What does it simulate? How accurate is it for a CLOB?
- Does paper trading work with orderbook data? Or only with quotes/trades?
- What does a complete paper trading script look like? Show the real Python.

### 3.3 Live Trading
- How does NautilusTrader's LiveNode work? (Explain for newcomer)
- How does the Polymarket adapter connect? What data flows in? What flows out?
- What does a complete live trading script look like? Show the real Python.
- What's different between the paper trading config and live trading config?

### 3.4 Universe Definition
- How does NautilusTrader discover instruments? (Explain InstrumentProvider for newcomer)
- How does the Polymarket instrument provider work? What can it filter on?
- How do we define "all 15-min crypto markets" or "all active markets tagged X"?
- How does the universe work differently in backtest (static set of historical markets) vs live (dynamic, markets appearing and resolving)?
- What exactly do we need to build for universe management?

### 3.5 Market Resolution / Lifecycle
- What happens when a Polymarket market resolves? What data does the adapter receive?
- Does NautilusTrader have any concept of instrument expiry? How does BinaryOption handle it?
- How do strategies know a market is about to resolve? Can they detect price convergence to 0.99/0.01?
- How does the strategy exit positions before resolution? (Note: `close_position()` uses MarketOrder which Polymarket rejects — this is a known problem from run 1)
- What do we need to build for lifecycle handling?

### 3.6 Strategy Parameterization
- How does NautilusTrader's StrategyConfig work? (Explain for newcomer)
- How do you define custom parameters on a strategy?
- What does a parameterized strategy look like in code?
- How would we sweep hyperparameters — what drives the outer loop?

---

## 4. Deep Dives — The Plan Must Answer These Precisely

### 4.1 "I want to backtest a strategy against historical Polymarket data"
Walk through the EXACT steps. From "I have PMXT parquet files on disk" to "I see backtest results." Every file, every function, every config. What exists, what I write, what I run.

### 4.2 "I want to paper trade a strategy on live Polymarket data"
Walk through the EXACT steps. From "I have a strategy class" to "it's paper trading on live data." Every file, every function, every config.

### 4.3 "I want to define a universe of 15-min crypto markets and trade them"
Walk through the EXACT steps. How do I find these markets? How do I tell NautilusTrader about them? How do I handle the fact that they expire and new ones appear?

### 4.4 "I want to record live Polymarket data for later backtesting"
Walk through the EXACT steps. How does StreamingConfig work? What files does it produce? How do I replay them?

---

## 5. Agentic Research Loop Design

Same requirements as before — agent roles, state contract, orchestration, runner script. But now the runner needs to be concrete: how does it actually invoke NautilusTrader? Show the Python script that takes a strategy file + config and runs a backtest. Show how results are written to disk. Show what the analyzer agent reads.

---

## 6. Tools Available To You

### Polymarket CLI
You have the `polymarket` CLI at `/usr/local/bin/polymarket`. Read `agents/POLYMARKET_CLI_GUIDE.md` for the full reference. **USE IT** to verify any claims about Polymarket data structures, market taxonomy, orderbook format, fees, etc.

**NEVER GUESS about Polymarket when you can verify with the CLI.**

### Previous Plan
Read `agents/archive/PLAN_run1.md` — it has 27 code-verified claims about NautilusTrader. Use it as your research baseline. Don't redo work that's already verified — build on it.

### NautilusTrader Codebase
Read the actual source code. Every claim about NautilusTrader must cite a file path. Key entry points:
- Strategies: `nautilus_trader/examples/strategies/`, `crates/trading/src/strategy/`
- Backtesting: `crates/backtest/src/`, `nautilus_trader/backtest/`
- Live/Paper: `crates/live/src/`, `nautilus_trader/live/`, `nautilus_trader/adapters/sandbox/`
- Polymarket adapter: `crates/adapters/polymarket/src/`
- Data persistence: `nautilus_trader/persistence/`
- Examples: `examples/backtest/`, `examples/live/polymarket/`, `examples/sandbox/`

---

## 7. Output Format

Write to `agents/PLAN.md`. Use the planner specialization structure. Use Mermaid diagrams heavily. Every NautilusTrader feature gets explained for a newcomer. Every capability gets the EXISTS/BUILD/BLOCKED treatment. The plan tells a story top-to-bottom. Cite file paths for all NautilusTrader claims.

The plan should be structured so a reader can answer these questions after reading it:
1. What can I do RIGHT NOW with zero code changes?
2. What do I need to build to get backtesting working with PMXT data?
3. What do I need to build to get paper trading working?
4. How do I define and manage a universe of Polymarket markets?
5. How do strategies handle market resolution and expiry?
6. What does the full agentic research loop look like?
