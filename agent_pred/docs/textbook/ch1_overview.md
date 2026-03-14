# Chapter 1: What This Framework Does

## The Problem

Polymarket is a prediction market exchange. You can buy and sell binary outcome tokens — "Will X happen?" — that pay $1 if the outcome resolves Yes, $0 if No. The price of a token is its implied probability.

These markets have order books. Where there's an order book, there's alpha to be found: momentum, mean reversion, spread capture, imbalance signals. But to test whether a trading idea works, you need:

1. Historical order book data
2. An execution engine that simulates order matching
3. A way to define strategies without coupling them to the execution mode
4. Tracking infrastructure to compare variants

This framework provides all four.

## Architecture

```
┌──────────────────────────────────────────────────────┐
│  experiments/                                         │
│  ├── strategies/   Your trading strategies            │
│  └── configs/      YAML configs (what to run, how)    │
├──────────────────────────────────────────────────────┤
│  src/ (framework)                                     │
│  ├── strategy/     Base class: exit lifecycle, timers  │
│  ├── runner/       Backtest engine, paper runner       │
│  ├── pmxt/         Historical data pipeline            │
│  ├── universe/     Market discovery (Gamma/CLOB APIs)  │
│  └── discovery/    Live market discovery actor          │
├──────────────────────────────────────────────────────┤
│  Infrastructure                                       │
│  ├── scripts/      CLI entry points                    │
│  ├── agents/       Dev loop (worker/reviewer)          │
│  └── results/      Backtest output                     │
└──────────────────────────────────────────────────────┘
```

The separation matters: `src/` is the framework (data pipeline, strategy base class, execution engine). `experiments/` is where you write strategies and configs. This is a one-way dependency — experiments depend on the framework, never the reverse.

## The Execution Modes

The same strategy class runs in both modes. The framework handles the differences.

| | Backtest | Paper |
|---|---|---|
| **Data source** | PMXT historical parquet files | Polymarket live WebSocket |
| **Execution** | BacktestEngine (simulated matching) | SandboxExecutionClient (simulated fills) |
| **Clock** | Replayed timestamps from data | Real wall clock |
| **Markets** | Fixed at config time | Dynamic (discovered at runtime) |
| **Entry point** | `run_backtest()` | `run_paper()` |

In backtest mode, time moves as fast as data can be replayed. A 24-hour trading session runs in seconds. In paper mode, time is real — you're watching actual markets with simulated fills.

## The Lifecycle of a Backtest

Here's what happens when you run a backtest, end to end:

```
1. Parse config YAML
   └── ExperimentConfig.from_yaml("experiments/configs/my_strategy.yml")

2. Discover markets
   ├── condition_ids in config → fetch each from CLOB API
   └── universe filters in config → discover via Gamma API

3. Build instruments
   └── build_instrument_maps(market_infos)
       → dict[token_id, BinaryOption]  (NautilusTrader instruments)
       → dict[token_id, InstrumentId]  (for order routing)
       → set[condition_id]             (for PMXT data filtering)

4. Stream historical data
   └── pmxt_data_generator(market_ids, hours, instruments, ...)
       → yields sorted list[OrderBookDelta] batches

5. Run engine
   └── BacktestEngine.run(start, end)
       → processes each delta → updates book → fires strategy callbacks

6. Compute results
   └── compute_tearsheet(positions_df, fills_df)
       → PnL, win_rate, sharpe, drawdown, profit_factor, ...

7. Save & log
   ├── results/{run_id}/  (tearsheet.json, orders.csv, fills.csv, ...)
   └── MLflow (optional)  (metrics, params, artifacts)
```

Each of these steps is covered in its own chapter.

## Built on NautilusTrader

This framework is built on top of [NautilusTrader](https://nautilustrader.io), a high-performance algorithmic trading platform. NautilusTrader provides:

- **BacktestEngine**: replays data through a simulated exchange
- **Strategy**: base class with lifecycle hooks (`on_start`, `on_order_book_deltas`, etc.)
- **BinaryOption**: instrument type for prediction market tokens
- **Cache**: in-memory store for orderbooks, instruments, positions, orders
- **TradingNode**: live/paper trading runtime with data and execution clients

We don't modify NautilusTrader source. We extend its classes (`Strategy`, `Actor`) and use its engine as-is. If you're familiar with NautilusTrader, the patterns here will feel natural. If not, you don't need to learn the whole framework — this textbook covers everything you need.

## Next

- **Chapter 2**: How historical orderbook data flows from PMXT into the engine
- **Chapter 3**: How markets are discovered and become tradeable instruments
- **Chapter 4**: How to write strategies — the base class, timer vs tick patterns, exit lifecycle
- **Chapter 5**: How to configure and run backtests
- **Chapter 6**: How MLflow tracks experiment results
- **Chapter 7**: How paper trading works with live data and dynamic market discovery
