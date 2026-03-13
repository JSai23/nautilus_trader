# Strategy Design — Things To Think Through

Questions, tradeoffs, and mental models that matter when writing strategies on this framework. Not documentation — more like "stuff you need to understand before the code makes sense."

## Timer vs Tick: What Are You Actually Seeing?

Two patterns exist in our strategies:

- **Tick-driven** (`on_order_book_deltas`): fires on every single orderbook update. You see everything.
- **Timer-driven** (`on_interval`): fires every N minutes. You only see the world at those snapshots.

The critical thing: **timer strategies are blind between fires.** If price spikes to 0.95 and drops back to 0.50 between two 1-minute timer fires, you never know it happened. You only see the price at the moment the timer fires.

The backtest engine processes events in timestamp order:
1. Advance clock to next data timestamp (fires any due timers)
2. Process the data event (orderbook delta → exchange → callbacks)
3. Process exchange responses (fills, etc.)

So hundreds of ticks happen between timer fires. The orderbook in cache reflects all of them — `self.cache.order_book(instrument_id)` is always current. But your `on_interval` logic only runs at timer ticks.

**Questions:**
- Is 1-minute granularity enough? What signals are we missing between fires?
- Should timer strategies also implement `on_order_book_deltas` to track extremes (high/low) between intervals?
- For live trading, does the timer interval interact differently with real-time data volume?

## Price History: Nobody Gives It To You

NautilusTrader does NOT provide a "last N prices" buffer for orderbook delta subscriptions. The cache has `quote_ticks()` and `trade_ticks()` but those are empty when you're subscribed to orderbook deltas (different data type).

Every strategy that needs lookback builds its own:
```python
self._mid_history: dict[InstrumentId, deque[float]] = {}
# on each tick/interval:
self._mid_history[instrument_id].append(mid)
```

This means:
- Timer strategies sample at interval frequency (1 price per minute)
- Tick strategies sample at tick frequency (every orderbook update)
- These are VERY different datasets for the same time window

**Questions:**
- Should the base class provide a standard price history buffer?
- If yes, what does it track — mid, bid, ask, spread, all of them?
- Timer strategies with 100-period lookback = 100 minutes of history. Tick strategies with 100-period lookback = last 100 orderbook updates (could be 30 seconds). Are strategies designed with this difference in mind?
- Would it be useful to have both a tick-level buffer AND a time-sampled buffer?

## What Can a Strategy Actually See?

On each callback (`on_order_book_deltas` or `on_interval`), a strategy has access to:

**From NautilusTrader:**
- `self.cache.order_book(instrument_id)` — current orderbook (all bid/ask levels)
- `self.cache.instrument(instrument_id)` — the BinaryOption instrument object
- `self.cache.positions()` / `self.cache.orders()` — your open positions and orders
- `self.portfolio` — account balances, margin, PnL
- `self.clock.timestamp_ns()` — current time

**NOT available without extra work:**
- Historical prices (must track yourself)
- Market metadata (question text, category, end date) — not stored on the instrument object, lost after discovery
- Other markets' data (each callback is for one instrument, but you can read any instrument from cache)
- Volume/trade flow (we subscribe to orderbook deltas, not trades)

**Questions:**
- Should we attach market metadata (question, slug, end_date, category) to instruments or strategy state so strategies can use it? Example: a strategy that exits 24h before market resolution needs to know the end date.
- The `BinaryOption` instrument has `expiration_ns` — is this populated from our metadata? If so, strategies could use it for time-to-expiry logic.
- Should strategies be able to see cross-market signals? (e.g., "if any BTC market moves, check all BTC markets")

## Orderbook Depth: How Much Do We Get?

PMXT data in backtest and live Polymarket data both give us L2 orderbook. But:
- How many levels deep? Is it top-of-book only or full depth?
- Our strategies currently only look at best_bid/best_ask (top of book). Is there signal in deeper levels?
- Spread is a key signal for several strategies — but spread behavior may differ between backtest (PMXT data) and live (WebSocket)

## FOK Orders: The Only Way We Trade

All our strategies use Fill-Or-Kill limit orders. This has consequences:
- Orders either fill completely or are cancelled — no partial fills
- If the book moves between signal and submission, the order gets rejected
- In backtest, the simulated exchange matches FOK against the book. In live, the CLOB does.
- **Rejection rate matters.** A strategy might generate 100 signals but only get 20 fills because the book moved. Are we tracking this?

**Questions:**
- What's our rejection rate? Should we log it?
- Should strategies adapt order prices based on recent rejection patterns?
- Are there cases where IOC (Immediate-Or-Cancel with partial fills) would be better?

## Multi-Market Strategies

Our strategies receive `instrument_ids` at init — a list of markets to trade. Each `on_order_book_deltas` callback is for one instrument. Timer callbacks iterate over all instruments.

But some strategy ideas are inherently cross-market:
- Pairs trading (two correlated markets)
- Portfolio-level risk management (reduce exposure across all markets)
- Relative value (buy the cheap market, sell the expensive one)

**Questions:**
- Can one strategy instance meaningfully track correlations across 25 markets?
- Should cross-market strategies be a separate pattern from single-market strategies?
- How does position sizing work when you're trading many markets from one account?

## Backtest vs Live: What's Different?

Same strategy class runs in both. But the execution environment differs:

| Aspect | Backtest | Live |
|--------|----------|------|
| Clock | Simulated (replays timestamps) | Real wall clock |
| Timer fires | At data timestamps | At real time intervals |
| Order matching | Simulated exchange | Real CLOB / sandbox |
| Latency | Zero | Network round-trip |
| Data gaps | None (parquet is complete) | Possible (WebSocket drops) |
| New markets | Fixed at startup | Dynamic (MarketDiscoveryActor) |

**Questions:**
- How do we validate that backtest performance approximates live performance?
- Should strategies have a "mode" concept, or should they be truly mode-agnostic?
- Timer strategies in live: if the system lags, do timer callbacks queue up or get skipped?
